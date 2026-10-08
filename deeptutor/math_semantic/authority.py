from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
from typing import Mapping, Self

from .refs import SourceRef

ORIENTATION_SUPPORT_MECHANISM = "non_mathematical_orientation_v1"
ORIENTATION_SUPPORT_SCOPE = "no_task_math_content"
MATH_SUPPLY_KINDS = (
    "chosen_operation",
    "justification",
    "operation_options",
    "orientation",
    "result",
)


def _sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any((char not in "0123456789abcdef" for char in value))
    ):
        raise ValueError(f"{label} must be an exact SHA-256")
    return value


def math_content_digest(artifact: object) -> str:
    """Hash the entire pinned content body; hashing does not verify its truth."""
    if not is_dataclass(artifact) or isinstance(artifact, type):
        raise ValueError("math content digest requires a complete dataclass content body")
    payload = json.dumps(
        asdict(artifact), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_ref(value: object, label: str) -> SourceRef:
    if (
        not isinstance(value, SourceRef)
        or not isinstance(value.kind, str)
        or (not value.kind.strip())
        or (not isinstance(value.identifier, str))
        or (not value.identifier.strip())
    ):
        raise ValueError(f"{label} must be an explicit source ref")
    return value


def _ref_payload(ref: SourceRef | None) -> dict[str, str] | None:
    return None if ref is None else {"kind": ref.kind, "identifier": ref.identifier}


def _ref_from_value(value: object, label: str) -> SourceRef | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"kind", "identifier"}:
        raise ValueError(f"{label} fields are not exact")
    return _source_ref(SourceRef(value["kind"], value["identifier"]), label)


@dataclass(frozen=True, slots=True)
class MathSemanticGrant:
    """One proposed target/act/content/support relation, never a cross product.

    A digest or a named mechanism does not prove support. Adoption must match
    the whole relation against its trusted, revision-pinned resolver bindings.
    ``content_digest`` binds the canonical content body, not its wording alone.
    """

    target_artifact_ref: str
    act_kind: str
    content_ref: SourceRef | None
    content_digest: str | None
    support_ref: SourceRef | None
    support_mechanism: str
    support_scope: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.target_artifact_ref, str)
            or not self.target_artifact_ref.strip()
            or self.act_kind not in MATH_SUPPLY_KINDS
        ):
            raise ValueError("semantic grant requires a target and math-local act")
        if any(
            (
                not isinstance(value, str) or not value.strip()
                for value in (self.support_mechanism, self.support_scope)
            )
        ):
            raise ValueError("semantic grant requires a named support mechanism and scope")
        if self.act_kind == "orientation":
            if (
                self.content_ref is not None
                or self.content_digest is not None
                or self.support_ref is not None
                or (self.support_mechanism != ORIENTATION_SUPPORT_MECHANISM)
                or (self.support_scope != ORIENTATION_SUPPORT_SCOPE)
            ):
                raise ValueError("orientation grant must explicitly supply no task mathematics")
        else:
            content = _source_ref(self.content_ref, "semantic content")
            if content.kind != "math_artifact":
                raise ValueError("math-local semantic content must refer to a math artifact")
            _sha256(self.content_digest, "semantic content digest")
            _source_ref(self.support_ref, "semantic support")

    @classmethod
    def orientation(cls, target_artifact_ref: str) -> Self:
        return cls(
            target_artifact_ref,
            "orientation",
            None,
            None,
            None,
            ORIENTATION_SUPPORT_MECHANISM,
            ORIENTATION_SUPPORT_SCOPE,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "target_artifact_ref": self.target_artifact_ref,
            "act_kind": self.act_kind,
            "content_ref": _ref_payload(self.content_ref),
            "content_digest": self.content_digest,
            "support_ref": _ref_payload(self.support_ref),
            "support_mechanism": self.support_mechanism,
            "support_scope": self.support_scope,
        }

    @classmethod
    def from_value(cls, value: object) -> Self:
        if not isinstance(value, Mapping) or set(value) != {
            "target_artifact_ref",
            "act_kind",
            "content_ref",
            "content_digest",
            "support_ref",
            "support_mechanism",
            "support_scope",
        }:
            raise ValueError("semantic grant fields are not exact")
        return cls(
            target_artifact_ref=value["target_artifact_ref"],
            act_kind=value["act_kind"],
            content_ref=_ref_from_value(value["content_ref"], "semantic content"),
            content_digest=value["content_digest"],
            support_ref=_ref_from_value(value["support_ref"], "semantic support"),
            support_mechanism=value["support_mechanism"],
            support_scope=value["support_scope"],
        )

    def relation_key(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class MathContentSupportBinding(MathSemanticGrant):
    """Canonical relation supplied by a trusted authority resolver.

    Constructing this type is not a verification mechanism or a trust upgrade.
    Production callers must obtain these bindings from the pinned audit domain,
    not from a Planner, Tutor, observer, or arbitrary caller payload.
    """

    def as_grant(self) -> MathSemanticGrant:
        return MathSemanticGrant.from_value(self.to_dict())
