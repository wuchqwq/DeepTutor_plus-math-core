"""One bounded conditional algebra relation, relative to explicit premises.

This is mathematical support for the existing host's justification act. It
does not assess the learner, prove premise truth, or solve a range problem.
"""

from dataclasses import asdict
import hashlib
import json
import re

from .authority import MathContentSupportBinding, math_content_digest
from .contracts import MathArtifact
from .refs import SourceRef
from .tools import MathToolRegistry

CORRECTION_MECHANISM = "bounded_premise_residual_v1"
CORRECTION_SCOPE = "conditional_algebra_relative_to_explicit_premises_not_truth_or_answer"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _equation(text):
    if not isinstance(text, str) or text.count("=") != 1 or any(c in text for c in "<>!"):
        return None
    left, right = (s.strip() for s in text.split("="))
    return (left, right) if left and right else None


def _polynomial_syntax(text):
    """Small polynomial display only; tool workers own all symbolic parsing."""
    return (
        len(text) <= 128
        and re.fullmatch(r"[A-Za-z0-9_+*()^\-\s]+", text) is not None
        and not re.search(r"[A-Za-z0-9_]\s*\(", text)
        and all(int(power) <= 8 for power in re.findall(r"(?:\^|\*\*)\s*(\d+)", text))
        and not re.search(r"(?:\^|\*\*)\s*[^\d\s]", text)
    )


def _definition(snapshot, symbol, revision):
    # Only the exact explicit target grammar supplies E. No extraction from
    # private solution prose or derived answers.
    target = snapshot.problem_model.target
    if target is None or target.status != "explicit" or target.uncertainty != 0:
        return None
    value = target.value
    if value.startswith("range of "):
        value = value[len("range of ") :]
    pair = _equation(value)
    if (
        pair is None
        or pair[0] != symbol
        or not _polynomial_syntax(pair[1])
        or re.search(r"\b" + re.escape(symbol) + r"\b", pair[1])
    ):
        return None
    statement = f"{symbol}={pair[1]}"
    return MathArtifact(
        statement,
        "definition",
        claim_kind="definition",
        provenance=(snapshot.problem_model.model_ref, *target.provenance),
        verification_status="qualified",
        verification_scope="explicit_problem_target_definition",
        workspace_revision=revision,
    )


def _basis(snapshot, targets, submission, alignment, episode_id):
    if submission is None or alignment is None or not episode_id:
        return None
    if (
        alignment.student_response_ref != SourceRef("student_response", submission.response_id)
        or alignment.math_workspace_ref != snapshot.workspace_ref
        or alignment.output_workspace_revision > snapshot.workspace.revision
        or alignment.uncertainty not in (None, 0)
    ):
        return None
    candidates = []
    for claim in alignment.claims[:8]:
        span = claim.evidence
        pair = _equation(claim.normalized_form)
        if (
            claim.parse_status != "parsed"
            or claim.uncertainty not in (None, 0)
            or submission.raw_content[span.start : span.end] != span.quote
            or pair is None
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", pair[0])
        ):
            continue
        symbol, student_rhs = pair
        if not _polynomial_syntax(student_rhs):
            continue
        definition = _definition(snapshot, symbol, snapshot.workspace.revision + 1)
        if definition is None:
            continue
        expression = _equation(definition.statement)[1]
        # Require exactly one explicit applicable given with a literal rational
        # constant and the same free identifier set. Never enumerate combinations.
        names = set(re.findall(r"[A-Za-z][A-Za-z0-9_]*", expression))
        premises = [
            a
            for a in snapshot.artifacts
            if a.artifact_id in targets
            and a.role == "given"
            and a.verification_status in {"qualified", "conditional", "verified"}
            and a.statement
            in {
                f.value
                for f in (*snapshot.problem_model.givens, *snapshot.problem_model.constraints)
                if f.status == "explicit" and f.uncertainty == 0
            }
            and _equation(a.statement) is not None
            and _polynomial_syntax(_equation(a.statement)[0])
            and re.fullmatch(r"-?\d+(?:/\d+)?", _equation(a.statement)[1])
            and set(re.findall(r"[A-Za-z][A-Za-z0-9_]*", _equation(a.statement)[0])) == names
        ]
        if len(premises) != 1:
            continue
        premise = premises[0]
        candidates.append((claim, definition, premise, symbol, expression, student_rhs))
    if len(candidates) != 1:
        return None
    claim, definition, premise, symbol, expression, student_rhs = candidates[0]
    context = {
        "session_id": submission.session_id,
        "turn_id": submission.turn_id,
        "message_id": submission.message_id,
        "episode_id": episode_id,
        "accepted_digest": hashlib.sha256(submission.raw_content.encode()).hexdigest(),
        "alignment_digest": hashlib.sha256(_json(asdict(alignment)).encode()).hexdigest(),
        "claim": asdict(claim),
        "workspace_id": snapshot.workspace.workspace_id,
        "model_digest": hashlib.sha256(_json(asdict(snapshot.problem_model)).encode()).hexdigest(),
        "premise_ref": premise.artifact_id,
        "premise_digest": math_content_digest(premise),
        "definition": definition.statement,
    }
    return context, definition, premise, symbol, expression, student_rhs


def _requests(basis, outputs):
    _, _, premise, symbol, expression, student_rhs = basis
    given, constant = _equation(premise.statement)
    requests = [("expand", {"expression": f"({expression})-({given})"})]
    if len(outputs) >= 1:
        requests.append(("expand", {"expression": f"({constant})+({outputs[0]})"}))
    if len(outputs) >= 2:
        requests.append(
            (
                "substitute",
                {"expression": f"{symbol}-({outputs[1]})", "substitutions": {symbol: expression}},
            )
        )
    if len(outputs) >= 3:
        requests.append(
            ("check_equivalence", {"left": outputs[2], "right": f"({given})-({constant})"})
        )
    if len(outputs) >= 4:
        requests.append(("expand", {"expression": f"({student_rhs})-({outputs[1]})"}))
    return requests


def _provenance(snapshot, context, revision):
    return (
        snapshot.workspace_ref,
        SourceRef("workspace_revision", f"{context['workspace_id']}@{revision}"),
        SourceRef("accepted_claim_context", hashlib.sha256(_json(context).encode()).hexdigest()),
    )


def materialize_correction_support(snapshot, targets, *, submission, alignment, episode_id):
    basis = _basis(snapshot, targets, submission, alignment, episode_id)
    if basis is None:
        return (), ()
    if correction_bindings(
        snapshot, targets, submission=submission, alignment=alignment, episode_id=episode_id
    ):
        return (), ()
    context, definition, premise, *_ = basis
    provenance = _provenance(snapshot, context, snapshot.workspace.revision)
    refs = (premise.artifact_id, definition.artifact_id, *(r.identifier for r in provenance))
    registry = MathToolRegistry(max_calls=5)
    proofs, outputs = [], []
    for index in range(5):
        kind, kwargs = _requests(basis, outputs)[index]
        result = registry.call(kind, input_refs=refs, **kwargs)
        proofs.append(result.evidence)
        if result.status != "succeeded":
            return (), tuple(proofs)
        outputs.append(result.evidence.output_summary)
        if index == 3 and outputs[3] != "True":
            return (), tuple(proofs)
    if outputs[4] == "0":
        return (), tuple(proofs)
    request = {
        "mechanism": CORRECTION_MECHANISM,
        "context": context,
        "input_revision": snapshot.workspace.revision,
        "definition_ref": definition.artifact_id,
        "outputs": outputs,
    }
    canonical = _json(request)
    correction = MathArtifact(
        canonical,
        "transformation",
        claim_kind="conditional_correction",
        normalized_form=canonical,
        provenance=provenance,
        dependencies=(premise.artifact_id, definition.artifact_id),
        verification_status="conditional",
        verification_scope=CORRECTION_SCOPE,
        tool_evidence_refs=tuple(e.evidence_id for e in proofs),
        workspace_revision=snapshot.workspace.revision + 1,
    )
    return (definition, correction), tuple(proofs)


def correction_bindings(snapshot, targets, *, submission=None, alignment=None, episode_id=None):
    basis = _basis(snapshot, targets, submission, alignment, episode_id)
    if basis is None:
        return ()
    context, _, premise, *_ = basis
    proofs = {e.evidence_id: e for e in snapshot.tool_evidence}
    artifacts = {a.artifact_id: a for a in snapshot.artifacts}
    bindings = []
    for artifact in snapshot.artifacts:
        if (
            artifact.claim_kind != "conditional_correction"
            or artifact.workspace_revision != snapshot.workspace.revision
            or artifact.verification_status != "conditional"
            or artifact.verification_scope != CORRECTION_SCOPE
            or artifact.role != "transformation"
        ):
            continue
        try:
            request = json.loads(artifact.statement)
            revision = request["input_revision"]
            definition = _definition(snapshot, basis[3], revision + 1)
            outputs = request["outputs"]
            provenance = _provenance(snapshot, context, revision)
            refs = (
                premise.artifact_id,
                definition.artifact_id,
                *(r.identifier for r in provenance),
            )
            if (
                set(request)
                != {"mechanism", "context", "input_revision", "definition_ref", "outputs"}
                or request["mechanism"] != CORRECTION_MECHANISM
                or request["context"] != context
                or type(revision) is not int
                or revision + 1 != snapshot.workspace.revision
                or request["definition_ref"] != definition.artifact_id
                or artifacts.get(definition.artifact_id) != definition
                or artifact.provenance != provenance
                or artifact.dependencies != (premise.artifact_id, definition.artifact_id)
                or artifact.normalized_form != artifact.statement
                or artifact.statement != _json(request)
                or not isinstance(outputs, list)
                or len(outputs) != 5
                or any(not isinstance(o, str) for o in outputs)
                or outputs[3] != "True"
                or outputs[4] == "0"
                or len(artifact.tool_evidence_refs) != 5
            ):
                continue
            for index, (kind, kwargs) in enumerate(_requests(basis, outputs)):
                proof = proofs.get(artifact.tool_evidence_refs[index])
                if (
                    proof is None
                    or proof.tool_name != kind
                    or proof.tool_version != MathToolRegistry.VERSION
                    or proof.status != "succeeded"
                    or proof.failure_type is not None
                    or proof.scope != MathToolRegistry._scope_for(kind)
                    or proof.input_refs != refs
                    or proof.input_summary != MathToolRegistry._input_summary(kwargs)
                    or proof.output_summary != outputs[index]
                ):
                    break
            else:
                bindings.append(
                    MathContentSupportBinding(
                        premise.artifact_id,
                        "justification",
                        SourceRef("math_artifact", artifact.artifact_id),
                        math_content_digest(artifact),
                        SourceRef("math_tool_evidence", artifact.tool_evidence_refs[3]),
                        CORRECTION_MECHANISM,
                        CORRECTION_SCOPE,
                    )
                )
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            continue
    return tuple(bindings)
