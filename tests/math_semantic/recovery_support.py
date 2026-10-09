"""Test-only composition; every worker independently loads reviewed source DI."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, closing
from dataclasses import replace
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
from deeptutor.math_semantic.refs import LearnerRef, QuestionRef
from deeptutor.math_semantic.state import MathMutation, ReviewedSource
from deeptutor.math_semantic.support import resolve_math_content_support
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
    assert (before["episode"], before["session"], before["revision"]) == (
        after["episode"],
        after["session"],
        after["revision"],
    )
    assert new["host_episode_first_message_id"] == old["host_episode_first_message_id"]
    assert (
        new["host_accepted_message_ids"][: len(old["host_accepted_message_ids"])]
        == old["host_accepted_message_ids"]
    )
    assert len(new["alignments"]) == len(old["alignments"]) + new_alignments
    assert {key: new["alignments"][key] for key in old["alignments"]} == old["alignments"]
    assert new["snapshots"] == old["snapshots"]
    assert new["confirmations"] == old["confirmations"]
    assert not any("trajectory" in key and key != "trajectory_version" for key in new)
