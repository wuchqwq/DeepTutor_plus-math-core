"""Transaction-local mathematical records, independent of any storage backend.

The host loads/saves this value inside its durable mutation authority. This
module owns no connection, commit, lease, session or acceptance lifecycle.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, replace
import json
from typing import Any, Protocol, TypeVar, cast

from .accepted import AcceptedSubmission, EpisodeIdentity
from .alignment import materialize_alignment
from .authority import MathSemanticGrant
from .ceiling import require_math_authority
from .claims import ResponseAlignment
from .codec import _decode, _payload
from .confirmation import resolve_confirmation
from .contracts import DependencyRelation, MathArtifact, SolutionPath, ToolEvidence
from .proposals import AlignmentProposal
from .reasoning import ReasoningStepProposal, materialize_reasoning
from .refs import SourceRef
from .trajectory import derive_trajectory
from .trajectory_types import MethodConfirmation, TrajectoryProjection
from .transformations import (
    SCOPE,
    VERSION,
    MaterializedTransformation,
    TransformationValidation,
    TypedTransformationOperation,
    _evaluate_transformation,
    _linear,
)
from .workspace import (
    DuplicateAttemptError,
    MathWorkspaceSnapshot,
    ReasoningAttempt,
    RevisionConflict,
    _digest,
    _snapshot_from,
    _snapshot_payload,
    append_snapshot,
)


@dataclass(frozen=True, slots=True)
class ReviewedSource:
    identity: EpisodeIdentity
    authored: MathWorkspaceSnapshot
    trajectory_version: str = "math_trajectory_v2"

    def __post_init__(self) -> None:
        if not self.identity.episode_id or not self.authored.paths:
            raise ValueError("reviewed source requires an explicit episode and authored paths")
        if self.identity.episode_id != self.authored.workspace.workspace_id:
            raise ValueError("reviewed workspace requires the explicit episode-scoped identity")
        model = self.authored.problem_model
        if (
            model.problem_id != self.identity.question_ref.question_id
            or model.revision != self.identity.question_ref.revision
        ):
            raise ValueError("reviewed question binding differs from the mathematical source")


Result = TypeVar("Result")


class ConfirmationScopeChanged(ValueError):
    """A pending choice must be invalidated before reporting revision drift."""


class MathMutationAuthority(Protocol):
    def __call__(self, mutation: Callable[[MathMutation], Result]) -> Awaitable[Result]: ...


async def run_math_operation(
    authority: MathMutationAuthority | None, mutation: Callable[[MathMutation], Result]
) -> Result:
    if authority is None:
        raise ValueError("mathematical mutation requires protected host commit authority")
    return await authority(mutation)


class MathMutation:
    """A host-owned transaction's math value. Returning it does not commit it."""

    def __init__(
        self,
        source: ReviewedSource,
        submission: AcceptedSubmission,
        prefix: tuple[AcceptedSubmission, ...],
        payload: str | None = None,
    ) -> None:
        self.source, self.submission, self.prefix = source, submission, prefix
        if payload is None:
            self._records: dict[str, Any] = {
                "source": asdict(source.identity),
                "trajectory_version": source.trajectory_version,
                "authored": _snapshot_payload(source.authored),
                "head": source.authored.workspace.revision,
                "snapshots": {
                    str(source.authored.workspace.revision): _snapshot_payload(source.authored)
                },
                "alignments": {},
                "confirmations": {},
                "transformations": {},
                "attempts": {},
            }
        else:
            self._records = json.loads(payload)
            if (
                self._records["trajectory_version"] != source.trajectory_version
                or self._records["source"] != asdict(source.identity)
                or _snapshot_from(json.dumps(self._records["authored"])) != source.authored
            ):
                raise ValueError("reviewed source or episode binding changed")

    def serialize(self) -> str:
        return json.dumps(self._records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def snapshot(self, revision: int | None = None) -> MathWorkspaceSnapshot:
        revision = self._records["head"] if revision is None else revision
        try:
            return _snapshot_from(json.dumps(self._records["snapshots"][str(revision)]))
        except KeyError as exc:
            raise ValueError("pinned mathematical revision is missing") from exc

    def append(
        self,
        *,
        expected_revision: int,
        artifacts: tuple[MathArtifact, ...] = (),
        evidence: tuple[ToolEvidence, ...] = (),
        relations: tuple[DependencyRelation, ...] = (),
        paths: tuple[SolutionPath, ...] = (),
        superseded_by: tuple[tuple[str, str], ...] = (),
        status: str | None = None,
    ) -> MathWorkspaceSnapshot:
        current = self.snapshot()
        if current.workspace.revision != expected_revision:
            raise RevisionConflict("mathematical workspace advanced")
        if not any((artifacts, evidence, relations, paths, superseded_by, status)):
            return current
        after = append_snapshot(
            current,
            artifacts=artifacts,
            evidence=evidence,
            relations=relations,
            paths=paths,
            superseded_by=superseded_by,
            status=status,
        )
        self._records["snapshots"][str(after.workspace.revision)] = _snapshot_payload(after)
        self._records["head"] = after.workspace.revision
        return after

    def align(
        self,
        proposal: AlignmentProposal,
        *,
        expected_revision: int,
        provider_id: str,
        config_digest: str,
        check_steps: bool = False,
    ) -> ResponseAlignment:
        slot = f"{self.submission.response_id}:{expected_revision}"
        request = _digest(
            {
                "proposal": asdict(AlignmentProposal.from_value(proposal)),
                "provider": provider_id,
                "config": config_digest,
                "submission": asdict(self.submission),
                "check_steps": check_steps,
            }
        )
        old = self._records["alignments"].get(slot)
        if old is not None and slot in self._records.get("alignment_inputs", {}):
            if self._records["alignment_inputs"][slot] != request:
                raise ValueError("immutable alignment input changed")
            alignment = _decode(old)
            self._check_step_evidence(alignment)
            return alignment
        snapshot = self.snapshot()
        if snapshot.workspace.revision != expected_revision:
            raise RevisionConflict("alignment input workspace revision is stale")
        mutation = materialize_alignment(
            self.submission,
            snapshot,
            proposal,
            provider_id=provider_id,
            config_digest=config_digest,
            check_steps=check_steps,
        )
        alignment = mutation.alignment
        old = self._records["alignments"].get(slot)
        if old is not None:
            if _decode(old) != alignment:
                raise ValueError("immutable alignment conflicts with a different result")
            return alignment
        if mutation.artifacts or mutation.evidence:
            self.append(
                expected_revision=expected_revision,
                artifacts=mutation.artifacts,
                evidence=mutation.evidence,
                paths=mutation.paths,
            )
        self._records["alignments"][slot] = _payload(alignment)
        if check_steps:
            self._records.setdefault("alignment_inputs", {})[slot] = request
        self._check_step_evidence(alignment)
        return alignment

    def _check_step_evidence(self, alignment: ResponseAlignment) -> None:
        from .validation import STEP_VERSION, step_basis

        before = self.snapshot(alignment.workspace_revision)
        after = self.snapshot(alignment.output_workspace_revision)
        proofs = {e.evidence_id: e for e in after.tool_evidence}
        for evidence in alignment.math_evidence:
            if evidence.tool_version != STEP_VERSION:
                continue
            fresh = replace(evidence, evidence_id=None)
            binding = json.loads(evidence.input_summary)
            claims = {c.claim_id: asdict(c) for c in alignment.claims}
            claim = binding["claim"]
            if (
                fresh.evidence_id != evidence.evidence_id
                or proofs.get(evidence.evidence_id) != evidence
                or binding["episode"] != self.source.identity.episode_id
                or binding["revision"] != alignment.workspace_revision
                or alignment.math_workspace_ref != before.workspace_ref
                or binding["math_basis"] != step_basis(before)
                or claims.get(claim["claim_id"]) != claim
            ):
                raise ValueError("foreign, stale or altered student step evidence")
            for ref in json.loads(evidence.output_summary)["tool_evidence_refs"]:
                proof = proofs.get(ref)
                if (
                    proof is None
                    or replace(proof, evidence_id=None).evidence_id != ref
                    or proof not in alignment.math_evidence
                    or proof.input_refs != evidence.input_refs
                ):
                    raise ValueError("student step evidence has a dangling or altered tool receipt")

    def trajectory(self, *, cutoff_revision: int | None = None) -> TrajectoryProjection:
        # A complete episode prefix must come from the trusted host reader;
        # episode resolution/completeness certification is Capability-02 work.
        if not self.prefix or len(self.prefix) > 32 or self.prefix[-1] != self.submission:
            raise ValueError("trajectory requires the complete bounded accepted prefix")
        if len({item.message_id for item in self.prefix}) != len(self.prefix):
            raise ValueError("accepted prefix contains duplicate identities")
        snapshot = self.snapshot(cutoff_revision)
        if snapshot != self.snapshot():
            raise ValueError("live trajectory mutation requires the current mathematical head")
        alignments: list[ResponseAlignment | None] = []
        basis: list[SourceRef] = []
        for ordinal, response in enumerate(self.prefix, 1):
            if response.session_id != self.submission.session_id:
                raise ValueError("foreign accepted evidence scope")
            basis.extend(
                (
                    SourceRef("task_turn", str(ordinal)),
                    SourceRef("student_response", response.response_id),
                )
            )
            candidates = [
                _decode(value)
                for value in self._records["alignments"].values()
                if _decode(value).student_response_ref.identifier == response.response_id
                and _decode(value).output_workspace_revision <= snapshot.workspace.revision
            ]
            alignment = max(candidates, key=lambda value: value.workspace_revision, default=None)
            if alignment is not None:
                self._check_step_evidence(alignment)
                before = self.snapshot(alignment.workspace_revision)
                after = self.snapshot(alignment.output_workspace_revision)
                if (
                    before.problem_model != self.source.authored.problem_model
                    or after.problem_model != before.problem_model
                ):
                    raise ValueError("historical alignment source drift")
                if alignment.math_workspace_ref != snapshot.workspace_ref:
                    raise ValueError("foreign alignment workspace")
                for claim in alignment.claims:
                    span = claim.evidence
                    if response.raw_content[span.start : span.end] != span.quote:
                        raise ValueError("historical claim is not grounded in accepted raw content")
                if not set(alignment.validated_artifact_refs) <= set(
                    after.workspace.artifact_refs
                ) or not set(alignment.validation_evidence_refs) <= set(
                    after.workspace.tool_evidence_refs
                ):
                    raise ValueError("historical validation refs are absent from the pinned output")
                basis.extend(
                    (
                        SourceRef("response_alignment", alignment.alignment_id),
                        SourceRef(
                            "workspace_revision",
                            f"{snapshot.workspace.workspace_id}@{alignment.output_workspace_revision}",
                        ),
                    )
                )
            alignments.append(alignment)
        confirmations = tuple(
            MethodConfirmation.from_dict(value) for value in self._records["confirmations"].values()
        )
        result = derive_trajectory(
            snapshot,
            self.source.authored,
            tuple(alignments),
            cutoff_response_ref=SourceRef("student_response", self.submission.response_id),
            cutoff_turn=len(self.prefix),
            basis_refs=tuple(basis),
            learner=self.source.identity.learner,
            question_ref=self.source.identity.question_ref,
            confirmations=confirmations,
        )
        confirmation = result.method_confirmation
        if (
            confirmation is not None
            and confirmation.confirmation_id not in self._records["confirmations"]
        ):
            self._records["confirmations"][confirmation.confirmation_id] = asdict(confirmation)
        return replace(result, version=self.source.trajectory_version)

    def confirm(
        self,
        issued: MethodConfirmation,
        *,
        option_token: str | None = None,
        expected_revision: int,
        invalidate: bool = False,
    ) -> MethodConfirmation:
        identity = self.source.identity
        if (
            issued.learner != identity.learner
            or issued.question_ref != identity.question_ref
            or issued.episode_ref != self.source.authored.workspace_ref
        ):
            raise ValueError("foreign method confirmation binding")
        existing = self._records["confirmations"].get(issued.confirmation_id)
        if existing is None:
            raise ValueError("method confirmation was not issued by this mathematical episode")
        if not invalidate and self.snapshot().workspace.revision != expected_revision:
            raise ConfirmationScopeChanged("method confirmation resolution scope changed")
        current = MethodConfirmation.from_dict(existing)
        if not invalidate:
            trajectory = self.trajectory()
            if (
                trajectory.method_confirmation is None
                or trajectory.method_confirmation.confirmation_id != issued.confirmation_id
            ):
                raise ValueError("method confirmation differs from the current mathematical basis")
        result = resolve_confirmation(
            issued,
            current,
            option_token=option_token,
            after_turn=len(self.prefix),
            invalidate=invalidate,
        )
        self._records["confirmations"][result.confirmation_id] = asdict(result)
        return result

    def authorize(
        self, selected_refs: tuple[str, ...], grants: tuple[MathSemanticGrant, ...]
    ) -> None:
        require_math_authority(self.snapshot(), self.trajectory(), selected_refs, grants)

    def transform(
        self,
        before: MathWorkspaceSnapshot,
        *,
        before_artifact_ref: str,
        operation: TypedTransformationOperation,
    ) -> MaterializedTransformation:
        if self.snapshot(before.workspace.revision) != before:
            raise RevisionConflict("snapshot differs from durable workspace")
        payload = {
            "workspace_id": before.workspace.workspace_id,
            "before": before_artifact_ref,
            "operation": operation.to_dict(),
        }
        request_id = "transform_" + _digest(payload)[:32]
        old = self._records["transformations"].get(request_id)
        if old is not None:
            return self._transformation_result(operation, request_id, old)
        if self.snapshot().workspace.revision != before.workspace.revision:
            raise RevisionConflict("workspace advanced before materialization")
        if len(self._records["transformations"]) >= 8:
            raise ValueError("bounded transformation budget exhausted")
        premise = next(
            (value for value in before.artifacts if value.artifact_id == before_artifact_ref), None
        )
        if premise is None:
            raise ValueError("before artifact not in supplied snapshot")
        validation, statement, solved = _evaluate_transformation(premise, operation)
        record = {
            "revision": before.workspace.revision,
            "before": before_artifact_ref,
            "after": None,
            "operation_artifact": None,
            "evidence": None,
            "validation": asdict(validation),
        }
        if statement is not None:
            revision = before.workspace.revision + 1
            operation_ref = SourceRef("math_transformation", request_id)
            provenance = (
                before.workspace_ref,
                SourceRef("math_artifact", before_artifact_ref),
                operation_ref,
            )
            labels = {
                "add_both_sides": "两边加上",
                "subtract_both_sides": "两边减去",
                "multiply_both_sides": "两边乘以",
                "divide_both_sides": "两边除以",
            }
            _, quantity = _linear(operation.quantity, None)
            scope = VERSION + ":" + SCOPE + ":" + before_artifact_ref
            op_artifact = MathArtifact(
                labels[operation.kind] + str(quantity),
                "transformation",
                claim_kind="operation_description",
                provenance=provenance,
                dependencies=(before_artifact_ref,),
                workspace_revision=revision,
                verification_status="qualified",
                verification_scope=scope,
            )
            artifact = MathArtifact(
                statement,
                "answer_candidate" if solved else "intermediate",
                provenance=provenance,
                dependencies=(before_artifact_ref,),
                assumptions=premise.assumptions,
                uncertainty=premise.uncertainty,
                verification_status="qualified",
                verification_scope=scope,
                workspace_revision=revision,
            )
            evidence = ToolEvidence(
                VERSION,
                "1",
                json.dumps(payload, ensure_ascii=False),
                statement,
                scope,
                "verified",
                input_refs=(before_artifact_ref, request_id),
                artifact_refs=(cast(str, artifact.artifact_id), cast(str, op_artifact.artifact_id)),
            )
            artifact = replace(artifact, tool_evidence_refs=(cast(str, evidence.evidence_id),))
            op_artifact = replace(
                op_artifact, tool_evidence_refs=(cast(str, evidence.evidence_id),)
            )
            relation = DependencyRelation(
                (before_artifact_ref,),
                cast(str, artifact.artifact_id),
                "equivalent_to",
                provenance,
                scope,
                revision,
            )
            self.append(
                expected_revision=before.workspace.revision,
                artifacts=(op_artifact, artifact),
                evidence=(evidence,),
                relations=(relation,),
            )
            record.update(
                revision=revision,
                after=artifact.artifact_id,
                operation_artifact=op_artifact.artifact_id,
                evidence=evidence.evidence_id,
            )
        self._records["transformations"][request_id] = record
        return self._transformation_result(operation, request_id, record)

    def _transformation_result(
        self, operation: TypedTransformationOperation, request_id: str, record: dict[str, Any]
    ) -> MaterializedTransformation:
        snapshot = self.snapshot(record["revision"])
        return MaterializedTransformation(
            operation,
            SourceRef("math_transformation", request_id),
            record["before"],
            record["after"],
            TransformationValidation(**record["validation"]),
            record["revision"],
            record["operation_artifact"],
            next(
                (value for value in snapshot.artifacts if value.artifact_id == record["after"]),
                None,
            ),
            next(
                (
                    value
                    for value in snapshot.tool_evidence
                    if value.evidence_id == record["evidence"]
                ),
                None,
            ),
        )

    def reserve_attempt(
        self,
        *,
        workspace_revision: int,
        provider_digest: str,
        model_config_digest: str,
        input_projection_digest: str,
        projected_refs: tuple[str, ...],
        attempt_no: int,
    ) -> ReasoningAttempt:
        if attempt_no < 1:
            raise ValueError("attempt_no must be positive")
        fields: dict[str, Any] = dict(
            workspace_id=self.snapshot().workspace.workspace_id,
            workspace_revision=workspace_revision,
            provider_digest=provider_digest,
            model_config_digest=model_config_digest,
            input_projection_digest=input_projection_digest,
            projected_refs=projected_refs,
            attempt_no=attempt_no,
        )
        attempt_id = "attempt_" + _digest(fields)[:24]
        for data in self._records["attempts"].values():
            previous = self._attempt(data)
            if (
                previous.workspace_revision == workspace_revision
                and previous.attempt_no == attempt_no
            ):
                if previous.attempt_id != attempt_id:
                    raise DuplicateAttemptError(
                        "attempt slot is bound to a different input/provider digest"
                    )
                return previous
        value = ReasoningAttempt(attempt_id=attempt_id, status="reserved", **fields)
        self._records["attempts"][attempt_id] = asdict(value)
        return value

    @staticmethod
    def _attempt(data: dict[str, Any]) -> ReasoningAttempt:
        return ReasoningAttempt(
            **{
                **data,
                "projected_refs": tuple(data["projected_refs"]),
                "evidence_refs": tuple(data["evidence_refs"]),
                "materialized_refs": tuple(data["materialized_refs"]),
            }
        )

    def update_attempt(self, attempt_id: str, **changes: Any) -> ReasoningAttempt:
        old = self._attempt(self._records["attempts"][attempt_id])
        if changes.get("model_call_state") not in {
            None,
            "started",
            "completed",
            "result_persisted",
            "timeout",
            "malformed",
            "failed",
            "outcome_unknown",
        }:
            raise ValueError("unsupported model call state")
        if changes.get("tool_call_state") not in {
            None,
            "started",
            "completed",
            "timeout",
            "failed",
            "outcome_unknown",
        }:
            raise ValueError("unsupported tool call state")
        proposal_json = changes.get("proposal_json")
        if proposal_json is not None and (
            len(proposal_json.encode("utf-8")) > 32_000
            or any(
                marker in proposal_json.casefold()
                for marker in ("chain of thought", "private cot", "思维链", "内部推理")
            )
        ):
            raise ValueError("structured proposal exceeds public durable bound")
        allowed = {
            "status",
            "proposal_json",
            "evidence_refs",
            "failure_type",
            "model_call_state",
            "tool_call_state",
        }
        if set(changes) - allowed:
            raise ValueError("unknown reasoning attempt update")
        result = replace(old, **{key: value for key, value in changes.items() if value is not None})
        self._records["attempts"][attempt_id] = asdict(result)
        return result

    def materialize_attempt(
        self, attempt_id: str, proposal: ReasoningStepProposal
    ) -> MathWorkspaceSnapshot:
        proposal = ReasoningStepProposal.from_value(proposal)
        attempt = self._attempt(self._records["attempts"][attempt_id])
        if attempt.status in {"materialized", "completed"}:
            return self.snapshot()
        artifacts, evidence, relations, paths, superseded = materialize_reasoning(
            self.snapshot(), attempt, proposal
        )
        snapshot = self.append(
            expected_revision=self.snapshot().workspace.revision,
            artifacts=artifacts,
            evidence=evidence,
            relations=relations,
            paths=paths,
            superseded_by=superseded,
        )
        self._records["attempts"][attempt_id] = asdict(
            replace(
                attempt,
                status="materialized",
                materialized_refs=tuple(cast(str, value.artifact_id) for value in artifacts)
                + tuple(cast(str, value.path_id) for value in paths),
                materialized_revision=snapshot.workspace.revision,
            )
        )
        return snapshot


async def confirm_method(
    authority: MathMutationAuthority | None,
    issued: MethodConfirmation,
    *,
    option_token: str,
    expected_revision: int,
) -> MethodConfirmation:
    """Preserve rejected-scope invalidation without bypassing the host commit.

    The old reviewed boundary committed invalidation separately before raising.
    Here the same domain effect commits under the host authority, then the caller
    receives the rejection. Other errors roll back the entire mutation.
    """

    def resolve(state: MathMutation) -> tuple[MethodConfirmation, str | None]:
        try:
            return state.confirm(
                issued, option_token=option_token, expected_revision=expected_revision
            ), None
        except ConfirmationScopeChanged as exc:
            return state.confirm(issued, expected_revision=expected_revision, invalidate=True), str(
                exc
            )

    confirmation, rejection = await run_math_operation(authority, resolve)
    if rejection is not None:
        raise ValueError(rejection)
    return confirmation
