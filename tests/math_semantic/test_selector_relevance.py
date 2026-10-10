"""Selector transport retains context and every existing offer.

These are input-contract tests with a provider stub. Native authority, receipt
and replay coverage remains in the existing publication and evidence tests;
real model selection is measured by the frozen checkpoint comparison.
"""

from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.math_turn.output import generate_response


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["WHOLE_OPERATION", "LOCAL_CONTRIBUTION", "UNKNOWN"])
async def test_selector_keeps_scope_request_and_operation_aliases(monkeypatch, scope):
    # Synthetic transport markers confer no native mathematical authority.
    operation = {"kind": "expand", "kwargs": {"expression": "(a-b)^2"}}
    inputs = {
        "basis": {"accepted_user_message_id": 3},
        "authority_basis": "transport-test-basis",
        "offers": [
            {
                "grant_id": "chosen-id",
                "grant": {"act_kind": "chosen_operation"},
                "text": "same literal",
            },
            {
                "grant_id": "option-id",
                "grant": {"act_kind": "operation_options"},
                "text": "same literal",
            },
        ],
        "private_teaching_context": {
            "authority": "context_only_never_grants_truth_completion_or_mastery",
            "previous_task": {"operations": [operation]},
            "operation_correspondence": [
                {
                    "operation": operation,
                    "scope": scope,
                    "stage_completion": "UNKNOWN",
                    "mastery": "NO_INFERENCE",
                }
            ],
        },
    }
    before = deepcopy(inputs)
    accepted = "Please repeat that same operation slowly."
    calls = []

    async def proposal(**kwargs):
        calls.append(kwargs)
        request = json.loads(kwargs["prompt"])
        return json.dumps({"authority_basis": request["authority_basis"], "grant_ids": []})

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", proposal)
    raw = await generate_response(
        SimpleNamespace(runtime=SimpleNamespace(accepted_user_content=accepted)), inputs
    )
    assert inputs == before
    assert len(calls) == 1
    assert json.loads(calls[0]["prompt"]) == {"accepted_user_content": accepted, **before}
    assert json.loads(raw) == {"authority_basis": inputs["authority_basis"], "grant_ids": []}
    system = calls[0]["system_prompt"]
    # Exact frozen A + B append; this tests the sent prompt, not model behavior.
    assert hashlib.sha256(system.encode()).hexdigest() == (
        "cee12ff60b34d28d42cf5bf430e982f487852b01ae193ef8a5262038a66faf46"
    )
    assert system.endswith(
        " When composing a response, prefer supported current local confirmation together "
        "with an authorized explanation that directly answers the accepted question. "
        "Add an operation only when it provides a distinct necessary next action."
    )
    assert "UNKNOWN is uncertainty" in system
    assert "LOCAL_CONTRIBUTION leaves the rest of the assigned operation open" in system
    assert "An explicit request to repeat permits that operation again" in system
