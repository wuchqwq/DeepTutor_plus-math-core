# POC-RECOVERY-02

Baseline: `wuchqwq/DeepTutor_plus-math-core`,
`dev@1e7187c4baa324d986a73147ed51869e30929e9d` (merged native Capability-02).
Remote dev was fetched and matched this exact revision before work. Migration
Roadmap V2 section 7.5 and the accepted extraction/capability contracts remain
the authority. This stage ends with a PR to dev; no merge or next stage.

## Minimal recovery change

The baseline capability requires a `MathEpisodeBinding` containing the first
accepted message ID. That binding can be supplied by a process-local resolver,
even though its start and accepted IDs already exist in the SQLite aggregate.
Fresh composition should not need that old object or an out-of-transaction
reader to recreate it.

The existing capability resolver and `sqlite_episode_mutation` now also accept
a native `ReviewedSource`. Trusted DI still supplies the stable reviewed
episode/learner/question/source identity and authored content. It supplies no
historical start, accepted IDs, math revision, ledger, or derived trajectory.
The existing explicit binding API remains compatible. This is not a generic
episode selection or content-authoring workflow.

Inside `run_durable_turn_mutation`, the existing host adapter:

1. Loads the named aggregate and verifies its host session.
2. Recovers its certified start from `host_episode_first_message_id`. Only a
   genuinely new aggregate starts at the current host-accepted row; a damaged
   existing aggregate fails closed and is never initialized again.
3. Reads the complete ordered bounded user interval from SQLite. Current
   ID/raw/turn/client metadata must equal the runtime accepted submission.
   Every historical row must have a corresponding host turn, and accepted
   message/turn identities must be unique.
4. Requires the durable accepted-ID basis to remain a nonempty exact prefix;
   keeps the existing superseded/overlapping-episode rejection.
5. Uses native `MathMutation` to check reviewed source identity/content and
   requires the SQLite math revision to equal its canonical snapshot head.
6. Uses the existing native alignment, trajectory, confirmation and authority
   calculation. Historical claim spans are rechecked against reopened raw user
   rows by Core. Missing grounding rejects observation; recovery cannot turn
   it into mathematical truth.

All reads and writes of the aggregate stay under the existing protected commit
authority. There is no ordinary-write fallback. Core, schema, host runtime,
coordinator, provider selection and default capability registration are
unchanged. There is no new recovery manager, registry or durable state owner.

## Executable recovery evidence

`tests/math_semantic/recovery_support.py` is test-only composition. Each instance
independently loads the inert reviewed source fixture and creates a new SQLite
store, `MemoryCoordinator`, registry, engine and `TurnRuntimeManager`. Its
registered observer calls the production `MathTurnCapability.run`; its injected
provider only proposes native alignment input. Skill discovery/title generation
are isolated; subprocesses use the same fake model configuration as the existing
pytest isolation fixture. No LLM/network request is needed.

The real chain is:

```text
fresh SQLiteSessionStore + fresh MemoryCoordinator + fresh TurnRuntimeManager
  -> persisted accepted user row
  -> TurnRuntimeContext / registered production MathTurnCapability
  -> existing protected SQLite math aggregate
  -> native Core trajectory / confirmation / authority
```

The tests close runtime/coordinator objects and construct independent replacements
over the same DB. SQLite's existing owner closes each operation's connection;
there is no persistent store connection or store-level `close` method. Test-only
inspection/tampering connections are also explicitly closed. Object identities,
empty execution/queue maps and absent old leases are checked. A repeated text
after restart gets a new actual host message ID and exactly one new alignment.

The stronger test launches `python -m tests.math_semantic.recovery_worker` twice
with different OS process IDs. The successor receives only DB path, host session
and old turn ID for assertions; each process independently constructs reviewed
source DI. No old manager, coordinator, binding, prefix, math projection or Python
object is passed to it. The seed advances the actual durable Core head through
the protected port, so recovering the authored initial revision cannot pass.

| Control | Required observed result |
| --- | --- |
| Completed worker exits; independent worker accepts next math row | Same durable episode/start/head and exact historical prefix |
| Reconstruct the same committed cutoff from reopened history | Exact trajectory and authority equality; reconstruction changes no Core records |
| Resolved confirmation, then worker exits | One resolved ledger entry persists; a different future path-specific claim remains constrained to its exact chosen path |
| Pending ledger and `waiting_input` commit, then actual OS worker kill | Pending survives; no old reply queue/lease can resolve it |
| Next accepted claim is different, uniquely path-B evidence | Existing pending card/token/path mapping is re-presented; no automatic resolution or result bypass |
| Explicit exact opaque choice after object reconstruction | Only the existing confirmation is resolved to its exact authored path |
| Forged token, stale question ID, display label after restart | Reject; pending ledger unchanged; no mathematical result |
| Exact old token, but protected head changes before resolution | Reject and durably invalidate; no chosen path or mathematical result |
| Successful path reconstruction with qualified/unverified artifacts | Remains UNKNOWN with orientation-only grants |
| Unsupported semantic relation after process reconstruction | UNKNOWN, empty verified subset; recovery adds no result authority |
| Missing start/empty prefix/deleted historical row/missing host turn/revision mismatch/changed learner/changed source | Production capability rejects; aggregate is not rewritten/reinitialized |
| Historical raw text changed after close | Production Core rejects its old claim grounding and rolls back proposed alignment/confirmation evidence |
| Subscribe/replay old turn twice through the fresh manager | Read-only identical events; no capability rerun; aggregate unchanged |

The historical projection instrument reads the validated transaction-local
prefix/payload and runs native Core on the committed cutoff; no cached previous
projection is supplied. It asserts serialization is unchanged. Its comparison
value is test-only, not another writable trajectory state. Corrupt-basis tests
disable this instrument, so their rejection must come from production code.

For the raw-corruption control, the existing preparation transaction can append
the genuinely accepted new row to host basis metadata before native observation
rejects the historical claim. The old alignment/confirmation/snapshots and math
revision remain unchanged; the proposed new mathematical evidence rolls back
and no result is produced. This does not repair or forgive corrupted history.

Historical alignment keys/payloads, snapshots and confirmation entries are
compared exactly across recovery. A genuinely new accepted turn creates exactly
one new alignment; it does not duplicate any old entry. The aggregate stays a
single row and contains no derived trajectory field/store. Re-presentation emits
a new turn's card event for the same existing confirmation, not another ledger.

## Host parked-turn boundary

A killed worker leaves a durable `waiting_input` row. A bare fresh
`TurnRuntimeManager.start_turn` rejects with `ActiveTurnConflict`, and an old
turn reply has no queue. That is the host's missing live continuation at the
bare manager seam, not missing mathematical state.

The existing `TurnApplicationService.start_turn` already reclaims that unowned
active row using its terminal CAS, marks it `failed / worker_lost`, and accepts
the next real user turn. The process test uses this existing application owner;
the math capability then recovers/re-presents the pending ledger. No generic
turn resume, queue restoration, HTTP/WS change or host lifecycle rewrite is
introduced. This proof covers the SQLite/single-process MemoryCoordinator
pairing, not distributed or PocketBase/Redis recovery.

## Local verification

Windows execution uses an ignored isolated home, shipped default agent settings
and the already-declared `tiktoken` dependency under ignored `data/test-deps`.
Subprocess test setup initially lacked pytest's fake model resolver and the test
report exceeded asyncio's default line limit; both harness issues were corrected
without changing production provider behavior or weakening assertions.

```powershell
$env:PYTHONUTF8 = '1'
$env:DEEPTUTOR_HOME = 'F:/demo2/DeepTutor_poc_recovery_02/data/test-home'
$env:PYTHONPATH = 'F:/demo2/DeepTutor_poc_recovery_02/data/test-deps;F:/demo2/DeepTutor_poc_recovery_02'
python -m pytest tests/math_semantic/test_recovery.py -q --basetemp=data/pytest-recovery-final-02
python -m pytest tests/math_semantic/test_recovery.py::test_closed_runtime_store_coordinator_reopen_without_binding -q --basetemp=data/pytest-replay-final
python -m pytest tests/math_semantic/test_recovery.py tests/math_semantic/test_math_turn_capability.py tests/math_semantic/test_host_boundary.py tests/math_semantic/test_import_boundary.py -q --basetemp=data/pytest-recovery-focused-final
python -m pytest tests/services/session tests/runtime/test_orchestrator.py tests/tools/test_ask_user.py tests/app/test_turn_parked_on_ask_user_is_reclaimable.py tests/app/test_waiting_turn_recovery.py tests/app/test_turn_application_service.py tests/app/test_multiworker_turn_application.py tests/agents/chat/test_ask_user_drafts.py -q -k 'not test_sqlite_store_migrates_legacy_chat_history_db' --basetemp=data/pytest-ordinary-recovery-final
python -m mypy deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py --follow-imports=silent
python -m ruff check deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python -m ruff format --check deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python scripts/check_repo_hygiene.py
git diff --check
# After the stage commit, also require a clean task checkout:
python scripts/check_workspace_hygiene.py
```

Final recovery suite: **17 passed in 67.18s**, including three independent-process
scenarios and an actual pending-worker kill. Native capability/host/import
regression: **44 passed** within the earlier combined **60 passed in 113.17s**
run; subsequent changes strengthened only recovery tests/docstrings, covered by
the final 17-case rerun. The subsequent strengthened manager-level read-only
subscribe/replay control passed separately (**1 case in 6.33s**). Mypy:
**26 source files pass**. Ruff lint and format:
**34 files pass**. Repository content hygiene and diff checks pass.

Ordinary regression: **583 passed, 1 skipped, 1 deselected, 7 warnings in 168.55s**.
Its one explicit Windows deselection is the unchanged legacy chat-history
migration test whose
open test SQLite connection prevents moving its DB. This preexisting limitation
is documented in `MATH_TURN_CAPABILITY_02.md`; that test/store lifecycle is
unchanged here. It is not reported as a passed test.

GitHub Actions is **NOT_RUN_QUOTA**, per Owner instruction. The stage commit uses
`[skip ci]`; no workflow/config change or manual workflow run is made. Local
verification is the evidence for this PR.

```ini
STAGE = POC_RECOVERY_02
BASE = 1e7187c4baa324d986a73147ed51869e30929e9d
DURABLE_EPISODE_RECOVERY = PASS
TRAJECTORY_AFTER_RESTART = PASS
RESOLVED_CONFIRMATION_AFTER_RESTART = PASS
PENDING_CONFIRMATION_FAIL_CLOSED_OR_RECOVERED = PASS
NO_DUPLICATE_MATH_EVIDENCE = PASS
AUTHORITY_AFTER_RESTART = PASS
PROCESS_LOCAL_BINDING_REQUIRED = NO
GENERIC_RUNTIME_CHANGED = NO
MATH_CORE_CHANGED = NO
NEW_SERVICE = NO
NEW_STORE = NO
NEW_TABLE = NO
NEW_RECOVERY_MANAGER_COORDINATOR_REGISTRY = NO
PRODUCT_ROUTING_CHANGED = NO
ROUTING_STARTED = NO
PUBLICATION_STARTED = NO
GITHUB_ACTIONS = NOT_RUN_QUOTA
```
