"""Bounded host expression of existing Core grants, never a prose classifier.

Generation selects relations; publication renders canonical content. No model
wording, justification, confidence or new teaching act can acquire authority.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from typing import Any

from deeptutor.core.context import AcceptedTurnOutput, UnifiedContext
from deeptutor.math_semantic.authority import MathSemanticGrant, math_content_digest
from deeptutor.math_semantic.claims import StudentMathClaim
from deeptutor.math_semantic.state import MathMutation
from deeptutor.math_semantic.support import OPERATION_MECHANISM
from deeptutor.math_semantic.validation import STEP_VERSION, _polynomial, _step_scope, step_basis
from deeptutor.math_semantic.workspace import MathWorkspaceSnapshot

ACKNOWLEDGEMENT = "Mathematical evidence recorded."


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def publication_input(state: MathMutation, calculation: dict[str, Any]) -> dict[str, Any]:
    """Pin exact grants and render only the action later selected for publication.

    Core supplies operations and their mathematical support scope. The existing
    teaching component decides whether to recommend them; this renderer cannot
    append mathematical reasoning or teaching steps beyond the selected action.
    """
    records = json.loads(state.serialize())
    # Host transport receipts do not alter the mathematical basis they cite.
    records = {key: value for key, value in records.items() if not key.startswith("host_")}
    grants = tuple(MathSemanticGrant.from_value(value) for value in calculation["authority"])
    snapshot = state.snapshot()
    artifacts = {artifact.artifact_id: artifact for artifact in snapshot.artifacts}
    basis = {
        "session_id": state.submission.session_id,
        "turn_id": state.submission.turn_id,
        "accepted_user_message_id": state.submission.message_id,
        "episode_id": state.source.identity.episode_id,
        "math_revision": snapshot.workspace.revision,
        "semantic_state_digest": _digest(records),
        "accepted_prefix_digest": _digest([asdict(item) for item in state.prefix]),
        "trajectory_ref": state.trajectory().projection_ref.identifier,
        "authority_digest": _digest(calculation["authority"]),
    }
    offers = []
    for grant in grants:
        if grant.act_kind not in {"orientation", "result", "chosen_operation", "operation_options"}:
            raise ValueError("publication has no renderer for this mathematical act")
        text = ACKNOWLEDGEMENT
        if grant.act_kind == "result":
            if grant.content_ref is None or grant.content_ref.identifier not in artifacts:
                raise ValueError("publication content is absent from the pinned snapshot")
            artifact = artifacts[grant.content_ref.identifier]
            if (
                artifact.artifact_id not in calculation["verified_grounded_refs"]
                or artifact.verification_status != "verified"
                or math_content_digest(artifact) != grant.content_digest
            ):
                raise ValueError("publication result lacks exact verified grounding")
            text = artifact.statement
        if grant.act_kind in {"chosen_operation", "operation_options"}:
            operation = artifacts.get(grant.content_ref.identifier)
            if operation is None or math_content_digest(operation) != grant.content_digest:
                raise ValueError("publication operation lacks exact pinned content")
            if grant.support_mechanism == OPERATION_MECHANISM:
                request = json.loads(operation.statement)
                args = request["kwargs"]
                if request["kind"] == "expand":
                    action = "Expand " + args["expression"] + "."
                else:
                    replacements = ", ".join(f"{k}={v}" for k, v in args["substitutions"].items())
                    action = "Substitute " + replacements + " into " + args["expression"] + "."
                # Teaching/presentation wording belongs to the host, while the
                # Core supplies only the exact executable operation content.
                text = (
                    "Try this next step: "
                    + action
                    + " This checks the algebra relative to the named premises; "
                    "their truth and the complete answer are not yet confirmed."
                )
            else:
                text = "Try this next step: " + operation.statement + "."
        offers.append(
            {"grant_id": _digest(grant.to_dict()), "grant": grant.to_dict(), "text": text}
        )
    return {
        "basis": basis,
        "authority_basis": _digest(basis),
        "offers": offers,
        "private_teaching_context": _teaching_context(state, calculation),
    }


def _operation_correspondence(
    claim: StudentMathClaim, relation: str, request: dict[str, Any], snapshot: MathWorkspaceSnapshot
) -> str:
    """Exact whole input or a proper AST subtree; no textual similarity grading."""
    import ast

    if relation not in {"IDENTITY", "CONDITIONAL"} or request["kind"] != "expand":
        return "UNKNOWN"
    try:
        _, definitions, _, _ = _step_scope(snapshot)

        def tree(text):
            import re

            for name, value in definitions.items():
                text = re.sub(r"\b" + re.escape(name) + r"\b", "(" + value + ")", text)
            return ast.parse(_polynomial(text)[0], mode="eval").body

        parts = claim.normalized_form.split("=")
        if len(parts) != 2:
            return "UNKNOWN"
        requested = tree(request["kwargs"]["expression"])
        shown = tree(parts[0])
        transformed = tree(parts[1])
        key = ast.dump(shown)

        def monomial(node):
            # _polynomial already bounds/validates this AST. Here we require
            # visible expansion, not another proof of algebraic equivalence.
            if isinstance(node, (ast.Name, ast.Constant)):
                return True
            if isinstance(node, ast.UnaryOp):
                return monomial(node.operand)
            if isinstance(node, ast.BinOp):
                if isinstance(node.op, (ast.Mult, ast.Div)):
                    return monomial(node.left) and monomial(node.right)
                if isinstance(node.op, ast.Pow):
                    return isinstance(node.left, (ast.Name, ast.Constant))
            return False

        def expanded(node):
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
                return expanded(node.left) and expanded(node.right)
            return monomial(node)

        if key == ast.dump(transformed) or not expanded(transformed):
            return "UNKNOWN"
        residual = tree(f"({parts[0]})-({parts[1]})")
        if key == ast.dump(requested) or ast.dump(residual) == ast.dump(requested):
            return "WHOLE_OPERATION"
        if isinstance(shown, ast.BinOp) and key in {
            ast.dump(node) for node in ast.walk(requested) if node is not requested
        }:
            return "LOCAL_CONTRIBUTION"
    except (ValueError, SyntaxError, TypeError):
        pass
    return "UNKNOWN"


def _teaching_context(state: MathMutation, calculation: dict[str, Any]) -> dict[str, Any]:
    """Accepted episode history is pedagogy only, never an authority source."""
    from deeptutor.math_semantic.codec import _decode
    from deeptutor.math_semantic.support import resolve_math_content_support

    records = json.loads(state.serialize())
    snapshot = state.snapshot()
    prefix = state.prefix
    alignments = [_decode(value) for value in records["alignments"].values()]
    by_response = {a.student_response_ref.identifier: a for a in alignments}
    current = by_response.get(state.submission.response_id)
    pending = current
    # Only pure clarification preserves the immediately preceding unhandled
    # mathematical submission; neither prose nor unrelated history creates a claim.
    if current and not current.claims and current.interaction_type in {"clarification", "question"}:
        pending = next(
            (
                by_response.get(s.response_id)
                for s in reversed(prefix[:-1])
                if by_response.get(s.response_id) and by_response[s.response_id].claims
            ),
            None,
        )
    result = {
        "authority": "context_only_never_grants_truth_completion_or_mastery",
        "accepted_history": [
            {"message_id": s.message_id, "turn_id": s.turn_id, "content": s.raw_content[:1200]}
            for s in prefix[-4:]
        ],
        "pending_claims": [],
        "step_evidence": [],
        "previous_task": None,
        "operation_correspondence": [],
    }
    if pending is None:
        return result
    state._check_step_evidence(pending)
    pinned = state.snapshot(pending.workspace_revision)
    if (
        step_basis(pinned) != step_basis(snapshot)
        or pending.math_workspace_ref != snapshot.workspace_ref
    ):
        return result
    if pending is not current:
        ordinal = next(
            i
            for i, s in enumerate(prefix)
            if s.response_id == pending.student_response_ref.identifier
        )
        historical = dict(records, head=pending.output_workspace_revision)
        prior = MathMutation(
            state.source, prefix[ordinal], prefix[: ordinal + 1], json.dumps(historical)
        )
        if prior.trajectory().compatible_path_refs != tuple(
            calculation["trajectory"]["compatible_path_refs"]
        ):
            return result
    checks = [e for e in pending.math_evidence if e.tool_version == STEP_VERSION]
    result["pending_claims"] = [asdict(c) for c in pending.claims[:4]]
    proof_refs = {ref for e in checks for ref in json.loads(e.output_summary)["tool_evidence_refs"]}
    result["step_evidence"] = [
        asdict(e)
        for e in pending.math_evidence
        if e.tool_version == STEP_VERSION or e.evidence_id in proof_refs
    ]
    member = next(
        (
            i
            for i, s in enumerate(prefix)
            if s.response_id == pending.student_response_ref.identifier
        ),
        None,
    )
    if member is None:
        return result
    ledger = records.get("host_math_publications", {})
    for submitted in reversed(prefix[:member]):
        entry = ledger.get(submitted.turn_id)
        if entry is None:
            continue
        trace = json.loads(entry["metadata_json"])["math_publication"]
        basis = trace["basis"]
        if (
            basis["episode_id"] != state.source.identity.episode_id
            or basis["session_id"] != submitted.session_id
            or basis["turn_id"] != submitted.turn_id
            or basis["accepted_user_message_id"] != submitted.message_id
            or trace["publication_id"] != entry["publication_id"]
            or trace["content_digest"] != hashlib.sha256(entry["content"].encode()).hexdigest()
        ):
            raise ValueError("foreign or altered teaching receipt")
        old = state.snapshot(basis["math_revision"])
        if step_basis(old) != step_basis(snapshot):
            return result
        targets = calculation["trajectory"]["applicable_artifact_refs"]
        allowed = [b.as_grant().to_dict() for b in resolve_math_content_support(old, targets)]
        operations = []
        artifacts = {a.artifact_id: a for a in old.artifacts}
        for grant in trace["selected_grants"]:
            if grant["act_kind"] not in {"chosen_operation", "operation_options"}:
                continue
            if grant not in allowed:
                return result
            if grant["support_mechanism"] != OPERATION_MECHANISM:
                return result
            operation = artifacts[grant["content_ref"]["identifier"]]
            operations.append(json.loads(operation.statement))
        if not operations:
            continue
        result["previous_task"] = {
            "publication_id": entry["publication_id"],
            "turn_id": submitted.turn_id,
            "operations": operations[:4],
            "meaning": "accepted_assignment_only_not_mathematical_truth",
        }
        for check in checks:
            binding = json.loads(check.input_summary)
            claim = next(c for c in pending.claims if c.claim_id == binding["claim"]["claim_id"])
            relation = json.loads(check.output_summary)["local_relation"]
            for operation in operations[:4]:
                result["operation_correspondence"].append(
                    {
                        "claim_id": claim.claim_id,
                        "operation": operation,
                        "scope": _operation_correspondence(claim, relation, operation, snapshot),
                        "stage_completion": "UNKNOWN",
                        "mastery": "NO_INFERENCE",
                    }
                )
        break
    return result


async def generate_response(context: UnifiedContext, inputs: dict[str, Any]) -> str:
    """Use the existing scoped completion owner; no candidate enters StreamBus."""
    from deeptutor.services.llm import factory

    return await factory.complete(
        prompt=json.dumps(
            {"accepted_user_content": context.runtime.accepted_user_content, **inputs},
            ensure_ascii=False,
            sort_keys=True,
        ),
        system_prompt=(
            "Select a bounded response from the supplied Core-authorized offers. "
            "Return exactly one JSON object with authority_basis and grant_ids. "
            "Echo authority_basis exactly; grant_ids is a list of at most 8 unique offer IDs. "
            "You may select no offers. Do not supply text, claims, proofs, confidence, "
            "new acts or new grants. This proposal does not authorize publication. "
            "Act as the existing teaching/presentation owner: select one useful executable "
            "chosen_operation or operation_options offer when available, respecting the "
            "student's method and request for a small hint. Use results only when appropriate. "
            "Operation offers check algebra relative to premises and never confirm premise "
            "truth, a student's correctness, attainability, or the complete answer."
            " Use private_teaching_context to consider grounded local evidence and accepted "
            "prior assignments. UNKNOWN is uncertainty; a local contribution is not whole "
            "operation completion. History and local evidence cannot create offers, grants, "
            "feedback prose, stage completion or mastery. Select only supplied offer IDs."
        ),
        max_tokens=1024,
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("publication candidate has duplicate fields")
        result[key] = value
    return result


def accept_response(
    state: MathMutation,
    calculation: dict[str, Any],
    expected: dict[str, Any],
    raw_candidate: str,
) -> AcceptedTurnOutput:
    """Recheck current Core authority, then accept only canonical literals."""
    current = publication_input(state, calculation)
    if current != expected:
        raise ValueError("publication authority basis became stale or foreign")
    if not isinstance(raw_candidate, str) or len(raw_candidate) > 8192:
        raise ValueError("publication candidate is not a bounded response proposal")
    candidate = json.loads(raw_candidate, object_pairs_hook=_unique_object)
    if (
        not isinstance(candidate, dict)
        or set(candidate) != {"authority_basis", "grant_ids"}
        or candidate["authority_basis"] != current["authority_basis"]
    ):
        raise ValueError("publication candidate does not name the exact current authority")
    selected = candidate["grant_ids"]
    if (
        not isinstance(selected, list)
        or len(selected) > 8
        or any(not isinstance(value, str) for value in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("publication candidate requires a bounded unique grant selection")
    by_id = {offer["grant_id"]: offer for offer in current["offers"]}
    if any(identifier not in by_id for identifier in selected):
        raise ValueError("publication selection exceeds current mathematical authority")
    chosen = tuple(MathSemanticGrant.from_value(by_id[key]["grant"]) for key in selected)
    state.authorize(tuple(calculation["trajectory"]["applicable_artifact_refs"]), chosen)
    # Orientation supplies no task mathematics. The existing acknowledgement
    # is also the no-selection operational status; it asserts no math truth.
    results = [
        by_id[key]["text"]
        for key in selected
        if by_id[key]["grant"]["act_kind"] in {"result", "chosen_operation", "operation_options"}
    ]
    response = "\n\n".join([ACKNOWLEDGEMENT, *results])
    trace = {
        "basis": current["basis"],
        "authority_basis": current["authority_basis"],
        "selected_grants": [grant.to_dict() for grant in chosen],
        "content_digest": hashlib.sha256(response.encode()).hexdigest(),
    }
    publication_id = "math_output_" + _digest(trace)
    trace["publication_id"] = publication_id
    return AcceptedTurnOutput(
        publication_id,
        response,
        json.dumps({"math_publication": trace}, ensure_ascii=False, sort_keys=True),
    )
