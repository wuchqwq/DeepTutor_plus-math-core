"""The mathematical ceiling only; no teaching planner, grading or delivery policy."""

from __future__ import annotations

from .authority import MathSemanticGrant
from .support import resolve_math_content_support
from .trajectory_types import TrajectoryProjection
from .workspace import MathWorkspaceSnapshot


def require_math_authority(
    snapshot: MathWorkspaceSnapshot,
    trajectory: TrajectoryProjection | None,
    selected_refs: tuple[str, ...],
    grants: tuple[MathSemanticGrant, ...],
    *,
    submission=None,
    alignment=None,
    episode_id=None,
) -> None:
    if trajectory is None:
        raise ValueError("fresh protected math execution requires trajectory applicability")
    if not set(selected_refs) <= set(trajectory.applicable_artifact_refs):
        raise ValueError("selected math refs exceed the trajectory authority ceiling")
    bindings = {
        binding.relation_key()
        for binding in resolve_math_content_support(
            snapshot,
            selected_refs,
            submission=submission,
            alignment=alignment,
            episode_id=episode_id,
        )
    }
    for grant in grants:
        if grant.target_artifact_ref not in selected_refs or grant.relation_key() not in bindings:
            raise ValueError("math supply requires an exact pinned support binding")
