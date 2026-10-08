# POC-ROUTING-ISOLATION-03

Baseline: `wuchqwq/DeepTutor_plus-math-core`,
`dev@b3d908d2622d9513178b4c2aa461955218c9e565` (merged POC-RECOVERY-02).
Remote dev was fetched and matched this SHA before work. Migration Roadmap V2
section 7.6, MATH-TURN-CAPABILITY-02 and POC-RECOVERY-02 were independently read.
This is the Owner's narrow routing seam stage; it ends with a PR to dev.

## Existing seam and minimal extension

The existing request preparer validates client capability/config and builds an
admission turn. The orchestrator dispatches `context.active_capability`; neither
the client capability nor the existing text-based quiz proposal certifies a math
episode. The executor already owns persistence of exact accepted user content and
construction of the protected mutation port.

`TurnEngine` now accepts optional host DI, `resolve_accepted_capability`. The
executor invokes its selection method after actual acceptance/context assembly
and before the existing dispatcher. The callback receives only a frozen
`TurnRoutingReference(session_id, turn_id, accepted_user_message_id)`; it receives
no raw text, prompt, model output, request config or client metadata. Trusted
application composition resolves its active reviewed scope and returns one
`CapabilityBinding(capability, scope_id)`, or `None` to retain the existing route.
An ambiguous/invalid result fails closed. This decision is neither a Core
verification result nor an authority grant.

For an accepted row with a protected port, the existing engine writes its exact
decision to that row's existing `metadata_json.host_capability_binding` using
`run_durable_turn_mutation`. It checks session, role, exact raw content and turn
identity before writing, and rejects a changed existing decision. The record is
`{turn_id, binding: {capability, scope_id}}`, or `{turn_id, binding: null}` for an
ordinary turn. `messages.capability`, execution capability and completion route
metadata reflect the selected dispatcher. `turns.capability` remains the requested
admission value: the protected SQL authorizer deliberately forbids changing host
lifecycle rows. No SQL authorizer restriction is relaxed.

The default engine has no resolver; builtin registration/default product routing
remain unchanged. This is an opt-in production seam in the existing application
boundary, not a new public scope-selection API or a reviewed-content authoring
workflow. Existing source/context preparation still occurs before selection;
provider selection and RAG preparation are not redesigned here.

Production `MathTurnCapability` requires the exact host binding and matches its
scope to the reviewed source episode before provider/Core work. Its certified
SQLite adapter rechecks the durable row attribution on every protected math
mutation. Client selection of `math_turn` alone cannot satisfy these checks.
Regenerate/non-persisted execution supplies no newly accepted identity and cannot
mint evidence. Missing protected ports remain fail closed, without an ordinary
write fallback. The explicit-prefix adapter API remains an extraction test seam;
the production capability always uses the certified episode path.

## Mathematical evidence ownership rule

For new routing-attributed history, an accepted row belongs to episode E only
when its exact immutable host decision says `math_turn / E`, matches its actual
host turn, and is on the current accepted message ancestry. Text, request
capability columns and message proximity do not determine membership.

The certified prefix is the ordered bounded sequence of E-owned accepted IDs,
not every user row between start and current. Its start is recovered from the
aggregate, or, before the first aggregate exists, the earliest durable E-owned
row. Ordinary gaps are excluded from IDs, alignment, trajectory ordinals and
confirmation cutoffs. An attributed math submission whose proposal/worker fails
remains in the prefix as missing evidence; dropping it would hide uncertainty.
All previously certified IDs remain pinned, so deleting/changing their markers
cannot silently remove them from the basis. Current ID/content/client ID must
still equal the runtime accepted submission.

The existing aggregate holds two additional host reference fields, not a second
trajectory/confirmation state: `host_math_ownership_version = 1` and
`host_legacy_accepted_message_ids`. At cutover, already-certified old IDs without
route markers are frozen as legacy evidence. Unseen unmarked rows are never
adopted, and this legacy set cannot grow on later turns. Missing/boolean/unknown
ownership versions with the new envelope fail closed. An already marked row
cannot become legacy evidence by erasing its marker.

This compatibility rule preserves the baseline's already-certified historical
IDs; it cannot retroactively decide whether an old interval contained ordinary
conversation. New turns use explicit ownership. The tests demonstrate an old
certified prefix followed by an unmarked ordinary gap is resumed without adopting
the gap. The test-only native producer writes the frozen baseline durable shape
through the real port; it does not dynamically load/execute the baseline adapter.

An accepted branch cannot borrow sibling math evidence. The ancestry check is
bounded at 1024 parent hops and fails closed beyond that bound. A fork that skips
E-owned history needs a new explicitly reviewed episode; rejected E-attributed
siblings also prevent silently treating the old E chronology as resumable.
The existing overlapping/superseded episode guard remains. This stage proves
return after ordinary turns, not arbitrary interleaved resumption of superseded
math episodes.

## Real host evidence

`tests/math_semantic/test_routing_isolation.py` composes the existing
`TurnApplicationService`, `TurnRuntimeManager`, `SQLiteSessionStore`,
`MemoryCoordinator`, `TurnEngine` and canonical capability catalog. Registered
math observers invoke the production capability/native Core; deterministic
proposal DI removes external provider calls. Ordinary chat/reading/research
probes exercise the same real host dispatcher, with ordinary behavior also
covered by the existing regression suite. No hand-built context substitutes for
acceptance. SQL test inspection connections are explicitly closed.

| Control | Observed contract |
| --- | --- |
| Explicit reviewed scope on an accepted chat request | Routes to math; exact durable ID/raw/client ID reach Core |
| Chat, immersive reading, RAG-style chat, research without math scope | Existing capability; zero Math Core proposal/mutation |
| Identical text under ordinary vs reviewed math scope | Different route/accepted IDs; ordinary row is excluded |
| Math → ordinary → same episode math | Aggregate unchanged during gap; one new alignment; cutoff counts math rows |
| Missing/ambiguous binding or forged request/config field | Preserve ordinary route or reject; no mathematical authority |
| Reviewed source disagrees with selected episode | Reject before proposal/Core |
| First attributed failure before aggregate creation | Next turn retains earliest row as missing evidence/UNKNOWN |
| Later failed math observation plus ordinary gap | Failed math row remains; ordinary row omitted; no verification upgrade |
| Regenerate/non-persisted math execution | No new acceptance, no math mutation |
| Ordinary regenerate | Existing ordinary route, no new math evidence |
| Removed/foreign route marker; downgraded ownership version | Reject; canonical math state unchanged |
| Frozen legacy prefix, unmarked gap, fresh host cutover | Exact frozen old IDs; gap excluded; no retroactive marker erasure exemption |
| Pending and resolved confirmation followed by ordinary turns | Ledger unchanged; opaque tokens/native basis absent from ordinary private context |
| Return after pending gap | Same pending confirmation/card/token/path mapping; exact explicit resolution |
| Closed runtime/coordinator/store replaced over same DB | Fresh scope reconnects same durable episode; old alignment/snapshot/ledger preserved |
| Branch skips sibling history | Reject; separately reviewed new episode can start independently |
| Successful trajectory on uncheckable authored relations | UNKNOWN, no verified subset, orientation-only ceiling |

Ordinary transcript text and displayed clarification text remain normal host
conversation history. They are not authoritative math state. Native projection,
reviewed source, accepted-ID basis, ledger/token and authority are not injected
into ordinary capability context. Ordinary rows never enter the production math
prefix merely because that display history exists. Native Core semantics and
authority calculation are unchanged: reconstruction success is not verification.

## Local verification

Windows uses an ignored isolated home, shipped agent defaults and the declared
`tiktoken` dependency in ignored `data/test-deps`. No personal settings or network
model calls are needed.

```powershell
$env:PYTHONUTF8 = '1'
$env:DEEPTUTOR_HOME = 'F:/demo2/DeepTutor_poc_routing_isolation_03/data/test-home'
$env:PYTHONPATH = 'F:/demo2/DeepTutor_poc_routing_isolation_03/data/test-deps;F:/demo2/DeepTutor_poc_routing_isolation_03'
python -m pytest tests/math_semantic/test_routing_isolation.py tests/math_semantic/test_math_turn_capability.py tests/math_semantic/test_recovery.py tests/math_semantic/test_host_boundary.py tests/math_semantic/test_import_boundary.py -q --basetemp=data/pytest-routing-final
python -m pytest tests/services/session tests/runtime/test_orchestrator.py tests/tools/test_ask_user.py tests/app/test_turn_parked_on_ask_user_is_reclaimable.py tests/app/test_waiting_turn_recovery.py tests/app/test_turn_application_service.py tests/app/test_multiworker_turn_application.py tests/agents/chat/test_ask_user_drafts.py -q -k 'not test_sqlite_store_migrates_legacy_chat_history_db' --basetemp=data/pytest-ordinary-routing-final
python -m mypy deeptutor/core/context.py deeptutor/runtime/turn_engine.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py --follow-imports=silent
python -m ruff check deeptutor/core/context.py deeptutor/runtime/turn_engine.py deeptutor/services/session/turns/executor.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python -m ruff format --check deeptutor/core/context.py deeptutor/runtime/turn_engine.py deeptutor/services/session/turns/executor.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python scripts/check_repo_hygiene.py
git diff --check
# After commit:
python scripts/check_workspace_hygiene.py
```

Final focused integration/native/recovery regression: **86 passed in 160.16s**.
Ordinary regression:
**583 passed, 1 skipped, 1 deselected, 7 warnings in 114.65s**. The explicit Windows
deselection is the unchanged legacy SQLite migration test whose open test
connection prevents moving the DB, documented in Capability-02/Recovery-02. It
is not reported as passing. Mypy: **28 relevant source files pass**. Ruff lint and
format: **38 files pass**. Repository hygiene and diff checks pass.

A broader mypy command adding `deeptutor/services/session/turns/executor.py`
reports its preexisting `Queue.put_nowait(None)` annotation error (current line
1443, baseline line 1434). Running mypy on that byte-identical baseline executor
in the clean Recovery-02 checkout reproduces the same error. This stage does not
claim a clean whole-executor typecheck or change the unrelated subscriber queue.

```powershell
# Broader check: one preexisting executor annotation error, not a clean pass.
python -m mypy deeptutor/core/context.py deeptutor/runtime/turn_engine.py deeptutor/services/session/turns/executor.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py --follow-imports=silent
# Baseline reproduction, from the clean preceding-stage checkout:
Push-Location F:/demo2/DeepTutor_poc_recovery_02
git rev-parse HEAD
python -m mypy deeptutor/services/session/turns/executor.py --follow-imports=silent
Pop-Location
# Its executor is byte-identical to this stage's baseline:
git diff db040f45f675b4e7a2db347017e7e2c164b3508e b3d908d2622d9513178b4c2aa461955218c9e565 -- deeptutor/services/session/turns/executor.py
```

GitHub Actions is **NOT_RUN_QUOTA**. Commit uses `[skip ci]`; no workflow/config
change or manual workflow dispatch is made. Local verification is the evidence.

```ini
STAGE = POC_ROUTING_ISOLATION_03
BASE = b3d908d2622d9513178b4c2aa461955218c9e565
MATH_ROUTE = PASS
NON_MATH_ISOLATION = PASS
MATH_EVIDENCE_ISOLATION = PASS
RETURN_TO_MATH_EPISODE = PASS
RECOVERED_EPISODE_ROUTING = PASS
AMBIGUOUS_SCOPE_FAIL_CLOSED = PASS
TEXT_HEURISTIC_AUTHORITY = NO
MATH_CORE_CHANGED = NO
PUBLICATION_STARTED = NO
NEW_GENERIC_ROUTING_FRAMEWORK = NO
NEW_SERVICE = NO
NEW_STORE = NO
NEW_TABLE = NO
NEW_MANAGER_COORDINATOR = NO
DEFAULT_PRODUCT_ROUTING_CHANGED = NO
GITHUB_ACTIONS = NOT_RUN_QUOTA
NEXT_STAGE_STARTED = NO
```

This proof covers the opt-in SQLite/MemoryCoordinator host application chain.
It does not claim HTTP/WS/CLI product activation, distributed routing, PocketBase/
Redis protected mutation, publication containment/idempotency or real-provider
teaching quality. Those owners and entrypoints are unchanged.
