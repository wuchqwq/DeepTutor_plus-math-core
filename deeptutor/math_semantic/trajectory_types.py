from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Literal

from .refs import LearnerRef, QuestionRef, SourceRef


@dataclass(frozen=True, slots=True)
class ArtifactProjection:
    artifact_ref: str
    workspace_id: str
    workspace_revision: int
    role: str
    statement: str
    verification_status: str
    verification_scope: str
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.artifact_ref or not self.workspace_id or self.workspace_revision < 1:
            raise ValueError("artifact projection identity is required")
        if not self.role or not self.statement or len(self.statement) > 1000:
            raise ValueError("artifact projection content is bounded and required")
        if not self.verification_status:
            raise ValueError("artifact verification status is required")
        if len(self.dependencies) > 16:
            raise ValueError("artifact dependencies exceed bound")

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_ref": self.artifact_ref,
            "workspace_id": self.workspace_id,
            "workspace_revision": self.workspace_revision,
            "role": self.role,
            "statement": self.statement,
            "verification_status": self.verification_status,
            "verification_scope": self.verification_scope,
            "dependencies": list(self.dependencies),
        }


@dataclass(frozen=True, slots=True)
class AlignmentProjection:
    alignment_ref: SourceRef
    workspace_ref: SourceRef
    source_workspace_revision: int
    output_workspace_revision: int
    matched_artifact_refs: tuple[str, ...]
    contradicted_artifact_refs: tuple[str, ...]
    active_path_refs: tuple[str, ...]
    divergence_artifact_refs: tuple[str, ...]
    unshown_artifact_refs: tuple[str, ...]
    learner_evidence_refs: tuple[SourceRef, ...]
    status: str
    uncertainty: float | None

    def __post_init__(self) -> None:
        if (
            self.alignment_ref.kind != "response_alignment"
            or self.workspace_ref.kind != "math_workspace"
        ):
            raise ValueError("alignment projection refs are invalid")
        if (
            self.source_workspace_revision < 1
            or self.output_workspace_revision < self.source_workspace_revision
        ):
            raise ValueError("alignment revisions are invalid")
        if any((ref.kind != "student_math_claim" for ref in self.learner_evidence_refs)):
            raise ValueError("planner learner evidence must be student math claim refs")
        if self.uncertainty is not None and (not 0 <= self.uncertainty <= 1):
            raise ValueError("alignment uncertainty is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "alignment_ref": {
                "kind": self.alignment_ref.kind,
                "identifier": self.alignment_ref.identifier,
            },
            "workspace_ref": {
                "kind": self.workspace_ref.kind,
                "identifier": self.workspace_ref.identifier,
            },
            "source_workspace_revision": self.source_workspace_revision,
            "output_workspace_revision": self.output_workspace_revision,
            "matched_artifact_refs": list(self.matched_artifact_refs),
            "contradicted_artifact_refs": list(self.contradicted_artifact_refs),
            "active_path_refs": list(self.active_path_refs),
            "divergence_artifact_refs": list(self.divergence_artifact_refs),
            "unshown_artifact_refs": list(self.unshown_artifact_refs),
            "learner_evidence_refs": [
                {"kind": ref.kind, "identifier": ref.identifier}
                for ref in self.learner_evidence_refs
            ],
            "status": self.status,
            "uncertainty": self.uncertainty,
        }


@dataclass(frozen=True, slots=True)
class MethodConfirmation:
    """Episode-local direction, never a mathematical claim or learner belief."""

    confirmation_id: str
    episode_ref: SourceRef
    learner: LearnerRef
    question_ref: QuestionRef
    issuing_turn: int
    issuing_basis_refs: tuple[SourceRef, ...]
    option_paths: tuple[tuple[str, str], ...]
    state: Literal["pending", "resolved", "invalidated"] = "pending"
    chosen_path_ref: str | None = None
    resolved_after_turn: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> MethodConfirmation:
        return cls(
            **{
                **data,
                "episode_ref": SourceRef(**data["episode_ref"]),
                "learner": LearnerRef(**data["learner"]),
                "question_ref": QuestionRef(**data["question_ref"]),
                "issuing_basis_refs": tuple(
                    (SourceRef(**ref) for ref in data["issuing_basis_refs"])
                ),
                "option_paths": tuple((tuple(pair) for pair in data["option_paths"])),
            }
        )


@dataclass(frozen=True, slots=True)
class TrajectoryProjection:
    """Derived interpretation; membership never asserts learner completion."""

    cutoff_response_ref: SourceRef
    cutoff_turn: int
    basis_refs: tuple[SourceRef, ...]
    authored_source_ref: SourceRef
    authored_path_refs: tuple[str, ...]
    compatible_path_refs: tuple[str, ...]
    applicable_artifact_refs: tuple[str, ...]
    status: str
    version: str = "ca02_trajectory_v1"
    method_confirmation: MethodConfirmation | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        if self.method_confirmation is None:
            data.pop("method_confirmation")
        return data

    @property
    def projection_ref(self) -> SourceRef:
        digest = hashlib.sha256(
            json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return SourceRef("trajectory_projection", digest)
