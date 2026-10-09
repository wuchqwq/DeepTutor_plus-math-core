"""Finite feedback permissions under the existing publication owner and receipt."""

from dataclasses import replace
import hashlib
import json

import pytest

from deeptutor.capabilities.math_turn.feedback import CLARIFICATION, FEEDBACK_VERSION
from deeptutor.capabilities.math_turn.output import accept_response, publication_input
from deeptutor.math_semantic.contracts import MathArtifact
from deeptutor.math_semantic.proposals import AlignmentProposal
from deeptutor.math_semantic.tools import MathToolRegistry
from deeptutor.math_semantic.validation import STEP_VERSION

from .test_publication import assistant_row, replay
from .test_publication import publication_host_factory as _publication_host_factory
from .test_student_step_evidence import (
    FULL,
    TRUE,
    align,
    calculation,
    issue_task,
    source,
    state_for,
)

publication_host_factory = _publication_host_factory


@pytest.fixture
def initialized_host_imports():
    # First-use optional host imports can exceed the turn lease on Windows.
    # Initialize them before accepting a turn; keep all authority/timers intact.
    from deeptutor.runtime.registry.tool_registry import get_tool_registry
    from deeptutor.services.rag.pipelines.pageindex import validate_pageindex_oss_selection

    get_tool_registry()
    validate_pageindex_oss_selection([])


def prepare(text=TRUE, reviewed=None, *, proposal_fields=None):
    state = state_for(reviewed or source(), text)
    if proposal_fields is None:
        align(state, text)
    else:
        state.align(
            AlignmentProposal.from_value(
                {"claims": [{"evidence": {"quote": text}, **proposal_fields}]}
            ),
            expected_revision=1,
            provider_id="test-only-extraction",
            config_digest="offline",
            check_steps=True,
        )
    calc = calculation(state)
    return state, calc, publication_input(state, calc)


def offers(inputs, kind):
    return [o for o in inputs["offers"] if o["grant"]["act_kind"] == kind]


def candidate(inputs, chosen):
    return json.dumps(
        {"authority_basis": inputs["authority_basis"], "grant_ids": [o["grant_id"] for o in chosen]}
    )


@pytest.mark.parametrize("text,relation", [(TRUE, "IDENTITY"), (FULL, "CONDITIONAL")])
def test_confirmation_exact_current_binding_without_result_or_math_prose(
    text, relation, monkeypatch
):
    state, calc, inputs = prepare(text)
    chosen = offers(inputs, "local_confirmation")
    assert len(chosen) == 1
    grant = chosen[0]["grant"]
    assert grant["contract"] == FEEDBACK_VERSION and grant["local_relation"] == relation
    assert grant["accepted_user_message_id"] == state.submission.message_id
    assert grant["student_response_ref"]["identifier"] == state.submission.response_id
    assert grant["episode_id"] == state.source.identity.episode_id
    assert grant["math_revision"] == state.snapshot().workspace.revision
    assert grant["checked_revision"] == 1
    assert grant["claim_ref"] == inputs["private_teaching_context"]["pending_claims"][0]["claim_id"]
    assert grant["support_ref"] in state.snapshot().workspace.tool_evidence_refs
    before = state.serialize()
    monkeypatch.setattr(
        MathToolRegistry, "call", lambda *a, **k: pytest.fail("publication ran a tool")
    )
    accepted = accept_response(state, calc, inputs, candidate(inputs, chosen))
    trace = json.loads(accepted.metadata_json)["math_publication"]
    assert trace["selected_feedback"] == [grant] and trace["selected_grants"] == []
    assert (
        "complete answer" in accepted.content and "explicit real scalar domain" in accepted.content
    )
    assert ("explicit definitions" in accepted.content) == (relation == "CONDITIONAL")
    assert text not in accepted.content and text not in accepted.metadata_json
    assert "Q in [1,9]" not in accepted.content + accepted.metadata_json
    assert trace["content_digest"] == hashlib.sha256(accepted.content.encode()).hexdigest()
    assert state.serialize() == before and not calc["verified_grounded_refs"]


def test_pure_clarification_is_current_no_math_contract_without_history_authority():
    reviewed = source()
    first = state_for(reviewed, TRUE)
    align(first, TRUE)
    following = state_for(
        reviewed, "Which part next?", payload=first.serialize(), prefix=first.prefix
    )
    aligned = align(following, following.submission.raw_content, clarification=True)
    calc = calculation(following)
    inputs = publication_input(following, calc)
    assert aligned.claims == aligned.math_evidence == ()
    assert inputs["private_teaching_context"]["pending_claims"]
    assert not offers(inputs, "local_confirmation")
    chosen = offers(inputs, "neutral_clarification")
    accepted = accept_response(following, calc, inputs, candidate(inputs, chosen))
    assert accepted.content.endswith(CLARIFICATION)
    grant = json.loads(accepted.metadata_json)["math_publication"]["selected_feedback"][0]
    assert grant["accepted_user_message_id"] == following.submission.message_id
    assert grant["support_scope"] == "no_task_math_content" and "claim_ref" not in grant


@pytest.mark.parametrize(
    "reviewed,text,fields",
    [
        (source(domain=None), TRUE, None),
        (source(givens=("x^2+x*y+y^2=100",)), "(x-y)^2=x^2-x*y+y^2", None),
        (source(domain="x,y are matrices"), TRUE, None),
        (source(), TRUE, {"uncertainty": 0.7}),
        (source(), TRUE, {"parse_status": "ambiguous"}),
        (source(), TRUE, {"claim_type": "answer"}),
        (source(definitions=("Q=2",)), "Q=2", None),
        (source(definitions=("Q=2",)), "Q+0=2", None),
        (source(definitions=("Q=2",)), "(Q)-(2)=0", None),
        (source(), "(x-y)^2=x^2-x*y+y^2", None),
    ],
)
def test_unknown_uncertain_scalar_answer_and_counterexample_cannot_confirm(reviewed, text, fields):
    state, calc, inputs = prepare(text, reviewed, proposal_fields=fields)
    assert offers(inputs, "neutral_clarification") and not offers(inputs, "local_confirmation")
    accepted = accept_response(
        state, calc, inputs, candidate(inputs, offers(inputs, "neutral_clarification"))
    )
    assert accepted.content.endswith(CLARIFICATION)
    assert "algebraic identity" not in accepted.content


def test_timeout_only_keeps_clarification(monkeypatch):
    monkeypatch.setattr(
        MathToolRegistry,
        "call",
        lambda self, op, **k: self._failure(op, "timeout", "test deadline", k["input_refs"]),
    )
    state, _, inputs = prepare()
    evidence = next(e for e in state.snapshot().tool_evidence if e.tool_version == STEP_VERSION)
    assert json.loads(evidence.output_summary)["reason"] == "timeout"
    assert not offers(inputs, "local_confirmation") and offers(inputs, "neutral_clarification")


def test_authored_answer_cannot_be_disclosed_as_local_identity():
    reviewed = source()
    snapshot = reviewed.authored
    answer = MathArtifact(TRUE, "final_answer", provenance=snapshot.problem_model.provenance)
    reviewed = replace(
        reviewed,
        authored=replace(
            snapshot,
            artifacts=(*snapshot.artifacts, answer),
            workspace=replace(
                snapshot.workspace,
                artifact_refs=(*snapshot.workspace.artifact_refs, answer.artifact_id),
            ),
        ),
    )
    _, _, inputs = prepare(TRUE, reviewed)
    assert not offers(inputs, "local_confirmation")
    assert all(o["grant"]["act_kind"] != "result" for o in inputs["offers"])


@pytest.mark.parametrize(
    "change",
    ["revision", "foreign_episode", "foreign_source", "old_grant", "forged_grant", "mixed_grants"],
)
def test_stale_foreign_illegal_and_mixed_selection_rejected_whole(change):
    state, calc, inputs = prepare()
    chosen = offers(inputs, "local_confirmation")
    expected, raw = inputs, candidate(inputs, chosen)
    if change == "revision":
        state.append(expected_revision=state.snapshot().workspace.revision, status="changed_scope")
    elif change in {"foreign_episode", "foreign_source"}:
        reviewed = (
            source(episode="another-episode")
            if change == "foreign_episode"
            else source(givens=("x^2+x*y+y^2=4",))
        )
        state, calc, _ = prepare(reviewed=reviewed)
    else:
        fake = dict(chosen[0]["grant"])
        if change == "old_grant":
            fake["contract"] = "bounded_math_feedback_v0"
        else:
            fake["support_ref"] = "forged-evidence"
        illegal = hashlib.sha256(
            json.dumps(fake, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        ids = [chosen[0]["grant_id"], illegal] if change == "mixed_grants" else [illegal]
        raw = json.dumps({"authority_basis": inputs["authority_basis"], "grant_ids": ids})
    before = state.serialize()
    with pytest.raises(ValueError):
        accept_response(state, calc, expected, raw)
    assert state.serialize() == before


def test_same_math_in_new_accepted_turn_cannot_reuse_confirmation_grant():
    first, _, old = prepare()
    following = state_for(first.source, TRUE, payload=first.serialize(), prefix=first.prefix)
    align(following, TRUE)
    calc = calculation(following)
    current = publication_input(following, calc)
    with pytest.raises(ValueError, match="exceeds"):
        accept_response(
            following, calc, current, candidate(current, offers(old, "local_confirmation"))
        )


@pytest.mark.parametrize("tamper", ["envelope", "missing", "claim", "scope"])
def test_altered_or_stale_current_evidence_cannot_confirm(tamper):
    state, _, _ = prepare()
    records = json.loads(state.serialize())
    slot = next(iter(records["alignments"]))
    aligned = json.loads(records["alignments"][slot])
    if tamper == "envelope":
        aligned["math_evidence"][-1]["output_summary"] = "forged"
    elif tamper == "claim":
        aligned["claims"][0]["evidence"]["quote"] = "foreign"
    elif tamper == "missing":
        records["snapshots"]["2"]["tool_evidence"] = []
    else:
        state.append(expected_revision=2, status="changed_scope")
        inputs = publication_input(state, calculation(state))
        assert not offers(inputs, "local_confirmation")
        return
    records["alignments"][slot] = json.dumps(aligned)
    rebuilt = state_for(state.source, TRUE, payload=json.dumps(records))
    with pytest.raises(ValueError):
        publication_input(rebuilt, calculation(rebuilt))


@pytest.mark.parametrize(
    "domain,operation,text,scope",
    [
        ("a,b are real", "a*(b+1)=a*b+a", "a*(b+1)=a*b+a", "WHOLE_OPERATION"),
        ("m,n are real", "m*(n-2)=m*n-2*m", "m*(n-2)=m*n-2*m", "WHOLE_OPERATION"),
        (
            "a,b are real",
            "(a-b)^2+(a+b)^2=2*a^2+2*b^2",
            "(a-b)^2=a^2-2*a*b+b^2",
            "LOCAL_CONTRIBUTION",
        ),
    ],
)
def test_partial_whole_and_non_s4_never_become_completion(domain, operation, text, scope):
    reviewed = source(domain=domain, givens=(), definitions=(), operation=operation)
    first = state_for(reviewed, operation)
    payload, _, _ = issue_task(first, operation)
    following = state_for(reviewed, text, payload=payload, prefix=first.prefix)
    align(following, text)
    calc = calculation(following)
    inputs = publication_input(following, calc)
    context = inputs["private_teaching_context"]
    assert {o["scope"] for o in context["operation_correspondence"]} == {scope}
    assert all(
        o["stage_completion"] == "UNKNOWN" and o["mastery"] == "NO_INFERENCE"
        for o in context["operation_correspondence"]
    )
    accepted = accept_response(
        following, calc, inputs, candidate(inputs, offers(inputs, "local_confirmation"))
    )
    assert "only that submitted equality" in accepted.content
    assert "does not confirm" in accepted.content and "task completion" in accepted.content


def select_feedback(generation, monkeypatch, kind, *, invalid=False):
    async def complete(config, _provider_spec, *, prompt, **kwargs):
        inputs = json.loads(prompt)
        generation.calls.append({"inputs": inputs, "config": config, "kwargs": kwargs})
        if generation.hook:
            await generation.hook(inputs)
        chosen = offers(inputs, kind)
        assert chosen, inputs["private_teaching_context"]["step_evidence"]
        value = json.loads(candidate(inputs, chosen[:1]))
        if invalid:
            value["grant_ids"].append("f" * 64)
        raw = json.dumps(value)
        generation.raw_candidates.append(raw)
        return raw

    monkeypatch.setattr("deeptutor.services.llm.factory._complete_with_resolved_config", complete)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,text",
    [("neutral_clarification", "Which part next?"), ("local_confirmation", "a*(b+1)=a*b+a")],
)
async def test_feedback_acceptance_precedes_live_persist_and_replay(
    publication_host_factory, initialized_host_imports, monkeypatch, kind, text
):
    host, generation, completions = publication_host_factory()
    host.source = source(
        domain="a,b are real", givens=(), definitions=(), operation="a*(b+1)=a*b+a"
    )
    host.scope = host.math_scope()
    select_feedback(generation, monkeypatch, kind)
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
    _, turn = await host.submit(text)
    assert observed and host.completed == [turn["id"]]
    _, stored, metadata, parent = assistant_row(host, turn["id"])
    trace = metadata["accepted_output"]["math_publication"]
    assert trace["selected_feedback"][0]["act_kind"] == kind
    assert parent == host.math_contexts[-1].runtime.accepted_user_message_id
    assert completions[-1].agent_output == stored
    before = host.state()
    monkeypatch.setattr(MathToolRegistry, "call", lambda *a, **k: pytest.fail("replay ran tool"))
    monkeypatch.setattr(
        "deeptutor.services.llm.factory._complete_with_resolved_config",
        lambda *a, **k: pytest.fail("replay called provider"),
    )
    first, second = await replay(host, turn), await replay(host, turn)
    assert first == second and host.state() == before
    assert "".join(e["content"] for e in first if e["type"] == "content") == stored
    result = next(e["metadata"] for e in first if e["type"] == "result")
    assert result["response"] == stored and result["math_publication"] == trace
    assert len(generation.calls) == 1


@pytest.mark.asyncio
async def test_mixed_illegal_feedback_blocks_all_publication(
    publication_host_factory, initialized_host_imports, monkeypatch
):
    host, generation, completions = publication_host_factory()
    host.source = source(
        domain="a,b are real", givens=(), definitions=(), operation="a*(b+1)=a*b+a"
    )
    host.scope = host.math_scope()
    select_feedback(generation, monkeypatch, "local_confirmation", invalid=True)
    _, turn = await host.start("a*(b+1)=a*b+a")
    await host.finish(turn, status="failed")
    assert host.errors and not host.completed
    events = await replay(host, turn)
    assert not any(e["type"] in {"content", "result"} for e in events)
    assert not host.state().get("host_math_publications")
    assert all(not e.agent_output for e in completions)
