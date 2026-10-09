"""Trusted host selection exercised through accepted application/runtime turns."""

from __future__ import annotations

import asyncio
from contextlib import closing
from dataclasses import fields, replace
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
import pytest_asyncio

from deeptutor.app.service import TurnApplicationService
from deeptutor.capabilities.math_turn.capability import MathTurnCapability
from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.core.context import CapabilityBinding, TurnRoutingReference
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.math_semantic.alignment import AlignmentEvaluator
from deeptutor.math_semantic.codec import _decode
from deeptutor.math_semantic.proposals import AlignmentProposal
from deeptutor.runtime.capability_catalog import CapabilityCatalog
from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.turn_engine import TurnEngine
from deeptutor.services.session.math_semantic_persistence import sqlite_math_mutation
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager

from .recovery_support import A, B, C, assert_private_evidence_extension, reviewed_source


class RoutingHost:
    """Test-only trusted composition; requests cannot change its selected scope."""

    def __init__(self, db: Path, *, unknown: bool = True, legacy: bool = False):
        self.db = db
        self.source = reviewed_source(unknown=unknown)
        self.scope = None
        self.references, self.accepted_rows = [], []
        self.math_contexts, self.ordinary_contexts, self.projections = [], [], []
        self.completed, self.errors = [], []
        self.mode = "normal"
        self.legacy_ids = []
        self.store = SQLiteSessionStore(db)
        self.coordinator = MemoryCoordinator()
        host = self

        async def resolve(reference):
            assert isinstance(reference, TurnRoutingReference)
            assert {field.name for field in fields(reference)} == {
                "session_id",
                "turn_id",
                "accepted_user_message_id",
            }
            assert not hasattr(reference, "content") and not hasattr(reference, "metadata")
            host.references.append(reference)
            if reference.accepted_user_message_id is not None:
                row = host.user_row(reference.accepted_user_message_id)
                assert row["session_id"] == reference.session_id
                assert row["metadata"]["turn_id"] == reference.turn_id
                host.accepted_rows.append(row)
            if isinstance(host.scope, tuple):
                raise ValueError("ambiguous trusted reviewed episode")
            return host.scope

        class Provider:
            provider_id = "routing-regression-proposal"
            model_config_digest = "routing-test-reviewed-proposal"

            def propose(self, projection):
                host.projections.append(projection)
                quote = (
                    "not present in accepted content"
                    if host.mode == "missing_grounding"
                    else projection.response_text.strip()
                )
                return {
                    "claims": [
                        {
                            "evidence": {"quote": quote},
                            "candidate_artifact_refs": [
                                artifact.artifact_id
                                for artifact in projection.artifacts
                                if artifact.statement == quote
                            ],
                            "parse_status": "unparsed" if host.mode == "unsupported" else "parsed",
                        }
                    ]
                }

        class ObservedMath(MathTurnCapability):
            def __init__(self):
                super().__init__(resolve_episode=lambda _accepted: host.source, provider=Provider())

            async def run(self, context, stream):
                host.math_contexts.append(context)
                try:
                    await super().run(context, stream)
                    host.completed.append(context.runtime.turn_id)
                except Exception as exc:
                    host.errors.append(exc)
                    raise

        class LegacyMath(TurnCapability):
            """Native producer of the frozen baseline durable contract shape.

            This is test-only compatibility setup. It executes the existing
            native extraction primitive on real persisted host rows, then
            writes the baseline's already-certified first/id envelope through
            the real protected port. It does not execute the old adapter or
            claim to exercise the baseline writer in this suite.
            """

            manifest = MathTurnCapability.manifest

            async def run(self, context, stream):
                host.math_contexts.append(context)
                runtime = context.runtime
                host.legacy_ids.append(runtime.accepted_user_message_id)
                authority = sqlite_math_mutation(
                    runtime,
                    session_id=context.session_id,
                    source=host.source,
                    accepted_prefix=tuple(host.legacy_ids),
                )
                provider = Provider()

                def observe(state):
                    snapshot = state.snapshot()
                    projection = AlignmentEvaluator._project(state.submission.raw_content, snapshot)
                    proposal = AlignmentProposal.from_value(provider.propose(projection))
                    state.align(
                        proposal,
                        expected_revision=snapshot.workspace.revision,
                        provider_id=provider.provider_id,
                        config_digest=provider.model_config_digest,
                    )
                    return state.trajectory().to_dict()

                trajectory = await authority(observe)

                def certify_baseline_envelope(sql):
                    rows = sql(
                        "SELECT id, metadata_json FROM messages WHERE session_id=? AND role='user' AND id>=? AND id<=? ORDER BY id",
                        (context.session_id, host.legacy_ids[0], host.legacy_ids[-1]),
                    )
                    assert [row[0] for row in rows] == host.legacy_ids
                    assert all("host_capability_binding" not in json.loads(row[1]) for row in rows)
                    for _, metadata_json in rows:
                        turn_id = json.loads(metadata_json)["turn_id"]
                        assert sql("SELECT session_id FROM turns WHERE id=?", (turn_id,)) == [
                            (context.session_id,)
                        ]
                    records = sql(
                        "SELECT payload_json FROM math_semantic_episodes WHERE episode_id=?",
                        (host.source.identity.episode_id,),
                    )
                    assert len(records) == 1
                    value = json.loads(records[0][0])
                    assert "host_math_ownership_version" not in value
                    assert "host_legacy_accepted_message_ids" not in value
                    value["host_episode_first_message_id"] = host.legacy_ids[0]
                    value["host_accepted_message_ids"] = host.legacy_ids
                    sql(
                        "UPDATE math_semantic_episodes SET payload_json=? WHERE episode_id=?",
                        (json.dumps(value), host.source.identity.episode_id),
                    )

                assert runtime.run_durable_turn_mutation is not None
                await runtime.run_durable_turn_mutation(certify_baseline_envelope)
                context.capability_output.event_metadata = {"math": {"trajectory": trajectory}}
                host.completed.append(runtime.turn_id)

        class Ordinary(TurnCapability):
            def __init__(self, name):
                self.manifest = CapabilityManifest(name=name, description="ordinary host probe")

            async def run(self, context, stream):
                host.ordinary_contexts.append(context)
                context.capability_output.agent_output = "Ordinary capability completed."
                await stream.emit(
                    StreamEvent(type=StreamEventType.CONTENT, source=self.name, content="ordinary")
                )
                host.completed.append(context.runtime.turn_id)

        catalog = CapabilityCatalog()
        catalog.register(
            name="math_turn",
            kind="turn",
            manifest=MathTurnCapability.manifest,
            factory=LegacyMath if legacy else ObservedMath,
        )
        for name in ("chat", "immersive_reading", "deep_research"):
            catalog.register(
                name=name,
                kind="turn",
                manifest=CapabilityManifest(name=name, description="ordinary host probe"),
                factory=lambda name=name: Ordinary(name),
            )
        self.engine = TurnEngine(
            capability_registry=CapabilityRegistry(catalog),
            resolve_accepted_capability=None if legacy else resolve,
        )
        self.runtime = TurnRuntimeManager(
            self.store,
            coordinator=self.coordinator,
            owner_id="trusted-routing-test-worker",
            turn_engine=self.engine,
        )

        async def no_title(**_kwargs):
            pass

        self.runtime._maybe_generate_session_title = no_title
        self.application = TurnApplicationService(
            SimpleNamespace(get=lambda: self.store),
            SimpleNamespace(get=lambda _store: self.runtime),
            self.coordinator,
        )

    def math_scope(self):
        return CapabilityBinding("math_turn", self.source.identity.episode_id)

    async def close(self):
        await self.runtime.close()
        await self.coordinator.close()

    async def start(self, text=A, *, session_id=None, **overrides):
        payload = {
            "content": text,
            "capability": "chat",
            "auto_route": False,
            "tools": [],
            "knowledge_bases": [],
            "language": "en",
            **overrides,
        }
        if session_id:
            payload["session_id"] = session_id
        return await self.application.start_turn(payload)

    async def finish(self, turn, *, status="completed"):
        execution = self.runtime._executions[turn["id"]]
        assert execution.task is not None
        await asyncio.wait_for(execution.task, 20)
        persisted = await self.store.get_turn(turn["id"])
        assert persisted["status"] == status, (persisted, self.errors)
        if status == "completed":
            assert turn["id"] in self.completed, self.errors
        else:
            assert turn["id"] not in self.completed
        return persisted

    async def submit(self, text=A, *, session_id=None, **overrides):
        session, turn = await self.start(text, session_id=session_id, **overrides)
        await self.finish(turn)
        return session, turn

    def user_row(self, message_id):
        with closing(sqlite3.connect(self.db)) as connection:
            value = connection.execute(
                "SELECT id, session_id, role, content, metadata_json FROM messages WHERE id=?",
                (message_id,),
            ).fetchone()
        assert value is not None and value[2] == "user"
        return {
            "id": value[0],
            "session_id": value[1],
            "content": value[3],
            "metadata": json.loads(value[4]),
        }

    def episodes(self):
        with closing(sqlite3.connect(self.db)) as connection:
            return {
                row[0]: json.loads(row[1])
                for row in connection.execute(
                    "SELECT episode_id, payload_json FROM math_semantic_episodes"
                )
            }

    def state(self):
        return self.episodes()[self.source.identity.episode_id]

    def result(self):
        return self.math_contexts[-1].extension_state["math_turn"]["calculation"]

    async def choice(self, turn):
        async with asyncio.timeout(15):
            card = None
            events = self.runtime.subscribe_turn(turn["id"])
            try:
                async for event in events:
                    payload = event.get("metadata", {}).get("tool_metadata", {}).get("ask_user")
                    if payload:
                        card = payload["questions"][0]
                    if card and event["type"] == "wait_for_input":
                        break
            finally:
                await events.aclose()
            while True:
                row = await self.store.get_turn(turn["id"])
                if card and row["status"] == "waiting_input":
                    return card
                assert not self.errors, self.errors
                await asyncio.sleep(0.01)

    async def answer(self, turn, card, *, token=None):
        assert await self.runtime.submit_user_reply(
            turn["id"],
            answers=[
                {
                    "questionId": card["id"],
                    "selected_option_id": token or card["options"][-1]["option_id"],
                    "text": "untrusted displayed choice",
                }
            ],
        )


@pytest_asyncio.fixture
async def host_factory(tmp_path, monkeypatch):
    hosts = []
    monkeypatch.setattr("deeptutor.services.skill.runtime.skill_manifest", lambda: "")

    def create(*, db=None, unknown=True, legacy=False):
        host = RoutingHost(
            db or tmp_path / f"routing-{len(hosts)}.db", unknown=unknown, legacy=legacy
        )
        hosts.append(host)
        return host

    yield create
    for host in reversed(hosts):
        await host.close()


def assert_marker(host, context, binding):
    runtime = context.runtime
    row = host.user_row(runtime.accepted_user_message_id)
    assert row["content"] == runtime.accepted_user_content
    assert row["metadata"]["turn_id"] == runtime.turn_id
    assert row["metadata"]["host_capability_binding"] == {
        "turn_id": runtime.turn_id,
        "binding": binding,
    }


def assert_ordinary_private_state_absent(context):
    assert context.runtime.capability_binding is None
    assert not context.capability_output.event_metadata
    assert context.extension_state == {}
    # Ordinary transcript text remains ordinary history. A mathematical
    # projection, ledger/token or reviewed source may not enter its private DI.
    private = json.dumps(
        {
            "metadata": context.metadata,
            "extensions": context.extension_state,
            "source_manifest": context.source_manifest,
            "conversation_history": context.conversation_history,
            "model_history": context.runtime.model_history,
            "previous_model_turn": context.runtime.previous_model_turn,
            "model_turn": context.runtime.model_turn,
            "config": context.config_overrides,
        },
        default=str,
    )
    assert "host_accepted_message_ids" not in private
    assert "verified_grounded_refs" not in private
    assert "option_paths" not in private
    assert "cutoff_response_ref" not in private
    return private


@pytest.mark.asyncio
async def test_explicit_reviewed_host_scope_routes_real_accepted_row_to_math(host_factory):
    host = host_factory()
    host.scope = host.math_scope()
    session, turn = await host.submit("  s=x+y\n", client_submission_id="client-causal-id")
    context = host.math_contexts[-1]
    assert context.active_capability == "math_turn"
    assert context.runtime.capability_binding == host.scope
    assert context.runtime.client_submission_id == "client-causal-id"
    reference = host.references[-1]
    assert reference.session_id == session["id"] and reference.turn_id == turn["id"]
    assert reference.accepted_user_message_id == context.runtime.accepted_user_message_id
    assert host.accepted_rows[-1]["content"] == "  s=x+y\n"
    assert host.projections[-1].response_text == "  s=x+y\n"
    assert_marker(
        host,
        context,
        {"capability": "math_turn", "scope_id": host.source.identity.episode_id},
    )
    assert host.state()["host_accepted_message_ids"] == [reference.accepted_user_message_id]
    assert host.result()["trajectory"]["status"] == "SUPPORTED"
    assert host.result()["verification_status"] == "UNKNOWN"
    assert not host.result()["verified_grounded_refs"]
    assert all(grant["act_kind"] == "orientation" for grant in host.result()["authority"])
    assert not host.ordinary_contexts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ordinary_request",
    [
        {},
        {"capability": "immersive_reading", "workspace_mode": "immersive_reading"},
        {"capability": "chat", "knowledge_bases": ["ordinary-rag-document"]},
        {"capability": "deep_research", "config": {"mode": "notes", "depth": "quick"}},
    ],
    ids=["chat", "reading", "rag-style-chat", "research"],
)
async def test_ordinary_reading_and_rag_preserve_existing_capability(
    host_factory, ordinary_request
):
    host = host_factory()
    await host.submit(A, **ordinary_request)
    context = host.ordinary_contexts[-1]
    assert context.active_capability == ordinary_request.get("capability", "chat")
    assert_marker(host, context, None)
    assert_ordinary_private_state_absent(context)
    assert not host.math_contexts and not host.projections and not host.episodes()


@pytest.mark.asyncio
async def test_same_text_routes_by_trusted_scope_not_content(host_factory):
    host = host_factory()
    session, _ = await host.submit(A)
    ordinary_id = host.ordinary_contexts[-1].runtime.accepted_user_message_id
    host.scope = host.math_scope()
    await host.submit(A, session_id=session["id"])
    math_id = host.math_contexts[-1].runtime.accepted_user_message_id
    assert math_id != ordinary_id
    assert host.user_row(ordinary_id)["content"] == host.user_row(math_id)["content"] == A
    assert host.state()["host_accepted_message_ids"] == [math_id]
    assert len(host.projections) == 1
    assert len(host.ordinary_contexts) == len(host.math_contexts) == 1


@pytest.mark.asyncio
async def test_math_ordinary_math_return_omits_middle_row_from_evidence(host_factory):
    host = host_factory()
    host.scope = host.math_scope()
    session, _ = await host.submit(A)
    first_id = host.math_contexts[-1].runtime.accepted_user_message_id
    committed = host.state()
    host.scope = None
    await host.submit(A, session_id=session["id"])
    ordinary = host.ordinary_contexts[-1]
    ordinary_id = ordinary.runtime.accepted_user_message_id
    assert host.state() == committed
    assert len(host.projections) == 1
    assert_marker(host, ordinary, None)
    assert_ordinary_private_state_absent(ordinary)
    host.scope = host.math_scope()
    await host.submit(A, session_id=session["id"])
    last_id = host.math_contexts[-1].runtime.accepted_user_message_id
    state = host.state()
    assert state["host_episode_first_message_id"] == first_id
    assert state["host_accepted_message_ids"] == [first_id, last_id]
    assert ordinary_id not in state["host_accepted_message_ids"]
    alignments = [_decode(value) for value in state["alignments"].values()]
    assert {alignment.student_response_ref.identifier for alignment in alignments} == {
        str(first_id),
        str(last_id),
    }
    assert len(state["alignments"]) == 2 and not state["confirmations"]
    assert host.result()["trajectory"]["cutoff_turn"] == 2
    assert host.result()["verification_status"] == "UNKNOWN"
    assert not host.result()["verified_grounded_refs"]


@pytest.mark.asyncio
async def test_missing_scope_does_not_allow_client_math_selection(host_factory):
    host = host_factory()
    _, turn = await host.start(A, capability="math_turn")
    await host.finish(turn, status="failed")
    assert not host.episodes() and not host.projections
    assert not host.math_contexts[-1].capability_output.event_metadata
    assert host.math_contexts[-1].runtime.capability_binding is None


@pytest.mark.asyncio
@pytest.mark.parametrize("execution", ["regenerate", "non_persist"])
async def test_math_scope_cannot_create_acceptance_for_replay_execution(host_factory, execution):
    host = host_factory()
    host.scope = host.math_scope()
    session, _ = await host.submit(A)
    committed = host.state()
    accepted_id = host.math_contexts[-1].runtime.accepted_user_message_id
    if execution == "regenerate":
        _, turn = await host.application.regenerate_last_turn(session["id"])
    else:
        _, turn = await host.start(B, session_id=session["id"], persist_user_message=False)
    await host.finish(turn, status="failed")
    context = host.math_contexts[-1]
    assert context.runtime.accepted_user_message_id is None
    assert context.runtime.accepted_user_content is None
    assert host.references[-1].accepted_user_message_id is None
    assert len(host.projections) == 1 and host.state() == committed
    rows = await host.store.get_messages(session["id"])
    assert [row["id"] for row in rows if row["role"] == "user"] == [accepted_id]


@pytest.mark.asyncio
async def test_ordinary_regenerate_preserves_existing_route_without_new_evidence(host_factory):
    host = host_factory()
    session, _ = await host.submit(A)
    original = host.ordinary_contexts[-1].runtime.accepted_user_message_id
    marker = host.user_row(original)["metadata"]["host_capability_binding"]
    _, turn = await host.application.regenerate_last_turn(session["id"])
    await host.finish(turn)
    context = host.ordinary_contexts[-1]
    assert context.active_capability == "chat"
    assert context.runtime.accepted_user_message_id is None
    assert host.references[-1].accepted_user_message_id is None
    assert host.user_row(original)["metadata"]["host_capability_binding"] == marker
    assert_ordinary_private_state_absent(context)
    assert not host.math_contexts and not host.projections and not host.episodes()


@pytest.mark.asyncio
@pytest.mark.parametrize("forged", ["request_field", "config_field"])
async def test_client_cannot_inject_host_binding(host_factory, forged):
    host = host_factory()
    binding = {"capability": "math_turn", "scope_id": host.source.identity.episode_id}
    payload = (
        {"host_capability_binding": binding}
        if forged == "request_field"
        else {"config": {"host_capability_binding": binding}}
    )
    with pytest.raises((ValueError, RuntimeError)):
        await host.start(A, **payload)
    assert not host.references and not host.math_contexts and not host.projections
    assert not host.episodes()


@pytest.mark.asyncio
async def test_ambiguous_trusted_scope_fails_before_any_capability(host_factory):
    host = host_factory()
    host.scope = (host.math_scope(), CapabilityBinding("math_turn", "other-reviewed-episode"))
    _, turn = await host.start(A)
    await host.finish(turn, status="failed")
    assert host.references[-1].accepted_user_message_id is not None
    assert not host.math_contexts and not host.ordinary_contexts
    assert not host.projections and not host.episodes()


@pytest.mark.asyncio
async def test_reviewed_source_cannot_override_routed_episode_identity(host_factory):
    host = host_factory()
    host.scope = host.math_scope()
    host.source = replace(
        host.source,
        identity=replace(host.source.identity, episode_id="different-reviewed-episode"),
        authored=replace(
            host.source.authored,
            workspace=replace(
                host.source.authored.workspace, workspace_id="different-reviewed-episode"
            ),
        ),
    )
    _, turn = await host.start(A)
    await host.finish(turn, status="failed")
    assert not host.projections and not host.episodes()
    assert not host.math_contexts[-1].capability_output.event_metadata


@pytest.mark.asyncio
async def test_first_attributed_failure_remains_episode_start_without_aggregate(host_factory):
    host = host_factory()
    original_source = host.source
    host.scope = host.math_scope()
    host.source = replace(
        original_source,
        identity=replace(original_source.identity, episode_id="wrong-review-at-first-turn"),
        authored=replace(
            original_source.authored,
            workspace=replace(
                original_source.authored.workspace, workspace_id="wrong-review-at-first-turn"
            ),
        ),
    )
    session, failed = await host.start(A)
    await host.finish(failed, status="failed")
    first_id = host.math_contexts[-1].runtime.accepted_user_message_id
    assert not host.episodes() and not host.projections
    assert_marker(
        host,
        host.math_contexts[-1],
        {"capability": "math_turn", "scope_id": original_source.identity.episode_id},
    )
    host.source = original_source
    await host.submit(A, session_id=session["id"])
    next_id = host.math_contexts[-1].runtime.accepted_user_message_id
    state = host.state()
    assert state["host_episode_first_message_id"] == first_id
    assert state["host_accepted_message_ids"] == [first_id, next_id]
    assert len(state["alignments"]) == 1
    assert host.result()["trajectory"]["status"] == "UNKNOWN"
    assert host.result()["verification_status"] == "UNKNOWN"
    assert not host.result()["verified_grounded_refs"]


@pytest.mark.asyncio
async def test_branch_cannot_skip_episode_history_but_new_reviewed_episode_can_start(host_factory):
    host = host_factory()
    host.scope = host.math_scope()
    session, _ = await host.submit(A)
    first_id = host.math_contexts[-1].runtime.accepted_user_message_id
    await host.submit(A, session_id=session["id"])
    original_episode, original = host.source.identity.episode_id, host.state()
    _, branch = await host.start(A, session_id=session["id"], parent_message_id=first_id)
    await host.finish(branch, status="failed")
    assert host.state() == original
    assert not host.math_contexts[-1].capability_output.event_metadata
    host.source = replace(
        host.source,
        identity=replace(host.source.identity, episode_id="reviewed-branch-episode"),
        authored=replace(
            host.source.authored,
            workspace=replace(
                host.source.authored.workspace, workspace_id="reviewed-branch-episode"
            ),
        ),
    )
    host.scope = host.math_scope()
    await host.submit(A, session_id=session["id"], parent_message_id=first_id)
    new_id = host.math_contexts[-1].runtime.accepted_user_message_id
    episodes = host.episodes()
    assert len(episodes) == 2 and episodes[original_episode] == original
    assert host.state()["host_episode_first_message_id"] == new_id
    assert host.state()["host_accepted_message_ids"] == [new_id]
    assert host.result()["episode_id"] == "reviewed-branch-episode"
    assert host.result()["verification_status"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_failed_math_alignment_membership_is_not_deleted_or_verified(host_factory):
    host = host_factory()
    host.scope = host.math_scope()
    session, _ = await host.submit(A)
    first_id = host.math_contexts[-1].runtime.accepted_user_message_id
    host.mode = "missing_grounding"
    _, failed = await host.start(B, session_id=session["id"])
    await host.finish(failed, status="failed")
    failed_id = host.math_contexts[-1].runtime.accepted_user_message_id
    assert host.state()["host_accepted_message_ids"] == [first_id, failed_id]
    assert len(host.state()["alignments"]) == 1
    host.scope, host.mode = None, "normal"
    await host.submit(B, session_id=session["id"])
    ordinary_id = host.ordinary_contexts[-1].runtime.accepted_user_message_id
    host.scope = host.math_scope()
    await host.submit(A, session_id=session["id"])
    current_id = host.math_contexts[-1].runtime.accepted_user_message_id
    state = host.state()
    assert state["host_accepted_message_ids"] == [first_id, failed_id, current_id]
    assert ordinary_id not in state["host_accepted_message_ids"]
    assert len(state["alignments"]) == 2
    assert host.result()["verification_status"] == "UNKNOWN"
    assert not host.result()["verified_grounded_refs"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["removed", "foreign"])
async def test_durable_route_marker_corruption_cannot_rewrite_math_basis(host_factory, mutation):
    host = host_factory()
    host.scope = host.math_scope()
    session, _ = await host.submit(A)
    math_id = host.math_contexts[-1].runtime.accepted_user_message_id
    host.scope = None
    await host.submit(A, session_id=session["id"])
    committed = host.state()
    row_id = math_id
    row = host.user_row(row_id)
    metadata = row["metadata"]
    if mutation == "removed":
        metadata.pop("host_capability_binding")
    else:
        metadata["host_capability_binding"]["binding"] = {
            "capability": "math_turn",
            "scope_id": "foreign-episode",
        }
    with closing(sqlite3.connect(host.db)) as connection:
        connection.execute(
            "UPDATE messages SET metadata_json=? WHERE id=?", (json.dumps(metadata), row_id)
        )
        connection.commit()
    host.scope = host.math_scope()
    _, turn = await host.start(A, session_id=session["id"])
    await host.finish(turn, status="failed")
    assert host.state() == committed
    assert not host.math_contexts[-1].capability_output.event_metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["missing_version", "boolean_version"])
async def test_ownership_version_cannot_downgrade_new_marker_basis(host_factory, corruption):
    host = host_factory()
    host.scope = host.math_scope()
    session, _ = await host.submit(A)
    committed = host.state()
    if corruption == "missing_version":
        committed.pop("host_math_ownership_version")
    else:
        committed["host_math_ownership_version"] = True
    with closing(sqlite3.connect(host.db)) as connection:
        connection.execute(
            "UPDATE math_semantic_episodes SET payload_json=? WHERE episode_id=?",
            (json.dumps(committed), host.source.identity.episode_id),
        )
        connection.commit()
    _, turn = await host.start(A, session_id=session["id"])
    await host.finish(turn, status="failed")
    assert host.state() == committed
    assert not host.math_contexts[-1].capability_output.event_metadata


@pytest.mark.asyncio
async def test_frozen_legacy_certified_ids_cut_over_without_adopting_unmarked_gap(host_factory):
    legacy = host_factory(legacy=True)
    session, _ = await legacy.submit(A, capability="math_turn")
    await legacy.submit(A, session_id=session["id"], capability="math_turn")
    committed = legacy.state()
    old_ids = committed["host_accepted_message_ids"]
    assert len(old_ids) == 2
    assert "host_math_ownership_version" not in committed
    assert "host_legacy_accepted_message_ids" not in committed
    assert all("host_capability_binding" not in legacy.user_row(row)["metadata"] for row in old_ids)
    await legacy.submit(A, session_id=session["id"])
    gap_id = legacy.ordinary_contexts[-1].runtime.accepted_user_message_id
    assert "host_capability_binding" not in legacy.user_row(gap_id)["metadata"]
    assert legacy.state() == committed
    await legacy.close()

    fresh = host_factory(db=legacy.db)
    fresh.scope = fresh.math_scope()
    await fresh.submit(A, session_id=session["id"])
    first_new = fresh.math_contexts[-1].runtime.accepted_user_message_id
    cutover = fresh.state()
    assert cutover["host_episode_first_message_id"] == old_ids[0]
    assert cutover["host_accepted_message_ids"] == [*old_ids, first_new]
    assert cutover["host_math_ownership_version"] == 1
    assert cutover["host_legacy_accepted_message_ids"] == old_ids
    assert gap_id not in cutover["host_accepted_message_ids"]
    assert {key: cutover["alignments"][key] for key in committed["alignments"]} == committed[
        "alignments"
    ]
    assert_private_evidence_extension(committed, cutover)
    assert cutover["confirmations"] == committed["confirmations"]
    await fresh.submit(A, session_id=session["id"])
    current_id = fresh.math_contexts[-1].runtime.accepted_user_message_id
    pinned = fresh.state()
    assert pinned["host_accepted_message_ids"] == [*old_ids, first_new, current_id]
    assert pinned["host_legacy_accepted_message_ids"] == old_ids
    assert len(pinned["alignments"]) == 4

    # A newly marked row cannot later be grandfathered by erasing its marker.
    metadata = fresh.user_row(first_new)["metadata"]
    metadata.pop("host_capability_binding")
    with closing(sqlite3.connect(fresh.db)) as connection:
        connection.execute(
            "UPDATE messages SET metadata_json=? WHERE id=?", (json.dumps(metadata), first_new)
        )
        connection.commit()
    _, turn = await fresh.start(A, session_id=session["id"])
    await fresh.finish(turn, status="failed")
    assert fresh.state() == pinned


@pytest.mark.asyncio
async def test_pending_confirmation_survives_ordinary_gap_without_private_leak(host_factory):
    host = host_factory(unknown=False)
    host.scope = host.math_scope()
    session, _ = await host.submit(A)
    _, parked = await host.start(B, session_id=session["id"])
    original_card = await host.choice(parked)
    original = host.state()
    confirmation = original["confirmations"][original_card["id"]]
    assert confirmation["state"] == "pending"
    assert await host.application.cancel_turn_and_wait(parked["id"])
    host.scope = None
    await host.submit(C, session_id=session["id"])
    ordinary = host.ordinary_contexts[-1]
    ordinary_id = ordinary.runtime.accepted_user_message_id
    assert host.state() == original
    private = assert_ordinary_private_state_absent(ordinary)
    assert all(option["option_id"] not in private for option in original_card["options"])
    host.scope = host.math_scope()
    _, returning = await host.start(C, session_id=session["id"])
    recovered_card = await host.choice(returning)
    waiting = host.state()
    assert recovered_card == original_card
    assert len(waiting["confirmations"]) == 1
    assert waiting["confirmations"][original_card["id"]] == confirmation
    assert ordinary_id not in waiting["host_accepted_message_ids"]
    assert not host.math_contexts[-1].capability_output.event_metadata
    await host.answer(returning, recovered_card)
    await host.finish(returning)
    resolved = host.state()["confirmations"][original_card["id"]]
    assert resolved["state"] == "resolved"
    assert resolved["chosen_path_ref"] == confirmation["option_paths"][-1][1]
    after_resolution = host.state()
    host.scope = None
    await host.submit(A, session_id=session["id"])
    resolved_ordinary = host.ordinary_contexts[-1]
    assert host.state() == after_resolution
    private = assert_ordinary_private_state_absent(resolved_ordinary)
    assert all(option["option_id"] not in private for option in original_card["options"])
    assert not host.projections[-1].response_text == resolved_ordinary.runtime.accepted_user_content


@pytest.mark.asyncio
async def test_fresh_host_reconnects_same_episode_after_ordinary_gap(host_factory):
    old = host_factory()
    old.scope = old.math_scope()
    session, turn = await old.submit(A)
    original = old.state()
    first_id = old.math_contexts[-1].runtime.accepted_user_message_id
    old.scope = None
    await old.submit(A, session_id=session["id"])
    ordinary_id = old.ordinary_contexts[-1].runtime.accepted_user_message_id
    await old.close()
    fresh = host_factory(db=old.db)
    assert fresh.runtime is not old.runtime and fresh.coordinator is not old.coordinator
    assert fresh.store is not old.store and fresh.source is not old.source
    assert fresh.references == [] and fresh.runtime._executions == {}
    assert await fresh.coordinator.get_lease(turn["id"]) is None
    fresh.scope = fresh.math_scope()
    await fresh.submit(A, session_id=session["id"])
    returned_id = fresh.math_contexts[-1].runtime.accepted_user_message_id
    state = fresh.state()
    assert state["host_episode_first_message_id"] == first_id
    assert state["host_accepted_message_ids"] == [first_id, returned_id]
    assert ordinary_id not in state["host_accepted_message_ids"]
    assert {key: state["alignments"][key] for key in original["alignments"]} == original[
        "alignments"
    ]
    assert len(state["alignments"]) == 2
    assert_private_evidence_extension(original, state)
    assert state["confirmations"] == original["confirmations"]
    assert fresh.result()["trajectory"]["status"] == old.result()["trajectory"]["status"]
    assert fresh.result()["verification_status"] == "UNKNOWN"
    assert not fresh.result()["verified_grounded_refs"]
