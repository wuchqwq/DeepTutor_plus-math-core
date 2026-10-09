"""Exact act aliases change presentation only, after complete native authority."""

from dataclasses import asdict, replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.math_turn import output
from deeptutor.math_semantic.support import materialize_operation_support
from deeptutor.math_semantic.tools import MathToolRegistry

from .test_publication import Generation, assistant_row, replay
from .test_publication import publication_host_factory as _publication_host_factory
from .test_student_step_evidence import align, calculation, issue_task, source, state_for

publication_host_factory = _publication_host_factory
TEXT = "w^2=a^2+2*a*b+b^2"


@pytest.fixture(scope="module")
def prepared():
    reviewed = source(domain="a,b are real", givens=(), definitions=("w=a+b",), operation=TEXT)
    state = state_for(reviewed, TEXT)
    issue_task(state, TEXT)
    calc = calculation(state)
    return state, calc, output.publication_input(state, calc)


def aliases(state, inputs, kind="expand"):
    artifacts = {a.artifact_id: a for a in state.snapshot().artifacts}
    chosen = next(
        o
        for o in inputs["offers"]
        if o["grant"]["act_kind"] == "chosen_operation"
        and artifacts[o["grant"]["target_artifact_ref"]].statement == TEXT
        and json.loads(artifacts[o["grant"]["content_ref"]["identifier"]].statement)["kind"] == kind
    )
    option = next(
        o
        for o in inputs["offers"]
        if o["grant"]["act_kind"] == "operation_options"
        and o["grant"]["content_ref"] == chosen["grant"]["content_ref"]
    )
    return chosen, option


def accept(state, calc, inputs, offers):
    return output.accept_response(
        state,
        calc,
        inputs,
        json.dumps(
            {
                "authority_basis": inputs["authority_basis"],
                "grant_ids": [o["grant_id"] for o in offers],
            }
        ),
    )


@pytest.mark.parametrize("kind", ["expand", "substitute"])
@pytest.mark.parametrize("reverse", [False, True])
def test_exact_alias_pair_renders_once_retains_both_grants(prepared, kind, reverse):
    state, calc, inputs = prepared
    pair = aliases(state, inputs, kind)
    selected = pair[::-1] if reverse else pair
    body = output.ACKNOWLEDGEMENT + "\n\n" + pair[0]["text"]
    singles = [accept(state, calc, inputs, [o]) for o in selected]
    assert all(receipt.content == body for receipt in singles)
    combined = accept(state, calc, inputs, selected)
    assert combined.content == body
    trace = json.loads(combined.metadata_json)["math_publication"]
    assert trace["selected_grants"] == [o["grant"] for o in selected]
    assert trace["content_digest"] == hashlib.sha256(body.encode()).hexdigest()
    assert combined.publication_id not in {receipt.publication_id for receipt in singles}


def test_a_alias_b_distinct_a_alias_preserves_first_operation_order(prepared):
    state, calc, inputs = prepared
    a, a_option = aliases(state, inputs)
    b, _ = aliases(state, inputs, "substitute")
    combined = accept(state, calc, inputs, [a, b, a_option])
    assert combined.content == "\n\n".join([output.ACKNOWLEDGEMENT, a["text"], b["text"]])
    assert json.loads(combined.metadata_json)["math_publication"]["selected_grants"] == [
        o["grant"] for o in (a, b, a_option)
    ]


@pytest.mark.parametrize(
    "change",
    [
        "target",
        "content",
        "digest",
        "support",
        "mechanism",
        "scope",
        "same_act",
        "other_act",
        "text",
    ],
)
def test_presentation_does_not_coalesce_same_words_with_distinct_relation(
    prepared, monkeypatch, change
):
    # Isolate presentation after an explicit test authority accepts both complete
    # relations. This does not assert that Core grants arbitrary changed scopes.
    state, _, inputs = prepared
    a, option = aliases(state, inputs)
    b = json.loads(json.dumps(option))
    if change == "target":
        b["grant"]["target_artifact_ref"] = "distinct-target"
    elif change in {"content", "support"}:
        b["grant"][change + "_ref"]["identifier"] = "distinct-ref"
    elif change == "digest":
        b["grant"]["content_digest"] = "f" * 64
    elif change in {"mechanism", "scope"}:
        b["grant"]["support_" + change] = "distinct-" + change
    elif change in {"same_act", "other_act"}:
        b["grant"]["act_kind"] = "chosen_operation" if change == "same_act" else "result"
    else:
        b["text"] += " "  # Strict bytes, not stripped or similar words.
    b["grant_id"] = "presentation-boundary-second"
    current = {**inputs, "offers": [a, b]}
    authorized = []
    test_authority = SimpleNamespace(authorize=lambda refs, chosen: authorized.extend(chosen))
    monkeypatch.setattr(output, "publication_input", lambda *args: current)
    receipt = accept(
        test_authority, {"trajectory": {"applicable_artifact_refs": []}}, current, [a, b]
    )
    assert len(authorized) == 2
    assert receipt.content == "\n\n".join([output.ACKNOWLEDGEMENT, a["text"], b["text"]])


def test_full_authorization_happens_before_alias_suppression(prepared, monkeypatch):
    _, calc, inputs = prepared
    pair = aliases(prepared[0], inputs)
    seen = []

    def reject(refs, chosen):
        seen.extend(chosen)
        raise ValueError("second grant refused by authority")

    monkeypatch.setattr(output, "publication_input", lambda *args: inputs)
    with pytest.raises(ValueError, match="second grant refused"):
        accept(SimpleNamespace(authorize=reject), calc, inputs, pair)
    assert [g.to_dict() for g in seen] == [o["grant"] for o in pair]


@pytest.mark.parametrize("bad", ["unknown", "forged", "stale"])
def test_second_invalid_grant_never_disappears_into_alias_filter(prepared, bad):
    original, _, original_inputs = prepared
    state = state_for(original.source, TEXT, payload=original.serialize())
    calc, inputs = calculation(state), output.publication_input(state, calculation(state))
    a, option = aliases(state, inputs)
    if bad == "stale":
        old_id = option["grant_id"]
        state.append(expected_revision=state.snapshot().workspace.revision, status="rebind-test")
        artifacts, evidence = materialize_operation_support(
            state.snapshot(), state.trajectory().applicable_artifact_refs
        )
        state.append(
            expected_revision=state.snapshot().workspace.revision,
            artifacts=artifacts,
            evidence=evidence,
        )
        calc = calculation(state)
        inputs = output.publication_input(state, calc)
        a, _ = aliases(state, inputs)
        invalid = {"grant_id": old_id}
    elif bad == "forged":
        forged = {**option["grant"], "support_scope": "forged-scope"}
        invalid = {"grant_id": output._digest(forged)}
    else:
        invalid = {"grant_id": "unknown-grant"}
    before = state.serialize()
    with pytest.raises(ValueError, match="exceeds current mathematical authority"):
        accept(state, calc, inputs, [a, invalid])
    assert state.serialize() == before
    assert original_inputs == prepared[2]


def test_historical_alias_projection_validates_all_grants_then_keeps_distinct_operations(prepared):
    original, calc, inputs = prepared
    state = state_for(original.source, TEXT, payload=original.serialize())
    a, option = aliases(state, inputs)
    b, b_option = aliases(state, inputs, "substitute")
    c = next(
        o
        for o in inputs["offers"]
        if o["grant"]["act_kind"] == "chosen_operation"
        and o["grant"]["target_artifact_ref"] != a["grant"]["target_artifact_ref"]
    )
    c_option = next(
        o
        for o in inputs["offers"]
        if o["grant"]["act_kind"] == "operation_options"
        and o["grant"]["content_ref"] == c["grant"]["content_ref"]
    )
    # A pre-fix receipt carries the old two-copy bytes. Projection must preserve
    # this receipt, including its identifier and complete original grant list.
    selected = [a, option, b, b_option, c, c_option]
    accepted = accept(state, calc, inputs, selected)
    old_body = "\n\n".join([output.ACKNOWLEDGEMENT, *(o["text"] for o in selected)])
    trace = json.loads(accepted.metadata_json)["math_publication"]
    trace["content_digest"] = hashlib.sha256(old_body.encode()).hexdigest()
    trace.pop("publication_id")
    old_id = "math_output_" + output._digest(trace)
    trace["publication_id"] = old_id
    old_receipt = replace(
        accepted,
        content=old_body,
        publication_id=old_id,
        metadata_json=json.dumps({"math_publication": trace}),
    )
    data = json.loads(state.serialize())
    data["host_math_publications"] = {state.submission.turn_id: asdict(old_receipt)}
    second = state_for(state.source, TEXT, payload=json.dumps(data), prefix=state.prefix)
    align(second, TEXT)
    before = second.serialize()
    private = output._teaching_context(second, calculation(second))
    assert private["previous_task"]["publication_id"] == old_id
    assert len(private["previous_task"]["operations"]) == 3
    assert len(private["operation_correspondence"]) == 3
    assert second.serialize() == before
    assert json.loads(before)["host_math_publications"][state.submission.turn_id] == asdict(
        old_receipt
    )

    # A duplicate-looking second alias with invalid support must invalidate the
    # projection rather than disappear before its support is checked.
    changed = json.loads(before)
    entry = changed["host_math_publications"][state.submission.turn_id]
    metadata = json.loads(entry["metadata_json"])
    metadata["math_publication"]["selected_grants"][1]["support_ref"]["identifier"] = "forged"
    entry["metadata_json"] = json.dumps(metadata)
    invalid = state_for(state.source, TEXT, payload=json.dumps(changed), prefix=state.prefix)
    assert output._teaching_context(invalid, calculation(invalid))["previous_task"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["expand", "substitute"])
@pytest.mark.parametrize("reverse", [False, True])
async def test_native_alias_publication_stream_store_receipt_and_replay(
    publication_host_factory, monkeypatch, kind, reverse
):
    host, generation, _ = publication_host_factory()
    host.source = source(domain="a,b are real", givens=(), definitions=("w=a+b",), operation=TEXT)
    host.scope = host.math_scope()
    generation.mode = "operation"
    chosen_ids, chosen_grants, texts, streamed = [], [], [], []
    original_generation = Generation.__call__
    original_live = host.runtime._publish_live_event

    async def choose(inputs):
        state = host.state()
        from deeptutor.math_semantic.workspace import _snapshot_from

        current = _snapshot_from(json.dumps(state["snapshots"][str(state["head"])]))
        pair = aliases(SimpleNamespace(snapshot=lambda: current), inputs, kind)
        ordered = pair[::-1] if reverse else pair
        chosen_ids[:] = [o["grant_id"] for o in ordered]
        chosen_grants[:] = [o["grant"] for o in ordered]
        texts[:] = [ordered[0]["text"]]
        generation.operation_grant_id = pair[0]["grant_id"]

    async def transport(self, *args, **kwargs):
        raw = await original_generation(self, *args, **kwargs)
        value = json.loads(raw)
        value["grant_ids"] = list(chosen_ids)
        raw = json.dumps(value)
        self.raw_candidates[-1] = raw
        return raw

    async def observe(execution, event):
        if event.type.value == "content":
            streamed.append(event.content)
        return await original_live(execution, event)

    generation.hook = choose
    monkeypatch.setattr(Generation, "__call__", transport)
    monkeypatch.setattr(host.runtime, "_publish_live_event", observe)
    _, turn = await host.submit(TEXT)
    body = output.ACKNOWLEDGEMENT + "\n\n" + texts[0]
    row = assistant_row(host, turn["id"])
    trace = row[2]["accepted_output"]["math_publication"]
    assert row[1] == "".join(streamed) == body
    assert trace["selected_grants"] == chosen_grants
    assert len(trace["selected_grants"]) == 2
    assert trace["content_digest"] == hashlib.sha256(body.encode()).hexdigest()
    before = host.state()

    def no_repeat(*args, **kwargs):
        pytest.fail("replay repeated generation, tools or math mutation")

    monkeypatch.setattr(Generation, "__call__", no_repeat)
    monkeypatch.setattr(MathToolRegistry, "call", no_repeat)
    monkeypatch.setattr(
        "deeptutor.capabilities.math_turn.capability.sqlite_episode_mutation", no_repeat
    )
    first, second = await replay(host, turn), await replay(host, turn)
    assert first == second and host.state() == before and len(generation.calls) == 1
    assert "".join(e["content"] for e in first if e["type"] == "content") == body
    result = next(e["metadata"] for e in first if e["type"] == "result")
    assert result["response"] == body and result["math_publication"] == trace
