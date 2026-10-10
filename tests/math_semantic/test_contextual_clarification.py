"""Accepted references identify an object without grading or widening Core grants."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from deeptutor.capabilities.math_turn.contextual_clarification import CONTEXTUAL_VERSION
from deeptutor.capabilities.math_turn.output import accept_response, publication_input
from deeptutor.math_semantic.contracts import MathArtifact
from deeptutor.math_semantic.state import MathMutation
from deeptutor.math_semantic.tools import MathToolRegistry

from .test_bounded_feedback import candidate, offers, prepare, select_feedback
from .test_bounded_feedback import initialized_host_imports as _initialized_host_imports
from .test_publication import assistant_row, replay
from .test_publication import publication_host_factory as _publication_host_factory
from .test_student_step_evidence import TRUE, align, calculation, issue_task, source, state_for

publication_host_factory = _publication_host_factory
initialized_host_imports = _initialized_host_imports


@pytest.mark.parametrize("text", ["a/(b-b)=1", "sqrt(x)=x", "(u-v)^2=u^2-2*u*v+v^2"])
def test_exact_accepted_reference_and_unknown_record_are_not_math_judgments(text, monkeypatch):
    state, calc, inputs = prepare(text)
    selected = offers(inputs, "contextual_clarification")
    assert len(selected) == 1
    grant = selected[0]["grant"]
    assert grant["contract"] == CONTEXTUAL_VERSION
    assert grant["reference_mode"] == "literal_quote"
    assert grant["object_kind"] == "current_submission"
    assert grant["span"] == {
        "start": 0,
        "end": len(text),
        "quote_digest": hashlib.sha256(text.encode()).hexdigest(),
    }
    assert grant["source_digest"] and grant["episode_id"] == state.source.identity.episode_id
    assert grant["math_revision"] == state.snapshot().workspace.revision
    before = state.serialize()
    monkeypatch.setattr(
        MathToolRegistry, "call", lambda *a, **k: pytest.fail("publication ran tool")
    )
    accepted = accept_response(state, calc, inputs, candidate(inputs, selected))
    trace = json.loads(accepted.metadata_json)["math_publication"]
    assert trace["selected_contextual_clarifications"] == [grant]
    assert trace["selected_grants"] == [] and "selected_feedback" not in trace
    assert "You wrote: " + json.dumps(text) in accepted.content
    assert "does not assess correctness" in accepted.content
    assert "available continuation" in accepted.content and "assumptions" in accepted.content
    assert (
        "algebraic identity" not in accepted.content and "complete answer" not in accepted.content
    )
    if text in {"a/(b-b)=1", "sqrt(x)=x"}:
        assert grant["recorded_check"] == "unsupported_form"
        assert "has not concluded" in accepted.content
    assert state.serialize() == before


def test_subjective_unsure_remains_attributed_text_not_claim_uncertainty():
    text = "I am unsure about sqrt(x)=x."
    state = state_for(source(), text)
    from deeptutor.math_semantic.proposals import AlignmentProposal

    current = state.align(
        AlignmentProposal.from_value(
            {"claims": [{"evidence": {"quote": "sqrt(x)=x"}, "claim_type": "equation"}]}
        ),
        expected_revision=1,
        provider_id="test-only-extraction",
        config_digest="offline",
        check_steps=True,
    )
    assert current.uncertainty is None and current.claims[0].uncertainty is None
    selected = offers(publication_input(state, calculation(state)), "contextual_clarification")
    assert selected[0]["grant"]["span"]["start"] == text.index("sqrt")
    assert selected[0]["grant"]["recorded_check"] == "unsupported_form"


def test_tool_timeout_is_no_conclusion_not_unsupported_or_wrong(monkeypatch):
    monkeypatch.setattr(
        MathToolRegistry,
        "call",
        lambda self, op, **k: self._failure(op, "timeout", "test deadline", k["input_refs"]),
    )
    _, _, inputs = prepare(TRUE)
    selected = offers(inputs, "contextual_clarification")
    assert selected[0]["grant"]["recorded_check"] == "no_conclusion"
    assert "did not reach a mathematical conclusion" in selected[0]["text"]
    assert "does not support this form" not in selected[0]["text"]


@pytest.mark.parametrize("text", ["a*(b+1)=a*b+a", "((a*b+a))=((a*(b+1)))"])
@pytest.mark.parametrize("role", ["answer", "answer_candidate", "final_answer"])
def test_known_answer_uses_position_even_when_extractor_omits_answer(text, role):
    reviewed = source(domain="a,b are real", givens=(), definitions=(), operation="a*(b+1)=a*b+a")
    snap = reviewed.authored
    answer = MathArtifact(
        "Hidden authored prose",
        role,
        normalized_form="a*(b+1)=a*b+a",
        provenance=snap.problem_model.provenance,
    )
    reviewed = replace(
        reviewed,
        authored=replace(
            snap,
            artifacts=(*snap.artifacts, answer),
            workspace=replace(
                snap.workspace, artifact_refs=(*snap.workspace.artifact_refs, answer.artifact_id)
            ),
        ),
    )
    state, calc, inputs = prepare(
        text,
        reviewed,
        proposal_fields={
            "claim_type": "equation",
            "candidate_artifact_refs": [snap.artifacts[0].artifact_id],
        },
    )
    selected = offers(inputs, "contextual_clarification")
    assert selected[0]["grant"]["reference_mode"] == "accepted_position"
    accepted = accept_response(state, calc, inputs, candidate(inputs, selected))
    assert "submitted item 1" in accepted.content
    assert text not in accepted.content + accepted.metadata_json
    assert "Hidden authored prose" not in accepted.content + accepted.metadata_json
    assert not offers(inputs, "local_confirmation")


@pytest.mark.parametrize(
    "text,fields",
    [
        (TRUE, {"claim_type": "answer"}),
        ("<b>x=x</b>", {"parse_status": "unparsed"}),
        ("x" * 170, {"parse_status": "unparsed"}),
    ],
)
def test_answer_markup_and_long_objects_have_bounded_position_reference(text, fields):
    state, calc, inputs = prepare(text, proposal_fields=fields)
    selected = offers(inputs, "contextual_clarification")
    assert selected[0]["grant"]["reference_mode"] == "accepted_position"
    accepted = accept_response(state, calc, inputs, candidate(inputs, selected))
    assert text not in accepted.content + accepted.metadata_json


def test_no_object_and_no_receipt_do_not_quote_pending_historical_claim():
    first = state_for(source(), TRUE)
    align(first, TRUE)
    following = state_for(
        first.source, "Please explain again.", payload=first.serialize(), prefix=first.prefix
    )
    align(following, following.submission.raw_content, clarification=True)
    inputs = publication_input(following, calculation(following))
    assert inputs["private_teaching_context"]["pending_claims"]
    assert not offers(inputs, "contextual_clarification")
    empty = state_for(source(), "Which step?")
    align(empty, empty.submission.raw_content, clarification=True)
    assert not offers(publication_input(empty, calculation(empty)), "contextual_clarification")


def test_prior_reference_binds_original_receipt_bytes_without_claiming_latest_work(monkeypatch):
    reviewed = source(domain="u,v are real", givens=(), definitions=(), operation="u*(v-2)=u*v-2*u")
    first = state_for(reviewed, "u=u")
    payload, _, receipt = issue_task(first, "u=u")
    following = state_for(
        reviewed, "Explain that earlier task again.", payload=payload, prefix=first.prefix
    )
    align(following, following.submission.raw_content, clarification=True)
    calc = calculation(following)
    inputs = publication_input(following, calc)
    selected = offers(inputs, "contextual_clarification")
    grant = selected[0]["grant"]
    assert grant["object_kind"] == "earlier_assignment"
    assert grant["previous_publication_id"] == receipt.publication_id
    assert grant["previous_content_digest"] == hashlib.sha256(receipt.content.encode()).hexdigest()
    span = grant["span"]
    assert (
        hashlib.sha256(receipt.content[span["start"] : span["end"]].encode()).hexdigest()
        == span["quote_digest"]
    )
    assert "recorded_check" not in grant and "claim_ref" not in grant
    before = following.serialize()
    monkeypatch.setattr(MathToolRegistry, "call", lambda *a, **k: pytest.fail("reference ran tool"))
    accepted = accept_response(following, calc, inputs, candidate(inputs, selected))
    assert "An earlier assigned task was:" in accepted.content and "Expand" in accepted.content
    assert "You wrote" not in accepted.content and "identity" not in accepted.content
    assert following.serialize() == before
    assert (
        json.loads(before)["host_math_publications"][first.submission.turn_id]
        == json.loads(payload)["host_math_publications"][first.submission.turn_id]
    )
    altered = json.loads(before)
    altered["host_math_publications"][first.submission.turn_id]["content"] += " changed"
    foreign = MathMutation(reviewed, following.submission, following.prefix, json.dumps(altered))
    with pytest.raises(ValueError, match="altered .*receipt"):
        publication_input(foreign, calc)
    # A receipt whose selected operation no longer belongs to the original
    # Core authority cannot become a reference through the no-claim fallback.
    altered = json.loads(before)
    entry = altered["host_math_publications"][first.submission.turn_id]
    trace = json.loads(entry["metadata_json"])
    trace["math_publication"]["selected_grants"][0]["support_mechanism"] = "foreign"
    entry["metadata_json"] = json.dumps(trace)
    unsupported = MathMutation(
        reviewed, following.submission, following.prefix, json.dumps(altered)
    )
    assert not offers(publication_input(unsupported, calc), "contextual_clarification")


@pytest.mark.parametrize(
    "field", ["source_digest", "episode_id", "math_revision", "span", "reference_mode", "text"]
)
def test_re_resolution_rejects_tampered_reference_or_prose(field):
    state, calc, inputs = prepare("sqrt(x)=x")
    altered = deepcopy(inputs)
    target = offers(altered, "contextual_clarification")[0]
    if field == "text":
        target[field] = "This proves the complete answer."
    else:
        target["grant"][field] = "forged"
    with pytest.raises(ValueError, match="stale or foreign"):
        accept_response(state, calc, altered, candidate(altered, [target]))


def test_old_and_foreign_reference_ids_cannot_be_selected_or_widened():
    _, _, old = prepare("sqrt(x)=x")
    state, calc, current = prepare("sqrt(y)=y", source(episode="foreign-episode"))
    with pytest.raises(ValueError, match="exceeds current"):
        accept_response(
            state, calc, current, candidate(current, offers(old, "contextual_clarification"))
        )
    target = offers(current, "contextual_clarification")
    raw = json.loads(candidate(current, target))
    raw["text"] = "New mathematical proof"
    with pytest.raises(ValueError, match="exact current authority"):
        accept_response(state, calc, current, json.dumps(raw))


@pytest.mark.asyncio
async def test_contextual_reference_acceptance_precedes_live_and_replays_exact_receipt(
    publication_host_factory, initialized_host_imports, monkeypatch
):
    host, generation, completions = publication_host_factory()
    host.source = source()
    host.scope = host.math_scope()
    select_feedback(generation, monkeypatch, "contextual_clarification")
    observed = []
    original = host.runtime._publish_live_event

    async def before_live(execution, event):
        if event.type.value == "content":
            receipt = host.state()["host_math_publications"][execution.turn_id]
            assert receipt["content"] == event.content
            assert json.loads(receipt["metadata_json"]) == event.metadata
            observed.append(receipt)
        return await original(execution, event)

    monkeypatch.setattr(host.runtime, "_publish_live_event", before_live)
    _, turn = await host.submit("sqrt(x)=x")
    assert observed
    _, body, metadata, parent = assistant_row(host, turn["id"])
    trace = metadata["accepted_output"]["math_publication"]
    assert trace["selected_contextual_clarifications"][0]["contract"] == CONTEXTUAL_VERSION
    assert trace["selected_grants"] == [] and "selected_feedback" not in trace
    assert 'You wrote: "sqrt(x)=x"' in body and "has not concluded" in body
    assert parent == host.math_contexts[-1].runtime.accepted_user_message_id
    assert completions[-1].agent_output == body
    before = host.state()
    monkeypatch.setattr(MathToolRegistry, "call", lambda *a, **k: pytest.fail("replay ran tool"))
    monkeypatch.setattr(
        "deeptutor.services.llm.factory._complete_with_resolved_config",
        lambda *a, **k: pytest.fail("replay called provider"),
    )
    first, second = await replay(host, turn), await replay(host, turn)
    assert first == second and host.state() == before
    assert "".join(e["content"] for e in first if e["type"] == "content") == body
    result = next(e["metadata"] for e in first if e["type"] == "result")
    assert result["math_publication"] == trace and result["response"] == body
