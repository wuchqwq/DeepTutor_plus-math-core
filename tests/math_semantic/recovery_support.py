"""Test-only composition; every worker independently loads reviewed source DI."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, closing
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from deeptutor.app.service import TurnApplicationService
from deeptutor.capabilities.math_turn.capability import MathTurnCapability
from deeptutor.core.context import CapabilityBinding
from deeptutor.math_semantic.accepted import EpisodeIdentity
from deeptutor.math_semantic.authority import MathSemanticGrant
from deeptutor.math_semantic.codec import _decode
from deeptutor.math_semantic.refs import LearnerRef, QuestionRef
from deeptutor.math_semantic.state import MathMutation, ReviewedSource
from deeptutor.math_semantic.support import (
    OPERATION_MECHANISM,
    OPERATION_SCOPE,
    resolve_math_content_support,
)
from deeptutor.math_semantic.validation import STEP_VERSION, step_basis
from deeptutor.math_semantic.workspace import _snapshot_from
from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.turn_engine import TurnEngine
from deeptutor.services.config.provider_runtime import ResolvedLLMConfig
from deeptutor.services.session.math_semantic_persistence import sqlite_episode_mutation
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager

A = "s=x+y"
B = "3*(x^2-x*y+y^2)-(x^2+x*y+y^2)=2*(x-y)^2"
C = "3*(x^2+x*y+y^2)-(x^2-x*y+y^2)=2*(x+y)^2"


async def harmless_generation(*_args, prompt, **_kwargs):
    """Offline transport for the actual native completion/generation seam."""
    inputs = json.loads(prompt)
    ids = [
        offer["grant_id"]
        for offer in inputs["offers"]
        if offer["grant"]["act_kind"] == "orientation"
    ][:1]
    return json.dumps({"authority_basis": inputs["authority_basis"], "grant_ids": ids})


def reviewed_source(*, unknown: bool = False) -> ReviewedSource:
    value = json.loads(
        Path(__file__).with_name("fixtures").joinpath("oracle.json").read_text(encoding="utf-8")
    )
    authored = _snapshot_from(json.dumps(value["snapshots"]["ca02"]))
    authored = replace(
        authored, workspace=replace(authored.workspace, workspace_id="durable-recovery-episode")
    )
    if unknown:
        authored = replace(
            authored,
            paths=authored.paths[:1],
            artifacts=tuple(
                replace(a, verification_status="not_checkable", verification_scope="")
                for a in authored.artifacts
            ),
        )
    return ReviewedSource(
        EpisodeIdentity(
            authored.workspace.workspace_id,
            LearnerRef("reviewed-space", "reviewed-learner"),
            QuestionRef(authored.problem_model.problem_id, authored.problem_model.revision),
        ),
        authored,
    )


class RecoveryHost:
    """Instrumentation around production run; no retained MathEpisodeBinding."""

    def __init__(
        self,
        db: Path,
        *,
        unknown: bool = False,
        advance: bool = False,
        inspect_history: bool = True,
    ):
        self.source = reviewed_source(unknown=unknown)
        self.unknown, self.advance = unknown, advance
        self.inspect_history = inspect_history
        self.contexts, self.completed, self.errors, self.history = [], [], [], []
        self.patches = ExitStack()
        self.patches.enter_context(
            patch("deeptutor.services.skill.runtime.skill_manifest", lambda: "")
        )
        # Subprocess workers do not run pytest's autouse config fixture. Use
        # that same isolated resolver; the injected alignment provider never
        # makes an LLM request.
        self.patches.enter_context(
            patch(
                "deeptutor.services.llm.config.resolve_llm_runtime_config",
                lambda *_args, **_kwargs: ResolvedLLMConfig(
                    model="gpt-4o-mini",
                    provider_name="openai",
                    provider_mode="direct",
                    binding="openai",
                    api_key="sk-test",
                    base_url="https://api.openai.com/v1",
                    effective_url="https://api.openai.com/v1",
                    context_window=128000,
                ),
            )
        )
        self.patches.enter_context(patch("deeptutor.services.llm.config._LLM_CONFIG_CACHE", None))
        self.patches.enter_context(
            patch(
                "deeptutor.services.llm.factory._complete_with_resolved_config", harmless_generation
            )
        )
        host = self

        class Provider:
            provider_id = "recovery-test-proposal"
            model_config_digest = "same-reviewed-test-configuration"

            def propose(self, projection):
                text = projection.response_text.strip()
                return {
                    "claims": [
                        {
                            "evidence": {"quote": text},
                            "candidate_artifact_refs": [
                                a.artifact_id for a in projection.artifacts if a.statement == text
                            ],
                            "parse_status": "unparsed"
                            if text == "unsupported semantic relation"
                            else "parsed",
                        }
                    ]
                }

        class Observed(MathTurnCapability):
            def __init__(self):
                # DI provides identity/content, NEVER historical start or IDs.
                super().__init__(resolve_episode=lambda _accepted: host.source, provider=Provider())

            async def run(self, context, stream):
                host.contexts.append(context)
                try:
                    if not host.inspect_history:
                        await super().run(context, stream)
                        host.completed.append(context.runtime.turn_id)
                        return
                    authority = sqlite_episode_mutation(
                        context.runtime, session_id=context.session_id, binding=host.source
                    )

                    def replay(state):
                        if len(state.prefix) == 1 and host.advance:
                            state.append(
                                expected_revision=state.snapshot().workspace.revision,
                                status="partial",
                            )
                        if len(state.prefix) <= 1:
                            return None
                        # Reconstruct exactly the already committed cutoff in
                        # a transaction-local READ projection. No old context,
                        # runtime, binding, IDs or projection is supplied.
                        history = MathMutation(
                            state.source, state.prefix[-2], state.prefix[:-1], state.serialize()
                        )
                        before = history.serialize()
                        trajectory = history.trajectory()
                        grants = tuple(
                            MathSemanticGrant.orientation(ref)
                            for ref in trajectory.applicable_artifact_refs
                        )
                        grants += tuple(
                            binding.as_grant()
                            for binding in resolve_math_content_support(
                                history.snapshot(), trajectory.applicable_artifact_refs
                            )
                            if binding.act_kind in {"chosen_operation", "operation_options"}
                        )
                        history.authorize(trajectory.applicable_artifact_refs, grants)
                        assert history.serialize() == before, (
                            "historical reconstruction rewrote math evidence"
                        )
                        return {
                            "trajectory": trajectory.to_dict(),
                            "head": history.snapshot().workspace.revision,
                            "prefix": [item.message_id for item in history.prefix],
                            "authority": [grant.to_dict() for grant in grants],
                        }

                    host.history.append(await authority(replay))
                    await super().run(context, stream)
                    host.completed.append(context.runtime.turn_id)
                except Exception as exc:
                    host.errors.append(exc)
                    raise

        registry = CapabilityRegistry()
        registry.register(Observed)

        async def host_scope(_reference):
            return CapabilityBinding("math_turn", host.source.identity.episode_id)

        self.store = SQLiteSessionStore(db)
        self.coordinator = MemoryCoordinator()
        self.runtime = TurnRuntimeManager(
            self.store,
            coordinator=self.coordinator,
            owner_id="fresh-recovery-worker",
            turn_engine=TurnEngine(
                capability_registry=registry, resolve_accepted_capability=host_scope
            ),
        )

        async def no_title(**_kwargs):
            pass

        self.runtime._maybe_generate_session_title = no_title
        self.application = TurnApplicationService(
            SimpleNamespace(get=lambda: self.store),
            SimpleNamespace(get=lambda _store: self.runtime),
            self.coordinator,
        )

    async def close(self):
        await self.runtime.close()
        await self.coordinator.close()
        self.patches.close()

    async def start(self, content, *, session_id=None, application=False):
        payload = {
            "content": content,
            "capability": "math_turn",
            "auto_route": False,
            "tools": [],
            "knowledge_bases": [],
            "language": "en",
        }
        if session_id:
            payload["session_id"] = session_id
        entry = self.application if application else self.runtime
        return await entry.start_turn(payload)

    async def finish(self, turn, *, error=None):
        task = self.runtime._executions[turn["id"]].task
        assert task is not None
        await asyncio.wait_for(task, 20)
        if error:
            assert turn["id"] not in self.completed
            assert self.errors and error in str(self.errors[-1]), self.errors
            assert not self.contexts[-1].capability_output.event_metadata
        else:
            assert turn["id"] in self.completed, self.errors
            assert not self.errors

    async def submit(self, content, *, session_id=None, application=False):
        session, turn = await self.start(content, session_id=session_id, application=application)
        await self.finish(turn)
        return session, turn

    async def choice(self, turn):
        async with asyncio.timeout(15):
            events = self.runtime.subscribe_turn(turn["id"])
            card = None
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
                row = await self.store.get_turn(turn["id"])
                if row["status"] == "waiting_input" and card:
                    return card
                assert not self.errors, self.errors
                await asyncio.sleep(0.01)

    async def answer(self, turn, card, *, token=None, question_id=None):
        token = token if token is not None else card["options"][-1]["option_id"]
        assert await self.runtime.submit_user_reply(
            turn["id"],
            answers=[
                {
                    "questionId": question_id or card["id"],
                    "selected_option_id": token,
                    "text": "untrusted display text",
                }
            ],
        )

    def result(self):
        return self.contexts[-1].extension_state["math_turn"]["calculation"]


def durable(db: Path):
    with closing(sqlite3.connect(db)) as connection:
        rows = connection.execute(
            "SELECT episode_id, session_id, math_revision, payload_json FROM math_semantic_episodes"
        ).fetchall()
        assert len(rows) == 1
        episode, session, revision, payload = rows[0]
        return {
            "episode": episode,
            "session": session,
            "revision": revision,
            "state": json.loads(payload),
        }


def assert_evidence_preserved(before, after, *, new_alignments):
    old, new = before["state"], after["state"]
    assert (before["episode"], before["session"]) == (
        after["episode"],
        after["session"],
    )
    assert before["revision"] == old["head"] and after["revision"] == new["head"]
    assert new["host_episode_first_message_id"] == old["host_episode_first_message_id"]
    assert (
        new["host_accepted_message_ids"][: len(old["host_accepted_message_ids"])]
        == old["host_accepted_message_ids"]
    )
    assert len(new["alignments"]) == len(old["alignments"]) + new_alignments
    assert {key: new["alignments"][key] for key in old["alignments"]} == old["alignments"]
    assert_private_evidence_extension(old, new)
    assert new["confirmations"] == old["confirmations"]
    assert not any("trajectory" in key and key != "trajectory_version" for key in new)


def assert_private_evidence_extension(old, new):
    """Exact history plus only scoped evidence and existing operation rebinding."""
    assert {key: new["snapshots"][key] for key in old["snapshots"]} == old["snapshots"]
    added = [
        _decode(value) for key, value in new["alignments"].items() if key not in old["alignments"]
    ]
    claim_proofs = {}
    for alignment in added:
        assert not alignment.novel_candidates
        assert not alignment.validated_artifact_refs
        assert not alignment.contradicted_artifact_refs
        for evidence in alignment.math_evidence:
            claim_proofs[evidence.evidence_id] = evidence
            if evidence.tool_version == STEP_VERSION:
                binding = json.loads(evidence.input_summary)
                assert binding["revision"] == alignment.workspace_revision
                assert binding["episode"] == new["source"]["episode_id"]
                assert binding["claim"] in [asdict(c) for c in alignment.claims]
                pinned = _snapshot_from(
                    json.dumps(new["snapshots"][str(alignment.workspace_revision)])
                )
                assert binding["math_basis"] == step_basis(pinned)
                assert binding["claim"]["student_response_ref"] == {
                    "kind": alignment.student_response_ref.kind,
                    "identifier": alignment.student_response_ref.identifier,
                }
    assert set(new["snapshots"]) - set(old["snapshots"]) == {
        str(revision) for revision in range(old["head"] + 1, new["head"] + 1)
    }
    assert new["head"] - old["head"] >= len(added)
    previous = _snapshot_from(json.dumps(old["snapshots"][str(old["head"])]))
    for revision in range(old["head"] + 1, new["head"] + 1):
        current = _snapshot_from(json.dumps(new["snapshots"][str(revision)]))
        assert current.problem_model == previous.problem_model
        assert current.paths == previous.paths and current.relations == previous.relations
        assert current.superseded_by == previous.superseded_by
        assert current.artifacts[: len(previous.artifacts)] == previous.artifacts
        assert current.tool_evidence[: len(previous.tool_evidence)] == previous.tool_evidence
        # append_snapshot regenerates membership indices from actual objects;
        # the frozen legacy fixture contains one removed-path index. This
        # checks that exact regeneration rather than ignoring path metadata.
        assert current.workspace == replace(
            previous.workspace,
            revision=revision,
            artifact_refs=tuple(a.artifact_id for a in current.artifacts),
            solution_path_refs=tuple(p.path_id for p in current.paths),
            dependency_relation_refs=tuple(r.relation_id for r in current.relations),
            tool_evidence_refs=tuple(e.evidence_id for e in current.tool_evidence),
        )
        artifacts = current.artifacts[len(previous.artifacts) :]
        receipts = current.tool_evidence[len(previous.tool_evidence) :]
        assert receipts
        targets = tuple(
            a.artifact_id for a in previous.artifacts if a.claim_kind != "operation_description"
        )

        def permissions(snapshot):
            return {
                (b.target_artifact_ref, b.act_kind, b.support_mechanism, b.support_scope)
                for b in resolve_math_content_support(snapshot, targets)
            }

        baseline = _snapshot_from(json.dumps(old["snapshots"][str(old["head"])]))
        if artifacts:
            # Existing calculation rebinds the same supported operations.
            assert permissions(current) == permissions(baseline)
        else:
            # Existing typed support is current-revision-only: evidence first
            # expires it; calculation may subsequently rebind it. Other support
            # remains exact, and no intermediate permission is added.
            assert permissions(current) == {
                p for p in permissions(previous) if p[2] != OPERATION_MECHANISM
            }
        operation_proofs = set()
        old_operations = []
        for artifact in previous.artifacts:
            if (
                artifact.claim_kind == "operation_description"
                and artifact.verification_scope == OPERATION_SCOPE
            ):
                request = json.loads(artifact.statement)
                request.pop("input_revision")
                old_operations.append(request)
        for artifact in artifacts:
            assert artifact.claim_kind == "operation_description"
            request = json.loads(artifact.statement)
            assert request.pop("input_revision") == previous.workspace.revision
            assert request in old_operations
            assert artifact.verification_status == "qualified"
            assert artifact.workspace_revision == revision
            operation_proofs.update(artifact.tool_evidence_refs)
        supported_proofs = {
            b.support_ref.identifier
            for b in resolve_math_content_support(current, targets)
            if b.support_ref is not None
        }
        assert operation_proofs <= supported_proofs
        for evidence in receipts:
            assert replace(evidence, evidence_id=None).evidence_id == evidence.evidence_id
            assert (
                evidence.evidence_id in operation_proofs
                or claim_proofs.get(evidence.evidence_id) == evidence
            )
        previous = current
