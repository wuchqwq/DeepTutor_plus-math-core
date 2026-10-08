"""Reopen actual host objects and terminate actual workers, never old bindings."""

from __future__ import annotations

import asyncio
from contextlib import closing
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

from deeptutor.math_semantic.state import ReviewedSource
from deeptutor.services.session.protocol import ActiveTurnConflict

from .recovery_support import A, B, C, RecoveryHost, assert_evidence_preserved, durable


@pytest.mark.asyncio
async def test_closed_runtime_store_coordinator_reopen_without_binding(tmp_path):
    db = tmp_path / "reopen.db"
    old = RecoveryHost(db, advance=True)
    try:
        session, turn = await old.submit(A)
        before, trajectory, authority = (
            durable(db),
            old.result()["trajectory"],
            old.result()["authority"],
        )
    finally:
        await old.close()
    fresh = RecoveryHost(db)
    try:
        assert fresh.runtime is not old.runtime and fresh.coordinator is not old.coordinator
        assert fresh.store is not old.store and fresh.source is not old.source
        assert fresh.runtime._executions == {} and fresh.runtime._reply_queues == {}
        assert await fresh.coordinator.get_lease(turn["id"]) is None
        # Only same DB and reviewed source identity survive. No accepted start,
        # prefix or MathEpisodeBinding is copied to this new composition.
        await fresh.submit(A, session_id=session["id"])
        accepted = fresh.contexts[-1].runtime
        rows = await fresh.store.get_messages(session["id"])
        row = next(row for row in rows if row["id"] == accepted.accepted_user_message_id)
        assert row["role"] == "user" and row["content"] == accepted.accepted_user_content == A
        assert (
            accepted.accepted_user_message_id
            == durable(db)["state"]["host_accepted_message_ids"][-1]
        )
        assert accepted.accepted_user_message_id not in before["state"]["host_accepted_message_ids"]
        history = fresh.history[-1]
        assert history["trajectory"] == trajectory
        assert history["authority"] == list(authority)
        assert history["head"] == before["revision"] > fresh.source.authored.workspace.revision
        assert history["prefix"] == before["state"]["host_accepted_message_ids"]
        assert_evidence_preserved(before, durable(db), new_alignments=1)
        # Old event replay is read-only; it neither runs capability nor writes
        # another alignment/confirmation/projection.
        committed = durable(db)
        executions = len(fresh.contexts)
        async with asyncio.timeout(5):
            first = [event async for event in fresh.runtime.subscribe_turn(turn["id"])]
            second = [event async for event in fresh.runtime.subscribe_turn(turn["id"])]
        assert first == second and first and durable(db) == committed
        assert len(fresh.contexts) == executions and turn["id"] not in fresh.runtime._executions
    finally:
        await fresh.close()


@pytest.mark.asyncio
async def test_pending_survives_graceful_destroy_and_exact_explicit_resolution(tmp_path):
    db = tmp_path / "pending.db"
    old = RecoveryHost(db)
    try:
        session, _ = await old.submit(A)
        _, turn = await old.start(B, session_id=session["id"])
        card = await old.choice(turn)
        before = durable(db)
        assert before["state"]["confirmations"][card["id"]]["state"] == "pending"
    finally:
        await old.close()
    assert durable(db) == before
    fresh = RecoveryHost(db)
    try:
        assert not await fresh.runtime.submit_user_reply(turn["id"], answers=[])
        _, new_turn = await fresh.start(C, session_id=session["id"])
        recovered = await fresh.choice(new_turn)
        assert recovered == card
        waiting = durable(db)
        assert_evidence_preserved(before, waiting, new_alignments=1)
        assert new_turn["id"] not in fresh.completed
        assert not fresh.contexts[-1].capability_output.event_metadata
        assert waiting["state"]["confirmations"][card["id"]]["state"] == "pending"
        await fresh.answer(new_turn, recovered)
        await fresh.finish(new_turn)
        after = durable(db)
        resolved = after["state"]["confirmations"][card["id"]]
        assert len(after["state"]["confirmations"]) == 1
        assert resolved["state"] == "resolved"
        assert (
            resolved["chosen_path_ref"]
            == before["state"]["confirmations"][card["id"]]["option_paths"][-1][1]
        )
    finally:
        await fresh.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["forged", "stale_question", "label", "head_drift"])
async def test_recovered_confirmation_rejects_stale_or_forged_reply(tmp_path, choice, monkeypatch):
    db = tmp_path / "rejected-reply.db"
    old = RecoveryHost(db)
    try:
        session, _ = await old.submit(A)
        _, turn = await old.start(B, session_id=session["id"])
        original_card = await old.choice(turn)
        before = durable(db)
    finally:
        await old.close()
    if choice == "head_drift":
        from deeptutor.capabilities.math_turn import capability

        original = capability.confirm_method

        async def advance_then_confirm(authority, issued, **kwargs):
            # After the actual new waiter has restored running, change the
            # durable head through that new turn's real protected port. The
            # old exact token must not resolve against this different head.
            await authority(
                lambda state: state.append(
                    expected_revision=state.snapshot().workspace.revision, status="partial"
                )
            )
            return await original(authority, issued, **kwargs)

        monkeypatch.setattr(capability, "confirm_method", advance_then_confirm)
    fresh = RecoveryHost(db)
    try:
        _, turn = await fresh.start(B, session_id=session["id"])
        card = await fresh.choice(turn)
        assert card == original_card
        waiting = durable(db)
        assert_evidence_preserved(before, waiting, new_alignments=1)
        await fresh.answer(
            turn,
            card,
            token="forged-token"
            if choice == "forged"
            else card["options"][-1]["label"]
            if choice == "label"
            else None,
            question_id="stale-confirmation-id" if choice == "stale_question" else None,
        )
        await fresh.finish(turn, error="confirmation")
        after = durable(db)
        confirmation = after["state"]["confirmations"][card["id"]]
        if choice == "head_drift":
            assert confirmation["state"] == "invalidated"
            assert confirmation["chosen_path_ref"] is None
            assert after["revision"] == waiting["revision"] + 1
            assert after["state"]["alignments"] == waiting["state"]["alignments"]
        else:
            assert after == waiting
            assert confirmation["state"] == "pending"
    finally:
        await fresh.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "damage", ["start", "prefix", "row", "turn", "revision", "learner", "source"]
)
async def test_recovered_basis_is_revalidated_and_never_reinitialized(tmp_path, damage):
    db = tmp_path / "revalidate.db"
    old = RecoveryHost(db)
    try:
        session, _ = await old.submit(A)
    finally:
        await old.close()
    record = durable(db)
    with closing(sqlite3.connect(db)) as connection, connection:
        value = record["state"]
        if damage == "start":
            value.pop("host_episode_first_message_id")
        elif damage == "prefix":
            value["host_accepted_message_ids"] = []
        elif damage == "row":
            connection.execute(
                "DELETE FROM messages WHERE id=?", (value["host_episode_first_message_id"],)
            )
        elif damage == "turn":
            connection.execute(
                "UPDATE messages SET metadata_json='{}' WHERE id=?",
                (value["host_episode_first_message_id"],),
            )
        elif damage == "revision":
            connection.execute("UPDATE math_semantic_episodes SET math_revision=math_revision+1")
        connection.execute("UPDATE math_semantic_episodes SET payload_json=?", (json.dumps(value),))
    before = durable(db)
    fresh = RecoveryHost(db, inspect_history=False)
    try:
        if damage == "learner":
            fresh.source = replace(
                fresh.source,
                identity=replace(
                    fresh.source.identity,
                    learner=replace(fresh.source.identity.learner, learner_id="foreign"),
                ),
            )
        elif damage == "source":
            fresh.source = ReviewedSource(
                fresh.source.identity,
                replace(
                    fresh.source.authored,
                    workspace=replace(fresh.source.authored.workspace, status="partial"),
                ),
            )
        _, turn = await fresh.start(A, session_id=session["id"])
        await fresh.finish(
            turn,
            error={
                "start": "start is missing",
                "prefix": "basis changed",
                "row": "prefix is missing",
                "turn": "matching host turn",
                "revision": "canonical head",
                "learner": "binding changed",
                "source": "binding changed",
            }[damage],
        )
        assert durable(db) == before
        assert fresh.history == []
    finally:
        await fresh.close()


@pytest.mark.asyncio
async def test_production_recovery_rechecks_historical_raw_grounding(tmp_path):
    db = tmp_path / "grounding.db"
    old = RecoveryHost(db)
    try:
        session, _ = await old.submit(A)
    finally:
        await old.close()
    before = durable(db)
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute(
            "UPDATE messages SET content='changed historical raw' WHERE id=?",
            (before["state"]["host_episode_first_message_id"],),
        )
    # No historical probe can intercept this failure: production capability
    # and Core must validate the persisted claim's span against the reopened
    # host user row. Its preparation may append the new accepted ID basis,
    # but failed observation must roll back its proposed math evidence.
    fresh = RecoveryHost(db, inspect_history=False)
    try:
        _, turn = await fresh.start(A, session_id=session["id"])
        await fresh.finish(turn, error="historical claim is not grounded")
        after = durable(db)
        assert after["episode"] == before["episode"] and after["revision"] == before["revision"]
        for key in ("alignments", "confirmations", "snapshots", "host_episode_first_message_id"):
            assert after["state"][key] == before["state"][key]
        assert fresh.history == []
    finally:
        await fresh.close()


async def launch(action, db, *, session=None, old_turn=None):
    command = [sys.executable, "-m", "tests.math_semantic.recovery_worker", action, str(db)]
    if session:
        command += ["--session", session, "--old-turn", old_turn]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=Path(__file__).resolve().parents[2],
        # The frozen authored snapshot is included in this test-only report.
        limit=2 * 1024 * 1024,
    )
    stderr = asyncio.create_task(process.stderr.read())
    try:
        async with asyncio.timeout(40):
            while line := await process.stdout.readline():
                if line.startswith(b"RECOVERY_REPORT "):
                    return process, stderr, json.loads(line[len(b"RECOVERY_REPORT ") :])
        raise AssertionError((await stderr).decode(errors="replace"))
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        await stderr
        raise


async def exited(process, stderr):
    async with asyncio.timeout(20):
        assert await process.wait() == 0, (await stderr).decode(errors="replace")
    await stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["resolved", "unknown", "pending"])
async def test_independent_process_reconstruction_and_pending_crash(tmp_path, scenario):
    db = tmp_path / "process.db"
    seed, seed_err, before = await launch("seed_" + scenario, db)
    if scenario == "pending":
        # Actual OS termination: the worker's runtime.close/finally never runs.
        seed.kill()
        await seed.wait()
        await seed_err
        assert seed.returncode != 0
        store_host = RecoveryHost(db)
        try:
            row = await store_host.store.get_turn(before["turn"])
            assert row["status"] == "waiting_input"
            assert await store_host.coordinator.get_lease(before["turn"]) is None
            assert not await store_host.runtime.submit_user_reply(before["turn"], answers=[])
            # This is a host parked-turn gap at the bare manager seam, not
            # lost math truth. Existing application entry reaps the dead row.
            with pytest.raises(ActiveTurnConflict):
                await store_host.start(B, session_id=before["session"])
            assert durable(db) == before["durable"]
        finally:
            await store_host.close()
    else:
        await exited(seed, seed_err)
    assert durable(db) == before["durable"]
    resumed, resumed_err, after = await launch(
        "continue_" + scenario, db, session=before["session"], old_turn=before["turn"]
    )
    await exited(resumed, resumed_err)
    assert before["pid"] != after["pid"] and after["pid"] != os.getpid()
    assert after["history"]["head"] == before["durable"]["revision"]
    assert after["history"]["prefix"] == before["durable"]["state"]["host_accepted_message_ids"]
    assert_evidence_preserved(before["durable"], after["durable"], new_alignments=1)
    if scenario == "pending":
        assert after["card"] == before["card"]
        assert (
            after["old_turn"]["status"] == "failed"
            and after["old_turn"]["failure_code"] == "worker_lost"
        )
        assert after["durable"] == after["before_reply"]
        assert after["result"] is None
        assert (
            after["durable"]["state"]["confirmations"][before["card"]["id"]]["state"] == "pending"
        )
    else:
        assert after["history"]["trajectory"] == before["result"]["trajectory"]
        assert after["history"]["authority"] == before["result"]["authority"]
        if scenario == "resolved":
            confirmation = next(iter(after["durable"]["state"]["confirmations"].values()))
            assert confirmation["state"] == "resolved"
            assert after["result"]["trajectory"]["compatible_path_refs"] == [
                confirmation["chosen_path_ref"]
            ]
            assert after["result"]["trajectory"]["status"] == "SUPPORTED"
            assert after["result"]["verification_status"] == "UNKNOWN"
            assert after["result"]["verified_grounded_refs"] == []
            assert all(grant["act_kind"] == "orientation" for grant in after["result"]["authority"])
        else:
            assert before["result"]["trajectory"]["status"] == "SUPPORTED"
            assert after["result"]["trajectory"]["status"] == "UNKNOWN"
            assert (
                before["result"]["verification_status"]
                == after["result"]["verification_status"]
                == "UNKNOWN"
            )
            assert after["result"]["verified_grounded_refs"] == []
            assert all(grant["act_kind"] == "orientation" for grant in after["result"]["authority"])
