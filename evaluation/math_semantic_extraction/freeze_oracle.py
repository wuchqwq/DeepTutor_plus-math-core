"""Offline oracle capture. Never imported by the DeepTutor product or pytest.

Run against the frozen tutor_demo@76d5d969... worktree; writes immutable JSON
expectations, not a second runtime. The legacy imports below are evaluation only.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import asdict, is_dataclass, replace
import hashlib
import itertools
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace

PIN = "76d5d9697186d086fb967e79a9e08e394b0d5474"
PLANNING_PIN = "a2a1905dc41eed3e5a574304993c2747dcb0838c"
DEEPTUTOR_PIN = "73774dc26a734c040d3f91bc887060127475178f"


def verify_source(source: Path) -> None:
    actual = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != PIN:
        raise ValueError(f"frozen oracle provenance mismatch: expected {PIN}, got {actual}")
    if subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain", "--", "src", "tests", "evaluation"],
        text=True,
    ).strip():
        raise ValueError("frozen oracle source has local modifications")


def canonical(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items() if key != "duration_ms"}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return value


def capture(source: Path):
    verify_source(source)
    sys.path.insert(0, str(source / "src"))
    from tutor_demo.alignment import (
        AlignmentStore,
        ResponseAlignmentService,
        ScriptedResponseAlignmentProvider,
    )
    from tutor_demo.alignment.contracts import (
        ClaimRelation,
        EvidenceSpan,
        ResponseAlignment,
        StudentMathClaim,
    )
    from tutor_demo.alignment.provider import ArtifactSummary, ProviderEvidence, resolve_evidence
    from tutor_demo.core import LearnerRef, QuestionRef, SourceRef
    from tutor_demo.math_core.contracts import DependencyGraph
    from tutor_demo.math_core.transformations import (
        TypedTransformationOperation,
        _evaluate_transformation,
    )
    from tutor_demo.math_core.workspace import (
        MathWorkspaceStore,
        _snapshot_payload,
    )
    from tutor_demo.math_validation import normalize_display, validate_math_claim
    from tutor_demo.teaching_claims import MathClaim
    from tutor_demo.teaching_planner.math_support import resolve_math_content_support
    from tutor_demo.teaching_planner.projection import derive_trajectory

    learner, question = LearnerRef("oracle-space", "learner"), QuestionRef("oracle", 1)
    result = {
        "baseline": PIN,
        "provenance": {
            "runtime_oracle_sha": PIN,
            "planning_sha": PLANNING_PIN,
            "deeptutor_base_sha": DEEPTUTOR_PIN,
            "whitelist_version": "MATH-ENGINE-EXTRACTION-WHITELIST-01",
            "whitelist_source": "docs/design/MATH_ENGINE_EXTRACTION_WHITELIST_01.md",
        },
        "snapshots": {},
        "compare": [],
        "alignment": [],
        "trajectory": [],
        "validation": [],
        "grounding": [],
        "transformation": [],
        "dependencies": [],
        "support": [],
        "confirmation": [],
        "reasoning_proposal": [],
        "reasoning_projection": [],
        "reasoning_materialization": [],
        "reasoning_budget": [],
        "transformation_materialization": [],
        "protected_boundary": [],
    }
    corpus = json.loads(
        (source / "evaluation/alignment_natural_math/corpus_129.json").read_text(encoding="utf-8")
    )
    for case_id, category, claim_type, text, statement, historical in corpus["cases"]:
        claim = StudentMathClaim(
            "c",
            SourceRef("student_response", "r"),
            EvidenceSpan(0, len(text), text),
            text,
            claim_type,
            "parsed",
            0.0,
        )
        artifact = ArtifactSummary(
            "a",
            statement,
            normalize_display(statement),
            "answer_candidate" if claim_type == "answer" else "intermediate",
            "qualified",
            "oracle",
        )
        result["compare"].append(
            {
                "id": case_id,
                "claim": canonical(claim),
                "artifact": canonical(artifact),
                "answer_ref": "a",
                "expected": canonical(
                    ResponseAlignmentService._compare(claim, artifact, answer_ref="a")
                ),
            }
        )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        ca02 = runpy.run_path(str(source / "tests/test_multipath_ca02_freeze.py"))[
            "ca02_gold"
        ].__wrapped__(root)[2]
        seed = runpy.run_path(str(source / "evaluation/second_seed/audit.py"))["authored"]
        snapshots = {"ca02": ca02}
        for name, count, revision, opaque in (
            ("one", 1, 2, False),
            ("two", 2, 3, False),
            ("three", 3, 5, False),
            ("opaque", 3, 4, True),
        ):
            store = MathWorkspaceStore(root / (name + ".sqlite3"))
            snapshots[name] = seed(store, "oracle-" + name, (name, count, revision, opaque))[0]
        for name, snapshot in snapshots.items():
            result["snapshots"][name] = canonical(_snapshot_payload(snapshot))
            graph = DependencyGraph(
                workspace_revision=snapshot.workspace.revision,
                artifacts=snapshot.artifacts,
                paths=snapshot.paths,
                allow_historical=True,
                workspace_ref=snapshot.workspace_ref,
            )
            for relation in snapshot.relations:
                graph.add_relation(relation)
            for path in snapshot.paths:
                result["dependencies"].append(
                    {
                        "snapshot": name,
                        "path": path.path_id,
                        "expected": {
                            ref: graph.dependency_status(ref, path_ref=path.path_id)
                            for ref in path.artifact_refs
                        },
                    }
                )
            refs = tuple(a.artifact_id for a in snapshot.artifacts)
            result["support"].append(
                {
                    "snapshot": name,
                    "refs": list(refs),
                    "expected": canonical(resolve_math_content_support(snapshot, refs)),
                }
            )
            shared = set.intersection(*(set(p.artifact_refs) for p in snapshot.paths))
            observations = [(None, "unknown"), (next(iter(sorted(shared))), "shared")]
            for path in snapshot.paths:
                distinct = next(
                    (ref for ref in path.artifact_refs if ref not in shared), path.artifact_refs[0]
                )
                observations.append((distinct, path.method))
            for indices in itertools.product(range(len(observations)), repeat=3):
                alignments = []
                for turn, index in enumerate(indices, 1):
                    artifact_ref = observations[index][0]
                    if artifact_ref is None:
                        alignments.append(None)
                        continue
                    artifact = next(a for a in snapshot.artifacts if a.artifact_id == artifact_ref)
                    claim = StudentMathClaim(
                        "claim-" + str(turn),
                        SourceRef("student_response", "r" + str(turn)),
                        EvidenceSpan(0, len(artifact.statement), artifact.statement),
                        artifact.normalized_form,
                        "equation",
                        "parsed",
                        0.0,
                    )
                    alignment = ResponseAlignment(
                        "al-" + str(turn),
                        claim.student_response_ref,
                        snapshot.workspace_ref,
                        snapshot.workspace.revision,
                        snapshot.workspace.revision,
                        (claim,),
                        (
                            ClaimRelation(
                                claim.claim_id, artifact_ref, "matches", "oracle", "exact"
                            ),
                        ),
                        matched_artifact_refs=(artifact_ref,),
                        projected_refs=(artifact_ref,),
                        contradicted_artifact_refs=(),
                        active_path_refs=(),
                        divergence=(),
                        unshown_steps=(),
                        novel_candidates=(),
                        novel_claim_refs=(),
                        novel_path_refs=(),
                        validated_artifact_refs=(),
                        validation_evidence_refs=(),
                        math_evidence=(),
                        interaction_type="answer",
                        provenance=(claim.student_response_ref, snapshot.workspace_ref),
                        status="aligned",
                    )
                    alignments.append(alignment)
                args = {
                    "cutoff_response_ref": SourceRef("student_response", "r3"),
                    "cutoff_turn": 3,
                    "basis_refs": (snapshot.workspace_ref,),
                    "learner": learner,
                    "question_ref": QuestionRef(
                        snapshot.problem_model.problem_id, snapshot.problem_model.revision
                    ),
                }
                trajectory = derive_trajectory(snapshot, snapshot, tuple(alignments), **args)
                result["trajectory"].append(
                    {
                        "snapshot": name,
                        "alignments": canonical(alignments),
                        "arguments": canonical(args),
                        "expected": canonical(trajectory.to_dict()),
                    }
                )
        capture_state_semantics(result, root, snapshots)
        capture_protected_boundary(result, root, source)
        # The full legacy service grounds spans, discovers scoped relations and
        # validates novel candidates. It is used only to freeze its domain output.
        phase3 = runpy.run_path(str(source / "tests/test_response_alignment_phase3.py"))
        for index, (text, statement, role, proposal) in enumerate(
            [
                (
                    "我算出 2 = x",
                    "x=2",
                    "answer_candidate",
                    {"claims": [{"evidence": {"quote": "2 = x"}, "claim_type": "equation"}]},
                ),
                (
                    "x=3",
                    "x=2",
                    "intermediate",
                    {"claims": [{"evidence": {"quote": "x=3"}, "claim_type": "equation"}]},
                ),
                (
                    "Q>=1",
                    "1<=Q<=9",
                    "answer_candidate",
                    {"claims": [{"evidence": {"quote": "Q>=1"}, "claim_type": "equation"}]},
                ),
                ("为什么？", "x=2", "intermediate", {"interaction_type": "question", "claims": []}),
                (
                    "恒等式 (x+y)^2=x^2+2*x*y+y^2",
                    "x=2",
                    "intermediate",
                    {
                        "claims": [
                            {
                                "evidence": {"quote": "(x+y)^2=x^2+2*x*y+y^2"},
                                "claim_type": "identity",
                            }
                        ],
                        "novel_paths": [
                            {"claim_indices": [0], "method": "algebraic_transformation"}
                        ],
                    },
                ),
                (
                    "恒等式 (x+y)^2=x^2+y^2",
                    "x=2",
                    "intermediate",
                    {
                        "claims": [
                            {"evidence": {"quote": "(x+y)^2=x^2+y^2"}, "claim_type": "identity"}
                        ],
                        "novel_paths": [
                            {"claim_indices": [0], "method": "algebraic_transformation"}
                        ],
                    },
                ),
            ]
        ):
            case_dir = root / str(index)
            case_dir.mkdir()
            store, snapshot = phase3["_workspace"](case_dir, statement, role)
            response = phase3["_response"](text, "frozen-response-" + str(index))
            provider = ScriptedResponseAlignmentProvider({text: proposal})
            alignment = ResponseAlignmentService(AlignmentStore(store), provider).align(
                response, snapshot
            )
            result["alignment"].append(
                {
                    "text": text,
                    "response_id": response.response_id,
                    "snapshot": canonical(_snapshot_payload(snapshot)),
                    "proposal": proposal,
                    "provider_id": provider.provider_id,
                    "config_digest": provider.model_config_digest,
                    "expected": canonical(alignment),
                    "output_snapshot": canonical(
                        _snapshot_payload(store.load(snapshot.workspace.workspace_id))
                    ),
                }
            )
        for snapshot_name in ("ca02", "three"):
            before = snapshots[snapshot_name].artifacts[1]
            for kind, quantity in itertools.product(
                (
                    "add_both_sides",
                    "subtract_both_sides",
                    "multiply_both_sides",
                    "divide_both_sides",
                ),
                ("0", "1", "-2", "1/3", "x", "1/0", "2^20"),
            ):
                operation = TypedTransformationOperation(kind, quantity)
                result["transformation"].append(
                    {
                        "before": canonical(before),
                        "operation": operation.to_dict(),
                        "expected": canonical(_evaluate_transformation(before, operation)),
                    }
                )
    for text in (
        "2=2",
        "2=3",
        "x=2",
        "x+x=2*x",
        "(x+y)^2=x^2+y^2",
        "x^2=4",
        "x²+x²=2*x²",
        r"\frac12=0.5",
        "x=\\bogus{x}",
        "中文",
        "__import__('os')",
    ):
        for kind, support in (("derived_equation", ""), ("algebraic_identity", "恒等式展开为")):
            value = MathClaim(text, support, kind)
            try:
                checked = validate_math_claim(value)
                expected = {
                    "status": checked.status,
                    "scope": checked.scope,
                    "residual": checked.residual,
                    "error": None,
                }
            except ValueError as exc:
                expected = {"error": str(exc)}
            result["validation"].append(
                {"statement": text, "support": support, "kind": kind, "expected": expected}
            )
    for text, quote, occurrence in (
        ("x=2", "x=2", None),
        ("x=2 x=2", "x=2", None),
        ("x=2 x=2", "x=2", 1),
        ("aaa", "aa", 1),
        ("x=2", "2=x", None),
        ("x=2", "x=2", 3),
    ):
        try:
            expected = {
                "span": canonical(resolve_evidence(text, ProviderEvidence(quote, occurrence)))
            }
        except ValueError as exc:
            expected = {"error": str(exc)}
        result["grounding"].append(
            {"text": text, "quote": quote, "occurrence": occurrence, "expected": expected}
        )
    result["source_sha256"] = {
        str(path.relative_to(source)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted((source / "src/tutor_demo").rglob("*.py"))
    }
    return result


def capture_state_semantics(result: dict, root: Path, snapshots: dict) -> None:
    """Freeze old domain functions and ledgers, with no native package imports."""
    from tutor_demo.core import SourceRef
    from tutor_demo.math_core.contracts import MathArtifact, ProblemFact, ProblemModel, SolutionPath
    from tutor_demo.math_core.reasoner import MathReasoner, ReasoningBudget, ReasoningStepProposal
    from tutor_demo.math_core.transformations import (
        MathTransformationService,
        TypedTransformationOperation,
    )
    from tutor_demo.math_core.workspace import (
        MathWorkspaceStore,
        ReasoningAttempt,
        _snapshot_payload,
    )
    from tutor_demo.teaching_planner.contracts import MethodConfirmation
    from tutor_demo.teaching_planner.projection import derive_trajectory
    from tutor_demo.teaching_planner.service import SlimTeachingPlannerStore

    # Capture the real legacy ledger. The supplied guard is evaluation-owned;
    # host mutation authority is independently exercised by native chain tests.
    pending_case = next(
        case
        for case in result["trajectory"]
        if case["snapshot"] == "three"
        and case["expected"]["status"] == "METHOD_CONFIRMATION_REQUIRED"
    )
    issued = MethodConfirmation.from_dict(pending_case["expected"]["method_confirmation"])
    for index, attack in enumerate(
        (
            "pending",
            "resolve",
            "same_choice",
            "different_choice",
            "forged_token",
            "path_as_token",
            "label_as_token",
            "stale_cutoff",
            "invalidate",
            "invalidated_choice",
            "foreign_episode",
            "foreign_learner",
            "foreign_question",
            "changed_basis",
            "missing_authority",
            "workspace_drift",
        )
    ):
        store = MathWorkspaceStore(root / f"confirmation-{index}.sqlite3")
        store.create(snapshots["three"].problem_model, workspace_id=issued.episode_ref.identifier)
        ledger = SlimTeachingPlannerStore(store)
        current = ledger.bind_method_confirmation(issued)
        if attack in {"same_choice", "different_choice"}:
            current = ledger.bind_method_confirmation(
                issued,
                option_token=issued.option_paths[1][0],
                resolution_context=SimpleNamespace(
                    trajectory=SimpleNamespace(cutoff_turn=3), workspace_revision=1
                ),
                resolution_scope=lambda connection: nullcontext(),
            )
        if attack == "invalidated_choice":
            current = ledger.bind_method_confirmation(issued, invalidate=True)
        requested = issued
        token, after_turn, invalidate = issued.option_paths[1][0], 3, False
        authority, revision = True, 1
        if attack == "same_choice":
            after_turn = 4
        elif attack == "different_choice":
            token = issued.option_paths[0][0]
        elif attack == "forged_token":
            token = "forged-token"
        elif attack == "path_as_token":
            token = issued.option_paths[1][1]
        elif attack == "label_as_token":
            token = "第二种"
        elif attack == "stale_cutoff":
            after_turn = 2
        elif attack == "invalidate":
            invalidate = True
        elif attack == "foreign_episode":
            requested = replace(issued, episode_ref=SourceRef("math_workspace", "foreign"))
        elif attack == "foreign_learner":
            requested = replace(issued, learner=replace(issued.learner, learner_id="foreign"))
        elif attack == "foreign_question":
            requested = replace(issued, question_ref=replace(issued.question_ref, revision=99))
        elif attack == "changed_basis":
            requested = replace(
                issued, issuing_basis_refs=(SourceRef("math_workspace", "foreign"),)
            )
        elif attack == "missing_authority":
            authority = False
        elif attack == "workspace_drift":
            revision = 2
        resolution = (
            None
            if attack in {"pending", "invalidate"}
            else SimpleNamespace(
                trajectory=SimpleNamespace(cutoff_turn=after_turn), workspace_revision=revision
            )
        )
        try:
            actual = ledger.bind_method_confirmation(
                requested,
                option_token=token,
                invalidate=invalidate,
                resolution_context=resolution,
                resolution_scope=(lambda connection: nullcontext()) if authority else None,
            )
            expected = {"accepted": True, "value": canonical(actual)}
        except ValueError as exc:
            expected = {"accepted": False, "error": str(exc)}
        result["confirmation"].append(
            {
                "id": attack,
                "issued": canonical(requested),
                "current": canonical(current),
                "option_token": token,
                "after_turn": after_turn,
                "invalidate": invalidate,
                "requires_resolution": resolution is not None,
                "authority": authority,
                "workspace_revision": revision,
                "expected": expected,
                "persisted": canonical(
                    ledger.method_confirmations(issued.episode_ref.identifier)[0]
                ),
            }
        )
        store.close()

    # Chosen path becomes applicable only after the durable resolution cutoff.
    # ResponseAlignment has no public decoder; use the legacy serializer owner.
    from tutor_demo.alignment.store import _decode
    from tutor_demo.core import LearnerRef, QuestionRef

    alignments = tuple(
        _decode(json.dumps(item)) if item else None for item in pending_case["alignments"]
    )
    resolved = replace(
        issued, state="resolved", chosen_path_ref=issued.option_paths[1][1], resolved_after_turn=3
    )
    for cutoff in (3, 4):
        history = alignments if cutoff == 3 else (*alignments, None)
        args = {
            **pending_case["arguments"],
            "cutoff_turn": cutoff,
            "cutoff_response_ref": SourceRef("student_response", "r" + str(cutoff)),
            "basis_refs": tuple(
                SourceRef(**ref) for ref in pending_case["arguments"]["basis_refs"]
            ),
            "learner": LearnerRef(**pending_case["arguments"]["learner"]),
            "question_ref": QuestionRef(**pending_case["arguments"]["question_ref"]),
            "confirmations": (resolved,),
        }
        actual = derive_trajectory(snapshots["three"], snapshots["three"], history, **args)
        result["trajectory"].append(
            {
                "snapshot": "three",
                "alignments": canonical(history),
                "arguments": canonical(args),
                "expected": canonical(actual.to_dict()),
            }
        )

    reasoner = MathReasoner(
        None, SimpleNamespace(provider_id="oracle", model_config_digest="oracle")
    )
    for name, snapshot in snapshots.items():
        result["reasoning_projection"].append(
            {
                "snapshot": name,
                "round": 2,
                "budget": canonical(ReasoningBudget()),
                "expected": canonical(reasoner._project(snapshot, 2).to_dict()),
            }
        )
    proposal_cases = [
        {"kind": "stop", "stop_reason": "complete"},
        {
            "kind": "tool",
            "requested_tool_call": {"operation": "simplify", "kwargs": {"expression": "x+x"}},
        },
        {
            "kind": "materialize",
            "proposed_artifacts": [
                {"statement": "x+x=2*x", "claim_kind": "algebraic_identity", "local_id": "local:a"}
            ],
            "public_summary": "恒等式展开为",
        },
        {
            "kind": "materialize",
            "proposed_artifacts": [{"statement": "x=2", "assumptions": ["x is real"]}],
        },
        {"kind": "materialize", "proposed_artifacts": [{"statement": "2=3"}]},
        {},
        {"kind": "other"},
        {"kind": "stop", "stop_reason": "unknown"},
        {"kind": "stop", "stop_reason": "complete", "unexpected": True},
        {"kind": "tool", "requested_tool_call": {"operation": "exec", "kwargs": {}}},
        {
            "kind": "tool",
            "requested_tool_call": {"operation": "simplify", "kwargs": {}},
            "stop_reason": "complete",
        },
        {"kind": "materialize", "public_summary": "private cot"},
        {"kind": "materialize", "public_summary": "x" * 1001},
        {"kind": "materialize", "proposed_artifacts": [{"statement": "x=2"}] * 9},
    ]
    snapshot = snapshots["ca02"]
    before_ref = snapshot.artifacts[0].artifact_id
    proposal_cases.append(
        {
            "kind": "materialize",
            "public_summary": "恒等式展开为",
            "proposed_artifacts": [
                {
                    "statement": "x+x=2*x",
                    "claim_kind": "algebraic_identity",
                    "local_id": "local:a",
                    "supersedes": before_ref,
                },
                {"statement": "2*x=x+x", "dependencies": ["local:a"], "local_id": "local:b"},
            ],
            "proposed_relations": [
                {
                    "source_artifact_refs": ["local:a"],
                    "target_artifact_ref": "local:b",
                    "relation_type": "equivalent_to",
                }
            ],
            "proposed_path_updates": [
                {
                    "method": "algebraic_transformation",
                    "artifact_refs": ["local:a", "local:b"],
                    "completeness": "partial",
                }
            ],
        }
    )
    for index, raw in enumerate(proposal_cases):
        try:
            proposal = ReasoningStepProposal.from_value(raw)
            expected = {"accepted": True, "value": canonical(proposal.to_dict())}
        except ValueError as exc:
            expected = {"accepted": False, "error": str(exc)}
        result["reasoning_proposal"].append({"id": index, "proposal": raw, "expected": expected})
        if expected["accepted"] and proposal.kind == "materialize":
            attempt = ReasoningAttempt(
                "frozen-attempt-" + str(index),
                snapshot.workspace.workspace_id,
                snapshot.workspace.revision,
                "oracle",
                "oracle",
                "projection",
                tuple(snapshot.workspace.artifact_refs),
                1,
                "proposal_persisted",
            )
            result["reasoning_materialization"].append(
                {
                    "id": index,
                    "snapshot": "ca02",
                    "proposal": raw,
                    "attempt": canonical(attempt),
                    "expected": canonical(reasoner._materialize(snapshot, attempt, proposal)),
                }
            )
    for model, tool in itertools.product(
        ("not_called", "started", "completed", "unknown"), repeat=2
    ):
        attempt = ReasoningAttempt(
            "attempt",
            "workspace",
            1,
            "provider",
            "config",
            "projection",
            (),
            1,
            "reserved",
            model_call_state=model,
            tool_call_state=tool,
        )
        result["reasoning_budget"].append(
            {
                "attempt": canonical(attempt),
                "expected": [attempt.model_budget_consumed, attempt.tool_budget_consumed],
            }
        )

    provenance = (SourceRef("reviewed_source", "linear-oracle"),)
    model = ProblemModel(
        "linear-oracle",
        provenance[0],
        provenance=provenance,
        givens=(ProblemFact("2*x+4=10", provenance=provenance),),
        target=ProblemFact("Find x", provenance=provenance),
    )
    store = MathWorkspaceStore(root / "transformation-materialization.sqlite3")
    store.create(model, workspace_id="linear-oracle")
    before = MathArtifact(
        "2*x+4=10",
        "intermediate",
        provenance=provenance,
        workspace_revision=2,
        verification_status="qualified",
        verification_scope="reviewed:relative_input",
    )
    initial = store.append_entities(
        "linear-oracle",
        expected_revision=1,
        artifacts=(before,),
        paths=(
            SolutionPath(
                "rational_linear",
                (before.artifact_id,),
                provenance=provenance,
                workspace_revision=2,
            ),
        ),
    )
    result["snapshots"]["linear"] = canonical(_snapshot_payload(initial))
    service = MathTransformationService(store)
    for index, (kind, quantity) in enumerate(
        (
            ("subtract_both_sides", "4"),
            ("subtract_both_sides", "4"),
            ("divide_both_sides", "2"),
            ("multiply_both_sides", "0"),
            ("add_both_sides", "x"),
            ("add_both_sides", "1/0"),
            ("add_both_sides", "2^20"),
            ("subtract_both_sides", "x"),
            ("divide_both_sides", "0"),
            ("multiply_both_sides", "x"),
        )
    ):
        input_snapshot = initial if index < 2 else store.load("linear-oracle")
        input_ref = (
            before.artifact_id
            if index < 2
            else next(
                a.artifact_id
                for a in reversed(input_snapshot.artifacts)
                if a.claim_kind != "operation_description"
            )
        )
        operation = TypedTransformationOperation(kind, quantity)
        try:
            actual = service.materialize(
                input_snapshot, before_artifact_ref=input_ref, operation=operation
            )
            expected = {"accepted": True, "value": canonical(actual)}
        except ValueError as exc:
            expected = {"accepted": False, "error": str(exc)}
        result["transformation_materialization"].append(
            {
                "id": index,
                "input_snapshot": canonical(_snapshot_payload(input_snapshot)),
                "before_ref": input_ref,
                "operation": operation.to_dict(),
                "expected": expected,
                "output_snapshot": canonical(_snapshot_payload(store.load("linear-oracle"))),
            }
        )
    store.close()


def capture_protected_boundary(result: dict, root: Path, source: Path) -> None:
    """Actual old protected boundary rejects; old host shell stays oracle-only."""
    sys.path.insert(0, str(source / "tests"))
    sys.path.insert(0, str(source))
    values = runpy.run_path(str(source / "tests/test_portability_authority.py"))
    task = values["_Task"](root / "protected-boundary.sqlite3", values["SEED"]["variants"][0])
    context = task.add("a0")
    snapshot = task.source
    # Use the workspace owner's semantic serializer, not the dataclass layout.
    from tutor_demo.math_core.workspace import _snapshot_payload

    result["snapshots"]["protected"] = canonical(_snapshot_payload(snapshot))
    from tutor_demo.core import LearnerRef, SourceRef

    for attack in (
        "missing",
        "unknown_policy",
        "contents",
        "revision",
        "source",
        "episode",
        "learner",
        "question",
        "truncated",
        "duplicate",
        "over_capacity",
        "missing_trajectory",
        "zero_paths",
    ):
        task.changes = {}
        task.boundary.reviewed_task, task.boundary.protected_math = task.binding, True
        candidate_context = context
        if attack == "missing":
            task.boundary.reviewed_task = None
        elif attack == "unknown_policy":
            task.boundary.protected_math = lambda response: None
        elif attack == "contents":
            task.changes["authored"] = replace(
                snapshot,
                artifacts=(
                    replace(snapshot.artifacts[0], statement="u+v=11"),
                    *snapshot.artifacts[1:],
                ),
            )
        elif attack == "revision":
            task.changes["authored"] = replace(
                snapshot, workspace=replace(snapshot.workspace, revision=1)
            )
        elif attack == "source":
            task.changes["authored"] = replace(
                snapshot,
                problem_model=replace(
                    snapshot.problem_model, public_ref=SourceRef("forged", "reviewed")
                ),
            )
        elif attack == "episode":
            task.changes["authored"] = replace(
                snapshot, workspace=replace(snapshot.workspace, workspace_id="foreign-episode")
            )
        elif attack == "learner":
            task.changes["learner"] = LearnerRef(task.learner.space_id, "foreign")
        elif attack == "question":
            task.changes["question_ref"] = replace(
                task.question.ref, revision=task.question.ref.revision + 1
            )
        elif attack in {"truncated", "duplicate", "over_capacity"}:
            task.changes["response_ids"] = (
                ()
                if attack == "truncated"
                else (task.responses[0].response_id,) * (2 if attack == "duplicate" else 33)
            )
        elif attack == "missing_trajectory":
            candidate_context = replace(context, trajectory=None)
        try:
            if attack == "zero_paths":
                from tutor_demo.teaching_planner.projection import derive_trajectory

                derive_trajectory(
                    snapshot,
                    replace(snapshot, paths=()),
                    (),
                    cutoff_response_ref=SourceRef("student_response", "none"),
                    cutoff_turn=0,
                    basis_refs=(),
                )
                calls = 0
            else:
                planner = task.planner(candidate_context, task.proposal(candidate_context, "g0"))
                planner.plan(candidate_context)
                calls = planner.provider.calls
            expected = {"accepted": True, "provider_calls": calls}
        except ValueError as exc:
            expected = {
                "accepted": False,
                "provider_calls": 0 if attack == "zero_paths" else planner.provider.calls,
                "error": str(exc),
            }
        result["protected_boundary"].append({"id": attack, "expected": expected})
    task.changes = {}
    task.boundary.reviewed_task, task.boundary.protected_math = task.binding, True
    result["authority"] = []
    from tutor_demo.teaching_planner.contracts import TeachingPolicyProposal
    from tutor_demo.teaching_planner.service import validate_policy_proposal

    for key in ("g0", "a0", "b1", "c0", "foreign"):
        raw = task.proposal(context, "g0" if key == "foreign" else key)
        if key == "foreign":
            raw["target_artifact_refs"] = ["foreign-artifact"]
        try:
            validate_policy_proposal(TeachingPolicyProposal.from_value(raw), context)
            accepted = True
        except ValueError:
            accepted = False
        result["authority"].append(
            {
                "id": "region-" + key,
                "snapshot": "protected",
                "trajectory": canonical(context.trajectory.to_dict()),
                "selected_refs": raw["target_artifact_refs"],
                "grants": [],
                "expected": accepted,
            }
        )
    from tutor_demo.teaching_planner.assistance import (
        ScopedMathAssistancePolicy,
        validate_scoped_math_authority,
    )
    from tutor_demo.teaching_planner.math_support import resolve_math_content_support

    target = task.math["g0"].artifact_id
    bindings = resolve_math_content_support(snapshot, (target,))
    result_grant = next(binding.as_grant() for binding in bindings if binding.act_kind == "result")
    orientation = next(
        binding.as_grant() for binding in bindings if binding.act_kind == "orientation"
    )
    variants = [
        ("exact_result", result_grant),
        ("orientation", orientation),
        ("forged_digest", replace(result_grant, content_digest="f" * 64)),
        ("forged_scope", replace(result_grant, support_scope="forged")),
        ("forged_mechanism", replace(result_grant, support_mechanism="forged")),
        ("unsupported_justification", replace(result_grant, act_kind="justification")),
        (
            "foreign_content",
            replace(result_grant, content_ref=SourceRef("math_artifact", "foreign")),
        ),
    ]
    for label, grant in variants:
        policy = ScopedMathAssistancePolicy(target, "0" * 64, "choose_operation", False, (grant,))
        try:
            validate_scoped_math_authority(
                policy,
                target_refs=(target,),
                reveal_refs=(target,),
                support_bindings=bindings,
                allowed_supply=(
                    "chosen_operation",
                    "justification",
                    "operation_options",
                    "orientation",
                    "result",
                ),
                final_answer_policy="ALLOW",
                goal_digest="0" * 64,
                artifact_roles={
                    artifact.artifact_id: artifact.role for artifact in snapshot.artifacts
                },
            )
            accepted = True
        except ValueError:
            accepted = False
        result["authority"].append(
            {
                "id": "support-" + label,
                "snapshot": "protected",
                "trajectory": canonical(context.trajectory.to_dict()),
                "selected_refs": [target],
                "grants": [canonical(grant)],
                "expected": accepted,
            }
        )
    task.workspace.close()


def extend_capture(source: Path, base_capture: Path) -> dict:
    """Reuse independently captured old outcomes after rechecking every source.

    This only avoids repeated symbolic comparisons; state/trajectory boundaries
    are captured again from legacy owners, never inferred from native results.
    """
    verify_source(source)
    value = json.loads(base_capture.read_text(encoding="utf-8"))
    hashes = {
        str(path.relative_to(source)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted((source / "src/tutor_demo").rglob("*.py"))
    }
    if value["baseline"] != PIN or value["source_sha256"] != hashes:
        raise ValueError("base capture is not from the exact unchanged frozen runtime")
    if any(
        case["artifact"]["role"] not in {"intermediate", "answer_candidate"}
        for case in value["compare"]
    ):
        raise ValueError("base capture used non-mathematical positional artifact summaries")
    sys.path.insert(0, str(source / "src"))
    from tutor_demo.alignment.store import _decode
    from tutor_demo.core import LearnerRef, QuestionRef, SourceRef
    from tutor_demo.math_core.workspace import _snapshot_from
    from tutor_demo.teaching_planner.projection import derive_trajectory

    snapshots = {
        name: _snapshot_from(json.dumps(value["snapshots"][name]))
        for name in ("ca02", "one", "two", "three", "opaque")
    }
    value["trajectory"] = [
        case for case in value["trajectory"] if "confirmations" not in case["arguments"]
    ]
    for case in value["trajectory"]:
        snapshot = snapshots[case["snapshot"]]
        original = case["arguments"]
        args = {
            **original,
            "cutoff_response_ref": SourceRef(**original["cutoff_response_ref"]),
            "basis_refs": tuple(SourceRef(**ref) for ref in original["basis_refs"]),
            "learner": LearnerRef(**original["learner"]),
            "question_ref": QuestionRef(
                snapshot.problem_model.problem_id, snapshot.problem_model.revision
            ),
        }
        alignments = tuple(
            _decode(json.dumps(item)) if item else None for item in case["alignments"]
        )
        case["arguments"] = canonical(args)
        case["expected"] = canonical(
            derive_trajectory(snapshot, snapshot, alignments, **args).to_dict()
        )
    for key in (
        "confirmation",
        "reasoning_proposal",
        "reasoning_projection",
        "reasoning_materialization",
        "reasoning_budget",
        "transformation_materialization",
        "protected_boundary",
    ):
        value[key] = []
    with tempfile.TemporaryDirectory() as directory:
        capture_state_semantics(value, Path(directory), snapshots)
        capture_protected_boundary(value, Path(directory), source)
    value["capture_base_sha256"] = hashlib.sha256(base_capture.read_bytes()).hexdigest()
    return value


def write_capture(value: dict, output: Path) -> None:
    """Keep one semantic case per line, with source/provenance maps readable."""
    entries = []
    for key, item in sorted(value.items()):
        prefix = "  " + json.dumps(key) + ": "
        if isinstance(item, list):
            cases = [
                "    " + json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for case in item
            ]
            encoded = "[\n" + ",\n".join(cases) + "\n  ]" if cases else "[]"
        elif key == "snapshots":
            snapshots = [
                "    "
                + json.dumps(name)
                + ": "
                + json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for name, snapshot in sorted(item.items())
            ]
            encoded = "{\n" + ",\n".join(snapshots) + "\n  }"
        elif isinstance(item, dict):
            encoded = json.dumps(item, ensure_ascii=False, sort_keys=True, indent=2).replace(
                "\n", "\n  "
            )
        else:
            encoded = json.dumps(item, ensure_ascii=False, sort_keys=True)
        entries.append(prefix + encoded)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("{\n" + ",\n".join(entries) + "\n}\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--base-capture",
        type=Path,
        help="unchanged independently captured old outcomes; rechecks full source hashes",
    )
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve the first capture; choose a new output path")
    value = (
        extend_capture(args.source.resolve(), args.base_capture.resolve())
        if args.base_capture
        else capture(args.source.resolve())
    )
    write_capture(value, args.output)
    print({key: len(items) for key, items in value.items() if isinstance(items, list)})
