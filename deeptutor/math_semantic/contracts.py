"""Provider-free mathematical contracts.

The contracts model task mathematics only.  They intentionally contain no
learner state, teaching policy, tutor wording, or provider response payload.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields, is_dataclass
import hashlib
import json
from typing import Any, Literal, cast

from deeptutor.math_semantic.refs import SourceRef

ParseStatus = Literal["parsed", "partial", "ambiguous", "conflicting", "unparsed"]
InterpretationStatus = Literal["explicit", "inferred", "unknown", "conflicting"]
VerificationStatus = Literal[
    "verified",
    "qualified",
    "conditional",
    "conditional_equation",
    "not_checkable",
    "refuted",
    "unresolved_conflict",
]
_RELATION_TYPES = frozenset(
    {"depends_on", "derived_from", "equivalent_to", "contradicts", "supports"}
)
_PRIVATE_REASONING_MARKERS = (
    "chain of thought",
    "private cot",
    "思维链",
    "内部推理",
    "private reasoning",
)


def _as_jsonable(value: Any) -> Any:
    if isinstance(value, SourceRef):
        return {"kind": value.kind, "identifier": value.identifier}
    if is_dataclass(value):
        return {item.name: _as_jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {
            str(key): _as_jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_as_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted((_as_jsonable(item) for item in value))
    if hasattr(value, "__dict__") and (not isinstance(value, type)):
        return {key: _as_jsonable(item) for key, item in vars(value).items()}
    return value


def _stable_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(
        _as_jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _refs(value: Iterable[SourceRef]) -> tuple[SourceRef, ...]:
    refs = tuple(value)
    if not refs or any(
        (not isinstance(item, SourceRef) or not item.kind or (not item.identifier) for item in refs)
    ):
        raise ValueError("provenance must contain at least one non-empty SourceRef")
    return refs


def _bounded_uncertainty(value: float) -> float:
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError("uncertainty must be between 0 and 1")
    return value


@dataclass(frozen=True, slots=True)
class ProblemFact:
    """One task interpretation with explicit epistemic status."""

    value: str | None
    status: InterpretationStatus = "explicit"
    provenance: tuple[SourceRef, ...] = ()
    uncertainty: float = 0.0
    note: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"explicit", "inferred", "unknown", "conflicting"}:
            raise ValueError(f"unsupported interpretation status: {self.status!r}")
        if self.status == "unknown" and self.value not in (None, ""):
            raise ValueError("unknown facts must not carry a resolved value")
        if self.status != "unknown" and self.value in (None, ""):
            raise ValueError("resolved facts require a value")
        _bounded_uncertainty(self.uncertainty)
        object.__setattr__(self, "provenance", _refs(self.provenance))


@dataclass(frozen=True, slots=True)
class ProblemModel:
    problem_id: str
    public_ref: SourceRef
    givens: tuple[ProblemFact, ...] = ()
    target: ProblemFact | None = None
    objective: tuple[ProblemFact, ...] = ()
    constraints: tuple[ProblemFact, ...] = ()
    domain: tuple[ProblemFact, ...] = ()
    quantifiers: tuple[ProblemFact, ...] = ()
    assumptions: tuple[ProblemFact, ...] = ()
    parse_status: ParseStatus = "parsed"
    uncertainty: float = 0.0
    provenance: tuple[SourceRef, ...] = ()
    version: str = "problem_model_v1"
    revision: int = 1

    def __post_init__(self) -> None:
        if not self.problem_id.strip():
            raise ValueError("problem_id is required")
        if not isinstance(self.public_ref, SourceRef):
            raise TypeError("public_ref must be a SourceRef")
        if self.parse_status not in {"parsed", "partial", "ambiguous", "conflicting", "unparsed"}:
            raise ValueError(f"unsupported parse status: {self.parse_status!r}")
        if self.revision < 1:
            raise ValueError("problem revision must be positive")
        _bounded_uncertainty(self.uncertainty)
        object.__setattr__(self, "provenance", _refs(self.provenance or (self.public_ref,)))
        for name in ("givens", "objective", "constraints", "domain", "quantifiers", "assumptions"):
            facts = tuple(getattr(self, name))
            if any((not isinstance(item, ProblemFact) for item in facts)):
                raise TypeError(f"{name} must contain ProblemFact values")
            object.__setattr__(self, name, facts)
        if self.target is not None and (not isinstance(self.target, ProblemFact)):
            raise TypeError("target must be a ProblemFact or None")
        facts = (
            *self.givens,
            *self.objective,
            *self.constraints,
            *self.domain,
            *self.quantifiers,
            *self.assumptions,
            *((self.target,) if self.target else ()),
        )
        inferred_uncertainty = max((item.uncertainty for item in facts), default=0.0)
        object.__setattr__(self, "uncertainty", max(self.uncertainty, inferred_uncertainty))

    @property
    def model_id(self) -> str:
        return self.problem_id

    @property
    def question_ref(self) -> SourceRef:
        """The original question identity; distinct from ``model_ref``."""
        return self.public_ref

    @property
    def model_ref(self) -> SourceRef:
        return SourceRef(
            "problem_model",
            _stable_id(
                "model",
                {
                    "problem_id": self.problem_id,
                    "question_ref": self.public_ref,
                    "givens": self.givens,
                    "target": self.target,
                    "objective": self.objective,
                    "constraints": self.constraints,
                    "domain": self.domain,
                    "quantifiers": self.quantifiers,
                    "assumptions": self.assumptions,
                    "parse_status": self.parse_status,
                    "uncertainty": self.uncertainty,
                    "provenance": self.provenance,
                    "version": self.version,
                    "revision": self.revision,
                },
            ),
        )

    @property
    def has_unknowns(self) -> bool:
        return any((item.status == "unknown" for item in self._facts))

    @property
    def has_conflicts(self) -> bool:
        return any((item.status == "conflicting" for item in self._facts))

    @property
    def semantic_summary(self) -> dict[str, bool]:
        return {"has_unknowns": self.has_unknowns, "has_conflicts": self.has_conflicts}

    @property
    def _facts(self) -> tuple[ProblemFact, ...]:
        return (
            *self.givens,
            *self.objective,
            *self.constraints,
            *self.domain,
            *self.quantifiers,
            *self.assumptions,
            *((self.target,) if self.target else ()),
        )


@dataclass(frozen=True, slots=True)
class ToolEvidence:
    tool_name: str
    tool_version: str
    input_summary: str
    output_summary: str
    scope: str
    status: str
    duration_ms: float = 0.0
    artifact_refs: tuple[str, ...] = ()
    failure_type: str | None = None
    input_refs: tuple[str, ...] = ()
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        combined = f"{self.input_summary}\n{self.output_summary}".casefold()
        if any((marker in combined for marker in _PRIVATE_REASONING_MARKERS)):
            raise ValueError("private reasoning is not ToolEvidence")
        if not self.tool_name.strip() or not self.tool_version.strip() or (not self.scope.strip()):
            raise ValueError("tool name, version, and scope are required")
        if self.duration_ms < 0:
            raise ValueError("duration_ms cannot be negative")
        if self.status in {
            "failed",
            "timeout",
            "unsupported",
            "not_checkable",
            "invalid_input",
        } and (not self.failure_type):
            object.__setattr__(self, "failure_type", self.status)
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        object.__setattr__(self, "input_refs", tuple(self.input_refs))
        if self.evidence_id is None:
            object.__setattr__(
                self,
                "evidence_id",
                _stable_id(
                    "evidence",
                    {
                        "tool_name": self.tool_name,
                        "tool_version": self.tool_version,
                        "input_summary": self.input_summary,
                        "output_summary": self.output_summary,
                        "scope": self.scope,
                        "status": self.status,
                        "artifact_refs": self.artifact_refs,
                        "input_refs": self.input_refs,
                        "failure_type": self.failure_type,
                    },
                ),
            )


@dataclass(frozen=True, slots=True)
class MathArtifact:
    statement: str
    role: str
    claim_kind: str = "derived_equation"
    normalized_form: str | None = None
    provenance: tuple[SourceRef, ...] = ()
    dependencies: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    verification_status: VerificationStatus = "not_checkable"
    verification_scope: str = ""
    tool_evidence_refs: tuple[str, ...] = ()
    uncertainty: float = 0.0
    workspace_revision: int = 1
    artifact_id: str | None = None

    def __post_init__(self) -> None:
        if not self.statement.strip() or not self.role.strip():
            raise ValueError("artifact statement and role are required")
        if self.verification_status not in {
            "verified",
            "qualified",
            "conditional",
            "conditional_equation",
            "not_checkable",
            "refuted",
            "unresolved_conflict",
        }:
            raise ValueError(f"unsupported verification status: {self.verification_status!r}")
        if self.workspace_revision < 1:
            raise ValueError("workspace revision must be positive")
        if self.verification_status != "not_checkable" and (not self.verification_scope.strip()):
            raise ValueError("non-default verification status requires a scope")
        _bounded_uncertainty(self.uncertainty)
        object.__setattr__(self, "provenance", _refs(self.provenance))
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        object.__setattr__(self, "tool_evidence_refs", tuple(self.tool_evidence_refs))
        if self.normalized_form is None:
            from deeptutor.math_semantic.verification import normalize_display

            object.__setattr__(self, "normalized_form", normalize_display(self.statement))
        if self.artifact_id is None:
            object.__setattr__(
                self,
                "artifact_id",
                _stable_id(
                    "artifact",
                    {
                        "statement": self.statement,
                        "normalized_form": self.normalized_form,
                        "role": self.role,
                        "claim_kind": self.claim_kind,
                        "provenance": self.provenance,
                        "dependencies": self.dependencies,
                        "assumptions": self.assumptions,
                        "workspace_revision": self.workspace_revision,
                    },
                ),
            )


@dataclass(frozen=True, slots=True)
class SolutionPath:
    method: str
    artifact_refs: tuple[str, ...] = ()
    status: str = "candidate"
    completeness: str = "unknown"
    provenance: tuple[SourceRef, ...] = ()
    uncertainty: float = 0.0
    workspace_revision: int = 1
    path_id: str | None = None

    def __post_init__(self) -> None:
        if not self.method.strip():
            raise ValueError("path method is required")
        if self.workspace_revision < 1:
            raise ValueError("path workspace revision must be positive")
        _bounded_uncertainty(self.uncertainty)
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        object.__setattr__(self, "provenance", _refs(self.provenance))
        if self.path_id is None:
            object.__setattr__(
                self,
                "path_id",
                _stable_id(
                    "path",
                    {
                        "method": self.method,
                        "artifact_refs": self.artifact_refs,
                        "status": self.status,
                        "completeness": self.completeness,
                        "provenance": self.provenance,
                        "workspace_revision": self.workspace_revision,
                    },
                ),
            )


@dataclass(frozen=True, slots=True)
class DependencyRelation:
    source_artifact_refs: tuple[str, ...]
    target_artifact_ref: str
    relation_type: str
    provenance: tuple[SourceRef, ...]
    scope: str
    workspace_revision: int
    relation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.source_artifact_refs or not all(self.source_artifact_refs):
            raise ValueError("dependency relation requires source artifact refs")
        if not self.target_artifact_ref:
            raise ValueError("dependency relation requires target artifact ref")
        if self.relation_type not in _RELATION_TYPES:
            raise ValueError(f"unsupported dependency relation: {self.relation_type!r}")
        if not self.scope.strip() or self.workspace_revision < 1:
            raise ValueError("dependency scope and positive workspace revision are required")
        object.__setattr__(self, "source_artifact_refs", tuple(self.source_artifact_refs))
        object.__setattr__(self, "provenance", _refs(self.provenance))
        if self.relation_id is None:
            object.__setattr__(
                self,
                "relation_id",
                _stable_id(
                    "relation",
                    {
                        "source": self.source_artifact_refs,
                        "target": self.target_artifact_ref,
                        "type": self.relation_type,
                        "provenance": self.provenance,
                        "scope": self.scope,
                        "workspace_revision": self.workspace_revision,
                    },
                ),
            )


@dataclass(frozen=True, slots=True)
class MathWorkspace:
    """Thin, independently addressable workspace header; payloads live elsewhere."""

    workspace_id: str
    problem_model_ref: SourceRef
    revision: int = 1
    artifact_refs: tuple[str, ...] = ()
    solution_path_refs: tuple[str, ...] = ()
    dependency_relation_refs: tuple[str, ...] = ()
    tool_evidence_refs: tuple[str, ...] = ()
    status: str = "open"
    version: str = "math_workspace_v1"

    def __post_init__(self) -> None:
        if not self.workspace_id.strip() or not isinstance(self.problem_model_ref, SourceRef):
            raise ValueError("workspace identity and problem_model_ref are required")
        if self.problem_model_ref.kind != "problem_model":
            raise ValueError("workspace must bind a problem_model identity, not a question ref")
        if self.revision < 1:
            raise ValueError("workspace revision must be positive")
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        object.__setattr__(self, "solution_path_refs", tuple(self.solution_path_refs))
        object.__setattr__(self, "dependency_relation_refs", tuple(self.dependency_relation_refs))
        object.__setattr__(self, "tool_evidence_refs", tuple(self.tool_evidence_refs))

    @property
    def problem_ref(self) -> SourceRef:
        return self.problem_model_ref

    @property
    def path_refs(self) -> tuple[str, ...]:
        return self.solution_path_refs


class DependencyGraph:
    """Mathematical relation graph with explicit closure failure states."""

    def __init__(
        self,
        *,
        workspace_revision: int,
        artifacts: Iterable[MathArtifact] = (),
        allow_historical: bool = False,
        workspace_ref: SourceRef | None = None,
        paths: Iterable[SolutionPath] = (),
    ) -> None:
        if workspace_revision < 1:
            raise ValueError("graph workspace revision must be positive")
        if workspace_ref is not None:
            if (
                not isinstance(workspace_ref, SourceRef)
                or workspace_ref.kind != "math_workspace"
                or (not workspace_ref.identifier.strip())
            ):
                raise ValueError("graph workspace_ref must be a math_workspace SourceRef")
        self.workspace_revision = workspace_revision
        self.workspace_ref = workspace_ref
        self.allow_historical = allow_historical
        self.artifacts = {item.artifact_id: item for item in artifacts}
        self.relations: dict[str, DependencyRelation] = {}
        self.paths = {item.path_id: item for item in paths}

    def add_artifact(self, artifact: MathArtifact) -> None:
        self.artifacts[artifact.artifact_id] = artifact

    def add_relation(self, relation: DependencyRelation) -> None:
        if relation.workspace_revision != self.workspace_revision:
            raise ValueError("dependency relation revision does not match graph revision")
        self.relations[cast(str, relation.relation_id)] = relation

    def dependency_status(self, artifact_ref: str, *, path_ref: str | None = None) -> str:
        """Structural closure, optionally within an explicitly supplied authored path.

        Membership scopes derivation supports, never mandatory dependencies or
        conflicts. This does not prove mathematics or learner completion. With
        no path, the existing global AND behavior is unchanged.
        """
        path = self.paths.get(path_ref) if path_ref is not None else None
        if path_ref is not None and path is None:
            return "missing_dependency"
        if path is not None and path.workspace_revision != self.workspace_revision:
            return "revision_mismatch"
        members = set(path.artifact_refs) if path is not None else None
        visiting: set[str] = set()
        visited: set[str] = set()

        def walk(ref: str) -> str:
            if members is not None and ref not in members:
                return "missing_dependency"
            if ref in visiting:
                return "cycle_detected"
            artifact = self.artifacts.get(ref)
            if artifact is None:
                return "missing_dependency"
            if artifact.workspace_revision != self.workspace_revision and (
                not (
                    self.allow_historical and artifact.workspace_revision < self.workspace_revision
                )
            ):
                return "revision_mismatch"
            if ref in visited:
                return "complete"
            visiting.add(ref)
            dependency_refs = set(artifact.dependencies)
            has_support = applicable_support = False
            for relation in self.relations.values():
                if relation.target_artifact_ref == ref:
                    if relation.workspace_revision != self.workspace_revision and (
                        not (
                            self.allow_historical
                            and relation.workspace_revision < self.workspace_revision
                        )
                    ):
                        return "revision_mismatch"
                    if relation.relation_type == "contradicts":
                        return "conflicting_relation"
                    if members is not None and relation.relation_type in {
                        "derived_from",
                        "supports",
                    }:
                        has_support = True
                        sources = set(relation.source_artifact_refs)
                        if not sources <= members:
                            if not any(
                                (
                                    other.workspace_revision == self.workspace_revision
                                    and {ref, *sources} <= set(other.artifact_refs)
                                    for other in self.paths.values()
                                )
                            ):
                                return "missing_dependency"
                            continue
                        applicable_support = True
                    if relation.relation_type in {"depends_on", "derived_from", "supports"}:
                        dependency_refs.update(relation.source_artifact_refs)
            if has_support and (not applicable_support):
                return "missing_dependency"
            for dependency in dependency_refs:
                result = walk(dependency)
                if result != "complete":
                    return result
            visiting.remove(ref)
            visited.add(ref)
            return "complete"

        return walk(artifact_ref)
