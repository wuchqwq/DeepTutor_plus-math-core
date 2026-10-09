"""Finite math-local support resolver, never a semantic classifier.

These bindings certify exact content identity and the particular relation
recorded by the rational-linear tool. They do not certify arbitrary prose,
premise truth, current applicability, or a complete justification/proof.
"""

from __future__ import annotations

import json
import re

from deeptutor.math_semantic.authority import MathContentSupportBinding, math_content_digest
from deeptutor.math_semantic.contracts import MathArtifact
from deeptutor.math_semantic.refs import SourceRef
from deeptutor.math_semantic.tools import MathToolRegistry
from deeptutor.math_semantic.workspace import MathWorkspaceSnapshot

OPERATION_MECHANISM = "typed_expand_substitute_support_v1"
OPERATION_SCOPE = "execution_relative_to_named_premises_not_truth_or_answer"


def _operation_requests(snapshot, target, allowed_refs):
    """Finite syntax-owned operations, with no question-specific identities."""
    by_ref = {a.artifact_id: a for a in snapshot.artifacts}
    artifact = by_ref[target]
    if (
        artifact.role not in {"given", "intermediate", "definition"}
        or artifact.verification_status not in {"qualified", "conditional", "verified"}
        or artifact.statement.count("=") != 1
        or any(c in artifact.statement for c in "<>!")
    ):
        return ()
    left, right = artifact.statement.split("=")
    expression = f"({left})-({right})"
    requests = [("expand", {"expression": expression}, (target,))]
    # Substitute only explicit symbol definitions in the same applicable scope.
    # A definition remains a premise; its use does not verify its truth.
    for definition in snapshot.artifacts:
        if (
            definition.artifact_id not in allowed_refs
            or definition.artifact_id == target
            or definition.role != "definition"
            or definition.statement.count("=") != 1
            or definition.verification_status not in {"qualified", "verified"}
        ):
            continue
        symbol, value = (s.strip() for s in definition.statement.split("="))
        if (
            re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", symbol)
            and re.search(r"\b" + re.escape(symbol) + r"\b", expression)
            and not re.search(r"\b" + re.escape(symbol) + r"\b", value)
        ):
            requests.append(
                (
                    "substitute",
                    {"expression": expression, "substitutions": {symbol: value}},
                    (target, definition.artifact_id),
                )
            )
    return tuple(requests[:3])


def materialize_operation_support(snapshot, target_refs, *, preferred_refs=()):
    """Execute existing tools and bind their unchanged evidence to this revision.

    Only operation descriptions are materialized. No result artifact or truth
    status is produced by this execution-relative support mechanism.
    """
    artifacts, evidence = [], []
    registry = MathToolRegistry(max_calls=4)
    cached = {
        binding.content_ref.identifier
        for binding in _typed_operation_bindings(snapshot, target_refs)
    }
    existing = [json.loads(a.statement) for a in snapshot.artifacts if a.artifact_id in cached]
    by_ref = {a.artifact_id: a for a in snapshot.artifacts}
    # Prefer student-grounded targets, then expressions whose parentheses
    # actually benefit from expansion. This is syntax ordering, not grading.
    remaining = sorted(
        target_refs, key=lambda ref: -len(re.findall(r"\)\s*\^", by_ref[ref].statement))
    )
    ordered = tuple(dict.fromkeys((*preferred_refs, *remaining)))
    allowed = set(target_refs)
    requests = [
        request
        for target in ordered
        if target in allowed
        for request in _operation_requests(snapshot, target, allowed)
    ][:4]
    if all(
        any(
            old["kind"] == kind and old["kwargs"] == kwargs and tuple(old["premises"]) == premises
            for old in existing
        )
        for kind, kwargs, premises in requests
    ):
        return (), ()
    # Rebind the entire bounded batch when any requested relation changes;
    # mixing old-head and new-head operation artifacts would lose support.
    for kind, kwargs, premises in requests:
        revision_ref = SourceRef(
            "workspace_revision",
            f"{snapshot.workspace.workspace_id}@{snapshot.workspace.revision}",
        )
        result = registry.call(kind, input_refs=(*premises, revision_ref.identifier), **kwargs)
        evidence.append(result.evidence)
        if result.status != "succeeded":
            continue
        request = {
            "mechanism": OPERATION_MECHANISM,
            "kind": kind,
            "kwargs": kwargs,
            "premises": list(premises),
            "workspace_id": snapshot.workspace.workspace_id,
            "input_revision": snapshot.workspace.revision,
        }
        canonical = json.dumps(request, ensure_ascii=False, sort_keys=True)
        artifacts.append(
            MathArtifact(
                canonical,
                "transformation",
                claim_kind="operation_description",
                normalized_form=canonical,
                provenance=(snapshot.workspace_ref, revision_ref),
                dependencies=premises,
                verification_status="qualified",
                verification_scope=OPERATION_SCOPE,
                tool_evidence_refs=(result.evidence.evidence_id,),
                workspace_revision=snapshot.workspace.revision + 1,
            )
        )
    return tuple(artifacts), tuple(evidence)


def _typed_operation_bindings(snapshot, target_refs):
    by_ref = {a.artifact_id: a for a in snapshot.artifacts}
    proofs = {e.evidence_id: e for e in snapshot.tool_evidence}
    for operation in snapshot.artifacts:
        if (
            operation.claim_kind != "operation_description"
            or operation.role != "transformation"
            or operation.verification_status != "qualified"
            or operation.verification_scope != OPERATION_SCOPE
            or operation.workspace_revision != snapshot.workspace.revision
            or len(operation.tool_evidence_refs) != 1
        ):
            continue
        try:
            request = json.loads(operation.statement)
            if set(request) != {
                "mechanism",
                "kind",
                "kwargs",
                "premises",
                "workspace_id",
                "input_revision",
            }:
                continue
            premises = tuple(request["premises"])
            target = premises[0]
            if (
                request["mechanism"] != OPERATION_MECHANISM
                or request["workspace_id"] != snapshot.workspace.workspace_id
                or type(request["input_revision"]) is not int
                or request["input_revision"] + 1 != operation.workspace_revision
                or target not in target_refs
                or not set(premises) <= set(target_refs)
                or not set(premises) <= set(by_ref)
                or operation.dependencies != premises
                or operation.normalized_form != operation.statement
            ):
                continue
            revision_ref = SourceRef(
                "workspace_revision",
                f"{snapshot.workspace.workspace_id}@{request['input_revision']}",
            )
            if operation.provenance != (snapshot.workspace_ref, revision_ref):
                continue
            permitted = _operation_requests(snapshot, target, set(target_refs))
            if (request["kind"], request["kwargs"], premises) not in permitted:
                continue
            proof = proofs.get(operation.tool_evidence_refs[0])
            if (
                proof is None
                or proof.tool_name != request["kind"]
                or proof.tool_version != MathToolRegistry.VERSION
                or proof.status != "succeeded"
                or proof.failure_type is not None
                or proof.scope != MathToolRegistry._scope_for(request["kind"])
                or proof.input_refs != (*premises, revision_ref.identifier)
                or proof.input_summary != MathToolRegistry._input_summary(request["kwargs"])
            ):
                continue
        except (TypeError, ValueError, KeyError, IndexError):
            continue
        for kind in ("chosen_operation", "operation_options"):
            yield MathContentSupportBinding(
                target,
                kind,
                SourceRef("math_artifact", operation.artifact_id),
                artifact_content_digest(operation),
                SourceRef("math_tool_evidence", proof.evidence_id),
                OPERATION_MECHANISM,
                OPERATION_SCOPE,
            )


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
    bindings.extend(_typed_operation_bindings(snapshot, target_refs))
    return tuple(bindings)
