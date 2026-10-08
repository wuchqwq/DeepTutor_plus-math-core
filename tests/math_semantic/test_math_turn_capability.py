"""Production capability exercised by real persisted, coordinated host turns."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from threading import Event
from types import SimpleNamespace

import pytest
import pytest_asyncio

from deeptutor.capabilities.math_turn.capability import MathTurnCapability
from deeptutor.core.context import CapabilityBinding
from deeptutor.math_semantic.accepted import EpisodeIdentity
from deeptutor.math_semantic.codec import _decode
from deeptutor.math_semantic.refs import LearnerRef, QuestionRef
from deeptutor.math_semantic.state import ReviewedSource
from deeptutor.math_semantic.workspace import _snapshot_from
from deeptutor.runtime.coordination import MemoryCoordinator, RedisCoordinator
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.turn_engine import TurnEngine
from deeptutor.services.session.math_semantic_persistence import (
    MathEpisodeBinding,
)
from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager
from tests.services.session.test_pocketbase_store_fallbacks import _FakeClient

A = "s=x+y"
B = "3*(x^2-x*y+y^2)-(x^2+x*y+y^2)=2*(x-y)^2"
RAW = "  Q=3-2*x*y\n"


@pytest_asyncio.fixture
async def host(tmp_path, monkeypatch):
    oracle = json.loads(
        Path(__file__).with_name("fixtures").joinpath("oracle.json").read_text(encoding="utf-8")
    )
    snapshot = _snapshot_from(json.dumps(oracle["snapshots"]["ca02"]))
    value = SimpleNamespace(
        contexts=[],
        completed=[],
        errors=[],
        projections=[],
        binding=None,
        snapshot=snapshot,
        episode="episode-one",
        before=None,
        mode="normal",
        propose_hook=None,
    )

    def resolve(submission):
        if value.binding is None:
            authored = replace(
                value.snapshot,
                workspace=replace(value.snapshot.workspace, workspace_id=value.episode),
            )
            value.binding = MathEpisodeBinding(
                submission.session_id,
                submission.message_id,
                ReviewedSource(
                    EpisodeIdentity(
                        value.episode,
                        LearnerRef("trusted-space", "trusted-learner"),
                        QuestionRef(
                            authored.problem_model.problem_id, authored.problem_model.revision
                        ),
                    ),
                    authored,
                ),
            )
        return value.binding

    class Provider:
        provider_id = "injected-proposal-provider"
        model_config_digest = "bounded-test-proposal"

        def propose(self, projection):
            value.projections.append(projection)
            if value.propose_hook:
                value.propose_hook()
            quote = projection.response_text.strip()
            if value.mode == "missing_grounding":
                quote = "unaccepted evidence"
            candidates = [a.artifact_id for a in projection.artifacts if a.statement == quote]
            return {
                "claims": [
                    {
                        "evidence": {"quote": quote},
                        "candidate_artifact_refs": candidates,
                        "parse_status": "unparsed" if value.mode == "unsupported" else "parsed",
                    }
                ]
            }

    class ObservedMath(MathTurnCapability):
        def __init__(self):
            super().__init__(resolve_episode=resolve, provider=Provider())

        async def run(self, context, stream):
            value.contexts.append(context)
            try:
                if value.before:
                    await value.before(context)
                await super().run(context, stream)
                value.completed.append(context.runtime.turn_id)
            except Exception as exc:
                value.errors.append(exc)
                raise

    registry = CapabilityRegistry()
    registry.register(ObservedMath)

    async def host_scope(_reference):
        episode = value.binding.source.identity.episode_id if value.binding else value.episode
        return CapabilityBinding("math_turn", episode)

    value.store = SQLiteSessionStore(tmp_path / "capability.db")
    value.runtime = TurnRuntimeManager(
        value.store,
        coordinator=MemoryCoordinator(),
        owner_id="native-math-worker",
        turn_engine=TurnEngine(
            capability_registry=registry, resolve_accepted_capability=host_scope
        ),
    )

    async def no_title(**_kwargs):
        pass

    monkeypatch.setattr(value.runtime, "_maybe_generate_session_title", no_title)
    monkeypatch.setattr("deeptutor.services.skill.runtime.skill_manifest", lambda: "")
    try:
        yield value
    finally:
        await value.runtime.close()
        await value.runtime.coordinator.close()


async def start(host, **overrides):
    return await host.runtime.start_turn(
        {
            "content": RAW,
            "capability": "math_turn",
            "auto_route": False,
            "tools": [],
            "knowledge_bases": [],
            "language": "en",
            **overrides,
        }
    )


async def finish(host, turn, *, error=None):
    task = host.runtime._executions[turn["id"]].task
    assert task is not None
    await asyncio.wait_for(task, 20)
    if error:
        assert turn["id"] not in host.completed
        assert host.errors and error in str(host.errors[-1])
        assert not host.contexts[-1].capability_output.event_metadata
    else:
        assert turn["id"] in host.completed, host.errors
        assert not host.errors


async def submit(host, **overrides):
    session, turn = await start(host, **overrides)
    await finish(host, turn)
    return session, turn


def episodes(host):
    with sqlite3.connect(host.store.db_path) as db:
        return {
            row[0]: json.loads(row[1])
            for row in db.execute("SELECT episode_id, payload_json FROM math_semantic_episodes")
        }


def result(host):
    return host.contexts[-1].extension_state["math_turn"]["calculation"]


async def wait_for_choice(host, turn):
    async with asyncio.timeout(15):
        card = None
        events = host.runtime.subscribe_turn(turn["id"])
        try:
            async for event in events:
                payload = event.get("metadata", {}).get("tool_metadata", {}).get("ask_user")
                if payload:
                    card = payload["questions"][0]
                if event["type"] == "wait_for_input" and card:
                    break
        finally:
            await events.aclose()
        while True:
            row = await host.store.get_turn(turn["id"])
            if row["status"] == "waiting_input" and card:
                return card
            assert not host.errors, host.errors
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_real_raw_identity_and_identical_submissions(host):
    session, _ = await submit(
        host,
        client_submission_id="first",
        attachments=[
            {
                "type": "file",
                "filename": "notes.txt",
                "mime_type": "text/plain",
                "base64": base64.b64encode(b"Unaccepted Q=9999").decode(),
            }
        ],
    )
    await submit(host, session_id=session["id"], client_submission_id="second")
    users = [row for row in await host.store.get_messages(session["id"]) if row["role"] == "user"]
    assert len(users) == 2 and users[0]["id"] != users[1]["id"]
    assert "Unaccepted Q=9999" in host.contexts[0].user_message
    for context, user, projection in zip(host.contexts, users, host.projections, strict=True):
        assert context.runtime.accepted_user_message_id == user["id"]
        assert (
            context.runtime.accepted_user_content
            == user["content"]
            == projection.response_text
            == RAW
        )
        assert context.runtime.client_submission_id == user["metadata"]["client_submission_id"]
    record = episodes(host)["episode-one"]
    assert record["host_accepted_message_ids"] == [u["id"] for u in users]
    alignments = [_decode(a) for a in record["alignments"].values()]
    assert {a.student_response_ref.identifier for a in alignments} == {str(u["id"]) for u in users}
    assert len({a.claims[0].claim_id for a in alignments}) == 2
    for alignment in alignments:
        claim = alignment.claims[0]
        assert RAW[claim.evidence.start : claim.evidence.end] == claim.evidence.quote
    assert result(host)["trajectory"]["cutoff_turn"] == 2
    assert result(host)["authority"]


@pytest.mark.asyncio
async def test_same_question_new_episode_is_independent_and_old_interval_closed(host):
    session, _ = await submit(host, content=A)
    first_binding, first = host.binding, episodes(host)["episode-one"]
    host.binding = None
    host.episode = "episode-two"
    await submit(host, session_id=session["id"], content=B)
    records = episodes(host)
    assert records["episode-one"] == first
    assert (
        records["episode-one"]["source"]["question_ref"]
        == records["episode-two"]["source"]["question_ref"]
    )
    assert set(records["episode-one"]["host_accepted_message_ids"]).isdisjoint(
        records["episode-two"]["host_accepted_message_ids"]
    )
    assert result(host)["trajectory"]["cutoff_turn"] == 1
    assert (
        result(host)["trajectory"]["compatible_path_refs"]
        != host.contexts[0].extension_state["math_turn"]["calculation"]["trajectory"][
            "compatible_path_refs"
        ]
    )
    assert not records["episode-two"]["confirmations"]
    host.binding = first_binding
    _, turn = await start(host, session_id=session["id"])
    await finish(host, turn, error="superseded")
    assert episodes(host) == records


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["non_persist", "regenerate"])
async def test_reexecution_without_new_acceptance_fails_closed(host, path):
    session, _ = await submit(host)
    before, calls = episodes(host), len(host.projections)
    if path == "non_persist":
        _, turn = await start(host, session_id=session["id"], persist_user_message=False)
    else:
        _, turn = await host.runtime.regenerate_last_turn(
            session["id"], overrides={"auto_route": False}
        )
    await finish(host, turn, error="no newly accepted submission")
    assert host.contexts[-1].runtime.accepted_user_message_id is None
    assert episodes(host) == before and len(host.projections) == calls


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["id", "raw", "client", "port", "lease"])
async def test_missing_or_changed_authority_cannot_write(host, damage):
    async def alter(context):
        runtime = context.runtime
        if damage == "id":
            runtime.accepted_user_message_id = -1
        elif damage == "raw":
            runtime.accepted_user_content = "forged"
        elif damage == "client":
            runtime.client_submission_id = "forged"
        elif damage == "port":
            runtime.run_durable_turn_mutation = None
        else:
            await host.runtime.coordinator.release_turn(runtime.turn_lease)

    host.before = alter
    _, turn = await start(host)
    await finish(
        host,
        turn,
        error={
            "id": "missing",
            "raw": "differs",
            "client": "differs",
            "port": "authority",
            "lease": "authority",
        }[damage],
    )
    assert episodes(host) == {} and host.projections == []


@pytest.mark.asyncio
async def test_uncoordinated_runtime_and_redis_binding_never_fall_back(host):
    # Actual Redis pairing refusal is the store binder's public contract.
    session, _ = await submit(host)
    context = host.contexts[-1]
    redis = RedisCoordinator("", client=object())
    assert (
        host.store.bind_durable_turn_mutation(
            redis, context.runtime.turn_lease, session_id=session["id"]
        )
        is None
    )
    before = episodes(host)
    coordinator = host.runtime.coordinator
    host.runtime.coordinator = None
    try:
        _, turn = await start(host, session_id=session["id"])
        await finish(host, turn, error="protected host commit authority")
        assert host.contexts[-1].runtime.run_durable_turn_mutation is None
        assert episodes(host) == before
    finally:
        host.runtime.coordinator = coordinator


@pytest.mark.asyncio
async def test_actual_pocketbase_runtime_rejects_math_without_normal_write_fallback(
    host, monkeypatch
):
    client = _FakeClient()
    monkeypatch.setattr("deeptutor.services.pocketbase_client.get_pb_client", lambda: client)
    runtime = host.runtime
    store = PocketBaseSessionStore()
    pb = TurnRuntimeManager(
        store,
        coordinator=MemoryCoordinator(),
        owner_id="pb-worker",
        turn_engine=runtime.turn_engine,
    )
    monkeypatch.setattr(pb, "_maybe_generate_session_title", runtime._maybe_generate_session_title)
    host.runtime = pb
    try:
        session, turn = await start(host)
        await finish(host, turn, error="protected host commit authority")
        rows = await store.get_messages(session["id"])
        assert rows[0]["role"] == "user" and rows[0]["content"] == RAW
        assert host.contexts[-1].runtime.accepted_user_message_id == rows[0]["id"]
        assert host.contexts[-1].runtime.run_durable_turn_mutation is None
        assert host.binding is None and host.projections == [] and episodes(host) == {}
    finally:
        await pb.close()
        await pb.coordinator.close()
        host.runtime = runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["exact", "forged", "label", "path_ref", "stale", "head_drift"])
async def test_real_method_confirmation_token_transport_and_scope(host, choice, monkeypatch):
    if choice == "head_drift":
        from deeptutor.capabilities.math_turn import capability

        original = capability.confirm_method

        async def drift_then_confirm(authority, issued, **kwargs):
            # Fault window after the REAL waiter restores running, immediately
            # before resolution. Even the injection uses protected host commit.
            await authority(
                lambda state: state.append(
                    expected_revision=state.snapshot().workspace.revision, status="partial"
                )
            )
            return await original(authority, issued, **kwargs)

        monkeypatch.setattr(capability, "confirm_method", drift_then_confirm)
    session, _ = await submit(host, content=A)
    _, turn = await start(host, session_id=session["id"], content=B)
    card = await wait_for_choice(host, turn)
    before = episodes(host)
    issued = before["episode-one"]["confirmations"][card["id"]]
    token, path = issued["option_paths"][-1]
    assert card["options"][-1]["option_id"] == token
    label = card["options"][-1]["label"]
    assert token != label and path != label
    assert label == next(
        p.method.replace("_", " ").capitalize()
        for p in host.binding.source.authored.paths
        if p.path_id == path
    )
    answers = [
        {
            "questionId": "stale" if choice == "stale" else card["id"],
            "text": "a completely different label",
            "selected_option_id": label
            if choice == "label"
            else path
            if choice == "path_ref"
            else "forged"
            if choice == "forged"
            else token,
        }
    ]
    assert await host.runtime.submit_user_reply(turn["id"], answers=answers)
    if choice == "exact":
        await finish(host, turn)
        resolved = episodes(host)["episode-one"]["confirmations"][card["id"]]
        assert resolved["state"] == "resolved" and resolved["chosen_path_ref"] == path
        # Choice applies to future turns, never rewrites current math evidence.
        assert result(host)["trajectory"]["status"] == "METHOD_CONFIRMATION_REQUIRED"
        await submit(host, session_id=session["id"], content=B)
        assert result(host)["trajectory"]["compatible_path_refs"] == (path,)
    else:
        await finish(
            host, turn, error="scope changed" if choice == "head_drift" else "confirmation"
        )
        after = episodes(host)
        if choice == "head_drift":
            assert after["episode-one"]["confirmations"][card["id"]]["state"] == "invalidated"
        else:
            assert after == before


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["unsupported", "no_domain_validation", "missing_grounding"])
async def test_path_reconstruction_never_upgrades_unverified_math(host, mode):
    host.mode = mode
    host.snapshot = replace(
        host.snapshot,
        paths=host.snapshot.paths[:1],
        artifacts=tuple(
            replace(a, verification_status="not_checkable", verification_scope="")
            for a in host.snapshot.artifacts
        ),
    )
    _, turn = await start(host, content=A)
    if mode == "missing_grounding":
        await finish(host, turn, error="does not match")
        assert not episodes(host)["episode-one"]["alignments"]
    else:
        await finish(host, turn)
        outcome = result(host)
        assert outcome["trajectory"]["authored_path_refs"]
        assert (
            outcome["verified_grounded_refs"] == () and outcome["verification_status"] == "UNKNOWN"
        )
        assert all(grant["act_kind"] == "orientation" for grant in outcome["authority"])
        assert all(
            a["verification_status"] == "not_checkable"
            for a in episodes(host)["episode-one"]["authored"]["artifacts"]
        )
        if mode == "unsupported":
            assert outcome["trajectory"]["status"] == "UNKNOWN"
            assert all(
                r["relation_type"] == "unresolved" for r in outcome["alignment"]["relations"]
            )
        else:
            assert outcome["trajectory"]["status"] == "SUPPORTED"
            assert outcome["alignment"]["matched_artifact_refs"]


def test_capability_is_not_in_default_product_routing():
    from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_SPECS

    assert "math_turn" not in BUILTIN_CAPABILITY_SPECS


@pytest.mark.asyncio
async def test_ownership_lost_between_proposal_and_alignment_commit(host):
    entered, resume = Event(), Event()

    def pause():
        entered.set()
        assert resume.wait(10), "test did not resume proposal"

    host.propose_hook = pause
    _, turn = await start(host)
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        before = episodes(host)
        assert not before["episode-one"]["alignments"]
        await host.runtime.coordinator.release_turn(host.contexts[-1].runtime.turn_lease)
        resume.set()
        await finish(host, turn, error="authority")
        assert episodes(host) == before
    finally:
        resume.set()


@pytest.mark.asyncio
async def test_missing_historical_accepted_basis_rejects_new_math_write(host):
    session, _ = await submit(host)
    first_id = host.contexts[0].runtime.accepted_user_message_id
    before = episodes(host)

    async def remove_basis(context):
        # Deliberate host evidence deletion, using the same protected port.
        await context.runtime.run_durable_turn_mutation(
            lambda sql: sql("DELETE FROM messages WHERE id = ?", (first_id,))
        )

    host.before = remove_basis
    _, turn = await start(host, session_id=session["id"])
    await finish(host, turn, error="prefix is missing")
    assert episodes(host) == before


@pytest.mark.asyncio
async def test_plain_user_row_without_host_acceptance_turn_is_not_prefix_evidence(host):
    session, _ = await submit(host)
    before = episodes(host)
    unowned_id = await host.store.add_message(
        session["id"], "user", "a stored row without accepted turn"
    )
    await submit(host, session_id=session["id"])
    after = episodes(host)["episode-one"]
    assert unowned_id not in after["host_accepted_message_ids"]
    assert len(after["host_accepted_message_ids"]) == result(host)["trajectory"]["cutoff_turn"] == 2
    assert len(after["alignments"]) == len(before["episode-one"]["alignments"]) + 1
