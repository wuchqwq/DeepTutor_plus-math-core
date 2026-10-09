"""Two finite host feedback acts, resolved from current accepted Core evidence.

These contracts neither reuse math-content grants nor admit claims or results.
The publication owner re-resolves them under the existing acceptance fence.
"""

from __future__ import annotations

import ast
from dataclasses import asdict
import json
from typing import Any

from deeptutor.math_semantic.authority import math_content_digest
from deeptutor.math_semantic.codec import _decode
from deeptutor.math_semantic.state import MathMutation
from deeptutor.math_semantic.validation import STEP_VERSION, _polynomial, _step_scope, step_basis
from deeptutor.math_semantic.verification import normalize_display

FEEDBACK_VERSION = "bounded_math_feedback_v1"
CLARIFICATION = (
    "Which expression or transformation in your current step would you like help with? "
    "Please point to that part."
)
_LIMIT = (
    " This checks only that submitted equality; it does not confirm the question's "
    "premises, the complete answer, task completion, or mastery."
)


def feedback_offers(state: MathMutation) -> list[dict[str, Any]]:
    """Canonical contracts and short templates; no tools, history carry or prose generation.

    v1 supports compound polynomial equalities only. Answer claims, scalar
    answers and correspondence to authored answer artifacts cannot acquire
    result disclosure through a local check, even when the check is positive.
    """
    snapshot = state.snapshot()
    records = json.loads(state.serialize())
    alignments = [_decode(value) for value in records["alignments"].values()]
    current = max(
        (
            a
            for a in alignments
            if a.student_response_ref.identifier == state.submission.response_id
            and a.output_workspace_revision <= snapshot.workspace.revision
        ),
        key=lambda a: a.workspace_revision,
        default=None,
    )
    if current is None:
        return []
    state._check_step_evidence(current)
    basis = {
        "contract": FEEDBACK_VERSION,
        "session_id": state.submission.session_id,
        "turn_id": state.submission.turn_id,
        "accepted_user_message_id": state.submission.message_id,
        "student_response_ref": asdict(current.student_response_ref),
        "episode_id": state.source.identity.episode_id,
        "source_digest": math_content_digest(state.source),
        "math_workspace_ref": asdict(snapshot.workspace_ref),
        "math_revision": snapshot.workspace.revision,
        "math_basis": step_basis(snapshot),
    }
    offers = [
        {
            "grant": {
                **basis,
                "act_kind": "neutral_clarification",
                "support_scope": "no_task_math_content",
            },
            "text": CLARIFICATION,
        }
    ]
    before = state.snapshot(current.workspace_revision)
    if (
        current.math_workspace_ref != snapshot.workspace_ref
        or step_basis(before) != step_basis(snapshot)
        or current.uncertainty not in {None, 0}
    ):
        return offers
    # Reuse the checker's finite explicit-domain/premise scope, without
    # invoking any mathematical tool during publication acceptance.
    try:
        symbols, _, _, _ = _step_scope(snapshot)
    except ValueError:
        return offers
    answer_refs = {
        a.artifact_id
        for a in snapshot.artifacts
        if a.role in {"answer", "answer_candidate", "final_answer"}
    }
    # Provider candidate refs may intentionally omit an authored answer.
    # Exclude known answer content from the complete pinned snapshot, using
    # only the existing display normalization (no mathematical tool here).
    answer_forms = {
        normalize_display(a.normalized_form).replace(" ", "")
        for a in snapshot.artifacts
        if a.artifact_id in answer_refs
    }
    proofs = {e.evidence_id: e for e in snapshot.tool_evidence}
    for ordinal, claim in enumerate(current.claims[:4], 1):
        if (
            claim.claim_type not in {"equation", "identity"}
            or claim.parse_status != "parsed"
            or claim.uncertainty not in {None, 0}
            or claim.student_response_ref != current.student_response_ref
            or state.submission.raw_content[claim.evidence.start : claim.evidence.end]
            != claim.evidence.quote
            or normalize_display(claim.evidence.quote) != claim.normalized_form
            or claim.normalized_form.replace(" ", "") in answer_forms
            or any(
                r.student_claim_ref == claim.claim_id and r.artifact_ref in answer_refs
                for r in current.relations
            )
        ):
            continue
        try:
            parts = claim.normalized_form.split("=")
            if len(parts) != 2:
                continue
            left, left_names, _ = _polynomial(parts[0])
            _, right_names, _ = _polynomial(parts[1])
            if not (left_names | right_names) & symbols or not isinstance(
                ast.parse(left, mode="eval").body, ast.BinOp
            ):
                continue
        except (ValueError, SyntaxError, TypeError):
            continue
        for evidence in current.math_evidence:
            if evidence.tool_version != STEP_VERSION:
                continue
            binding = json.loads(evidence.input_summary)
            checked = json.loads(evidence.output_summary)
            relation = checked["local_relation"]
            expected_reason = {
                "IDENTITY": "zero_polynomial_over_explicit_reals",
                "CONDITIONAL": "zero_after_explicit_definitions",
            }.get(relation)
            if (
                binding["claim"] != asdict(claim)
                or expected_reason is None
                or checked["reason"] != expected_reason
                or evidence.status != "succeeded"
                or evidence.failure_type is not None
                or not checked["tool_evidence_refs"]
                or any(proofs[ref].status != "succeeded" for ref in checked["tool_evidence_refs"])
            ):
                continue
            grant = {
                **basis,
                "act_kind": "local_confirmation",
                "claim_ref": claim.claim_id,
                "claim_digest": math_content_digest(claim),
                "claim_position": ordinal,
                "support_ref": evidence.evidence_id,
                "support_digest": math_content_digest(evidence),
                "checked_revision": current.workspace_revision,
                "local_relation": relation,
                "support_scope": "submitted_equality_only_no_result_completion_or_mastery",
            }
            if relation == "IDENTITY":
                text = f"Submitted equality {ordinal} is an algebraic identity in the question's explicit real scalar domain."
            else:
                text = (
                    f"Submitted equality {ordinal} has zero residual after applying the question's explicit definitions "
                    "in its explicit real scalar domain. This support depends on those definitions."
                )
            offers.append({"grant": grant, "text": text + _LIMIT})
            break
    return offers
