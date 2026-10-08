"""Accepted user rows reach registered capabilities through the real runtime."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from deeptutor.core.capability_protocol import (
    CapabilityManifest,
    StreamBusProtocol,
    TurnCapability,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.turn_engine import TurnEngine
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


@pytest_asyncio.fixture
async def seam_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[tuple[TurnRuntimeManager, SQLiteSessionStore, list[UnifiedContext]]]:
    contexts: list[UnifiedContext] = []

    class RecordingCapability(TurnCapability):
        manifest = CapabilityManifest(name="submission_probe", description="Test input consumer")

        async def run(self, context: UnifiedContext, stream: StreamBusProtocol) -> None:
            contexts.append(context)
            await stream.emit(
                StreamEvent(type=StreamEventType.CONTENT, source=self.name, content="normal reply")
            )

    registry = CapabilityRegistry()
    registry.register(RecordingCapability)
    store = SQLiteSessionStore(tmp_path / "accepted.sqlite3")
    runtime = TurnRuntimeManager(
        store=store,
        coordinator=MemoryCoordinator(),
        owner_id="seam-test-worker",
        turn_engine=TurnEngine(capability_registry=registry),
    )

    async def no_title(**_kwargs: Any) -> None:
        pass

    # Title generation and skill discovery are unrelated external work. Keep
    # persistence, context assembly, routing, capability execution and events real.
    monkeypatch.setattr(runtime, "_maybe_generate_session_title", no_title)
    monkeypatch.setattr("deeptutor.services.skill.runtime.skill_manifest", lambda: "")
    try:
        yield runtime, store, contexts
    finally:
        await runtime.close()


async def _submit(runtime: TurnRuntimeManager, **overrides: Any) -> tuple[dict, dict]:
    session, turn = await runtime.start_turn(
        {
            "content": "  x = 2\n",  # Whitespace is part of the accepted source.
            "capability": "submission_probe",
            "tools": [],
            "knowledge_bases": [],
            "language": "en",
            "auto_route": False,
            **overrides,
        }
    )
    task = runtime._executions[turn["id"]].task
    assert task is not None
    await asyncio.wait_for(task, timeout=15)
    persisted_turn = await runtime.store.get_turn(turn["id"])
    assert persisted_turn is not None and persisted_turn["status"] == "completed"
    return session, turn


@pytest.mark.asyncio
@pytest.mark.parametrize("client_id", [None, "browser-submission-1"])
async def test_persisted_submission_and_lease_reach_registered_capability(
    seam_runtime, client_id: str | None
) -> None:
    runtime, store, contexts = seam_runtime
    session, turn = await _submit(runtime, client_submission_id=client_id)
    rows = await store.get_messages(session["id"])
    user = next(row for row in rows if row["role"] == "user")
    context = contexts[-1]
    assert context.runtime.accepted_user_message_id == user["id"]
    assert context.runtime.accepted_user_content == user["content"] == "  x = 2\n"
    assert context.runtime.client_submission_id == user["metadata"].get("client_submission_id")
    assert context.runtime.client_submission_id == client_id
    assert context.runtime.turn_id == user["metadata"]["turn_id"] == turn["id"]
    lease = context.runtime.turn_lease
    persisted_turn = await store.get_turn(turn["id"])
    assert lease is not None and persisted_turn is not None
    assert lease.turn_id == turn["id"]
    assert lease.session_id == f"{runtime._coordination_scope}:{session['id']}"
    assert lease.owner_id == persisted_turn["owner_id"] == "seam-test-worker"
    assert lease.fencing_token == persisted_turn["fencing_token"] > 0
    assert lease.expires_at > 0
    assert rows[-1]["role"] == "assistant" and rows[-1]["content"] == "normal reply"
    assert "accepted_user_content" not in context.metadata
    assert "turn_lease" not in context.metadata


@pytest.mark.asyncio
async def test_attachment_expands_prompt_without_changing_accepted_source(seam_runtime) -> None:
    runtime, store, contexts = seam_runtime
    session, _ = await _submit(
        runtime,
        attachments=[
            {
                "type": "file",
                "filename": "notes.txt",
                "mime_type": "text/plain",
                "base64": base64.b64encode(b"Reference context, not student evidence.\n").decode(),
            }
        ],
    )
    context = contexts[-1]
    user = next(row for row in await store.get_messages(session["id"]) if row["role"] == "user")
    assert "Reference context, not student evidence." in context.user_message
    assert "[User Question]" in context.user_message
    assert context.user_message != user["content"]
    assert context.runtime.accepted_user_content == user["content"] == "  x = 2\n"
    assert context.runtime.accepted_user_message_id == user["id"]


@pytest.mark.asyncio
async def test_identical_text_and_separate_sessions_keep_real_identities(seam_runtime) -> None:
    runtime, store, contexts = seam_runtime
    first, _ = await _submit(runtime, client_submission_id="first")
    await _submit(runtime, session_id=first["id"], client_submission_id="second")
    other, _ = await _submit(runtime, client_submission_id="third")
    users = [row for row in await store.get_messages(first["id"]) if row["role"] == "user"]
    users += [row for row in await store.get_messages(other["id"]) if row["role"] == "user"]
    assert len(users) == 3 and len({row["id"] for row in users}) == 3
    assert [ctx.runtime.accepted_user_message_id for ctx in contexts] == [
        row["id"] for row in users
    ]
    assert all(ctx.runtime.accepted_user_content == "  x = 2\n" for ctx in contexts)
    assert contexts[-1].session_id != contexts[0].session_id


@pytest.mark.asyncio
@pytest.mark.parametrize("root_edit", [False, True])
async def test_branch_edit_creates_a_new_row_without_rewriting_source(
    seam_runtime, root_edit
) -> None:
    runtime, store, contexts = seam_runtime
    session, _ = await _submit(runtime, content="original source")
    original_rows = await store.get_messages(session["id"])
    original_user = original_rows[0]
    parent_id = None if root_edit else original_rows[-1]["id"]
    await _submit(
        runtime,
        session_id=session["id"],
        content="edited branch source",
        parent_message_id=parent_id,
    )
    rows = await store.get_messages(session["id"])
    edited = next(row for row in rows if row["id"] == contexts[-1].runtime.accepted_user_message_id)
    assert edited["content"] == contexts[-1].runtime.accepted_user_content == "edited branch source"
    assert edited["parent_message_id"] == parent_id
    assert edited["id"] != original_user["id"]
    assert next(row for row in rows if row["id"] == original_user["id"]) == original_user


@pytest.mark.asyncio
async def test_regenerate_keeps_original_user_row_without_new_acceptance(seam_runtime) -> None:
    runtime, store, contexts = seam_runtime
    session, _ = await _submit(runtime, client_submission_id="original-client")
    original_user = (await store.get_messages(session["id"]))[0]
    _, turn = await runtime.regenerate_last_turn(session["id"], overrides={"auto_route": False})
    task = runtime._executions[turn["id"]].task
    assert task is not None
    await asyncio.wait_for(task, timeout=15)
    rows = await store.get_messages(session["id"])
    assert [row for row in rows if row["role"] == "user"] == [original_user]
    assert contexts[-1].runtime.turn_id != original_user["metadata"]["turn_id"]
    assert contexts[-1].runtime.accepted_user_message_id is None
    assert contexts[-1].runtime.accepted_user_content is None
    assert contexts[-1].runtime.client_submission_id is None
    assert rows[-1]["content"] == "normal reply"


@pytest.mark.asyncio
async def test_non_persisted_input_cannot_borrow_existing_identity(seam_runtime) -> None:
    runtime, store, contexts = seam_runtime
    session, _ = await _submit(runtime)
    original_user = (await store.get_messages(session["id"]))[0]
    await _submit(
        runtime,
        session_id=session["id"],
        persist_user_message=False,
        client_submission_id="not-accepted",
        config={"accepted_user_message_id": original_user["id"], "accepted_user_content": "forged"},
    )
    assert [row for row in await store.get_messages(session["id"]) if row["role"] == "user"] == [
        original_user
    ]
    assert contexts[-1].runtime.accepted_user_message_id is None
    assert contexts[-1].runtime.accepted_user_content is None
    assert contexts[-1].runtime.client_submission_id is None


@pytest.mark.asyncio
async def test_local_runtime_does_not_invent_a_lease(seam_runtime) -> None:
    runtime, _, contexts = seam_runtime
    runtime.coordinator = None
    await _submit(runtime)
    assert contexts[-1].runtime.accepted_user_message_id is not None
    assert contexts[-1].runtime.turn_lease is None


@pytest.mark.asyncio
async def test_failed_persistence_does_not_invoke_capability(seam_runtime, monkeypatch) -> None:
    runtime, store, contexts = seam_runtime

    async def fail_user_write(*_args: Any, **_kwargs: Any) -> int:
        raise OSError("user row write failed")

    monkeypatch.setattr(store, "add_message", fail_user_write)
    session, turn = await runtime.start_turn(
        {"content": "not accepted", "capability": "submission_probe", "auto_route": False}
    )
    task = runtime._executions[turn["id"]].task
    assert task is not None
    await asyncio.wait_for(task, timeout=15)
    persisted = await store.get_turn(turn["id"])
    assert persisted is not None and persisted["status"] == "failed"
    assert persisted["error"] == "user row write failed"
    assert await store.get_messages(session["id"]) == []
    assert contexts == []
