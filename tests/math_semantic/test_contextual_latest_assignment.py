"""Native A -> B -> no-claim probe; provider I/O alone is deterministic setup."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

import pytest

from deeptutor.capabilities.math_turn import contextual_clarification
from deeptutor.capabilities.math_turn.output import publication_input
from deeptutor.math_semantic.accepted import AcceptedSubmission
from deeptutor.math_semantic.contracts import MathArtifact
from deeptutor.math_semantic.state import MathMutation
from deeptutor.math_semantic.tools import MathToolRegistry

from .test_bounded_feedback import initialized_host_imports as _initialized_host_imports
from .test_publication import assistant_row, replay
from .test_publication import publication_host_factory as _publication_host_factory
from .test_student_step_evidence import source

publication_host_factory = _publication_host_factory
initialized_host_imports = _initialized_host_imports

A = "u*(v+1)=u*v+u"
B = "u*(v-2)=u*v-2*u"
REPLY_A = "(u*(v+1))-(u*v+u)=0"
CLARIFY = "Please explain the operation you just assigned. I have no new calculation."


def two_tasks():
    reviewed = source(domain="u,v are real", givens=(), definitions=(), operation=A)
    snap = reviewed.authored
    second = MathArtifact(
        B,
        "intermediate",
        provenance=snap.problem_model.provenance,
        verification_status="qualified",
        verification_scope="reviewed operation input",
    )
    refs = (*snap.workspace.artifact_refs, second.artifact_id)
    path = replace(snap.paths[0], artifact_refs=refs, path_id=None)
    return replace(
        reviewed,
        authored=replace(
            snap,
            artifacts=(*snap.artifacts, second),
            paths=(path,),
            workspace=replace(
                snap.workspace, artifact_refs=refs, solution_path_refs=(path.path_id,)
            ),
        ),
    )


async def native_chain(publication_host_factory, monkeypatch):
    host, generation, completions = publication_host_factory()
    host.source = two_tasks()
    host.scope = host.math_scope()
    provider_type = type(
        host.engine.capability_registry.catalog.get("turn", "math_turn").factory()._provider
    )

    def proposal(_provider, projection):
        text = projection.response_text
        return {
            "claims": [
                {
                    "evidence": {"quote": REPLY_A},
                    "claim_type": "equation",
                    "candidate_artifact_refs": [],
                }
            ]
            if text == REPLY_A
            else [],
            "interaction_type": "answer" if text == REPLY_A else "clarification",
        }

    monkeypatch.setattr(provider_type, "propose", proposal)

    async def selection(_config, _provider_spec, *, prompt, **_kwargs):
        inputs = json.loads(prompt)
        generation.calls.append({"inputs": inputs})
        number = len(generation.calls)
        if number < 3:
            marker = "v+1" if number == 1 else "v-2"
            chosen = [
                o
                for o in inputs["offers"]
                if o["grant"]["act_kind"] == "chosen_operation" and marker in o["text"]
            ]
        else:
            chosen = [
                o for o in inputs["offers"] if o["grant"]["act_kind"] == "contextual_clarification"
            ]
        assert chosen, (number, inputs)
        return json.dumps(
            {"authority_basis": inputs["authority_basis"], "grant_ids": [chosen[0]["grant_id"]]}
        )

    monkeypatch.setattr("deeptutor.services.llm.factory._complete_with_resolved_config", selection)
    session, first = await host.submit("Give me a small algebra step.")
    _, second = await host.submit(REPLY_A, session_id=session["id"])
    receipts_before = host.state()["host_math_publications"]
    _, a_body, a_meta, _ = assistant_row(host, first["id"])
    _, b_body, b_meta, _ = assistant_row(host, second["id"])
    assert "v+1" in a_body and "v-2" in b_body
    assert (
        a_meta["accepted_output"]["math_publication"]["selected_grants"][0]["act_kind"]
        == "chosen_operation"
    )
    assert (
        b_meta["accepted_output"]["math_publication"]["selected_grants"][0]["act_kind"]
        == "chosen_operation"
    )
    _, third = await host.submit(CLARIFY, session_id=session["id"])
    inputs = generation.calls[-1]["inputs"]
    _, c_body, c_meta, _ = assistant_row(host, third["id"])
    refs = [o for o in inputs["offers"] if o["grant"]["act_kind"] == "contextual_clarification"]
    assert refs
    assert len(generation.calls) == 3
    assert all(host.state()["host_math_publications"][k] == v for k, v in receipts_before.items())
    events = await replay(host, third)
    assert "".join(e["content"] for e in events if e["type"] == "content") == c_body
    record = {
        "scenario": "accepted A -> submitted A + accepted B -> no current claim clarification",
        "first_turn": first,
        "second_turn": second,
        "third_turn": third,
        "original_receipts_before_clarification": receipts_before,
        "native_state": host.state(),
        "clarification_selector_input": inputs,
        "clarification_body": c_body,
        "clarification_metadata": c_meta,
        "offers": refs,
        "expected_latest_publication_id": receipts_before[second["id"]]["publication_id"],
        "older_A_publication_id": receipts_before[first["id"]]["publication_id"],
        "old_receipts_unchanged": True,
        "native_durable_replay_equal": True,
        "paid_provider_calls": 0,
        "selection_is_controlled_setup_not_model_choice_proof": True,
    }
    destination = os.environ.get("LATEST_ASSIGNMENT_PROBE_OUT")
    if destination:
        Path(destination).write_text(json.dumps(record, ensure_ascii=True, indent=2) + "\n", "utf8")
    return host, record


@pytest.mark.asyncio
async def test_latest_task_is_B_after_answer_A_and_no_claim_clarification(
    publication_host_factory, initialized_host_imports, monkeypatch
):
    host, record = await native_chain(publication_host_factory, monkeypatch)
    assert (
        record["clarification_selector_input"]["private_teaching_context"]["previous_task"][
            "publication_id"
        ]
        == record["older_A_publication_id"]
    )
    assert {o["grant"]["previous_publication_id"] for o in record["offers"]} == {
        record["expected_latest_publication_id"]
    }
    assert "v-2" in record["clarification_body"] and "v+1" not in record["clarification_body"]
    # A later valid reference-only publication does not replace the latest
    # accepted operation B, nor make old correspondence task A current.
    _, following = await host.submit(CLARIFY, session_id=host.math_contexts[-1].session_id)
    _, body, metadata, _ = assistant_row(host, following["id"])
    trace = metadata["accepted_output"]["math_publication"]
    following_reference = trace["selected_contextual_clarifications"][0]["previous_publication_id"]
    assert (
        trace["selected_contextual_clarifications"][0]["previous_publication_id"]
        == record["expected_latest_publication_id"]
    )
    assert "v-2" in body and "v+1" not in body
    assert all(
        host.state()["host_math_publications"][k] == v
        for k, v in record["original_receipts_before_clarification"].items()
    )

    prefix = tuple(
        AcceptedSubmission(
            row["id"],
            row["content"],
            row["session_id"],
            row["metadata"]["turn_id"],
            row["metadata"].get("client_submission_id"),
        )
        for row in host.accepted_rows
    )
    calc = host.result()
    native = host.state()
    monkeypatch.setattr(
        MathToolRegistry, "call", lambda *a, **k: pytest.fail("receipt re-resolution ran a tool")
    )
    latest_turn = record["second_turn"]["id"]
    original_a = record["original_receipts_before_clarification"][record["first_turn"]["id"]]
    original_b = record["original_receipts_before_clarification"][latest_turn]
    b_trace = json.loads(original_b["metadata_json"])["math_publication"]
    a_trace = json.loads(original_a["metadata_json"])["math_publication"]
    checks = []
    for change in (
        "foreign_episode",
        "altered_content",
        "stale_revision",
        "invalid_grant",
        "missing_span",
        "duplicate_span",
    ):
        altered = json.loads(json.dumps(native))
        entry = altered["host_math_publications"][latest_turn]
        payload = json.loads(entry["metadata_json"])
        trace = payload["math_publication"]
        if change == "foreign_episode":
            trace["basis"]["episode_id"] = "foreign-episode"
        elif change == "altered_content":
            entry["content"] += " changed"
        elif change == "stale_revision":
            trace["basis"]["math_revision"] = a_trace["basis"]["math_revision"]
        elif change == "invalid_grant":
            trace["selected_grants"][0]["support_mechanism"] = "foreign"
        else:
            entry["content"] = (
                "Mathematical evidence recorded."
                if change == "missing_span"
                else original_b["content"] + "\n\n" + original_b["content"]
            )
            trace["content_digest"] = hashlib.sha256(entry["content"].encode()).hexdigest()
        entry["metadata_json"] = json.dumps(payload)
        state = MathMutation(host.source, prefix[-1], prefix, json.dumps(altered))
        if change in {"foreign_episode", "altered_content"}:
            with pytest.raises(ValueError, match="contextual assignment receipt"):
                publication_input(state, calc)
            outcome = "rejected"
        else:
            inputs = publication_input(state, calc)
            assert not [
                o for o in inputs["offers"] if o["grant"]["act_kind"] == "contextual_clarification"
            ]
            outcome = "no_reference_no_fallback_to_A"
        checks.append({"change": change, "outcome": outcome})

    # Existing Core lookup can stop supporting the latest relation. Remove
    # only B's binding in this isolated fault injection; A remains authorized.
    resolve = contextual_clarification.resolve_math_content_support
    b_ref = b_trace["selected_grants"][0]["content_ref"]["identifier"]
    a_ref = a_trace["selected_grants"][0]["content_ref"]["identifier"]
    state = MathMutation(host.source, prefix[-1], prefix, json.dumps(native))
    old_a = state.snapshot(a_trace["basis"]["math_revision"])
    assert any(
        b.content_ref is not None and b.content_ref.identifier == a_ref
        for b in resolve(old_a, calc["trajectory"]["applicable_artifact_refs"])
    )

    def revoked_latest(snapshot, targets):
        return tuple(
            b
            for b in resolve(snapshot, targets)
            if b.content_ref is None or b.content_ref.identifier != b_ref
        )

    with monkeypatch.context() as isolated:
        isolated.setattr(contextual_clarification, "resolve_math_content_support", revoked_latest)
        assert not [
            o
            for o in publication_input(state, calc)["offers"]
            if o["grant"]["act_kind"] == "contextual_clarification"
        ]
    checks.append(
        {
            "change": "latest_core_binding_unavailable",
            "outcome": "no_reference_no_fallback_to_still_authorized_A",
        }
    )
    assert host.state() == native, "Negative copies never modify the original native receipts"
    destination = os.environ.get("LATEST_ASSIGNMENT_CONTROL_OUT")
    if destination:
        Path(destination).write_text(
            json.dumps(
                {
                    "checks": checks,
                    "original_native_receipts_unchanged": True,
                    "provider_calls": 0,
                    "latest_reference_after_valid_non_operation_receipt": following_reference,
                },
                indent=2,
            )
            + "\n",
            "utf8",
        )
