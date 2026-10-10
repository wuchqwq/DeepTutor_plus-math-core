"""Finite math-local support resolver, never a semantic classifier.

These bindings certify exact content identity and the particular relation
recorded by the rational-linear tool. They do not certify arbitrary prose,
premise truth, current applicability, or a complete justification/proof.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from fractions import Fraction
import json
import re

from deeptutor.math_semantic.authority import MathContentSupportBinding, math_content_digest
from deeptutor.math_semantic.contracts import MathArtifact
from deeptutor.math_semantic.refs import SourceRef
from deeptutor.math_semantic.tools import MathToolRegistry
from deeptutor.math_semantic.validation import STEP_VERSION, _polynomial, _step_scope, step_basis
from deeptutor.math_semantic.verification import normalize_display
from deeptutor.math_semantic.workspace import MathWorkspaceSnapshot

OPERATION_MECHANISM = "typed_expand_substitute_support_v1"
OPERATION_SCOPE = "execution_relative_to_named_premises_not_truth_or_answer"
CONNECTION_MECHANISM = "reviewed_intermediate_certificate_v1"
CONNECTION_SCOPE = "reviewed_connection_only_no_range_completion_or_mastery"


def _connection_residual(text, names):
    parts = normalize_display(text).split("=")
    if len(parts) != 2:
        raise ValueError("connection requires a finite equality")
    left, ln, _ = _polynomial(parts[0])
    right, rn, _ = _polynomial(parts[1])
    if (ln | rn) - names:
        raise ValueError("undefined connection symbol")
    return f"({left})-({right})"


def _connection_coefficient(value):
    coefficient = Fraction(value)
    if not coefficient or max(abs(coefficient.numerator), coefficient.denominator) > 1000:
        raise ValueError("connection coefficient budget")
    return f"({coefficient.numerator}/{coefficient.denominator})"


def _connection_zero(proof, kwargs, refs):
    return (
        proof.tool_name == "expand"
        and proof.tool_version == MathToolRegistry.VERSION
        and proof.status == "succeeded"
        and proof.failure_type is None
        and proof.scope == MathToolRegistry._scope_for("expand")
        and proof.input_summary == MathToolRegistry._input_summary(kwargs)
        and proof.input_refs == refs
        and proof.output_summary == "0"
        and replace(proof, evidence_id=None).evidence_id == proof.evidence_id
    )


def _connection_origin(state, revision):
    """Read the existing pending step from canonical accepted records only."""
    from deeptutor.math_semantic.codec import _decode

    records = json.loads(state.serialize())
    alignments = [_decode(v) for v in records["alignments"].values()]

    def latest(submitted):
        return max(
            (
                a
                for a in alignments
                if a.student_response_ref.identifier == submitted.response_id
                and a.output_workspace_revision <= revision
            ),
            key=lambda a: a.workspace_revision,
            default=None,
        )

    current = latest(state.submission)
    if current is None or current.uncertainty not in {None, 0}:
        return None
    if current.interaction_type == "answer":
        return state.submission, current, None
    if current.claims or current.interaction_type not in {"clarification", "question"}:
        return None
    snapshot = state.snapshot()
    if current.math_workspace_ref != snapshot.workspace_ref or step_basis(
        state.snapshot(current.workspace_revision)
    ) != step_basis(snapshot):
        return None
    state._check_step_evidence(current)
    # This is the same bounded pending-step look-back as teaching context, but
    # a missing/unclear/latest substantive alignment stops, never falls back.
    prefix = state.prefix
    if not prefix or prefix[-1] != state.submission or len(prefix) > 32:
        return None
    if len({s.response_id for s in prefix}) != len(prefix) or any(
        s.session_id != state.submission.session_id for s in prefix
    ):
        return None
    for ordinal in range(len(prefix) - 2, -1, -1):
        submitted = prefix[ordinal]
        pending = latest(submitted)
        if pending is None or pending.uncertainty not in {None, 0}:
            return None
        if not pending.claims:
            if pending.interaction_type in {"clarification", "question"}:
                continue
            return None
        if pending.interaction_type != "answer" or len(pending.claims) != 1:
            return None
        state._check_step_evidence(pending)
        pinned = state.snapshot(pending.output_workspace_revision)
        from deeptutor.math_semantic.state import MathMutation

        prior = MathMutation(
            state.source,
            submitted,
            prefix[: ordinal + 1],
            json.dumps(dict(records, head=pending.output_workspace_revision)),
        )
        proofs = {e.evidence_id: e for e in snapshot.tool_evidence}
        if (
            pending.math_workspace_ref != snapshot.workspace_ref
            or step_basis(pinned) != step_basis(snapshot)
            or pinned.paths != snapshot.paths
            or prior.trajectory().compatible_path_refs != state.trajectory().compatible_path_refs
            or any(proofs.get(e.evidence_id) != e for e in pending.math_evidence)
        ):
            return None
        return (
            submitted,
            pending,
            {
                "session_id": submitted.session_id,
                "turn_id": submitted.turn_id,
                "accepted_user_message_id": submitted.message_id,
                "student_response_ref": asdict(pending.student_response_ref),
                "alignment_ref": pending.alignment_id,
                "workspace_revision": pending.workspace_revision,
                "output_workspace_revision": pending.output_workspace_revision,
                "submission_digest": math_content_digest(submitted),
                "alignment_digest": math_content_digest(pending),
                "inquiry_digest": math_content_digest(state.submission),
                "inquiry_alignment_digest": math_content_digest(current),
            },
        )
    return None


def connection_request(state, target_refs, *, input_revision=None):
    """Use a current claim or the explicitly permitted unique pending claim.

    Pure inquiries reference the latest valid accepted claim without becoming
    assertions. Historical row/claim/step/tool revisions remain their originals;
    the new certificate and publication are bound to this inquiry separately.
    """
    declaration = state.source.reviewed_connection
    if declaration is None:
        return None
    snapshot = state.snapshot()
    revision = snapshot.workspace.revision if input_revision is None else input_revision
    origin = _connection_origin(state, revision)
    if origin is None:
        return None
    submitted, current, historical = origin
    if (
        current is None
        or current.interaction_type != "answer"
        or current.uncertainty not in {None, 0}
    ):
        return None
    state._check_step_evidence(current)
    try:
        model = snapshot.problem_model
        symbols, definitions, _, facts = _step_scope(snapshot)
        if (
            model.has_unknowns
            or model.has_conflicts
            or declaration.model_digest != math_content_digest(model)
            or model != state.source.authored.problem_model
            or current.math_workspace_ref != snapshot.workspace_ref
            or step_basis(state.snapshot(current.workspace_revision)) != step_basis(snapshot)
            or any(
                not f.provenance or f.status != "explicit" or f.uncertainty != 0
                for f in model.domain
            )
        ):
            return None
        target = next(
            a for a in state.source.authored.artifacts if a.artifact_id == declaration.relation_ref
        )
        if (
            target.artifact_id not in target_refs
            or target.role != "intermediate"
            or math_content_digest(target) != declaration.relation_digest
            or target not in snapshot.artifacts
            or target.uncertainty != 0
            or target.assumptions
            or target.verification_status in {"refuted", "unresolved_conflict"}
        ):
            return None
        names = symbols | definitions.keys()
        terms = []
        for category, index, digest, coefficient in declaration.premise_terms:
            if (
                category not in {"givens", "constraints", "assumptions", "target"}
                or type(index) is not int
                or index < 0
            ):
                return None
            values = (model.target,) if category == "target" else getattr(model, category)
            fact = values[index]
            if (
                fact is None
                or math_content_digest(fact) != digest
                or fact.status != "explicit"
                or fact.uncertainty != 0
                or not fact.provenance
                or not set(fact.provenance) <= set(model.provenance)
            ):
                return None
            equality = fact.value.removeprefix("range of ") if category == "target" else fact.value
            terms.append(
                f"{_connection_coefficient(coefficient)}*({_connection_residual(equality, names)})"
            )
        proofs = {e.evidence_id: e for e in snapshot.tool_evidence}
        for claim in current.claims[:4]:
            if (
                claim.claim_type not in {"identity", "equation"}
                or claim.parse_status != "parsed"
                or claim.uncertainty not in {None, 0}
                or claim.student_response_ref != current.student_response_ref
                or normalize_display(claim.normalized_form)
                != normalize_display(declaration.student_equality)
                or normalize_display(claim.evidence.quote) != claim.normalized_form
                or submitted.raw_content[claim.evidence.start : claim.evidence.end]
                != claim.evidence.quote
            ):
                continue
            residual = _connection_residual(claim.normalized_form, symbols)
            for envelope in current.math_evidence:
                if envelope.tool_version != STEP_VERSION:
                    continue
                binding, checked = (
                    json.loads(envelope.input_summary),
                    json.loads(envelope.output_summary),
                )
                refs = (
                    submitted.response_id,
                    claim.claim_id,
                    f"{snapshot.workspace.workspace_id}@{current.workspace_revision}",
                    model.model_ref.identifier,
                    *tuple(dict.fromkeys(ref for _, ref in facts)),
                )
                if (
                    binding["claim"] != asdict(claim)
                    or binding["model"] != json.loads(json.dumps(asdict(model)))
                    or binding["premises"] != [list(f) for f in facts]
                    or envelope.input_refs != refs
                    or checked["local_relation"] != "IDENTITY"
                    or checked["reason"] != "zero_polynomial_over_explicit_reals"
                    or envelope.status != "succeeded"
                    or envelope.failure_type is not None
                    or len(checked["tool_evidence_refs"]) != 1
                ):
                    continue
                proof = proofs.get(checked["tool_evidence_refs"][0])
                if proof is None or not _connection_zero(proof, {"expression": residual}, refs):
                    continue
                expression = _connection_residual(target.statement, names)
                expression += (
                    "-("
                    + "+".join(
                        (
                            *terms,
                            f"{_connection_coefficient(declaration.student_coefficient)}*({residual})",
                        )
                    )
                    + ")"
                )
                # Every component used the existing polynomial grammar; only a
                # fixed rational sum is assembled. No search or solver is used.
                from deeptutor.math_semantic.tools import _safe_expression

                _safe_expression(expression)
                return {
                    "mechanism": CONNECTION_MECHANISM,
                    "target": target.artifact_id,
                    "source_digest": math_content_digest(state.source),
                    "declaration_digest": math_content_digest(declaration),
                    "input_revision": revision,
                    "workspace_id": snapshot.workspace.workspace_id,
                    "submission_digest": math_content_digest(submitted),
                    "alignment_digest": math_content_digest(current),
                    "claim_ref": claim.claim_id,
                    "claim_digest": math_content_digest(claim),
                    "step_ref": envelope.evidence_id,
                    "step_digest": math_content_digest(envelope),
                    "kwargs": {"expression": expression},
                    "text": declaration.canonical_explanation,
                    **({"historical_claim_origin": historical} if historical is not None else {}),
                }
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        StopIteration,
        AttributeError,
        SyntaxError,
    ):
        return None
    return None


def _connection_refs(request):
    refs = (
        f"{request['workspace_id']}@{request['input_revision']}",
        request["source_digest"],
        request["submission_digest"],
        request["claim_ref"],
        request["step_ref"],
    )
    if "historical_claim_origin" in request:
        origin = request["historical_claim_origin"]
        refs += (origin["inquiry_digest"], origin["inquiry_alignment_digest"])
    return refs


def materialize_connection_support(request):
    """One explicit certificate tool call outside the transaction; no permission."""
    if request is None:
        return (), ()
    result = MathToolRegistry(max_calls=1).call(
        "expand", input_refs=_connection_refs(request), **request["kwargs"]
    )
    if not _connection_zero(result.evidence, request["kwargs"], _connection_refs(request)):
        return (), (result.evidence,)
    revision = SourceRef(
        "workspace_revision", f"{request['workspace_id']}@{request['input_revision']}"
    )
    canonical = json.dumps(request, ensure_ascii=False, sort_keys=True)
    artifact = MathArtifact(
        canonical,
        "transformation",
        claim_kind="operation_description",
        normalized_form=canonical,
        provenance=(SourceRef("math_workspace", request["workspace_id"]), revision),
        dependencies=(request["target"],),
        verification_status="qualified",
        verification_scope=CONNECTION_SCOPE,
        tool_evidence_refs=(result.evidence.evidence_id,),
        workspace_revision=request["input_revision"] + 1,
    )
    return (artifact,), (result.evidence,)


def _connection_bindings(snapshot, target_refs, state):
    if state is None or state.snapshot() != snapshot:
        return
    request = connection_request(state, target_refs, input_revision=snapshot.workspace.revision - 1)
    if request is None:
        return
    canonical = json.dumps(request, ensure_ascii=False, sort_keys=True)
    proofs = {e.evidence_id: e for e in snapshot.tool_evidence}
    for artifact in snapshot.artifacts:
        if (
            artifact.claim_kind != "operation_description"
            or artifact.role != "transformation"
            or artifact.verification_scope != CONNECTION_SCOPE
            or artifact.verification_status != "qualified"
            or artifact.workspace_revision != snapshot.workspace.revision
            or artifact.statement != canonical
            or artifact.normalized_form != canonical
            or artifact.dependencies != (request["target"],)
            or artifact.provenance
            != (
                snapshot.workspace_ref,
                SourceRef("workspace_revision", _connection_refs(request)[0]),
            )
            or len(artifact.tool_evidence_refs) != 1
        ):
            continue
        proof = proofs.get(artifact.tool_evidence_refs[0])
        if proof is not None and _connection_zero(
            proof, request["kwargs"], _connection_refs(request)
        ):
            yield MathContentSupportBinding(
                request["target"],
                "justification",
                SourceRef("math_artifact", artifact.artifact_id),
                artifact_content_digest(artifact),
                SourceRef("math_tool_evidence", proof.evidence_id),
                CONNECTION_MECHANISM,
                CONNECTION_SCOPE,
            )


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
    snapshot: MathWorkspaceSnapshot, target_refs: tuple[str, ...], *, state=None
) -> tuple[MathContentSupportBinding, ...]:
    """Resolve only registered built-in mechanisms from a trusted pinned snapshot.

    No caller-supplied role/scope string creates a binding. In particular this
    version supplies only the explicitly reviewed current-claim connection
    below; ordinary operation evidence cannot authorize explanatory prose.
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
    bindings.extend(_connection_bindings(snapshot, target_refs, state))
    return tuple(bindings)
