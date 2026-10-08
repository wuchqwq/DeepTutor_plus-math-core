"""Math Turn capability: the protected-math channel through DeepTutor's turn seam.

DeepTutor owns the session, turn lifecycle, UI, structured ``ask_user`` display
and publication. The math engine owns alignment, trajectory regions, method
confirmation identity and the option-token -> path mapping. This capability is
the one thin seam between them: it resolves an authenticated session to a
reviewed math episode, drives one turn, and publishes only what the math
engine's bounded authority permits.

It never streams a provider answer before that authority exists, never infers a
path from a label or free text, and fails closed when no trusted reviewed
binding is wired for the turn.
"""

from __future__ import annotations

from typing import Any, cast

from deeptutor.capabilities.math_turn.engine import (
    MathTurnEngine,
    MathTurnOutcome,
    MathTurnUnavailable,
    get_math_turn_engine,
)
from deeptutor.core.capability_protocol import (
    CapabilityManifest,
    StreamBusProtocol,
    TurnCapability,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus
from deeptutor.tools.ask_user import build_ask_user_payload

#: Fixed, non-math copy shown when a protected turn cannot be served. It never
#: echoes rejected content and never falls back to generic chat.
UNAVAILABLE_MESSAGE = "Protected math is unavailable for this turn."

METHOD_CONFIRMATION_PROMPT = "Which method should we continue with?"


def build_method_confirmation_payload(outcome: MathTurnOutcome) -> dict[str, Any]:
    """Map a math ``MethodConfirmation`` onto the host's structured ask card.

    Mapping is exact and display-independent: ``confirmation_id`` -> the
    question identity, each math option token -> ``AskUserOption.option_id``,
    and the human method name -> the label (presentation only).
    """
    question = {
        "id": outcome.confirmation_id,
        "prompt": METHOD_CONFIRMATION_PROMPT,
        "header": "Method",
        "multi_select": False,
        "allow_free_text": False,
        "options": [
            {
                "label": option.label,
                "description": option.description or None,
                "option_id": option.token,
            }
            for option in outcome.options
        ],
    }
    payload, error = build_ask_user_payload(questions=[question])
    if payload is None:  # pragma: no cover - defensive
        raise MathTurnUnavailable(error or "method confirmation payload rejected")
    return payload.to_dict()


def selected_option_id(reply: Any, question_id: str) -> str:
    """Read the structured ``selected_option_id`` for one question, or refuse.

    Only the opaque option identity is authority-bearing. Free text or a missing
    selection is rejected; the caller must not fall back to a label.
    """
    answers = reply.get("answers") if isinstance(reply, dict) else None
    if not isinstance(answers, list):
        raise MathTurnUnavailable("method confirmation requires a structured selection")
    for entry in answers:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("questionId") or entry.get("id") or "").strip()
        if entry_id != question_id:
            continue
        option_id = entry.get("selected_option_id")
        if isinstance(option_id, str) and option_id.strip():
            return option_id
    raise MathTurnUnavailable("method confirmation requires a structured selection")


class MathTurnCapability(TurnCapability):
    manifest = CapabilityManifest(
        name="math_turn",
        description=(
            "Protected math tutoring turn owned by the math engine: alignment, "
            "trajectory region, and structured method confirmation."
        ),
        stages=["authority", "publish"],
        tools_used=[],
        cli_aliases=["math"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBusProtocol) -> None:
        bus = cast(StreamBus, stream)
        engine = get_math_turn_engine()
        if engine is None or not engine.is_bound(context.session_id):
            await self._fail_closed(context, bus)
            return
        try:
            outcome = engine.run_turn(context.session_id, context.user_message)
        except MathTurnUnavailable:
            await self._fail_closed(context, bus)
            return

        # Authority now exists. Nothing student-facing has been emitted yet.
        await self._emit_authority(bus, outcome)

        if outcome.confirmation_id is not None:
            try:
                chosen = await self._resolve_method_confirmation(context, bus, engine, outcome)
            except (MathTurnUnavailable, ValueError):
                await self._fail_closed(context, bus)
                return
            approved = self._resolved_output(engine, chosen)
        else:
            approved = outcome.approved_output

        context.capability_output.agent_output = approved
        await bus.result(
            {
                "response": approved,
                "metadata": {
                    "math_authority": outcome.status,
                    "trajectory_version": outcome.trajectory_version,
                },
            },
            source=self.name,
        )

    async def _emit_authority(self, stream: StreamBus, outcome: MathTurnOutcome) -> None:
        """Publish the bounded authority result (no math content) before output."""
        await stream.progress(
            "",
            source=self.name,
            stage="authority",
            metadata={
                "trace_kind": "math_authority",
                "math_status": outcome.status,
                "trajectory_version": outcome.trajectory_version,
                "compatible_path_refs": list(outcome.compatible_path_refs),
                "applicable_artifact_refs": list(outcome.applicable_artifact_refs),
                "method_confirmation_required": outcome.confirmation_id is not None,
            },
        )

    async def _resolve_method_confirmation(
        self,
        context: UnifiedContext,
        stream: StreamBus,
        engine: MathTurnEngine,
        outcome: MathTurnOutcome,
    ) -> str:
        confirmation_id = cast(str, outcome.confirmation_id)
        payload = build_method_confirmation_payload(outcome)
        call_id = f"method-confirmation:{confirmation_id}"
        await stream.tool_result(
            tool_name="ask_user",
            result=METHOD_CONFIRMATION_PROMPT,
            source=self.name,
            stage="authority",
            metadata={
                "trace_kind": "tool_result",
                "tool_call_id": call_id,
                "tool_metadata": {"ask_user": payload},
            },
        )
        waiter = context.runtime.wait_for_user_reply
        if not callable(waiter):
            raise MathTurnUnavailable("no structured reply channel for method confirmation")
        reply = await waiter()
        if reply is None:
            raise MathTurnUnavailable("method confirmation was not answered")
        option_token = selected_option_id(reply, confirmation_id)
        await stream.progress(
            "",
            source=self.name,
            stage="authority",
            metadata={
                "trace_kind": "user_reply",
                "ask_user_resolved": True,
                "ask_user_tool_call_id": call_id,
            },
        )
        return engine.resolve(context.session_id, confirmation_id, option_token)

    @staticmethod
    def _resolved_output(engine: MathTurnEngine, chosen_path_ref: str) -> str:
        label = engine._method_labels().get(chosen_path_ref, chosen_path_ref)
        return (
            "Method confirmation resolved by the math engine. "
            f"Continuing on the selected path: {label}."
        )

    async def _fail_closed(self, context: UnifiedContext, stream: StreamBus) -> None:
        context.capability_output.agent_output = ""
        await stream.error(
            UNAVAILABLE_MESSAGE,
            source=self.name,
            stage="authority",
            metadata={"turn_terminal": True, "status": "unavailable"},
        )


__all__ = [
    "METHOD_CONFIRMATION_PROMPT",
    "UNAVAILABLE_MESSAGE",
    "MathTurnCapability",
    "build_method_confirmation_payload",
    "selected_option_id",
]
