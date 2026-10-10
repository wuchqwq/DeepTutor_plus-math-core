"""Teaching order does not remove authority or turn unknown/partial into whole."""

from copy import deepcopy
import json

import pytest

from deeptutor.capabilities.math_turn.feedback import FEEDBACK_VERSION
from deeptutor.capabilities.math_turn.output import _same_assignment, _selector_input

from .test_student_step_evidence import (
    align,
    calculation,
    issue_task,
    state_for,
)
from .test_student_step_evidence import (
    source as reviewed_source,
)


def inputs(scope):
    return {
        "authority_basis": "unchanged",
        "offers": [
            {
                "grant_id": kind,
                "grant": {"act_kind": kind, "content_ref": {"identifier": "rebound-content"}},
            }
            for kind in ("chosen_operation", "operation_options")
        ]
        + [
            {
                "grant_id": "clarify",
                "grant": {"act_kind": "neutral_clarification", "contract": FEEDBACK_VERSION},
            },
            {
                "grant_id": "confirm",
                "grant": {
                    "act_kind": "local_confirmation",
                    "claim_ref": "pending-claim",
                    "contract": FEEDBACK_VERSION,
                },
            },
        ],
        "private_teaching_context": {
            "assignment_offer_links": [
                {
                    "content_ref": "rebound-content",
                    "previous_publication_id": "accepted-receipt",
                    "claim_scopes": [{"claim_id": "pending-claim", "scope": scope}],
                }
            ]
        },
    }


@pytest.mark.parametrize("scope", ["WHOLE_OPERATION", "LOCAL_CONTRIBUTION", "UNKNOWN"])
def test_order_retains_all_grants_and_accepted_repeat_request(scope):
    source = inputs(scope)
    before = deepcopy(source)
    request = "Please repeat the same operation slowly."
    view = _selector_input(request, source)
    assert source == before and view["authority_basis"] == before["authority_basis"]
    assert view["accepted_user_content"] == request
    assert {o["grant_id"]: o for o in view["offers"]} == {
        o["grant_id"]: o for o in before["offers"]
    }
    if scope == "WHOLE_OPERATION":
        assert [o["grant_id"] for o in view["offers"]] == [
            "confirm",
            "clarify",
            "chosen_operation",
            "operation_options",
        ]
        assert "all offers remain selectable" in view["teaching_priority"]["choice"]
    else:
        assert view == {"accepted_user_content": request, **before}


def test_no_feedback_and_mixed_scope_do_not_defer_an_operation():
    for source in (inputs("WHOLE_OPERATION"), inputs("LOCAL_CONTRIBUTION")):
        source["offers"] = source["offers"][:2]
        assert "teaching_priority" not in _selector_input("next", source)
    source = inputs("WHOLE_OPERATION")
    source["private_teaching_context"]["assignment_offer_links"][0]["claim_scopes"].append(
        {"claim_id": "other", "scope": "UNKNOWN"}
    )
    assert "teaching_priority" not in _selector_input("next", source)


@pytest.mark.parametrize("changed", ["mechanism", "kind", "kwargs", "premises", "workspace_id"])
def test_assignment_identity_is_exact_structure_not_grant_or_revision(changed):
    previous = {
        "mechanism": "typed",
        "kind": "expand",
        "kwargs": {"expression": "(u-v)^2"},
        "premises": ["reviewed-premise"],
        "workspace_id": "episode",
        "input_revision": 2,
    }
    rebound = {**deepcopy(previous), "input_revision": 9}
    assert _same_assignment(rebound, previous)
    rebound[changed] = "different"
    assert not _same_assignment(rebound, previous)


def test_native_rebound_assignment_links_whole_without_removing_repeat_authority():
    from deeptutor.capabilities.math_turn.output import accept_response, publication_input
    from deeptutor.math_semantic.support import materialize_operation_support

    reviewed = reviewed_source(
        domain="u,v are real", givens=(), definitions=(), operation="u*(v-2)=u*v-2*u"
    )
    first = state_for(reviewed, "u=u")
    payload, prior_input, prior_receipt = issue_task(first, "u=u")
    request = next(o for o in prior_input["offers"] if o["grant"]["act_kind"] == "chosen_operation")
    original = json.loads(prior_receipt.metadata_json)
    following = state_for(reviewed, "(u*(v-2))-(u*v-2*u)=0", payload=payload, prefix=first.prefix)
    align(following, following.submission.raw_content)
    operations, evidence = materialize_operation_support(
        following.snapshot(), following.trajectory().applicable_artifact_refs
    )
    following.append(
        expected_revision=following.snapshot().workspace.revision,
        artifacts=operations,
        evidence=evidence,
    )
    calc = calculation(following)
    current = publication_input(following, calc)
    before = following.serialize()
    repeat = next(o for o in current["offers"] if o["grant"]["act_kind"] == "chosen_operation")
    assert request["grant_id"] != repeat["grant_id"]
    assert {
        s["scope"]
        for link in current["private_teaching_context"]["assignment_offer_links"]
        for s in link["claim_scopes"]
    } == {"WHOLE_OPERATION"}
    view = _selector_input("Repeat that exact check slowly.", current)
    assert repeat["grant_id"] in view["teaching_priority"]["repeat_of_whole_assignment_ids"]
    accepted = accept_response(
        following,
        calc,
        current,
        json.dumps(
            {"authority_basis": current["authority_basis"], "grant_ids": [repeat["grant_id"]]}
        ),
    )
    assert json.loads(accepted.metadata_json)["math_publication"]["selected_grants"] == [
        repeat["grant"]
    ]
    assert following.serialize() == before
    assert (
        json.loads(payload)["host_math_publications"][first.submission.turn_id]["metadata_json"]
        == prior_receipt.metadata_json
    )
    assert json.loads(prior_receipt.metadata_json) == original
