"""Real typed-tool support: execution permissions never upgrade premise truth."""

from dataclasses import replace

import pytest

from deeptutor.math_semantic.contracts import MathArtifact, MathWorkspace, ProblemModel
from deeptutor.math_semantic.refs import SourceRef
from deeptutor.math_semantic.support import (
    materialize_operation_support,
    resolve_math_content_support,
)
from deeptutor.math_semantic.workspace import MathWorkspaceSnapshot, append_snapshot


@pytest.fixture(scope="module")
def operation_snapshot():
    provenance = (SourceRef("question", "generic-operation-test"),)
    model = ProblemModel("generic-operation-test", provenance[0])
    premise = MathArtifact(
        "w^2-r=4",
        "intermediate",
        provenance=provenance,
        verification_status="qualified",
        verification_scope="AI-reviewed",
    )
    definition = MathArtifact(
        "w=a+b",
        "definition",
        claim_kind="definition",
        provenance=provenance,
        verification_status="qualified",
        verification_scope="AI-reviewed",
    )
    artifacts = (premise, definition)
    snapshot = MathWorkspaceSnapshot(
        MathWorkspace(
            "operation-test", model.model_ref, artifact_refs=tuple(a.artifact_id for a in artifacts)
        ),
        model,
        artifacts,
    )
    operations, evidence = materialize_operation_support(snapshot, snapshot.workspace.artifact_refs)
    assert evidence and all(e.status == "succeeded" for e in evidence)
    return append_snapshot(snapshot, artifacts=operations, evidence=evidence), premise, definition


def operation_bindings(snapshot, refs):
    return [
        b
        for b in resolve_math_content_support(snapshot, refs)
        if b.act_kind in {"chosen_operation", "operation_options"}
    ]


def test_real_expand_and_substitute_bind_exact_premises_without_truth_upgrade(operation_snapshot):
    snapshot, premise, definition = operation_snapshot
    bindings = operation_bindings(snapshot, (premise.artifact_id, definition.artifact_id))
    assert bindings
    assert {e.tool_name for e in snapshot.tool_evidence} == {"expand", "substitute"}
    assert all(e.tool_version == "typed_math_tools_v1" for e in snapshot.tool_evidence)
    assert snapshot.artifacts[0].verification_status == "qualified"
    assert not any(a.verification_status == "verified" for a in snapshot.artifacts)
    assert all(b.act_kind != "justification" for b in bindings)


def test_same_pinned_support_reuse_is_read_only_and_makes_no_tool_call(
    operation_snapshot, monkeypatch
):
    from deeptutor.math_semantic.tools import MathToolRegistry

    snapshot, premise, definition = operation_snapshot

    def unexpected(*args, **kwargs):
        raise AssertionError("Already bound evidence must not execute again")

    monkeypatch.setattr(MathToolRegistry, "call", unexpected)
    assert materialize_operation_support(
        snapshot, (premise.artifact_id, definition.artifact_id)
    ) == ((), ())


@pytest.mark.parametrize(
    "change", ["revision", "workspace", "missing_definition", "wrong_evidence", "content"]
)
def test_stale_foreign_and_cross_artifact_support_is_rejected(operation_snapshot, change):
    snapshot, premise, definition = operation_snapshot
    refs = (premise.artifact_id, definition.artifact_id)
    if change == "revision":
        snapshot = replace(snapshot, workspace=replace(snapshot.workspace, revision=3))
    elif change == "workspace":
        snapshot = replace(snapshot, workspace=replace(snapshot.workspace, workspace_id="foreign"))
    elif change == "missing_definition":
        refs = (premise.artifact_id,)
    elif change == "wrong_evidence":
        snapshot = replace(
            snapshot,
            tool_evidence=tuple(
                replace(e, input_refs=("foreign",)) for e in snapshot.tool_evidence
            ),
        )
    else:
        snapshot = replace(
            snapshot,
            artifacts=tuple(
                replace(a, statement='{"forged":true}') if a.role == "transformation" else a
                for a in snapshot.artifacts
            ),
        )
    bindings = operation_bindings(snapshot, refs)
    if change == "missing_definition":
        proofs = {e.evidence_id: e for e in snapshot.tool_evidence}
        assert all(proofs[b.support_ref.identifier].tool_name == "expand" for b in bindings)
    else:
        assert bindings == []


def test_failed_tool_call_cannot_create_operation_authority():
    provenance = (SourceRef("question", "unsupported-operation"),)
    model = ProblemModel("unsupported-operation", provenance[0])
    premise = MathArtifact(
        "w=__import__(1)",
        "intermediate",
        provenance=provenance,
        verification_status="qualified",
        verification_scope="AI-reviewed",
    )
    snapshot = MathWorkspaceSnapshot(
        MathWorkspace("unsupported", model.model_ref, artifact_refs=(premise.artifact_id,)),
        model,
        (premise,),
    )
    operations, evidence = materialize_operation_support(snapshot, (premise.artifact_id,))
    assert not operations and evidence[0].status == "invalid_input"
    after = append_snapshot(snapshot, evidence=evidence)
    assert operation_bindings(after, (premise.artifact_id,)) == []
