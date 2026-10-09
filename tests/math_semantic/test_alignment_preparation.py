"""Outside-transaction real tools, exact input adoption and native fences."""

import asyncio
from dataclasses import replace
import json
import sqlite3
from threading import Event
import time

import pytest

from deeptutor.math_semantic.alignment import materialize_alignment
from deeptutor.math_semantic.state import MathMutation
from deeptutor.math_semantic.tools import MathToolRegistry
from deeptutor.services.session.math_semantic_persistence import sqlite_episode_mutation

from .test_publication import assert_no_answer_leak
from .test_publication import publication_host_factory as publication_host_factory
from .test_student_step_evidence import TRUE, proposal, source, state_for

ARGS = {
    "expected_revision": 1,
    "provider_id": "proposal-only",
    "config_digest": "offline",
    "check_steps": True,
}


@pytest.fixture
def prepared_step():
    state = state_for(source(), TRUE)
    prepared = materialize_alignment(
        state.submission,
        state.snapshot(),
        proposal(TRUE),
        **{k: v for k, v in ARGS.items() if k != "expected_revision"},
    )
    return state, prepared


def test_exact_prepared_replay_does_not_recompute(prepared_step, monkeypatch):
    state, prepared = prepared_step
    result = state.align(proposal(TRUE), prepared=prepared, **ARGS)
    before = state.serialize()

    def unexpected(*args, **kwargs):
        raise AssertionError("Exact replay must not compute alignment or execute tools")

    monkeypatch.setattr("deeptutor.math_semantic.state.materialize_alignment", unexpected)
    monkeypatch.setattr(MathToolRegistry, "call", unexpected)
    assert state.replay_alignment(proposal(TRUE), **ARGS) == result
    assert state.align(proposal(TRUE), **ARGS) == result
    assert state.serialize() == before


@pytest.mark.parametrize(
    "change", ["submission", "proposal", "provider", "config", "snapshot", "receipt", "revision"]
)
def test_prepared_input_or_receipt_change_is_rejected_without_append(prepared_step, change):
    state, prepared = prepared_step
    args = dict(ARGS)
    proposed = proposal(TRUE)
    if change == "submission":
        foreign = replace(state.submission, session_id="foreign")
        state = MathMutation(state.source, foreign, (foreign,), state.serialize())
    elif change == "proposal":
        proposed = proposal("(x-y)^2=x^2-x*y+y^2")
    elif change in {"provider", "config"}:
        args["provider_id" if change == "provider" else "config_digest"] = "changed"
    elif change == "snapshot":
        prepared = replace(
            prepared,
            input_snapshot=replace(
                prepared.input_snapshot,
                workspace=replace(prepared.input_snapshot.workspace, status="changed"),
            ),
        )
    elif change == "receipt":
        prepared = replace(
            prepared,
            evidence=(
                replace(prepared.evidence[0], output_summary="altered"),
                *prepared.evidence[1:],
            ),
        )
    else:
        prepared = replace(
            prepared, alignment=replace(prepared.alignment, output_workspace_revision=99)
        )
    before = state.serialize()
    with pytest.raises(ValueError, match="prepared alignment"):
        state.align(proposed, prepared=prepared, **args)
    assert state.serialize() == before


@pytest.fixture
def paused_real_step(monkeypatch):
    entered, resume = Event(), Event()
    original = MathToolRegistry.call

    def paused(self, name, **kwargs):
        if not entered.is_set() and any(
            str(ref).startswith("student_claim_") for ref in kwargs.get("input_refs", ())
        ):
            entered.set()
            assert resume.wait(10), "Controlled real tool was not resumed"
        return original(self, name, **kwargs)

    monkeypatch.setattr(MathToolRegistry, "call", paused)
    yield entered, resume
    resume.set()


@pytest.mark.asyncio
async def test_real_alignment_preparation_allows_second_session_sqlite_write(
    publication_host_factory, paused_real_step
):
    host, _, _ = publication_host_factory()
    host.source = source()
    host.scope = host.math_scope()
    other = await host.store.create_session("other session")
    entered, resume = paused_real_step
    _, turn = await host.start(TRUE)
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        assert host.state()["alignments"] == {}

        def write():
            started = time.monotonic()
            with sqlite3.connect(host.db, timeout=0.3) as connection:
                connection.execute(
                    "UPDATE sessions SET title=? WHERE id=?",
                    ("while real alignment tools prepare", other["id"]),
                )
            return time.monotonic() - started

        elapsed = await asyncio.wait_for(asyncio.to_thread(write), 1)
        assert elapsed < 1
        assert not host.state()["alignments"]
    finally:
        resume.set()
    await host.finish(turn)
    assert any(
        e["tool_name"] == "expand" and e["status"] == "succeeded"
        for e in host.result()["alignment"]["math_evidence"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "snapshot", "ownership", "accepted"])
async def test_preparation_drift_is_atomically_rejected(
    publication_host_factory, paused_real_step, change
):
    host, generation, completions = publication_host_factory()
    host.source = source()
    host.scope = host.math_scope()
    entered, resume = paused_real_step
    _, turn = await host.start(TRUE)
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        context = host.math_contexts[-1]
        if change == "revision":
            authority = sqlite_episode_mutation(
                context.runtime, session_id=context.session_id, binding=host.source
            )
            await authority(
                lambda state: state.append(
                    expected_revision=state.snapshot().workspace.revision, status="changed"
                )
            )
        elif change == "ownership":
            assert await host.coordinator.release_turn(context.runtime.turn_lease)
        else:

            def mutate(sql):
                if change == "accepted":
                    row = sql(
                        "SELECT metadata_json FROM messages WHERE id=?",
                        (context.runtime.accepted_user_message_id,),
                    )[0]
                    metadata = json.loads(row[0])
                    metadata.pop("host_capability_binding")
                    sql(
                        "UPDATE messages SET metadata_json=? WHERE id=?",
                        (json.dumps(metadata), context.runtime.accepted_user_message_id),
                    )
                else:
                    row = sql(
                        "SELECT payload_json FROM math_semantic_episodes WHERE episode_id=?",
                        (host.source.identity.episode_id,),
                    )[0]
                    state = json.loads(row[0])
                    state["snapshots"][str(state["head"])]["workspace"]["status"] = (
                        "same-revision scope drift"
                    )
                    sql(
                        "UPDATE math_semantic_episodes SET payload_json=? WHERE episode_id=?",
                        (json.dumps(state), host.source.identity.episode_id),
                    )

            await context.runtime.run_durable_turn_mutation(mutate)
        before = host.state()
        assert not before["alignments"]
    finally:
        resume.set()
    await host.finish(turn, status="failed")
    assert host.state() == before
    assert not generation.calls and "host_math_publications" not in host.state()
    assert_no_answer_leak(await host.store.get_turn_events(turn["id"]), completions)
