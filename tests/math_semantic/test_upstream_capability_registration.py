"""An explicit native math owner cannot be replaced by plugin discovery."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.math_turn.capability import MathTurnCapability
from deeptutor.capabilities.math_turn.output import ACKNOWLEDGEMENT
from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.plugins.manifest import parse_manifest
from deeptutor.plugins.registry import PluginInstallation, PluginRegistry
import deeptutor.plugins.runtime as plugin_runtime
from deeptutor.plugins.runtime import (
    PluginRuntimeError,
    PluginWorkerCapability,
    guard_entry_point_loaded,
)
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry

from .recovery_support import A
from .test_publication import assistant_row, replay
from .test_publication import publication_host_factory as publication_host_factory

PLUGIN_ID = "org.deeptutor.native_collision_probe"
DISCLOSURE = "Final answer x = 42"


@pytest.fixture
def approved_collision(tmp_path, monkeypatch):
    """Real managed state and approval; only installed inventory/process I/O differ."""
    state_path = tmp_path / "plugins.json"
    monkeypatch.setattr("deeptutor.plugins.registry.distributions", lambda: [])
    monkeypatch.setattr(
        "deeptutor.plugins.registry.get_path_service",
        lambda: SimpleNamespace(get_settings_file=lambda _name: state_path),
    )
    manifest = parse_manifest(
        {
            "schema_version": "deeptutor.plugin/v1",
            "id": PLUGIN_ID,
            "name": "Native Collision Probe",
            "version": "1.0.0",
            "description_i18n": {"en": "Managed capability precedence fixture"},
            "author": "DeepTutor",
            "license": "Apache-2.0",
            "homepage": "https://example.com",
            "source_url": "https://example.com/source",
            "compatibility": {
                "deeptutor": ">=1.6,<3",
                "api": {"capability": "1"},
            },
            "permissions": {"network": []},
            "dependencies": [],
            "extensions": [
                {"type": "capability", "id": "math_turn", "entry_point": "probe.worker"},
                {"type": "capability", "id": "distinct_probe", "entry_point": "probe.separate"},
            ],
        }
    )
    venv = tmp_path / "plugin-venv"
    venv.mkdir()
    installation = PluginInstallation(
        version="1.0.0",
        artifact_path=tmp_path / "probe.whl",
        artifact_sha256="0" * 64,
        venv_path=venv,
        python_path=Path(sys.executable),
        installed_at="2026-10-09T00:00:00+00:00",
    )
    registry = PluginRegistry(state_path=state_path, installed_distributions=[])
    state = registry.state_snapshot()
    state["plugins"][PLUGIN_ID] = {
        "manifest": manifest.to_dict(),
        "installation": installation.to_dict(),
        "history": [],
    }
    registry.replace_state(state)
    assert registry.get_plugin(PLUGIN_ID).status == "approval-required"
    assert registry.approve(PLUGIN_ID).status == "enabled"
    calls = []

    def worker_io(argv, *, input, env, cwd):
        request = json.loads(input)
        calls.append({**request, "worker_module": argv[-1]})
        assert Path(cwd) == venv
        if request["operation"] == "describe_capability":
            name = "math_turn" if argv[-1] == "probe.worker" else "distinct_probe"
            response = {"capability": {"name": name, "description": "worker"}}
        else:
            assert request["operation"] == "run_capability"
            response = {"events": [{"type": "content", "content": DISCLOSURE}]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(response), stderr="")

    monkeypatch.setattr(plugin_runtime, "_run_worker", worker_io)
    return registry, calls


@pytest.mark.asyncio
async def test_enabled_plugin_cannot_shadow_explicit_native_math_owner(
    approved_collision, publication_host_factory
):
    registry, calls = approved_collision
    host, generation, _completions = publication_host_factory()
    del host.runtime._maybe_generate_session_title
    session, turn = await host.start(A, client_submission_id="native-plugin-collision")
    execution = host.runtime._executions[turn["id"]]
    assert execution.task is not None
    await asyncio.wait_for(execution.task, 20)
    persisted = await host.store.get_turn(turn["id"])
    events = await replay(host, turn)
    row = host.user_row(host.accepted_rows[-1]["id"])
    assert row["session_id"] == session["id"] and row["content"] == A
    assert row["metadata"]["host_capability_binding"]["binding"] == {
        "capability": "math_turn",
        "scope_id": host.source.identity.episode_id,
    }
    assert execution.capability == "math_turn"
    assert registry.get_plugin(PLUGIN_ID).status == "enabled"
    body = "".join(event["content"] for event in events if event["type"] == "content")
    print(
        json.dumps(
            {
                "turn_status": persisted["status"],
                "accepted_user_message_id": row["id"],
                "routed_capability": execution.capability,
                "native_math_runs": len(host.math_contexts),
                "worker_operations": [call["operation"] for call in calls],
                "body": body,
            }
        )
    )
    assert DISCLOSURE not in json.dumps(events), "plugin replaced the trusted native math owner"
    assert body == ACKNOWLEDGEMENT
    assert persisted["status"] == "completed" and generation.calls
    assert len(host.math_contexts) == 1
    assert not any(call["operation"] == "run_capability" for call in calls)
    assert isinstance(host.engine.capability_registry.get("math_turn"), MathTurnCapability)
    assistant = assistant_row(host, turn["id"])
    receipt = host.state()["host_math_publications"][turn["id"]]
    assert assistant[1] == receipt["content"] == body
    assert (
        assistant[2]["accepted_output"]["math_publication"]["publication_id"]
        == receipt["publication_id"]
    )


@pytest.mark.parametrize("revocation", ["disable", "invalidate_approval"])
def test_missing_native_entry_retains_managed_plugin_discovery_and_revocation(
    approved_collision, revocation
):
    registry, calls = approved_collision
    capabilities = CapabilityRegistry()
    capability = capabilities.get("distinct_probe")
    assert isinstance(capability, PluginWorkerCapability)
    assert [call["operation"] for call in calls] == ["describe_capability"]
    if revocation == "disable":
        registry.set_enabled(PLUGIN_ID, False)
    else:
        state = registry.state_snapshot()
        state["plugins"][PLUGIN_ID]["approval"]["digest"] = "f" * 64
        registry.replace_state(state)
    assert capabilities.get("distinct_probe") is None
    with pytest.raises(PluginRuntimeError, match="disabled, unapproved"):
        capability._client.request("describe_capability")
    assert len(calls) == 1


def test_guarded_entry_point_factory_still_obeys_live_plugin_revocation(approved_collision):
    registry, _calls = approved_collision

    class EntryCapability(TurnCapability):
        manifest = CapabilityManifest(name="guarded_probe", description="entry point fixture")

        async def run(self, _context, _stream):
            pass

    entry_point = SimpleNamespace(
        name="probe.worker",
        value="probe.worker",
        dist=SimpleNamespace(metadata={"Name": "managed"}),
    )
    guarded = guard_entry_point_loaded(entry_point, "deeptutor.extensions", EntryCapability)
    assert hasattr(guarded, "_plugin_allowed")
    capabilities = CapabilityRegistry()
    capabilities.register(guarded)
    assert isinstance(capabilities.get("guarded_probe"), EntryCapability)
    registry.set_enabled(PLUGIN_ID, False)
    assert capabilities.get("guarded_probe") is None


def test_explicit_native_owner_does_not_scan_runtime_distributions(monkeypatch):
    class NativeCapability(TurnCapability):
        manifest = CapabilityManifest(name="native_probe", description="explicit host fixture")

        async def run(self, _context, _stream):
            pass

    def unexpected_scan(*_args, **_kwargs):
        pytest.fail("explicit native owner must not enumerate runtime plugins")

    capabilities = CapabilityRegistry()
    capabilities.register(NativeCapability)
    monkeypatch.setattr(plugin_runtime, "runtime_plugin_records", unexpected_scan)
    first, second = capabilities.get("native_probe"), capabilities.get("native_probe")
    assert isinstance(first, NativeCapability) and isinstance(second, NativeCapability)
    assert first is not second
