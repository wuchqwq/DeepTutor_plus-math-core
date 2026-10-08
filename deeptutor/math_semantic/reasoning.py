from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Protocol, cast

from .contracts import DependencyRelation, MathArtifact, ProblemModel, SolutionPath
from .refs import SourceRef
from .tools import validate_artifact
from .workspace import MathWorkspaceSnapshot, ReasoningAttempt

STOP_REASONS = frozenset(
    {
        "complete",
        "partial",
        "blocked_unknown",
        "blocked_tool_limit",
        "blocked_model_limit",
        "unsupported_domain",
        "conflict",
        "runtime_failure",
    }
)
_PRIVATE_MARKERS = ("chain of thought", "private cot", "思维链", "内部推理")
_ALLOWED_TOOL_NAMES = frozenset(
    {"simplify", "expand", "factor", "substitute", "check_equivalence", "numeric_evaluate"}
)


@dataclass(frozen=True, slots=True)
class ReasoningBudget:
    max_reasoning_rounds: int = 4
    max_tool_calls: int = 4
    max_model_calls: int = 4
    deadline_ms: int = 30000
    per_call_timeout_ms: int = 5000
    max_output_chars: int = 8000

    def __post_init__(self) -> None:
        for name in (
            "max_reasoning_rounds",
            "max_tool_calls",
            "max_model_calls",
            "deadline_ms",
            "per_call_timeout_ms",
        ):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if self.max_output_chars < 256:
            raise ValueError("max_output_chars is too small")


@dataclass(frozen=True, slots=True)
class ArtifactProposal:
    statement: str
    role: str = "intermediate"
    claim_kind: str = "derived_equation"
    dependencies: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    uncertainty: float = 0.0
    local_id: str | None = None
    supersedes: str | None = None

    @classmethod
    def from_value(cls, value: object) -> "ArtifactProposal":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("artifact proposal must be an object")
        allowed = {
            "statement",
            "role",
            "claim_kind",
            "dependencies",
            "assumptions",
            "uncertainty",
            "local_id",
            "supersedes",
        }
        if set(value) - allowed:
            raise ValueError("artifact proposal contains unknown fields")
        statement = value.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError("artifact proposal statement is required")
        return cls(
            statement=statement,
            role=str(value.get("role", "intermediate")),
            claim_kind=str(value.get("claim_kind", "derived_equation")),
            dependencies=tuple((str(item) for item in value.get("dependencies", ()))),
            assumptions=tuple((str(item) for item in value.get("assumptions", ()))),
            uncertainty=float(value.get("uncertainty", 0.0)),
            local_id=str(value["local_id"]) if value.get("local_id") is not None else None,
            supersedes=str(value["supersedes"]) if value.get("supersedes") is not None else None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "statement": self.statement,
            "role": self.role,
            "claim_kind": self.claim_kind,
            "dependencies": list(self.dependencies),
            "assumptions": list(self.assumptions),
            "uncertainty": self.uncertainty,
            "local_id": self.local_id,
            "supersedes": self.supersedes,
        }


@dataclass(frozen=True, slots=True)
class RelationProposal:
    source_artifact_refs: tuple[str, ...]
    target_artifact_ref: str
    relation_type: str
    scope: str = "reasoning"

    @classmethod
    def from_value(cls, value: object) -> "RelationProposal":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("relation proposal must be an object")
        allowed = {"source_artifact_refs", "target_artifact_ref", "relation_type", "scope"}
        if set(value) - allowed:
            raise ValueError("relation proposal contains unknown fields")
        return cls(
            source_artifact_refs=tuple(
                (str(item) for item in value.get("source_artifact_refs", ()))
            ),
            target_artifact_ref=str(value.get("target_artifact_ref", "")),
            relation_type=str(value.get("relation_type", "")),
            scope=str(value.get("scope", "reasoning")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_artifact_refs": list(self.source_artifact_refs),
            "target_artifact_ref": self.target_artifact_ref,
            "relation_type": self.relation_type,
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class PathUpdateProposal:
    method: str
    artifact_refs: tuple[str, ...] = ()
    status: str = "candidate"
    completeness: str = "unknown"

    @classmethod
    def from_value(cls, value: object) -> "PathUpdateProposal":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("path update must be an object")
        allowed = {"method", "artifact_refs", "status", "completeness"}
        if set(value) - allowed:
            raise ValueError("path update contains unknown fields")
        method = str(value.get("method", ""))
        if not method.strip():
            raise ValueError("path update method is required")
        return cls(
            method,
            tuple((str(item) for item in value.get("artifact_refs", ()))),
            str(value.get("status", "candidate")),
            str(value.get("completeness", "unknown")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "artifact_refs": list(self.artifact_refs),
            "status": self.status,
            "completeness": self.completeness,
        }


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    operation: str
    kwargs: Mapping[str, object]
    input_refs: tuple[str, ...] = ()
    timeout_ms: int = 5000

    @classmethod
    def from_value(cls, value: object) -> "ToolCallRequest":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("tool request must be an object")
        allowed = {"operation", "kwargs", "input_refs", "timeout_ms"}
        if set(value) - allowed:
            raise ValueError("tool request contains unknown fields")
        operation = str(value.get("operation", ""))
        kwargs = value.get("kwargs", {})
        if operation not in _ALLOWED_TOOL_NAMES or not isinstance(kwargs, Mapping):
            raise ValueError("tool request is not an allow-listed typed call")
        timeout_ms = int(value.get("timeout_ms", 5000))
        if timeout_ms < 1:
            raise ValueError("tool request timeout must be positive")
        return cls(
            operation,
            dict(kwargs),
            tuple((str(item) for item in value.get("input_refs", ()))),
            timeout_ms,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "kwargs": dict(self.kwargs),
            "input_refs": list(self.input_refs),
            "timeout_ms": self.timeout_ms,
        }


@dataclass(frozen=True, slots=True)
class ReasoningStepProposal:
    """One bounded proposal round with explicit, mutually-exclusive action modes.

    The discriminated ``kind`` makes unsafe mixtures hard to express at the
    schema boundary: a tool round can never smuggle materialization or a stop
    (evidence-before-materialization), and direct construction derives the
    kind from the payload so scripted callers cannot build mixed forms either.
    A ``materialize`` round may carry a terminal ``stop_reason``; that is the
    safe "propose final state and finish" step and touches no tool evidence.
    """

    kind: str | None = None
    proposed_artifacts: tuple[ArtifactProposal, ...] = ()
    proposed_relations: tuple[RelationProposal, ...] = ()
    proposed_path_updates: tuple[PathUpdateProposal, ...] = ()
    requested_tool_call: ToolCallRequest | None = None
    stop_reason: str | None = None
    public_summary: str | None = None

    def __post_init__(self) -> None:
        if self.kind is None:
            if self.requested_tool_call is not None:
                kind = "tool"
            elif self.stop_reason is not None and (
                not (
                    self.proposed_artifacts or self.proposed_relations or self.proposed_path_updates
                )
            ):
                kind = "stop"
            else:
                kind = "materialize"
            object.__setattr__(self, "kind", kind)
        self._validate_modes()

    def _validate_modes(self) -> None:
        if self.kind not in {"tool", "materialize", "stop"}:
            raise ValueError(f"unsupported proposal kind: {self.kind!r}")
        carries_payload = bool(
            self.proposed_artifacts or self.proposed_relations or self.proposed_path_updates
        )
        if self.kind == "tool":
            if self.requested_tool_call is None:
                raise ValueError("tool proposal requires requested_tool_call")
            if carries_payload:
                raise ValueError("tool proposal cannot carry materialization payload")
            if self.stop_reason is not None:
                raise ValueError("tool proposal cannot set stop_reason")
        elif self.kind == "materialize":
            if self.requested_tool_call is not None:
                raise ValueError("materialize proposal cannot request a tool")
        else:
            if self.requested_tool_call is not None:
                raise ValueError("stop proposal cannot request a tool")
            if carries_payload:
                raise ValueError("stop proposal cannot carry materialization payload")
            if self.stop_reason is None:
                raise ValueError("stop proposal requires stop_reason")

    @classmethod
    def from_value(cls, value: object, *, max_output_chars: int = 8000) -> "ReasoningStepProposal":
        if isinstance(value, cls):
            proposal = value
        else:
            if not isinstance(value, Mapping):
                raise ValueError("reasoning proposal must be an object")
            allowed = {
                "kind",
                "proposed_artifacts",
                "proposed_relations",
                "proposed_path_updates",
                "requested_tool_call",
                "stop_reason",
                "public_summary",
            }
            if set(value) - allowed:
                raise ValueError("reasoning proposal contains unknown fields")
            if value.get("kind") not in {"tool", "materialize", "stop"}:
                raise ValueError("reasoning proposal must declare kind: tool, materialize, or stop")
            proposal = cls(
                kind=str(value["kind"]),
                proposed_artifacts=tuple(
                    (
                        ArtifactProposal.from_value(item)
                        for item in value.get("proposed_artifacts", ())
                    )
                ),
                proposed_relations=tuple(
                    (
                        RelationProposal.from_value(item)
                        for item in value.get("proposed_relations", ())
                    )
                ),
                proposed_path_updates=tuple(
                    (
                        PathUpdateProposal.from_value(item)
                        for item in value.get("proposed_path_updates", ())
                    )
                ),
                requested_tool_call=ToolCallRequest.from_value(value["requested_tool_call"])
                if value.get("requested_tool_call") is not None
                else None,
                stop_reason=str(value["stop_reason"])
                if value.get("stop_reason") is not None
                else None,
                public_summary=str(value["public_summary"])
                if value.get("public_summary") is not None
                else None,
            )
        if proposal.public_summary is not None and len(proposal.public_summary) > 1000:
            raise ValueError("public summary exceeds bounded length")
        serialized = json.dumps(
            proposal.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if len(serialized) > max_output_chars or any(
            (marker in serialized.casefold() for marker in _PRIVATE_MARKERS)
        ):
            raise ValueError("reasoning proposal exceeds bounded public structure")
        if (
            len(proposal.proposed_artifacts) > 8
            or len(proposal.proposed_relations) > 16
            or len(proposal.proposed_path_updates) > 4
        ):
            raise ValueError("reasoning proposal exceeds item bounds")
        if proposal.stop_reason is not None and proposal.stop_reason not in STOP_REASONS:
            raise ValueError(f"unsupported stop reason: {proposal.stop_reason}")
        return proposal

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "proposed_artifacts": [item.to_dict() for item in self.proposed_artifacts],
            "proposed_relations": [item.to_dict() for item in self.proposed_relations],
            "proposed_path_updates": [item.to_dict() for item in self.proposed_path_updates],
            "requested_tool_call": self.requested_tool_call.to_dict()
            if self.requested_tool_call
            else None,
            "stop_reason": self.stop_reason,
            "public_summary": self.public_summary,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceProjection:
    workspace_ref: SourceRef
    workspace_revision: int
    problem_model_summary: Mapping[str, object]
    active_path_refs: tuple[str, ...]
    artifact_summaries: tuple[Mapping[str, object], ...]
    unresolved_targets: tuple[str, ...]
    recent_tool_evidence: tuple[Mapping[str, object], ...]
    projected_refs: tuple[str, ...]
    budget: Mapping[str, int]
    tool_input_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "workspace_ref": {
                "kind": self.workspace_ref.kind,
                "identifier": self.workspace_ref.identifier,
            },
            "workspace_revision": self.workspace_revision,
            "problem_model_summary": dict(self.problem_model_summary),
            "active_path_refs": list(self.active_path_refs),
            "artifact_summaries": [dict(item) for item in self.artifact_summaries],
            "unresolved_targets": list(self.unresolved_targets),
            "recent_tool_evidence": [dict(item) for item in self.recent_tool_evidence],
            "projected_refs": list(self.projected_refs),
            "budget": dict(self.budget),
            "tool_input_refs": list(self.tool_input_refs),
        }


@dataclass(frozen=True, slots=True)
class ReasoningContext:
    problem_model: ProblemModel
    projection: WorkspaceProjection
    round_number: int
    attempt_no: int


class MathReasoningProvider(Protocol):
    provider_id: str
    model_config_digest: str

    def propose(self, context: ReasoningContext) -> object:
        """Return one bounded structured proposal; no tool execution or persistence."""


def validate_tool_input_refs(
    snapshot: MathWorkspaceSnapshot, request: ToolCallRequest
) -> tuple[str, ...]:
    """Authenticate referenced math inputs against the pinned workspace.

    The problem-model reference is available for audit in a projection; it is
    outside tool-input authority. Empty refs retain the frozen tool semantics.
    """
    input_refs = tuple(request.input_refs)
    known_refs = set(snapshot.workspace.artifact_refs) | set(snapshot.workspace.tool_evidence_refs)
    if input_refs and not set(input_refs) <= known_refs:
        raise ValueError("tool request references an unknown artifact/evidence")
    return input_refs


def materialize_reasoning(
    snapshot: MathWorkspaceSnapshot, attempt: ReasoningAttempt, proposal: ReasoningStepProposal
) -> tuple[
    tuple[MathArtifact, ...],
    tuple[Any, ...],
    tuple[DependencyRelation, ...],
    tuple[SolutionPath, ...],
    tuple[tuple[str, str], ...],
]:
    next_revision = snapshot.workspace.revision + 1
    local_refs: dict[str, str] = {}
    artifacts: list[MathArtifact] = []
    evidence: list[Any] = []
    provenance = (
        snapshot.problem_model.model_ref,
        SourceRef("reasoning_attempt", attempt.attempt_id),
    )
    for item in proposal.proposed_artifacts:
        dependencies = tuple((local_refs.get(ref, ref) for ref in item.dependencies))
        artifact = MathArtifact(
            statement=item.statement,
            role=item.role,
            claim_kind=item.claim_kind,
            provenance=provenance,
            dependencies=dependencies,
            assumptions=item.assumptions,
            uncertainty=item.uncertainty,
            workspace_revision=next_revision,
        )
        checked, validation_evidence = validate_artifact(
            artifact, support_text=proposal.public_summary or ""
        )
        artifacts.append(checked)
        evidence.append(validation_evidence)
        if item.local_id:
            local_refs[item.local_id] = cast(str, checked.artifact_id)
    relations: list[DependencyRelation] = []
    for relation_proposal in proposal.proposed_relations:
        sources = tuple(
            (local_refs.get(ref, ref) for ref in relation_proposal.source_artifact_refs)
        )
        target = local_refs.get(
            relation_proposal.target_artifact_ref, relation_proposal.target_artifact_ref
        )
        relations.append(
            DependencyRelation(
                source_artifact_refs=sources,
                target_artifact_ref=target,
                relation_type=relation_proposal.relation_type,
                provenance=provenance,
                scope=relation_proposal.scope,
                workspace_revision=next_revision,
            )
        )
    paths: list[SolutionPath] = []
    for path_proposal in proposal.proposed_path_updates:
        refs = tuple((local_refs.get(ref, ref) for ref in path_proposal.artifact_refs))
        paths.append(
            SolutionPath(
                method=path_proposal.method,
                artifact_refs=refs,
                status=path_proposal.status,
                completeness=path_proposal.completeness,
                provenance=provenance,
                workspace_revision=next_revision,
            )
        )
    superseded = tuple(
        (
            (item.supersedes, local_refs[item.local_id])
            for item in proposal.proposed_artifacts
            if item.supersedes and item.local_id in local_refs
        )
    )
    return (tuple(artifacts), tuple(evidence), tuple(relations), tuple(paths), superseded)


def project_reasoning(
    snapshot: MathWorkspaceSnapshot, round_number: int, budget: ReasoningBudget
) -> WorkspaceProjection:
    active_path = snapshot.paths[-1] if snapshot.paths else None
    active_refs = tuple(active_path.artifact_refs) if active_path else ()
    by_id = {item.artifact_id: item for item in snapshot.artifacts}
    selected = [by_id[ref] for ref in active_refs if ref in by_id]
    if not selected:
        selected = list(snapshot.artifacts[-4:])
    summaries = tuple(
        (
            {
                "artifact_id": item.artifact_id,
                "statement": item.statement,
                "verification_status": item.verification_status,
                "dependencies": item.dependencies,
                "verification_scope": item.verification_scope,
            }
            for item in selected
        )
    )
    unresolved = tuple(
        (
            fact.value or "unknown"
            for fact in ((snapshot.problem_model.target,) if snapshot.problem_model.target else ())
            if fact.status in {"unknown", "conflicting"}
        )
    )
    evidence = tuple(
        (
            {
                "evidence_id": item.evidence_id,
                "tool_name": item.tool_name,
                "status": item.status,
                "scope": item.scope,
                "input_refs": item.input_refs,
                "output_summary": item.output_summary,
            }
            for item in snapshot.tool_evidence[-4:]
        )
    )
    refs = (
        snapshot.workspace.problem_model_ref,
        *[item["artifact_id"] for item in summaries],
        *[item["evidence_id"] for item in evidence],
    )
    tool_input_refs = tuple(
        [str(item["artifact_id"]) for item in summaries]
        + [str(item["evidence_id"]) for item in evidence]
    )
    return WorkspaceProjection(
        workspace_ref=SourceRef("math_workspace", snapshot.workspace.workspace_id),
        workspace_revision=snapshot.workspace.revision,
        problem_model_summary={
            "problem_id": snapshot.problem_model.problem_id,
            "question_ref": snapshot.problem_model.question_ref,
            "model_ref": snapshot.problem_model.model_ref,
            "target_status": snapshot.problem_model.target.status
            if snapshot.problem_model.target
            else None,
            "target": snapshot.problem_model.target.value
            if snapshot.problem_model.target
            else None,
            "parse_status": snapshot.problem_model.parse_status,
            "has_unknowns": snapshot.problem_model.has_unknowns,
            "has_conflicts": snapshot.problem_model.has_conflicts,
        },
        active_path_refs=active_refs,
        artifact_summaries=summaries,
        unresolved_targets=unresolved,
        recent_tool_evidence=evidence,
        projected_refs=tuple(
            (str(ref.identifier if isinstance(ref, SourceRef) else ref) for ref in refs)
        ),
        budget={
            "round": round_number,
            "max_reasoning_rounds": budget.max_reasoning_rounds,
            "max_tool_calls": budget.max_tool_calls,
            "max_model_calls": budget.max_model_calls,
        },
        tool_input_refs=tool_input_refs,
    )
