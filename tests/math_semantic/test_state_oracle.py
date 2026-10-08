"""Stateful native domain outcomes compared to frozen legacy ledger results.

The legacy capture is evaluation-only. Native tests load inert fixtures and
exercise only the extracted package; host acceptance is a separate real-chain
suite because these explicit fixture identities are not product submissions.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass, replace
import json
from pathlib import Path

import pytest

from deeptutor.math_semantic.accepted import AcceptedSubmission, EpisodeIdentity
from deeptutor.math_semantic.authority import MathSemanticGrant
from deeptutor.math_semantic.ceiling import require_math_authority
from deeptutor.math_semantic.confirmation import resolve_confirmation
from deeptutor.math_semantic.proposals import AlignmentProposal
from deeptutor.math_semantic.reasoning import (
    ReasoningBudget,
    ReasoningStepProposal,
    materialize_reasoning,
    project_reasoning,
)
from deeptutor.math_semantic.refs import LearnerRef, QuestionRef, SourceRef
from deeptutor.math_semantic.state import (
    MathMutation,
    ReviewedSource,
    confirm_method,
    run_math_operation,
)
from deeptutor.math_semantic.trajectory_types import MethodConfirmation, TrajectoryProjection
from deeptutor.math_semantic.transformations import TypedTransformationOperation
from deeptutor.math_semantic.workspace import ReasoningAttempt, _snapshot_from, _snapshot_payload

ORACLE = json.loads(
    Path(__file__).with_name("fixtures").joinpath("oracle.json").read_text(encoding="utf-8")
)
WRAPPER = json.loads(
    Path(__file__)
    .with_name("fixtures")
    .joinpath("confirmation_wrapper.json")
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


def decode_timed_snapshot(value):
    value = json.loads(json.dumps(value))
    for evidence in value["tool_evidence"]:
        # Capture intentionally removes wall-clock duration, never semantic
        # evidence fields. Restore the neutral schema default for deserialization.
        evidence["duration_ms"] = 0.0
    return _snapshot_from(json.dumps(value))


def new_mutation(current, *, prefix_length=1, payload=None):
    source = ReviewedSource(
        EpisodeIdentity(
            current.workspace.workspace_id,
            LearnerRef("oracle-space", "learner"),
            QuestionRef(current.problem_model.problem_id, current.problem_model.revision),
        ),
        current,
    )
    prefix = tuple(
        AcceptedSubmission(
            "frozen-state-" + str(index),
            "fixture evidence",
            "oracle-session",
            "oracle-turn-" + str(index),
        )
        for index in range(1, prefix_length + 1)
    )
    return MathMutation(source, prefix[-1], prefix, payload)


@pytest.mark.parametrize("case", ORACLE.get("confirmation", ()), ids=lambda case: case["id"])
def test_confirmation_exact_tokens_state_and_rejection(case):
    issued = MethodConfirmation.from_dict(case["issued"])
    current = MethodConfirmation.from_dict(case["current"])
    if not case["authority"]:
        with pytest.raises(ValueError, match="protected host commit authority"):
            asyncio.run(run_math_operation(None, lambda value: value))
        assert not case["expected"]["accepted"]
        return
    if case["id"] == "workspace_drift":
        value = new_mutation(snapshot("three"), prefix_length=case["after_turn"])
        records = json.loads(value.serialize())
        records["confirmations"][current.confirmation_id] = canonical(current)
        value = new_mutation(
            snapshot("three"), prefix_length=case["after_turn"], payload=json.dumps(records)
        )
        with pytest.raises(ValueError, match="resolution scope changed"):
            value.confirm(
                issued,
                option_token=case["option_token"],
                expected_revision=value.snapshot().workspace.revision + 1,
            )
        assert not case["expected"]["accepted"]
        assert (
            canonical(
                MethodConfirmation.from_dict(
                    json.loads(value.serialize())["confirmations"][current.confirmation_id]
                )
            )
            == case["persisted"]
        )
        return
    try:
        actual = (
            current
            if case["id"] == "pending"
            else resolve_confirmation(
                issued,
                current,
                option_token=case["option_token"],
                after_turn=case["after_turn"],
                invalidate=case["invalidate"],
            )
        )
    except ValueError:
        assert not case["expected"]["accepted"]
        # A failed choice leaves the issuing state and exact token mapping intact.
        assert canonical(current) == case["persisted"]
    else:
        assert case["expected"]["accepted"]
        assert canonical(actual) == case["expected"]["value"]
        assert canonical(actual) == case["persisted"]


@pytest.mark.parametrize(
    "case", ORACLE.get("reasoning_proposal", ()), ids=lambda case: str(case["id"])
)
def test_reasoning_proposal_bounded_discriminated_semantics(case):
    try:
        proposal = ReasoningStepProposal.from_value(case["proposal"])
        actual = {"accepted": True, "value": canonical(proposal.to_dict())}
    except ValueError as exc:
        actual = {"accepted": False, "error": str(exc)}
    assert actual == case["expected"]


@pytest.mark.parametrize(
    "case", ORACLE.get("reasoning_projection", ()), ids=lambda case: case["snapshot"]
)
def test_reasoning_projection_math_membership_and_tool_ref_authority(case):
    actual = project_reasoning(
        snapshot(case["snapshot"]), case["round"], ReasoningBudget(**case["budget"])
    )
    assert canonical(actual.to_dict()) == case["expected"]


@pytest.mark.parametrize(
    "case", ORACLE.get("reasoning_materialization", ()), ids=lambda case: str(case["id"])
)
def test_reasoning_math_materialization_local_dependencies_and_supersession(case):
    attempt = ReasoningAttempt(
        **{
            **case["attempt"],
            "projected_refs": tuple(case["attempt"]["projected_refs"]),
            "evidence_refs": tuple(case["attempt"]["evidence_refs"]),
            "materialized_refs": tuple(case["attempt"]["materialized_refs"]),
        }
    )
    actual = materialize_reasoning(
        snapshot(case["snapshot"]), attempt, ReasoningStepProposal.from_value(case["proposal"])
    )
    assert canonical(actual) == case["expected"]


@pytest.mark.parametrize("case", ORACLE.get("reasoning_budget", ()))
def test_started_or_unknown_math_domain_attempts_consume_budget(case):
    attempt = ReasoningAttempt(**case["attempt"])
    assert [attempt.model_budget_consumed, attempt.tool_budget_consumed] == case["expected"]


def test_transformation_materialization_replay_restart_relative_scope_and_budget():
    value = new_mutation(snapshot("linear"))
    for case in ORACLE["transformation_materialization"]:
        before = decode_timed_snapshot(case["input_snapshot"])
        try:
            actual = value.transform(
                before,
                before_artifact_ref=case["before_ref"],
                operation=TypedTransformationOperation(
                    case["operation"]["kind"], case["operation"]["quantity"]
                ),
            )
            observed = {"accepted": True, "value": canonical(actual)}
        except ValueError as exc:
            observed = {"accepted": False, "error": str(exc)}
        assert observed == case["expected"]
        assert canonical(_snapshot_payload(value.snapshot())) == case["output_snapshot"]
        # Reconstruct after every step; no mutable in-memory cache is an oracle.
        value = new_mutation(snapshot("linear"), payload=value.serialize())


@pytest.mark.parametrize("case", ORACLE.get("protected_boundary", ()), ids=lambda case: case["id"])
def test_protected_source_prefix_and_missing_authority_fail_closed(case):
    assert case["expected"]["accepted"] is False
    assert case["expected"]["provider_calls"] == 0
    current = snapshot("protected")
    value = new_mutation(current)
    baseline = value.serialize()
    attack = case["id"]
    if attack in {"missing", "unknown_policy"}:
        calls = []
        with pytest.raises(ValueError, match="protected host commit authority"):
            asyncio.run(run_math_operation(None, lambda mutation: calls.append(mutation)))
        assert calls == []
        return
    if attack in {"truncated", "duplicate", "over_capacity"}:
        prefix = (
            ()
            if attack == "truncated"
            else (value.submission,) * (2 if attack == "duplicate" else 33)
        )
        guarded = MathMutation(value.source, value.submission, prefix, baseline)
        with pytest.raises(ValueError):
            guarded.trajectory()
        assert guarded.serialize() == baseline
        return
    if attack == "missing_trajectory":
        with pytest.raises(ValueError, match="trajectory"):
            require_math_authority(current, None, (current.artifacts[0].artifact_id,), ())
        return
    with pytest.raises(ValueError):
        source = value.source
        if attack == "contents":
            source = replace(
                source,
                authored=replace(
                    current,
                    artifacts=(
                        replace(current.artifacts[0], statement="u+v=11"),
                        *current.artifacts[1:],
                    ),
                ),
            )
        elif attack == "revision":
            source = replace(
                source, authored=replace(current, workspace=replace(current.workspace, revision=1))
            )
        elif attack == "source":
            source = replace(
                source,
                authored=replace(
                    current,
                    problem_model=replace(
                        current.problem_model, public_ref=SourceRef("forged", "reviewed")
                    ),
                ),
            )
        elif attack == "episode":
            source = replace(
                source,
                authored=replace(
                    current, workspace=replace(current.workspace, workspace_id="foreign-episode")
                ),
            )
        elif attack == "learner":
            source = replace(
                source,
                identity=replace(
                    source.identity, learner=replace(source.identity.learner, learner_id="foreign")
                ),
            )
        elif attack == "question":
            source = replace(
                source,
                identity=replace(
                    source.identity, question_ref=replace(source.identity.question_ref, revision=99)
                ),
            )
        elif attack == "zero_paths":
            source = replace(source, authored=replace(current, paths=()))
        else:
            pytest.fail("unrecognized frozen protected control")
        MathMutation(source, value.submission, value.prefix, baseline)


@pytest.mark.parametrize("case", ORACLE.get("authority", ()), ids=lambda case: case["id"])
def test_math_region_and_exact_content_support_authority_ceiling(case):
    fields = dict(case["trajectory"])
    for name in ("cutoff_response_ref", "authored_source_ref"):
        fields[name] = SourceRef(**fields[name])
    fields["basis_refs"] = tuple(SourceRef(**value) for value in fields["basis_refs"])
    for name in ("authored_path_refs", "compatible_path_refs", "applicable_artifact_refs"):
        fields[name] = tuple(fields[name])
    if fields.get("method_confirmation") is not None:
        fields["method_confirmation"] = MethodConfirmation.from_dict(fields["method_confirmation"])
    trajectory = TrajectoryProjection(**fields)
    grants = tuple(MathSemanticGrant.from_value(value) for value in case["grants"])
    try:
        require_math_authority(
            snapshot(case["snapshot"]), trajectory, tuple(case["selected_refs"]), grants
        )
        accepted = True
    except ValueError:
        accepted = False
    assert accepted is case["expected"]


@pytest.mark.parametrize("case", WRAPPER["cases"], ids=lambda case: case["id"])
def test_reviewed_boundary_confirmation_invalidation_and_restart_canonical_outcome(case):
    """Compare old wrapper effects; SQLite fence proof is the real-chain suite."""
    authored = _snapshot_from(json.dumps(case["authored"]))
    source = ReviewedSource(
        EpisodeIdentity(
            authored.workspace.workspace_id,
            LearnerRef(**case["learner"]),
            QuestionRef(**case["question_ref"]),
        ),
        authored,
    )
    prefix, payload = [], None
    for row in case["responses"]:
        submission = AcceptedSubmission(
            row["message_id"], row["raw_content"], "oracle-session", "oracle-turn"
        )
        prefix.append(submission)
        current = MathMutation(source, submission, tuple(prefix), payload)
        proposal = AlignmentProposal.from_value(
            {"claims": [{"evidence": {"quote": row["raw_content"]}, "claim_type": "equation"}]}
        )
        current.align(
            proposal,
            expected_revision=current.snapshot().workspace.revision,
            provider_id=case["provider_id"],
            config_digest=case["config_digest"],
        )
        trajectory = current.trajectory()
        payload = current.serialize()
    issued = trajectory.method_confirmation
    assert issued is not None
    assert [path for _, path in issued.option_paths] == [
        path for _, path in case["issued"]["option_paths"]
    ]
    assert issued.issuing_turn == case["issued"]["issuing_turn"]

    async def authority(mutation):
        nonlocal payload
        current = MathMutation(source, submission, tuple(prefix), payload)
        result = mutation(current)
        payload = current.serialize()
        return result

    original_revision = current.snapshot().workspace.revision
    token = issued.option_paths[1][0]
    if case["id"] == "same_choice":
        asyncio.run(
            confirm_method(
                authority, issued, option_token=token, expected_revision=original_revision
            )
        )
    elif case["id"] == "stale_workspace":
        current = MathMutation(source, submission, tuple(prefix), payload)
        current.append(expected_revision=original_revision, status="complete")
        payload = current.serialize()
    elif case["id"] == "forged_token":
        token = case["requested_token"]
    before = payload
    try:
        asyncio.run(
            confirm_method(
                None if case["id"] == "ended_host" else authority,
                issued,
                option_token=token,
                expected_revision=original_revision,
            )
        )
        accepted = True
    except ValueError:
        accepted = False
    assert accepted is case["accepted"]
    confirmations = json.loads(payload)["confirmations"]
    restored = MethodConfirmation.from_dict(confirmations[issued.confirmation_id])
    for field in ("state", "chosen_path_ref", "resolved_after_turn"):
        assert getattr(restored, field) == case["persisted"][field]
    assert dict(restored.option_paths) == dict(issued.option_paths)
    if case["id"] in {"forged_token", "ended_host"}:
        assert payload == before
