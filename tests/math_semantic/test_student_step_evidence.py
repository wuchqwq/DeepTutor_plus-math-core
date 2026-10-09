"""Grounded steps, finite witness checks, persistence and private host consumption."""

from dataclasses import asdict, replace
import json
import time

import pytest

from deeptutor.capabilities.math_turn.output import (
    _operation_correspondence,
    _teaching_context,
    accept_response,
    publication_input,
)
from deeptutor.math_semantic.accepted import AcceptedSubmission, EpisodeIdentity
from deeptutor.math_semantic.alignment import materialize_alignment
from deeptutor.math_semantic.authority import MathSemanticGrant
from deeptutor.math_semantic.codec import _decode, _payload
from deeptutor.math_semantic.contracts import (
    MathArtifact,
    MathWorkspace,
    ProblemFact,
    ProblemModel,
    SolutionPath,
)
from deeptutor.math_semantic.proposals import AlignmentProposal
from deeptutor.math_semantic.refs import LearnerRef, QuestionRef, SourceRef
from deeptutor.math_semantic.state import MathMutation, ReviewedSource
from deeptutor.math_semantic.support import (
    materialize_operation_support,
    resolve_math_content_support,
)
from deeptutor.math_semantic.tools import MathToolRegistry
from deeptutor.math_semantic.validation import STEP_VERSION, check_student_step
from deeptutor.math_semantic.workspace import MathWorkspaceSnapshot, RevisionConflict

from .test_publication import (
    assistant_row,
    replay,
)
from .test_publication import (
    publication_host_factory as _publication_host_factory,
)

publication_host_factory = _publication_host_factory

TRUE = "(x-y)^2=x^2-2*x*y+y^2"
FALSE = "(x-y)^2=x^2-x*y+y^2"
FULL = "(3*Q-(x^2+x*y+y^2))-2*(x-y)^2=0"


def source(
    *,
    domain="x,y are real",
    givens=("x^2+x*y+y^2=3",),
    definitions=("Q=x^2-x*y+y^2",),
    operation=FULL,
    episode="step-episode",
):
    ref = SourceRef("question", "generic-step-question")

    def fact(text):
        return ProblemFact(text, provenance=(ref,))

    model = ProblemModel(
        ref.identifier,
        ref,
        domain=(fact(domain),) if domain else (),
        givens=tuple(fact(text) for text in givens),
    )
    artifacts = tuple(
        MathArtifact(
            text,
            "definition",
            provenance=(ref,),
            verification_status="qualified",
            verification_scope="explicit premise",
        )
        for text in definitions
    )
    artifacts += (
        MathArtifact(
            operation,
            "intermediate",
            provenance=(ref,),
            verification_status="qualified",
            verification_scope="reviewed operation input",
        ),
    )
    path = SolutionPath(
        "reviewed polynomial work",
        artifact_refs=tuple(a.artifact_id for a in artifacts),
        provenance=(ref,),
    )
    snapshot = MathWorkspaceSnapshot(
        MathWorkspace(
            episode,
            model.model_ref,
            artifact_refs=path.artifact_refs,
            solution_path_refs=(path.path_id,),
        ),
        model,
        artifacts,
        paths=(path,),
    )
    return ReviewedSource(
        EpisodeIdentity(
            episode, LearnerRef("test-space", "student"), QuestionRef(model.problem_id, 1)
        ),
        snapshot,
    )


def proposal(text, *, clarification=False):
    return AlignmentProposal.from_value(
        {
            "claims": []
            if clarification
            else [
                {"evidence": {"quote": text}, "claim_type": "equation", "parse_status": "parsed"}
            ],
            "interaction_type": "clarification" if clarification else "answer",
        }
    )


def check(text, reviewed=None):
    reviewed = reviewed or source()
    response = AcceptedSubmission(1, text, "step-session", "step-turn-1")
    result = materialize_alignment(
        response,
        reviewed.authored,
        proposal(text),
        provider_id="proposal-only",
        config_digest="offline",
        check_steps=True,
    )
    envelope = next(e for e in result.evidence if e.tool_version == STEP_VERSION)
    return result, json.loads(envelope.output_summary), envelope


@pytest.mark.parametrize(
    "text,relation", [(TRUE, "IDENTITY"), (FALSE, "COUNTEREXAMPLE"), (FULL, "CONDITIONAL")]
)
def test_grounded_local_relations_without_novel_path_or_truth_admission(text, relation):
    checked, verdict, envelope = check(text)
    assert verdict["local_relation"] == relation
    assert checked.artifacts == checked.paths == ()
    assert checked.alignment.validated_artifact_refs == ()
    assert not checked.alignment.novel_candidates
    # New evidence is private, independent of old authored correspondence.
    baseline = materialize_alignment(
        AcceptedSubmission(1, text, "step-session", "step-turn-1"),
        source().authored,
        proposal(text),
        provider_id="proposal-only",
        config_digest="offline",
    )
    assert checked.alignment.matched_artifact_refs == baseline.alignment.matched_artifact_refs
    assert (
        checked.alignment.contradicted_artifact_refs
        == baseline.alignment.contradicted_artifact_refs
    )
    binding = json.loads(envelope.input_summary)
    assert binding["claim"]["evidence"]["quote"] == text
    assert binding["episode"] == "step-episode" and binding["revision"] == 1
    assert binding["model"]["domain"][0]["value"] == "x,y are real"
    assert set(verdict["tool_evidence_refs"]) <= {e.evidence_id for e in checked.evidence}
    if relation == "COUNTEREXAMPLE":
        x, y = verdict["witness"]["x"], verdict["witness"]["y"]
        assert x * x + x * y + y * y == 3 and (x - y) ** 2 != x * x - x * y + y * y
        witness_checks = [e for e in checked.evidence if e.tool_name == "substitute"]
        assert len(witness_checks) >= 3  # definition + all constraints + nonzero residual
        assert all(e.input_refs == envelope.input_refs for e in checked.evidence)


@pytest.mark.parametrize(
    "reviewed,text,reason",
    [
        (source(definitions=()), FULL, "undefined_symbol"),
        (source(givens=("x^2+x*y+y^2=100",)), FALSE, "finite_search_no_witness"),
        (
            source(givens=("x and y obey an unspecified restriction",)),
            FALSE,
            "unsupported_constraint",
        ),
        (source(domain=None), TRUE, "real_scalar_domain_required"),
        (source(domain="x,y are matrices"), TRUE, "unsupported_domain"),
        (source(domain="x,y are noncommuting real operators"), TRUE, "unsupported_domain"),
        (
            source(domain="a,b are real", givens=("a+b=2",), definitions=("Z=a-b",)),
            "Z=2*a-2",
            "finite_search_no_witness",
        ),
        (source(givens=("x>0", "x<0")), FALSE, "finite_search_no_witness"),
        (source(givens=("sin(x)=0",)), TRUE, "unsupported_polynomial"),
        (source(definitions=("Q=Z", "Z=Q")), FULL, "cyclic_definition"),
        (source(), "__import__(1)=0", "expression contains a blocked identifier"),
    ],
)
def test_uncertain_relations_never_become_refutations(reviewed, text, reason):
    _, verdict, _ = check(text, reviewed)
    assert verdict["local_relation"] == "UNKNOWN" and verdict["reason"] == reason
    assert verdict["witness"] is None


@pytest.mark.parametrize(
    "field",
    [
        "model",
        "domain",
        "givens",
        "constraints",
        "assumptions",
        "target",
        "objective",
        "artifact_given",
        "artifact_definition",
    ],
)
def test_uncertain_scope_or_actual_premise_is_unknown_before_tools(field, monkeypatch):
    reviewed = source(
        domain="a,b are real", givens=("a=1",), definitions=(), operation="(a-b)^2=a^2-2*a*b+b^2"
    )
    model = reviewed.authored.problem_model
    artifacts = reviewed.authored.artifacts
    if field == "model":
        model = replace(model, uncertainty=0.7)
    elif field == "domain":
        model = replace(model, domain=(replace(model.domain[0], uncertainty=0.7),))
    elif field in {"givens", "constraints", "assumptions"}:
        model = replace(
            model, **{field: (ProblemFact("a=1", provenance=model.provenance, uncertainty=0.7),)}
        )
    elif field in {"target", "objective"}:
        fact = ProblemFact(
            "range of Z=a-b" if field == "target" else "Unrelated teaching objective",
            provenance=model.provenance,
            uncertainty=0.7,
        )
        model = replace(model, **{field: fact if field == "target" else (fact,)})
    else:
        artifacts += (
            MathArtifact(
                "b=1" if field == "artifact_given" else "Z=a-b",
                "given" if field == "artifact_given" else "definition",
                provenance=model.provenance,
                verification_status="qualified",
                verification_scope="explicit premise",
                uncertainty=0.7,
            ),
        )
    snapshot = replace(
        reviewed.authored,
        problem_model=model,
        artifacts=artifacts,
        workspace=replace(
            reviewed.authored.workspace,
            problem_model_ref=model.model_ref,
            artifact_refs=tuple(a.artifact_id for a in artifacts),
        ),
    )
    reviewed = replace(reviewed, authored=snapshot)

    def unexpected(*args, **kwargs):
        raise AssertionError("Uncertain scope must not be used for a positive check or witness")

    monkeypatch.setattr(MathToolRegistry, "call", unexpected)
    text = "(a-b)^2=a^2-2*a*b+b^2" if field in {"domain", "model", "objective"} else "a=0"
    checked, verdict, envelope = check(text, reviewed)
    assert verdict["local_relation"] == "UNKNOWN" and verdict["witness"] is None
    assert verdict["reason"] == (
        "uncertain_premise_artifact" if field.startswith("artifact_") else "uncertain_problem_scope"
    )
    assert envelope.status == "not_checkable" and len(checked.evidence) == 1
    assert checked.alignment.validated_artifact_refs == checked.artifacts == checked.paths == ()
    # The shared scope gate also rejects an old affirmative relation as evidence
    # of completing an operation under a currently uncertain premise scope.
    assert (
        _operation_correspondence(
            checked.alignment.claims[0],
            "IDENTITY",
            {"kind": "expand", "kwargs": {"expression": "(a-b)^2"}},
            snapshot,
        )
        == "UNKNOWN"
    )


def test_unrelated_intermediate_uncertainty_does_not_reject_step_scope():
    reviewed = source(domain="a,b are real", givens=(), definitions=())
    snapshot = reviewed.authored
    artifacts = tuple(replace(a, uncertainty=0.7) for a in snapshot.artifacts)
    reviewed = replace(
        reviewed,
        authored=replace(
            snapshot,
            artifacts=artifacts,
            workspace=replace(
                snapshot.workspace, artifact_refs=tuple(a.artifact_id for a in artifacts)
            ),
        ),
    )
    checked, verdict, _ = check("(a-b)^2=a^2-2*a*b+b^2", reviewed)
    assert verdict["local_relation"] == "IDENTITY"
    assert (
        _operation_correspondence(
            checked.alignment.claims[0],
            "IDENTITY",
            {"kind": "expand", "kwargs": {"expression": "(a-b)^2"}},
            reviewed.authored,
        )
        == "WHOLE_OPERATION"
    )


def test_zero_uncertainty_given_still_supports_exact_witness():
    reviewed = source(domain="a,b are real", givens=("a=1",), definitions=())
    _, verdict, envelope = check("a=0", reviewed)
    assert envelope.status == "succeeded" and verdict["local_relation"] == "COUNTEREXAMPLE"
    assert verdict["witness"]["a"] == 1


@pytest.mark.parametrize("letters", [("a", "b"), ("u", "v"), ("r", "t")])
def test_other_symbols_and_exact_constraint_witness(letters):
    a, b = letters
    reviewed = source(
        domain=f"{a},{b} are real", givens=(f"{a}^2+{a}*{b}+{b}^2=3",), definitions=()
    )
    assert check(f"({a}-{b})^2={a}^2-2*{a}*{b}+{b}^2", reviewed)[1]["local_relation"] == "IDENTITY"
    assert (
        check(f"({a}-{b})^2={a}^2-{a}*{b}+{b}^2", reviewed)[1]["local_relation"] == "COUNTEREXAMPLE"
    )


def test_bounded_implicit_products_and_host_arithmetic_resource_limit():
    assert check("(x-y)^2=x^2-2xy+y^2")[1]["local_relation"] == "IDENTITY"
    assert check("(x-y)^2=x^2-xy+y^2")[1]["local_relation"] == "COUNTEREXAMPLE"
    assert check("((((10000^8)^8)^8)^8)=0")[1]["reason"] == "polynomial_arithmetic_budget"
    assert (
        check("I^2=-1", source(domain="I are real", givens=(), definitions=()))[1]["local_relation"]
        == "UNKNOWN"
    )


def test_timeout_and_tool_failure_are_unknown_with_actual_receipts(monkeypatch):
    checked, _, _ = check(TRUE)
    claim = checked.alignment.claims[0]
    proofs = check_student_step(
        claim, source().authored, MathToolRegistry(), deadline=time.monotonic() - 1
    )
    assert proofs[0].status == "timeout"
    assert json.loads(proofs[-1].output_summary)["reason"] == "timeout"
    monkeypatch.setattr(
        MathToolRegistry,
        "call",
        lambda self, op, **kwargs: self._failure(
            op, "invalid_input", "test parse failure", kwargs["input_refs"]
        ),
    )
    assert check(TRUE)[1]["local_relation"] == "UNKNOWN"
    assert check(TRUE)[1]["reason"] == "invalid_input"


def state_for(reviewed, text, *, payload=None, prefix=()):
    submitted = AcceptedSubmission(
        len(prefix) + 1, text, "step-session", f"step-turn-{len(prefix) + 1}"
    )
    return MathMutation(reviewed, submitted, (*prefix, submitted), payload)


def align(state, text, *, clarification=False):
    return state.align(
        proposal(text, clarification=clarification),
        expected_revision=state.snapshot().workspace.revision,
        provider_id="proposal-only",
        config_digest="offline",
        check_steps=True,
    )


def test_evidence_only_revision_idempotent_replay_and_foreign_stale_rejection(monkeypatch):
    reviewed = source()
    state = state_for(reviewed, TRUE)
    alignment = align(state, TRUE)
    assert state.snapshot().workspace.revision == 2
    assert state.snapshot().artifacts == reviewed.authored.artifacts
    assert state.snapshot().paths == reviewed.authored.paths
    assert set(alignment.validation_evidence_refs) <= set(
        state.snapshot().workspace.tool_evidence_refs
    )
    before = state.serialize()
    monkeypatch.setattr(MathToolRegistry, "call", lambda *a, **kw: pytest.fail("replay reran tool"))
    assert (
        state.align(
            proposal(TRUE),
            expected_revision=1,
            provider_id="proposal-only",
            config_digest="offline",
            check_steps=True,
        )
        == alignment
    )
    assert state.serialize() == before
    with pytest.raises(ValueError, match="input changed"):
        state.align(
            proposal(FALSE),
            expected_revision=1,
            provider_id="proposal-only",
            config_digest="offline",
            check_steps=True,
        )
    other = state_for(reviewed, FALSE, payload=before, prefix=state.prefix)
    with pytest.raises(RevisionConflict):
        other.align(
            proposal(FALSE),
            expected_revision=1,
            provider_id="proposal-only",
            config_digest="offline",
            check_steps=True,
        )
    with pytest.raises(ValueError, match="episode binding changed"):
        state_for(source(episode="foreign"), TRUE, payload=before)
    with pytest.raises(ValueError, match="episode binding changed"):
        state_for(source(givens=("x^2+x*y+y^2=4",)), TRUE, payload=before)


@pytest.mark.parametrize(
    "tamper", ["envelope", "tool", "missing", "claim", "workspace", "revision"]
)
def test_altered_or_dangling_evidence_rejected_on_reconstruction(tamper):
    reviewed = source()
    state = state_for(reviewed, TRUE)
    aligned = align(state, TRUE)
    data = json.loads(state.serialize())
    slot = next(iter(data["alignments"]))
    value = json.loads(data["alignments"][slot])
    if tamper in {"envelope", "tool"}:
        index = -1 if tamper == "envelope" else 0
        value["math_evidence"][index]["output_summary"] = "forged output"
    elif tamper == "missing":
        data["snapshots"]["2"]["tool_evidence"] = []
    elif tamper == "claim":
        value["claims"][0]["evidence"]["quote"] = FALSE
    elif tamper == "workspace":
        value["math_workspace_ref"]["identifier"] = "foreign"
    else:
        value["workspace_revision"] = 2
    data["alignments"][slot] = json.dumps(value)
    rebuilt = state_for(reviewed, TRUE, payload=json.dumps(data))
    with pytest.raises(ValueError):
        rebuilt.trajectory()


def calculation(state):
    trajectory = state.trajectory()
    refs = trajectory.applicable_artifact_refs
    grants = tuple(MathSemanticGrant.orientation(ref) for ref in refs)
    grants += tuple(
        b.as_grant()
        for b in resolve_math_content_support(state.snapshot(), refs)
        if b.act_kind in {"chosen_operation", "operation_options"}
    )
    return {
        "authority": [g.to_dict() for g in grants],
        "trajectory": trajectory.to_dict(),
        "verified_grounded_refs": (),
    }


def issue_task(state, text):
    align(state, text)
    operations, evidence = materialize_operation_support(
        state.snapshot(), state.trajectory().applicable_artifact_refs
    )
    state.append(
        expected_revision=state.snapshot().workspace.revision,
        artifacts=operations,
        evidence=evidence,
    )
    calc = calculation(state)
    inputs = publication_input(state, calc)
    selected = next(
        o
        for o in inputs["offers"]
        if o["grant"]["act_kind"] == "chosen_operation"
        and json.loads(
            next(
                a.statement
                for a in state.snapshot().artifacts
                if a.artifact_id == o["grant"]["content_ref"]["identifier"]
            )
        )["kind"]
        == "expand"
    )
    accepted = accept_response(
        state,
        calc,
        inputs,
        json.dumps(
            {"authority_basis": inputs["authority_basis"], "grant_ids": [selected["grant_id"]]}
        ),
    )
    data = json.loads(state.serialize())
    data["host_math_publications"] = {state.submission.turn_id: asdict(accepted)}
    return json.dumps(data), inputs, accepted


def test_private_receipt_context_local_whole_clarification_and_no_new_grants():
    reviewed = source(definitions=("Q=x^2-x*y+y^2",))
    first = state_for(reviewed, FULL)
    payload, _, receipt = issue_task(first, FULL)
    second = state_for(reviewed, TRUE, payload=payload, prefix=first.prefix)
    align(second, TRUE)
    private = _teaching_context(second, calculation(second))
    assert private["previous_task"]["publication_id"] == receipt.publication_id
    assert {c["scope"] for c in private["operation_correspondence"]} == {"LOCAL_CONTRIBUTION"}
    assert all(
        c["stage_completion"] == "UNKNOWN" and c["mastery"] == "NO_INFERENCE"
        for c in private["operation_correspondence"]
    )
    # Exact whole residual equals zero, after using Q's explicit definition.
    whole = state_for(reviewed, FULL, payload=payload, prefix=first.prefix)
    aligned = align(whole, FULL)
    private_whole = _teaching_context(whole, calculation(whole))
    assert {c["scope"] for c in private_whole["operation_correspondence"]} == {"WHOLE_OPERATION"}
    clarify = state_for(
        reviewed,
        "Please explain the product term",
        payload=second.serialize(),
        prefix=second.prefix,
    )
    clarification = align(clarify, clarify.submission.raw_content, clarification=True)
    assert clarification.claims == () and clarification.math_evidence == ()
    carried = _teaching_context(clarify, calculation(clarify))
    assert carried["pending_claims"] == private["pending_claims"]
    assert carried["step_evidence"] == private["step_evidence"]
    assert carried["previous_task"] == private["previous_task"]
    wrong_path = calculation(clarify)
    wrong_path["trajectory"]["compatible_path_refs"] = ["foreign-path"]
    assert _teaching_context(clarify, wrong_path)["step_evidence"] == []
    foreign_receipt = json.loads(clarify.serialize())
    entry = next(iter(foreign_receipt["host_math_publications"].values()))
    metadata = json.loads(entry["metadata_json"])
    metadata["math_publication"]["basis"]["episode_id"] = "foreign-episode"
    entry["metadata_json"] = json.dumps(metadata)
    foreign = state_for(
        reviewed,
        clarify.submission.raw_content,
        payload=json.dumps(foreign_receipt),
        prefix=second.prefix,
    )
    with pytest.raises(ValueError, match="teaching receipt"):
        _teaching_context(foreign, calculation(foreign))
    # Scope changes make old private evidence unusable; no guessed carry.
    clarify.append(expected_revision=clarify.snapshot().workspace.revision, status="changed_scope")
    assert _teaching_context(clarify, calculation(clarify))["step_evidence"] == []
    assert aligned.validated_artifact_refs == ()
    assert not any(
        g["act_kind"] in {"result", "correctness", "justification"}
        for g in calculation(whole)["authority"]
    )


def test_non_s4_whole_sum_and_one_square_are_distinct():
    reviewed = source(
        domain="a,b are real", givens=(), definitions=(), operation="(a-b)^2+(a+b)^2=2*a^2+2*b^2"
    )
    local, verdict, _ = check("(a-b)^2=a^2-2*a*b+b^2", reviewed)
    request = {"kind": "expand", "kwargs": {"expression": "(a-b)^2+(a+b)^2"}}
    assert (
        _operation_correspondence(
            local.alignment.claims[0], verdict["local_relation"], request, reviewed.authored
        )
        == "LOCAL_CONTRIBUTION"
    )
    full, verdict, _ = check("(a-b)^2+(a+b)^2=2*a^2+2*b^2", reviewed)
    assert (
        _operation_correspondence(
            full.alignment.claims[0], verdict["local_relation"], request, reviewed.authored
        )
        == "WHOLE_OPERATION"
    )
    # Being an identity cannot complete a different operation with zero residual.
    request["kwargs"]["expression"] = "(a+b)^2-(a^2+2*a*b+b^2)"
    assert (
        _operation_correspondence(local.alignment.claims[0], "IDENTITY", request, reviewed.authored)
        == "UNKNOWN"
    )
    repeated, verdict, _ = check("(a-b)^2+(a+b)^2=(a-b)^2+(a+b)^2", reviewed)
    request["kwargs"]["expression"] = "(a-b)^2+(a+b)^2"
    assert (
        _operation_correspondence(
            repeated.alignment.claims[0], verdict["local_relation"], request, reviewed.authored
        )
        == "UNKNOWN"
    )


@pytest.mark.parametrize(
    "domain,operation,response,scope",
    [
        ("a,b are real", "a*(b+1)=a*b+a", "(a*(b+1))-(a*b+a)=0+((a*(b+1))-(a*b+a))", "UNKNOWN"),
        ("a,b are real", "a*(b+1)=a*b+a", "(a*(b+1))-(a*b+a)=1*((a*(b+1))-(a*b+a))", "UNKNOWN"),
        ("a,b are real", "a*(b+1)=a*b+a", "(a*(b+1))-(a*b+a)=-(-((a*(b+1))-(a*b+a)))", "UNKNOWN"),
        ("a,b are real", "a*(b+1)=a*b+a", "(a*(b+1))-(a*b+a)=0", "WHOLE_OPERATION"),
        ("a,b are real", "a*(b+1)=a*b+a", "a*(b+1)=a*b+a", "WHOLE_OPERATION"),
        ("m,n are real", "m*(n-2)=m*n-2*m", "m*(n-2)=m*n-2*m", "WHOLE_OPERATION"),
        (
            "m,n are real",
            "m*(n-2)=m*n-2*m",
            "(m*(n-2))-(m*n-2*m)=0+((m*(n-2))-(m*n-2*m))",
            "UNKNOWN",
        ),
        ("a,b are real", "a*(b/2+1)=a*b/2+a", "a*(b/2+1)=a*b/2+a", "WHOLE_OPERATION"),
    ],
)
def test_native_residual_assignment_requires_visible_polynomial_expansion(
    domain, operation, response, scope
):
    reviewed = source(domain=domain, givens=(), definitions=(), operation=operation)
    first = state_for(reviewed, operation)
    payload, _, receipt = issue_task(first, operation)
    left, right = operation.split("=")
    requested = f"({left})-({right})"
    actual_operations = [
        a for a in first.snapshot().artifacts if a.claim_kind == "operation_description"
    ]
    assert len(actual_operations) == 1
    assert json.loads(actual_operations[0].statement)["kwargs"] == {"expression": requested}
    proof_id = actual_operations[0].tool_evidence_refs[0]
    proof = next(e for e in first.snapshot().tool_evidence if e.evidence_id == proof_id)
    assert proof.tool_name == "expand" and proof.output_summary == "0"
    second = state_for(reviewed, response, payload=payload, prefix=first.prefix)
    aligned = align(second, response)
    envelope = next(e for e in aligned.math_evidence if e.tool_version == STEP_VERSION)
    assert json.loads(envelope.output_summary)["local_relation"] == "IDENTITY"
    private = publication_input(second, calculation(second))["private_teaching_context"]
    assert private["previous_task"]["publication_id"] == receipt.publication_id
    assert [r["kwargs"] for r in private["previous_task"]["operations"]] == [
        {"expression": requested}
    ]
    assert {c["scope"] for c in private["operation_correspondence"]} == {scope}
    assert all(
        c["stage_completion"] == "UNKNOWN" and c["mastery"] == "NO_INFERENCE"
        for c in private["operation_correspondence"]
    )
    assert aligned.validated_artifact_refs == aligned.novel_path_refs == ()
    assert all(g["act_kind"] != "result" for g in calculation(second)["authority"])


@pytest.mark.asyncio
async def test_real_host_selector_consumes_evidence_and_receipt_without_publication_expansion(
    publication_host_factory,
):
    host, generation, _ = publication_host_factory()
    host.source = source()
    host.scope = host.math_scope()
    generation.mode = "operation"
    session, first = await host.submit(FULL)
    first_inputs = generation.calls[-1]["inputs"]
    first_receipt = assistant_row(host, first["id"])[2]["accepted_output"]["math_publication"]
    _, second = await host.submit(TRUE, session_id=session["session_id"])
    inputs = generation.calls[-1]["inputs"]
    context = inputs["private_teaching_context"]
    assert context["previous_task"]["publication_id"] == first_receipt["publication_id"]
    assert {c["scope"] for c in context["operation_correspondence"]} == {"LOCAL_CONTRIBUTION"}
    assert any(
        json.loads(e["output_summary"]).get("local_relation") == "IDENTITY"
        for e in context["step_evidence"]
        if e["tool_version"] == STEP_VERSION
    )

    # Target/act/scope permissions are identical despite evidence-only revisions
    # rebinding the existing operation content/support IDs.
    def permissions(value):
        return {
            (
                o["grant"]["act_kind"],
                o["grant"]["target_artifact_ref"],
                o["grant"]["support_mechanism"],
                o["grant"]["support_scope"],
            )
            for o in value["offers"]
            if "contract" not in o["grant"]
        }

    assert permissions(inputs) == permissions(first_inputs)
    assert not host.result()["verified_grounded_refs"]
    assert host.result()["alignment"]["validated_artifact_refs"] == []
    body = assistant_row(host, second["id"])[1]
    assert "IDENTITY" not in body and "COUNTEREXAMPLE" not in body
    before = host.state()
    first_replay, second_replay = await replay(host, second), await replay(host, second)
    assert first_replay == second_replay and host.state() == before
    assert len(generation.calls) == 2
    assert "".join(e["content"] for e in first_replay if e["type"] == "content") == body
