from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import json
from math import isfinite
import re
from typing import cast

from deeptutor.math_semantic.claims import (
    ClaimRelation,
    ClaimType,
    NovelMathCandidate,
    PathDivergence,
    RelationType,
    ResponseAlignment,
    StudentMathClaim,
    UnshownStep,
)
from deeptutor.math_semantic.proposals import (
    AlignmentProjection,
    AlignmentProposal,
    ArtifactSummary,
    PathSummary,
    resolve_evidence,
)
from deeptutor.math_semantic.refs import SourceRef
from deeptutor.math_semantic.student_proposals import (
    StudentMathProposal,
    validate_student_proposals,
)
from deeptutor.math_semantic.workspace import MathWorkspaceSnapshot

from .accepted import AcceptedSubmission
from .contracts import MathArtifact, SolutionPath, ToolEvidence


@dataclass(frozen=True, slots=True)
class AlignmentMutation:
    alignment: ResponseAlignment
    artifacts: tuple[MathArtifact, ...]
    paths: tuple[SolutionPath, ...]
    evidence: tuple[ToolEvidence, ...]


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


class AlignmentEvaluator:
    @staticmethod
    def _normalize_claim(text: str) -> str:
        from deeptutor.math_semantic.verification import normalize_display

        return normalize_display(text)

    @staticmethod
    def _compare(
        claim: StudentMathClaim, artifact, *, answer_ref: str | None = None
    ) -> tuple[RelationType, str, str]:
        unresolved: tuple[RelationType, str, str] = ("unresolved", "no_safe_match", "unresolved")
        if claim.parse_status != "parsed":
            return unresolved
        student = claim.normalized_form
        value = AlignmentEvaluator._answer_value(claim.evidence.quote)
        if claim.claim_type == "answer" and value is None and ("=" not in student):
            return unresolved
        if claim.claim_type == "answer" and value is not None:
            if artifact.artifact_id != answer_ref:
                return unresolved
            expected = AlignmentEvaluator._answer_value(artifact.statement, artifact=True)
            if expected is None:
                return unresolved
            from deeptutor.math_semantic.tools import MathToolRegistry

            registry = MathToolRegistry(max_calls=2)
            left, right = (registry.numeric_evaluate(value), registry.numeric_evaluate(expected))
            if (
                left.status != "succeeded"
                or right.status != "succeeded"
                or (not isfinite(left.value))
                or (not isfinite(right.value))
            ):
                return unresolved
            exact = tuple(
                (
                    Fraction(parts[0].strip())
                    / (Fraction(parts[1].strip()) if len(parts) == 2 else 1)
                    for parts in (value.split("/"), expected.split("/"))
                )
            )
            if exact[0] == exact[1]:
                relation: RelationType = "matches" if value == expected else "equivalent_to"
            else:
                relation = "contradicts"
            return (
                relation,
                "MathToolRegistry.numeric_evaluate+fractions.Fraction",
                "unique_projected_answer_value",
            )
        from deeptutor.math_semantic.verification import normalize_display

        forms = tuple(
            (
                re.sub("\\s*(<=|>=)\\s*", "\\1", normalize_display(text))
                for text in (student, artifact.normalized_form)
            )
        )
        if forms[0] == forms[1]:
            return ("matches", "normalized_display", "normalization")
        if claim.claim_type in {"equation", "answer"}:
            bounds = tuple(
                (AlignmentEvaluator._bounds(text) for text in (student, artifact.statement))
            )
            if all(bounds):
                (subject, asserted), (other, expected_bounds) = cast(
                    tuple[
                        tuple[str, dict[str, tuple[Fraction, bool]]],
                        tuple[str, dict[str, tuple[Fraction, bool]]],
                    ],
                    bounds,
                )
                if AlignmentEvaluator._content_equivalent(subject, other):
                    if asserted == expected_bounds:
                        return (
                            "equivalent_to",
                            "closed_numeric_bounds",
                            "same_subject_and_boundaries",
                        )
                    if (
                        len(asserted) == 1
                        and len(expected_bounds) == 2
                        and all((expected_bounds.get(k) == v for k, v in asserted.items()))
                    ):
                        return (
                            "partial_match",
                            "closed_numeric_bounds",
                            "one_asserted_boundary_only",
                        )
                return unresolved
        if AlignmentEvaluator._content_equivalent(
            student,
            artifact.statement,
            allow_residual=claim.claim_type in {"equation", "identity"}
            and artifact.role in {"given", "intermediate", "transformation"},
        ):
            return (
                "equivalent_to",
                "ResponseAlignmentService._content_equivalent",
                "content_correspondence",
            )
        if AlignmentEvaluator._positive_assignment_conflict(student, artifact.statement):
            return (
                "contradicts",
                "MathToolRegistry.numeric_evaluate",
                "same_lhs_distinct_numeric_rhs",
            )
        return ("unresolved", "no_safe_match", "unresolved")

    @staticmethod
    def _content_equivalent(student: str, artifact: str, *, allow_residual: bool = False) -> bool:
        """Preserve operands, or compare a bounded nonzero polynomial residual."""
        from deeptutor.math_semantic.tools import _safe_expression
        from deeptutor.math_semantic.verification import answers_equivalent

        try:
            texts = tuple((_safe_expression(text) for text in (student, artifact)))
        except ValueError:
            return False
        if set(re.findall("[A-Za-z_][A-Za-z0-9_]*", texts[0])) != set(
            re.findall("[A-Za-z_][A-Za-z0-9_]*", texts[1])
        ):
            return False
        left, right = (text.split("=") for text in texts)
        if (
            len(left) != len(right)
            or len(left) not in {1, 2}
            or any((not part.strip() or re.search("[<>!;,]", part) for part in (*left, *right)))
        ):
            return False

        def same(parts):
            return all(
                (a.strip() == b.strip() or answers_equivalent(a, b) for a, b in zip(left, parts))
            )

        if same(right) or (len(left) == 2 and same(tuple(reversed(right)))):
            return True
        if not allow_residual or len(left) != 2:
            return False
        import ast

        def unwrap(parts):
            if "0" in (p.strip() for p in parts):
                body = parts[1] if parts[0].strip() == "0" else parts[0]
                node = ast.parse(body.strip().replace("^", "**"), mode="eval").body
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
                    return tuple((ast.unparse(p) for p in (node.left, node.right)))
            return tuple(parts)

        try:
            unwrapped = (unwrap(left), unwrap(right))
        except (SyntaxError, ValueError, RecursionError):
            return False
        if unwrapped != (
            tuple(left),
            tuple(right),
        ) and AlignmentEvaluator._content_equivalent(
            "=".join(unwrapped[0]), "=".join(unwrapped[1])
        ):
            return True
        if len(set(re.findall("[A-Za-z_][A-Za-z0-9_]*", texts[0]))) < 2 or any(
            (
                "/" in text or re.search("[A-Za-z_]\\w*\\s*\\(|\\*\\*\\s*\\(?\\s*-", text)
                for text in texts
            )
        ):
            return False
        from deeptutor.math_semantic.verification import equation_residuals_correspond

        return equation_residuals_correspond(*texts)

    @staticmethod
    def _bounds(text: str) -> tuple[str, dict[str, tuple[Fraction, bool]]] | None:
        """Closed numeric endpoints on one explicit subject; no implication."""
        from deeptutor.math_semantic.tools import _safe_expression
        from deeptutor.math_semantic.verification import normalize_display

        text = normalize_display(text)
        if len(text) > 512:
            return None
        interval = re.fullmatch(
            "(.+?)\\s*(?:∈|\\bin\\b)\\s*([\\[(])\\s*([^,]+),\\s*([^,]+)\\s*([\\])])", text
        )
        if interval:
            subject, opening, low, high, closing = interval.groups()
            text = f"{low}{('<=' if opening == '[' else '<')}{subject}{('<=' if closing == ']' else '<')}{high}"
        subjects, bounds = ([], {})
        for clause in text.split(" and "):
            parts = re.split("(<=|>=|<|>)", clause)
            if len(parts) not in {3, 5}:
                return None
            for i in range(0, len(parts) - 2, 2):
                left, operator, right = (p.strip() for p in parts[i : i + 3])
                values = tuple((AlignmentEvaluator._answer_value(p) for p in (left, right)))
                if (values[0] is None) == (values[1] is None):
                    return None
                subject = right if values[0] is not None else left
                try:
                    subject = _safe_expression(subject)
                except ValueError:
                    return None
                if not re.search("[A-Za-z]", subject) or re.search("[=<>!;,]", subject):
                    return None
                value = next((v for v in values if v is not None))
                pieces = value.split("/")
                endpoint = Fraction(pieces[0].strip()) / (
                    Fraction(pieces[1].strip()) if len(pieces) == 2 else 1
                )
                lower = operator.startswith("<") == (values[0] is not None)
                key = "lower" if lower else "upper"
                if key in bounds:
                    return None
                bounds[key] = (endpoint, "=" in operator)
                subjects.append(subject)
        if not all((AlignmentEvaluator._content_equivalent(subjects[0], s) for s in subjects[1:])):
            return None
        if len(bounds) == 2:
            (low, lc), (high, hc) = (bounds["lower"], bounds["upper"])
            if low > high or (low == high and (not (lc and hc))):
                return None
        return (subjects[0], bounds)

    @staticmethod
    def _answer_value(text: str, *, artifact: bool = False) -> str | None:
        """Closed scalar grammar; never extract arbitrary numbers from prose."""
        from deeptutor.math_semantic.verification import normalize_display

        text = normalize_display(text)
        if artifact and "=" in text:
            parts = text.split("=")
            if len(parts) != 2 or not re.fullmatch(
                "(?:[A-Za-z][A-Za-z0-9_]*|[0-9]+(?:\\s*[+-]\\s*[0-9]+)+)", parts[0].strip()
            ):
                return None
            text = parts[1].strip()
        if len(text) > 64 or not re.fullmatch(
            "[+-]?(?:[0-9]+(?:\\s*/\\s*[+-]?[0-9]+)?|[0-9]+\\.[0-9]+|\\.[0-9]+)", text
        ):
            return None
        if "/" in text and int(text.split("/")[1]) == 0:
            return None
        return text

    @staticmethod
    def _positive_assignment_conflict(student: str, artifact: str) -> bool:
        if "=" not in student or "=" not in artifact:
            return False
        from deeptutor.math_semantic.verification import normalize_display

        student_lhs, student_rhs = (
            part.strip() for part in normalize_display(student).split("=", 1)
        )
        artifact_lhs, artifact_rhs = (
            part.strip() for part in normalize_display(artifact).split("=", 1)
        )
        student_lhs = re.sub("\\s*([+*/^()-])\\s*", "\\1", student_lhs)
        artifact_lhs = re.sub("\\s*([+*/^()-])\\s*", "\\1", artifact_lhs)
        if student_lhs != artifact_lhs:
            return False
        from deeptutor.math_semantic.tools import MathToolRegistry

        registry = MathToolRegistry(max_calls=2)
        left = registry.numeric_evaluate(student_rhs)
        right = registry.numeric_evaluate(artifact_rhs)
        return (
            left.status == "succeeded"
            and right.status == "succeeded"
            and (left.value != right.value)
        )

    @staticmethod
    def _active_paths(snapshot: MathWorkspaceSnapshot, matched: list[str]) -> tuple[str, ...]:
        return tuple(
            (
                cast(str, path.path_id)
                for path in snapshot.paths
                if set(matched) & set(path.artifact_refs)
            )
        )

    @staticmethod
    def _matched_range(refs: tuple[str, ...], matched: list[str]) -> tuple[int | None, int | None]:
        positions = [index for index, ref in enumerate(refs) if ref in matched]
        return (min(positions), max(positions)) if positions else (None, None)

    @staticmethod
    def _project(text: str, snapshot: MathWorkspaceSnapshot) -> AlignmentProjection:
        selected_paths = snapshot.paths[-4:]
        members = {ref for path in selected_paths for ref in path.artifact_refs}
        path_artifacts = tuple((a for a in snapshot.artifacts if a.artifact_id in members))
        if len(path_artifacts) <= 32:
            extras = tuple((a for a in snapshot.artifacts[-12:] if a.artifact_id not in members))
            remaining = 32 - len(path_artifacts)
            selected_artifacts = path_artifacts + (extras[-remaining:] if remaining else ())
        else:
            selected_artifacts = snapshot.artifacts[-32:]
        artifacts = tuple(
            (
                ArtifactSummary(
                    cast(str, a.artifact_id),
                    a.statement,
                    cast(str, a.normalized_form),
                    a.role,
                    a.verification_status,
                    a.verification_scope,
                )
                for a in selected_artifacts
            )
        )
        paths = tuple(
            (PathSummary(cast(str, p.path_id), p.method, p.artifact_refs) for p in selected_paths)
        )
        edges = tuple(
            (
                (r.target_artifact_ref, source)
                for r in snapshot.relations[-24:]
                for source in r.source_artifact_refs
            )
        )
        refs = (
            snapshot.workspace.problem_model_ref.identifier,
            *(cast(str, item.artifact_id) for item in artifacts),
            *(cast(str, item.path_id) for item in paths),
        )
        return AlignmentProjection(
            text,
            snapshot.workspace.workspace_id,
            snapshot.workspace.revision,
            snapshot.problem_model.target.value if snapshot.problem_model.target else None,
            artifacts,
            paths,
            edges,
            refs,
        )


def materialize_alignment(
    response: AcceptedSubmission,
    snapshot: MathWorkspaceSnapshot,
    proposal: AlignmentProposal,
    *,
    provider_id: str,
    config_digest: str,
) -> AlignmentMutation:
    proposal = AlignmentProposal.from_value(proposal)
    text = response.text_content()
    if text is None:
        raise ValueError("Phase 3 text alignment requires a text StudentResponse")
    if snapshot.workspace.problem_model_ref != snapshot.problem_model.model_ref:
        raise ValueError("workspace snapshot has an invalid ProblemModel binding")
    response_ref = SourceRef("student_response", response.response_id)
    workspace_ref = SourceRef("math_workspace", snapshot.workspace.workspace_id)
    projection = AlignmentEvaluator._project(text, snapshot)
    projected_artifacts = {item.artifact_id: item for item in projection.artifacts}
    answer_refs = tuple(
        (
            item.artifact_id
            for item in projection.artifacts
            if item.role in {"answer", "answer_candidate", "final_answer"}
        )
    )
    answer_ref = answer_refs[0] if len(answer_refs) == 1 else None
    input_digest = _digest(
        {
            "response": response_ref,
            "text": text,
            "workspace": workspace_ref,
            "revision": snapshot.workspace.revision,
            "projected_refs": projection.projected_refs,
            "provider": provider_id,
            "config": config_digest,
        }
    )
    alignment_id = "alignment_" + input_digest[:24]
    claims = []
    for index, item in enumerate(proposal.claims):
        evidence = resolve_evidence(text, item.evidence)
        normalized = AlignmentEvaluator._normalize_claim(evidence.quote)
        claims.append(
            StudentMathClaim(
                claim_id=f"student_claim_{input_digest[:12]}_{index}",
                student_response_ref=response_ref,
                evidence=evidence,
                normalized_form=normalized,
                claim_type=cast(ClaimType, item.claim_type),
                parse_status=item.parse_status,
                uncertainty=item.uncertainty,
            )
        )
    by_claim = {item.claim_id: item for item in claims}
    if any(
        (
            ref not in projected_artifacts
            for path in proposal.novel_paths
            for ref in path.dependency_artifact_refs
        )
    ):
        raise ValueError("provider referenced an unknown artifact or an unprojected artifact")
    relations: list[ClaimRelation] = []
    matched, contradicted, novel = ([], [], [])
    for index, item in enumerate(proposal.claims):
        claim = claims[index]
        if item.candidate_artifact_refs:
            for artifact_ref in item.candidate_artifact_refs:
                artifact = projected_artifacts.get(artifact_ref)
                if artifact is None:
                    raise ValueError(
                        "provider referenced an unknown artifact or an unprojected artifact"
                    )
                relation, mechanism, scope = AlignmentEvaluator._compare(
                    claim, artifact, answer_ref=answer_ref
                )
                relations.append(
                    ClaimRelation(claim.claim_id, artifact_ref, relation, mechanism, scope)
                )
                if relation in {"matches", "equivalent_to"}:
                    matched.append(artifact_ref)
                elif relation == "contradicts":
                    contradicted.append(artifact_ref)
        else:
            claim_relations = 0
            for artifact in projection.artifacts:
                relation, mechanism, scope = AlignmentEvaluator._compare(
                    claim, artifact, answer_ref=answer_ref
                )
                if relation in {"matches", "equivalent_to", "partial_match", "contradicts"}:
                    relations.append(
                        ClaimRelation(
                            claim.claim_id, artifact.artifact_id, relation, mechanism, scope
                        )
                    )
                    claim_relations += 1
                    if relation == "contradicts":
                        contradicted.append(artifact.artifact_id)
                    elif relation != "partial_match":
                        matched.append(artifact.artifact_id)
            if not claim_relations:
                novel.append(claim.claim_id)
    novelty = tuple(
        (
            NovelMathCandidate(
                tuple((claims[index].claim_id for index in path.claim_indices)),
                path.method,
                path.dependency_artifact_refs,
                path.candidate_id or f"candidate_{index}",
            )
            for index, path in enumerate(proposal.novel_paths)
        )
    )
    active_paths = AlignmentEvaluator._active_paths(snapshot, matched)
    unshown = tuple(
        (
            UnshownStep(path.path_id, artifact_ref)
            for path in snapshot.paths
            if path.path_id in active_paths
            for first, last in [AlignmentEvaluator._matched_range(path.artifact_refs, matched)]
            if first is not None and last is not None and (last > first)
            for artifact_ref in path.artifact_refs[first + 1 : last]
            if artifact_ref not in matched
        )
    )
    divergence = tuple(
        (
            PathDivergence(
                path.path_id,
                next((ref for ref in reversed(path.artifact_refs) if ref in matched), None),
                claims[index].claim_id,
                tuple(path.artifact_refs),
            )
            for path in snapshot.paths
            for candidate in novelty
            for index in [
                next(
                    (
                        i
                        for i, claim in enumerate(claims)
                        if claim.claim_id in candidate.student_claim_refs
                    ),
                    0,
                )
            ]
            if candidate.student_claim_refs and path.path_id in active_paths
        )
    )
    alignment = ResponseAlignment(
        alignment_id=alignment_id,
        student_response_ref=response_ref,
        math_workspace_ref=workspace_ref,
        workspace_revision=snapshot.workspace.revision,
        output_workspace_revision=snapshot.workspace.revision,
        claims=tuple(claims),
        relations=tuple(relations),
        matched_artifact_refs=tuple(dict.fromkeys(matched)),
        contradicted_artifact_refs=tuple(dict.fromkeys(contradicted)),
        active_path_refs=active_paths,
        divergence=divergence,
        unshown_steps=unshown,
        novel_candidates=novelty,
        novel_claim_refs=tuple(novel),
        novel_path_refs=(),
        validated_artifact_refs=(),
        validation_evidence_refs=(),
        projected_refs=projection.projected_refs,
        math_evidence=(),
        interaction_type=proposal.interaction_type,
        status="no_math_claim"
        if not claims
        else "unresolved"
        if contradicted
        else "partial"
        if any((r.relation_type == "partial_match" for r in relations))
        else "aligned"
        if matched
        else "unresolved",
        provenance=(response_ref, workspace_ref, snapshot.problem_model.model_ref),
    )
    validated_artifacts: tuple[MathArtifact, ...] = ()
    validation_evidence: tuple[ToolEvidence, ...] = ()
    candidate_paths: tuple[SolutionPath, ...] = ()
    candidate_records = []
    for candidate in novelty:
        member_proposals = tuple(
            (
                StudentMathProposal(
                    statement=claims[index].normalized_form,
                    student_claim_ref=SourceRef("student_math_claim", claims[index].claim_id),
                    student_response_ref=response_ref,
                    alignment_ref=SourceRef("response_alignment", alignment.alignment_id),
                    claim_kind="algebraic_identity"
                    if claims[index].claim_type == "identity"
                    else "derived_equation",
                    observed_dependency_refs=candidate.dependency_artifact_refs,
                    candidate_ref=SourceRef(
                        "novel_math_candidate", candidate.candidate_id or "candidate"
                    ),
                )
                for index in (
                    i
                    for i, claim in enumerate(claims)
                    if claim.claim_id in candidate.student_claim_refs
                )
            )
        )
        checked = validate_student_proposals(
            snapshot, member_proposals, source_text=text, method=candidate.method
        )
        if len(checked.accepted_artifacts) == len(member_proposals):
            validated_artifacts += checked.accepted_artifacts
            validation_evidence += checked.evidence
            candidate_paths += checked.candidate_paths
            candidate_records.append(
                replace(
                    candidate,
                    validated_artifact_refs=tuple(
                        (cast(str, item.artifact_id) for item in checked.accepted_artifacts)
                    ),
                    validation_evidence_refs=tuple(
                        (cast(str, item.evidence_id) for item in checked.evidence)
                    ),
                    candidate_path_ref=checked.candidate_paths[0].path_id,
                    status="validated",
                )
            )
        else:
            candidate_records.append(
                replace(
                    candidate,
                    validated_artifact_refs=tuple(
                        (cast(str, item.artifact_id) for item in checked.accepted_artifacts)
                    ),
                    validation_evidence_refs=tuple(
                        (cast(str, item.evidence_id) for item in checked.evidence)
                    ),
                    status="rejected",
                )
            )
    if novelty:
        alignment = replace(
            alignment,
            novel_candidates=tuple(candidate_records),
            validated_artifact_refs=tuple(
                (cast(str, item.artifact_id) for item in validated_artifacts)
            ),
            validation_evidence_refs=tuple(
                (cast(str, item.evidence_id) for item in validation_evidence)
            ),
            novel_path_refs=tuple((cast(str, item.path_id) for item in candidate_paths)),
            math_evidence=validation_evidence,
            output_workspace_revision=snapshot.workspace.revision + 1
            if validated_artifacts
            else snapshot.workspace.revision,
        )
    return AlignmentMutation(alignment, validated_artifacts, candidate_paths, validation_evidence)
