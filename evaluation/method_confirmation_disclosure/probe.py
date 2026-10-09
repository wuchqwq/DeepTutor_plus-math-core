"""Opt-in B2 counterexample, never a default safety regression.

Exit 0 asserts that disclosure WAS reproduced on the pinned baseline. It is
not a publication-safety PASS. This script changes no product code.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import patch

from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.services.config.provider_runtime import ResolvedLLMConfig
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager
from tests.math_semantic.recovery_support import A, B, harmless_generation
from tests.math_semantic.test_routing_isolation import RoutingHost

DISCLOSURE = "Final answer x = 42"


async def wait_until(read, predicate):
    async with asyncio.timeout(15):
        while True:
            value = read()
            if predicate(value):
                return value
            await asyncio.sleep(0.01)


async def run(db: Path) -> dict:
    if db.exists():
        raise ValueError("choose a fresh isolated probe database")
    db.parent.mkdir(parents=True, exist_ok=True)
    generated = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def generation(*args, **kwargs):
        inputs = json.loads(kwargs["prompt"])
        generated.append(inputs)
        if len(generated) == 2:
            entered.set()
            await release.wait()
        return await harmless_generation(*args, **kwargs)

    with (
        patch("deeptutor.services.skill.runtime.skill_manifest", lambda: ""),
        patch(
            "deeptutor.services.llm.config.resolve_llm_runtime_config",
            lambda *args, **kwargs: ResolvedLLMConfig(
                model="gpt-4o-mini",
                provider_name="openai",
                provider_mode="direct",
                binding="openai",
                api_key="sk-test",
                base_url="https://api.openai.com/v1",
                effective_url="https://api.openai.com/v1",
                context_window=128000,
            ),
        ),
        patch("deeptutor.services.llm.config._LLM_CONFIG_CACHE", None),
        patch("deeptutor.services.llm.factory._complete_with_resolved_config", generation),
    ):
        host = RoutingHost(db, unknown=False)
        # Keep the two authored paths, IDs and mathematical content. Only the
        # reviewed display-like method field is adversarial, as requested.
        assert len(host.source.authored.paths) == 2
        host.source = replace(
            host.source,
            authored=replace(
                host.source.authored,
                paths=tuple(
                    replace(path, method=method)
                    for path, method in zip(
                        host.source.authored.paths, ("Factorization", DISCLOSURE), strict=True
                    )
                ),
            ),
        )
        assert all(a.verification_status != "verified" for a in host.source.authored.artifacts)
        assert all(DISCLOSURE not in a.statement for a in host.source.authored.artifacts)
        host.scope = host.math_scope()
        # Run the real title owner too: merged B1 must not be replaced by a no-op.
        del host.runtime._maybe_generate_session_title
        try:
            session, seed = await host.submit(A)
            assert host.result()["verification_status"] == "UNKNOWN"
            assert all(g["act_kind"] == "orientation" for g in host.result()["authority"])
            _, turn = await host.start(B, session_id=session["id"])
            card = await host.choice(turn)
            context = host.math_contexts[-1]
            row = host.user_row(context.runtime.accepted_user_message_id)
            assert row["content"] == context.runtime.accepted_user_content == B
            assert (
                row["metadata"]["host_capability_binding"]["binding"]["capability"] == "math_turn"
            )
            malicious = next(option for option in card["options"] if option["label"] == DISCLOSURE)
            token = malicious["option_id"]
            state = host.state()
            issued = state["confirmations"][card["id"]]
            path = dict(issued["option_paths"])[token]
            assert issued["state"] == "pending"
            assert path == host.source.authored.paths[1].path_id
            assert token != path and token != DISCLOSURE
            assert turn["id"] not in state["host_math_publications"]
            assert context.capability_output.accepted_output is None
            assert len(generated) == 1  # No final proposal/acceptance for this turn yet.
            events = list(host.runtime._executions[turn["id"]].events)
            tool = next(event for event in events if event["type"] == "tool_result")
            wait = next(event for event in events if event["type"] == "wait_for_input")
            assert DISCLOSURE in json.dumps(tool["metadata"])
            assert "math_publication" not in tool["metadata"]
            assert DISCLOSURE not in json.dumps(wait)
            assert tool["seq"] < wait["seq"]
            assert not any(event["type"] in {"content", "result"} for event in events)
            assert (await host.store.get_turn(turn["id"]))["status"] == "waiting_input"

            # Resolve using the exact issued token; client reply text is unrelated.
            await host.answer(turn, card, token=token)
            await asyncio.wait_for(entered.wait(), 15)
            events = await wait_until(
                lambda: list(host.runtime._executions[turn["id"]].events),
                lambda values: any(e["metadata"].get("ask_user_resolved") for e in values),
            )
            progress = next(e for e in events if e["metadata"].get("ask_user_resolved"))
            assert progress["type"] == "progress"
            assert progress["metadata"]["answers"][0]["text"] == DISCLOSURE
            assert "math_publication" not in progress["metadata"]
            resolved = host.state()["confirmations"][card["id"]]
            assert resolved["state"] == "resolved" and resolved["chosen_path_ref"] == path
            assert host.result()["verification_status"] == "UNKNOWN"
            assert host.result()["verified_grounded_refs"] == ()
            assert all(g["act_kind"] == "orientation" for g in host.result()["authority"])
            assert all(o["grant"]["act_kind"] == "orientation" for o in generated[-1]["offers"])
            assert turn["id"] not in host.state()["host_math_publications"]
            assert context.capability_output.accepted_output is None
            assert not any(event["type"] in {"content", "result"} for event in events)

            release.set()
            await host.finish(turn)
            receipt = host.state()["host_math_publications"][turn["id"]]
            assert receipt["content"] == "Mathematical evidence recorded."
            durable = await host.store.get_turn_events(turn["id"])
            assert (
                next(e for e in durable if e["seq"] == tool["seq"])["metadata"] == tool["metadata"]
            )
            assert (
                next(e for e in durable if e["seq"] == wait["seq"])["metadata"] == wait["metadata"]
            )
            assert (
                next(e for e in durable if e["seq"] == progress["seq"])["metadata"]
                == progress["metadata"]
            )
            assert progress["seq"] < next(e["seq"] for e in durable if e["type"] == "content")
            assert (await host.store.get_session(session["id"]))["title"] == "New conversation"
            assert not any(e["type"] == "session_meta" for e in durable)
        finally:
            release.set()
            await host.close()

    # Replay uses fresh host objects and the durable DB, without reviewed DI,
    # the old reply queue, old coordinator journal or capability reexecution.
    coordinator = MemoryCoordinator()
    fresh = TurnRuntimeManager(SQLiteSessionStore(db), coordinator=coordinator)
    try:
        replay = [event async for event in fresh.subscribe_turn(turn["id"])]
        for event in (tool, wait, progress):
            assert (
                next(e for e in replay if e["seq"] == event["seq"])["metadata"] == event["metadata"]
            )
        assert DISCLOSURE in json.dumps(replay)
        assert len(generated) == 2
        return {
            "B2_METHOD_CONFIRMATION_DISCLOSURE": "BLOCKER",
            "accepted_user_message_id": row["id"],
            "turn_id": turn["id"],
            "episode_id": host.source.identity.episode_id,
            "verification": "UNKNOWN",
            "authority_kinds": sorted({g["act_kind"] for g in host.result()["authority"]}),
            "tool_result_label": malicious["label"],
            "wait_for_input_contains_disclosure": False,
            "resolved_progress_text": progress["metadata"]["answers"][0]["text"],
            "tool_seq": tool["seq"],
            "wait_seq": wait["seq"],
            "progress_seq": progress["seq"],
            "durable_replay_contains_disclosure": True,
            "approved_body": receipt["content"],
            "body_contains_disclosure": DISCLOSURE in receipt["content"],
        }
    finally:
        await fresh.close()
        await coordinator.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="fresh isolated SQLite database")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.db)), ensure_ascii=False, sort_keys=True))
