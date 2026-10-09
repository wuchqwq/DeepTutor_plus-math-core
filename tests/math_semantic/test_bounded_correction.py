"""Actual typed evidence for one explicit-premise relation and exact publication."""

from dataclasses import replace
import hashlib
import json
import re

import pytest

from deeptutor.capabilities.math_turn.output import accept_response, publication_input
from deeptutor.math_semantic.accepted import AcceptedSubmission, EpisodeIdentity
from deeptutor.math_semantic.authority import MathSemanticGrant
from deeptutor.math_semantic.contracts import (
    MathArtifact,
    MathWorkspace,
    ProblemFact,
    ProblemModel,
    SolutionPath,
)
from deeptutor.math_semantic.correction import CORRECTION_MECHANISM, materialize_correction_support
from deeptutor.math_semantic.proposals import AlignmentProposal
from deeptutor.math_semantic.refs import LearnerRef, QuestionRef, SourceRef
from deeptutor.math_semantic.state import MathMutation, ReviewedSource
from deeptutor.math_semantic.support import resolve_math_content_support
from deeptutor.math_semantic.workspace import MathWorkspaceSnapshot, append_snapshot


def make_state(
    given="x^2+x*y+y^2=3",
    definition="Q=x^2-x*y+y^2",
    claim="Q=3+2*x*y",
    *,
    domain=None,
    target=None,
    objective=(),
    raw_content=None,
    model_updates=None,
):
    ref = SourceRef("question", "generic-residual")
    if domain is None:
        names = sorted(
            set(
                re.findall(
                    r"[A-Za-z][A-Za-z0-9_]*", given.split("=")[0] + " " + definition.split("=")[1]
                )
            )
        )
        domain = ",".join(names) + " are real"
    domain_facts = (ProblemFact(domain, provenance=(ref,)),) if isinstance(domain, str) else domain
    model = ProblemModel(
        ref.identifier,
        ref,
        givens=(ProblemFact(given, provenance=(ref,)),),
        target=ProblemFact(target or "range of " + definition, provenance=(ref,)),
        domain=domain_facts,
        objective=tuple(ProblemFact(value, provenance=(ref,)) for value in objective),
    )
    if model_updates:
        model = replace(model, **model_updates)
    premise = MathArtifact(
        given,
        "given",
        provenance=(ref,),
        verification_status="qualified",
        verification_scope="reviewed relative premise",
    )
    answer = MathArtifact(
        "range unknown",
        "answer",
        provenance=(ref,),
        verification_status="qualified",
        verification_scope="reviewed only",
    )
    path = SolutionPath(
        "algebraic transformation", (premise.artifact_id, answer.artifact_id), provenance=(ref,)
    )
    snapshot = MathWorkspaceSnapshot(
        MathWorkspace(
            "generic-episode",
            model.model_ref,
            artifact_refs=(premise.artifact_id, answer.artifact_id),
            solution_path_refs=(path.path_id,),
        ),
        model,
        (premise, answer),
        paths=(path,),
    )
    source = ReviewedSource(
        EpisodeIdentity(
            "generic-episode", LearnerRef("test", "learner"), QuestionRef(ref.identifier, 1)
        ),
        snapshot,
    )
    raw_content = raw_content or claim
    submission = AcceptedSubmission(1, raw_content, "generic-session", "generic-turn")
    state = MathMutation(source, submission, (submission,))
    state.align(
        AlignmentProposal.from_value(
            {
                "claims": [
                    {
                        "evidence": {"quote": claim, "occurrence": raw_content.count(claim) - 1},
                        "claim_type": "equation",
                    }
                ]
            }
        ),
        expected_revision=1,
        provider_id="test-native",
        config_digest="test-config",
    )
    return state


def context(state):
    return dict(
        submission=state.submission,
        alignment=state.current_alignment(),
        episode_id=state.source.identity.episode_id,
    )


def bindings(state, snapshot=None, refs=None, **overrides):
    scope = {**context(state), **overrides}
    return [
        b
        for b in resolve_math_content_support(
            snapshot or state.snapshot(),
            refs or state.trajectory().applicable_artifact_refs,
            **scope,
        )
        if b.support_mechanism == CORRECTION_MECHANISM
    ]


@pytest.fixture(scope="module")
def supported():
    state = make_state()
    before = state.snapshot()
    artifacts, evidence = materialize_correction_support(
        before,
        state.trajectory().applicable_artifact_refs,
        **context(state),
    )
    assert len(evidence) == 5 and all(e.status == "succeeded" for e in evidence)
    state.append(
        expected_revision=before.workspace.revision, artifacts=artifacts, evidence=evidence
    )
    return state


def test_exact_conditional_relation_does_not_upgrade_claim_or_premises(supported):
    state = supported
    found = bindings(state)
    assert len(found) == 1 and found[0].act_kind == "justification"
    state.authorize(state.trajectory().applicable_artifact_refs, (found[0].as_grant(),))
    correction = next(
        a for a in state.snapshot().artifacts if a.claim_kind == "conditional_correction"
    )
    outputs = json.loads(correction.statement)["outputs"]
    assert outputs == ["-2*x*y", "-2*x*y + 3", "x**2 + x*y + y**2 - 3", "True", "4*x*y"]
    assert state.snapshot().artifacts[0].verification_status == "qualified"
    assert not any(a.verification_status == "verified" for a in state.snapshot().artifacts)
    assert not state.current_alignment().matched_artifact_refs
    assert not any(r.relation_type == "equivalent_to" for r in state.current_alignment().relations)


def test_non_question_specific_variables_constants_and_matching_claim():
    state = make_state("a^2+3*a*b+b^2=7", "Z=a^2-a*b+b^2", "Z=7+4*a*b")
    before = state.snapshot()
    artifacts, evidence = materialize_correction_support(
        before,
        state.trajectory().applicable_artifact_refs,
        **context(state),
    )
    assert len(artifacts) == 2
    state.append(expected_revision=1, artifacts=artifacts, evidence=evidence)
    correction = json.loads(artifacts[-1].statement)
    assert correction["outputs"][1] == "-4*a*b + 7"
    assert correction["outputs"][4] == "8*a*b"
    assert len(bindings(state)) == 1
    correct = make_state(claim="Q=3-2*x*y")
    artifacts, evidence = materialize_correction_support(
        correct.snapshot(),
        correct.trajectory().applicable_artifact_refs,
        **context(correct),
    )
    assert artifacts == () and evidence[-1].output_summary == "0"


@pytest.mark.parametrize("constant", ["nan", "oo", "zoo"])
@pytest.mark.parametrize("position", ["claim", "definition", "premise"])
def test_nonfinite_input_is_admitted_but_cannot_supply_correction(constant, position):
    given, definition, claim = "x+y=2", "Z=x-y", "Z=2+2*y"
    if position == "claim":
        claim = f"Z={constant}"
    elif position == "definition":
        definition = f"Z=x-y+{constant}"
        given = f"x+y+0*{constant}=2"
    else:
        given = f"x+y+{constant}=2"
        definition = f"Z=x-y+{constant}^0"
    state = make_state(given, definition, claim)
    assert state.current_alignment().claims[0].parse_status == "parsed"
    before = state.snapshot()
    refs = state.trajectory().applicable_artifact_refs
    artifacts, evidence = materialize_correction_support(before, refs, **context(state))
    assert artifacts == ()
    assert len(evidence) == 1 and evidence[0].status == "invalid_input"
    state.append(expected_revision=before.workspace.revision, evidence=evidence)
    assert bindings(state) == []
    assert not any(a.claim_kind == "conditional_correction" for a in state.snapshot().artifacts)
    state.authorize(refs, ())
    offers = publication_input(
        state,
        {"authority": [], "trajectory": state.trajectory().to_dict(), "verified_grounded_refs": []},
    )["offers"]
    assert not any(o["grant"]["act_kind"] == "justification" for o in offers)


def test_literal_rational_premise_requires_a_finite_coefficient():
    state = make_state("x+y=1/0", "Z=x-y", "Z=2+2*y")
    artifacts, evidence = materialize_correction_support(
        state.snapshot(), state.trajectory().applicable_artifact_refs, **context(state)
    )
    assert artifacts == () and len(evidence) == 1
    assert evidence[0].status == "invalid_input"


@pytest.mark.parametrize("rhs", ["oo^0", "zoo^0", "pi-pi+2*y", "I-I+2*y"])
def test_cancellation_cannot_hide_input_outside_supported_domain(rhs):
    state = make_state("x+y=2", "Z=x-y", f"Z={rhs}")
    artifacts, evidence = materialize_correction_support(
        state.snapshot(), state.trajectory().applicable_artifact_refs, **context(state)
    )
    assert artifacts == ()
    assert evidence[-1].status == "invalid_input"


@pytest.mark.parametrize(
    "given,definition,claim,derived,difference",
    [
        ("x+y=2", "Z=x-y", "Z=2+2*y", "2 - 2*y", "4*y"),
        ("a+b=5/2", "W=a-b", "W=5+2*b", "5/2 - 2*b", "4*b + 5/2"),
        ("r+s=-7", "T=r-s", "T=-7+s^3", "-2*s - 7", "s**3 + 2*s"),
        ("u+v=0", "N=u-v", "N=1", "-2*v", "2*v + 1"),
        ("oo_1+nan_1=2", "Z=oo_1-nan_1", "Z=2+2*nan_1", "2 - 2*nan_1", "4*nan_1"),
    ],
)
def test_finite_polynomial_controls_retain_exact_correction(
    given, definition, claim, derived, difference
):
    state = make_state(given, definition, claim)
    artifacts, evidence = materialize_correction_support(
        state.snapshot(), state.trajectory().applicable_artifact_refs, **context(state)
    )
    assert len(artifacts) == 2 and len(evidence) == 5
    assert all(e.status == "succeeded" for e in evidence)
    assert json.loads(artifacts[-1].statement)["outputs"][1::3] == [derived, difference]
    state.append(expected_revision=1, artifacts=artifacts, evidence=evidence)
    grant = bindings(state)[0].as_grant()
    state.authorize(state.trajectory().applicable_artifact_refs, (grant,))
    assert state.snapshot().artifacts[0].verification_status == "qualified"


@pytest.mark.parametrize("value", ["nan", "oo", "zoo"])
def test_worker_rejects_out_of_domain_results(monkeypatch, value):
    import sympy

    from deeptutor.math_semantic import tools

    monkeypatch.setattr(tools, "_expand_value", lambda **kwargs: getattr(sympy, value))
    with pytest.raises(ValueError, match="finite rational polynomial domain"):
        tools._run_operation(
            "expand", {"expression": "x+y", "expression_domain": tools.FINITE_POLYNOMIAL_DOMAIN}
        )


def test_evidence_without_the_exact_polynomial_domain_request_cannot_bind(supported):
    snapshot = supported.snapshot()
    snapshot = replace(
        snapshot,
        tool_evidence=tuple(
            replace(
                e,
                input_summary=e.input_summary.replace(
                    "; expression_domain=finite_rational_polynomial_v1", ""
                ),
            )
            for e in snapshot.tool_evidence
        ),
    )
    assert bindings(supported, snapshot) == []


@pytest.mark.parametrize(
    "domain",
    [
        (),
        "x,y are 2x2 real matrices",
        "x,y are noncommuting operators",
        "x,y are complex",
        "x are real",
    ],
)
def test_unconfirmed_scalar_domain_has_no_support_grant_or_accepted_correction(domain):
    state = make_state(domain=domain)
    refs = state.trajectory().applicable_artifact_refs
    artifacts, evidence = materialize_correction_support(state.snapshot(), refs, **context(state))
    assert artifacts == ()
    if evidence:
        assert evidence[-1].status == "invalid_input"
        state.append(expected_revision=1, evidence=evidence)
    assert bindings(state) == []
    calculation = {
        "authority": [MathSemanticGrant.orientation(ref).to_dict() for ref in refs],
        "trajectory": state.trajectory().to_dict(),
        "verified_grounded_refs": [],
    }
    inputs = publication_input(state, calculation)
    assert not any(o["grant"]["act_kind"] == "justification" for o in inputs["offers"])
    accepted = accept_response(
        state,
        calculation,
        inputs,
        json.dumps({"authority_basis": inputs["authority_basis"], "grant_ids": []}),
    )
    assert accepted.content == "Mathematical evidence recorded."
    assert json.loads(accepted.metadata_json)["math_publication"]["selected_grants"] == []


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "noncommuting",
        "inferred",
        "uncertain",
        "changed_real",
        "value_target",
        "extra_assumption",
    ],
)
def test_domain_and_disclosure_changes_invalidate_old_binding_and_offer(supported, change):
    snapshot = supported.snapshot()
    model = snapshot.problem_model
    fact = model.domain[0]
    updates = {
        "missing": {"domain": ()},
        "noncommuting": {"domain": (replace(fact, value="x,y are noncommuting operators"),)},
        "inferred": {"domain": (replace(fact, status="inferred"),)},
        "uncertain": {"domain": (replace(fact, uncertainty=0.25),)},
        "changed_real": {"domain": (replace(fact, value="x,y are real numbers"),)},
        "value_target": {"target": replace(model.target, value="Q=x^2-x*y+y^2")},
        "extra_assumption": {
            "assumptions": (replace(fact, value="unspecified multiplication semantics"),)
        },
    }[change]
    model = replace(model, **updates)
    fresh = make_state(domain=model.domain, target=model.target.value, model_updates=updates)
    # Replay old proofs/artifacts into a current source with changed interpretation.
    fresh.append(
        expected_revision=1, artifacts=snapshot.artifacts[2:], evidence=snapshot.tool_evidence
    )
    assert bindings(fresh) == []
    old_grant = bindings(supported)[0].as_grant()
    calculation = {
        "authority": [old_grant.to_dict()],
        "trajectory": fresh.trajectory().to_dict(),
        "verified_grounded_refs": [],
    }
    inputs = publication_input(fresh, calculation)
    assert inputs["offers"] == []
    with pytest.raises(ValueError, match="exceeds"):
        accept_response(
            fresh,
            calculation,
            inputs,
            json.dumps(
                {
                    "authority_basis": inputs["authority_basis"],
                    "grant_ids": [
                        hashlib.sha256(
                            json.dumps(
                                old_grant.to_dict(), sort_keys=True, separators=(",", ":")
                            ).encode()
                        ).hexdigest()
                    ],
                }
            ),
        )


@pytest.mark.parametrize("target", ["Z=x+y", "range of Z=x+y"])
def test_target_value_disclosure_is_ineligible_even_with_zero_result_grants(target):
    state = make_state(
        "x+y=2",
        "Z=x+y",
        "Z=0",
        target=target,
        objective=("Check with a small hint; do not reveal the final answer.",),
    )
    refs = state.trajectory().applicable_artifact_refs
    artifacts, evidence = materialize_correction_support(state.snapshot(), refs, **context(state))
    assert artifacts == ()
    if target.startswith("range"):
        assert len(evidence) == 2 and evidence[-1].status == "invalid_input"
        assert "complete target value" in evidence[-1].output_summary
        state.append(expected_revision=1, evidence=evidence)
    else:
        assert evidence == ()
    assert bindings(state) == []
    calculation = {
        "authority": [],
        "trajectory": state.trajectory().to_dict(),
        "verified_grounded_refs": [],
    }
    inputs = publication_input(state, calculation)
    assert inputs["offers"] == []
    accepted = accept_response(
        state,
        calculation,
        inputs,
        json.dumps({"authority_basis": inputs["authority_basis"], "grant_ids": []}),
    )
    assert accepted.content == "Mathematical evidence recorded."


def test_accepted_explicit_domain_override_cannot_borrow_scalar_source():
    state = make_state(raw_content="Domain: x,y are noncommuting operators\nQ=3+2*x*y")
    assert materialize_correction_support(
        state.snapshot(), state.trajectory().applicable_artifact_refs, **context(state)
    ) == ((), ())


def test_declared_real_commutativity_and_constant_claim_are_local_range_support():
    state = make_state(
        "x*y+x=2",
        "Z=y*x-x",
        "Z=0",
        domain="x,y,Z are real scalar variables.",
        raw_content="Domain: x,y,Z are real scalar variables.\nHint only.\nZ=0",
    )
    refs = state.trajectory().applicable_artifact_refs
    artifacts, evidence = materialize_correction_support(state.snapshot(), refs, **context(state))
    assert len(artifacts) == 2 and all(e.status == "succeeded" for e in evidence)
    state.append(expected_revision=1, artifacts=artifacts, evidence=evidence)
    grant = bindings(state)[0].as_grant()
    calculation = {
        "authority": [grant.to_dict()],
        "trajectory": state.trajectory().to_dict(),
        "verified_grounded_refs": [],
    }
    inputs = publication_input(state, calculation)
    accepted = accept_response(
        state,
        calculation,
        inputs,
        json.dumps(
            {
                "authority_basis": inputs["authority_basis"],
                "grant_ids": [inputs["offers"][0]["grant_id"]],
            }
        ),
    )
    assert "Z=2 - 2*x" in accepted.content
    assert "x,y,Z are real scalar variables." in accepted.content
    receipt = json.loads(accepted.metadata_json)["math_publication"]
    assert receipt["content_digest"] == hashlib.sha256(accepted.content.encode()).hexdigest()
    assert state.snapshot().artifacts[0].verification_status == "qualified"


@pytest.mark.parametrize(
    "change",
    [
        "revision",
        "workspace",
        "episode",
        "session",
        "turn",
        "claim",
        "accepted",
        "alignment",
        "premise",
        "missing",
        "definition",
        "failure",
        "wrong_input",
        "wrong_output",
        "content",
    ],
)
def test_stale_foreign_inapplicable_and_wrong_evidence_are_rejected(supported, change):
    state = supported
    snapshot = state.snapshot()
    overrides = {}
    refs = state.trajectory().applicable_artifact_refs
    if change == "revision":
        snapshot = replace(snapshot, workspace=replace(snapshot.workspace, revision=3))
    elif change == "workspace":
        snapshot = replace(snapshot, workspace=replace(snapshot.workspace, workspace_id="foreign"))
    elif change == "episode":
        overrides["episode_id"] = "foreign"
    elif change in {"session", "turn", "accepted"}:
        overrides["submission"] = replace(
            state.submission,
            **{
                "session": {"session_id": "foreign"},
                "turn": {"turn_id": "foreign"},
                "accepted": {"raw_content": "Q=999"},
            }[change],
        )
    elif change in {"claim", "alignment"}:
        alignment = state.current_alignment()
        overrides["alignment"] = (
            replace(alignment, alignment_id="foreign")
            if change == "alignment"
            else replace(alignment, claims=(replace(alignment.claims[0], normalized_form="Q=999"),))
        )
    elif change == "missing":
        refs = (snapshot.artifacts[1].artifact_id,)
    elif change in {"premise", "definition", "content"}:
        role = {"premise": "given", "definition": "definition", "content": "transformation"}[change]
        snapshot = replace(
            snapshot,
            artifacts=tuple(
                replace(a, statement="forged") if a.role == role else a for a in snapshot.artifacts
            ),
        )
    else:
        snapshot = replace(
            snapshot,
            tool_evidence=tuple(
                replace(
                    e,
                    **{
                        "failure": {"status": "failed", "failure_type": "failed"},
                        "wrong_input": {"input_refs": ("foreign",)},
                        "wrong_output": {"output_summary": "False"},
                    }[change],
                )
                for e in snapshot.tool_evidence
            ),
        )
    assert bindings(state, snapshot, refs, **overrides) == []


def test_failure_and_inapplicable_scope_create_no_correction(monkeypatch):
    from deeptutor.math_semantic.tools import MathToolRegistry

    state = make_state()
    snapshot = state.snapshot()
    assert materialize_correction_support(snapshot, (), **context(state)) == ((), ())
    monkeypatch.setattr(
        MathToolRegistry,
        "call",
        lambda self, operation, **kwargs: self._failure(
            operation, "failed", "failure", kwargs["input_refs"]
        ),
    )
    artifacts, evidence = materialize_correction_support(
        snapshot, state.trajectory().applicable_artifact_refs, **context(state)
    )
    assert artifacts == () and len(evidence) == 1 and evidence[0].status == "failed"


@pytest.mark.parametrize(
    "given,definition,claim",
    [
        ("a+b=2", "Z=a/b", "Z=2+a"),
        ("a+b=2", "Z=a^10000+b", "Z=2+a"),
        ("a+b=2", "Z=sin(a)+b", "Z=2+a"),
        ("a+b=k", "Z=a-b", "Z=k+2*b"),
        ("a+b=2", "Z=a-b", "W=2+2*b"),
    ],
)
def test_outside_small_explicit_relation_makes_no_tool_calls(monkeypatch, given, definition, claim):
    from deeptutor.math_semantic.tools import MathToolRegistry

    state = make_state(given, definition, claim)

    def unexpected(*args, **kwargs):
        raise AssertionError("inapplicable input must not run tools")

    monkeypatch.setattr(MathToolRegistry, "call", unexpected)
    assert materialize_correction_support(
        state.snapshot(),
        state.trajectory().applicable_artifact_refs,
        **context(state),
    ) == ((), ())


def test_cached_support_and_exact_publication_receipt(supported, monkeypatch):
    from deeptutor.math_semantic.tools import MathToolRegistry

    state = supported
    refs = state.trajectory().applicable_artifact_refs

    def unexpected(*args, **kwargs):
        raise AssertionError("same-head support should make no tool call")

    monkeypatch.setattr(MathToolRegistry, "call", unexpected)
    assert materialize_correction_support(state.snapshot(), refs, **context(state)) == ((), ())
    grant = bindings(state)[0].as_grant()
    calculation = {
        "authority": [grant.to_dict()],
        "trajectory": state.trajectory().to_dict(),
        "verified_grounded_refs": [],
    }
    inputs = publication_input(state, calculation)
    offer = inputs["offers"][0]
    assert "Q=-2*x*y + 3" in offer["text"] and "4*x*y=0" in offer["text"]
    assert "not identical expressions" in offer["text"]
    accepted = accept_response(
        state,
        calculation,
        inputs,
        json.dumps(
            {
                "authority_basis": inputs["authority_basis"],
                "grant_ids": [offer["grant_id"]],
            }
        ),
    )
    receipt = json.loads(accepted.metadata_json)["math_publication"]
    assert receipt["content_digest"] == hashlib.sha256(accepted.content.encode()).hexdigest()
    assert accepted.content.endswith(offer["text"])
    assert receipt["basis"]["session_id"] == state.submission.session_id
    assert receipt["basis"]["episode_id"] == state.source.identity.episode_id
    with pytest.raises(ValueError, match="exact pinned"):
        state.authorize(refs, (replace(grant, act_kind="result"),))
    with pytest.raises(ValueError, match="exact pinned"):
        state.authorize(refs, (replace(grant, content_digest="f" * 64),))
    with pytest.raises(ValueError, match="verified"):
        publication_input(
            state,
            {
                **calculation,
                "authority": [
                    MathSemanticGrant(
                        state.snapshot().artifacts[1].artifact_id,
                        "result",
                        SourceRef("math_artifact", state.snapshot().artifacts[1].artifact_id),
                        "f" * 64,
                        SourceRef("math_artifact", state.snapshot().artifacts[1].artifact_id),
                        "exact_artifact_content_v1",
                        "literal_result_for_same_target_not_truth_verification",
                    ).to_dict()
                ],
            },
        )
