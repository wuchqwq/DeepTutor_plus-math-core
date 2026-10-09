"""Actual accepted/routed math turns use native generation and host publication."""

from __future__ import annotations

import asyncio
from contextlib import closing
from dataclasses import replace
import hashlib
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from deeptutor.capabilities.math_turn.output import ACKNOWLEDGEMENT
from deeptutor.core.stream import StreamEventType
from deeptutor.math_semantic.support import resolve_math_content_support
from deeptutor.services.session._turn_runtime_shared import _repair_chinese_emphasis_for_persistence
from deeptutor.services.session.math_semantic_persistence import sqlite_episode_mutation
from deeptutor.services.session.turns.title_service import SessionTitleService

from .recovery_support import A
from .test_routing_isolation import RoutingHost

FORBIDDEN_ANSWER = "CONFIDENT_FINAL_ANSWER: Q = 999"


class Generation:
    """Replace only provider I/O below the real scoped completion factory."""

    def __init__(self):
        self.mode = "orientation"
        self.calls, self.raw_candidates = [], []
        self.hook = None
        self.previous = None
        self.foreign_grant = None

    async def __call__(self, config, _provider_spec, *, prompt, **kwargs):
        inputs = json.loads(prompt)
        self.calls.append({"inputs": inputs, "config": config, "kwargs": kwargs})
        if self.hook:
            await self.hook(inputs)
        orientation = [
            offer["grant_id"]
            for offer in inputs["offers"]
            if offer["grant"]["act_kind"] == "orientation"
        ][:1]
        result = [
            offer["grant_id"]
            for offer in inputs["offers"]
            if offer["grant"]["act_kind"] == "result"
        ][:1]
        candidate = {"authority_basis": inputs["authority_basis"], "grant_ids": orientation}
        if self.mode == "result":
            assert result, "positive control requires actual Core result authority"
            candidate["grant_ids"] = result
        elif self.mode == "operation":
            candidate["grant_ids"] = [
                offer["grant_id"]
                for offer in inputs["offers"]
                if offer["grant"]["act_kind"] == "chosen_operation"
            ][:1]
            assert candidate["grant_ids"], "positive control requires real operation evidence"
        elif self.mode == "free_prose":
            return FORBIDDEN_ANSWER
        elif self.mode == "orientation_with_text":
            candidate["text"] = FORBIDDEN_ANSWER
        elif self.mode == "confident_unknown":
            candidate.update(text=FORBIDDEN_ANSWER, verification_status="VERIFIED", confidence=1)
        elif self.mode == "forged_result":
            candidate["grant_ids"] = ["f" * 64]
        elif self.mode == "foreign_result":
            assert self.foreign_grant is not None
            candidate["grant_ids"] = [
                hashlib.sha256(
                    json.dumps(self.foreign_grant, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
            ]
        elif self.mode == "foreign_basis":
            candidate["authority_basis"] = "foreign-episode-authority"
        elif self.mode == "replay":
            assert self.previous is not None
            return self.previous
        elif self.mode == "duplicate_field":
            return json.dumps(candidate)[:-1] + ', "grant_ids": []}'
        elif self.mode == "exception":
            exc = RuntimeError(FORBIDDEN_ANSWER)
            exc.error_code = FORBIDDEN_ANSWER
            raise exc
        value = json.dumps(candidate)
        self.raw_candidates.append(value)
        return value


@pytest_asyncio.fixture
async def publication_host_factory(tmp_path, monkeypatch):
    hosts = []
    generation = Generation()
    completions = []

    async def capture(event):
        completions.append(event)

    monkeypatch.setattr("deeptutor.services.skill.runtime.skill_manifest", lambda: "")
    monkeypatch.setattr("deeptutor.services.llm.factory._complete_with_resolved_config", generation)
    monkeypatch.setattr(
        "deeptutor.runtime.orchestrator.get_event_bus", lambda: SimpleNamespace(publish=capture)
    )

    def create(*, verified=False):
        host = RoutingHost(tmp_path / f"publication-{len(hosts)}.db", unknown=True)
        if verified:
            # This is trusted reviewed authored content, not a provider's
            # verification claim. Core consumes it under its unchanged contract.
            host.source = replace(
                host.source,
                authored=replace(
                    host.source.authored,
                    artifacts=tuple(
                        replace(
                            artifact,
                            verification_status="verified",
                            verification_scope="independently_reviewed_literal_fixture",
                        )
                        if artifact.statement in {A, "Q in [1,9]"}
                        else artifact
                        for artifact in host.source.authored.artifacts
                    ),
                ),
            )
        host.scope = host.math_scope()
        hosts.append(host)
        return host, generation, completions

    yield create
    for host in reversed(hosts):
        await host.close()


async def replay(host, turn):
    return [event async for event in host.runtime.subscribe_turn(turn["id"])]


def assistant_row(host, turn_id):
    with closing(sqlite3.connect(host.db)) as connection:
        row = connection.execute(
            "SELECT m.id, m.content, m.metadata_json, m.parent_message_id FROM messages m "
            "JOIN turns t ON t.assistant_message_id=m.id WHERE t.id=? AND m.role='assistant'",
            (turn_id,),
        ).fetchone()
    assert row is not None
    return row[0], row[1], json.loads(row[2]), row[3]


def assert_no_answer_leak(events, completions):
    assert not any(event["type"] in {"content", "result"} for event in events)
    assert FORBIDDEN_ANSWER not in json.dumps(events, default=str)
    assert all(not event.agent_output for event in completions)
    assert FORBIDDEN_ANSWER not in json.dumps(
        [event.metadata for event in completions], default=str
    )
    assert not any("alignment" in event.get("metadata", {}) for event in events)


@pytest.mark.asyncio
async def test_buffered_generation_acceptance_precedes_live_and_durable_publication(
    publication_host_factory, monkeypatch
):
    host, generation, completions = publication_host_factory(verified=True)
    generation.mode = "result"
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause(_inputs):
        entered.set()
        await release.wait()

    generation.hook = pause
    observed = []
    original = host.runtime._publish_live_event

    async def before_live(execution, event):
        if event.type == StreamEventType.CONTENT:
            entry = host.state()["host_math_publications"][execution.turn_id]
            assert entry["content"] == event.content
            assert json.loads(entry["metadata_json"]) == event.metadata
            observed.append(entry)
        return await original(execution, event)

    monkeypatch.setattr(host.runtime, "_publish_live_event", before_live)
    _, turn = await host.start(A, client_submission_id="publication-causal-id")
    await asyncio.wait_for(entered.wait(), 15)
    context = host.math_contexts[-1]
    row = host.user_row(context.runtime.accepted_user_message_id)
    assert row["content"] == context.runtime.accepted_user_content == A
    assert row["metadata"]["host_capability_binding"]["binding"]["capability"] == "math_turn"
    assert context.runtime.client_submission_id == "publication-causal-id"
    assert "host_math_publications" not in host.state()
    assert not observed and not context.capability_output.accepted_output
    assert not any(
        event["type"] == "content" for event in host.runtime._executions[turn["id"]].events
    )
    release.set()
    await host.finish(turn)
    events = await replay(host, turn)
    content = "".join(event["content"] for event in events if event["type"] == "content")
    assert content == ACKNOWLEDGEMENT + "\n\n" + A
    result = next(event["metadata"] for event in events if event["type"] == "result")
    trace = result["math_publication"]
    assert result["response"] == content
    assert trace["basis"]["turn_id"] == turn["id"]
    assert trace["basis"]["accepted_user_message_id"] == row["id"]
    assert trace["basis"]["episode_id"] == host.source.identity.episode_id
    assert trace["content_digest"] == hashlib.sha256(content.encode()).hexdigest()
    receipt = context.capability_output.accepted_output
    assert len(observed) == 1 and observed[0]["publication_id"] == receipt.publication_id
    _, stored, metadata, parent = assistant_row(host, turn["id"])
    assert stored == content and parent == row["id"]
    assert metadata["accepted_output"]["math_publication"] == trace
    assert completions[-1].agent_output == content
    assert completions[-1].metadata["math_publication"] == trace
    assert "math" not in result and "alignment" not in result
    assert len(generation.calls) == 1 and host.result()["verified_grounded_refs"]


@pytest.mark.asyncio
async def test_orientation_only_publishes_no_task_mathematics(publication_host_factory):
    host, generation, _ = publication_host_factory()
    _, turn = await host.submit(A)
    events = await replay(host, turn)
    assert host.result()["verification_status"] == "UNKNOWN"
    assert all(
        offer["grant"]["act_kind"] == "orientation"
        for offer in generation.calls[-1]["inputs"]["offers"]
    )
    assert assistant_row(host, turn["id"])[1] == ACKNOWLEDGEMENT
    assert all(A not in event["content"] for event in events)
    assert all("claims" not in event.get("metadata", {}) for event in events)


@pytest.mark.asyncio
async def test_qualified_premise_publishes_executable_operation_and_replays_exact_bytes(
    publication_host_factory,
):
    host, generation, _ = publication_host_factory()
    host.source = replace(
        host.source,
        authored=replace(
            host.source.authored,
            artifacts=tuple(
                replace(a, verification_status="qualified", verification_scope="AI-reviewed")
                if a.statement == A
                else a
                for a in host.source.authored.artifacts
            ),
        ),
    )
    generation.mode = "operation"
    _, turn = await host.submit(A)
    body = assistant_row(host, turn["id"])[1]
    assert "Try this next step:" in body and "Expand " in body
    assert not host.result()["verified_grounded_refs"]
    assert not any(
        o["grant"]["act_kind"] == "result" for o in generation.calls[-1]["inputs"]["offers"]
    )
    before = host.state()
    first, second = await replay(host, turn), await replay(host, turn)
    assert first == second and host.state() == before
    assert "".join(e["content"] for e in first if e["type"] == "content") == body
    assert len(generation.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("verified", [False, True])
@pytest.mark.parametrize(
    "mode",
    [
        "free_prose",
        "orientation_with_text",
        "confident_unknown",
        "forged_result",
        "duplicate_field",
        "exception",
    ],
)
async def test_unknown_cannot_upgrade_or_leak_through_candidates_or_errors(
    publication_host_factory, mode, verified
):
    host, generation, completions = publication_host_factory(verified=verified)
    host.mode = "unsupported"
    generation.mode = mode
    _, turn = await host.start(A)
    await host.finish(turn, status="failed")
    assert host.result()["verification_status"] == "UNKNOWN"
    assert not host.result()["verified_grounded_refs"]
    assert "host_math_publications" not in host.state()
    assert not host.ordinary_contexts
    assert_no_answer_leak(await replay(host, turn), completions)
    assert assistant_row(host, turn["id"])[1] == ""


@pytest.mark.asyncio
async def test_verified_scope_is_exact_literal_not_free_prose_or_other_results(
    publication_host_factory,
):
    host, generation, completions = publication_host_factory(verified=True)
    generation.mode = "result"
    session, turn = await host.submit(A)
    authorized = generation.calls[-1]["inputs"]["offers"]
    results = [offer for offer in authorized if offer["grant"]["act_kind"] == "result"]
    assert len(results) == 1 and results[0]["text"] == A
    assert assistant_row(host, turn["id"])[1] == ACKNOWLEDGEMENT + "\n\n" + A
    assert "Q in [1,9]" not in assistant_row(host, turn["id"])[1]
    # A resolver-supported verified result is still outside the current
    # accepted turn's grounded authority, even if its digest is genuine.
    other = next(a for a in host.source.authored.artifacts if a.statement == "Q in [1,9]")
    assert other.verification_status == "verified"
    generation.foreign_grant = next(
        value.to_dict()
        for value in resolve_math_content_support(host.source.authored, (other.artifact_id,))
        if value.act_kind == "result"
    )
    generation.mode = "foreign_result"
    _, failed = await host.start(A, session_id=session["id"])
    await host.finish(failed, status="failed")
    assert any(
        offer["grant"]["act_kind"] == "result" for offer in generation.calls[-1]["inputs"]["offers"]
    )
    assert_no_answer_leak(await replay(host, failed), completions[-1:])


@pytest.mark.asyncio
async def test_canonical_granted_bytes_are_not_changed_by_persistence_formatter(
    publication_host_factory,
    monkeypatch,
):
    literal = "**“已记录”**啊"
    assert _repair_chinese_emphasis_for_persistence(literal, "zh") != literal
    # Test-only reviewed display copy exposes the existing formatter gap;
    # mathematical content/grants remain the actual native A fixture.
    monkeypatch.setattr("deeptutor.capabilities.math_turn.output.ACKNOWLEDGEMENT", literal)
    host, generation, _ = publication_host_factory(verified=True)
    generation.mode = "result"
    _, turn = await host.submit(A, language="zh")
    events = await replay(host, turn)
    body = literal + "\n\n" + A
    assert assistant_row(host, turn["id"])[1] == body
    assert "".join(event["content"] for event in events if event["type"] == "content") == body
    trace = next(
        event["metadata"]["math_publication"] for event in events if event["type"] == "content"
    )
    assert trace["content_digest"] == hashlib.sha256(body.encode()).hexdigest()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["new_accepted_turn", "new_episode", "revision_during_generation"]
)
async def test_stale_or_foreign_authority_cannot_authorize_current_turn(
    publication_host_factory, change
):
    host, generation, completions = publication_host_factory(verified=True)
    generation.mode = "result"
    session, original = await host.submit(A)
    old_receipt = host.state()["host_math_publications"][original["id"]]
    generation.previous = generation.raw_candidates[-1]
    if change == "new_episode":
        host.source = replace(
            host.source,
            identity=replace(host.source.identity, episode_id="foreign-reviewed-episode"),
            authored=replace(
                host.source.authored,
                workspace=replace(
                    host.source.authored.workspace, workspace_id="foreign-reviewed-episode"
                ),
            ),
        )
        host.scope = host.math_scope()
    elif change == "revision_during_generation":

        async def advance(_inputs):
            context = host.math_contexts[-1]
            authority = sqlite_episode_mutation(
                context.runtime, session_id=context.session_id, binding=host.source
            )
            await authority(
                lambda state: state.append(
                    expected_revision=state.snapshot().workspace.revision, status="partial"
                )
            )

        generation.hook = advance
    generation.mode = "result" if change == "revision_during_generation" else "replay"
    _, failed = await host.start(A, session_id=session["id"])
    await host.finish(failed, status="failed")
    assert failed["id"] not in host.state().get("host_math_publications", {})
    assert_no_answer_leak(await replay(host, failed), completions[-1:])
    old_episode = json.loads(old_receipt["metadata_json"])["math_publication"]["basis"][
        "episode_id"
    ]
    assert host.episodes()[old_episode]["host_math_publications"][original["id"]] == old_receipt


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_port", "rollback", "ownership_lost"])
async def test_publication_commit_failure_has_no_unconstrained_fallback(
    publication_host_factory, failure
):
    host, generation, completions = publication_host_factory(verified=True)
    generation.mode = "result"

    async def fail(_inputs):
        context = host.math_contexts[-1]
        if failure == "missing_port":
            context.runtime.run_durable_turn_mutation = None
        elif failure == "ownership_lost":
            assert await host.coordinator.release_turn(context.runtime.turn_lease)
        else:
            original = context.runtime.run_durable_turn_mutation

            async def reject(mutation, **kwargs):
                def after_write(sql):
                    mutation(sql)
                    rows = sql(
                        "SELECT payload_json FROM math_semantic_episodes WHERE episode_id=?",
                        (host.source.identity.episode_id,),
                    )
                    assert (
                        context.runtime.turn_id in json.loads(rows[0][0])["host_math_publications"]
                    )
                    raise RuntimeError(FORBIDDEN_ANSWER)

                return await original(after_write, **kwargs)

            context.runtime.run_durable_turn_mutation = reject

    generation.hook = fail
    _, turn = await host.start(A)
    await host.finish(turn, status="failed")
    assert "host_math_publications" not in host.state()
    assert not host.ordinary_contexts
    assert_no_answer_leak(await replay(host, turn), completions)


@pytest.mark.asyncio
async def test_regenerate_and_explicit_retry_cannot_reuse_old_authority(publication_host_factory):
    host, generation, completions = publication_host_factory(verified=True)
    generation.mode = "result"
    session, original = await host.submit(A)
    committed = host.state()
    generation.previous = generation.raw_candidates[-1]
    _, regenerate = await host.application.regenerate_last_turn(session["id"])
    await host.finish(regenerate, status="failed")
    assert len(generation.calls) == 1 and host.state() == committed
    assert host.math_contexts[-1].runtime.accepted_user_message_id is None
    assert_no_answer_leak(await replay(host, regenerate), completions[-1:])
    generation.mode = "replay"
    _, retry = await host.start(A, session_id=session["id"])
    await host.finish(retry, status="failed")
    assert retry["id"] not in host.state()["host_math_publications"]
    assert_no_answer_leak(await replay(host, retry), completions[-1:])
    generation.mode = "orientation"
    _, next_turn = await host.submit(A, session_id=session["id"])
    assert assistant_row(host, next_turn["id"])[1] == ACKNOWLEDGEMENT
    assert set(host.state()["host_math_publications"]) == {original["id"], next_turn["id"]}


@pytest.mark.asyncio
async def test_stream_publication_failure_after_approval_never_falls_back(
    publication_host_factory, monkeypatch
):
    from deeptutor.runtime.stream_bus import StreamBus

    host, generation, completions = publication_host_factory(verified=True)
    generation.mode = "result"
    original = StreamBus.emit

    async def fail_delivery(bus, event):
        if event.source == "math_turn" and event.type == StreamEventType.CONTENT:
            assert host.state()["host_math_publications"]
            raise RuntimeError(FORBIDDEN_ANSWER)
        await original(bus, event)

    monkeypatch.setattr(StreamBus, "emit", fail_delivery)
    session, turn = await host.start(A)
    await host.finish(turn, status="failed")
    assert set(host.state()["host_math_publications"]) == {turn["id"]}
    assert not host.ordinary_contexts
    assert_no_answer_leak(await replay(host, turn), completions)
    assert assistant_row(host, turn["id"])[1] == ""
    _, retry = await host.application.regenerate_last_turn(session["id"])
    await host.finish(retry, status="failed")
    assert len(generation.calls) == 1
    assert set(host.state()["host_math_publications"]) == {turn["id"]}
    assert_no_answer_leak(await replay(host, retry), completions[-1:])


@pytest.mark.asyncio
async def test_durable_event_replay_is_read_only_and_preserves_approved_identity(
    publication_host_factory,
):
    host, generation, _ = publication_host_factory(verified=True)
    generation.mode = "result"
    _, turn = await host.submit(A)
    before = host.state()
    first = await replay(host, turn)
    second = await replay(host, turn)
    assert first == second and host.state() == before and len(generation.calls) == 1
    content = next(event for event in first if event["type"] == "content")
    result = next(event for event in first if event["type"] == "result")
    assert content["metadata"]["math_publication"] == result["metadata"]["math_publication"]


@pytest.mark.asyncio
async def test_non_math_keeps_existing_publication_even_after_math_response(
    publication_host_factory,
):
    host, generation, completions = publication_host_factory(verified=True)
    generation.mode = "result"
    session, _ = await host.submit(A)
    committed = host.state()
    host.scope = None
    _, ordinary = await host.submit(A, session_id=session["id"])
    context = host.ordinary_contexts[-1]
    assert context.capability_output.accepted_output is None and context.extension_state == {}
    assert host.state() == committed and len(generation.calls) == 1
    assert assistant_row(host, ordinary["id"])[1] == "ordinary"
    assert completions[-1].agent_output == "Ordinary capability completed."
    assert "math_publication" not in completions[-1].metadata
    assert not any(
        "math_publication" in event["metadata"] for event in await replay(host, ordinary)
    )


class TitleProvider:
    """Deterministic provider I/O under the actual title stream factory."""

    def __init__(self, text, failure=False):
        self.text, self.failure, self.calls = text, failure, []

    async def chat_stream_with_retry(self, **kwargs):
        self.calls.append(kwargs["messages"])
        if self.failure:
            raise RuntimeError("test-only title provider failure")
        await kwargs["on_content_delta"](self.text)
        return SimpleNamespace(
            finish_reason="stop", content=self.text, reasoning_content="", usage={}
        )

    async def aclose(self):
        pass


def enable_real_titles(host, monkeypatch, *, text, failure=False):
    # The shared body-publication fixture normally isolates title generation.
    # Remove that instance override: these controls run the real runtime MRO.
    del host.runtime._maybe_generate_session_title
    assert (
        host.runtime._maybe_generate_session_title.__func__
        is SessionTitleService._maybe_generate_session_title
    )
    provider = TitleProvider(text, failure)
    monkeypatch.setattr(
        "deeptutor.services.llm.factory.get_runtime_provider", lambda _cfg: provider
    )
    writes = AsyncMock(wraps=host.store.update_session_title)
    monkeypatch.setattr(host.store, "update_session_title", writes)
    return provider, writes


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["malicious", "empty", "failure"])
async def test_routed_math_skips_real_title_owner_model_fallback_write_and_event(
    publication_host_factory, monkeypatch, mode
):
    host, generation, completions = publication_host_factory()
    provider, writes = enable_real_titles(
        host,
        monkeypatch,
        text="" if mode == "empty" else FORBIDDEN_ANSWER,
        failure=mode == "failure",
    )
    # Request says chat; only trusted routing selects math. Raw content A
    # would produce a non-neutral fallback title if the title owner ran it.
    session, turn = await host.submit(A, capability="chat")
    saved_turn = await host.store.get_turn(turn["id"])
    saved_session = await host.store.get_session(session["id"])
    context = host.math_contexts[-1]
    row = host.user_row(context.runtime.accepted_user_message_id)
    assert saved_turn["capability"] == "chat" and context.active_capability == "math_turn"
    assert row["content"] == context.runtime.accepted_user_content == A
    assert row["metadata"]["host_capability_binding"]["binding"]["capability"] == "math_turn"
    assert host.result()["verification_status"] == "UNKNOWN"
    assert all(grant["act_kind"] == "orientation" for grant in host.result()["authority"])
    assert saved_session["title"] == session["title"] == "New conversation"
    assert provider.calls == []
    writes.assert_not_awaited()
    events = await replay(host, turn)
    assert not any(
        event["type"] == "session_meta" and "title" in event["metadata"] for event in events
    )
    assert FORBIDDEN_ANSWER not in json.dumps(events)
    # The same turn still completes the existing protected math body path.
    _, body, metadata, parent = assistant_row(host, turn["id"])
    assert body == ACKNOWLEDGEMENT and parent == row["id"]
    receipt = host.state()["host_math_publications"][turn["id"]]
    trace = json.loads(receipt["metadata_json"])["math_publication"]
    assert receipt["content"] == body and metadata["accepted_output"]["math_publication"] == trace
    assert trace["basis"]["accepted_user_message_id"] == row["id"]
    assert trace["basis"]["turn_id"] == turn["id"]
    assert completions[-1].agent_output == body and len(generation.calls) == 1
    assert any(event["type"] == "done" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["chat", "immersive_reading", "deep_research"])
@pytest.mark.parametrize("mode", ["generated", "empty", "failure"])
async def test_ordinary_real_title_owner_keeps_generation_fallback_and_publication(
    publication_host_factory, monkeypatch, capability, mode
):
    host, generation, _ = publication_host_factory()
    host.scope = None
    provider, writes = enable_real_titles(
        host,
        monkeypatch,
        text="" if mode == "empty" else "Conversation overview",
        failure=mode == "failure",
    )
    config = {"mode": "notes", "depth": "quick"} if capability == "deep_research" else {}
    session, turn = await host.submit(A, capability=capability, config=config)
    context = host.ordinary_contexts[-1]
    assert context.active_capability == capability and not host.math_contexts
    expected = "Conversation overview" if mode == "generated" else A
    assert (await host.store.get_session(session["id"]))["title"] == expected
    assert len(provider.calls) == 1 and A in provider.calls[0][1]["content"]
    writes.assert_awaited_once_with(session["id"], expected)
    assert generation.calls == [] and host.episodes() == {}
    events = await replay(host, turn)
    title = next(event for event in events if event["type"] == "session_meta")
    assert title["content"] == title["metadata"]["title"] == expected
    assert title["seq"] > next(event["seq"] for event in events if event["type"] == "done")
    assert assistant_row(host, turn["id"])[1] == "ordinary"
