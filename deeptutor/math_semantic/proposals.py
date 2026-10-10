"""One bounded extraction proposal; provider labels never grant authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Mapping, Protocol

from deeptutor.math_semantic.claims import EvidenceSpan

METHODS = frozenset(
    {
        "completing_square",
        "factorization",
        "substitution",
        "algebraic_transformation",
        "unspecified",
    }
)


@dataclass(frozen=True, slots=True)
class ProviderEvidence:
    """Provider-facing evidence: quote is authoritative; offsets are local data."""

    quote: str
    occurrence: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.quote, str) or not self.quote or len(self.quote) > 512:
            raise ValueError("provider evidence quote must be bounded")
        if self.occurrence is not None and (
            type(self.occurrence) is not int or self.occurrence < 0
        ):
            raise ValueError("evidence occurrence must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ExtractedClaim:
    evidence: ProviderEvidence | EvidenceSpan
    claim_type: str = "equation"
    parse_status: str = "parsed"
    candidate_artifact_refs: tuple[str, ...] = ()
    uncertainty: float | None = None


@dataclass(frozen=True, slots=True)
class NovelPathProposal:
    claim_indices: tuple[int, ...]
    method: str
    dependency_artifact_refs: tuple[str, ...] = ()
    candidate_id: str | None = None


@dataclass(frozen=True, slots=True)
class AlignmentProposal:
    claims: tuple[ExtractedClaim, ...] = ()
    novel_paths: tuple[NovelPathProposal, ...] = ()
    interaction_type: str = "answer"

    @classmethod
    def from_value(
        cls, value: object, *, max_output_chars: int = 12000, max_output_bytes: int = 32000
    ) -> "AlignmentProposal":
        if isinstance(value, cls):
            value = asdict(value)
        if not isinstance(value, Mapping) or set(value) - {
            "claims",
            "novel_paths",
            "interaction_type",
        }:
            raise ValueError("alignment proposal contains unknown fields")
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(serialized) > max_output_chars or len(serialized.encode("utf-8")) > max_output_bytes:
            raise ValueError("alignment proposal exceeds output bound")
        claims = []
        for item in value.get("claims", ()):
            if not isinstance(item, Mapping) or set(item) - {
                "evidence",
                "claim_type",
                "parse_status",
                "candidate_artifact_refs",
                "uncertainty",
            }:
                raise ValueError("claim extraction contains unknown fields")
            span = item.get("evidence")
            evidence: EvidenceSpan | ProviderEvidence
            if not isinstance(span, Mapping):
                raise ValueError("claim requires evidence quote")
            if "quote" not in span or set(span) - {"quote", "occurrence", "start", "end"}:
                raise ValueError("claim evidence has unsupported fields")
            if "start" in span or "end" in span:
                if set(span) != {"start", "end", "quote"}:
                    raise ValueError("legacy evidence span must include start/end/quote")
                evidence = EvidenceSpan(**span)
            else:
                evidence = ProviderEvidence(span["quote"], span.get("occurrence"))
            refs = tuple(item.get("candidate_artifact_refs", ()))
            if len(refs) > 8 or any((not isinstance(ref, str) for ref in refs)):
                raise ValueError("candidate refs must be bounded strings")
            claim_type = item.get("claim_type", "equation")
            parse_status = item.get("parse_status", "parsed")
            uncertainty = item.get("uncertainty")
            if claim_type not in {"equation", "expression", "answer", "identity"}:
                raise ValueError("unsupported student claim type")
            if parse_status not in {"parsed", "ambiguous", "unparsed"}:
                raise ValueError("unsupported claim parse status")
            if uncertainty is not None and (
                type(uncertainty) not in {float, int} or not 0 <= uncertainty <= 1
            ):
                raise ValueError("invalid uncertainty")
            claims.append(ExtractedClaim(evidence, claim_type, parse_status, refs, uncertainty))
        paths = []
        for item in value.get("novel_paths", ()):
            if not isinstance(item, Mapping) or set(item) - {
                "claim_indices",
                "method",
                "dependency_artifact_refs",
                "candidate_id",
            }:
                raise ValueError("path proposal contains unknown fields")
            indices = tuple(item.get("claim_indices", ()))
            refs = tuple(item.get("dependency_artifact_refs", ()))
            if (
                item.get("method") not in METHODS
                or not indices
                or len(indices) > 8
                or (len(set(indices)) != len(indices))
            ):
                raise ValueError("invalid bounded path proposal")
            if any((type(index) is not int or not 0 <= index < len(claims) for index in indices)):
                raise ValueError("path references unknown student claim")
            if len(refs) > 8 or any((not isinstance(ref, str) for ref in refs)):
                raise ValueError("invalid dependency refs")
            candidate_id = item.get("candidate_id")
            if candidate_id is not None and (
                not isinstance(candidate_id, str)
                or not candidate_id.isidentifier()
                or len(candidate_id) > 32
            ):
                raise ValueError("candidate id must be a bounded identifier")
            paths.append(NovelPathProposal(indices, item["method"], refs, candidate_id))
        interaction = value.get("interaction_type", "answer")
        if interaction not in {"answer", "question", "clarification", "unclear"}:
            raise ValueError("invalid interaction type")
        if len(claims) > 8 or len(paths) > 2:
            raise ValueError("alignment proposal exceeds item bounds")
        if interaction in {"question", "clarification"} and claims:
            raise ValueError("questions must not be represented as asserted math claims")
        return cls(tuple(claims), tuple(paths), interaction)


def resolve_evidence(text: str, evidence: ProviderEvidence | EvidenceSpan) -> EvidenceSpan:
    """Exact substring resolver. Occurrence is zero-based, including overlaps."""
    if isinstance(evidence, EvidenceSpan):
        if evidence.end > len(text) or text[evidence.start : evidence.end] != evidence.quote:
            raise ValueError("student evidence span does not match source response")
        return evidence
    starts, position = ([], 0)
    while (found := text.find(evidence.quote, position)) >= 0:
        starts.append(found)
        position = found + 1
    if not starts:
        raise ValueError("student evidence quote does not match source response")
    if len(starts) > 1 and evidence.occurrence is None:
        raise ValueError("ambiguous duplicate evidence quote requires occurrence")
    occurrence = evidence.occurrence if evidence.occurrence is not None else 0
    if occurrence >= len(starts):
        raise ValueError("evidence occurrence is out of range")
    start = starts[occurrence]
    return EvidenceSpan(start, start + len(evidence.quote), evidence.quote)


@dataclass(frozen=True, slots=True)
class ArtifactSummary:
    artifact_id: str
    statement: str
    normalized_form: str
    role: str
    verification_status: str
    verification_scope: str


@dataclass(frozen=True, slots=True)
class PathSummary:
    path_id: str
    method: str
    artifact_refs: tuple[str, ...]


EXTRACTION_REQUEST_GUIDANCE = (
    "interaction_type describes the presence of the student's own current mathematical "
    "assertion, not a question mark, certainty or mathematical correctness. If claims "
    "is nonempty, use answer, including a submitted equality hedged with uncertainty "
    "or followed by a request to check or explain it. Preserve that assertion; do not "
    "drop claims to make question or clarification valid. question and clarification "
    "require empty claims. A formula only quoted from someone else, copied as problem "
    "context, or mentioned as the subject of a question is not an asserted student "
    "claim. In a mixed response, extract only the student's own exact assertion spans. "
    "Do not decide truth, grade, solve, or invent evidence. Examples describe speech "
    "acts only and never supply evidence for the actual response_text: "
    "'My submitted equality is p+1=q. I am unsure; can you check it?' has answer and "
    "one equation claim quoting p+1=q. 'The worksheet says p+1=q; what does it mean?' "
    "has question and empty claims. 'The worksheet says p+1=q. My line is p-1=r; "
    "please check my line.' has answer and only one claim quoting p-1=r. "
    "Return the existing AlignmentProposal object; this request guidance is not a "
    "response field and does not relax its schema."
)


@dataclass(frozen=True, slots=True)
class AlignmentProjection:
    response_text: str
    workspace_id: str
    workspace_revision: int
    target: str | None
    artifacts: tuple[ArtifactSummary, ...]
    paths: tuple[PathSummary, ...]
    dependency_edges: tuple[tuple[str, str], ...]
    projected_refs: tuple[str, ...]
    extraction_guidance: str = EXTRACTION_REQUEST_GUIDANCE


class ResponseAlignmentProvider(Protocol):
    provider_id: str
    model_config_digest: str

    def propose(self, projection: AlignmentProjection) -> object:
        """Extract exact student spans and propose references, never grade or teach."""
