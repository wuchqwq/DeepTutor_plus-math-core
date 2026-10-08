# MATH-SEMANTIC-EXTRACTION-01

This stage extracts approved mathematical responsibilities into
`deeptutor/math_semantic`. It preserves canonical mathematical outcomes while
removing the old acceptance, provider, planner and storage owners. It does not
register a math capability or connect the package to a product turn.

## Provenance and scope

| Authority | Exact revision / source |
| --- | --- |
| DeepTutor implementation base | `73774dc26a734c040d3f91bc887060127475178f` |
| tutor_demo planning base | `a2a1905dc41eed3e5a574304993c2747dcb0838c` |
| Actual frozen mathematical runtime oracle | `76d5d9697186d086fb967e79a9e08e394b0d5474` |
| Whitelist | `MATH-ENGINE-EXTRACTION-WHITELIST-01`, planning `docs/design/MATH_ENGINE_EXTRACTION_WHITELIST_01.md` |
| Roadmap | planning `docs/design/DEEPTUTOR_MATH_MIGRATION_ROADMAP_V2.md` |

The planning revision contains later documentation. It does not replace the
runtime revision frozen by the whitelist. All 21 eligible source files were
checked byte for byte between the planning archive and the frozen runtime;
their SHA-256 values agree. The machine-readable
[source map](../../evaluation/math_semantic_extraction/source_map.json) retains
both revisions, hashes of the three planning authorities, every whitelist row,
approved slices, exclusions, new owners and oracle coverage.

The map accounts for all 107 unique manifest paths: 4 `MIGRATE`, 17
`MIGRATE_WITH_ADAPTATION`, 36 `REGRESSION_ONLY`, 22 `DO_NOT_MIGRATE`, 24
`DELETE_AFTER_CUTOVER` and 4 `REQUIRES_OWNER_DECISION`. Only the first two
classifications supply production slices. All four owner-decision files remain
excluded. No cutover deletion is performed in tutor_demo.

The expanded Owner instruction was reconciled with the already prepared
mathematical slices before adding host composition. Approved runtime inputs
have the exact frozen contents; this reconciliation does not silently select a
new oracle or import additional old owners.

## Compact old-to-new map

Old paths below are relative to `src/tutor_demo/`; native paths are relative to
`deeptutor/math_semantic/`. The host adapter is
`deeptutor/services/session/math_semantic_persistence.py`.

| Old source | Protected responsibility | Class | Native owner / mode | Oracle coverage |
| --- | --- | --- | --- | --- |
| `math_core/contracts.py` | Facts/models, artifact identities/content, paths, dependencies and relative closure | MIGRATE | `contracts.py`; mathematical values | Snapshots, dependency closure, trajectory |
| `math_core/tools.py` | Restricted operations, budgets/deadlines and scoped validation evidence | MIGRATE | `tools.py`; bounded synchronous mathematics | Tool guards, validation, scoped evidence |
| `math_core/student_proposals.py` | Grounded student origin and independently validated partial candidate admission | MIGRATE | `student_proposals.py`; accepted-evidence adaptation | Grounded/novel alignment, uncertainty |
| `alignment/contracts.py` | Claims, spans, correspondence, active/unshown/divergence and immutable alignments | MIGRATE | `claims.py`; mathematical DTOs | Claims, relations, active paths |
| `core.py` | Neutral learner, question and source-reference values | ADAPT | `refs.py`; scope values only | Reviewed binding, trajectory, confirmation |
| `responses.py` | Real accepted identity/raw content and ordered evidence consumption | ADAPT | `accepted.py`, `state.py`, host adapter; no acceptance lifecycle | Actual accepted seam, grounding, prefix checks |
| `teaching_claims.py` | Only expression/check fields and required parser helper | ADAPT | `expression.py`; minimal neutral value/error | Unsupported/ambiguous math, validation |
| `math_validation.py` | Normalization and bounded structural verification/correspondence | ADAPT | `verification.py`; neutral expression input | Equivalent/partial/unresolved/contradictory math |
| `math_core/validation.py` | Neutral request/result and killable worker timeout | ADAPT | `validation.py`; no teaching contracts | Deadline, verifier unavailable, fail closed |
| `math_core/workspace.py` | Pinned codecs, append/CAS, supersession and domain-attempt identity | ADAPT | `workspace.py`, `state.py`, host adapter; no SQL owner in Core | Revisions, mutation atomicity, idempotency |
| `math_core/reasoner.py` | Bounded proposals/projections, mathematical materialization and domain-attempt state | ADAPT | `reasoning.py`, `state.py`; pure functions and injected protocol | Proposal bounds, tool-ref guards, attempt/materialization |
| `math_core/transformations.py` | Rational-linear relative equivalence and eight-operation bound | ADAPT | `transformations.py`, `state.py`, host adapter; atomic domain materialization | Operation scope, replay, budgets |
| `alignment/provider.py` | Bounded extraction DTOs, exact occurrence resolution and transport-neutral protocol | ADAPT | `proposals.py`; provider implementation excluded | Duplicate/missing/forged spans, proposal schema |
| `alignment/service.py` | Grounded correspondence, active/unshown/divergence and novel admission | ADAPT | `alignment.py`; pure materialization | Natural-math corpus and full grounded alignments |
| `alignment/store.py` | Immutable alignment and atomic output workspace revision | ADAPT | `codec.py`, `state.py`, host adapter; existing commit owner | Immutable replay/conflict, alignment-plus-workspace |
| `teaching_planner/contracts.py` | Only math projections, trajectory and confirmation values | ADAPT | `trajectory_types.py`; no planner DTOs | Status/region/token/state outcomes |
| `teaching_planner/projection.py` | Pure artifact/alignment and accepted-prefix trajectory derivation | ADAPT | `trajectory.py`; no planner input builder | Single/multi-path, divergence, second seed |
| `teaching_planner/evidence.py` | Exact reviewed source, grounded prefix and pinned reconstruction/resolution checks | ADAPT | `state.py`, host adapter; no Assessment or old host joins | Drift, foreign basis, missing evidence/authority |
| `teaching_planner/service.py` | Confirmation state machine and mathematical applicability subset | ADAPT | `confirmation.py`, `ceiling.py`, `state.py`, host adapter | Exact tokens, stale/foreign rejection, next-turn cutoff |
| `teaching_planner/assistance.py` | Full-content digest and finite math grant/support constraints | ADAPT | `authority.py`; no generic assistance policy | Exact relation binding, no truth upgrade |
| `teaching_planner/math_support.py` | Finite literal content and relative operation support | ADAPT | `support.py`; pinned snapshot resolver | Authority ceiling, operation/support scope |

`ADAPT` means `MIGRATE_WITH_ADAPTATION`, not permission to copy an entire file.
Historical mechanism labels containing the former alignment class name remain
data identifying a frozen comparator. They are not imports or retained service
objects.

## Native boundaries and subtraction

`AcceptedSubmission` is an immutable consumption value. The optional host
adapter obtains its identity and raw content from `TurnRuntimeContext` and
verifies them against the existing persisted user row inside the protected
mutation. A client submission ID remains causal metadata; it does not become
the accepted message identity. Core does not infer acceptance from prompts,
hashes, counters, model output or client declarations. Regenerate and
non-persisted executions have no new accepted identity and fail this input
boundary.

`ReviewedSource` and the explicit episode identity are trusted DI inputs.
Session-to-episode resolution and completeness certification belong to the
later capability stage. Core consumes a bounded, complete ordered prefix,
checks grounding and relevant revisions, and reconstructs mathematical
interpretation. Missing alignment remains unknown; missing authority cannot
write. An episode ID is not synthesized from a session, workspace revision or
prompt. The package adds no resolver or registry.

The host adapter verifies the supplied rows, uniqueness, size and current
accepted cutoff. It does not certify which session rows belong to a solving
episode or establish their mathematical order/ordinal. Those guarantees are
explicit trusted-composition preconditions for the supplied complete prefix;
this stage does not accept client metadata as that certification or claim
episode binding has been proved.

`MathMutation` contains transaction-local canonical domain records;
`MathMutationAuthority` is the narrow injected commit port. They own neither
a connection nor a commit, lease, session or accepted response lifecycle.
`run_math_operation` rejects an absent authority. The host adapter loads and
saves mathematical records through `run_durable_turn_mutation`; there is no
check-lease / await / ordinary-write path. The existing SQLite owner still
owns initialization, restricted SQL execution, rollback and durable commit.

The native package imports only its mathematical modules, standard-library
facilities and optional bounded SymPy verification. SQLite and persisted host
user-row access remain outside Core. Proposal protocols describe structured
inputs; they do not execute, configure or retry providers.

The old `StudentResponse` acceptance factory, `SQLiteLearningStore`, private
`MathWorkspaceStore` connection/lock, concrete `AlignmentStore`, provider-owning
`ResponseAlignmentService` and `MathReasoner`, `SlimTeachingPlannerService` and
`SlimTeachingPlannerStore`, old `ReviewedMathTask`/Assessment joins, generic
teaching plan/assistance/progression classes and eager demo exports do not
exist in the extracted implementation. Scripted providers, authored demo
seeds and instrumentation remain oracle-only. Generic Tutor, Adoption,
Delivery, Memory/Mastery, web/session/runtime/provider shells and the PR #2
adapter are excluded.

This is subtraction from the new active dependency graph, not deletion of
the historical oracle. Existing DeepTutor accepted-message, turn/runtime,
provider, session, coordinator and publication owners retain their work. No
second database, accepted-submission ledger, lease manager, provider loop,
trajectory manager, generic graph engine or teaching pipeline is introduced.

## Persistence choice and complexity gate

The adapter supports the already accepted SQLiteSessionStore / same-process
MemoryCoordinator protected-mutation pairing. PocketBase and Redis do not
provide this protected port and are unsupported for these mathematical
mutations. Their ordinary runtime remains unchanged. Multi-process authority,
cross-backend operation, product episode binding, restart/reconnect recovery,
retention policy, source publication, routing and publication remain later
Owner decisions; this stage does not claim their guarantees.

The existing SQLite initialization adds one `math_semantic_episodes` table in
the existing host database. Core records retain immutable workspace snapshots
and alignments, necessary attempt/transform identities and confirmation
lifecycle; a derived trajectory is not a second writable canonical state.
The table has no new cascade or foreign-key deletion policy. Removing host
accepted evidence leaves the mathematical records retained, but reconstruction
rejects the missing basis. Retention and authorized cleanup remain an Owner
decision rather than an implicit extraction side effect.

The roadmap's table gate is answered as follows:

- **Observed failure:** existing user/turn rows preserve host acceptance and
  execution, but have no canonical revision-pinned mathematical workspace,
  alignment or confirmation records.
- **Why the existing owner alone cannot represent it:** using user-message
  text or generic session summaries as mathematical truth would lose the
  protected immutable basis. The old private mathematical SQLite owner is
  prohibited.
- **Why a small adapter suffices:** this adapter uses one domain aggregate
  table initialized by the existing SQLite owner and its existing protected
  transaction port. It introduces no database, connection owner, service,
  transaction framework or coordinator. SQL is absent from pure Core.

This backend choice implements the explicit native persistence authorization
against the merged commit contract. It does not silently promote any of the
four `REQUIRES_OWNER_DECISION` implementation units.

## Regression evidence

The offline oracle runner imports the exact frozen checkout only to capture
canonical semantic expectations. Native pytest consumes checked-in fixtures
without importing the old package or relying on an external checkout. Only
wall-clock `duration_ms` instrumentation is excluded from comparisons; IDs,
content, provenance, scopes, relations, path status/applicability and
confirmation outcomes remain compared.

The oracle includes CA02 and independent second-seed task variants with
different path counts, authored revisions and opaque labels. It compares
shared and exclusive observations, unknown/contradictory evidence,
divergence, pending/resolved confirmation, exact opaque option-token mapping,
future-turn cutoff and unchanged negative controls. Reconstructed domain
records exercise the supported mathematical persistence semantics; they do
not prove product recovery.

The import gate walks AST imports in all scopes, including lazy, relative and
`TYPE_CHECKING` imports, follows the native/host-adapter import closure, checks
all 107 source-map rows and imports the native package in an isolated process
with old runtime/evaluation/fixture imports blocked.

Focused verification commands and their final results are recorded below by
the implementation owner. The scope is the semantic suite and touched-owner
ordinary regressions; it does not require a full repository suite.

The independent source/import gate passed: `python -m pytest
tests/math_semantic/test_import_boundary.py -q` — **4 passed**. The Windows run
used an isolated `DEEPTUTOR_HOME`, repository `PYTHONPATH` and worktree-local
`--basetemp` under normal temporary-directory permissions. Its isolated
package-import subprocess clears external `PYTHONPATH` and blocks the oracle
packages.

```text
SEMANTIC_ORACLE = PASS (774 semantic/import/real-host tests)
SECOND_SEED = PASS (independent single/two/three/opaque-path variants)
CONFIRMATION = PASS (exact token mapping, ledger/wrapper outcomes, cutoff and negative controls)
NON_MATH_REGRESSION = PASS (571 passed, 1 skipped, 1 disclosed baseline-only deselection)
TYPECHECK = PASS (24 native Core/adapter source files)
LINT = PASS (Ruff check and format, including the existing SQLite owner)
PRODUCT_ROUTING_CHANGED = NO
GENERIC_RUNTIME_CHANGED = NO
MATH_TURN_CAPABILITY_02_STARTED = NO
```

The non-math gate was run with the shipped default agent settings in an ignored
test home, the already declared `tiktoken` dependency installed in ignored
worktree-local `data/test-deps`, and no developer configuration changes:

```powershell
$env:PYTHONUTF8 = '1'
$env:DEEPTUTOR_HOME = 'F:\demo2\DeepTutor_math_semantic_extraction_01\data\non-math-regression-home'
$env:PYTHONPATH = 'F:\demo2\DeepTutor_math_semantic_extraction_01\data\test-deps;F:\demo2\DeepTutor_math_semantic_extraction_01'
python -m pytest tests/services/session tests/runtime/test_orchestrator.py tests/tools/test_ask_user.py tests/app/test_turn_parked_on_ask_user_is_reclaimable.py tests/agents/chat/test_ask_user_drafts.py -q -k 'not test_sqlite_store_migrates_legacy_chat_history_db' --basetemp=data/non-math-pytest-02
python -m pytest tests/math_semantic -q --basetemp=data/semantic-final-sequential
python -m mypy deeptutor/math_semantic deeptutor/services/session/math_semantic_persistence.py --follow-imports=silent
python -m ruff check deeptutor/math_semantic deeptutor/services/session/math_semantic_persistence.py deeptutor/services/session/sqlite_store.py tests/math_semantic evaluation/math_semantic_extraction
python -m ruff format --check deeptutor/math_semantic deeptutor/services/session/math_semantic_persistence.py deeptutor/services/session/sqlite_store.py tests/math_semantic evaluation/math_semantic_extraction
python scripts/check_repo_hygiene.py
```

On this Windows sandbox, pytest-created temporary-directory ACLs require these
tests to run with normal user permissions outside the sandbox. No assertion is
skipped to work around that environment issue. The non-math result is **571
passed, 1 skipped, 1 deselected in 76.17 seconds**. The single deselection is
`test_sqlite_store_migrates_legacy_chat_history_db`: its legacy SQLite connection
context manager leaves the connection open, so Windows rejects the migration's
file move. The exact same failure was reproduced on a clean detached
`73774dc...` checkout. Three initial environment failures also reproduced there;
they passed after restoring the declared tokenizer dependency and isolated
default agent settings. No baseline runtime/test fix is included.

`scripts/check_architecture.py` independently reports the same existing
`core -> domain_runtime` cycle and `core/context.py` import of runtime
coordination on both this branch and the clean exact baseline. It is recorded
as a baseline failure, not as a passed gate or an extraction change.

The old capture produced a load-dependent validation timeout when concurrent
native tests were active. A sequential independent recapture, with unchanged
five-second budget and all 83 source hashes checked, matched the first old
capture exactly. One contended final native run likewise failed its novel
alignment assertion (773 other cases passed); that case passed alone. Timed
out validation is never normalized into verified/refuted truth. Explicit
zero-budget old/native controls compare the closed timeout result separately.
The final full semantic gate ran sequentially with no overlapping checks:
**774 passed in 191.94 seconds**. This includes 754 frozen semantic/boundary
comparisons and controls, 16 real accepted-runtime/host-mutation tests and four
source-map/import tests. No fixture was rewritten from a native outcome and
no mathematical assertion or validation deadline was weakened.

## Diff budget and closeout

```text
RUNTIME_FILES_CHANGED = 25
RUNTIME_LINES_ADDED = 5397
RUNTIME_LINES_DELETED = 0
TEST_FILES_CHANGED = 10
TEST_LINES_ADDED = 3615
TEST_LINES_DELETED = 0
NEW_RUNTIME_FILES = 24
NEW_RUNTIME_ABSTRACTIONS = immutable mathematical DTOs; pure functions;
  transaction-local MathMutation; narrow MathMutationAuthority;
  optional existing-owner persistence adapter
```

Runtime counts include 23 Core modules, the optional host adapter and nine
initialization lines in the existing SQLite owner. Test counts include four
pytest modules, three inert JSON fixtures (910 lines, about 2.92 MB) and three
evaluation-only capture scripts. Three dependency configuration files add nine
lines separately. Source mapping, evaluation instructions and this evidence
document are documentation, not runtime or executable test code. No existing
tutor_demo file is changed or deleted.

After focused gates pass: commit, push, open one PR targeting `dev`, then STOP.
No merge, capability registration, generic dispatch/routing/provider change,
HTTP/WS route, recovery, publication, retrieval or StudentState work is part of
this extraction.
