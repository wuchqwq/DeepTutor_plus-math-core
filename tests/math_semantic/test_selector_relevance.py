"""Selector input and bounded fallback through the original host acceptance seam.

The provider stub exercises the seam, never claims to establish model behavior.
Real model selection is measured separately using frozen checkpoint comparisons.
"""

import json

import pytest

from deeptutor.capabilities.math_turn.output import ACKNOWLEDGEMENT

from .test_publication import assistant_row, replay
from .test_publication import publication_host_factory as _publication_host_factory
from .test_student_step_evidence import source

publication_host_factory = _publication_host_factory
SUM = "(a-b)^2+(a+b)^2=2*a^2+2*b^2"
LOCAL = "(a-b)^2=a^2-2*a*b+b^2"
WHOLE = "((a-b)^2+(a+b)^2)-(2*a^2+2*b^2)=0"


@pytest.mark.asyncio
@pytest.mark.parametrize("text,scope", [(WHOLE, "WHOLE_OPERATION"), (LOCAL, "LOCAL_CONTRIBUTION")])
async def test_no_selection_preserves_exact_context_offers_and_host_receipt(
    publication_host_factory, monkeypatch, text, scope
):
    host, generation, _ = publication_host_factory()
    host.source = source(domain="a,b are real", givens=(), definitions=(), operation=SUM)
    host.scope = host.math_scope()
    generation.mode = "operation"
    session, first = await host.submit(LOCAL)
    prior = assistant_row(host, first["id"])[2]["accepted_output"]["math_publication"]
    requests = []

    async def choose_none(_config, _spec, *, prompt, **_kwargs):
        inputs = json.loads(prompt)
        requests.append(inputs)
        return json.dumps({"authority_basis": inputs["authority_basis"], "grant_ids": []})

    monkeypatch.setattr("deeptutor.services.llm.factory._complete_with_resolved_config", choose_none)
    _, second = await host.submit(text, session_id=session["session_id"])
    inputs = requests[-1]
    private = inputs["private_teaching_context"]
    assert inputs["accepted_user_content"] == text
    assert private["previous_task"]["publication_id"] == prior["publication_id"]
    assert {item["scope"] for item in private["operation_correspondence"]} == {scope}
    assert all(
        item["stage_completion"] == "UNKNOWN" and item["mastery"] == "NO_INFERENCE"
        for item in private["operation_correspondence"]
    )
    # The selector policy cannot erase either authorized alias to force its choice.
    operations = [
        offer for offer in inputs["offers"]
        if offer["grant"]["act_kind"] in {"chosen_operation", "operation_options"}
    ]
    assert {offer["grant"]["act_kind"] for offer in operations} == {
        "chosen_operation", "operation_options"
    }
    assert len({offer["text"] for offer in operations}) < len(operations)
    body = assistant_row(host, second["id"])[1]
    receipt = assistant_row(host, second["id"])[2]["accepted_output"]["math_publication"]
    assert body == ACKNOWLEDGEMENT and receipt["selected_grants"] == []
    assert receipt["basis"] == inputs["basis"]
    before = host.state()
    events = await replay(host, second)
    assert host.state() == before
    assert "".join(event["content"] for event in events if event["type"] == "content") == body
    assert len(requests) == 1
