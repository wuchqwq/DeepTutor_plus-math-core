"""Finite point feedback: genuine checker receipts, no forced math relations."""

from dataclasses import asdict, replace
import hashlib
import json

import pytest

from deeptutor.capabilities.math_turn.counterexample_feedback import (
    COUNTEREXAMPLE_VERSION,
    _counterexample_point,
)
from deeptutor.capabilities.math_turn.output import accept_response, publication_input
from deeptutor.math_semantic.contracts import MathArtifact, ProblemFact
from deeptutor.math_semantic.support import materialize_operation_support
from deeptutor.math_semantic.tools import MathToolRegistry
from deeptutor.math_semantic.validation import STEP_VERSION

from .test_bounded_feedback import (
    candidate,
    offers,
    prepare,
    select_feedback,
)
from .test_bounded_feedback import initialized_host_imports as _initialized_host_imports
from .test_publication import assistant_row, replay
from .test_publication import publication_host_factory as _publication_host_factory
from .test_student_step_evidence import FALSE, align, calculation, source, state_for

publication_host_factory = _publication_host_factory
initialized_host_imports = _initialized_host_imports


def generic():
    return source(domain="a,b are real", givens=(), definitions=(), operation="a*(b+1)=a*b+a")


@pytest.fixture(scope="module")
def genuine_states():
    return {
        "non_s4": prepare("a*(b+1)=a*b", generic()),
        "other_structure": prepare(
            "(m-n)^2=m^2+n^2",
            source(domain="m,n are real", givens=(), definitions=(), operation="(m-n)^2"),
        ),
        "constrained": prepare(FALSE, source()),
    }


def evidence(state):
    envelope = next(e for e in state.snapshot().tool_evidence if e.tool_version == STEP_VERSION)
    binding, checked = json.loads(envelope.input_summary), json.loads(envelope.output_summary)
    by_id = {e.evidence_id: e for e in state.snapshot().tool_evidence}
    return envelope, binding, checked, [by_id[ref] for ref in checked["tool_evidence_refs"]]


@pytest.mark.parametrize("case", ["non_s4", "other_structure", "constrained"])
def test_genuine_exact_point_and_all_premises_without_result_or_diagnosis(
    case, genuine_states, monkeypatch
):
    state, calc, inputs = genuine_states[case]
    envelope, binding, checked, _ = evidence(state)
    assert checked["local_relation"] == "COUNTEREXAMPLE"
    assert checked["reason"] == "all_constraints_exactly_checked"
    chosen = offers(inputs, "local_counterexample")
    assert len(chosen) == 1 and not offers(inputs, "local_confirmation")
    grant = chosen[0]["grant"]
    assert grant["contract"] == COUNTEREXAMPLE_VERSION
    assert (
        grant["claim_digest"]
        == hashlib.sha256(
            json.dumps(
                binding["claim"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
    )
    assert grant["support_ref"] == envelope.evidence_id
    assert grant["checked_revision"] == binding["revision"] == 1
    assert grant["accepted_user_message_id"] == state.submission.message_id
    assert grant["episode_id"] == state.source.identity.episode_id
    assert grant["math_revision"] == state.snapshot().workspace.revision
    assert set(grant["witness"]) <= {"a", "b", "m", "n", "x", "y"}
    assert "Q" not in grant["witness"] and "Q=1" not in chosen[0]["text"]
    before = state.serialize()
    monkeypatch.setattr(MathToolRegistry, "call", lambda *a, **k: pytest.fail("publication tool"))
    accepted = accept_response(state, calc, inputs, candidate(inputs, chosen))
    trace = json.loads(accepted.metadata_json)["math_publication"]
    assert trace["selected_feedback"] == [grant] and trace["selected_grants"] == []
    assert "two sides of submitted equality 1 are unequal" in accepted.content
    assert "all explicit applicable premises" in accepted.content
    assert state.submission.raw_content not in accepted.content
    assert "Q in [1,9]" not in accepted.content + accepted.metadata_json
    assert trace["content_digest"] == hashlib.sha256(accepted.content.encode()).hexdigest()
    assert state.serialize() == before


@pytest.mark.parametrize("missing", ["definition", "premise", "residual"])
def test_each_missing_applicable_receipt_denies_projection(missing, genuine_states):
    state, _, _ = genuine_states["constrained"]
    _, binding, checked, receipts = evidence(state)
    if missing == "definition":
        excluded = next(e for e in receipts if "expression=(Q)-" in e.input_summary)
    elif missing == "premise":
        excluded = next(
            e for e in receipts if e.tool_name == "substitute" and "(3)" in e.input_summary
        )
    else:
        excluded = receipts[-1]
    remaining = [e for e in receipts if e.evidence_id != excluded.evidence_id]
    assert _counterexample_point(state.snapshot(), binding, checked, remaining) is None


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "missing_variable",
        "extra_variable",
        "bool",
        "different_point",
        "premises",
        "model",
        "failed_receipt",
    ],
)
def test_invalid_witness_or_scope_never_acquires_point_permission(change, genuine_states):
    state, _, _ = genuine_states["non_s4"]
    _, binding, checked, receipts = evidence(state)
    binding, checked = json.loads(json.dumps(binding)), json.loads(json.dumps(checked))
    if change == "none":
        checked["witness"] = None
    elif change == "missing_variable":
        checked["witness"].pop("b")
    elif change == "extra_variable":
        checked["witness"]["Z"] = 0
    elif change == "bool":
        checked["witness"]["a"] = True
    elif change == "different_point":
        checked["witness"]["a"] = 0
    elif change == "premises":
        binding["premises"] = [["a=1", "foreign"]]
    elif change == "model":
        binding["model"]["problem_id"] = "foreign"
    else:
        receipts = [replace(e, status="timeout") for e in receipts]
    assert _counterexample_point(state.snapshot(), binding, checked, receipts) is None


@pytest.mark.parametrize(
    "change",
    [
        "stale_revision",
        "old_turn",
        "foreign_episode",
        "foreign_source",
        "forged",
        "old_contract",
        "mixed",
    ],
)
def test_old_stale_foreign_and_illegal_grant_reject_entire_publication(change, genuine_states):
    original, _, old = genuine_states["non_s4"]
    state = state_for(
        original.source, original.submission.raw_content, payload=original.serialize()
    )
    calc, inputs = calculation(state), old
    chosen = offers(old, "local_counterexample")
    raw = candidate(old, chosen)
    if change == "stale_revision":
        state.append(expected_revision=2, status="changed_scope")
    elif change == "old_turn":
        state = state_for(
            original.source, "Which part?", payload=original.serialize(), prefix=original.prefix
        )
        align(state, "Which part?", clarification=True)
        calc = calculation(state)
        inputs = publication_input(state, calc)
        assert not offers(inputs, "local_counterexample")
        raw = candidate(inputs, chosen)
    elif change in {"foreign_episode", "foreign_source"}:
        different = source(
            domain="a,b are real",
            definitions=(),
            givens=("a=1",) if change == "foreign_source" else (),
            episode="foreign"
            if change == "foreign_episode"
            else original.source.identity.episode_id,
        )
        with pytest.raises(ValueError):
            state_for(different, original.submission.raw_content, payload=original.serialize())
        return
    else:
        fake = dict(chosen[0]["grant"])
        if change == "old_contract":
            fake["contract"] = "bounded_math_feedback_v1"
        else:
            fake["witness"] = {"a": 1, "b": 1}
        identifier = hashlib.sha256(
            json.dumps(fake, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        ids = [chosen[0]["grant_id"], identifier] if change == "mixed" else [identifier]
        raw = json.dumps({"authority_basis": inputs["authority_basis"], "grant_ids": ids})
    before = state.serialize()
    with pytest.raises(ValueError):
        accept_response(state, calc, inputs, raw)
    assert state.serialize() == before


@pytest.mark.parametrize(
    "role", ["answer", "answer_candidate", "final_answer", "target", "objective"]
)
def test_existing_counterexample_cannot_disclose_answer_or_target_point(role, genuine_states):
    state, _, _ = genuine_states["non_s4"]
    _, binding, checked, receipts = evidence(state)
    snapshot = state.snapshot()
    assert checked["local_relation"] == "COUNTEREXAMPLE"
    if role in {"target", "objective"}:
        model = replace(
            snapshot.problem_model,
            **{
                role: ProblemFact("a=1", provenance=snapshot.problem_model.provenance)
                if role == "target"
                else (ProblemFact("Find a", provenance=snapshot.problem_model.provenance),)
            },
        )
        snapshot = replace(snapshot, problem_model=model)
    else:
        snapshot = replace(
            snapshot,
            artifacts=(
                *snapshot.artifacts,
                MathArtifact("a=-1", role, provenance=snapshot.problem_model.provenance),
            ),
        )
    snapshot = replace(
        snapshot,
        workspace=replace(
            snapshot.workspace,
            problem_model_ref=snapshot.problem_model.model_ref,
            artifact_refs=tuple(a.artifact_id for a in snapshot.artifacts),
        ),
    )
    # Keep the model binding current: denial must come from the disclosure
    # boundary, rather than an unrelated changed-model mismatch.
    binding["model"] = json.loads(json.dumps(asdict(snapshot.problem_model)))
    assert _counterexample_point(snapshot, binding, checked, receipts) is None


@pytest.mark.parametrize("role", ["answer", "target", "objective"])
def test_real_counterexample_with_result_resource_still_has_no_witness_offer(role):
    reviewed = generic()
    snapshot = reviewed.authored
    fact = ProblemFact("a=1", provenance=snapshot.problem_model.provenance)
    if role == "answer":
        snapshot = replace(
            snapshot,
            artifacts=(
                *snapshot.artifacts,
                MathArtifact("a=-1", role, provenance=snapshot.problem_model.provenance),
            ),
        )
    else:
        snapshot = replace(
            snapshot,
            problem_model=replace(
                snapshot.problem_model, **{role: fact if role == "target" else (fact,)}
            ),
        )
    snapshot = replace(
        snapshot,
        workspace=replace(
            snapshot.workspace,
            problem_model_ref=snapshot.problem_model.model_ref,
            artifact_refs=tuple(a.artifact_id for a in snapshot.artifacts),
        ),
    )
    state, _, inputs = prepare("a*(b+1)=a*b", replace(reviewed, authored=snapshot))
    assert evidence(state)[2]["local_relation"] == "COUNTEREXAMPLE"
    assert not offers(inputs, "local_counterexample")
    assert offers(inputs, "neutral_clarification")


def test_point_feedback_composes_with_independently_authorized_operation(
    genuine_states, monkeypatch
):
    original, _, _ = genuine_states["non_s4"]
    state = state_for(
        original.source,
        original.submission.raw_content,
        payload=original.serialize(),
    )
    operations, receipts = materialize_operation_support(
        state.snapshot(), state.trajectory().applicable_artifact_refs
    )
    state.append(expected_revision=2, artifacts=operations, evidence=receipts)
    calc = calculation(state)
    inputs = publication_input(state, calc)
    feedback = offers(inputs, "local_counterexample")
    selected = [feedback[0], offers(inputs, "chosen_operation")[0]]
    before = state.serialize()
    monkeypatch.setattr(MathToolRegistry, "call", lambda *a, **k: pytest.fail("acceptance tool"))
    accepted = accept_response(state, calc, inputs, candidate(inputs, selected))
    trace = json.loads(accepted.metadata_json)["math_publication"]
    assert trace["selected_feedback"] == [feedback[0]["grant"]]
    assert len(trace["selected_grants"]) == 1
    assert trace["selected_grants"][0]["act_kind"] == "chosen_operation"
    assert all(o["text"] in accepted.content for o in selected)
    assert state.serialize() == before


@pytest.mark.parametrize("receipt_kind", ["definition", "premise", "residual"])
def test_unproved_definition_premise_or_unequal_residual_denies_feedback(
    receipt_kind, genuine_states
):
    state, _, _ = genuine_states["constrained"]
    _, binding, checked, receipts = evidence(state)
    if receipt_kind == "definition":
        chosen = next(e for e in receipts if "expression=(Q)-" in e.input_summary)
    elif receipt_kind == "premise":
        chosen = next(
            e for e in receipts if e.tool_name == "substitute" and "(3)" in e.input_summary
        )
    else:
        chosen = receipts[-1]
    corrupt = replace(chosen, output_summary="0" if receipt_kind == "residual" else "1")
    receipts = [corrupt if e.evidence_id == chosen.evidence_id else e for e in receipts]
    assert _counterexample_point(state.snapshot(), binding, checked, receipts) is None


@pytest.mark.parametrize(
    "text,fields,givens",
    [
        ("a/(b-b)=1", None, ()),
        (
            "a*(b+1)=a*b",
            {"claim_type": "equation", "parse_status": "parsed", "uncertainty": 0.7},
            (),
        ),
        ("a*(b+1)=a*b", None, ("a=4",)),
    ],
)
def test_unknown_uncertain_and_finite_no_witness_leave_existing_clarification(text, fields, givens):
    reviewed = source(
        domain="a,b are real", givens=givens, definitions=(), operation="a*(b+1)=a*b+a"
    )
    _, _, inputs = prepare(text, reviewed, proposal_fields=fields)
    assert not offers(inputs, "local_counterexample")
    assert offers(inputs, "neutral_clarification")


def test_timeout_creates_no_counterexample_feedback(monkeypatch):
    monkeypatch.setattr(
        MathToolRegistry,
        "call",
        lambda self, op, **k: self._failure(
            op, "timeout", "test deadline", k.get("input_refs", ())
        ),
    )
    state, _, inputs = prepare("a*(b+1)=a*b", generic())
    assert evidence(state)[2]["local_relation"] == "UNKNOWN"
    assert not offers(inputs, "local_counterexample")


@pytest.mark.asyncio
@pytest.mark.parametrize("mixed_illegal", [False, True])
async def test_native_acceptance_live_persist_and_replay_or_whole_rejection(
    publication_host_factory, initialized_host_imports, monkeypatch, mixed_illegal
):
    host, generation, _ = publication_host_factory()
    host.source, host.scope = generic(), None
    host.scope = host.math_scope()
    select_feedback(generation, monkeypatch, "local_counterexample", invalid=mixed_illegal)
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
    _, turn = await host.start("a*(b+1)=a*b")
    await host.finish(turn, status="failed" if mixed_illegal else "completed")
    if mixed_illegal:
        assert not observed and not host.completed
        assert not host.state().get("host_math_publications")
        return
    _, body, metadata, parent = assistant_row(host, turn["id"])
    assert observed and host.completed == [turn["id"]]
    trace = metadata["accepted_output"]["math_publication"]
    assert trace["selected_feedback"][0]["contract"] == COUNTEREXAMPLE_VERSION
    assert parent == host.math_contexts[-1].runtime.accepted_user_message_id
    assert "two sides" in body and trace["selected_grants"] == []
    before = host.state()
    monkeypatch.setattr(MathToolRegistry, "call", lambda *a, **k: pytest.fail("replay math"))
    monkeypatch.setattr(
        "deeptutor.services.llm.factory._complete_with_resolved_config",
        lambda *a, **k: pytest.fail("replay provider"),
    )
    first, second = await replay(host, turn), await replay(host, turn)
    assert first == second and host.state() == before
    assert "".join(e["content"] for e in first if e["type"] == "content") == body
    assert next(e["metadata"]["math_publication"] for e in first if e["type"] == "result") == trace
