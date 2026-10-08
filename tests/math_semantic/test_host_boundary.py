"""Real accepted submissions reach math commits through the audited host port."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
import json
from pathlib import Path
import sqlite3
from threading import Event
from typing import Any

import pytest
import pytest_asyncio

from deeptutor.core.capability_protocol import CapabilityManifest, StreamBusProtocol, TurnCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.math_semantic.accepted import EpisodeIdentity
from deeptutor.math_semantic.claims import ResponseAlignment
from deeptutor.math_semantic.codec import _decode
from deeptutor.math_semantic.proposals import AlignmentProposal
from deeptutor.math_semantic.refs import LearnerRef, QuestionRef
from deeptutor.math_semantic.state import (
    MathMutation,
    ReviewedSource,
    confirm_method,
    run_math_operation,
)
from deeptutor.math_semantic.workspace import _snapshot_from
from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.turn_engine import TurnEngine
from deeptutor.services.session.math_semantic_persistence import sqlite_math_mutation
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager

RAW = "  Q=3-2*x*y\n"
QUOTE = "Q=3-2*x*y"


@dataclass
class Host:
    runtime: TurnRuntimeManager
    store: SQLiteSessionStore
    source: ReviewedSource
    contexts: list[UnifiedContext]
    action: Callable[[UnifiedContext], Awaitable[None]] | None = None
    finished: list[str] = field(default_factory=list)

    async def prefix(self, context: UnifiedContext) -> tuple[int, ...]:
        # This fixture supplies the complete episode prefix explicitly. There
        # is no product session-to-episode resolver or routing here.
        return tuple(
            row["id"]
            for row in await self.store.get_messages(context.session_id)
            if row["role"] == "user"
        )

    async def authority(self, context: UnifiedContext):
        return sqlite_math_mutation(
            context.runtime,
            session_id=context.session_id,
            source=self.source,
            accepted_prefix=await self.prefix(context),
        )

    def align(self, state: MathMutation, quote: str = QUOTE) -> ResponseAlignment:
        target = next(item for item in state.snapshot().artifacts if item.statement == quote)
        proposal = AlignmentProposal.from_value(
            {
                "claims": [
                    {
                        "evidence": {"quote": quote},
                        "candidate_artifact_refs": [target.artifact_id],
                    }
                ]
            }
        )
        return state.align(
            proposal,
            expected_revision=state.snapshot().workspace.revision,
            provider_id="registered-test-proposal",
            config_digest="frozen-test-configuration",
        )


@pytest_asyncio.fixture
async def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Host]:
    frozen = json.loads(
        Path(__file__).with_name("fixtures").joinpath("oracle.json").read_text(encoding="utf-8")
    )
    authored = _snapshot_from(json.dumps(frozen["snapshots"]["ca02"]))
    # The explicit reviewed episode namespace differs from question/session
    # identity. Its supplied canonical workspace belongs to the same episode.
    authored = replace(
        authored, workspace=replace(authored.workspace, workspace_id="math-test-episode")
    )
    source = ReviewedSource(
        EpisodeIdentity(
            "math-test-episode",
            LearnerRef("test-space", "test-learner"),
            QuestionRef(authored.problem_model.problem_id, authored.problem_model.revision),
        ),
        authored,
    )
    contexts: list[UnifiedContext] = []

    class RegisteredMathProbe(TurnCapability):
        manifest = CapabilityManifest(
            name="math_semantic_test", description="Test-only native mathematical mutation"
        )

        async def run(self, context: UnifiedContext, stream: StreamBusProtocol) -> None:
            contexts.append(context)
            if value.action is not None:
                await value.action(context)
            value.finished.append(context.runtime.turn_id)
            await stream.emit(
                StreamEvent(type=StreamEventType.CONTENT, source=self.name, content="normal reply")
            )

    registry = CapabilityRegistry()
    registry.register(RegisteredMathProbe)
    store = SQLiteSessionStore(tmp_path / "math-host.sqlite3")
    runtime = TurnRuntimeManager(
        store=store,
        coordinator=MemoryCoordinator(),
        owner_id="math-semantic-test-worker",
        turn_engine=TurnEngine(capability_registry=registry),
    )
    value = Host(runtime, store, source, contexts)

    async def no_title(**_kwargs: Any) -> None:
        pass

    monkeypatch.setattr(runtime, "_maybe_generate_session_title", no_title)
    monkeypatch.setattr("deeptutor.services.skill.runtime.skill_manifest", lambda: "")
    try:
        yield value
    finally:
        await runtime.close()


async def submit(host: Host, **overrides: Any) -> tuple[dict, dict]:
    session, turn = await host.runtime.start_turn(
        {
            "content": RAW,
            "capability": "math_semantic_test",
            "auto_route": False,
            "tools": [],
            "knowledge_bases": [],
            "language": "en",
            **overrides,
        }
    )
    execution = host.runtime._executions[turn["id"]].task
    assert execution is not None
    await asyncio.wait_for(execution, timeout=15)
    assert turn["id"] in host.finished, "registered capability did not finish its assertions"
    return session, turn


def durable_episodes(host: Host) -> list[tuple[str, str, int, str]]:
    # Inspect committed rows through an independent SQLite connection.
    with sqlite3.connect(host.store.db_path) as connection:
        return connection.execute(
            "SELECT episode_id, session_id, math_revision, payload_json "
            "FROM math_semantic_episodes ORDER BY episode_id"
        ).fetchall()


def durable_alignments(host: Host) -> tuple[ResponseAlignment, ...]:
    rows = durable_episodes(host)
    assert len(rows) == 1
    records = json.loads(rows[0][3])
    return tuple(_decode(value) for value in records["alignments"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize("client_id", [None, "browser-submission-1"])
async def test_real_accepted_row_remains_grounded_when_prompt_is_expanded(host: Host, client_id):
    results = []

    async def action(context):
        results.append(await run_math_operation(await host.authority(context), host.align))

    host.action = action
    session, turn = await submit(
        host,
        client_submission_id=client_id,
        attachments=[
            {
                "type": "file",
                "filename": "notes.txt",
                "mime_type": "text/plain",
                "base64": base64.b64encode(b"Reference text: Q=9999\n").decode(),
            }
        ],
    )
    context = host.contexts[-1]
    user = next(
        row for row in await host.store.get_messages(session["id"]) if row["role"] == "user"
    )
    assert context.user_message != RAW and "Reference text: Q=9999" in context.user_message
    assert context.runtime.accepted_user_message_id == user["id"]
    assert context.runtime.accepted_user_content == user["content"] == RAW
    assert (
        context.runtime.client_submission_id
        == user["metadata"].get("client_submission_id")
        == client_id
    )
    assert context.runtime.turn_id == user["metadata"]["turn_id"] == turn["id"]
    assert context.runtime.run_durable_turn_mutation is not None
    assert context.runtime.turn_lease is not None
    assert results == list(durable_alignments(host))
    claim = results[0].claims[0]
    assert claim.student_response_ref.identifier == str(user["id"])
    assert RAW[claim.evidence.start : claim.evidence.end] == claim.evidence.quote == QUOTE
    assert claim.evidence.start == 2 and claim.evidence.end == 2 + len(QUOTE)
    assert results[0].matched_artifact_refs
    assert durable_episodes(host)[0][:3] == (
        host.source.identity.episode_id,
        session["id"],
        host.source.authored.workspace.revision,
    )
    assert (await host.store.get_turn(turn["id"]))["status"] == "completed"


@pytest.mark.asyncio
async def test_identical_raw_text_uses_two_real_accepted_identities(host: Host):
    results = []

    async def action(context):
        results.append(await run_math_operation(await host.authority(context), host.align))

    host.action = action
    session, _ = await submit(host, client_submission_id="first")
    await submit(host, session_id=session["id"], client_submission_id="second")
    users = [row for row in await host.store.get_messages(session["id"]) if row["role"] == "user"]
    assert len(users) == 2 and users[0]["id"] != users[1]["id"]
    assert users[0]["content"] == users[1]["content"] == RAW
    assert [value.student_response_ref.identifier for value in results] == [
        str(row["id"]) for row in users
    ]
    assert results[0].alignment_id != results[1].alignment_id
    assert results[0].claims[0].claim_id != results[1].claims[0].claim_id
    assert set(durable_alignments(host)) == set(results)


@pytest.mark.asyncio
async def test_core_mutation_exception_rolls_back_all_mathematical_records(host: Host):
    def failing(state):
        host.align(state)
        raise RuntimeError("failure after grounded mathematical mutation")

    async def action(context):
        with pytest.raises(RuntimeError, match="failure after grounded"):
            await run_math_operation(await host.authority(context), failing)

    host.action = action
    await submit(host)
    assert durable_episodes(host) == []


@pytest.mark.asyncio
async def test_lost_ownership_before_math_mutation_prevents_body_and_commit(host: Host):
    called = []

    def mutation(state):
        called.append(True)
        return host.align(state)

    async def action(context):
        authority = await host.authority(context)
        assert await host.runtime.coordinator.release_turn(context.runtime.turn_lease)
        with pytest.raises(RuntimeError):
            await run_math_operation(authority, mutation)

    host.action = action
    await submit(host)
    assert called == [] and durable_episodes(host) == []


@pytest.mark.asyncio
async def test_retained_math_authority_is_rejected_after_original_turn_finishes(host: Host):
    retained = []

    async def action(context):
        authority = await host.authority(context)
        retained.append(authority)
        await run_math_operation(authority, host.align)

    host.action = action
    _, turn = await submit(host)
    before = durable_episodes(host)
    called = []

    def stale_mutation(state):
        called.append(True)
        return host.align(state)

    assert (await host.store.get_turn(turn["id"]))["status"] == "completed"
    with pytest.raises(RuntimeError):
        await run_math_operation(retained[0], stale_mutation)
    assert called == [] and durable_episodes(host) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", ["id", "raw", "client", "authority"])
async def test_native_boundary_rejects_corrupted_host_seam_without_durable_effect(
    host: Host, corrupt
):
    called = []

    def mutation(state):
        called.append(True)
        return host.align(state)

    async def action(context):
        changes = {
            "id": {"accepted_user_message_id": -1},
            "raw": {"accepted_user_content": context.user_message + " forged"},
            "client": {"client_submission_id": "forged-client"},
            "authority": {"run_durable_turn_mutation": None},
        }[corrupt]
        damaged = replace(context.runtime, **changes)
        prefix = await host.prefix(context)
        if corrupt == "id":
            prefix = (*prefix[:-1], -1)
        with pytest.raises(ValueError):
            authority = sqlite_math_mutation(
                damaged, session_id=context.session_id, source=host.source, accepted_prefix=prefix
            )
            await run_math_operation(authority, mutation)

    host.action = action
    await submit(host, client_submission_id="actual-client")
    assert called == [] and durable_episodes(host) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["non_persist", "regenerate"])
async def test_reexecution_cannot_invent_a_new_accepted_math_submission(host: Host, path):
    async def first(context):
        await run_math_operation(await host.authority(context), host.align)

    host.action = first
    session, _ = await submit(host)
    before = durable_episodes(host)

    async def no_acceptance(context):
        assert context.runtime.accepted_user_message_id is None
        assert context.runtime.accepted_user_content is None
        with pytest.raises(ValueError, match="no newly accepted submission"):
            await host.authority(context)

    host.action = no_acceptance
    if path == "non_persist":
        await submit(host, session_id=session["id"], persist_user_message=False)
    else:
        _, turn = await host.runtime.regenerate_last_turn(
            session["id"], overrides={"auto_route": False}
        )
        execution = host.runtime._executions[turn["id"]].task
        assert execution is not None
        await asyncio.wait_for(execution, timeout=15)
        assert turn["id"] in host.finished
    users = [row for row in await host.store.get_messages(session["id"]) if row["role"] == "user"]
    assert len(users) == 1 and durable_episodes(host) == before


@pytest.mark.asyncio
async def test_foreign_host_session_cannot_mutate_existing_mathematical_episode(host: Host):
    async def first(context):
        await run_math_operation(await host.authority(context), host.align)

    host.action = first
    first_session, _ = await submit(host)
    before = durable_episodes(host)
    called = []

    def foreign(state):
        called.append(True)
        return host.align(state)

    async def second(context):
        assert context.session_id != first_session["id"]
        with pytest.raises(ValueError, match="foreign host session"):
            await run_math_operation(await host.authority(context), foreign)

    host.action = second
    await submit(host)
    assert called == [] and durable_episodes(host) == before


@pytest.mark.asyncio
async def test_actual_math_commit_orders_before_ownership_invalidation_during_mutation(host: Host):
    entered, resume = Event(), Event()

    def mutation(state):
        alignment = host.align(state)
        entered.set()
        assert resume.wait(10), "test did not resume the transaction-local mathematical mutation"
        return alignment

    async def action(context):
        await run_math_operation(await host.authority(context), mutation)

    host.action = action
    _, turn = await host.runtime.start_turn(
        {"content": RAW, "capability": "math_semantic_test", "auto_route": False}
    )
    invalidation = None
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        assert durable_episodes(host) == []
        lease = host.contexts[-1].runtime.turn_lease
        started = asyncio.Event()

        async def release():
            started.set()
            return await host.runtime.coordinator.release_turn(lease)

        invalidation = asyncio.create_task(release())
        await started.wait()
        await asyncio.sleep(0)
        assert not invalidation.done()
        resume.set()
        await asyncio.wait_for(invalidation, timeout=10)
        execution = host.runtime._executions[turn["id"]].task
        assert execution is not None
        await asyncio.wait_for(execution, timeout=15)
        assert turn["id"] in host.finished
        assert len(durable_alignments(host)) == 1
        retained = sqlite_math_mutation(
            host.contexts[-1].runtime,
            session_id=host.contexts[-1].session_id,
            source=host.source,
            accepted_prefix=await host.prefix(host.contexts[-1]),
        )
        before = durable_episodes(host)
        with pytest.raises(RuntimeError):
            await run_math_operation(retained, host.align)
        assert durable_episodes(host) == before
    finally:
        resume.set()
        if invalidation is not None and not invalidation.done():
            await asyncio.wait_for(invalidation, timeout=10)


@pytest.mark.asyncio
async def test_math_operation_without_host_authority_fails_closed():
    called = []

    def mutation(_state):
        called.append(True)

    with pytest.raises(ValueError, match="protected host commit authority"):
        await run_math_operation(None, mutation)
    assert called == []


@pytest.mark.asyncio
async def test_head_drift_invalidates_confirmation_only_through_live_commit_authority(host: Host):
    method_a = "s=x+y"
    method_b = "3*(x^2-x*y+y^2)-(x^2+x*y+y^2)=2*(x-y)^2"
    retained, issued = [], []

    async def first(context):
        authority = await host.authority(context)
        retained.append(authority)

        def observe(state):
            host.align(state, method_a)
            assert state.trajectory().status == "SUPPORTED"

        await run_math_operation(authority, observe)

    host.action = first
    session, _ = await submit(host, content=method_a)

    async def second(context):
        def observe(state):
            host.align(state, method_b)
            trajectory = state.trajectory()
            assert trajectory.status == "METHOD_CONFIRMATION_REQUIRED"
            confirmation = trajectory.method_confirmation
            assert confirmation is not None and confirmation.state == "pending"
            issued.append((confirmation, state.snapshot().workspace.revision))

        await run_math_operation(await host.authority(context), observe)

    host.action = second
    await submit(host, session_id=session["id"], content=method_b)
    confirmation, original_revision = issued[0]

    async def drift_and_resolve(context):
        authority = await host.authority(context)

        def advance(state):
            state.append(expected_revision=original_revision, status="partial")

        await run_math_operation(authority, advance)
        before = durable_episodes(host)
        record = json.loads(before[0][3])["confirmations"][confirmation.confirmation_id]
        assert record["state"] == "pending"
        token = confirmation.option_paths[0][0]
        with pytest.raises(ValueError, match="protected host commit authority"):
            await confirm_method(
                None, confirmation, option_token=token, expected_revision=original_revision
            )
        assert durable_episodes(host) == before
        with pytest.raises(RuntimeError):
            await confirm_method(
                retained[0], confirmation, option_token=token, expected_revision=original_revision
            )
        assert durable_episodes(host) == before
        with pytest.raises(ValueError, match="resolution scope changed"):
            await confirm_method(
                authority, confirmation, option_token=token, expected_revision=original_revision
            )
        after = durable_episodes(host)
        assert after[0][2] == original_revision + 1
        current = json.loads(after[0][3])["confirmations"][confirmation.confirmation_id]
        assert current["state"] == "invalidated"
        assert current["chosen_path_ref"] is None and current["resolved_after_turn"] is None

    host.action = drift_and_resolve
    await submit(host, session_id=session["id"], content="resolve the previously issued method")
