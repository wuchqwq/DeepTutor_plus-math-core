from __future__ import annotations

from dataclasses import asdict
import json

from .claims import (
    ClaimRelation,
    EvidenceSpan,
    NovelMathCandidate,
    PathDivergence,
    ResponseAlignment,
    StudentMathClaim,
    UnshownStep,
)
from .contracts import ToolEvidence
from .refs import SourceRef


def _payload(value: ResponseAlignment) -> str:
    return json.dumps(asdict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(payload: str) -> ResponseAlignment:
    data = json.loads(payload)
    for field in ("student_response_ref", "math_workspace_ref"):
        data[field] = SourceRef(**data[field])
    data["provenance"] = tuple((SourceRef(**item) for item in data["provenance"]))
    data["claims"] = tuple(
        (
            StudentMathClaim(
                **{
                    **item,
                    "student_response_ref": SourceRef(**item["student_response_ref"]),
                    "evidence": EvidenceSpan(**item["evidence"]),
                }
            )
            for item in data["claims"]
        )
    )
    data["relations"] = tuple(
        (
            ClaimRelation(**{**item, "tool_evidence_refs": tuple(item["tool_evidence_refs"])})
            for item in data["relations"]
        )
    )
    data["divergence"] = tuple(
        (
            PathDivergence(
                **{**item, "relevant_artifact_refs": tuple(item["relevant_artifact_refs"])}
            )
            for item in data["divergence"]
        )
    )
    data["unshown_steps"] = tuple((UnshownStep(**item) for item in data["unshown_steps"]))
    data["novel_candidates"] = tuple(
        (
            NovelMathCandidate(
                tuple(item["student_claim_refs"]),
                item["method"],
                tuple(item["dependency_artifact_refs"]),
                item.get("candidate_id"),
                tuple(item.get("validated_artifact_refs", ())),
                tuple(item.get("validation_evidence_refs", ())),
                item.get("candidate_path_ref"),
                item.get("status", "unvalidated"),
            )
            for item in data["novel_candidates"]
        )
    )
    data["math_evidence"] = tuple((ToolEvidence(**item) for item in data["math_evidence"]))
    for field in (
        "matched_artifact_refs",
        "contradicted_artifact_refs",
        "active_path_refs",
        "novel_claim_refs",
        "novel_path_refs",
        "validated_artifact_refs",
        "validation_evidence_refs",
        "projected_refs",
    ):
        data[field] = tuple(data[field])
    return ResponseAlignment(**data)
