"""Finite math-local support resolver, never a semantic classifier.

These bindings certify exact content identity and the particular relation
recorded by the rational-linear tool. They do not certify arbitrary prose,
premise truth, current applicability, or a complete justification/proof.
"""

from __future__ import annotations

import json

from deeptutor.math_semantic.authority import MathContentSupportBinding, math_content_digest
from deeptutor.math_semantic.contracts import MathArtifact
from deeptutor.math_semantic.refs import SourceRef
from deeptutor.math_semantic.workspace import MathWorkspaceSnapshot


def artifact_content_digest(artifact: MathArtifact) -> str:
    return math_content_digest(artifact)


def resolve_math_content_support(
    snapshot: MathWorkspaceSnapshot, target_refs: tuple[str, ...]
) -> tuple[MathContentSupportBinding, ...]:
    """Resolve only registered built-in mechanisms from a trusted pinned snapshot.

    No caller-supplied role/scope string creates a binding. In particular this
    version has no semantic justification mechanism; operation evidence cannot
    be used to authorize explanatory prose by changing the requested act.
    """
    by_ref = {item.artifact_id: item for item in snapshot.artifacts}
    bindings = []
    for target in target_refs:
        if target not in by_ref:
            raise ValueError("math support target is not in the pinned workspace")
        bindings.append(MathContentSupportBinding.orientation(target))
        artifact = by_ref[target]
        if artifact.verification_status in {"refuted", "unresolved_conflict"}:
            continue
        if artifact.claim_kind == "derived_equation" and artifact.role in {
            "given",
            "intermediate",
            "answer_candidate",
            "final_answer",
            "answer",
        }:
            ref = SourceRef("math_artifact", target)
            bindings.append(
                MathContentSupportBinding(
                    target,
                    "result",
                    ref,
                    artifact_content_digest(artifact),
                    ref,
                    "exact_artifact_content_v1",
                    "literal_result_for_same_target_not_truth_verification",
                )
            )
        for evidence in snapshot.tool_evidence:
            if (
                evidence.tool_name != "rational_linear_transform_v1"
                or evidence.tool_version != "1"
                or evidence.status != "verified"
                or (target not in evidence.artifact_refs)
                or (evidence.evidence_id not in artifact.tool_evidence_refs)
                or (evidence.output_summary != artifact.statement)
            ):
                continue
            try:
                request = json.loads(evidence.input_summary)
            except (TypeError, ValueError):
                continue
            if not isinstance(request, dict):
                continue
            before = request.get("before")
            if (
                request.get("workspace_id") != snapshot.workspace.workspace_id
                or before not in by_ref
                or before not in artifact.dependencies
                or (before not in evidence.input_refs)
                or (
                    evidence.scope
                    != "rational_linear_transform_v1:one_variable_rational_linear_equivalence_relative_to_input:"
                    + before
                )
            ):
                continue
            for operation_ref in evidence.artifact_refs:
                operation = by_ref.get(operation_ref)
                if (
                    operation is None
                    or operation.claim_kind != "operation_description"
                    or operation.role != "transformation"
                    or (operation.dependencies != (before,))
                    or (operation.verification_status != "qualified")
                    or (operation.verification_scope != evidence.scope)
                    or (evidence.evidence_id not in operation.tool_evidence_refs)
                ):
                    continue
                for kind in ("chosen_operation", "operation_options"):
                    bindings.append(
                        MathContentSupportBinding(
                            target,
                            kind,
                            SourceRef("math_artifact", operation_ref),
                            artifact_content_digest(operation),
                            SourceRef("math_tool_evidence", evidence.evidence_id),
                            evidence.tool_name,
                            evidence.scope,
                        )
                    )
    return tuple(bindings)
