"""S2 counterexamples, not a math runtime or a proposed persistence design.

Use existing turn/event/message rows as write witnesses. SQLite exercises real
transactions and reopen/readback. PocketBase exercises the real adapter against
the existing test client; it does not claim live server transaction coverage.
Passing tests below reproduce a HOST_CONTRACT_GAP, not a commit-ownership PASS.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from threading import Event
from types import SimpleNamespace

import pytest
import pytest_asyncio

from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.runtime.coordination import MemoryCoordinator, RuntimeCoordinator, TurnLease
from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore
from deeptutor.services.session.protocol import SessionStoreProtocol
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from tests.services.session.test_pocketbase_store_fallbacks import _FakeClient, as_user
from tests.services.session.test_trusted_turn_seam import seam_runtime

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(params=["sqlite", "pocketbase"])
async def backend(request, monkeypatch, tmp_path: Path) -> AsyncIterator[tuple]:
    client = None
    if request.param == "sqlite":
        store = SQLiteSessionStore(tmp_path / "chat_history.db")
    else:
        client = _FakeClient()
        monkeypatch.setattr("deeptutor.services.pocketbase_client.get_pb_client", lambda: client)
        store = PocketBaseSessionStore()
    assert isinstance(store, SessionStoreProtocol)
    with as_user("fence-probe"):
        await store.create_session(session_id="probe_session")
        yield store, client


@pytest_asyncio.fixture
async def ownership(monkeypatch) -> AsyncIterator[tuple[MemoryCoordinator, TurnLease, list[float]]]:
    clock = [1000.0]
    # Replace only the coordinator's clock namespace, not its ownership logic
    # or the process-wide time module. No sleep-dependent expiration races.
    monkeypatch.setattr(
        "deeptutor.runtime.coordination.memory.time", SimpleNamespace(time=lambda: clock[0])
    )
    coordinator = MemoryCoordinator(lease_ttl_seconds=30)
    assert isinstance(coordinator, RuntimeCoordinator)
    lease = await coordinator.acquire_turn("probe_turn", "scope:probe_session", "worker_a")
    assert lease is not None
    try:
        yield coordinator, lease, clock
    finally:
        await coordinator.close()


async def _begin(store, lease: TurnLease) -> dict:
    return await store.begin_turn(
        "probe_session",
        turn_id=lease.turn_id,
        owner_id=lease.owner_id,
        fencing_token=lease.fencing_token,
    )


async def _take_over(coordinator, lease: TurnLease, clock: list[float]) -> TurnLease:
    clock[0] = lease.expires_at + 1
    assert await coordinator.get_lease(lease.turn_id) is None
    successor = await coordinator.acquire_turn(lease.turn_id, lease.session_id, "worker_b")
    assert successor is not None and successor.fencing_token > lease.fencing_token
    assert await coordinator.renew_turn(lease) is None
    assert await coordinator.release_turn(lease) is False
    return successor


async def test_current_owner_can_commit_native_writes(backend, ownership) -> None:
    store, _ = backend
    coordinator, lease, _ = ownership
    await _begin(store, lease)
    assert await coordinator.get_lease(lease.turn_id) == lease
    assert await store.append_events(
        lease.turn_id,
        [{"type": "content", "content": "valid owner"}],
        fencing_token=lease.fencing_token,
    )
    assert await store.transition_turn(
        lease.turn_id, "completed", expected_status="running", fencing_token=lease.fencing_token
    )
    assert (await store.get_turn(lease.turn_id))["status"] == "completed"
    assert (await store.get_events(lease.turn_id))[0]["content"] == "valid owner"


async def test_mismatched_stored_token_rejects_native_writes(backend, ownership) -> None:
    store, _ = backend
    _, lease, _ = ownership
    await _begin(store, lease)
    with pytest.raises(RuntimeError, match="Turn lease lost"):
        await store.append_events(lease.turn_id, [{"type": "content"}], fencing_token=999)
    assert not await store.transition_turn(
        lease.turn_id, "completed", expected_status="running", fencing_token=999
    )
    assert await store.get_events(lease.turn_id) == []
    turn = await store.get_turn(lease.turn_id)
    assert turn["status"] == "running" and turn["state_version"] == 1


@pytest.mark.parametrize("loss", ["release", "expiry", "takeover"])
async def test_ownership_lost_before_mutation_still_accepts_matching_snapshot(
    backend, ownership, loss: str
) -> None:
    store, _ = backend
    coordinator, lease, clock = ownership
    await _begin(store, lease)
    if loss == "release":
        assert await coordinator.release_turn(lease)
    elif loss == "expiry":
        clock[0] = lease.expires_at + 1
    else:
        await _take_over(coordinator, lease, clock)
    assert await coordinator.get_lease(lease.turn_id) != lease
    assert await coordinator.renew_turn(lease) is None

    [accepted] = await store.append_events(
        lease.turn_id,
        [{"type": "content", "content": "probe-only: x=2"}],
        fencing_token=lease.fencing_token,
    )
    assert await store.transition_turn(
        lease.turn_id, "completed", expected_status="running", fencing_token=lease.fencing_token
    )
    # A fresh SQLite store reads the committed row; PB reads through the adapter.
    reader = SQLiteSessionStore(store.db_path) if isinstance(store, SQLiteSessionStore) else store
    assert (await reader.get_events(lease.turn_id))[0]["content"] == accepted["content"]
    turn = await reader.get_turn(lease.turn_id)
    assert turn["status"] == "completed"
    assert turn["owner_id"] == lease.owner_id and turn["fencing_token"] == lease.fencing_token


async def test_terminal_status_rejects_transition_but_not_other_mutations(
    backend, ownership
) -> None:
    store, _ = backend
    coordinator, lease, clock = ownership
    await _begin(store, lease)
    await _take_over(coordinator, lease, clock)
    # Model the existing recovery/cancel writer marking the old turn failed.
    assert await store.transition_turn(lease.turn_id, "failed", expected_status="running")
    assert not await store.transition_turn(
        lease.turn_id, "completed", expected_status="running", fencing_token=lease.fencing_token
    )
    assert await store.append_events(
        lease.turn_id,
        [{"type": "content", "content": "after terminal status"}],
        fencing_token=lease.fencing_token,
    )
    assert await store.add_message("probe_session", "assistant", "probe-only: x=2")
    assert (await store.get_turn(lease.turn_id))["status"] == "failed"
    assert len(await store.get_events(lease.turn_id)) == 1
    assert (await store.get_messages("probe_session"))[-1]["content"] == "probe-only: x=2"


async def test_state_version_increment_is_not_a_compare_and_swap(backend, ownership) -> None:
    store, _ = backend
    _, lease, _ = ownership
    snapshot = await _begin(store, lease)
    assert await store.transition_turn(lease.turn_id, "waiting_input", expected_status="running")
    assert await store.transition_turn(lease.turn_id, "running", expected_status="waiting_input")
    # Status has returned to running, but the original version is stale. The
    # public port accepts expected_status/token only, not expected_state_version.
    assert (await store.get_turn(lease.turn_id))["state_version"] > snapshot["state_version"]
    assert await store.transition_turn(
        lease.turn_id,
        "completed",
        expected_status=snapshot["status"],
        fencing_token=snapshot["fencing_token"],
    )
    assert (await store.get_turn(lease.turn_id))["state_version"] == 4


@pytest.mark.parametrize("window", ["after_fence_check", "during_batch", "before_commit"])
@pytest.mark.parametrize("cancel_awaiter", [False, True])
async def test_sqlite_ownership_loss_inside_transaction_does_not_prevent_commit(
    tmp_path: Path, monkeypatch, ownership, window: str, cancel_awaiter: bool
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    await store.create_session(session_id="probe_session")
    coordinator, lease, clock = ownership
    await _begin(store, lease)
    entered, proceed, committed = Event(), Event(), Event()
    original_connect = store._connect
    inserts = 0
    gate_timed_out = False

    def trace(sql: str) -> None:
        nonlocal inserts, gate_timed_out
        normalized = " ".join(sql.upper().split())
        if normalized.startswith("INSERT INTO TURN_EVENTS"):
            inserts += 1
        pause = (
            (window == "after_fence_check" and inserts == 1 and normalized.startswith("INSERT"))
            or (window == "during_batch" and inserts == 2 and normalized.startswith("INSERT"))
            or (window == "before_commit" and normalized == "COMMIT")
        )
        if pause:
            entered.set()
            # sqlite trace callbacks swallow exceptions: assert timeout on the
            # event-loop side instead of trying to raise inside this callback.
            gate_timed_out = not proceed.wait(10)

    @contextmanager
    def paused_connect():
        with original_connect() as conn:
            conn.set_trace_callback(trace)
            yield conn
        committed.set()  # Only after the real connection context has committed.

    monkeypatch.setattr(store, "_connect", paused_connect)
    task = asyncio.create_task(
        store.append_events(
            lease.turn_id,
            [
                {"type": "content", "content": "probe-only: x=2"},
                {"type": "content", "content": "probe-only: y=3"},
            ],
            fencing_token=lease.fencing_token,
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        with sqlite3.connect(store.db_path) as reader:
            assert reader.execute("SELECT COUNT(*) FROM turn_events").fetchone()[0] == 0
        await _take_over(coordinator, lease, clock)
        if cancel_awaiter:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        proceed.set()
        assert await asyncio.to_thread(committed.wait, 10)
        if not cancel_awaiter:
            assert len(await task) == 2
        assert not gate_timed_out
    finally:
        proceed.set()
        await asyncio.gather(task, return_exceptions=True)

    reader = SQLiteSessionStore(store.db_path)
    assert [row["content"] for row in await reader.get_events(lease.turn_id)] == [
        "probe-only: x=2",
        "probe-only: y=3",
    ]
    assert (await reader.get_turn(lease.turn_id))["fencing_token"] == lease.fencing_token
    assert await coordinator.get_lease(lease.turn_id) != lease


@pytest.mark.parametrize("window", ["after_fence_check", "during_batch", "before_write"])
async def test_pocketbase_token_changes_after_check_are_not_conditional_writes(
    monkeypatch, ownership, window: str
) -> None:
    client = _FakeClient()
    monkeypatch.setattr("deeptutor.services.pocketbase_client.get_pb_client", lambda: client)
    store = PocketBaseSessionStore()
    coordinator, lease, clock = ownership
    entered, proceed = Event(), Event()
    gate_timed_out = False
    events = client.collection("turn_events")
    original_list, original_create = events.get_full_list, events.create
    creates = 0

    def gate():
        nonlocal gate_timed_out
        entered.set()
        gate_timed_out = not proceed.wait(10)

    def paused_list(query_params=None):
        if window == "after_fence_check" and not entered.is_set():
            gate()
        return original_list(query_params)

    def paused_create(data):
        nonlocal creates
        creates += 1
        if (window == "before_write" and creates == 1) or (
            window == "during_batch" and creates == 2
        ):
            gate()
        return original_create(data)

    monkeypatch.setattr(events, "get_full_list", paused_list)
    monkeypatch.setattr(events, "create", paused_create)
    with as_user("fence-probe"):
        await store.create_session(session_id="probe_session")
        await _begin(store, lease)
        task = asyncio.create_task(
            store.append_events(
                lease.turn_id,
                [
                    {"type": "content", "content": "probe-only: x=2"},
                    {"type": "content", "content": "probe-only: y=3"},
                ],
                fencing_token=lease.fencing_token,
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            assert len(original_list()) == (1 if window == "during_batch" else 0)
            successor = await _take_over(coordinator, lease, clock)
            [row] = client.collection("turns").get_full_list()
            client.collection("turns").update(
                row.id,
                {
                    "owner_id": successor.owner_id,
                    "fencing_token": successor.fencing_token,
                    "status": "failed",
                    "state_version": 20,
                },
            )
            proceed.set()
            assert len(await asyncio.wait_for(task, 10)) == 2
            assert not gate_timed_out
        finally:
            proceed.set()
            await asyncio.gather(task, return_exceptions=True)
        assert len(await store.get_events(lease.turn_id)) == 2
        turn = await store.get_turn(lease.turn_id)
        assert turn["status"] == "failed" and turn["fencing_token"] == successor.fencing_token


async def test_pocketbase_stale_transition_overwrites_terminal_status_and_version(
    monkeypatch, ownership
) -> None:
    client = _FakeClient()
    monkeypatch.setattr("deeptutor.services.pocketbase_client.get_pb_client", lambda: client)
    store = PocketBaseSessionStore()
    coordinator, lease, clock = ownership
    entered, proceed = Event(), Event()
    turns = client.collection("turns")
    original_update = turns.update
    gate_timed_out = False

    def paused_update(record_id, data):
        nonlocal gate_timed_out
        entered.set()
        gate_timed_out = not proceed.wait(10)
        return original_update(record_id, data)

    with as_user("fence-probe"):
        await store.create_session(session_id="probe_session")
        await _begin(store, lease)
        monkeypatch.setattr(turns, "update", paused_update)
        task = asyncio.create_task(
            store.transition_turn(
                lease.turn_id,
                "completed",
                expected_status="running",
                fencing_token=lease.fencing_token,
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            successor = await _take_over(coordinator, lease, clock)
            [row] = turns.get_full_list()
            original_update(
                row.id,
                {
                    "owner_id": successor.owner_id,
                    "fencing_token": successor.fencing_token,
                    "status": "failed",
                    "state_version": 20,
                },
            )
            proceed.set()
            assert await asyncio.wait_for(task, 10) is True
            assert not gate_timed_out
        finally:
            proceed.set()
            await asyncio.gather(task, return_exceptions=True)
        turn = await store.get_turn(lease.turn_id)
        assert turn["owner_id"] == successor.owner_id
        assert turn["fencing_token"] == successor.fencing_token
        assert turn["status"] == "completed" and turn["state_version"] == 2


async def test_runtime_detects_lease_loss_and_cancels_but_sqlite_worker_commits(
    seam_runtime,  # noqa: F811 -- imported pytest fixture
    ownership,
    monkeypatch,
) -> None:
    runtime, store, contexts = seam_runtime
    _, _, clock = ownership
    runtime.coordinator.lease_ttl_seconds = 0.9
    entered, proceed, committed = Event(), Event(), Event()
    original_connect = store._connect
    gate_timed_out = False

    class FenceProbe(TurnCapability):
        manifest = CapabilityManifest(name="fence_probe", description="Test commit witness")

        async def run(self, context, stream) -> None:
            contexts.append(context)
            lease = context.runtime.turn_lease
            assert lease is not None
            await store.append_events(
                lease.turn_id,
                [{"type": "content", "content": "probe-only: x=2"}],
                fencing_token=lease.fencing_token,
            )

    @contextmanager
    def paused_connect():
        witness_inserted = False

        def trace(sql: str) -> None:
            nonlocal witness_inserted, gate_timed_out
            if "INSERT INTO turn_events" in sql and "probe-only: x=2" in sql:
                witness_inserted = True
            if witness_inserted and sql == "COMMIT":
                entered.set()
                gate_timed_out = not proceed.wait(10)

        with original_connect() as conn:
            conn.set_trace_callback(trace)
            yield conn
        if witness_inserted:
            committed.set()

    monkeypatch.setattr(store, "_connect", paused_connect)
    runtime.turn_engine.capability_registry.register(FenceProbe)
    session, turn = await runtime.start_turn(
        {
            "content": "x=2",
            "capability": "fence_probe",
            "tools": [],
            "knowledge_bases": [],
            "language": "en",
            "auto_route": False,
        }
    )
    execution = runtime._executions[turn["id"]]
    task = execution.task
    assert task is not None
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        lease = contexts[-1].runtime.turn_lease
        successor = await _take_over(runtime.coordinator, lease, clock)
        # The real lifecycle renew loop discovers the loss and cancels both
        # the executor and the orchestrator's capability task. No manual cancel.
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), 5)
        assert execution.lease_lost and task.cancelled()
        assert not committed.is_set()
        proceed.set()
        assert await asyncio.to_thread(committed.wait, 10)
        assert not gate_timed_out
    finally:
        proceed.set()
        await asyncio.gather(task, return_exceptions=True)

    reader = SQLiteSessionStore(store.db_path)
    assert any(row["content"] == "probe-only: x=2" for row in await reader.get_events(turn["id"]))
    assert (await reader.get_messages(session["id"]))[0]["content"] == "x=2"
    assert (await reader.get_turn(turn["id"]))["status"] == "running"
    assert await runtime.coordinator.get_lease(turn["id"]) == successor
