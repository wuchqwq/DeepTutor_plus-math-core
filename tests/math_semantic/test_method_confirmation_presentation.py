"""PR #13 counterexample as safety regression through the actual host chain."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json

import pytest
import pytest_asyncio

from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager
from deeptutor.services.session.turns.title_service import SessionTitleService
from deeptutor.tools.ask_user import build_ask_user_payload

from .recovery_support import A, B, harmless_generation
from .test_routing_isolation import RoutingHost

PRIVATE_METHODS = ("Factorization", "Final answer x = 42")


def assert_private_methods_absent(value):
    serialized = json.dumps(value)
    assert all(method not in serialized for method in PRIVATE_METHODS)


@pytest_asyncio.fixture
async def hostile_host_factory(tmp_path, monkeypatch):
    hosts = []
    monkeypatch.setattr("deeptutor.services.skill.runtime.skill_manifest", lambda: "")
    monkeypatch.setattr(
        "deeptutor.services.llm.factory._complete_with_resolved_config", harmless_generation
    )

    def create():
        host = RoutingHost(tmp_path / f"hostile-method-{len(hosts)}.db", unknown=False)
        assert len(host.source.authored.paths) == 2
        host.source = replace(
            host.source,
            authored=replace(
                host.source.authored,
                paths=tuple(
                    replace(path, method=method)
                    for path, method in zip(
                        host.source.authored.paths, PRIVATE_METHODS, strict=True
                    )
                ),
            ),
        )
        assert all(a.verification_status != "verified" for a in host.source.authored.artifacts)
        assert all(
            method not in artifact.statement
            for method in PRIVATE_METHODS
            for artifact in host.source.authored.artifacts
        )
        host.scope = host.math_scope()
        # Retain real merged B1 behavior, rather than the helper's no-title stub.
        del host.runtime._maybe_generate_session_title
        assert (
            host.runtime._maybe_generate_session_title.__func__
            is SessionTitleService._maybe_generate_session_title
        )
        hosts.append(host)
        return host

    yield create
    for host in reversed(hosts):
        await host.close()


@pytest.mark.asyncio
async def test_hostile_method_text_is_private_before_acceptance_and_on_replay(
    hostile_host_factory, monkeypatch
):
    host = hostile_host_factory()
    generated = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def generation(*args, **kwargs):
        generated.append(json.loads(kwargs["prompt"]))
        if len(generated) == 2:
            entered.set()
            await release.wait()
        return await harmless_generation(*args, **kwargs)

    monkeypatch.setattr("deeptutor.services.llm.factory._complete_with_resolved_config", generation)
    try:
        session, seed = await host.submit(A)
        assert host.result()["verification_status"] == "UNKNOWN"
        _, turn = await host.start(B, session_id=session["id"])
        card = await host.choice(turn)
        context = host.math_contexts[-1]
        row = host.user_row(context.runtime.accepted_user_message_id)
        assert row["content"] == context.runtime.accepted_user_content == B
        assert row["metadata"]["turn_id"] == turn["id"]
        assert row["metadata"]["host_capability_binding"]["binding"]["capability"] == "math_turn"
        assert [option["label"] for option in card["options"]] == ["Method 1", "Method 2"]
        assert card["allow_free_text"] is False
        assert_private_methods_absent(card)
        token = card["options"][1]["option_id"]
        issued = host.state()["confirmations"][card["id"]]
        path = dict(issued["option_paths"])[token]
        assert issued["state"] == "pending"
        assert path == host.source.authored.paths[1].path_id
        assert token not in {path, "Method 2", "2", *PRIVATE_METHODS}
        assert turn["id"] not in host.state()["host_math_publications"]
        assert context.capability_output.accepted_output is None
        assert len(generated) == 1
        events = list(host.runtime._executions[turn["id"]].events)
        tool = next(e for e in events if e["type"] == "tool_result")
        wait = next(e for e in events if e["type"] == "wait_for_input")
        assert tool["metadata"]["tool"] == "ask_user"
        assert tool["metadata"]["tool_call_id"] == card["id"]
        assert tool["seq"] < wait["seq"]
        assert_private_methods_absent(events)
        assert not any(e["type"] in {"content", "result"} for e in events)
        assert (await host.store.get_turn(turn["id"]))["status"] == "waiting_input"

        # Deliberately contradictory client text cannot change token identity.
        assert await host.runtime.submit_user_reply(
            turn["id"],
            answers=[{"questionId": card["id"], "selected_option_id": token, "text": "Method 1"}],
        )
        await asyncio.wait_for(entered.wait(), 15)
        events = list(host.runtime._executions[turn["id"]].events)
        progress = next(e for e in events if e["metadata"].get("ask_user_resolved"))
        assert progress["type"] == "progress"
        assert progress["metadata"]["ask_user_tool_call_id"] == card["id"]
        assert progress["metadata"]["answers"] == [
            {"questionId": card["id"], "selected_option_id": token, "text": "Method 2"}
        ]
        assert_private_methods_absent(events)
        resolved = host.state()["confirmations"][card["id"]]
        assert resolved["state"] == "resolved"
        assert resolved["chosen_path_ref"] == path
        assert resolved["option_paths"] == issued["option_paths"]
        assert len(host.state()["confirmations"]) == 1
        assert host.result()["verification_status"] == "UNKNOWN"
        assert host.result()["verified_grounded_refs"] == ()
        # Confirmation authorizes no truth/result. Independently executed
        # operation support can still supply a bounded algebraic next step.
        assert all(
            g["act_kind"] in {"orientation", "chosen_operation", "operation_options"}
            for g in host.result()["authority"]
        )
        assert all(o["grant"]["act_kind"] != "result" for o in generated[-1]["offers"])
        assert turn["id"] not in host.state()["host_math_publications"]
        assert context.capability_output.accepted_output is None
        assert not any(e["type"] in {"content", "result"} for e in events)

        release.set()
        await host.finish(turn)
        receipt = host.state()["host_math_publications"][turn["id"]]
        assert receipt["content"] == "Mathematical evidence recorded."
        assert context.capability_output.accepted_output.content == receipt["content"]
        durable = await host.store.get_turn_events(turn["id"])
        for event in (tool, wait, progress):
            assert (
                next(e for e in durable if e["seq"] == event["seq"])["metadata"]
                == event["metadata"]
            )
        assert progress["seq"] < next(e["seq"] for e in durable if e["type"] == "content")
        assert_private_methods_absent(durable)
        assert_private_methods_absent(await host.store.get_turn_events(seed["id"]))
        assert (await host.store.get_session(session["id"]))["title"] == "New conversation"
        assert not any(e["type"] == "session_meta" for e in durable)
    finally:
        release.set()
        await host.close()

    # Fresh durable replay with no old reply queue, reviewed DI or journal.
    coordinator = MemoryCoordinator()
    fresh = TurnRuntimeManager(SQLiteSessionStore(host.db), coordinator=coordinator)
    try:
        replay = [event async for event in fresh.subscribe_turn(turn["id"])]
        assert_private_methods_absent(replay)
        for event in (tool, wait, progress):
            assert (
                next(e for e in replay if e["seq"] == event["seq"])["metadata"] == event["metadata"]
            )
        assert len(generated) == 2
    finally:
        await fresh.close()
        await coordinator.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "choice",
    [
        "forged",
        "foreign_token",
        "stale_question",
        "label",
        "ordinal",
        "raw_method",
        "path",
        "free_text",
    ],
)
async def test_neutral_display_does_not_grant_confirmation_identity(hostile_host_factory, choice):
    host = hostile_host_factory()
    session, _ = await host.submit(A)
    _, turn = await host.start(B, session_id=session["id"])
    card = await host.choice(turn)
    before = host.state()
    option = card["options"][1]
    answer = {
        "questionId": card["id"],
        "selected_option_id": option["option_id"],
        "text": "Method 2",
    }
    if choice == "foreign_token":
        foreign = hostile_host_factory()
        foreign.source = replace(
            foreign.source,
            identity=replace(foreign.source.identity, episode_id="foreign-episode"),
            authored=replace(
                foreign.source.authored,
                workspace=replace(
                    foreign.source.authored.workspace, workspace_id="foreign-episode"
                ),
            ),
        )
        foreign.scope = foreign.math_scope()
        other_session, _ = await foreign.submit(A)
        _, other_turn = await foreign.start(B, session_id=other_session["id"])
        other_card = await foreign.choice(other_turn)
        answer["selected_option_id"] = other_card["options"][1]["option_id"]
        assert answer["selected_option_id"] != option["option_id"]
    elif choice == "stale_question":
        answer["questionId"] = "stale-confirmation-id"
    elif choice == "free_text":
        answer.pop("selected_option_id")
    else:
        answer["selected_option_id"] = {
            "forged": "forged-token",
            "label": option["label"],
            "ordinal": "2",
            "raw_method": PRIVATE_METHODS[1],
            "path": host.source.authored.paths[1].path_id,
        }[choice]
    assert await host.runtime.submit_user_reply(turn["id"], answers=[answer])
    await host.finish(turn, status="failed")
    assert host.errors and "confirmation" in str(host.errors[-1])
    assert host.state() == before
    assert before["confirmations"][card["id"]]["state"] == "pending"
    assert before["confirmations"][card["id"]]["chosen_path_ref"] is None
    context = host.math_contexts[-1]
    assert context.capability_output.accepted_output is None
    assert turn["id"] not in host.state()["host_math_publications"]
    events = await host.store.get_turn_events(turn["id"])
    assert not any(e["type"] in {"content", "result"} for e in events)
    assert not any(e["metadata"].get("ask_user_resolved") for e in events)
    assert_private_methods_absent(events)


def test_ordinary_ask_user_preserves_its_authored_labels():
    # Negative control: math-specific presentation must not globally alter ask_user.
    payload, error = build_ask_user_payload(
        questions=[
            {
                "id": "ordinary-choice",
                "prompt": "Choose an ordinary topic.",
                "options": [
                    {"label": method, "option_id": f"ordinary-{index}"}
                    for index, method in enumerate(PRIVATE_METHODS)
                ],
            }
        ]
    )
    assert error is None
    question = payload.to_dict()["questions"][0]
    assert [o["label"] for o in question["options"]] == list(PRIVATE_METHODS)
    assert [o["option_id"] for o in question["options"]] == ["ordinary-0", "ordinary-1"]
