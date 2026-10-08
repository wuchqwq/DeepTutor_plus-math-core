"""Compare the native package to captured outputs, without importing tutor_demo."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path

import pytest

from deeptutor.math_semantic.accepted import AcceptedSubmission
from deeptutor.math_semantic.alignment import AlignmentEvaluator, materialize_alignment
from deeptutor.math_semantic.claims import EvidenceSpan, StudentMathClaim
from deeptutor.math_semantic.codec import _decode
from deeptutor.math_semantic.contracts import DependencyGraph
from deeptutor.math_semantic.expression import MathExpression
from deeptutor.math_semantic.proposals import (
    AlignmentProposal,
    ArtifactSummary,
    ProviderEvidence,
    resolve_evidence,
)
from deeptutor.math_semantic.refs import LearnerRef, QuestionRef, SourceRef
from deeptutor.math_semantic.support import resolve_math_content_support
from deeptutor.math_semantic.trajectory import derive_trajectory
from deeptutor.math_semantic.trajectory_types import MethodConfirmation
from deeptutor.math_semantic.transformations import (
    TypedTransformationOperation,
    _evaluate_transformation,
)
from deeptutor.math_semantic.validation import ValidationRequest, validate_request
from deeptutor.math_semantic.verification import math_verifier_available, validate_math_claim
from deeptutor.math_semantic.workspace import (
    _artifact_from,
    _snapshot_from,
    _snapshot_payload,
    append_snapshot,
)

ORACLE = json.loads(
    Path(__file__).with_name("fixtures").joinpath("oracle.json").read_text(encoding="utf-8")
)
NEGATIVE = json.loads(
    Path(__file__)
    .with_name("fixtures")
    .joinpath("trajectory_negative.json")
    .read_text(encoding="utf-8")
)


def canonical(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items() if key != "duration_ms"}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return value


def snapshot(name):
    return _snapshot_from(json.dumps(ORACLE["snapshots"][name]))


@pytest.mark.parametrize("case", ORACLE["compare"], ids=lambda c: c["id"])
def test_math_correspondence(case):
    value = case["claim"]
    claim = StudentMathClaim(
        **{
            **value,
            "student_response_ref": SourceRef(**value["student_response_ref"]),
            "evidence": EvidenceSpan(**value["evidence"]),
        }
    )
    artifact = ArtifactSummary(**case["artifact"])
    assert (
        canonical(AlignmentEvaluator._compare(claim, artifact, answer_ref=case["answer_ref"]))
        == case["expected"]
    )


@pytest.mark.parametrize("case", ORACLE["alignment"])
def test_full_grounded_alignment(case):
    before = _snapshot_from(json.dumps(case["snapshot"]))
    response = AcceptedSubmission(
        case["response_id"], case["text"], "oracle-session", "oracle-turn"
    )
    result = materialize_alignment(
        response,
        before,
        AlignmentProposal.from_value(case["proposal"]),
        provider_id=case["provider_id"],
        config_digest=case["config_digest"],
    )
    assert canonical(result.alignment) == case["expected"]
    after = (
        append_snapshot(
            before, artifacts=result.artifacts, paths=result.paths, evidence=result.evidence
        )
        if result.artifacts
        else before
    )
    assert canonical(_snapshot_payload(after)) == case["output_snapshot"]


@pytest.mark.parametrize("case", ORACLE["trajectory"])
def test_trajectory_prefix_equivalence(case):
    current = snapshot(case["snapshot"])
    arguments = case["arguments"]
    args = {
        **arguments,
        "cutoff_response_ref": SourceRef(**arguments["cutoff_response_ref"]),
        "basis_refs": tuple(SourceRef(**ref) for ref in arguments["basis_refs"]),
        "learner": LearnerRef(**arguments["learner"]),
        "question_ref": QuestionRef(**arguments["question_ref"]),
    }
    if "confirmations" in arguments:
        args["confirmations"] = tuple(
            MethodConfirmation.from_dict(value) for value in arguments["confirmations"]
        )
    alignments = tuple(
        _decode(json.dumps(value)) if value else None for value in case["alignments"]
    )
    result = derive_trajectory(current, current, alignments, **args)
    assert canonical(result.to_dict()) == case["expected"]


@pytest.mark.parametrize("case", ORACLE["grounding"])
def test_exact_span_grounding(case):
    try:
        actual = {
            "span": canonical(
                resolve_evidence(case["text"], ProviderEvidence(case["quote"], case["occurrence"]))
            )
        }
    except ValueError as exc:
        actual = {"error": str(exc)}
    assert actual == case["expected"]


@pytest.mark.parametrize("case", ORACLE["validation"])
def test_math_validation(case):
    assert math_verifier_available(), "oracle equivalence requires the verifier; never skip"
    try:
        result = validate_math_claim(
            MathExpression(case["statement"], case["support"], case["kind"])
        )
        actual = {
            "status": result.status,
            "scope": result.scope,
            "residual": result.residual,
            "error": None,
        }
    except ValueError as exc:
        actual = {"error": str(exc)}
    assert actual == case["expected"]


@pytest.mark.parametrize("case", ORACLE["transformation"])
def test_relative_transformation_scope(case):
    assert (
        canonical(
            _evaluate_transformation(
                _artifact_from(case["before"]),
                TypedTransformationOperation(
                    case["operation"]["kind"], case["operation"]["quantity"]
                ),
            )
        )
        == case["expected"]
    )


@pytest.mark.parametrize("case", ORACLE["dependencies"])
def test_path_relative_dependency_closure(case):
    current = snapshot(case["snapshot"])
    graph = DependencyGraph(
        workspace_revision=current.workspace.revision,
        artifacts=current.artifacts,
        paths=current.paths,
        workspace_ref=current.workspace_ref,
        allow_historical=True,
    )
    for relation in current.relations:
        graph.add_relation(relation)
    assert {
        ref: graph.dependency_status(ref, path_ref=case["path"]) for ref in case["expected"]
    } == case["expected"]


@pytest.mark.parametrize("case", ORACLE["support"])
def test_literal_math_support_is_not_truth_or_justification(case):
    result = resolve_math_content_support(snapshot(case["snapshot"]), tuple(case["refs"]))
    assert canonical(result) == case["expected"]


def test_frozen_provenance_is_not_the_planning_revision():
    assert ORACLE["baseline"] == "76d5d9697186d086fb967e79a9e08e394b0d5474"
    assert ORACLE["provenance"] == {
        "runtime_oracle_sha": "76d5d9697186d086fb967e79a9e08e394b0d5474",
        "planning_sha": "a2a1905dc41eed3e5a574304993c2747dcb0838c",
        "deeptutor_base_sha": "73774dc26a734c040d3f91bc887060127475178f",
        "whitelist_version": "MATH-ENGINE-EXTRACTION-WHITELIST-01",
        "whitelist_source": "docs/design/MATH_ENGINE_EXTRACTION_WHITELIST_01.md",
    }
    assert len(ORACLE["source_sha256"]) > 50


def test_comparison_fixture_inputs_are_mathematical_artifact_summaries():
    # This control rejects a wrong positional-constructor capture that could
    # make old and new agree while testing role labels as mathematical text.
    assert len(ORACLE["compare"]) == 129
    for case in ORACLE["compare"]:
        assert case["artifact"]["role"] in {"intermediate", "answer_candidate"}
        assert case["artifact"]["verification_status"] == "qualified"
        assert case["artifact"]["verification_scope"] == "oracle"
        assert case["artifact"]["statement"] not in {"intermediate", "answer_candidate"}


@pytest.mark.parametrize("case", NEGATIVE["trajectory"], ids=lambda case: case["id"])
def test_negative_trajectory_uncertainty_contradiction_and_active_filtering(case):
    current = _snapshot_from(json.dumps(case["current"]))
    authored = _snapshot_from(json.dumps(case["authored"]))
    original = case["arguments"]
    arguments = {
        **original,
        "cutoff_response_ref": SourceRef(**original["cutoff_response_ref"]),
        "basis_refs": tuple(SourceRef(**ref) for ref in original["basis_refs"]),
        "learner": LearnerRef(**original["learner"]),
        "question_ref": QuestionRef(**original["question_ref"]),
    }
    history = tuple(_decode(json.dumps(item)) for item in case["alignments"])
    actual = derive_trajectory(current, authored, history, **arguments)
    assert canonical(actual.to_dict()) == case["expected"]


@pytest.mark.parametrize("case", NEGATIVE["validation_request"])
def test_zero_deadline_adapter_never_promotes_mathematical_truth(case):
    assert math_verifier_available(), "timeout oracle was captured with available verifier"
    assert canonical(validate_request(ValidationRequest(**case["request"]))) == case["expected"]
