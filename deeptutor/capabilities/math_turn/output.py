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
from deeptutor.math_semantic.correction import CORRECTION_MECHANISM, correction_bindings
from deeptutor.math_semantic.state import MathMutation
from deeptutor.math_semantic.support import OPERATION_MECHANISM

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
    correction_grants = (
        tuple(
            binding.as_grant()
            for binding in correction_bindings(
                snapshot,
                state.trajectory().applicable_artifact_refs,
                submission=state.submission,
                alignment=state.current_alignment(),
                episode_id=state.source.identity.episode_id,
            )
        )
        if any(grant.act_kind == "justification" for grant in grants)
        else ()
    )
    for grant in grants:
        if grant.act_kind not in {
            "orientation",
            "result",
            "chosen_operation",
            "operation_options",
            "justification",
        }:
            raise ValueError("publication has no renderer for this mathematical act")
        text = ACKNOWLEDGEMENT
        if grant.act_kind == "justification":
            # A mathematical act name is not permission to disclose a complete
            # target. Recheck the bounded scope before exposing any offer text.
            if grant not in correction_grants:
                continue
            artifact = artifacts.get(grant.content_ref.identifier)
            if (
                grant.support_mechanism != CORRECTION_MECHANISM
                or artifact is None
                or math_content_digest(artifact) != grant.content_digest
            ):
                raise ValueError("publication correction lacks exact pinned content")
            request = json.loads(artifact.statement)
            premise = artifacts[request["context"]["premise_ref"]]
            definition = artifacts[request["definition_ref"]]
            symbol = definition.statement.split("=")[0]
            rhs, difference = request["outputs"][1], request["outputs"][4]
            claim = request["context"]["claim"]["normalized_form"]
            domain = "; ".join(
                fact["value"] for fact in request["context"]["scalar_domain"]["facts"]
            )
            text = (
                f"Under the explicit scalar domain {domain}, relative to the explicit premises "
                f"{definition.statement} and {premise.statement}, "
                f"the algebra gives {symbol}={rhs}. In your claim {claim}, the right-hand side "
                f"minus this derived right-hand side is {difference}. The two agree only when "
                f"{difference}=0; they are not identical expressions. "
                "This conditional check does not confirm premise truth or the complete answer."
            )
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
    return {"basis": basis, "authority_basis": _digest(basis), "offers": offers}


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
            "justification, chosen_operation or operation_options offer when available, respecting the "
            "student's method and request for a small hint. Use results only when appropriate. "
            "Operation offers check algebra relative to premises and never confirm premise "
            "truth, a student's correctness, attainability, or the complete answer."
            " A justification offer supplies only its exact conditional algebra relation; "
            "select it when it addresses the current claim."
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
        if by_id[key]["grant"]["act_kind"]
        in {"result", "chosen_operation", "operation_options", "justification"}
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
