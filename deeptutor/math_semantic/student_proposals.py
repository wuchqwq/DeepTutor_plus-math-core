"""Scoped student-origin proposals; only Math Core validates task additions."""

from dataclasses import dataclass
from typing import cast

from deeptutor.math_semantic.contracts import MathArtifact, SolutionPath, ToolEvidence
from deeptutor.math_semantic.refs import SourceRef
from deeptutor.math_semantic.tools import validate_artifact
from deeptutor.math_semantic.workspace import MathWorkspaceSnapshot


@dataclass(frozen=True, slots=True)
class StudentMathProposal:
    statement: str
    student_claim_ref: SourceRef
    student_response_ref: SourceRef
    alignment_ref: SourceRef
    claim_kind: str = "derived_equation"
    observed_dependency_refs: tuple[str, ...] = ()
    candidate_ref: SourceRef | None = None


@dataclass(frozen=True, slots=True)
class StudentProposalValidation:
    checked_artifacts: tuple[MathArtifact, ...]
    evidence: tuple[ToolEvidence, ...]
    accepted_artifacts: tuple[MathArtifact, ...]
    candidate_paths: tuple[SolutionPath, ...]


def validate_student_proposals(
    snapshot: MathWorkspaceSnapshot,
    proposals: tuple[StudentMathProposal, ...],
    *,
    source_text: str,
    method: str | None = None,
    timeout_deadline: float | None = None,
) -> StudentProposalValidation:
    """Return scoped validated additions, never infer conditional entailment.

    Independently verified identities may form a *candidate*, incomplete path.
    Assignments and conditional equations need a future entailment mechanism
    before admission.  All rejected claims remain student evidence upstream.
    """
    if len(proposals) > 8:
        raise ValueError("student math proposal budget exceeded")
    checked, evidence = ([], [])
    for proposal in proposals:
        if (
            proposal.student_response_ref.kind != "student_response"
            or proposal.alignment_ref.kind != "response_alignment"
        ):
            raise ValueError("student-origin provenance is required")
        if proposal.student_claim_ref.kind != "student_math_claim":
            raise ValueError("student claim provenance is required")
        if not set(proposal.observed_dependency_refs) <= set(snapshot.workspace.artifact_refs):
            raise ValueError("student proposal references unknown dependency")
        artifact = MathArtifact(
            proposal.statement,
            "intermediate",
            claim_kind=proposal.claim_kind,
            dependencies=proposal.observed_dependency_refs,
            provenance=(
                snapshot.problem_model.model_ref,
                proposal.student_response_ref,
                proposal.alignment_ref,
                proposal.student_claim_ref,
                *((proposal.candidate_ref,) if proposal.candidate_ref else ()),
            ),
            workspace_revision=snapshot.workspace.revision + 1,
        )
        validated, proof = validate_artifact(
            artifact, support_text=source_text, turn_deadline_monotonic=timeout_deadline
        )
        checked.append(validated)
        evidence.append(proof)
    accepted = tuple((item for item in checked if item.verification_status == "verified"))
    paths: tuple[SolutionPath, ...] = ()
    if method and proposals and (len(accepted) == len(proposals)):
        paths = (
            SolutionPath(
                method,
                tuple((cast(str, item.artifact_id) for item in accepted)),
                status="candidate",
                completeness="partial",
                provenance=tuple(
                    dict.fromkeys((ref for item in accepted for ref in item.provenance))
                ),
                workspace_revision=snapshot.workspace.revision + 1,
            ),
        )
    return StudentProposalValidation(tuple(checked), tuple(evidence), accepted, paths)
