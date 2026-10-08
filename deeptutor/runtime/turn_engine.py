"""Shared lower-level execution engine used by every application adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict
import json

from deeptutor.core.context import (
    CapabilityBinding,
    TurnMutationSQL,
    TurnRoutingReference,
    UnifiedContext,
)
from deeptutor.core.stream import StreamEvent


class TurnEngine:
    """Execute an assembled context through the canonical orchestrator."""

    def __init__(
        self,
        capability_registry=None,  # noqa: ANN001
        *,
        resolve_accepted_capability: Callable[
            [TurnRoutingReference], Awaitable[CapabilityBinding | None]
        ]
        | None = None,
    ) -> None:
        self.capability_registry = capability_registry
        self._resolve_accepted_capability = resolve_accepted_capability

    async def select_capability(self, context: UnifiedContext) -> None:
        """Optional host DI after acceptance, before the existing dispatcher.

        None retains the ordinary route. The decision is not an LLM proposal,
        request option, session-wide text rule or mathematical verification.
        """
        if self._resolve_accepted_capability is None:
            return
        runtime = context.runtime
        binding = await self._resolve_accepted_capability(
            TurnRoutingReference(
                context.session_id, runtime.turn_id, runtime.accepted_user_message_id
            )
        )
        if binding is not None and not isinstance(binding, CapabilityBinding):
            raise ValueError("ambiguous or invalid host capability binding")
        requested = context.active_capability or "chat"
        selected = binding.capability if binding is not None else requested
        decision = {"turn_id": runtime.turn_id, "binding": asdict(binding) if binding else None}

        def attribute(sql: TurnMutationSQL) -> None:
            rows = sql(
                "SELECT session_id, role, content, metadata_json FROM messages WHERE id=?",
                (runtime.accepted_user_message_id,),
            )
            if len(rows) != 1 or rows[0][:3] != (
                context.session_id,
                "user",
                runtime.accepted_user_content,
            ):
                raise ValueError("host capability binding differs from accepted row")
            metadata = json.loads(rows[0][3])
            if metadata.get("turn_id") != runtime.turn_id:
                raise ValueError("host capability binding differs from accepted turn")
            if (
                "host_capability_binding" in metadata
                and metadata["host_capability_binding"] != decision
            ):
                raise ValueError("immutable host capability binding changed")
            metadata["host_capability_binding"] = decision
            sql(
                "UPDATE messages SET capability=?, metadata_json=? WHERE id=?",
                (
                    selected,
                    json.dumps(metadata, ensure_ascii=False),
                    runtime.accepted_user_message_id,
                ),
            )

        # Missing accepted input/unsupported commit ports can never mint a
        # durable assignment. Protected capabilities independently fail closed
        # before proposal/Core work; ordinary backends retain their route.
        if (
            runtime.accepted_user_message_id is not None
            and runtime.run_durable_turn_mutation is not None
        ):
            await runtime.run_durable_turn_mutation(attribute)
        runtime.capability_binding = binding
        context.active_capability = selected
        if binding is not None:
            from deeptutor.runtime.capability_routing import CapabilityRoute

            context.metadata["capability_route"] = CapabilityRoute(
                requested_capability=requested,
                capability=selected,
                confidence=1.0,
                strategy="trusted_scope",
                reason="The host selected a reviewed capability scope.",
            ).as_metadata()

    async def execute(self, context: UnifiedContext) -> AsyncIterator[StreamEvent]:
        # Lazy loading avoids provider/plugin import side effects at process
        # boot and leaves one stable patch point for tests and embedders.
        from deeptutor.runtime.orchestrator import ChatOrchestrator

        orchestrator = (
            ChatOrchestrator()
            if self.capability_registry is None
            else ChatOrchestrator(capability_registry=self.capability_registry)
        )
        async for event in orchestrator.handle(context):
            yield event


_default_engine: TurnEngine | None = None


def get_turn_engine() -> TurnEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = TurnEngine()
    return _default_engine


__all__ = ["TurnEngine", "get_turn_engine"]
