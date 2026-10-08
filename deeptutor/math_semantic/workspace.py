from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, cast

from .contracts import (
    DependencyRelation,
    MathArtifact,
    MathWorkspace,
    ProblemFact,
    ProblemModel,
    SolutionPath,
    ToolEvidence,
)
from .refs import SourceRef


class WorkspaceError(RuntimeError):
    """Base class for durable workspace failures."""


class WorkspaceNotFound(WorkspaceError):
    pass


class RevisionConflict(WorkspaceError):
    pass


class DuplicateAttemptError(WorkspaceError):
    pass


@dataclass(frozen=True, slots=True)
class MathWorkspaceSnapshot:
    workspace: MathWorkspace
    problem_model: ProblemModel
    artifacts: tuple[MathArtifact, ...] = ()
    relations: tuple[DependencyRelation, ...] = ()
    paths: tuple[SolutionPath, ...] = ()
    tool_evidence: tuple[ToolEvidence, ...] = ()
    superseded_by: tuple[tuple[str, str], ...] = ()

    @property
    def workspace_ref(self) -> SourceRef:
        return SourceRef("math_workspace", self.workspace.workspace_id)

    @property
    def refs_manifest(self) -> dict[str, object]:
        return {
            "workspace_ref": self.workspace_ref,
            "workspace_revision": self.workspace.revision,
            "problem_model_ref": self.workspace.problem_model_ref,
            "artifact_refs": self.workspace.artifact_refs,
            "solution_path_refs": self.workspace.solution_path_refs,
            "dependency_relation_refs": self.workspace.dependency_relation_refs,
            "tool_evidence_refs": self.workspace.tool_evidence_refs,
        }


@dataclass(frozen=True, slots=True)
class ReasoningAttempt:
    attempt_id: str
    workspace_id: str
    workspace_revision: int
    provider_digest: str
    model_config_digest: str
    input_projection_digest: str
    projected_refs: tuple[str, ...]
    attempt_no: int
    status: str
    proposal_json: str | None = None
    evidence_refs: tuple[str, ...] = ()
    materialized_refs: tuple[str, ...] = ()
    materialized_revision: int | None = None
    failure_type: str | None = None
    model_call_state: str = "not_called"
    tool_call_state: str = "not_called"

    @property
    def model_budget_consumed(self) -> bool:
        return self.model_call_state != "not_called"

    @property
    def tool_budget_consumed(self) -> bool:
        return self.tool_call_state != "not_called"


def _src(value: SourceRef) -> dict[str, str]:
    return {"kind": value.kind, "identifier": value.identifier}


def _src_from(value: dict[str, str]) -> SourceRef:
    return SourceRef(value["kind"], value["identifier"])


def _fact(value: ProblemFact) -> dict[str, object]:
    return {
        "value": value.value,
        "status": value.status,
        "provenance": [_src(item) for item in value.provenance],
        "uncertainty": value.uncertainty,
        "note": value.note,
    }


def _fact_from(value: dict[str, Any]) -> ProblemFact:
    return ProblemFact(
        value=value["value"],
        status=value["status"],
        provenance=tuple((_src_from(item) for item in value["provenance"])),
        uncertainty=value["uncertainty"],
        note=value["note"],
    )


def _model(value: ProblemModel) -> dict[str, object]:
    return {
        "problem_id": value.problem_id,
        "public_ref": _src(value.public_ref),
        "givens": [_fact(item) for item in value.givens],
        "target": _fact(value.target) if value.target else None,
        "objective": [_fact(item) for item in value.objective],
        "constraints": [_fact(item) for item in value.constraints],
        "domain": [_fact(item) for item in value.domain],
        "quantifiers": [_fact(item) for item in value.quantifiers],
        "assumptions": [_fact(item) for item in value.assumptions],
        "parse_status": value.parse_status,
        "uncertainty": value.uncertainty,
        "provenance": [_src(item) for item in value.provenance],
        "version": value.version,
        "revision": value.revision,
    }


def _model_from(value: dict[str, Any]) -> ProblemModel:
    return ProblemModel(
        problem_id=value["problem_id"],
        public_ref=_src_from(value["public_ref"]),
        givens=tuple((_fact_from(item) for item in value["givens"])),
        target=_fact_from(value["target"]) if value["target"] else None,
        objective=tuple((_fact_from(item) for item in value["objective"])),
        constraints=tuple((_fact_from(item) for item in value["constraints"])),
        domain=tuple((_fact_from(item) for item in value["domain"])),
        quantifiers=tuple((_fact_from(item) for item in value["quantifiers"])),
        assumptions=tuple((_fact_from(item) for item in value["assumptions"])),
        parse_status=value["parse_status"],
        uncertainty=value["uncertainty"],
        provenance=tuple((_src_from(item) for item in value["provenance"])),
        version=value["version"],
        revision=value["revision"],
    )


def _artifact(value: MathArtifact) -> dict[str, object]:
    return {
        "statement": value.statement,
        "role": value.role,
        "claim_kind": value.claim_kind,
        "normalized_form": value.normalized_form,
        "provenance": [_src(item) for item in value.provenance],
        "dependencies": list(value.dependencies),
        "assumptions": list(value.assumptions),
        "verification_status": value.verification_status,
        "verification_scope": value.verification_scope,
        "tool_evidence_refs": list(value.tool_evidence_refs),
        "uncertainty": value.uncertainty,
        "workspace_revision": value.workspace_revision,
        "artifact_id": value.artifact_id,
    }


def _artifact_from(value: dict[str, Any]) -> MathArtifact:
    return MathArtifact(
        statement=value["statement"],
        role=value["role"],
        claim_kind=value["claim_kind"],
        normalized_form=value["normalized_form"],
        provenance=tuple((_src_from(item) for item in value["provenance"])),
        dependencies=tuple(value["dependencies"]),
        assumptions=tuple(value["assumptions"]),
        verification_status=value["verification_status"],
        verification_scope=value["verification_scope"],
        tool_evidence_refs=tuple(value["tool_evidence_refs"]),
        uncertainty=value["uncertainty"],
        workspace_revision=value["workspace_revision"],
        artifact_id=value["artifact_id"],
    )


def _path(value: SolutionPath) -> dict[str, object]:
    return {
        "method": value.method,
        "artifact_refs": list(value.artifact_refs),
        "status": value.status,
        "completeness": value.completeness,
        "provenance": [_src(item) for item in value.provenance],
        "uncertainty": value.uncertainty,
        "workspace_revision": value.workspace_revision,
        "path_id": value.path_id,
    }


def _path_from(value: dict[str, Any]) -> SolutionPath:
    return SolutionPath(
        method=value["method"],
        artifact_refs=tuple(value["artifact_refs"]),
        status=value["status"],
        completeness=value["completeness"],
        provenance=tuple((_src_from(item) for item in value["provenance"])),
        uncertainty=value["uncertainty"],
        workspace_revision=value["workspace_revision"],
        path_id=value["path_id"],
    )


def _relation(value: DependencyRelation) -> dict[str, object]:
    return {
        "source_artifact_refs": list(value.source_artifact_refs),
        "target_artifact_ref": value.target_artifact_ref,
        "relation_type": value.relation_type,
        "provenance": [_src(item) for item in value.provenance],
        "scope": value.scope,
        "workspace_revision": value.workspace_revision,
        "relation_id": value.relation_id,
    }


def _relation_from(value: dict[str, Any]) -> DependencyRelation:
    return DependencyRelation(
        source_artifact_refs=tuple(value["source_artifact_refs"]),
        target_artifact_ref=value["target_artifact_ref"],
        relation_type=value["relation_type"],
        provenance=tuple((_src_from(item) for item in value["provenance"])),
        scope=value["scope"],
        workspace_revision=value["workspace_revision"],
        relation_id=value["relation_id"],
    )


def _evidence(value: ToolEvidence) -> dict[str, object]:
    return {
        "tool_name": value.tool_name,
        "tool_version": value.tool_version,
        "input_summary": value.input_summary,
        "output_summary": value.output_summary,
        "scope": value.scope,
        "status": value.status,
        "duration_ms": value.duration_ms,
        "artifact_refs": list(value.artifact_refs),
        "failure_type": value.failure_type,
        "input_refs": list(value.input_refs),
        "evidence_id": value.evidence_id,
    }


def _evidence_from(value: dict[str, Any]) -> ToolEvidence:
    return ToolEvidence(
        tool_name=value["tool_name"],
        tool_version=value["tool_version"],
        input_summary=value["input_summary"],
        output_summary=value["output_summary"],
        scope=value["scope"],
        status=value["status"],
        duration_ms=value["duration_ms"],
        artifact_refs=tuple(value["artifact_refs"]),
        failure_type=value["failure_type"],
        input_refs=tuple(value["input_refs"]),
        evidence_id=value["evidence_id"],
    )


def _workspace(value: MathWorkspace) -> dict[str, object]:
    return {
        "workspace_id": value.workspace_id,
        "problem_model_ref": _src(value.problem_model_ref),
        "revision": value.revision,
        "artifact_refs": list(value.artifact_refs),
        "solution_path_refs": list(value.solution_path_refs),
        "dependency_relation_refs": list(value.dependency_relation_refs),
        "tool_evidence_refs": list(value.tool_evidence_refs),
        "status": value.status,
        "version": value.version,
    }


def _workspace_from(value: dict[str, Any]) -> MathWorkspace:
    return MathWorkspace(
        workspace_id=value["workspace_id"],
        problem_model_ref=_src_from(value["problem_model_ref"]),
        revision=value["revision"],
        artifact_refs=tuple(value["artifact_refs"]),
        solution_path_refs=tuple(value["solution_path_refs"]),
        dependency_relation_refs=tuple(value["dependency_relation_refs"]),
        tool_evidence_refs=tuple(value["tool_evidence_refs"]),
        status=value["status"],
        version=value["version"],
    )


def _snapshot_payload(value: MathWorkspaceSnapshot) -> dict[str, object]:
    return {
        "workspace": _workspace(value.workspace),
        "problem_model": _model(value.problem_model),
        "artifacts": [_artifact(item) for item in value.artifacts],
        "relations": [_relation(item) for item in value.relations],
        "paths": [_path(item) for item in value.paths],
        "tool_evidence": [_evidence(item) for item in value.tool_evidence],
        "superseded_by": [list(item) for item in value.superseded_by],
    }


def _snapshot_from(payload: str) -> MathWorkspaceSnapshot:
    value = json.loads(payload)
    return MathWorkspaceSnapshot(
        workspace=_workspace_from(value["workspace"]),
        problem_model=_model_from(value["problem_model"]),
        artifacts=tuple((_artifact_from(item) for item in value["artifacts"])),
        relations=tuple((_relation_from(item) for item in value["relations"])),
        paths=tuple((_path_from(item) for item in value["paths"])),
        tool_evidence=tuple((_evidence_from(item) for item in value["tool_evidence"])),
        superseded_by=tuple((tuple(item) for item in value["superseded_by"])),
    )


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def append_snapshot(
    current: MathWorkspaceSnapshot,
    *,
    artifacts: tuple[MathArtifact, ...] = (),
    evidence: tuple[ToolEvidence, ...] = (),
    relations: tuple[DependencyRelation, ...] = (),
    paths: tuple[SolutionPath, ...] = (),
    superseded_by: tuple[tuple[str, str], ...] = (),
    status: str | None = None,
) -> MathWorkspaceSnapshot:
    revision = current.workspace.revision + 1
    entities: tuple[MathArtifact | DependencyRelation | SolutionPath, ...] = (
        *artifacts,
        *relations,
        *paths,
    )
    for entity in entities:
        if entity.workspace_revision != revision:
            raise RevisionConflict("new workspace entities must carry the next revision")
    existing_artifacts = {cast(str, item.artifact_id): item for item in current.artifacts}
    existing_evidence = {cast(str, item.evidence_id): item for item in current.tool_evidence}
    existing_relations = {cast(str, item.relation_id): item for item in current.relations}
    existing_paths = {cast(str, item.path_id): item for item in current.paths}
    for artifact in artifacts:
        existing_artifacts[cast(str, artifact.artifact_id)] = artifact
    for proof in evidence:
        existing_evidence[cast(str, proof.evidence_id)] = proof
    for relation in relations:
        existing_relations[cast(str, relation.relation_id)] = relation
    for path in paths:
        existing_paths[cast(str, path.path_id)] = path
    superseded = dict(current.superseded_by)
    superseded.update(dict(superseded_by))
    workspace = MathWorkspace(
        workspace_id=current.workspace.workspace_id,
        problem_model_ref=current.workspace.problem_model_ref,
        revision=revision,
        artifact_refs=tuple(existing_artifacts),
        solution_path_refs=tuple(existing_paths),
        dependency_relation_refs=tuple(existing_relations),
        tool_evidence_refs=tuple(existing_evidence),
        status=status or current.workspace.status,
        version=current.workspace.version,
    )
    return MathWorkspaceSnapshot(
        workspace=workspace,
        problem_model=current.problem_model,
        artifacts=tuple(existing_artifacts.values()),
        relations=tuple(existing_relations.values()),
        paths=tuple(existing_paths.values()),
        tool_evidence=tuple(existing_evidence.values()),
        superseded_by=tuple(superseded.items()),
    )
