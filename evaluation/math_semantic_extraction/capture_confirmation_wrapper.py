"""Capture the frozen reviewed-boundary invalidation effect, evaluation only."""

from __future__ import annotations

import argparse
from pathlib import Path
import runpy
import sys
import tempfile

from freeze_oracle import PIN, canonical, verify_source, write_capture


def capture(source: Path) -> dict:
    verify_source(source)
    sys.path[:0] = [str(source / "src"), str(source / "tests"), str(source)]
    from tutor_demo.alignment import ScriptedResponseAlignmentProvider
    from tutor_demo.math_core.workspace import _snapshot_payload

    helpers = runpy.run_path(str(source / "tests/test_portability_authority.py"))
    result = {"baseline": PIN, "cases": []}
    with tempfile.TemporaryDirectory() as directory:
        for index, attack in enumerate(
            ("resolve", "same_choice", "forged_token", "stale_workspace", "ended_host")
        ):
            task = helpers["_Task"](
                Path(directory) / f"wrapper-{index}.sqlite3", helpers["SEED"]["variants"][0]
            )
            task.add("a0")
            context = task.add("b1")
            issued = context.trajectory.method_confirmation
            provider = ScriptedResponseAlignmentProvider({})
            before = task.workspace.load(task.source.workspace.workspace_id)
            token = issued.option_paths[1][0]
            if attack == "same_choice":
                task.boundary.resolve_method_confirmation(
                    context, confirmation_id=issued.confirmation_id, option_token=token
                )
            elif attack == "forged_token":
                token = "forged-token"
            elif attack == "stale_workspace":
                task.workspace.finalize(
                    before.workspace.workspace_id,
                    expected_revision=before.workspace.revision,
                    status="complete",
                )
            elif attack == "ended_host":
                task.active = False
            try:
                resolved = task.boundary.resolve_method_confirmation(
                    context, confirmation_id=issued.confirmation_id, option_token=token
                )
                accepted = True
            except ValueError:
                resolved, accepted = None, False
            (stored,) = task.ledger.method_confirmations(task.source.workspace.workspace_id)
            result["cases"].append(
                {
                    "id": attack,
                    "authored": canonical(_snapshot_payload(task.source)),
                    "learner": canonical(task.learner),
                    "question_ref": canonical(task.question.ref),
                    "responses": [
                        {"message_id": response.response_id, "raw_content": response.text_content()}
                        for response in task.responses
                    ],
                    "provider_id": provider.provider_id,
                    "config_digest": provider.model_config_digest,
                    "issued": canonical(issued),
                    "requested_token": token,
                    "accepted": accepted,
                    "persisted": canonical(stored),
                    "resolved": canonical(resolved),
                    "head_revision": task.workspace.load(
                        before.workspace.workspace_id
                    ).workspace.revision,
                }
            )
            task.workspace.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("preserve captured oracle results; choose a new output")
    write_capture(capture(args.source.resolve()), args.output)
    print("captured 5 real legacy reviewed-boundary confirmation outcomes")
