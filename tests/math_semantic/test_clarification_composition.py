"""Finite clarification composition changes display after complete acceptance."""

from copy import deepcopy
import hashlib
import json

import pytest

from deeptutor.capabilities.math_turn import output
from deeptutor.math_semantic.proposals import AlignmentProposal
from deeptutor.math_semantic.tools import MathToolRegistry

from .test_bounded_feedback import candidate, offers, prepare
from .test_bounded_feedback import initialized_host_imports as _initialized_host_imports
from .test_publication import assistant_row, replay
from .test_publication import publication_host_factory as _publication_host_factory
from .test_student_step_evidence import align, calculation, issue_task, source, state_for

publication_host_factory = _publication_host_factory
initialized_host_imports = _initialized_host_imports


def pair(inputs):
    return [
        offers(inputs, kind)[0] for kind in ("contextual_clarification", "neutral_clarification")
    ]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "text,fields",
    [("u/(v-v)=1", None), ("sqrt(u)=u", None), ("<b>u=u</b>", {"parse_status": "unparsed"})],
)
def test_one_current_object_folds_only_display_retains_both_contracts(
    text, fields, reverse, monkeypatch
):
    state, calc, inputs = prepare(text, proposal_fields=fields)
    specific, neutral = pair(inputs)
    selected = [neutral, specific] if reverse else [specific, neutral]
    before = state.serialize()
    frozen_inputs = deepcopy(inputs)
    monkeypatch.setattr(
        MathToolRegistry, "call", lambda *a, **k: pytest.fail("publication ran tool")
    )
    accepted = output.accept_response(state, calc, inputs, candidate(inputs, selected))
    body = output.ACKNOWLEDGEMENT + "\n\n" + specific["text"]
    trace = json.loads(accepted.metadata_json)["math_publication"]
    assert accepted.content == body and neutral["text"] not in body
    assert trace["selected_feedback"] == [neutral["grant"]]
    assert trace["selected_contextual_clarifications"] == [specific["grant"]]
    assert trace["selected_grants"] == []
    assert (
        trace["basis"] == inputs["basis"] and trace["authority_basis"] == inputs["authority_basis"]
    )
    assert trace["content_digest"] == hashlib.sha256(body.encode()).hexdigest()
    assert inputs == frozen_inputs and state.serialize() == before
    opposite = output.accept_response(state, calc, inputs, candidate(inputs, selected[::-1]))
    assert opposite == accepted


@pytest.mark.parametrize("kind", ["neutral_clarification", "contextual_clarification"])
def test_single_clarification_keeps_its_canonical_text(kind):
    state, calc, inputs = prepare("sqrt(u)=u")
    selected = offers(inputs, kind)
    accepted = output.accept_response(state, calc, inputs, candidate(inputs, selected))
    assert accepted.content == output.ACKNOWLEDGEMENT + "\n\n" + selected[0]["text"]


@pytest.mark.parametrize(
    "text,kind",
    [("u*(v+1)=u*v+u", "local_confirmation"), ("u*(v+1)=u*v", "local_counterexample")],
)
def test_complementary_feedback_and_requested_operation_remain(text, kind):
    reviewed = source(domain="u,v are real", givens=(), definitions=(), operation="u*(v+1)=u*v+u")
    state = state_for(reviewed, text)
    issue_task(state, text)
    calc = calculation(state)
    inputs = output.publication_input(state, calc)
    specific, neutral = pair(inputs)
    feedback = offers(inputs, kind)[0]
    operation = offers(inputs, "chosen_operation")[0]
    selected = [neutral, feedback, specific, operation]
    accepted = output.accept_response(state, calc, inputs, candidate(inputs, selected))
    assert accepted.content == "\n\n".join(
        [output.ACKNOWLEDGEMENT, feedback["text"], specific["text"], operation["text"]]
    )
    trace = json.loads(accepted.metadata_json)["math_publication"]
    assert trace["selected_grants"] == [operation["grant"]]
    assert trace["selected_feedback"] == [neutral["grant"], feedback["grant"]]
    assert trace["selected_contextual_clarifications"] == [specific["grant"]]


def test_multiple_current_objects_do_not_fold_even_if_only_one_specific_is_selected():
    quotes = ["sqrt(u)=u", "sqrt(v)=v"]
    state = state_for(source(), "; ".join(quotes))
    state.align(
        AlignmentProposal.from_value({"claims": [{"evidence": {"quote": q}} for q in quotes]}),
        expected_revision=1,
        provider_id="offline-test-extraction",
        config_digest="offline",
        check_steps=True,
    )
    calc = calculation(state)
    inputs = output.publication_input(state, calc)
    assert len(offers(inputs, "contextual_clarification")) == 2
    selected = pair(inputs)
    accepted = output.accept_response(state, calc, inputs, candidate(inputs, selected))
    assert accepted.content == "\n\n".join([output.ACKNOWLEDGEMENT, *(o["text"] for o in selected)])


def test_earlier_assignment_keeps_both_clarifications_and_original_receipt():
    reviewed = source(domain="u,v are real", givens=(), definitions=(), operation="u*(v-2)=u*v-2*u")
    first = state_for(reviewed, "u=u")
    payload, _, original = issue_task(first, "u=u")
    following = state_for(
        reviewed, "Explain that task again.", payload=payload, prefix=first.prefix
    )
    align(following, following.submission.raw_content, clarification=True)
    calc = calculation(following)
    inputs = output.publication_input(following, calc)
    selected = pair(inputs)
    assert selected[0]["grant"]["object_kind"] == "earlier_assignment"
    before = following.serialize()
    accepted = output.accept_response(following, calc, inputs, candidate(inputs, selected))
    assert accepted.content == "\n\n".join([output.ACKNOWLEDGEMENT, *(o["text"] for o in selected)])
    assert following.serialize() == before
    assert (
        json.loads(before)["host_math_publications"][first.submission.turn_id]["content"]
        == original.content
    )


@pytest.mark.parametrize(
    "field",
    [
        "session_id",
        "turn_id",
        "accepted_user_message_id",
        "student_response_ref",
        "episode_id",
        "source_digest",
        "math_workspace_ref",
        "math_revision",
        "math_basis",
        "contract",
        "text",
    ],
)
def test_invalid_generic_companion_is_rejected_before_display_folding(field):
    state, calc, inputs = prepare("sqrt(u)=u")
    altered = deepcopy(inputs)
    neutral = offers(altered, "neutral_clarification")[0]
    if field == "text":
        neutral["text"] = "Altered generic text"
    else:
        neutral["grant"][field] = "foreign-or-altered"
    before = state.serialize()
    with pytest.raises(ValueError, match="stale or foreign"):
        output.accept_response(state, calc, altered, candidate(altered, pair(altered)))
    assert state.serialize() == before


@pytest.mark.parametrize("bad", ["unknown", "stale", "duplicate"])
def test_invalid_raw_companion_does_not_disappear(bad):
    state, calc, inputs = prepare("sqrt(u)=u")
    raw = json.loads(candidate(inputs, pair(inputs)))
    if bad == "unknown":
        raw["grant_ids"].append("unknown-grant")
    elif bad == "duplicate":
        raw["grant_ids"].append(raw["grant_ids"][1])
    else:
        state.append(expected_revision=state.snapshot().workspace.revision, status="advanced")
    before = state.serialize()
    with pytest.raises(ValueError):
        output.accept_response(state, calc, inputs, json.dumps(raw))
    assert state.serialize() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_native_fold_acceptance_live_sqlite_and_replay(
    publication_host_factory, initialized_host_imports, monkeypatch, reverse
):
    host, generation, completions = publication_host_factory()
    host.source = source(
        domain="u,v are real", givens=(), definitions=(), operation="u*(v+1)=u*v+u"
    )
    host.scope = host.math_scope()
    proposed, live = [], []

    async def fixed_choice(config, _provider_spec, *, prompt, **kwargs):
        inputs = json.loads(prompt)
        selected = pair(inputs)
        if reverse:
            selected.reverse()
        raw = candidate(inputs, selected)
        generation.raw_candidates.append(raw)
        proposed.append({"inputs": inputs, "raw": raw})
        return raw

    original_live = host.runtime._publish_live_event

    async def accepted_live(execution, event):
        if event.type.value == "content":
            receipt = host.state()["host_math_publications"][execution.turn_id]
            assert receipt["content"] == event.content
            assert json.loads(receipt["metadata_json"]) == event.metadata
            live.append(event.content)
        return await original_live(execution, event)

    monkeypatch.setattr(
        "deeptutor.services.llm.factory._complete_with_resolved_config", fixed_choice
    )
    monkeypatch.setattr(host.runtime, "_publish_live_event", accepted_live)
    _, turn = await host.submit("sqrt(u)=u")
    assert len(proposed) == 1 and live
    inputs = proposed[0]["inputs"]
    specific, neutral = pair(inputs)
    body = output.ACKNOWLEDGEMENT + "\n\n" + specific["text"]
    _, stored, metadata, parent = assistant_row(host, turn["id"])
    trace = metadata["accepted_output"]["math_publication"]
    assert stored == "".join(live) == body == completions[-1].agent_output
    assert parent == host.math_contexts[-1].runtime.accepted_user_message_id
    assert trace["selected_feedback"] == [neutral["grant"]]
    assert trace["selected_contextual_clarifications"] == [specific["grant"]]
    assert (
        trace["basis"] == inputs["basis"] and trace["authority_basis"] == inputs["authority_basis"]
    )
    assert trace["content_digest"] == hashlib.sha256(body.encode()).hexdigest()
    before = host.state()

    def forbidden(*a, **k):
        pytest.fail("replay reran generation, math tool, or math mutation")

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", forbidden)
    monkeypatch.setattr(MathToolRegistry, "call", forbidden)
    monkeypatch.setattr(
        "deeptutor.capabilities.math_turn.capability.sqlite_episode_mutation", forbidden
    )
    first, second = await replay(host, turn), await replay(host, turn)
    assert first == second and host.state() == before and len(proposed) == 1
    assert "".join(e["content"] for e in first if e["type"] == "content") == body
    result = next(e["metadata"] for e in first if e["type"] == "result")
    assert result["response"] == body and result["math_publication"] == trace
