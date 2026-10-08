from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from typing import cast

from .claims import ResponseAlignment
from .refs import LearnerRef, QuestionRef, SourceRef
from .trajectory_types import (
    AlignmentProjection,
    ArtifactProjection,
    MethodConfirmation,
    TrajectoryProjection,
)
from .workspace import MathWorkspaceSnapshot


def build_artifact_projections(snapshot: MathWorkspaceSnapshot) -> tuple[ArtifactProjection, ...]:
    """One canonical projection shared by construction and durable validation."""
    return tuple(
        (
            ArtifactProjection(
                artifact_ref=cast(str, item.artifact_id),
                workspace_id=snapshot.workspace.workspace_id,
                workspace_revision=snapshot.workspace.revision,
                role=item.role,
                statement=item.statement,
                verification_status=item.verification_status,
                verification_scope=item.verification_scope,
                dependencies=tuple(item.dependencies),
            )
            for item in snapshot.artifacts
        )
    )


def build_alignment_projection(alignment: ResponseAlignment) -> AlignmentProjection:
    return AlignmentProjection(
        alignment_ref=SourceRef("response_alignment", alignment.alignment_id),
        workspace_ref=alignment.math_workspace_ref,
        source_workspace_revision=alignment.workspace_revision,
        output_workspace_revision=alignment.output_workspace_revision,
        matched_artifact_refs=tuple(alignment.matched_artifact_refs),
        contradicted_artifact_refs=tuple(alignment.contradicted_artifact_refs),
        active_path_refs=tuple(alignment.active_path_refs),
        divergence_artifact_refs=tuple(
            dict.fromkeys(
                (ref for item in alignment.divergence for ref in item.relevant_artifact_refs)
            )
        ),
        unshown_artifact_refs=tuple((item.artifact_ref for item in alignment.unshown_steps)),
        learner_evidence_refs=tuple(
            (SourceRef("student_math_claim", item.claim_id) for item in alignment.claims)
        ),
        status=alignment.status,
        uncertainty=alignment.uncertainty,
    )


def derive_trajectory(
    snapshot: MathWorkspaceSnapshot,
    authored: MathWorkspaceSnapshot,
    alignments: tuple[ResponseAlignment | None, ...],
    *,
    cutoff_response_ref: SourceRef,
    cutoff_turn: int,
    basis_refs: tuple[SourceRef, ...],
    learner: LearnerRef | None = None,
    question_ref: QuestionRef | None = None,
    confirmations: tuple[MethodConfirmation, ...] = (),
) -> TrajectoryProjection:
    """Pure bounded interpretation; the caller authenticates the frozen source."""
    members = {cast(str, path.path_id): set(path.artifact_refs) for path in authored.paths}
    if not members:
        raise ValueError("protected multipath source requires at least one reviewed path")
    shared = set.intersection(*members.values())
    compatible = set(members)
    observed = unknown = contradicted = novel = False
    active = {
        item.artifact_id
        for item in snapshot.artifacts
        if item.verification_status not in {"refuted", "unresolved_conflict"}
    } - set(dict(snapshot.superseded_by))
    admitted: set[str] = set()
    novel_refs: set[str] = set()
    confirmation, pending, prefix = (None, False, [])
    for turn, alignment in enumerate(alignments, 1):
        if (
            pending
            and confirmation is not None
            and (confirmation.state == "resolved")
            and (turn > cast(int, confirmation.resolved_after_turn))
        ):
            compatible, pending = ({cast(str, confirmation.chosen_path_ref)}, False)
            prefix.append(SourceRef("method_confirmation", confirmation.confirmation_id))
        previous, turn_choices = (set(compatible), set(members))
        if alignment is None or alignment.uncertainty not in (None, 0):
            unknown = True
            continue
        prefix.append(SourceRef("response_alignment", alignment.alignment_id))
        admitted.update(alignment.validated_artifact_refs)
        for claim in alignment.claims:
            if claim.parse_status != "parsed" or claim.uncertainty not in (None, 0):
                unknown = True
                continue
            relations = tuple(
                (item for item in alignment.relations if item.student_claim_ref == claim.claim_id)
            )
            positive = {
                item.artifact_ref
                for item in relations
                if item.relation_type in {"matches", "equivalent_to"}
                and item.artifact_ref
                in {*alignment.projected_refs, *alignment.validated_artifact_refs}
                and (item.artifact_ref in active)
            }
            choices = {path for path, refs in members.items() if refs & positive}
            local_novel = {
                ref
                for candidate in alignment.novel_candidates
                if candidate.status == "validated"
                and claim.claim_id in candidate.student_claim_refs
                for ref in candidate.validated_artifact_refs
                if ref in admitted
            }
            if choices:
                observed = True
                turn_choices.intersection_update(choices)
                if not pending:
                    compatible.intersection_update(choices)
            elif positive & admitted or local_novel:
                novel = True
                novel_refs.update(positive & admitted | local_novel)
            elif any((item.relation_type == "contradicts" for item in relations)):
                contradicted = True
            else:
                unknown = True
        if (
            not pending
            and len(previous) == len(turn_choices) == 1
            and (not previous & turn_choices)
        ):
            pending, compatible = (True, previous)
            if learner is not None and question_ref is not None:
                issuing_basis = (
                    *prefix,
                    SourceRef(
                        "workspace_revision",
                        f"{snapshot.workspace.workspace_id}@{alignment.output_workspace_revision}",
                    ),
                )
                paths = (next(iter(previous)), next(iter(turn_choices)))
                identity = (
                    snapshot.workspace.workspace_id,
                    learner,
                    question_ref,
                    turn,
                    issuing_basis,
                    paths,
                )
                identifier = hashlib.sha256(json.dumps(identity, default=str).encode()).hexdigest()
                issued = MethodConfirmation(
                    identifier,
                    snapshot.workspace_ref,
                    learner,
                    question_ref,
                    turn,
                    issuing_basis,
                    tuple(((f"{identifier}:{i}", path) for i, path in enumerate(paths))),
                )
                confirmation = next(
                    (item for item in confirmations if item.confirmation_id == identifier), issued
                )
                if (
                    replace(
                        confirmation,
                        state="pending",
                        chosen_path_ref=None,
                        resolved_after_turn=None,
                    )
                    != issued
                ):
                    raise ValueError("method confirmation issuing basis mismatch")
    if pending:
        status = "METHOD_CONFIRMATION_REQUIRED"
    elif novel or not compatible:
        status = "UNREPRESENTED"
    elif unknown or (not observed and (not contradicted)):
        status = "UNKNOWN"
    elif contradicted:
        status = "CONTRADICTED"
    else:
        status = "SUPPORTED" if len(compatible) == 1 else "AMBIGUOUS"
    safe = set.intersection(*(members[path] for path in compatible)) if compatible else shared
    if pending:
        safe, novel_refs = (shared, set())
    return TrajectoryProjection(
        cutoff_response_ref,
        cutoff_turn,
        tuple(dict.fromkeys(basis_refs)),
        authored.problem_model.public_ref,
        tuple(sorted(members)),
        tuple(sorted(compatible)),
        tuple(sorted((safe | novel_refs) & active)),
        status,
        method_confirmation=replace(
            confirmation, state="pending", chosen_path_ref=None, resolved_after_turn=None
        )
        if pending and confirmation is not None
        else confirmation,
    )
