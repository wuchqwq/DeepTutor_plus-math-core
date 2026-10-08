"""MATH-TURN-CAPABILITY-01 acceptance tests (A-J).

These prove one real protected-math turn hosted through DeepTutor's public
``TurnCapability`` seam while ``tutor_demo`` remains the source of mathematical
authority. They need the frozen math engine checkout; point
``DEEPTUTOR_MATH_ENGINE_SRC`` at it (or they skip with a clear reason).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import os
from pathlib import Path
import subprocess

import pytest

import deeptutor
from deeptutor.capabilities.math_turn.capability import (
    UNAVAILABLE_MESSAGE,
    MathTurnCapability,
    build_method_confirmation_payload,
)
from deeptutor.capabilities.math_turn.engine import (
    MATH_ENGINE_COMMIT,
    MATH_ENGINE_SOURCE_ENV,
    MathEngineSourceError,
    MathTurnEngine,
    MathTurnUnavailable,
    MethodOption,
    ReviewedMathEpisode,
    configure_math_turn_engine,
    load_math_engine,
)
from deeptutor.core.capability_protocol import TurnCapability
from deeptutor.core.context import TurnRuntimeContext, UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.stream_bus import StreamBus

SESSION_ID = "dt-session-ca02"
#: Reviewed CA02 claims: "AS" grounds path A, "B2" exclusively grounds path B.
PATH_A_TURN = "s=x+y"
PATH_B_TURN = "3*(x^2-x*y+y^2)-(x^2+x*y+y^2)=2*(x-y)^2"


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _frozen_source() -> str:
    source = os.environ.get(MATH_ENGINE_SOURCE_ENV, "")
    if not source or not Path(source).is_dir():
        pytest.skip(
            f"{MATH_ENGINE_SOURCE_ENV} is not set to a checkout; frozen math engine unavailable"
        )
    return source


@pytest.fixture(scope="session")
def engine_modules():
    return load_math_engine(_frozen_source())


@pytest.fixture
def math_engine(tmp_path, engine_modules):
    episode = ReviewedMathEpisode(
        session_id=SESSION_ID,
        workspace_id="dt:HB2-CA-02:capability-test",
        db_path=str(tmp_path / "math-engine.sqlite3"),
        learner_id="dt-learner",
    )
    engine = MathTurnEngine(episode, modules=engine_modules)
    configure_math_turn_engine(engine)
    try:
        yield engine
    finally:
        configure_math_turn_engine(None)
        engine.close()


async def _run_capability(
    *,
    session_id: str,
    text: str,
    reply: dict | None = None,
) -> tuple[UnifiedContext, list, StreamBus]:
    """Run the capability over a real StreamBus and collect every event."""

    bus = StreamBus()
    events: list = []

    async def consume() -> None:
        async for event in bus.subscribe():
            events.append(event)

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0)

    async def waiter() -> dict | None:
        return reply

    context = UnifiedContext(
        session_id=session_id,
        user_message=text,
        runtime=TurnRuntimeContext(turn_id="turn-1", wait_for_user_reply=waiter),
    )
    await MathTurnCapability().run(context, bus)
    await bus.close()
    await consumer
    return context, events, bus


def _math_card(events: list):
    for event in events:
        if event.type != StreamEventType.TOOL_RESULT:
            continue
        ask = (event.metadata.get("tool_metadata") or {}).get("ask_user")
        if ask:
            return ask
    return None


def _path_ids(engine: MathTurnEngine) -> tuple[str, ...]:
    snapshot = engine.workspace.load(engine.episode.workspace_id, revision=2)
    return tuple(path.path_id for path in snapshot.paths)


# ---------------------------------------------------------------------------
# A. capability registration
# ---------------------------------------------------------------------------


def test_capability_is_a_turn_capability() -> None:
    capability = MathTurnCapability()
    assert isinstance(capability, TurnCapability)
    assert capability.name == "math_turn"
    assert capability.manifest.stages == ["authority", "publish"]


def test_pyproject_declares_extension_entry_point() -> None:
    repo_root = Path(deeptutor.__file__).resolve().parents[1]
    text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert '[project.entry-points."deeptutor.extensions"]' in text
    assert "math_turn = " in text
    assert "MathTurnCapability" in text


def test_registry_discovers_capability_via_extensions(monkeypatch) -> None:
    from importlib.metadata import EntryPoint

    entry = EntryPoint(
        name="math_turn",
        value="deeptutor.capabilities.math_turn.capability:MathTurnCapability",
        group="deeptutor.extensions",
    )
    monkeypatch.setattr(
        "deeptutor.core.entry_points.entry_points",
        lambda **params: [entry] if params.get("group") == "deeptutor.extensions" else [],
    )
    registry = CapabilityRegistry()
    registry.load_plugins()
    assert "math_turn" in registry.list_capabilities()
    discovered = registry.get("math_turn")
    assert isinstance(discovered, MathTurnCapability)


# ---------------------------------------------------------------------------
# B. correct source / wrong-tree guard
# ---------------------------------------------------------------------------


def test_wrong_tree_guard_rejects_unset_source(monkeypatch) -> None:
    monkeypatch.delenv(MATH_ENGINE_SOURCE_ENV, raising=False)
    with pytest.raises(MathEngineSourceError):
        load_math_engine()


def test_wrong_tree_guard_rejects_missing_source(tmp_path) -> None:
    with pytest.raises(MathEngineSourceError):
        load_math_engine(str(tmp_path / "does-not-exist"))


def test_wrong_tree_guard_rejects_non_git_source(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    with pytest.raises(MathEngineSourceError):
        load_math_engine(str(tmp_path))


def test_wrong_tree_guard_rejects_wrong_commit(tmp_path) -> None:
    repo = tmp_path / "wrong-checkout"
    (repo / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@e",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-qm",
            "not the frozen engine",
        ],
        check=True,
    )
    with pytest.raises(MathEngineSourceError):
        load_math_engine(str(repo))


def test_correct_source_is_pinned(engine_modules) -> None:
    src = os.path.abspath(os.path.join(_frozen_source(), "src"))
    paths = engine_modules.module_paths
    assert paths
    for name, path in paths.items():
        assert os.path.abspath(path).startswith(src + os.sep), name
    assert MATH_ENGINE_COMMIT


# ---------------------------------------------------------------------------
# C + D. normal protected turn, authority before publication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_protected_turn_authorizes_before_publishing(math_engine) -> None:
    context, events, _ = await _run_capability(session_id=SESSION_ID, text=PATH_A_TURN)

    authority = [e for e in events if e.metadata.get("trace_kind") == "math_authority"]
    assert len(authority) == 1
    meta = authority[0].metadata
    assert meta["trajectory_version"] == "ca02_trajectory_v1"
    assert meta["math_status"] == "SUPPORTED"
    assert meta["compatible_path_refs"]
    assert meta["applicable_artifact_refs"]
    assert meta["method_confirmation_required"] is False

    results = [e for e in events if e.type == StreamEventType.RESULT]
    assert len(results) == 1
    assert events.index(authority[0]) < events.index(results[0])
    assert [e for e in events if e.type == StreamEventType.CONTENT] == []
    assert context.capability_output.agent_output == results[0].metadata["response"]
    assert "Protected math turn accepted" in results[0].metadata["response"]


# ---------------------------------------------------------------------------
# E + F. method divergence surfaces structured option identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_method_divergence_and_option_identity(math_engine) -> None:
    await _run_capability(session_id=SESSION_ID, text=PATH_A_TURN)
    # Waiter declines to answer so the card is observable and the turn fails
    # closed rather than picking a branch.
    context, events, _ = await _run_capability(session_id=SESSION_ID, text=PATH_B_TURN)

    authority = [e for e in events if e.metadata.get("trace_kind") == "math_authority"]
    assert authority and authority[0].metadata["math_status"] == "METHOD_CONFIRMATION_REQUIRED"
    assert authority[0].metadata["method_confirmation_required"] is True

    card = _math_card(events)
    assert card is not None
    question = card["questions"][0]
    assert question["allow_free_text"] is False
    option_ids = [option["option_id"] for option in question["options"]]
    labels = [option["label"] for option in question["options"]]
    # F: the math option tokens are the host option identities, and the opaque
    # question identity is the confirmation id -- not a label.
    assert all(option_ids)
    assert option_ids == list(dict.fromkeys(option_ids))
    assert option_ids[0].startswith(question["id"] + ":")
    assert all(label not in option_ids for label in labels)
    assert not [e for e in events if e.type == StreamEventType.RESULT]


# ---------------------------------------------------------------------------
# G. structured resolution hits the exact path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_selected_option_id_resolves_exact_path(math_engine) -> None:
    await _run_capability(session_id=SESSION_ID, text=PATH_A_TURN)
    _, probe_events, _ = await _run_capability(session_id=SESSION_ID, text=PATH_B_TURN)
    card = _math_card(probe_events)
    question = card["questions"][0]
    token_b = question["options"][1]["option_id"]

    reply = {"answers": [{"questionId": question["id"], "text": "", "selected_option_id": token_b}]}
    _, events, _ = await _run_capability(session_id=SESSION_ID, text=PATH_B_TURN, reply=reply)

    assert [e for e in events if e.type == StreamEventType.RESULT], "resolution must publish"
    assert not [e for e in events if e.type == StreamEventType.ERROR]

    stored = math_engine.ledger.method_confirmations(math_engine.episode.workspace_id)
    assert len(stored) == 1
    assert stored[0].state == "resolved"
    expected = _path_ids(math_engine)[1]
    assert stored[0].chosen_path_ref == expected


# ---------------------------------------------------------------------------
# H. labels carry no authority
# ---------------------------------------------------------------------------


def test_labels_do_not_change_selected_path(math_engine) -> None:
    path_ids = _path_ids(math_engine)
    math_engine.run_turn(SESSION_ID, PATH_A_TURN)
    outcome = math_engine.run_turn(SESSION_ID, PATH_B_TURN)
    assert outcome.confirmation_id is not None

    def relabel(texts: tuple[str, str]) -> list[str]:
        options = tuple(
            MethodOption(token=option.token, label=texts[i], description="")
            for i, option in enumerate(outcome.options)
        )
        payload = build_method_confirmation_payload(replace(outcome, options=options))
        return [o["option_id"] for o in payload["questions"][0]["options"]]

    ids_first = relabel(("Method one", "Method two"))
    ids_second = relabel(("Alpha approach", "Beta approach"))
    assert ids_first == ids_second
    assert ids_first == [option.token for option in outcome.options]

    chosen = math_engine.resolve(SESSION_ID, outcome.confirmation_id, ids_second[1])
    assert chosen == path_ids[1]


# ---------------------------------------------------------------------------
# I. invalid option identity is rejected
# ---------------------------------------------------------------------------


def test_unknown_option_id_does_not_resolve(math_engine) -> None:
    path_ids = _path_ids(math_engine)
    math_engine.run_turn(SESSION_ID, PATH_A_TURN)
    outcome = math_engine.run_turn(SESSION_ID, PATH_B_TURN)
    assert outcome.confirmation_id is not None

    for bogus in ("not-a-token", path_ids[1], "Method two"):
        with pytest.raises(ValueError):
            math_engine.resolve(SESSION_ID, outcome.confirmation_id, bogus)

    stored = math_engine.ledger.method_confirmations(math_engine.episode.workspace_id)
    assert stored[0].state == "pending"
    assert stored[0].chosen_path_ref is None


@pytest.mark.asyncio
async def test_unknown_selected_option_id_fails_closed(math_engine) -> None:
    await _run_capability(session_id=SESSION_ID, text=PATH_A_TURN)
    _, probe_events, _ = await _run_capability(session_id=SESSION_ID, text=PATH_B_TURN)
    question = _math_card(probe_events)["questions"][0]
    reply = {"answers": [{"questionId": question["id"], "selected_option_id": "forged-token"}]}
    _, events, _ = await _run_capability(session_id=SESSION_ID, text=PATH_B_TURN, reply=reply)
    assert [e for e in events if e.type == StreamEventType.RESULT] == []
    errors = [e for e in events if e.type == StreamEventType.ERROR]
    assert errors and errors[0].content == UNAVAILABLE_MESSAGE


# ---------------------------------------------------------------------------
# J. protected math without a trusted binding fails closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_binding_fails_closed(engine_modules, tmp_path) -> None:
    configure_math_turn_engine(None)
    try:
        context, events, _ = await _run_capability(session_id=SESSION_ID, text=PATH_A_TURN)
    finally:
        configure_math_turn_engine(None)
    _assert_unavailable(context, events)


@pytest.mark.asyncio
async def test_unenrolled_session_fails_closed(engine_modules, tmp_path) -> None:
    episode = ReviewedMathEpisode(
        session_id="some-other-session",
        workspace_id="dt:HB2-CA-02:unenrolled",
        db_path=str(tmp_path / "math-engine.sqlite3"),
        learner_id="dt-learner",
    )
    engine = MathTurnEngine(episode, modules=engine_modules)
    configure_math_turn_engine(engine)
    try:
        context, events, _ = await _run_capability(session_id=SESSION_ID, text=PATH_A_TURN)
    finally:
        configure_math_turn_engine(None)
        engine.close()
    _assert_unavailable(context, events)


def _assert_unavailable(context: UnifiedContext, events: list) -> None:
    errors = [e for e in events if e.type == StreamEventType.ERROR]
    assert errors, "a protected turn without binding must emit an unavailable state"
    assert errors[0].content == UNAVAILABLE_MESSAGE
    assert [e for e in events if e.type in (StreamEventType.RESULT, StreamEventType.CONTENT)] == []
    assert context.capability_output.agent_output == ""


def test_engine_run_turn_refuses_unbound_session(math_engine) -> None:
    with pytest.raises(MathTurnUnavailable):
        math_engine.run_turn("foreign-session", PATH_A_TURN)
