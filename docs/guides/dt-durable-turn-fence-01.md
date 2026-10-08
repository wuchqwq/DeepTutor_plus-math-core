# DT-DURABLE-TURN-FENCE-01

## Baseline and scope

[PR #4](https://github.com/wuchqwq/DeepTutor_plus-math-core/pull/4) was merged at
`2b974512f5b2617780be24f40ead67dd6229f419`, the dev baseline for this stage.
Its 25 unchanged counterexamples now live under `evaluation/commit_fence_probe/`
and remain opt-in evidence, outside default regression discovery. They showed
that stored-token comparisons and coroutine cancellation do not protect a
running SQL worker through commit. Ordinary native writes still have those
semantics; this stage adds an explicitly protected contract.

Supported scope is the default **SQLiteSessionStore + one shared, process-local
MemoryCoordinator** in the application's single-worker deployment. Source and
tests confirm that `ApplicationContainer.build()` defaults to MemoryCoordinator,
`RuntimeRegistry` injects that same instance into the runtime, and the default
store provider chooses SQLite when PocketBase is not enabled. CoordinationSettings
already rejects multi-worker memory configuration. The compatibility helper
that constructs a runtime without a coordinator does not provide this contract.

PocketBase protected commit is **not supported in this stage**. Redis and
multi-process protected commit are **not proven in this stage** and are not
advertised by this seam. Their ordinary APIs are unchanged.

## Public contract and existing owners

`TurnRuntimeContext.run_durable_turn_mutation` is an optional host-bound callable.
The executor supplies it only for the audited SQLite/MemoryCoordinator pairing.
Unsupported pairings expose `None`; consumers must reject protected work when
the callable is absent. The capability receives neither a SessionStore nor a
RuntimeCoordinator nor a SQLite connection/cursor.

```python
run = context.runtime.run_durable_turn_mutation
if run is None:
    raise RuntimeError("Protected durable turn mutation is unsupported")
result = await run(synchronous_body, expected_state_version=observed_turn_version)
```

The synchronous body receives a transaction-local SQL statement runner returning
plain tuples. It can read/write via that runner, but cannot control COMMIT,
ROLLBACK, SAVEPOINT, PRAGMA, schema/attachment operations or the `turns` authority
row. SQLite's authorizer enforces that restriction, and the runner is revoked
on body exit. Async bodies are rejected. This is a trusted plugin execution
contract, not a sandbox for arbitrary Python or model-generated SQL.

Authoritative ownership remains in the existing MemoryCoordinator. The SQLite
owner binds the actual lease, session and store/account scope into the callable;
the capability does not supply or refresh authority fields. Invocation rechecks
scope. Coordinator admission validates the current live owner/token/session/turn
and session-to-turn association. SQLite then validates the durable row's matching
session/owner/token and `running` status inside `BEGIN IMMEDIATE`.

The optional `expected_state_version` is a CAS on the **host turn revision**.
A protected mutation increments it in the same transaction, so a stale revision
rejects before body execution. It is not claimed to be the future mathematical
basis/version. A future ledger must read/check its own basis inside this same
transaction body; no math schema, basis or authority logic is introduced here.

## Ordering through COMMIT

The protected window is:

1. Acquire the existing store lock, then the existing coordinator lock.
2. Validate live coordinator authority while holding its lock.
3. Start the worker, enter SQLite `BEGIN IMMEDIATE`, validate the durable row
   and optional host version, then execute the synchronous body.
4. Advance the host revision; the existing `_connect` context performs the real
   COMMIT (or ROLLBACK on failure) and closes the connection.
5. Observe completion of the executor future, then release coordinator/store
   protection. Only then may an ownership change finish.

Acquisition, renewal, release, lease lookup and expiry acknowledgement already
use that coordinator lock; close now also uses it. An owner released, expired or
replaced **before admission** cannot enter. Once admitted, an ownership change
queues until the transaction has finished. SQLite's write transaction separately
orders a concurrent terminal/version update, including one from another store
instance, after the protected commit or before its validation.

**Expiry ordering is explicit:** admission checks wall-clock expiry. Expiry for
already admitted work becomes observable/authoritative only after the protected
window ends. Crossing the snapshot's `expires_at` during a transaction does not
grant a successor authority; a waiting `get_lease`/acquire observes expiry after
the worker finishes. Thus the permitted order is commit first, invalidation
second. This is not a promise that every in-flight mutation is rolled back when
its original TTL passes.

The shared lock is coordinator-wide, so lease/command/event operations can queue
behind a protected body. Bodies must be bounded synchronous transaction work;
do not put provider calls, retrieval, arbitrary waits or external side effects
inside them. No per-turn lock registry, second lease owner, transaction service
or cross-backend protocol is added.

## Cancellation

Shielding a `to_thread` Task alone would let a cancelled wrapper look finished
while SQL continues. The coordinator instead holds the lock and waits on the
executor future for the synchronous worker itself, with copied contextvars.
It catches cancellation (including repeated cancellation), keeps draining that
future, and re-raises cancellation only after the worker has actually completed
commit/rollback. Cancellation while waiting to enter schedules no protected SQL
work. An admitted operation may commit successfully despite cancellation, but
always before ownership invalidation/replacement is allowed to complete.

The real runtime test cancels the executor while the capability's transaction
is paused immediately before COMMIT. The successor cannot acquire authority,
and the capability cannot observe completed cancellation, until the SQL worker
has finished. A fresh SQLite store reads the final durable state.

## Evidence and limits

[Desired-behavior regressions](../../tests/services/session/test_durable_turn_fence.py)
cover valid/current owner and host CAS; wrong/released/expired/replaced owner;
scope/row identity; ineligible status; async-body rejection; rollback and revoked
runner; forbidden transaction control; and deterministic races after validation,
during the transaction and immediately before COMMIT. They also cover repeated
cancellation, cancellation before admission, concurrent terminal status changes,
real accepted user → runtime context → registered capability → protected commit,
default wiring and ordinary PocketBase/uncoordinated runtime behavior.

The related runtime suites cover normal capabilities, regeneration, context,
ordinary events/messages, application/WS entry points and existing coordination/
recovery behavior. They do not prove recovery of protected mathematical state.

This stage does **not** prove Math Core integration, episode binding, trajectory,
MethodConfirmation, routing isolation, publication, cross-process safety, live
Redis/PocketBase commit support, or writes outside the supplied SQLite transaction.
No new service, store, table, database schema, coordinator or manager is created.

For a future math ledger, this is safe only if its accepted mutation/basis checks
are performed through the supplied runner inside this protected transaction.
The host then orders authoritative invalidation after real durable completion;
the domain adapter never has to simulate host liveness. Merely reading the lease
or writing through an ordinary store method still does not receive this guarantee.

Retrieved analogous examples and prior learner attempts may later be supplied
as bounded teaching/trajectory evidence, but retrieval output is not itself
canonical trajectory authority.

## Reproduction

```bash
python -m pytest tests/services/session/test_durable_turn_fence.py -q
```

Use the current worktree's import path, an isolated `DEEPTUTOR_HOME` and a
worktree-local pytest temporary directory. The tests use existing schema only;
session titles/messages are test witnesses, not mathematical storage design.

Final focused result: **47 passed**. The related runtime run completed with
**255 passed, 6 warnings** (including the then-current 43 desired cases). A
separate SQLite native regression run plus the then-current 46 desired cases
completed with **91 passed, 1 deselected**. The deselection was explicitly
`test_sqlite_store_migrates_legacy_chat_history_db`, the independently reproduced
baseline failure already recorded by PR #4, not an ownership/commit case.
Ruff lint/format and diff whitespace checks pass on all changed source/test files.

Static-check limits were compared with an exact archived baseline: the changed
core/context and MemoryCoordinator pass mypy; wider checking retains eight
unchanged errors in SQLite/executor (four Windows fcntl stubs, three existing
optional-int conversions, one existing reply-queue annotation). Architecture
checking retains the same baseline TYPE_CHECKING TurnLease import/cycle report.
These unrelated diagnostics are not fixed or described as a clean overall gate.
