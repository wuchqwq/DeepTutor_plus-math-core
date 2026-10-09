"""v1.6.14 submission lifecycle through the real routed math/publication host."""

from __future__ import annotations

import asyncio
from contextlib import closing
import json
import sqlite3

import pytest

from deeptutor.core.stream import StreamEventType
from deeptutor.services.workspace import get_content_workspace_service
from deeptutor.services.workspace.context import workspace_context

from .recovery_support import A, B, reviewed_source
from .test_publication import (
    FORBIDDEN_ANSWER,
    assert_no_answer_leak,
    assistant_row,
    replay,
)
from .test_publication import (
    publication_host_factory as publication_host_factory,
)
from .test_routing_isolation import RoutingHost


def durable_submission_rows(host):
    with closing(sqlite3.connect(host.db)) as sql:
        return {
            "users": sql.execute(
                "SELECT id, session_id, content, metadata_json FROM messages "
                "WHERE role='user' ORDER BY id"
            ).fetchall(),
            "submissions": sql.execute(
                "SELECT * FROM turn_submissions ORDER BY client_submission_id"
            ).fetchall(),
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("with_confirmation", [False, True])
async def test_completed_lost_ack_restores_exact_math_publication_after_fresh_restart(
    publication_host_factory, with_confirmation
):
    host, generation, completions = publication_host_factory()
    # Exercise the actual title owner as well as the body/publication owner.
    del host.runtime._maybe_generate_session_title
    session_id = None
    content = A
    if with_confirmation:
        host.source = reviewed_source()
        host.scope = host.math_scope()
        session, _ = await host.submit(A)
        session_id, content = session["id"], B
    session, original = await host.start(
        content, session_id=session_id, client_submission_id="math-lost-ack"
    )
    if with_confirmation:
        card = await host.choice(original)
        assert [option["label"] for option in card["options"]] == ["Method 1", "Method 2"]
        await host.answer(original, card)
    await host.finish(original)
    accepted = host.math_contexts[-1].runtime
    user = host.user_row(accepted.accepted_user_message_id)
    assert user["content"] == accepted.accepted_user_content == content
    assert user["metadata"]["client_submission_id"] == "math-lost-ack"
    assert user["metadata"]["turn_id"] == original["id"]
    state, rows = host.state(), durable_submission_rows(host)
    assistant = assistant_row(host, original["id"])
    events = await replay(host, original)
    receipt = state["host_math_publications"][original["id"]]
    trace = assistant[2]["accepted_output"]["math_publication"]
    assert receipt["publication_id"] == trace["publication_id"]
    assert trace["basis"]["accepted_user_message_id"] == user["id"]
    assert trace["basis"]["turn_id"] == original["id"]
    assert trace["basis"]["episode_id"] == host.source.identity.episode_id
    assert (
        assistant[1]
        == receipt["content"]
        == "".join(event["content"] for event in events if event["type"] == "content")
    )
    assert (
        next(event for event in events if event["type"] == "result")["metadata"]["response"]
        == receipt["content"]
    )
    calls, completion_count = len(generation.calls), len(completions)
    same_session, same_turn = await host.start(
        content, session_id=session_id, client_submission_id="math-lost-ack"
    )
    assert (same_session["id"], same_turn["id"]) == (session["id"], original["id"])
    assert await replay(host, same_turn) == events
    assert host.state() == state and durable_submission_rows(host) == rows
    assert len(generation.calls) == calls and len(completions) == completion_count
    await host.close()

    # New objects and reviewed DI; no prior MathEpisodeBinding/context is supplied.
    fresh = RoutingHost(host.db)
    fresh.source = reviewed_source(unknown=not with_confirmation)
    fresh.scope = fresh.math_scope()
    del fresh.runtime._maybe_generate_session_title
    try:
        assert fresh.runtime is not host.runtime and fresh.coordinator is not host.coordinator
        assert fresh.store is not host.store
        recovered_session, recovered = await fresh.start(
            content, session_id=session_id, client_submission_id="math-lost-ack"
        )
        assert (recovered_session["id"], recovered["id"]) == (session["id"], original["id"])
        assert await replay(fresh, recovered) == events
        assert assistant_row(fresh, recovered["id"]) == assistant
        assert fresh.state() == state and durable_submission_rows(fresh) == rows
        assert fresh.user_row(user["id"]) == user
        assert not fresh.math_contexts and not fresh.ordinary_contexts and not fresh.references
        assert not fresh.runtime._executions
        assert len(generation.calls) == calls and len(completions) == completion_count
    finally:
        await fresh.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_status", ["failed", "cancelled", "approved_then_failed"])
async def test_same_submission_retry_associates_original_row_without_new_math_acceptance(
    publication_host_factory, monkeypatch, prior_status
):
    host, generation, completions = publication_host_factory()
    del host.runtime._maybe_generate_session_title
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause(_inputs):
        entered.set()
        await release.wait()

    if prior_status == "failed":
        generation.mode = "confident_unknown"
    elif prior_status == "cancelled":
        generation.hook = pause
    else:
        from deeptutor.runtime.stream_bus import StreamBus

        original_emit = StreamBus.emit

        async def fail_delivery(bus, event):
            if event.source == "math_turn" and event.type == StreamEventType.CONTENT:
                assert host.state()["host_math_publications"]
                raise RuntimeError(FORBIDDEN_ANSWER)
            await original_emit(bus, event)

        monkeypatch.setattr(StreamBus, "emit", fail_delivery)
    session, first = await host.start(A, client_submission_id="retry-causal-id")
    first_execution = host.runtime._executions[first["id"]]
    if prior_status == "cancelled":
        await asyncio.wait_for(entered.wait(), 15)
        assert await host.application.cancel_turn_and_wait(first["id"], command_id="cancel-first")
    assert first_execution.task is not None
    if prior_status == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first_execution.task, 20)
    else:
        await asyncio.wait_for(first_execution.task, 20)
    assert (await host.store.get_turn(first["id"]))["status"] == (
        "cancelled" if prior_status == "cancelled" else "failed"
    )
    runtime = host.math_contexts[-1].runtime
    user = host.user_row(runtime.accepted_user_message_id)
    assert user["content"] == runtime.accepted_user_content == A
    committed, original_users = host.state(), durable_submission_rows(host)["users"]
    if prior_status == "approved_then_failed":
        assert set(committed["host_math_publications"]) == {first["id"]}
    else:
        assert not committed.get("host_math_publications")
    assert_no_answer_leak(await replay(host, first), completions)
    calls, projections = len(generation.calls), len(host.projections)
    generation.previous = generation.raw_candidates[-1] if generation.raw_candidates else None
    generation.mode, generation.hook = "replay", None
    retry_session, retry = await host.start(A, client_submission_id="retry-causal-id")
    execution = host.runtime._executions[retry["id"]]
    assert retry_session["id"] == session["id"] and retry["id"] != first["id"]
    await host.finish(retry, status="failed")
    retry_runtime = host.math_contexts[-1].runtime
    assert retry_runtime.turn_id == retry["id"]
    assert retry_runtime.accepted_user_message_id is None
    assert (
        retry_runtime.accepted_user_content is None and retry_runtime.client_submission_id is None
    )
    assert not host.ordinary_contexts
    assert len(generation.calls) == calls and len(host.projections) == projections
    assert host.state() == committed and host.user_row(user["id"]) == user
    assert durable_submission_rows(host)["users"] == original_users
    assert (await host.store.submission_turn("retry-causal-id"))["id"] == retry["id"]
    assert execution.capability == "math_turn"
    assert execution.payload["regenerated_from_message_id"] == user["id"]
    assert execution.payload["superseded_turn_id"] == first["id"]
    assert execution.payload["persist_user_message"] is False
    events = await replay(host, retry)
    session_event = next(event for event in events if event["type"] == "session")
    assert session_event["metadata"]["regenerated_from_message_id"] == user["id"]
    assert (
        next(event for event in events if event["type"] == "done")["metadata"]["user_message_id"]
        == user["id"]
    )
    assert_no_answer_leak(events, completions[-1:])
    _, body, metadata, parent = assistant_row(host, retry["id"])
    assert body == "" and parent == user["id"] and "accepted_output" not in metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["content", "config", "conversation", "workspace"])
async def test_submission_identity_abuse_fails_before_math_runtime(
    publication_host_factory, changed
):
    host, generation, _ = publication_host_factory()
    session, original = await host.submit(A, client_submission_id="reserved-math-request")
    state, rows = host.state(), durable_submission_rows(host)
    math_calls, generation_calls = len(host.math_contexts), len(generation.calls)
    if changed == "workspace":
        workspace = get_content_workspace_service().create_workspace("Submission isolation control")
        with workspace_context(workspace["workspace_id"]):
            with pytest.raises(RuntimeError, match="different request or workspace"):
                await host.start(A, client_submission_id="reserved-math-request")
    else:
        overrides = {"client_submission_id": "reserved-math-request"}
        content = A
        if changed == "content":
            content = A + " altered"
        elif changed == "config":
            overrides["config"] = {"temperature": 0.73}
        else:
            other = await host.store.ensure_session("unrelated-explicit-conversation")
            overrides["session_id"] = other["id"]
        with pytest.raises(RuntimeError, match="another conversation|different request"):
            await host.start(content, **overrides)
    assert host.state() == state and durable_submission_rows(host) == rows
    assert len(host.math_contexts) == math_calls and len(generation.calls) == generation_calls
    assert (await host.store.submission_turn("reserved-math-request"))["id"] == original["id"]
    assert (await host.store.get_turn(original["id"]))["session_id"] == session["id"]


@pytest.mark.asyncio
async def test_regenerate_is_new_execution_not_lost_ack_replay(publication_host_factory):
    host, generation, completions = publication_host_factory(verified=True)
    generation.mode = "result"
    session, original = await host.submit(A, client_submission_id="completed-submission")
    state, rows = host.state(), durable_submission_rows(host)
    _, same = await host.start(A, client_submission_id="completed-submission")
    assert same["id"] == original["id"]
    generation.previous = generation.raw_candidates[-1]
    generation.mode = "replay"
    _, regenerated = await host.application.regenerate_last_turn(session["id"])
    assert regenerated["id"] != original["id"]
    await host.finish(regenerated, status="failed")
    assert host.math_contexts[-1].runtime.accepted_user_message_id is None
    assert len(generation.calls) == 1 and host.state() == state
    assert durable_submission_rows(host) == rows
    assert_no_answer_leak(await replay(host, regenerated), completions[-1:])
    assert regenerated["id"] not in state["host_math_publications"]
    assert "accepted_output" not in assistant_row(host, regenerated["id"])[2]
    assert not host.ordinary_contexts
