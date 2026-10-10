"""Offline qualification and native host tests; selections are not model evidence."""

from contextlib import closing
from dataclasses import replace
import json
import sqlite3

import pytest

from deeptutor.capabilities.math_turn import output
from deeptutor.math_semantic.authority import math_content_digest
from deeptutor.math_semantic.codec import _decode, _payload
from deeptutor.math_semantic.contracts import MathArtifact, ToolEvidence
from deeptutor.math_semantic.proposals import AlignmentProposal
from deeptutor.math_semantic.state import MathMutation
from deeptutor.math_semantic.support import connection_request
from deeptutor.math_semantic.tools import MathToolRegistry

from .test_goal_connection import aligned, offers, prepare, reviewed_case
from .test_publication import Generation, assistant_row, replay
from .test_publication import publication_host_factory as _publication_host_factory
from .test_student_step_evidence import FALSE, state_for

publication_host_factory = _publication_host_factory


def inquire(previous, *, interaction="question", uncertainty=None):
    state = state_for(
        previous.source,
        "Explain the previous checked step's connection to the goal.",
        prefix=previous.prefix,
        payload=previous.serialize(),
    )
    proposal = AlignmentProposal.from_value({"claims": [], "interaction_type": interaction})
    state.align(
        proposal,
        expected_revision=state.snapshot().workspace.revision,
        provider_id="offline",
        config_digest="offline",
        check_steps=True,
    )
    if uncertainty is not None:
        for slot in state._records["alignments"]:
            if slot.startswith(state.submission.response_id + ":"):
                state._records["alignments"][slot] = _payload(
                    replace(_decode(state._records["alignments"][slot]), uncertainty=uncertainty)
                )
    return state


@pytest.mark.parametrize("kind", ["s4", "linear"])
def test_first_explanation_uses_original_claim_without_prior_justification(kind):
    reviewed, step = reviewed_case(kind)
    prior = aligned(reviewed, step)  # native local check only; no connection or publication
    before = prior.serialize()
    original_evidence = prior.snapshot().tool_evidence
    question = inquire(prior)
    request = prepare(question)
    assert request is not None and prior.serialize() == before
    origin = request["historical_claim_origin"]
    assert origin["accepted_user_message_id"] == prior.submission.message_id
    assert (
        origin["submission_digest"]
        == request["submission_digest"]
        == math_content_digest(prior.submission)
    )
    assert origin["inquiry_digest"] == math_content_digest(question.submission)
    assert all(e in question.snapshot().tool_evidence for e in original_evidence)
    assert len(question.snapshot().tool_evidence) == len(original_evidence) + 1
    calc, inputs, choices = offers(question)
    assert len(choices) == 1
    accepted = output.accept_response(
        question,
        calc,
        inputs,
        json.dumps(
            {"authority_basis": inputs["authority_basis"], "grant_ids": [choices[0]["grant_id"]]}
        ),
    )
    receipt = json.loads(accepted.metadata_json)["math_publication"]
    assert receipt["basis"]["accepted_user_message_id"] == question.submission.message_id
    reference = receipt["historical_claim_references"][0]
    assert reference["origin"] == origin
    assert (
        reference["claim_ref"] == request["claim_ref"]
        and reference["step_ref"] == request["step_ref"]
    )
    assert reviewed.reviewed_connection.canonical_explanation in accepted.content
    assert question.submission.message_id != prior.submission.message_id


@pytest.mark.parametrize("latest", ["changed", "unknown", "unclear", "two_claims", "empty_answer"])
def test_latest_substantive_submission_blocks_older_matching_claim(latest):
    reviewed, step = reviewed_case()
    prior = aligned(reviewed, step)
    changed = state_for(
        reviewed,
        FALSE if latest != "two_claims" else step + "\n" + FALSE,
        prefix=prior.prefix,
        payload=prior.serialize(),
    )
    claims = (
        []
        if latest in {"unclear", "empty_answer"}
        else [{"evidence": {"quote": FALSE}, "claim_type": "equation", "parse_status": "parsed"}]
    )
    if latest == "two_claims":
        claims.insert(
            0, {"evidence": {"quote": step}, "claim_type": "equation", "parse_status": "parsed"}
        )
    if latest == "unknown":
        claims[0]["parse_status"] = "unparsed"
    changed.align(
        AlignmentProposal.from_value(
            {"claims": claims, "interaction_type": "unclear" if latest == "unclear" else "answer"}
        ),
        expected_revision=changed.snapshot().workspace.revision,
        provider_id="offline",
        config_digest="offline",
        check_steps=True,
    )
    question = inquire(changed)
    assert prepare(question) is None and offers(question)[2] == []


@pytest.mark.parametrize(
    "bad", ["unreviewed", "uncertain_inquiry", "question_with_claim", "path", "tool", "origin_row"]
)
def test_historical_qualification_fails_closed(bad):
    reviewed, step = reviewed_case("linear")
    if bad == "unreviewed":
        reviewed = replace(reviewed, reviewed_connection=None)
    prior = aligned(reviewed, step)
    question = inquire(prior, uncertainty=0.3 if bad == "uncertain_inquiry" else None)
    if bad == "question_with_claim":
        question = aligned(reviewed, step, prefix=prior.prefix, payload=prior.serialize())
        slot = next(
            k
            for k, a in question._records["alignments"].items()
            if str(question.submission.message_id) + ":" in k
        )
        question._records["alignments"][slot] = _payload(
            replace(_decode(question._records["alignments"][slot]), interaction_type="question")
        )
    elif bad == "path":
        question.append(
            expected_revision=question.snapshot().workspace.revision,
            paths=(
                replace(
                    question.snapshot().paths[0],
                    method="altered path",
                    path_id=None,
                    workspace_revision=question.snapshot().workspace.revision + 1,
                ),
            ),
        )
    elif bad == "tool":
        question._records["snapshots"][str(question.snapshot().workspace.revision)][
            "tool_evidence"
        ][0]["output_summary"] = "altered"
        with pytest.raises(ValueError, match="altered tool receipt"):
            prepare(question)
        return
    elif bad == "origin_row":
        question = MathMutation(
            reviewed,
            question.submission,
            (replace(prior.submission, message_id=99), question.submission),
            question.serialize(),
        )
    assert prepare(question) is None and offers(question)[2] == []


def test_revision_count_can_change_but_current_acceptance_is_pinned():
    from deeptutor.capabilities.math_turn import output

    reviewed, step = reviewed_case()
    prior = aligned(reviewed, step)
    question = inquire(prior)
    # An auxiliary counter fixture is not mathematical support. Evidence-only
    # revisions may advance without changing the submitted step's math basis.
    counter = ToolEvidence(
        tool_name="clarification_counter",
        tool_version="test_only",
        input_summary="pure-inquiry-count",
        output_summary="no-math",
        scope="test_counter_only",
        status="succeeded",
        duration_ms=0,
    )
    question.append(expected_revision=question.snapshot().workspace.revision, evidence=(counter,))
    assert prepare(question) is not None
    calc, inputs, choices = offers(question)
    question.append(expected_revision=question.snapshot().workspace.revision, status="advanced")
    with pytest.raises(ValueError, match="stale or foreign"):
        output.accept_response(
            question,
            calc,
            inputs,
            json.dumps(
                {
                    "authority_basis": inputs["authority_basis"],
                    "grant_ids": [choices[0]["grant_id"]],
                }
            ),
        )


def test_new_matching_claim_replaces_old_origin_without_reusing_old_step():
    reviewed, step = reviewed_case()
    old = aligned(reviewed, step)
    latest = aligned(reviewed, step, prefix=old.prefix, payload=old.serialize())
    question = inquire(latest)
    request = prepare(question)
    assert (
        request["historical_claim_origin"]["accepted_user_message_id"]
        == latest.submission.message_id
    )
    assert request["submission_digest"] == math_content_digest(latest.submission)
    assert (
        request["historical_claim_origin"]["accepted_user_message_id"] != old.submission.message_id
    )
    alignment = max(
        (
            _decode(v)
            for v in latest._records["alignments"].values()
            if _decode(v).student_response_ref.identifier == latest.submission.response_id
        ),
        key=lambda a: a.workspace_revision,
    )
    assert request["claim_ref"] == alignment.claims[0].claim_id
    assert request["step_ref"] in [e.evidence_id for e in alignment.math_evidence]


@pytest.mark.parametrize("changed", ["episode", "source", "premise", "domain", "path", "permit"])
def test_historical_source_scope_cannot_be_changed_or_retroactively_rebound(changed):
    reviewed, step = reviewed_case("linear")
    question = inquire(aligned(reviewed, step))
    with pytest.raises(ValueError):
        if changed == "episode":
            replacement = replace(reviewed, identity=replace(reviewed.identity, episode_id="other"))
        elif changed == "permit":
            replacement = replace(
                reviewed,
                reviewed_connection=replace(
                    reviewed.reviewed_connection, canonical_explanation="Changed permission"
                ),
            )
        elif changed == "path":
            replacement = replace(
                reviewed,
                authored=replace(
                    reviewed.authored,
                    paths=(replace(reviewed.authored.paths[0], method="different method"),),
                ),
            )
        else:
            model = reviewed.authored.problem_model
            if changed == "premise":
                model = replace(
                    model, givens=(replace(model.givens[0], value="u=2*v+2"), *model.givens[1:])
                )
            elif changed == "domain":
                model = replace(model, domain=())
            else:
                model = replace(model, target=replace(model.target, value="different goal"))
            replacement = replace(
                reviewed, authored=replace(reviewed.authored, problem_model=model)
            )
        MathMutation(replacement, question.submission, question.prefix, question.serialize())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "approved",
        "source_changed",
        "tools_source_changed",
        "ownership_lost",
        "waiting_source_changed",
    ],
)
async def test_native_inquiry_after_local_confirmation_and_E_without_justification(
    publication_host_factory, monkeypatch, mode
):
    from deeptutor.capabilities.math_turn import capability

    init = capability.MathTurnCapability.__init__

    def initialize(self, *, resolve_episode, provider):
        provider.propose = lambda p: (
            {"claims": [], "interaction_type": "question"}
            if p.response_text.startswith("Explain")
            else {
                "claims": [
                    {
                        "evidence": {"quote": p.response_text.split("\n")[0]},
                        "claim_type": "equation",
                        "parse_status": "parsed",
                    }
                ],
                "interaction_type": "answer",
            }
        )
        init(self, resolve_episode=resolve_episode, provider=provider)

    monkeypatch.setattr(capability.MathTurnCapability, "__init__", initialize)
    host, generation, _ = publication_host_factory()
    reviewed, step = reviewed_case()
    E = MathArtifact(
        "3*(x^2-x*y+y^2)-(x^2+x*y+y^2)=2*(x-y)^2",
        "intermediate",
        provenance=reviewed.authored.artifacts[0].provenance,
        verification_status="qualified",
        verification_scope="reviewed operation input",
    )
    host.source = replace(
        reviewed,
        authored=replace(
            reviewed.authored,
            artifacts=(*reviewed.authored.artifacts, E),
            paths=tuple(
                replace(p, artifact_refs=(*p.artifact_refs, E.artifact_id))
                for p in reviewed.authored.paths
            ),
        ),
    )
    host.scope = host.math_scope()
    original_generate = Generation.__call__

    async def select(self, *args, **kwargs):
        candidate = json.loads(await original_generate(self, *args, **kwargs))
        inputs = self.calls[-1]["inputs"]
        if len(self.calls) == 1:
            choices = [
                o
                for o in inputs["offers"]
                if o["grant"]["act_kind"] == "local_confirmation"
                or (
                    o["grant"]["act_kind"] == "chosen_operation"
                    and o["grant"]["target_artifact_ref"] == E.artifact_id
                )
            ]
            assert len(choices) == 2
        else:
            choices = [o for o in inputs["offers"] if o["grant"]["act_kind"] == "justification"]
            assert len(choices) == 1
            if mode == "source_changed":
                host.source = replace(host.source, reviewed_connection=None)
            if mode == "ownership_lost":
                assert await host.coordinator.release_turn(
                    host.math_contexts[-1].runtime.turn_lease
                )
            if mode == "waiting_source_changed":
                context = host.math_contexts[-1]
                protected = context.runtime.run_durable_turn_mutation

                async def revoke(mutation, **options):
                    host.source = replace(host.source, reviewed_connection=None)
                    return await protected(mutation, **options)

                context.runtime.run_durable_turn_mutation = revoke
        candidate["grant_ids"] = [o["grant_id"] for o in choices]
        raw = json.dumps(candidate)
        self.raw_candidates[-1] = raw
        return raw

    monkeypatch.setattr(Generation, "__call__", select)
    _, first = await host.start(step)
    await host.finish(first)
    original_row = assistant_row(host, first["id"])
    with closing(sqlite3.connect(host.db)) as db:
        original_bytes = db.execute(
            "SELECT content,metadata_json FROM messages WHERE id=?", (original_row[0],)
        ).fetchone()
    original_replay = await replay(host, first)
    original_receipt = original_row[2]["accepted_output"]["math_publication"]
    assert [g["act_kind"] for g in original_receipt["selected_grants"]] == ["chosen_operation"]
    assert original_receipt["selected_feedback"][0]["act_kind"] == "local_confirmation"
    original_state = host.state()
    if mode == "tools_source_changed":
        materialize = capability.materialize_connection_support

        def revoke(request):
            result = materialize(request)
            if request and "historical_claim_origin" in request:
                host.source = replace(host.source, reviewed_connection=None)
            return result

        monkeypatch.setattr(capability, "materialize_connection_support", revoke)
    original_call = MathToolRegistry.call
    subsequent_calls = []

    def observe_call(self, *args, **kwargs):
        subsequent_calls.append(kwargs)
        return original_call(self, *args, **kwargs)

    monkeypatch.setattr(MathToolRegistry, "call", observe_call)
    _, second = await host.start(
        "Explain the previous checked step's connection to the goal.",
        session_id=first["session_id"],
    )
    await host.finish(second, status="completed" if mode == "approved" else "failed")
    assert assistant_row(host, first["id"]) == original_row
    with closing(sqlite3.connect(host.db)) as db:
        assert (
            db.execute(
                "SELECT content,metadata_json FROM messages WHERE id=?", (original_row[0],)
            ).fetchone()
            == original_bytes
        )
    assert not any("timeout_ms" in c for c in subsequent_calls)  # no historical step recheck
    if mode != "approved":
        assert len(generation.calls) == (1 if mode == "tools_source_changed" else 2)
        if mode != "ownership_lost":
            assert any("source changed" in str(e) for e in host.errors)
        assert not any(e["type"] in {"content", "result"} for e in await replay(host, second))
        return
    row = assistant_row(host, second["id"])
    receipt = row[2]["accepted_output"]["math_publication"]
    assert host.source.reviewed_connection.canonical_explanation in row[1]
    assert receipt["basis"]["turn_id"] == second["id"]
    assert receipt["historical_claim_references"][0]["origin"]["turn_id"] == first["id"]
    original_alignments = original_state["alignments"]
    assert all(host.state()["alignments"][k] == v for k, v in original_alignments.items())
    stable = host.state()

    def no_repeat(*args, **kwargs):
        pytest.fail("replay recomputed model, tools or mutation")

    monkeypatch.setattr(Generation, "__call__", no_repeat)
    monkeypatch.setattr(MathToolRegistry, "call", no_repeat)
    monkeypatch.setattr(capability, "sqlite_episode_mutation", no_repeat)
    assert await replay(host, first) == await replay(host, first) == original_replay
    assert await replay(host, second) == await replay(host, second)
    assert host.state() == stable and assistant_row(host, first["id"]) == original_row
