"""Immutable current-turn evidence, never assessment or learner belief."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from deeptutor.math_semantic.contracts import ToolEvidence
from deeptutor.math_semantic.refs import SourceRef

ClaimType = Literal["equation", "expression", "answer", "identity"]
RelationType = Literal["matches", "equivalent_to", "partial_match", "contradicts", "unresolved"]


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    start: int
    end: int
    quote: str

    def __post_init__(self) -> None:
        if (
            type(self.start) is not int
            or type(self.end) is not int
            or (not 0 <= self.start < self.end)
        ):
            raise ValueError("invalid evidence span")
        if not isinstance(self.quote, str) or not self.quote or len(self.quote) > 512:
            raise ValueError("evidence quote must be bounded")


@dataclass(frozen=True, slots=True)
class StudentMathClaim:
    claim_id: str
    student_response_ref: SourceRef
    evidence: EvidenceSpan
    normalized_form: str
    claim_type: ClaimType
    parse_status: str = "parsed"
    uncertainty: float | None = None

    def __post_init__(self) -> None:
        if self.student_response_ref.kind != "student_response" or not self.claim_id:
            raise ValueError("student claim needs response identity")
        if self.claim_type not in {"equation", "expression", "answer", "identity"}:
            raise ValueError("unsupported student claim type")
        if self.parse_status not in {"parsed", "ambiguous", "unparsed"}:
            raise ValueError("unsupported claim parse status")
        if self.uncertainty is not None and (not 0 <= self.uncertainty <= 1):
            raise ValueError("uncertainty must be calibrated or absent")


@dataclass(frozen=True, slots=True)
class ClaimRelation:
    student_claim_ref: str
    artifact_ref: str | None
    relation_type: RelationType
    mechanism: str
    scope: str
    tool_evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PathDivergence:
    path_ref: str
    last_matched_artifact_ref: str | None
    student_next_claim_ref: str
    relevant_artifact_refs: tuple[str, ...]
    status: str = "unresolved"


@dataclass(frozen=True, slots=True)
class UnshownStep:
    path_ref: str
    artifact_ref: str
    status: str = "not_explicitly_shown"


@dataclass(frozen=True, slots=True)
class NovelMathCandidate:
    student_claim_refs: tuple[str, ...]
    method: str
    dependency_artifact_refs: tuple[str, ...] = ()
    candidate_id: str | None = None
    validated_artifact_refs: tuple[str, ...] = ()
    validation_evidence_refs: tuple[str, ...] = ()
    candidate_path_ref: str | None = None
    status: str = "unvalidated"


@dataclass(frozen=True, slots=True)
class ResponseAlignment:
    alignment_id: str
    student_response_ref: SourceRef
    math_workspace_ref: SourceRef
    workspace_revision: int
    output_workspace_revision: int
    claims: tuple[StudentMathClaim, ...]
    relations: tuple[ClaimRelation, ...]
    matched_artifact_refs: tuple[str, ...]
    contradicted_artifact_refs: tuple[str, ...]
    active_path_refs: tuple[str, ...]
    divergence: tuple[PathDivergence, ...]
    unshown_steps: tuple[UnshownStep, ...]
    novel_candidates: tuple[NovelMathCandidate, ...]
    novel_claim_refs: tuple[str, ...]
    novel_path_refs: tuple[str, ...]
    validated_artifact_refs: tuple[str, ...]
    validation_evidence_refs: tuple[str, ...]
    math_evidence: tuple[ToolEvidence, ...]
    projected_refs: tuple[str, ...]
    interaction_type: str
    status: str
    provenance: tuple[SourceRef, ...]
    uncertainty: float | None = None
    version: str = "response_alignment_v1"

    @property
    def student_claim_refs(self) -> tuple[str, ...]:
        return tuple((item.claim_id for item in self.claims))

    def __post_init__(self) -> None:
        if self.workspace_revision < 1 or self.output_workspace_revision < self.workspace_revision:
            raise ValueError("alignment must bind exact workspace revisions")
        if (
            self.student_response_ref.kind != "student_response"
            or self.math_workspace_ref.kind != "math_workspace"
        ):
            raise ValueError("alignment requires typed response/workspace refs")
        if self.interaction_type not in {"answer", "question", "clarification", "unclear"}:
            raise ValueError("unsupported interaction type")
        if self.status not in {"aligned", "partial", "unresolved", "no_math_claim"}:
            raise ValueError("unsupported alignment status")
        if any((item.student_response_ref != self.student_response_ref for item in self.claims)):
            raise ValueError("claim response binding mismatch")
        if (
            self.student_response_ref not in self.provenance
            or self.math_workspace_ref not in self.provenance
        ):
            raise ValueError("alignment provenance is required")
