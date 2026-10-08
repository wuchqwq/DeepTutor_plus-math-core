from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth, unified_ws


class _Turns:
    def __init__(self) -> None:
        self.cancelled: list[tuple[str, str]] = []
        self.replies: list[dict] = []

    async def submit_user_reply(self, turn_id, text=None, *, answers=None, command_id):
        self.replies.append({"turn_id": turn_id, "text": text, "answers": answers})
        return True

    async def cancel_turn(self, turn_id: str, *, command_id: str) -> bool:
        self.cancelled.append((turn_id, command_id))
        return True

    async def check_active_turn(self, _session_id: str) -> dict[str, str]:
        return {"turn_id": "turn-1", "status": "recovering", "owner_id": "worker-b"}


@pytest.fixture
def protocol_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, _Turns]:
    turns = _Turns()

    async def allow(_ws):
        return None

    monkeypatch.setattr(auth, "ws_require_auth", allow)
    app = FastAPI()
    app.state.application_container = SimpleNamespace(turns=turns)
    app.include_router(unified_ws.router)
    return TestClient(app), turns


def test_ws_rejects_missing_and_future_protocol_versions(protocol_client) -> None:
    client, _turns = protocol_client
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "ping"})
        missing = socket.receive_json()
        socket.send_json({"type": "ping", "protocol_version": "3.0"})
        future = socket.receive_json()

    for frame in (missing, future):
        assert frame == {
            "type": "protocol_error",
            "error_code": "unsupported_protocol_version",
            "message": "Unsupported or missing protocol_version; expected 2.0.",
            "retryable": False,
            "session_id": "",
            "turn_id": "",
            "protocol_version": "2.0",
        }


def test_ws_versions_heartbeats_active_state_and_command_ack(protocol_client) -> None:
    client, turns = protocol_client
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "ping", "protocol_version": "2.0"})
        assert socket.receive_json() == {"type": "pong", "protocol_version": "2.0"}

        socket.send_json(
            {
                "type": "check_active_turn",
                "session_id": "session-1",
                "protocol_version": "2.0",
            }
        )
        assert socket.receive_json() == {
            "type": "active_turn_info",
            "turn_id": "turn-1",
            "status": "recovering",
            "owner_id": "worker-b",
            "protocol_version": "2.0",
        }

        socket.send_json(
            {
                "type": "cancel_turn",
                "turn_id": "turn-1",
                "command_id": "cancel-1",
                "protocol_version": "2.0",
            }
        )
        assert socket.receive_json() == {
            "type": "command_ack",
            "command_id": "cancel-1",
            "command_type": "cancel_turn",
            "accepted": True,
            "turn_id": "turn-1",
            "error_code": "",
            "message": "",
            "protocol_version": "2.0",
        }

    assert turns.cancelled == [("turn-1", "cancel-1")]


def test_ws_requires_command_ids_for_retryable_mutations(protocol_client) -> None:
    client, turns = protocol_client
    with client.websocket_connect("/ws") as socket:
        socket.send_json(
            {
                "type": "cancel_turn",
                "turn_id": "turn-1",
                "protocol_version": "2.0",
            }
        )
        frame = socket.receive_json()

    assert frame["type"] == "protocol_error"
    assert frame["error_code"] == "invalid_command"
    assert frame["protocol_version"] == "2.0"
    assert turns.cancelled == []


@pytest.mark.parametrize(
    "reply",
    [
        {
            "answers": [
                {"questionId": "q1", "text": "Display", "selected_option_id": " opaque/α:1 "}
            ]
        },
        {"answers": [{"questionId": "q1", "text": "Legacy label"}]},
        {"answers": [{"questionId": "q1", "text": "Free text"}]},
        {"answers": [{"questionId": "q1", "text": ""}]},
        {"text": "Legacy flat reply"},
    ],
)
def test_ws_reply_preserves_identity_and_legacy_shapes(protocol_client, reply) -> None:
    client, turns = protocol_client
    with client.websocket_connect("/ws") as socket:
        socket.send_json(
            {
                "type": "submit_user_reply",
                "turn_id": "turn-1",
                "command_id": "reply-1",
                "protocol_version": "2.0",
                **reply,
            }
        )
        ack = socket.receive_json()
    assert ack["type"] == "command_ack" and ack["accepted"] is True
    assert turns.replies == [
        {
            "turn_id": "turn-1",
            "text": reply.get("text"),
            "answers": reply.get("answers"),
        }
    ]


@pytest.mark.parametrize("option_id", ["", "   ", "x" * 129, 7])
def test_ws_rejects_malformed_selected_identity(protocol_client, option_id) -> None:
    client, turns = protocol_client
    with client.websocket_connect("/ws") as socket:
        socket.send_json(
            {
                "type": "submit_user_reply",
                "turn_id": "turn-1",
                "command_id": "reply-1",
                "protocol_version": "2.0",
                "answers": [{"questionId": "q1", "selected_option_id": option_id}],
            }
        )
        frame = socket.receive_json()
    assert frame["type"] == "protocol_error" and frame["error_code"] == "invalid_command"
    assert turns.replies == []
