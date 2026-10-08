"""Desired commit ordering on the default SQLite / MemoryCoordinator path."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path
import sqlite3
from threading import Event
from types import SimpleNamespace

import pytest
import pytest_asyncio

from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.runtime.coordination import MemoryCoordinator, RedisCoordinator
from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore
from deeptutor.services.session.scope import store_scope
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager
from tests.services.session.test_pocketbase_store_fallbacks import _FakeClient
from tests.services.session.test_trusted_turn_seam import seam_runtime

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def fence(tmp_path: Path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(
        "deeptutor.runtime.coordination.memory.time", SimpleNamespace(time=lambda: clock[0])
    )
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    await store.create_session(session_id="s", title="original")
    coordinator = MemoryCoordinator()
    scope = hashlib.sha256(store_scope(store).cache_key.encode()).hexdigest()[:16]
    lease = await coordinator.acquire_turn("t", f"{scope}:s", "a")
    await store.begin_turn("s", turn_id="t", owner_id="a", fencing_token=lease.fencing_token)
    yield store, coordinator, lease, clock
    await coordinator.close()


def _bind(store, coordinator, lease):
    run = store.bind_durable_turn_mutation(coordinator, lease, session_id="s")
    assert run is not None
    return run


def _write(sql):
    sql("UPDATE sessions SET title = ? WHERE id = ?", ("committed", "s"))
    return "result"


def _read(store) -> tuple[str, int]:
    # Independent connection: check durable state, not coroutine status.
    with sqlite3.connect(store.db_path) as conn:
        title = conn.execute("SELECT title FROM sessions WHERE id = 's'").fetchone()[0]
        version = conn.execute("SELECT state_version FROM turns WHERE id = 't'").fetchone()[0]
    return title, version


async def test_valid_owner_commits_with_matching_basis(fence) -> None:
    store, coordinator, lease, _ = fence
    assert await _bind(store, coordinator, lease)(_write, expected_state_version=1) == "result"
    assert _read(store) == ("committed", 2)
    with pytest.raises(RuntimeError, match="version"):
        await _bind(store, coordinator, lease)(_write, expected_state_version=1)
    assert _read(store) == ("committed", 2)


@pytest.mark.parametrize(
    "invalid", ["token", "owner", "session", "turn", "release", "expiry", "replace"]
)
async def test_invalid_owner_never_mutates(fence, invalid: str) -> None:
    store, coordinator, lease, clock = fence
    if invalid in {"token", "owner", "session", "turn"}:
        change = {
            "token": {"fencing_token": 999},
            "owner": {"owner_id": "b"},
            "session": {"session_id": "wrong:s"},
            "turn": {"turn_id": "other"},
        }
        lease = replace(lease, **change[invalid])
    elif invalid == "release":
        assert await coordinator.release_turn(lease)
    else:
        clock[0] = lease.expires_at + 1
        if invalid == "replace":
            successor = await coordinator.acquire_turn("t", lease.session_id, "b")
            assert successor.fencing_token > lease.fencing_token
    called = []

    def mutation(sql):
        called.append(True)
        return _write(sql)

    with pytest.raises(RuntimeError):
        await _bind(store, coordinator, lease)(mutation)
    assert not called and _read(store) == ("original", 1)


@pytest.mark.parametrize("status", ["waiting_input", "completed", "failed", "cancelled"])
async def test_ineligible_turn_is_rejected(fence, status: str) -> None:
    store, coordinator, lease, _ = fence
    assert await store.transition_turn("t", status, expected_status="running")
    with pytest.raises(RuntimeError, match="authority"):
        await _bind(store, coordinator, lease)(_write)
    assert _read(store) == ("original", 2)


@pytest.mark.parametrize("field", ["owner_id", "fencing_token", "session_id"])
async def test_stored_owner_token_and_session_are_validated(fence, field) -> None:
    store, coordinator, lease, _ = fence
    # Coordinator ownership alone cannot authorize a different durable row.
    await store.create_session(session_id="other")
    with sqlite3.connect(store.db_path) as conn:
        changes = {"owner_id": "different", "fencing_token": 999, "session_id": "other"}
        conn.execute(f"UPDATE turns SET {field} = ? WHERE id = 't'", (changes[field],))
    with pytest.raises(RuntimeError, match="authority"):
        await _bind(store, coordinator, lease)(_write)
    assert _read(store) == ("original", 1)


async def test_scope_is_captured_and_cannot_be_rebound(fence, tmp_path: Path) -> None:
    store, coordinator, lease, _ = fence
    other = SQLiteSessionStore(tmp_path / "different.db")
    await other.create_session(session_id="s", title="original")
    await other.begin_turn("s", turn_id="t", owner_id="a", fencing_token=lease.fencing_token)
    with pytest.raises(RuntimeError, match="scope"):
        await _bind(other, coordinator, lease)(_write)
    assert _read(store) == _read(other) == ("original", 1)


@pytest.mark.parametrize(
    "statement",
    [
        "COMMIT",
        "ROLLBACK",
        "SAVEPOINT escape",
        "PRAGMA user_version=99",
        "UPDATE turns SET owner_id='b'",
    ],
)
async def test_mutation_cannot_control_transaction_or_authority(fence, statement: str) -> None:
    store, coordinator, lease, _ = fence

    def mutation(sql):
        _write(sql)
        sql(statement, ())

    with pytest.raises(sqlite3.DatabaseError):
        await _bind(store, coordinator, lease)(mutation)
    assert _read(store) == ("original", 1)


async def test_failure_rolls_back_and_statement_runner_cannot_escape(fence) -> None:
    store, coordinator, lease, _ = fence
    escaped = []

    def mutation(sql):
        escaped.append(sql)
        _write(sql)
        raise ValueError("reject candidate")

    with pytest.raises(ValueError, match="reject candidate"):
        await _bind(store, coordinator, lease)(mutation)
    assert _read(store) == ("original", 1)
    with pytest.raises(RuntimeError, match="closed"):
        escaped[0]("UPDATE sessions SET title='escaped'", ())


@pytest.fixture
def pause_sqlite(monkeypatch):
    def install(store, window):
        entered, proceed, committed = Event(), Event(), Event()
        original_connect = store._connect
        timeouts = []

        @contextmanager
        def paused_connect():
            protected = False

            def trace(sql):
                nonlocal protected
                normalized = " ".join(sql.upper().split())
                if normalized.startswith(
                    "SELECT SESSION_ID, STATUS, OWNER_ID, FENCING_TOKEN, STATE_VERSION"
                ):
                    protected = True
                pause = protected and (
                    (window == "after_validation" and normalized.startswith("UPDATE SESSIONS"))
                    or (
                        window == "during_transaction"
                        and normalized.startswith("UPDATE TURNS SET STATE_VERSION")
                    )
                    or (window == "before_commit" and normalized == "COMMIT")
                )
                if pause:
                    entered.set()
                    timeouts.append(not proceed.wait(10))

            with original_connect() as conn:
                conn.set_trace_callback(trace)
                yield conn
            if protected:
                committed.set()

        monkeypatch.setattr(store, "_connect", paused_connect)
        return entered, proceed, committed, timeouts

    return install


@pytest.mark.parametrize("window", ["after_validation", "during_transaction", "before_commit"])
@pytest.mark.parametrize("invalidation", ["release", "expiry", "replacement"])
async def test_commit_serializes_before_invalidation(
    fence, pause_sqlite, window, invalidation
) -> None:
    store, coordinator, lease, clock = fence
    entered, proceed, committed, timeouts = pause_sqlite(store, window)
    task = asyncio.create_task(_bind(store, coordinator, lease)(_write))
    change = None
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        assert _read(store) == ("original", 1)
        clock[0] = lease.expires_at + 1
        if invalidation == "release":
            change = asyncio.create_task(coordinator.release_turn(lease))
        elif invalidation == "expiry":
            change = asyncio.create_task(coordinator.get_lease("t"))
        else:
            change = asyncio.create_task(coordinator.acquire_turn("t", lease.session_id, "b"))
        # Let the contender reach the existing coordinator lock; no timed race.
        await asyncio.sleep(0)
        assert not change.done() and not committed.is_set()
        proceed.set()
        assert await task == "result"
        result = await change
        assert committed.is_set() and not any(timeouts)
        assert _read(store) == ("committed", 2)
        assert result is not None if invalidation != "expiry" else result is None
        with pytest.raises(RuntimeError):
            await _bind(store, coordinator, lease)(_write)
        assert _read(store) == ("committed", 2)
    finally:
        proceed.set()
        await asyncio.gather(task, *([change] if change else []), return_exceptions=True)


async def test_cancellation_before_entry_and_expiry_while_waiting_never_write(fence) -> None:
    store, coordinator, lease, clock = fence
    async with coordinator._lock:
        task = asyncio.create_task(_bind(store, coordinator, lease)(_write))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert _read(store) == ("original", 1)
    async with coordinator._lock:
        task = asyncio.create_task(_bind(store, coordinator, lease)(_write))
        await asyncio.sleep(0)
        clock[0] = lease.expires_at + 1
    with pytest.raises(RuntimeError, match="authority"):
        await task
    assert _read(store) == ("original", 1)


@pytest.mark.parametrize("window", ["after_validation", "during_transaction", "before_commit"])
async def test_cancelled_awaiter_drains_worker_before_replacement(
    fence, pause_sqlite, window
) -> None:
    store, coordinator, lease, clock = fence
    entered, proceed, committed, timeouts = pause_sqlite(store, window)
    task = asyncio.create_task(_bind(store, coordinator, lease)(_write))
    successor = None
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # A second cancellation must not abandon protection.
        await asyncio.sleep(0)
        clock[0] = lease.expires_at + 1
        successor = asyncio.create_task(coordinator.acquire_turn("t", lease.session_id, "b"))
        await asyncio.sleep(0)
        assert not task.done() and not successor.done() and not committed.is_set()
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        replacement = await successor
        assert replacement.fencing_token > lease.fencing_token and committed.is_set()
        assert _read(store) == ("committed", 2) and not any(timeouts)
    finally:
        proceed.set()
        await asyncio.gather(task, *([successor] if successor else []), return_exceptions=True)


async def test_real_runtime_capability_uses_host_contract(seam_runtime):  # noqa: F811
    runtime, store, contexts = seam_runtime

    class ProtectedWitness(TurnCapability):
        manifest = CapabilityManifest(name="protected_witness", description="Test host commit")

        async def run(self, context, stream):
            contexts.append(context)
            assert context.runtime.accepted_user_message_id is not None
            run = context.runtime.run_durable_turn_mutation
            assert run is not None

            def mutation(sql):
                [row] = sql(
                    "SELECT content FROM messages WHERE id=?",
                    (context.runtime.accepted_user_message_id,),
                )
                assert row[0] == context.runtime.accepted_user_content == "raw learner input"
                sql(
                    "UPDATE sessions SET title=? WHERE id=?",
                    ("protected commit", context.session_id),
                )

            await run(mutation, expected_state_version=1)

    runtime.turn_engine.capability_registry.register(ProtectedWitness)
    session, turn = await runtime.start_turn(
        {
            "content": "raw learner input",
            "capability": "protected_witness",
            "tools": [],
            "knowledge_bases": [],
            "language": "en",
            "auto_route": False,
        }
    )
    await asyncio.wait_for(runtime._executions[turn["id"]].task, 15)
    reader = SQLiteSessionStore(store.db_path)
    assert (await reader.get_session(session["id"]))["title"] == "protected commit"
    assert (await reader.get_turn(turn["id"]))["status"] == "completed"
    assert (await reader.get_turn(turn["id"]))["state_version"] == 3


async def test_unsupported_coordinator_does_not_receive_commit_capability(fence) -> None:
    store, _, lease, _ = fence
    redis = RedisCoordinator("", client=object())
    assert store.bind_durable_turn_mutation(redis, lease, session_id="s") is None
    assert store.bind_durable_turn_mutation(None, lease, session_id="s") is None


async def test_ordinary_runtime_without_coordinator_still_works(seam_runtime):  # noqa: F811
    runtime, store, contexts = seam_runtime
    runtime.coordinator = None
    session, turn = await runtime.start_turn(
        {
            "content": "ordinary input",
            "capability": "submission_probe",
            "tools": [],
            "knowledge_bases": [],
            "language": "en",
            "auto_route": False,
        }
    )
    await asyncio.wait_for(runtime._executions[turn["id"]].task, 15)
    assert contexts[-1].runtime.run_durable_turn_mutation is None
    assert (await store.get_messages(session["id"]))[-1]["content"] == "normal reply"
    assert (await store.get_turn(turn["id"]))["status"] == "completed"


async def test_default_container_wiring_is_memory_and_sqlite(monkeypatch, tmp_path):
    from deeptutor.app.container import ApplicationContainer

    monkeypatch.setattr("deeptutor.app.container.load_system_settings", lambda: {})
    monkeypatch.setattr("deeptutor.app.container.load_integrations_settings", lambda: {})
    container = ApplicationContainer.build()
    assert type(container.coordinator) is MemoryCoordinator
    assert container.settings.backend_workers == 1
    monkeypatch.setattr("deeptutor.services.pocketbase_client.is_pocketbase_enabled", lambda: False)
    store = container.store_provider.get()
    assert isinstance(store, SQLiteSessionStore)
    runtime = container.runtime_registry.get(store)
    assert runtime.coordinator is container.coordinator
    await runtime.close()
    await container.coordinator.close()


async def test_pocketbase_ordinary_runtime_has_no_protected_commit_port(
    seam_runtime,  # noqa: F811 -- imported pytest fixture
    monkeypatch,
):
    original, _, contexts = seam_runtime
    client = _FakeClient()
    monkeypatch.setattr("deeptutor.services.pocketbase_client.get_pb_client", lambda: client)
    store = PocketBaseSessionStore()
    runtime = TurnRuntimeManager(
        store,
        coordinator=MemoryCoordinator(),
        owner_id="pb-worker",
        turn_engine=original.turn_engine,
    )
    monkeypatch.setattr(
        runtime, "_maybe_generate_session_title", original._maybe_generate_session_title
    )
    try:
        session, turn = await runtime.start_turn(
            {
                "content": "ordinary PB input",
                "capability": "submission_probe",
                "tools": [],
                "knowledge_bases": [],
                "language": "en",
                "auto_route": False,
            }
        )
        await asyncio.wait_for(runtime._executions[turn["id"]].task, 15)
        assert contexts[-1].runtime.run_durable_turn_mutation is None
        assert (await store.get_messages(session["id"]))[-1]["content"] == "normal reply"
        assert (await store.get_turn(turn["id"]))["status"] == "completed"
    finally:
        await runtime.close()
        await runtime.coordinator.close()


async def test_executor_cancellation_retains_commit_protection(
    seam_runtime,  # noqa: F811 -- imported pytest fixture
    fence,
    pause_sqlite,
):
    runtime, store, contexts = seam_runtime
    _, _, _, clock = fence
    entered, proceed, committed, timeouts = pause_sqlite(store, "before_commit")
    cancellation_observed = asyncio.Event()

    class CancellingWitness(TurnCapability):
        manifest = CapabilityManifest(name="cancel_witness", description="Test real cancellation")

        async def run(self, context, stream):
            contexts.append(context)

            def mutation(sql):
                sql(
                    "UPDATE sessions SET title=? WHERE id=?",
                    ("protected commit", context.session_id),
                )

            try:
                await context.runtime.run_durable_turn_mutation(mutation)
            except asyncio.CancelledError:
                cancellation_observed.set()
                raise

    runtime.turn_engine.capability_registry.register(CancellingWitness)
    session, turn = await runtime.start_turn(
        {
            "content": "accepted input",
            "capability": "cancel_witness",
            "tools": [],
            "knowledge_bases": [],
            "language": "en",
            "auto_route": False,
        }
    )
    task = runtime._executions[turn["id"]].task
    successor = None
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        lease = contexts[-1].runtime.turn_lease
        assert contexts[-1].runtime.accepted_user_message_id is not None
        task.cancel()
        await asyncio.sleep(0)
        clock[0] = lease.expires_at + 1
        successor = asyncio.create_task(
            runtime.coordinator.acquire_turn(turn["id"], lease.session_id, "replacement")
        )
        await asyncio.sleep(0)
        assert not task.done() and not successor.done() and not cancellation_observed.is_set()
        proceed.set()
        replacement = await asyncio.wait_for(successor, 10)
        assert committed.is_set() and replacement.fencing_token > lease.fencing_token
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 15)
        assert cancellation_observed.is_set() and not any(timeouts)
        reader = SQLiteSessionStore(store.db_path)
        assert (await reader.get_session(session["id"]))["title"] == "protected commit"
    finally:
        proceed.set()
        await asyncio.gather(task, *([successor] if successor else []), return_exceptions=True)


async def test_terminal_status_change_serializes_with_sqlite_commit(fence, pause_sqlite) -> None:
    store, coordinator, lease, _ = fence
    other = SQLiteSessionStore(store.db_path)
    entered, proceed, committed, timeouts = pause_sqlite(store, "before_commit")
    task = asyncio.create_task(_bind(store, coordinator, lease)(_write))
    change = None
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        change = asyncio.create_task(
            other.transition_turn("t", "failed", expected_status="running")
        )
        await asyncio.sleep(0)
        assert _read(store) == ("original", 1) and not change.done()
        proceed.set()
        assert await task == "result" and await change is True
        assert committed.is_set() and not any(timeouts)
        assert _read(store) == ("committed", 3)
        with pytest.raises(RuntimeError, match="authority"):
            await _bind(store, coordinator, lease)(_write)
        assert _read(store) == ("committed", 3)
    finally:
        proceed.set()
        await asyncio.gather(task, *([change] if change else []), return_exceptions=True)


async def test_async_mutation_body_is_rejected(fence):
    store, coordinator, lease, _ = fence

    async def mutation(sql):
        _write(sql)

    with pytest.raises(TypeError, match="synchronous"):
        await _bind(store, coordinator, lease)(mutation)
    assert _read(store) == ("original", 1)


async def test_multi_write_transaction_returns_values_and_revokes_sql_runner(fence):
    store, coordinator, lease, _ = fence
    escaped = []

    def mutation(sql):
        escaped.append(sql)
        [row] = sql(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES(?,?,?,?) RETURNING id",
            ("s", "assistant", "test-only durable witness", 1000),
        )
        _write(sql)
        return row[0]

    message_id = await _bind(store, coordinator, lease)(mutation)
    assert (await store.get_messages("s"))[0]["id"] == message_id
    assert _read(store) == ("committed", 2)
    with pytest.raises(RuntimeError, match="closed"):
        escaped[0]("UPDATE sessions SET title='escaped'", ())


async def test_closed_coordinator_refuses_mutation(fence):
    store, coordinator, lease, _ = fence
    await coordinator.close()
    with pytest.raises(RuntimeError, match="authority"):
        await _bind(store, coordinator, lease)(_write)
    assert _read(store) == ("original", 1)


async def test_bound_port_rejects_changed_owner_scope(fence, monkeypatch):
    store, coordinator, lease, _ = fence
    run = _bind(store, coordinator, lease)
    monkeypatch.setattr(
        "deeptutor.services.session.scope.current_owner_id", lambda: "other-account"
    )
    with pytest.raises(RuntimeError, match="scope"):
        await run(_write)
    assert _read(store) == ("original", 1)


async def test_renewed_owner_uses_live_authority_not_snapshot_expiry(fence):
    store, coordinator, lease, clock = fence
    run = _bind(store, coordinator, lease)
    clock[0] = lease.expires_at - 1
    renewed = await coordinator.renew_turn(lease)
    clock[0] = lease.expires_at + 1
    assert await coordinator.get_lease("t") == renewed
    assert await run(_write) == "result"
    assert _read(store) == ("committed", 2)
