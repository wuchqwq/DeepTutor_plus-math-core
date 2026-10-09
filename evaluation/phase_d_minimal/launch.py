"""Run the unchanged application with Phase D host DI, bound to localhost."""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=("ordinary", "integrated"), required=True)
    parser.add_argument("--case", choices=tuple(f"S{i}" for i in range(1, 9)), required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--catalog-home", type=Path, help="Existing user-configured standard Catalog home in this task; process-only service reuse, no credential copies")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--model", required=True, help="Exact configured DeepSeek model, including a rolling alias if applicable")
    parser.add_argument("--port", type=int, default=49301)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--request-limit", type=int, default=12)
    parser.add_argument("--check", action="store_true", help="Construct the real dependency graph, start/close coordinator; no turn or model call")
    args = parser.parse_args()
    if not args.model.lower().startswith("deepseek"):
        parser.error("This experiment requires DeepSeek")
    home, evidence = args.home.resolve(), args.evidence.resolve()
    # Restrict writes to this task's repository and keep evidence outside runtime.
    for target in (home, evidence):
        if not target.is_relative_to(ROOT / "data"):
            parser.error("home/evidence must be inside this checkout's ignored data directory")
    if evidence.is_relative_to(home) or home.is_relative_to(evidence):
        parser.error("runtime and evidence directories must be separate")
    home.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    os.environ["DEEPTUTOR_HOME"] = str(home)
    os.environ["DEEPTUTOR_VERSION_CHECK_ENABLED"] = "false"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    from source import make_source, write_source_evidence
    from provider import RealAlignmentProvider, observe_sdk_calls
    from deeptutor.app.container import ApplicationContainer, set_application_container
    from deeptutor.capabilities.math_turn.capability import MathTurnCapability
    from deeptutor.core.context import CapabilityBinding
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.runtime.turn_engine import TurnEngine
    from deeptutor.services.llm.config import get_llm_config, set_scoped_llm_config

    # Reuse the existing standard Catalog service while all student persistence
    # remains in this case's own home. This is only an in-process DI entry;
    # there is no new credential store, file link, migration, or value export.
    catalog_path = None
    if args.catalog_home is not None:
        from deeptutor.services.config.model_catalog import ModelCatalogService
        from deeptutor.services.path_service import get_path_service
        catalog_home = args.catalog_home.resolve()
        if not catalog_home.is_relative_to(ROOT / "data"):
            parser.error("catalog-home must be an existing standard home inside this task's data directory")
        catalog_path = catalog_home / "data/user/settings/model_catalog.json"
        if not catalog_path.is_file():
            parser.error("The user-configured standard Catalog does not exist")
        local_catalog = get_path_service().get_settings_file("model_catalog").resolve()
        ModelCatalogService._instances[str(local_catalog)] = ModelCatalogService.get_instance(catalog_path)

    observe_sdk_calls(evidence, allow_paid=args.allow_paid, expected_model=args.model, request_limit=args.request_limit)
    authentication = "NOT_CONFIGURED"
    try:
        config = get_llm_config()
    except Exception:
        config = None
    if config is not None:
        if config.binding != "deepseek" or config.model != args.model:
            raise RuntimeError("Catalog must select the same DeepSeek model as --model")
        authentication = "STANDARD_CATALOG_CONFIG_PRESENT_NOT_NETWORK_VERIFIED"
        set_scoped_llm_config(replace(config, temperature=0, max_tokens=4096, max_concurrency=1))
    if args.allow_paid and config is None:
        raise RuntimeError("Configure DeepSeek in this runtime's Settings > Catalog before permitting real calls")

    container = ApplicationContainer.build()
    if container.settings.backend != "memory":
        raise RuntimeError("Phase D minimal experiment requires one local MemoryCoordinator worker")
    if args.arm == "integrated":
        accepted_scope = None
        adapter = RealAlignmentProvider(args.model, evidence)
        # One isolated process serves one case. Sources are deterministic for a
        # real authenticated host session, and survive refresh without a second registry.
        def source_for(session_id):
            learner = get_current_user().id
            episode = "phase_d_" + hashlib.sha256(f"{args.case}:{learner}:{session_id}".encode()).hexdigest()[:24]
            return make_source(episode, learner)

        async def route(accepted_reference):
            nonlocal accepted_scope
            scope = (get_current_user().id, accepted_reference.session_id)
            if accepted_scope is None:
                accepted_scope = scope
            if accepted_scope != scope:
                raise RuntimeError("This isolated experiment process serves one learner/session/case")
            return CapabilityBinding("math_turn", source_for(accepted_reference.session_id).identity.episode_id)

        def resolve_episode(submission):
            # Native capability invokes this on its running host loop before
            # moving the synchronous propose() seam into a worker thread.
            adapter.loop = asyncio.get_running_loop()
            source = source_for(submission.session_id)
            write_source_evidence(source, evidence / "sources" / source.identity.episode_id, submission.raw_content)
            return source

        container.capability_registry.register(lambda: MathTurnCapability(
            resolve_episode=resolve_episode,
            provider=adapter))
        engine = TurnEngine(container.capability_registry, resolve_accepted_capability=route)
        container.turn_engine = engine
        container.runtime_registry.turn_engine = engine
    set_application_container(container)
    manifest = {"arm": args.arm, "case": args.case, "model": args.model, "provider": "deepseek", "snapshot_available": "not assumed; retain actual response model and UTC metadata", "temperature": 0, "top_p": "provider default; actual wire recorded", "ordinary_output_cap": 4096, "alignment_output_cap": 2048, "selector_output_cap": 1024, "request_limit": args.request_limit, "allow_paid": args.allow_paid, "authentication": authentication, "runtime_home": str(home), "evidence": str(evidence), "base_sha": "143e41784bdd2c34d765a50c754869ef3a2d9830", "teaching_and_publication": "unchanged", "provider_execution": "NOT_RUN_AT_STARTUP"}
    manifest["standard_catalog_path"] = str(catalog_path) if catalog_path else "this runtime's own Catalog"
    manifest["credential_copy_or_file_link"] = False
    manifest["top_p"] = 1
    (evidence / "run_config.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if args.check:
        if args.allow_paid:
            parser.error("--check does not permit --allow-paid")
        async def check():
            await container.start()
            assert await container.coordinator.health()
            if args.arm == "integrated":
                assert isinstance(container.capability_registry.get("math_turn"), MathTurnCapability)
            await container.close()
        asyncio.run(check())
        print(json.dumps({"status": "REAL_CONTAINER_START_CLOSE_PASS", "provider_calls": 0, "arm": args.arm, "authentication": authentication}))
        return
    from deeptutor.api.main import app
    app.state.application_container = container
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1, log_level="info")


if __name__ == "__main__":
    main()
