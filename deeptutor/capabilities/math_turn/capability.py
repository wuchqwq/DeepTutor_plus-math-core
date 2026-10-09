"""Accepted host turns consume native mathematics through one commit authority.

Composition injects reviewed episode scope and the existing proposal provider.
Neither prompts nor request metadata can choose the mathematical source. This
module owns no acceptance, provider loop, session lifecycle or recovery policy.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import json
from typing import Any, cast

from deeptutor.core.capability_protocol import CapabilityManifest, StreamBusProtocol, TurnCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.math_semantic.accepted import AcceptedSubmission
from deeptutor.math_semantic.alignment import AlignmentEvaluator
from deeptutor.math_semantic.authority import MathSemanticGrant
from deeptutor.math_semantic.claims import ResponseAlignment
from deeptutor.math_semantic.codec import _payload
from deeptutor.math_semantic.proposals import (
    AlignmentProjection,
    AlignmentProposal,
    ResponseAlignmentProvider,
)
from deeptutor.math_semantic.state import MathMutation, ReviewedSource, confirm_method
from deeptutor.math_semantic.support import (
    materialize_operation_support,
    resolve_math_content_support,
)
from deeptutor.math_semantic.trajectory_types import TrajectoryProjection
from deeptutor.services.session.math_semantic_persistence import (
    MathEpisodeBinding,
    accepted_submission,
    sqlite_episode_mutation,
)
from deeptutor.tools.ask_user import AskUserOption, AskUserPayload, AskUserQuestion

from .output import accept_response, generate_response, publication_input


class MathTurnCapability(TurnCapability):
    manifest = CapabilityManifest(
        name="math_turn",
        description="Native accepted-turn mathematical evidence",
        stages=["alignment", "confirmation"],
    )

    def __init__(
        self,
        *,
        resolve_episode: Callable[[AcceptedSubmission], MathEpisodeBinding | ReviewedSource],
        provider: ResponseAlignmentProvider,
    ) -> None:
        self._resolve_episode = resolve_episode
        self._provider = provider

    async def run(self, context: UnifiedContext, stream: StreamBusProtocol) -> None:
        submission = accepted_submission(context.runtime, session_id=context.session_id)
        # Reject unsupported backends before any proposal/provider work.
        if context.runtime.run_durable_turn_mutation is None:
            raise ValueError("mathematical mutation requires protected host commit authority")
        selected = context.runtime.capability_binding
        if selected is None or selected.capability != self.name:
            raise ValueError("math turn requires a trusted host capability binding")
        binding = self._resolve_episode(submission)
        source = binding if isinstance(binding, ReviewedSource) else binding.source
        if selected.scope_id != source.identity.episode_id:
            raise ValueError("host capability binding differs from reviewed math episode")
        authority = sqlite_episode_mutation(
            context.runtime,
            session_id=context.session_id,
            binding=binding,
        )

        def prepare(state: MathMutation) -> tuple[int, AlignmentProjection]:
            snapshot = state.snapshot()
            return snapshot.workspace.revision, AlignmentEvaluator._project(
                state.submission.raw_content,
                snapshot,
            )

        revision, projection = await authority(prepare)
        # The provider only proposes. Native grounding/validation runs inside
        # the protected mutation against the same pinned revision.
        proposed = await asyncio.to_thread(self._provider.propose, projection)
        proposal = AlignmentProposal.from_value(proposed)

        def observe(state: MathMutation) -> tuple[ResponseAlignment, TrajectoryProjection, int]:
            alignment = state.align(
                proposal,
                expected_revision=revision,
                provider_id=self._provider.provider_id,
                config_digest=self._provider.model_config_digest,
                check_steps=True,
            )
            trajectory = state.trajectory()
            return alignment, trajectory, state.snapshot().workspace.revision

        alignment, trajectory, revision = await authority(observe)
        issued = trajectory.method_confirmation
        if issued is not None and issued.state == "pending":
            waiter = context.runtime.wait_for_user_reply
            if waiter is None:
                raise ValueError("method confirmation requires the host reply port")
            authored_paths = {path.path_id for path in source.authored.paths}
            if any(path not in authored_paths for _, path in issued.option_paths):
                raise ValueError("confirmation path is not in the reviewed authored source")
            # Authored method text is private semantic data, not disclosure
            # authority. Ordinals are display-only; Core-issued tokens own identity.
            labels = {
                token: f"Method {index}"
                for index, (token, _) in enumerate(issued.option_paths, start=1)
            }
            payload = AskUserPayload(
                questions=(
                    AskUserQuestion(
                        id=issued.confirmation_id,
                        prompt="Choose the method to continue.",
                        options=tuple(
                            AskUserOption(label=labels[token], option_id=token)
                            for token, _ in issued.option_paths
                        ),
                        allow_free_text=False,
                    ),
                )
            )
            await stream.emit(
                StreamEvent(
                    type=StreamEventType.TOOL_RESULT,
                    source=self.name,
                    metadata={
                        "tool": "ask_user",
                        "tool_call_id": issued.confirmation_id,
                        "tool_metadata": {"ask_user": payload.to_dict()},
                    },
                )
            )
            await stream.emit(StreamEvent(type=StreamEventType.WAIT_FOR_INPUT, source=self.name))
            reply = await waiter()
            answers = reply.get("answers") if isinstance(reply, dict) else None
            if not isinstance(answers, list) or len(answers) != 1:
                raise ValueError("method confirmation requires one exact opaque choice")
            answer = answers[0]
            if not isinstance(answer, dict) or answer.get("questionId") != issued.confirmation_id:
                raise ValueError("foreign or stale method confirmation reply")
            token = answer.get("selected_option_id")
            if not isinstance(token, str) or token not in dict(issued.option_paths):
                raise ValueError("invalid or stale method confirmation token")
            # Text/label/order never participates in identity. Core rechecks
            # ledger, source, episode, head and exact path mapping at commit.
            await confirm_method(authority, issued, option_token=token, expected_revision=revision)
            await stream.emit(
                StreamEvent(
                    type=StreamEventType.PROGRESS,
                    source=self.name,
                    metadata={
                        "ask_user_resolved": True,
                        "ask_user_tool_call_id": issued.confirmation_id,
                        "answers": [
                            {
                                "questionId": issued.confirmation_id,
                                "selected_option_id": token,
                                "text": labels[token],
                            }
                        ],
                    },
                )
            )

        def calculate(state: MathMutation) -> dict[str, Any]:
            current = state.trajectory()
            snapshot = state.snapshot()
            selected = current.applicable_artifact_refs
            # Applicability and literal identity are not truth verification.
            # Only grounded matches to independently verified artifacts can
            # enter the verified subset; unknown relations add nothing.
            verified = tuple(
                cast(str, item.artifact_id)
                for item in snapshot.artifacts
                if item.artifact_id in selected
                and item.artifact_id in alignment.matched_artifact_refs
                and item.verification_status == "verified"
            )
            grants = tuple(MathSemanticGrant.orientation(ref) for ref in selected)
            grants += tuple(
                binding.as_grant()
                for binding in resolve_math_content_support(snapshot, selected)
                if binding.act_kind in {"chosen_operation", "operation_options"}
                or (binding.act_kind == "result" and binding.target_artifact_ref in verified)
            )
            state.authorize(selected, grants)
            return {
                "episode_id": source.identity.episode_id,
                "accepted_user_message_id": state.submission.message_id,
                "alignment": json.loads(_payload(alignment)),
                "trajectory": current.to_dict(),
                "verified_grounded_refs": verified,
                "verification_status": "VERIFIED_FOR_LISTED_REFS" if verified else "UNKNOWN",
                "authority": tuple(grant.to_dict() for grant in grants),
            }

        snapshot, applicable = await authority(
            lambda state: (state.snapshot(), state.trajectory().applicable_artifact_refs)
        )
        # Existing tools execute outside the commit transaction. The native
        # revision fence rechecks the exact input before adopting their evidence.
        operations, evidence = await asyncio.to_thread(
            materialize_operation_support,
            snapshot,
            applicable,
            preferred_refs=alignment.matched_artifact_refs,
        )

        def prepare_publication(state: MathMutation) -> tuple[dict[str, Any], dict[str, Any]]:
            if state.snapshot() != snapshot:
                raise ValueError("operation input revision became stale")
            if operations or evidence:
                state.append(
                    expected_revision=snapshot.workspace.revision,
                    artifacts=operations,
                    evidence=evidence,
                )
            calculation = calculate(state)
            return calculation, publication_input(state, calculation)

        result, inputs = await authority(prepare_publication)
        # Canonical domain detail is private. In particular raw claim quotes
        # and confirmation ledgers are never final-response metadata.
        context.extension_state["math_turn"] = {"calculation": result}
        raw_candidate = await generate_response(context, inputs)
        publication_authority = sqlite_episode_mutation(
            context.runtime,
            session_id=context.session_id,
            binding=binding,
            record_publication=True,
        )
        accepted = await publication_authority(
            lambda state: accept_response(state, calculate(state), inputs, raw_candidate)
        )
        # Acceptance commits under the existing fence before any answer bytes
        # reach the host stream. There is no ordinary math-answer fallback.
        context.capability_output.accepted_output = accepted
        context.capability_output.agent_output = accepted.content
        context.capability_output.event_metadata = json.loads(accepted.metadata_json)
        await stream.emit(
            StreamEvent(
                type=StreamEventType.CONTENT,
                source=self.name,
                content=accepted.content,
                metadata=json.loads(accepted.metadata_json),
            )
        )
        await stream.emit(
            StreamEvent(
                type=StreamEventType.RESULT,
                source=self.name,
                metadata={"response": accepted.content, **json.loads(accepted.metadata_json)},
            )
        )
        context.capability_output.answer_published = True
