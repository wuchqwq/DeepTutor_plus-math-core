"""Finite references to accepted objects, never mathematical feedback authority."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import re
from typing import Any

from deeptutor.math_semantic.authority import math_content_digest
from deeptutor.math_semantic.codec import _decode
from deeptutor.math_semantic.state import MathMutation
from deeptutor.math_semantic.support import OPERATION_MECHANISM, resolve_math_content_support
from deeptutor.math_semantic.validation import STEP_VERSION, step_basis
from deeptutor.math_semantic.verification import normalize_display

from .feedback import _equality_structure

CONTEXTUAL_VERSION = "accepted_object_clarification_v1"
_CHOICES = (
    " Would you like to revisit that step, look for an available continuation, "
    "or add the exact part or assumptions you want checked?"
)


def _quoted(text: str) -> bool:
    # Narrow literal alphabet avoids executable markup and free prose. Longer,
    # ambiguous or answer objects can still be identified by accepted position.
    return bool(len(text) <= 160 and re.fullmatch(r"[A-Za-z0-9 +*/^()=,._-]+", text))


def _answer_object(claim, current, snapshot) -> bool:
    answers = [
        a for a in snapshot.artifacts if a.role in {"answer", "answer_candidate", "final_answer"}
    ]
    if claim.claim_type == "answer" or any(
        r.student_claim_ref == claim.claim_id and r.artifact_ref in {a.artifact_id for a in answers}
        for r in current.relations
    ):
        return True
    # Exact display or closed syntax identity only; no solver/equivalence claim.
    for answer in answers:
        for text in (answer.statement, answer.normalized_form):
            if normalize_display(text) == normalize_display(claim.evidence.quote):
                return True
            try:
                if _equality_structure(text) == _equality_structure(claim.normalized_form):
                    return True
            except (ValueError, SyntaxError, TypeError):
                continue
    return False


def contextual_clarification_offers(
    state: MathMutation, calculation: dict[str, Any], teaching_context: dict[str, Any]
) -> list[dict[str, Any]]:
    """Resolve current exact spans, or a previously validated operation receipt.

    Resolve the latest accepted assignment against its original Core grants.
    Correspondence context can precede a newer task. No model prose or new proof.
    """
    records = json.loads(state.serialize())
    snapshot = state.snapshot()
    current = max(
        (
            a
            for value in records["alignments"].values()
            if (a := _decode(value)).student_response_ref.identifier == state.submission.response_id
            and a.output_workspace_revision <= snapshot.workspace.revision
        ),
        key=lambda a: a.workspace_revision,
        default=None,
    )
    if current is None:
        return []
    state._check_step_evidence(current)
    if current.math_workspace_ref != snapshot.workspace_ref or step_basis(
        state.snapshot(current.workspace_revision)
    ) != step_basis(snapshot):
        return []
    basis = {
        "contract": CONTEXTUAL_VERSION,
        "act_kind": "contextual_clarification",
        "support_scope": "accepted_object_reference_only_no_math_judgment",
        "session_id": state.submission.session_id,
        "turn_id": state.submission.turn_id,
        "accepted_user_message_id": state.submission.message_id,
        "student_response_ref": asdict(current.student_response_ref),
        "episode_id": state.source.identity.episode_id,
        "source_digest": math_content_digest(state.source),
        "math_workspace_ref": asdict(snapshot.workspace_ref),
        "math_revision": snapshot.workspace.revision,
        "math_basis": step_basis(snapshot),
        "alignment_ref": current.alignment_id,
    }
    offers = []
    for ordinal, claim in enumerate(current.claims[:4], 1):
        span = claim.evidence
        if (
            claim.student_response_ref != current.student_response_ref
            or state.submission.raw_content[span.start : span.end] != span.quote
        ):
            raise ValueError("contextual clarification has a foreign or altered accepted span")
        quote = _quoted(span.quote) and not _answer_object(claim, current, snapshot)
        grant = {
            **basis,
            "object_kind": "current_submission",
            "claim_ref": claim.claim_id,
            "claim_digest": math_content_digest(claim),
            "claim_position": ordinal,
            "span": {
                "start": span.start,
                "end": span.end,
                "quote_digest": hashlib.sha256(span.quote.encode()).hexdigest(),
            },
            "reference_mode": "literal_quote" if quote else "accepted_position",
        }
        text = (
            "You wrote: " + json.dumps(span.quote, ensure_ascii=False) + "."
            if quote
            else f"I am referring to submitted item {ordinal} in your latest accepted message."
        )
        # A record of UNKNOWN is a check boundary, never a negative judgment.
        # Subjective prose such as 'I am unsure' does not set claim uncertainty.
        for evidence in current.math_evidence:
            if evidence.tool_version != STEP_VERSION:
                continue
            binding = json.loads(evidence.input_summary)
            checked = json.loads(evidence.output_summary)
            if binding["claim"] != asdict(claim) or checked["local_relation"] != "UNKNOWN":
                continue
            grant.update(
                recorded_check_ref=evidence.evidence_id,
                recorded_check_digest=math_content_digest(evidence),
                checked_revision=current.workspace_revision,
                recorded_check="unsupported_form"
                if checked["reason"] == "unsupported_polynomial"
                else "no_conclusion",
            )
            text += (
                " The recorded check does not support this form and has not concluded "
                "that the equality is right or wrong."
                if grant["recorded_check"] == "unsupported_form"
                else " The recorded check did not reach a mathematical conclusion."
            )
            break
        text += " This identifies your submitted text; it does not assess correctness."
        offers.append({"grant": grant, "text": text + _CHOICES})
    if current.claims:
        return offers
    previous = None
    # Correspondence context points before the pending claim, which may precede
    # a newer accepted task. No-claim clarification follows receipt chronology;
    # invalid latest authority returns no reference rather than falling back.
    for submitted in reversed(state.prefix[:-1]):
        entry = records.get("host_math_publications", {}).get(submitted.turn_id)
        if entry is None:
            continue
        trace = json.loads(entry["metadata_json"])["math_publication"]
        old_basis = trace["basis"]
        if (
            old_basis["episode_id"] != state.source.identity.episode_id
            or old_basis["session_id"] != submitted.session_id
            or old_basis["turn_id"] != submitted.turn_id
            or old_basis["accepted_user_message_id"] != submitted.message_id
            or trace["publication_id"] != entry["publication_id"]
            or trace["content_digest"] != hashlib.sha256(entry["content"].encode()).hexdigest()
        ):
            raise ValueError("foreign or altered contextual assignment receipt")
        old = state.snapshot(old_basis["math_revision"])
        if step_basis(old) != step_basis(snapshot):
            return []
        allowed = [
            b.as_grant().to_dict()
            for b in resolve_math_content_support(
                old, calculation["trajectory"]["applicable_artifact_refs"]
            )
        ]
        artifacts = {a.artifact_id: a for a in old.artifacts}
        operations = []
        for grant in trace["selected_grants"]:
            if grant["act_kind"] not in {"chosen_operation", "operation_options"}:
                continue
            if grant not in allowed or grant["support_mechanism"] != OPERATION_MECHANISM:
                return []
            operation = json.loads(artifacts[grant["content_ref"]["identifier"]].statement)
            if operation not in operations:
                operations.append(operation)
        if operations:
            previous = {
                "turn_id": submitted.turn_id,
                "publication_id": entry["publication_id"],
                "operations": operations[:4],
            }
            break
    if not previous:
        return []
    entry = records.get("host_math_publications", {}).get(previous["turn_id"])
    if entry is None or entry["publication_id"] != previous["publication_id"]:
        raise ValueError("contextual clarification lost the validated prior assignment")
    trace = json.loads(entry["metadata_json"])["math_publication"]
    for ordinal, operation in enumerate(previous["operations"], 1):
        args = operation["kwargs"]
        if operation["kind"] == "expand":
            action = "Expand " + args["expression"] + "."
        elif operation["kind"] == "substitute":
            replacements = ", ".join(f"{k}={v}" for k, v in args["substitutions"].items())
            action = "Substitute " + replacements + " into " + args["expression"] + "."
        else:
            continue
        literal = "Try this next step: " + action
        # Quote only the canonical operation instruction found in original
        # accepted bytes, never arbitrary assistant prose or a computed result.
        if entry["content"].count(literal) != 1:
            continue
        start = entry["content"].index(literal)
        quote = _quoted(action)
        grant = {
            **basis,
            "object_kind": "earlier_assignment",
            "previous_publication_id": previous["publication_id"],
            "previous_turn_id": previous["turn_id"],
            "previous_content_digest": trace["content_digest"],
            "previous_math_revision": trace["basis"]["math_revision"],
            "operation_position": ordinal,
            "operation_digest": hashlib.sha256(
                json.dumps(operation, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "span": {
                "start": start,
                "end": start + len(literal),
                "quote_digest": hashlib.sha256(literal.encode()).hexdigest(),
            },
            "reference_mode": "literal_quote" if quote else "accepted_position",
        }
        text = (
            "An earlier assigned task was: " + json.dumps(action, ensure_ascii=False) + "."
            if quote
            else f"I am referring to task {ordinal} in the earlier accepted assignment."
        )
        offers.append(
            {
                "grant": grant,
                "text": text
                + " This identifies the instruction; it does not assess your work."
                + _CHOICES,
            }
        )
    return offers
