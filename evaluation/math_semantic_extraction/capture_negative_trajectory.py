"""Focused old-derived uncertainty, contradiction, active-set and timeout oracle."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import runpy
import sys
import tempfile

from freeze_oracle import PIN, canonical, verify_source, write_capture


def capture(source: Path) -> dict:
    verify_source(source)
    sys.path[:0] = [str(source / "src"), str(source / "tests"), str(source)]
    from tutor_demo.alignment.contracts import ClaimRelation
    from tutor_demo.math_core.validation import ValidationRequest, validate_request
    from tutor_demo.math_core.workspace import _snapshot_payload
    from tutor_demo.teaching_planner.projection import derive_trajectory

    helpers = runpy.run_path(str(source / "tests/test_portability_authority.py"))
    result = {"baseline": PIN, "trajectory": [], "validation_request": []}
    with tempfile.TemporaryDirectory() as directory:
        for variant in helpers["SEED"]["variants"][:2]:
            task = helpers["_Task"](Path(directory) / (variant[0] + ".sqlite3"), variant)
            context = task.add("a0")
            first = task.alignments.load(context.alignment.alignment_ref.identifier)
            second_context = task.add("a0")
            second = task.alignments.load(second_context.alignment.alignment_ref.identifier)
            current, authored = task.workspace.load(task.source.workspace.workspace_id), task.source
            target = first.matched_artifact_refs[0]
            contrary = replace(
                first,
                relations=(
                    ClaimRelation(
                        first.claims[0].claim_id,
                        target,
                        "contradicts",
                        "oracle",
                        "contradictory_input",
                    ),
                ),
                matched_artifact_refs=(),
                contradicted_artifact_refs=(target,),
                status="unresolved",
            )
            variants = [
                ("alignment_uncertainty", current, (replace(first, uncertainty=0.5),)),
                (
                    "claim_uncertainty",
                    current,
                    (
                        replace(
                            first,
                            claims=tuple(replace(claim, uncertainty=0.5) for claim in first.claims),
                        ),
                    ),
                ),
                (
                    "claim_ambiguous",
                    current,
                    (
                        replace(
                            first,
                            claims=tuple(
                                replace(claim, parse_status="ambiguous") for claim in first.claims
                            ),
                        ),
                    ),
                ),
                (
                    "claim_unparsed",
                    current,
                    (
                        replace(
                            first,
                            claims=tuple(
                                replace(claim, parse_status="unparsed") for claim in first.claims
                            ),
                        ),
                    ),
                ),
                ("contradiction_only", current, (contrary,)),
                ("contradiction_then_positive", current, (contrary, second)),
                (
                    "refuted_active_artifact",
                    replace(
                        current,
                        artifacts=tuple(
                            replace(artifact, verification_status="refuted")
                            if artifact.artifact_id == target
                            else artifact
                            for artifact in current.artifacts
                        ),
                    ),
                    (first,),
                ),
                (
                    "conflicting_active_artifact",
                    replace(
                        current,
                        artifacts=tuple(
                            replace(artifact, verification_status="unresolved_conflict")
                            if artifact.artifact_id == target
                            else artifact
                            for artifact in current.artifacts
                        ),
                    ),
                    (first,),
                ),
                (
                    "superseded_active_artifact",
                    replace(current, superseded_by=((target, task.math["b1"].artifact_id),)),
                    (first,),
                ),
                (
                    "no_claims",
                    current,
                    (
                        replace(
                            first,
                            claims=(),
                            relations=(),
                            matched_artifact_refs=(),
                            status="no_math_claim",
                        ),
                    ),
                ),
            ]
            for label, snapshot, history in variants:
                last = history[-1]
                args = {
                    "cutoff_response_ref": last.student_response_ref,
                    "cutoff_turn": len(history),
                    "basis_refs": (authored.workspace_ref,),
                    "learner": task.learner,
                    "question_ref": task.question.ref,
                }
                projection = derive_trajectory(snapshot, authored, history, **args)
                result["trajectory"].append(
                    {
                        "id": variant[0] + ":" + label,
                        "current": canonical(_snapshot_payload(snapshot)),
                        "authored": canonical(_snapshot_payload(authored)),
                        "alignments": canonical(history),
                        "arguments": canonical(args),
                        "expected": canonical(projection.to_dict()),
                    }
                )
            task.workspace.close()
    for statement, kind in (
        ("2=2", "derived_equation"),
        ("x+x=2*x", "algebraic_identity"),
        ("中文", "derived_equation"),
    ):
        request = ValidationRequest(statement, kind, "恒等式", timeout_ms=0)
        result["validation_request"].append(
            {"request": canonical(request), "expected": canonical(validate_request(request))}
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve captured outcomes; choose a new output")
    value = capture(args.source.resolve())
    write_capture(value, args.output)
    print({key: len(item) for key, item in value.items() if isinstance(item, list)})
