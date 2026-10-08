# MATH-TURN-CAPABILITY-02

Baseline: `wuchqwq/DeepTutor_plus-math-core`, `dev@6a2c6451b2f82b499830012d03cc2efe748b3ff5`.
Latest remote dev was fetched and matched that exact revision before work.
Migration Roadmap V2 (planning `a2a1905...`, sections 3.1 and 7.4), the
accepted extraction whitelist and PR #6's `MATH_SEMANTIC_EXTRACTION_01.md`
remain the migration authority. No source is taken from PR #2.

## Implemented contract

`MathTurnCapability.run(context, stream)` consumes only
`accepted_user_message_id` / `accepted_user_content` via the existing runtime
seam. The injected native proposal provider receives a native projection of
that exact accepted text, never the expanded prompt. Its output is a bounded
proposal; native Core performs grounding, relation validation, alignment,
trajectory reconstruction and mathematical authority calculation.

The existing optional host adapter now also accepts a trusted
`MathEpisodeBinding`: host session, actual accepted start row, and reviewed
learner/question/revision/episode source. The capability's resolver is explicit
constructor DI. It receives the accepted DTO, not `context.metadata`, request
configuration, source text, labels or model output. The composing host must
resolve authenticated learner and reviewed content scope. This opt-in stage
adds no product question-source authoring/selection workflow or routing.

An episode covers the ordered user rows from its accepted start through the
current accepted cutoff in that host session. The protected transaction reads
the entire bounded interval (maximum 32), verifies durable ID/raw/turn/client
metadata, pins its start and accepted IDs in the existing mathematical aggregate,
and rejects missing/changed basis or overlap with another episode. A new
reviewed episode closes the previous interval to further writes. All rows in
that interval count, including a row with no successful math alignment; such
missing evidence remains UNKNOWN. This intentionally supports consecutive
solving episodes, not interleaved episode resumption. Same-question restart
uses another explicit episode identity and independent workspace/ledger.

The aggregate contains host association refs, not another writable trajectory
or confirmation store. Existing Core owns immutable alignments, snapshots and
the sole confirmation ledger. The extraction's explicit-prefix API remains
for its contract fixtures; production capability uses the certified start-row
API exclusively.

Every preparation, alignment/trajectory, confirmation resolution/invalidation,
and authority calculation runs through `run_durable_turn_mutation`. Proposal
work happens outside the transaction; commit rechecks its pinned revision.
There is no ordinary-write fallback, lease-snapshot check followed by writing,
new database/table/service/coordinator/lease manager, or generic runtime change.
SQLiteSessionStore + MemoryCoordinator remains the supported host pairing.

## Confirmation and authority

Core-issued opaque token is emitted as existing `AskUserOption.option_id` in
`tool_metadata.ask_user`. The existing live turn reply queue supplies
`answers[].selected_option_id`; the exact confirmation question ID and token
must match. Text, display label and list position cannot select a path.
Core then checks the durable ledger, episode/learner/question, current source,
revision and issuing basis inside the protected resolution. Resolved-card
metadata is emitted only after resolution commits. Head drift invalidates the
pending ledger under the same live authority and rejects the reply. Choices
apply only to later accepted turns, preserving the frozen cutoff semantics.

Trajectory membership/applicability and literal-content identity are distinct
from verification. The result reports native relation/trajectory status and a
separate `verified_grounded_refs` subset. Only grounded matches to artifacts
already independently verified in the reviewed/native workspace enter that
subset. Unverified artifacts, unsupported/unparsed relations and absent
raw grounding cannot become mathematical truth through trajectory success.
Orientation grants supply no mathematics; literal result grants are restricted
to that verified subset and still pass Core's exact support/ceiling check.
`VERIFIED_FOR_LISTED_REFS` describes only the listed refs, never the whole path,
proof or student answer. Generic negative controls add no geometry semantics.

The terminal response is an evidence-recorded status and structured projection;
this stage adds no free-form final-answer generator. Host transport remains
unchanged. Result metadata does not prove crash-safe publication, routing
isolation or restart/reconnect recovery.

## Evidence

All focused capability tests start through `TurnRuntimeManager`, persist a user
row, assemble the real `TurnRuntimeContext`, route through an explicitly
registered observer subclass that calls production `MathTurnCapability.run`,
and commit through the actual SQLite protected port. No test substitutes a
hand-built UnifiedContext for that chain. Assertions inspect independent
SQLite reads and completion/error markers, so runtime-swallowed exceptions
cannot produce a false pass.

Coverage includes raw/ID/client equality despite attachment expansion, equal
text with distinct row/claim identities, same-question independent episodes,
closed old intervals, absent acceptance on regenerate/non-persist, corrupted
row evidence, absent authority, ownership loss before and after proposal,
missing historical basis, exact opaque A-to-B confirmation, token/label/stale
reply rejection, revision drift and unverified mathematics negative controls.
The existing host suite also tests ownership invalidation ordering during an
actual durable mathematical mutation.

PocketBase coverage runs the real PocketBaseSessionStore and turn executor
against the existing fake HTTP collection client: the accepted user row exists,
the executor provides no protected port, and production capability rejects
before source resolution/provider work. This is a backend contract test, not a
live PocketBase deployment claim. Redis coverage uses the real SQLite binder's
refusal of RedisCoordinator and the actual runtime missing-port rejection;
no distributed Redis commit guarantee is claimed.

The import gate now includes the capability's complete static dependency
closure and an isolated import with old/evaluation/fixture packages blocked.
Production `tutor_demo` imports are zero. Native Core and frozen oracle fixtures
are unchanged. The capability is absent from builtin specs and default routing.

Final commands/results are recorded below after verification.

Opt-in composition can use the existing catalog factory without changing
builtin registration or teaching the generic runtime a new dependency:

```python
catalog.register(
    name=MathTurnCapability.manifest.name,
    kind="turn",
    manifest=MathTurnCapability.manifest,
    factory=lambda: MathTurnCapability(
        resolve_episode=trusted_episode_resolver,
        provider=existing_alignment_provider,
    ),
)
```

These dependencies are host-owned, reviewed DI. This example is not added to
bootstrap; there is no global source catalog/binding or production demo seed.

## Verification commands and results

The Windows runs use normal user permissions for pytest-created temporary
folders, an ignored isolated `DEEPTUTOR_HOME`, and the already-declared
`tiktoken` dependency under ignored `data/test-deps`. The actual shipped agent
defaults are written to `data/test-home/data/user/settings/agents.yaml`; no
personal configuration is copied. An initial missing-parent test-directory
setup error and an initial missing-default-agent-config regression failure
were corrected in that ignored environment without changing assertions.

```powershell
$env:PYTHONUTF8 = '1'
$env:DEEPTUTOR_HOME = 'F:/demo2/DeepTutor_math_turn_capability_02/data/test-home'
$env:PYTHONPATH = 'F:/demo2/DeepTutor_math_turn_capability_02/data/test-deps;F:/demo2/DeepTutor_math_turn_capability_02'
python -m pytest tests/math_semantic -q --basetemp=data/pytest-semantic-final
python -m pytest tests/math_semantic/test_math_turn_capability.py tests/math_semantic/test_host_boundary.py tests/math_semantic/test_import_boundary.py -q --basetemp=data/pytest-focused-final
python -m pytest tests/math_semantic/test_math_turn_capability.py::test_plain_user_row_without_host_acceptance_turn_is_not_prefix_evidence -q --basetemp=data/pytest-provenance-final
python -m pytest tests/math_semantic/test_math_turn_capability.py -k path_reconstruction_never_upgrades -q --basetemp=data/pytest-negative-final
python -m pytest tests/services/session tests/runtime/test_orchestrator.py tests/tools/test_ask_user.py tests/app/test_turn_parked_on_ask_user_is_reclaimable.py tests/agents/chat/test_ask_user_drafts.py -q -k 'not test_sqlite_store_migrates_legacy_chat_history_db' --basetemp=data/pytest-nonmath-final-02
python -m mypy deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py --follow-imports=silent
python -m ruff check deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python -m ruff format --check deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python scripts/check_repo_hygiene.py
git diff --check
```

The full semantic run passed **796 cases in 242.74s** before final authored
label/host-turn provenance tightening. The affected final native/host/import
suite passed **43 cases in 49.51s**, with the additional plain-row provenance
control passing separately (**1 case**). The final strengthened negative
controls also require SUPPORTED path reconstruction with no domain verification
to remain UNKNOWN and orientation-only. Core and frozen fixtures are unchanged;
these focused reruns cover the subsequent host/capability edits.

Mypy: **26 source files pass**. Ruff check and format: **31 files pass**.
Repository hygiene and diff checks pass. Ordinary regression results follow.

The one disclosed Windows deselection is the unchanged
`test_sqlite_store_migrates_legacy_chat_history_db`: the test's SQLite context
manager retains an open connection while migration moves the file. PR #6
already reproduces that failure on its clean pinned baseline; this test is
byte-unchanged between that baseline and this stage's baseline. Neither its
runtime owner nor test is changed here.

## Scope disposition

- Production math capability: opt-in implementation; builtin/default routing unchanged.
- Native Core/frozen semantic oracle: unchanged; production old imports zero.
- Existing host adapter: episode-start/prefix certification only.
- Generic runtime/store schema/coordinator/provider selection/HTTP/WS routes: unchanged.
- New service/store/table/coordinator/lease manager/provider loop: none.
- Geometry, Memory/Mastery, retrieval, recovery, routing isolation and publication stages: not started.
- PR #2: untouched, formally replaced by this native seam implementation.

After verified closeout: commit, push, open a PR targeting dev, STOP; no merge.

```ini
REAL_ACCEPTED_SUBMISSION = PASS
NATIVE_MATH_CORE_ONLY = PASS
PROTECTED_MUTATION = PASS
MISSING_AUTHORITY_FAIL_CLOSED = PASS
UNSUPPORTED_BACKEND_FAIL_CLOSED = PASS
METHOD_CONFIRMATION = PASS
UNVERIFIED_MATH_NOT_UPGRADED = PASS
NON_MATH_TURN_CAPABILITY_REGRESSION = PASS
FINAL_FOCUSED_CHAIN_TESTS = PASS (44 final cases across affected reruns)
ORDINARY_REGRESSION = PASS (571 passed, 1 skipped, 1 disclosed baseline Windows deselection; 78.79s)
NEGATIVE_CONTROLS = PASS (3 strengthened cases; 6.71s)
PRODUCT_ROUTING_CHANGED = NO
RECOVERY_STARTED = NO
PUBLICATION_STARTED = NO
```
