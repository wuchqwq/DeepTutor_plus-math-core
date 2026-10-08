"""Opaque method choice semantics; a choice never becomes mathematical evidence."""

from __future__ import annotations

from dataclasses import replace

from .trajectory_types import MethodConfirmation


def resolve_confirmation(
    issued: MethodConfirmation,
    current: MethodConfirmation,
    *,
    option_token: str | None = None,
    after_turn: int | None = None,
    invalidate: bool = False,
) -> MethodConfirmation:
    normalized = replace(current, state="pending", chosen_path_ref=None, resolved_after_turn=None)
    if normalized != issued:
        raise ValueError("method confirmation binding changed")
    if invalidate:
        return replace(current, state="invalidated") if current.state == "pending" else current
    selected = dict(current.option_paths).get(option_token) if option_token is not None else None
    if (
        selected is None
        or current.state == "invalidated"
        or after_turn is None
        or after_turn < current.issuing_turn
    ):
        raise ValueError("invalid or stale method confirmation")
    if current.state == "resolved" and current.chosen_path_ref != selected:
        raise ValueError("method confirmation already resolved differently")
    if current.state == "resolved":
        return current
    return replace(
        current, state="resolved", chosen_path_ref=selected, resolved_after_turn=after_turn
    )
