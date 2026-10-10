"""Explicit host review, current native certificates and unchanged publication."""

import base64
from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sqlite3
import zlib

import pytest

from deeptutor.capabilities.math_turn import output
from deeptutor.math_semantic.authority import math_content_digest
from deeptutor.math_semantic.contracts import ProblemFact
from deeptutor.math_semantic.proposals import AlignmentProposal
from deeptutor.math_semantic.refs import SourceRef
from deeptutor.math_semantic.state import MathMutation, ReviewedGoalConnection
from deeptutor.math_semantic.support import (
    CONNECTION_MECHANISM,
    connection_request,
    materialize_connection_support,
    resolve_math_content_support,
)
from deeptutor.math_semantic.tools import MathToolRegistry

from .test_publication import Generation, assistant_row, replay
from .test_publication import publication_host_factory as _publication_host_factory
from .test_student_step_evidence import TRUE, calculation, source, state_for

publication_host_factory = _publication_host_factory


def reviewed_case(kind="s4"):
    if kind == "s4":
        relation, step = "Q-1=(2/3)*(x-y)^2", TRUE
        reviewed = source(definitions=(), operation=relation)
        model = replace(
            reviewed.authored.problem_model,
            target=ProblemFact(
                "range of Q=x^2-x*y+y^2", provenance=reviewed.authored.problem_model.provenance
            ),
        )
        terms = (
            ("target", 0, math_content_digest(model.target), "1"),
            ("givens", 0, math_content_digest(model.givens[0]), "1/3"),
        )
        coefficient = "-2/3"
        text = "Under the reviewed explicit premises, Q-1=(2/3)*(x-y)^2 connects finding the range of Q to studying the square expression."
    else:
        relation = "u+w=v+5"
        step = "(u+w)-(v+5)=(u-2*v-1)+(v+w-4)"
        reviewed = source(
            domain="u,v,w are real", givens=("u=2*v+1", "v+w=4"), definitions=(), operation=relation
        )
        model = replace(
            reviewed.authored.problem_model,
            target=ProblemFact(
                "describe all real triples satisfying the givens",
                provenance=reviewed.authored.problem_model.provenance,
            ),
        )
        terms = tuple(
            ("givens", i, math_content_digest(fact), "1") for i, fact in enumerate(model.givens)
        )
        coefficient = "1"
        text = "Under the reviewed explicit premises, u+w=v+5 connects the sum to v; this is an intermediate relation for describing the feasible triples."
    authored = replace(
        reviewed.authored,
        problem_model=model,
        workspace=replace(reviewed.authored.workspace, problem_model_ref=model.model_ref),
    )
    permit = ReviewedGoalConnection(
        math_content_digest(model),
        authored.artifacts[-1].artifact_id,
        math_content_digest(authored.artifacts[-1]),
        step,
        terms,
        coefficient,
        text,
    )
    return replace(reviewed, authored=authored, reviewed_connection=permit), step


def aligned(reviewed, step, *, prefix=(), payload=None):
    state = state_for(
        reviewed,
        step + "\nPlease explain the connection to the goal.",
        prefix=prefix,
        payload=payload,
    )
    state.align(
        AlignmentProposal.from_value(
            {
                "claims": [
                    {
                        "evidence": {"quote": step},
                        "claim_type": "equation",
                        "parse_status": "parsed",
                    }
                ],
                "interaction_type": "answer",
            }
        ),
        expected_revision=state.snapshot().workspace.revision,
        provider_id="offline",
        config_digest="offline",
        check_steps=True,
    )
    return state


def prepare(state):
    targets = state.trajectory().applicable_artifact_refs
    request = connection_request(state, targets)
    artifacts, evidence = materialize_connection_support(request)
    if artifacts or evidence:
        state.append(
            expected_revision=state.snapshot().workspace.revision,
            artifacts=artifacts,
            evidence=evidence,
        )
    return request


def offers(state):
    calc = calculation(state)
    calc["authority"] = [
        binding.to_dict()
        for binding in resolve_math_content_support(
            state.snapshot(), state.trajectory().applicable_artifact_refs, state=state
        )
        if binding.act_kind in {"orientation", "justification"}
    ]
    inputs = output.publication_input(state, calc)
    return calc, inputs, [o for o in inputs["offers"] if o["grant"]["act_kind"] == "justification"]


@pytest.fixture(scope="module")
def prepared():
    reviewed, step = reviewed_case()
    state = aligned(reviewed, step)
    assert prepare(state) is not None
    assert len(offers(state)[2]) == 1
    return state


@pytest.mark.parametrize("kind", ["s4", "linear"])
def test_native_fixed_certificate_and_exact_reviewed_text(kind):
    reviewed, step = reviewed_case(kind)
    state = aligned(reviewed, step)
    assert prepare(state) is not None
    calc, inputs, selected = offers(state)
    assert (
        len(selected) == 1
        and selected[0]["text"] == reviewed.reviewed_connection.canonical_explanation
    )
    receipt = output.accept_response(
        state,
        calc,
        inputs,
        json.dumps(
            {"authority_basis": inputs["authority_basis"], "grant_ids": [selected[0]["grant_id"]]}
        ),
    )
    assert receipt.content == output.ACKNOWLEDGEMENT + "\n\n" + selected[0]["text"]
    assert (
        json.loads(receipt.metadata_json)["math_publication"]["selected_grants"][0][
            "support_mechanism"
        ]
        == CONNECTION_MECHANISM
    )
    assert state.snapshot().artifacts[0].verification_status == "qualified"


def test_no_retroactive_review_and_no_content_decode(prepared):
    plain = replace(prepared.source, reviewed_connection=None)
    with pytest.raises(ValueError, match="source or episode"):
        MathMutation(plain, prepared.submission, prepared.prefix, prepared.serialize())
    legacy = json.loads(state_for(plain, TRUE).serialize())
    legacy.pop("reviewed_connection")
    legacy.pop("reviewed_source_digest")
    old = MathMutation(plain, prepared.submission, prepared.prefix, json.dumps(legacy))
    before = old.serialize()
    assert connection_request(old, ()) is None and old.serialize() == before
    with pytest.raises(ValueError, match="source or episode"):
        MathMutation(prepared.source, prepared.submission, prepared.prefix, json.dumps(legacy))
    with pytest.raises(TypeError, match="trusted-composition"):
        replace(
            plain,
            reviewed_connection={"approved": True, **asdict(prepared.source.reviewed_connection)},
        )
    with pytest.raises(ValueError, match="purpose"):
        replace(prepared.source.reviewed_connection, purpose="give_final_range")


@pytest.mark.parametrize("bad", ["coefficient", "fact_digest", "relation", "model"])
def test_bad_or_unreviewed_binding_never_creates_offer(bad):
    reviewed, step = reviewed_case()
    permit = reviewed.reviewed_connection
    changes = {
        "coefficient": {
            "premise_terms": (*permit.premise_terms[:1], (*permit.premise_terms[1][:3], "1/2"))
        },
        "fact_digest": {"premise_terms": (("givens", 0, "0" * 64, "1"),)},
        "relation": {"relation_ref": "unreviewed-relation"},
        "model": {"model_digest": "0" * 64},
    }
    state = aligned(replace(reviewed, reviewed_connection=replace(permit, **changes[bad])), step)
    prepare(state)
    assert offers(state)[2] == []


@pytest.mark.parametrize("bad", ["domain", "uncertain", "inferred", "provenance"])
def test_unknown_or_unreliable_premises_are_not_truth(bad):
    reviewed, step = reviewed_case()
    model = reviewed.authored.problem_model
    if bad == "domain":
        model = replace(model, domain=())
    else:
        fact = model.givens[0]
        fact = replace(
            fact,
            **{
                "uncertain": {"uncertainty": 0.2},
                "inferred": {"status": "inferred"},
                "provenance": {"provenance": (SourceRef("question", "foreign-source"),)},
            }[bad],
        )
        model = replace(model, givens=(fact,))
    authored = replace(
        reviewed.authored,
        problem_model=model,
        workspace=replace(reviewed.authored.workspace, problem_model_ref=model.model_ref),
    )
    permit = replace(
        reviewed.reviewed_connection,
        model_digest=math_content_digest(model),
        premise_terms=(
            ("target", 0, math_content_digest(model.target), "1"),
            ("givens", 0, math_content_digest(model.givens[0]), "1/3"),
        ),
    )
    state = aligned(replace(reviewed, authored=authored, reviewed_connection=permit), step)
    assert prepare(state) is None and offers(state)[2] == []


@pytest.mark.parametrize(
    "bad",
    [
        "session",
        "episode",
        "row",
        "revision",
        "certificate_refs",
        "certificate_output",
        "step_evidence",
    ],
)
def test_foreign_stale_forged_or_replaced_evidence_is_not_consumed(prepared, bad):
    if bad == "episode":
        with pytest.raises(ValueError, match="reviewed workspace"):
            replace(
                prepared.source, identity=replace(prepared.source.identity, episode_id="foreign")
            )
        return
    submitted = prepared.submission
    if bad in {"session", "row"}:
        submitted = replace(
            submitted,
            **(
                {"session_id": "foreign"}
                if bad == "session"
                else {"message_id": 99, "turn_id": "another-turn"}
            ),
        )
    state = MathMutation(prepared.source, submitted, (submitted,), prepared.serialize())
    if bad == "revision":
        state.append(expected_revision=state.snapshot().workspace.revision, status="advanced")
    if bad.startswith("certificate_") or bad == "step_evidence":
        values = state._records["snapshots"][str(state.snapshot().workspace.revision)][
            "tool_evidence"
        ]
        proof = values[-1] if bad.startswith("certificate_") else values[0]
        if bad == "certificate_refs":
            proof["input_refs"] = ["forged"]
        else:
            proof["output_summary"] = "altered"
    assert offers(state)[2] == []


def test_same_formula_different_submission_requires_new_evidence_and_receipt(prepared):
    second = aligned(prepared.source, TRUE, prefix=prepared.prefix, payload=prepared.serialize())
    assert offers(second)[2] == []
    prepare(second)
    assert offers(second)[2][0]["grant_id"] != offers(prepared)[2][0]["grant_id"]
    assert offers(second)[2][0]["text"] == offers(prepared)[2][0]["text"]


def test_correct_direct_answer_certificate_is_not_release_permission():
    direct = source(
        domain="x,y are real", givens=("x+y=2", "Z=x+y"), definitions=(), operation="Z=2"
    )
    proof = MathToolRegistry(max_calls=1).call("expand", expression="(Z-2)-((x+y-2)+(Z-(x+y)))")
    assert proof.status == "succeeded" and str(proof.value) == "0"
    state = aligned(direct, "(x+y)-(x+y)=0")
    assert prepare(state) is None and offers(state)[2] == []


def test_r3_earlier_step_only_request_is_explicitly_not_supported(prepared):
    state = state_for(
        prepared.source,
        "Explain that previous step's connection to the goal",
        prefix=prepared.prefix,
        payload=prepared.serialize(),
    )
    state.align(
        AlignmentProposal.from_value({"claims": [], "interaction_type": "clarification"}),
        expected_revision=state.snapshot().workspace.revision,
        provider_id="offline",
        config_digest="offline",
        check_steps=True,
    )
    assert prepare(state) is None and offers(state)[2] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "approved",
        "ordinary_source",
        "source_changed",
        "tools_source_changed",
        "ownership_lost",
        "waiting_source_changed",
    ],
)
async def test_trusted_host_entry_native_acceptance_and_zero_recompute_replay(
    publication_host_factory, monkeypatch, mode
):
    from deeptutor.capabilities.math_turn.capability import MathTurnCapability

    original_init = MathTurnCapability.__init__

    def initialize(self, *, resolve_episode, provider):
        provider.propose = lambda projection: {
            "claims": [
                {
                    "evidence": {"quote": projection.response_text.split("\n")[0]},
                    "parse_status": "parsed",
                    "claim_type": "equation",
                }
            ],
            "interaction_type": "answer",
        }
        original_init(self, resolve_episode=resolve_episode, provider=provider)

    monkeypatch.setattr(MathTurnCapability, "__init__", initialize)
    host, generation, _ = publication_host_factory()
    host.source, step = reviewed_case()
    if mode == "ordinary_source":
        host.source = replace(host.source, reviewed_connection=None)
    host.scope = host.math_scope()
    if mode == "tools_source_changed":
        from deeptutor.capabilities.math_turn import capability

        materialize = capability.materialize_connection_support

        def revoke_after_tools(request):
            result = materialize(request)
            host.source = replace(host.source, reviewed_connection=None)
            return result

        monkeypatch.setattr(capability, "materialize_connection_support", revoke_after_tools)
    original_generation = Generation.__call__

    async def select(self, *args, **kwargs):
        candidate = json.loads(await original_generation(self, *args, **kwargs))
        options = [
            o
            for o in self.calls[-1]["inputs"]["offers"]
            if o["grant"]["act_kind"] == "justification"
        ]
        assert bool(options) == (mode != "ordinary_source")
        candidate["grant_ids"] = [o["grant_id"] for o in options]
        if mode == "source_changed":
            host.source = replace(host.source, reviewed_connection=None)
        if mode == "ownership_lost":
            assert await host.coordinator.release_turn(host.math_contexts[-1].runtime.turn_lease)
        if mode == "waiting_source_changed":
            context = host.math_contexts[-1]
            protected = context.runtime.run_durable_turn_mutation

            async def revoke_before_commit(mutation, **kwargs):
                host.source = replace(host.source, reviewed_connection=None)
                return await protected(mutation, **kwargs)

            context.runtime.run_durable_turn_mutation = revoke_before_commit
        raw = json.dumps(candidate)
        self.raw_candidates[-1] = raw
        return raw

    monkeypatch.setattr(Generation, "__call__", select)
    if mode == "ordinary_source":
        with pytest.raises(RuntimeError, match="reviewed_connection"):
            await host.start(step, config={"reviewed_connection": {"approved": True}})
    _, turn = await host.start(step + "\nPlease explain the connection.")
    await host.finish(
        turn,
        status="failed"
        if mode
        in {"source_changed", "tools_source_changed", "ownership_lost", "waiting_source_changed"}
        else "completed",
    )
    if mode in {
        "source_changed",
        "tools_source_changed",
        "ownership_lost",
        "waiting_source_changed",
    }:
        if mode != "ownership_lost":
            assert any("source changed" in str(e) for e in host.errors)
        if mode == "tools_source_changed":
            assert generation.calls == []
        assert not any(e["type"] in {"content", "result"} for e in await replay(host, turn))
        return
    row = assistant_row(host, turn["id"])
    expected = output.ACKNOWLEDGEMENT + (
        "\n\n" + host.source.reviewed_connection.canonical_explanation if mode == "approved" else ""
    )
    assert row[1] == expected
    before = host.state()

    def no_repeat(*args, **kwargs):
        pytest.fail("replay reran model, tools or domain mutation")

    monkeypatch.setattr(Generation, "__call__", no_repeat)
    monkeypatch.setattr(MathToolRegistry, "call", no_repeat)
    monkeypatch.setattr(
        "deeptutor.capabilities.math_turn.capability.sqlite_episode_mutation", no_repeat
    )
    first, second = await replay(host, turn), await replay(host, turn)
    assert first == second and host.state() == before
    assert "".join(e["content"] for e in first if e["type"] == "content") == expected


def test_provider_payload_cannot_adopt_reviewed_source_permission(prepared):
    with pytest.raises(ValueError):
        AlignmentProposal.from_value(
            {"claims": [], "reviewed_connection": asdict(prepared.source.reviewed_connection)}
        )
    # Public source/artifact content remains ordinary mathematics even when it
    # calls itself approved. Only the trusted resolver can attach the type.
    plain = source(
        definitions=(),
        operation=json.dumps({"approved": True, "purpose": "explain_connection_to_goal"}),
    )
    state = aligned(plain, TRUE)
    assert prepare(state) is None and offers(state)[2] == []


@pytest.mark.asyncio
async def test_sealed_prechange_receipt_replays_original_bytes_without_upgrade(
    tmp_path, monkeypatch
):
    from .test_routing_isolation import RoutingHost

    sealed = Path(__file__).with_name("fixtures") / "prechange_publication_25b5_zlib.json"
    assert (
        hashlib.sha256(sealed.read_bytes()).hexdigest()
        == "b6925bc383e80ac1984311fba394370644fb3d184b603fc628cedadd1d13c5d6"
    )
    fixture = json.loads(sealed.read_text())
    assert fixture["producer_head"] == "25b5a5868cb046aa8d89deb1221df7216573b0a5"
    assert (
        fixture["capture_sha256"]
        == "271d88743167f68606bc5a97513003f06906dc065c2a05d4119f19aa43d71ef3"
    )
    database = zlib.decompress(base64.b64decode(fixture["database_zlib_base64"]))
    assert hashlib.sha256(database).hexdigest() == fixture["database_sha256"]
    db = tmp_path / "prechange-publication.db"
    db.write_bytes(database)

    def persisted_bytes():
        with closing(sqlite3.connect(db)) as connection:
            assistant = connection.execute(
                "SELECT m.content,m.metadata_json FROM messages m JOIN turns t "
                "ON t.assistant_message_id=m.id WHERE t.id=?",
                (fixture["turn"]["id"],),
            ).fetchone()
            payload = connection.execute(
                "SELECT payload_json FROM math_semantic_episodes"
            ).fetchone()[0]
        assert list(assistant) == fixture["assistant_raw"]
        assert hashlib.sha256(payload.encode()).hexdigest() == fixture["episode_payload_sha256"]
        records = json.loads(payload)
        assert "reviewed_connection" not in records and "reviewed_source_digest" not in records
        assert (
            records["host_math_publications"][fixture["turn"]["id"]] == fixture["publication_entry"]
        )
        return assistant, payload

    before = persisted_bytes()

    def no_recompute(*args, **kwargs):
        pytest.fail("legacy replay reran generation, tools or math mutation")

    monkeypatch.setattr(Generation, "__call__", no_recompute)
    monkeypatch.setattr(MathToolRegistry, "call", no_recompute)
    monkeypatch.setattr(MathMutation, "__init__", no_recompute)
    monkeypatch.setattr(
        "deeptutor.capabilities.math_turn.capability.sqlite_episode_mutation", no_recompute
    )
    host = RoutingHost(db)
    try:
        assert host.source.reviewed_connection is None
        first, second = await replay(host, fixture["turn"]), await replay(host, fixture["turn"])
        assert first == second == fixture["events"]
        assert (
            "".join(e["content"] for e in first if e["type"] == "content")
            == fixture["assistant_raw"][0]
        )
        assert persisted_bytes() == before
    finally:
        await host.close()
    assert persisted_bytes() == before
    assert (
        hashlib.sha256(sealed.read_bytes()).hexdigest()
        == "b6925bc383e80ac1984311fba394370644fb3d184b603fc628cedadd1d13c5d6"
    )
