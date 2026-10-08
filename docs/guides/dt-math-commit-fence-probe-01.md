# DT-MATH-COMMIT-FENCE-PROBE-01

## Decision

**HOST_CONTRACT_GAP — STOP.** At DeepTutor dev
`c6ee78f463cf6c8cc3a959616df292dc9e5ddef5`, neither SQLite nor PocketBase
provides the required public contract for a durable mathematical mutation
whose protection extends through commit. No runtime changes are proposed or
implemented here. Extraction and Capability-02 remain unstarted.

This is the Stage 2 feasibility probe under the accepted
[migration roadmap](https://github.com/wuchqwq/tutor_demo/blob/a2a1905dc41eed3e5a574304993c2747dcb0838c/docs/design/DEEPTUTOR_MATH_MIGRATION_ROADMAP_V2.md).
It uses existing `turns`, `turn_events`, and `messages` as **test-only write
witnesses**. The strings `probe-only: x=2` and `probe-only: y=3` are not Math
Core state or an approved domain storage design. Successful event persistence
does not prove mathematical authority. These counterexamples disqualify the
existing generic fence from being used as that proof.

## Existing contracts examined

- [SessionStoreProtocol](../../deeptutor/services/session/protocol.py):
  `begin_turn` stores owner/token; `transition_turn` optionally compares
  expected status/token; `append_events` optionally compares token.
  There is no expected state-version input or scoped domain mutation/commit port.
  `add_message` has no turn fence input.
- [SQLiteSessionStore](../../deeptutor/services/session/sqlite_store.py):
  `BEGIN IMMEDIATE` serializes the stored-token check and event batch or turn
  transition in one SQLite transaction. It never consults the coordinator's
  current lease, expiry, or replacement owner. Event append does not check turn
  status. `state_version` is incremented on transitions, not compared as a CAS.
- [PocketBaseSessionStore](../../deeptutor/services/session/pocketbase_store.py):
  reads/checks precede separate unconditional collection updates/creates. Turn
  state-version increments are computed from a prior read. No server-side
  conditional update or atomic domain commit contract is invoked by this adapter.
- [RuntimeCoordinator](../../deeptutor/runtime/coordination/protocol.py) and
  [TurnLease](../../deeptutor/runtime/coordination/types.py) expose lease operations
  and snapshots, not a persistence commit scope. The real MemoryCoordinator
  rejects stale renewal/release after expiry/takeover. Redis Lua guards lease
  operations in Redis; it does not encompass a SQLite/PocketBase transaction.
- [TurnLifecycle](../../deeptutor/services/session/turns/lifecycle.py) renews and
  cancels on ownership loss; [TurnExecutor](../../deeptutor/services/session/turns/executor.py)
  avoids subsequent writes after detecting loss. Cancellation does not roll back
  a running `asyncio.to_thread` persistence operation.

## Focused probe results

[Tests](../../tests/services/session/test_commit_fence_probe.py) intentionally
assert observed counterexamples, so a green probe suite means the gap was
reproduced. No ownership validator or guard is replaced with a fake success.
MemoryCoordinator uses a controlled clock and its real lease operations.
Thread events pause actual SQLite SQL execution or PocketBase client calls.

| Case | SQLite, real transaction/reopen | PocketBase, real adapter/existing test client |
| --- | --- | --- |
| Current owner, matching stored token | Event and terminal transition accepted | Same |
| Wrong stored token | Event rejected, transition false, no writes | Same |
| Lease released or expired before mutation | Old snapshot accepted; turn can become completed | Same |
| Same-turn worker replacement before mutation | Renewal/release rejected by coordinator; old store token still accepted | Same |
| Loss after token check, before first mutation | Old event batch commits | Events accepted despite intervening token/status change |
| Loss during batch, after first mutation | Uncommitted batch commits in full after takeover | Second event accepted after takeover; first already exists |
| Loss immediately before commit/write acceptance | Real SQLite COMMIT proceeds; fresh store reads both events | Adapter's next create accepted despite updated token/status |
| Cancellation in all three SQLite transaction windows | Awaiter cancelled; worker still commits | Not used as live PocketBase commit evidence |
| Real runtime ownership-loss cancellation | Renewal loop cancels executor and capability, but worker commits; old turn remains running | Not tested through a live server/runtime |
| Terminal old turn | Completed transition rejected, but fenced append and unfenced message accepted | Same |
| Changed state version, status returns to running | Stale snapshot still accepted; version increments to 4 | Same |
| Token/status/version replaced between transition check and update | Native check and update are in one SQLite transaction | Old writer returns true, overwrites failed with completed and version 20 with 2 |

The real runtime case enters `TurnRuntimeManager`, persists the user row, builds
the context, and invokes a registered test capability. Ownership changes while
the capability's native store operation is paused before SQLite COMMIT. The
real renewal loop discovers loss and cancels execution; only then is the SQL
worker released. The durable write survives. This is an in-flight write
counterexample, not a claim that the runtime deliberately approves a mathematical
result or that recovery/publication has been tested.

## Backend scope and smallest missing contract

| Persistence / coordination | Verdict | Evidence limit |
| --- | --- | --- |
| SQLite / MemoryCoordinator | GAP | Real SQLite commits, independent readback, actual lease expiry/takeover and runtime cancellation |
| PocketBase / MemoryCoordinator | GAP | Deterministic adapter/client interleavings; no live PocketBase server was run |
| SQLite or PocketBase / RedisCoordinator | GAP at public contract | Source inspection only; no live Redis/multi-process claim. Redis lease atomicity does not supply a store commit scope |

The missing contract belongs at the **existing persistence/ownership owner**:
an accepted scoped mutation must be atomically conditional on authoritative
current turn ownership (owner/token, expiry/revocation and allowed status), with
an expected basis/version where the mutation depends on prior state. Ownership
invalidation/replacement must be ordered with that mutation's commit so an
execution that lost authority cannot subsequently produce an accepted commit.
The scope must protect check → mutation → durable commit, not just a preflight
`get_lease`, a stored token snapshot, or the awaiter's lifetime.

SQLite currently protects only its stored row condition and native write in one
transaction, independently of coordinator invalidation. PocketBase additionally
lacks atomic conditional writes in the adapter's existing contract. Incrementing
`state_version`, marking a turn terminal, or cancelling the coroutine supplies
neither missing guarantee. Choosing a single worker/MemoryCoordinator alone
also fails the measured SQLite cancellation window.

Owner authorization is required before strengthening an existing host contract
or accepting a deployment restriction. This probe does not invent an API,
coordinator, lock, service, store, schema, or workaround. Both backends remain
unproven for protected mathematical commits; do not start the next stage on the
basis of this test suite passing.

## Validation and reproduction

On Windows / Python 3.13, the focused probe completed with **25 passed**.
The related regression command below completed with **171 passed, 1 failed,
2 warnings**. Its sole failure, the existing
`test_sqlite_store_migrates_legacy_chat_history_db` assertion that the old file
was removed, also failed alone in a fresh process with an isolated home.
That test and all product sources are unchanged from the pinned baseline;
the new probe module was not collected in the independent failure reproduction.
This PR does not fix that unrelated migration failure or report the regression
suite as fully passing. Ruff lint and format checks pass on the added test file.

```bash
python -m pytest tests/services/session/test_commit_fence_probe.py -q
python -m pytest tests/services/session/test_commit_fence_probe.py tests/services/session/test_sqlite_store.py tests/services/session/test_pocketbase_store_fallbacks.py tests/runtime/coordination/test_memory_coordinator.py tests/services/session/test_trusted_turn_seam.py tests/services/session/test_turn_runtime.py -q
python -m pytest tests/services/session/test_sqlite_store.py::test_sqlite_store_migrates_legacy_chat_history_db -q
```

Use an isolated `DEEPTUTOR_HOME` and pytest temporary directory. No provider,
Math Core, tutor_demo runtime, live Redis, or live PocketBase dependency is needed.
