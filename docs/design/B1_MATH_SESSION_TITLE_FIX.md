# B1: routed math turns retain their existing session title

Baseline: `wuchqwq/DeepTutor_plus-math-core`,
`dev@b741c3a14fef8f131f9b0defe29c66c32fada561`.
Fetched dev matched this SHA before work. Related audit:
[PR #11](https://github.com/wuchqwq/DeepTutor_plus-math-core/pull/11).

## Problem and minimal fix

A successfully accepted math answer is followed by the existing automatic title
service. Its free-text model and raw-user fallback can publish mathematical
content outside that answer's Core authority, both in the persisted session title
and the student-visible SESSION_META event. The audit reproduced this with
UNKNOWN/orientation-only math and an invented final answer as the title.

`SessionTitleService._maybe_generate_session_title` now returns immediately when
`execution.capability == "math_turn"`. The executor has already updated this
host-owned execution field after trusted routing. The check runs before session
or message reads, title model selection/calls, sanitation, raw-user fallback,
session-title writes and SESSION_META publication. The current neutral/default
title is retained. No new title is synthesized.

The existing ordinary path is unchanged for all other capability values. Neither
request capability, user text, regex, prompt classification nor Core semantics
decides this branch. No title guard, publication manager, policy engine, output
manager, service, store, table or coordinator is added. Production changes are
four added lines in this existing owner; executor/routing/Core are unchanged.

## Real host regression

The 12 new parameterized controls in `tests/math_semantic/test_publication.py`
reuse its existing application/SQLite/MemoryCoordinator/production math setup.
They **delete the fixture's instance-level no-title override**, then assert that
the bound method is exactly `SessionTitleService._maybe_generate_session_title`.
They do not replace that method with another no-op.

The complete chain is TurnApplicationService → TurnRuntimeManager → persisted
accepted user row → trusted routing → production MathTurnCapability/native Core
→ bounded proposal/protected publication → assistant row/DONE → real title owner.
Only provider I/O under the existing completion/stream factories is deterministic.
An AsyncMock wraps the real session-title write for call-count assertions.

| Control | Observed behavior required |
| --- | --- |
| Request `chat`, trusted scope selects `math_turn`; malicious title provider | UNKNOWN, orientation-only; title model calls=0; title writes=0; no title SESSION_META; default title remains |
| Same math turn with empty title output configured | No model call or raw-user fallback; no title write/event |
| Same math turn with provider exception configured | No model call or raw-user fallback; no title write/event |
| Each math control's existing body | Completed real accepted row; exact status body/parent/receipt/authority trace persist; bounded generation/completion still succeed |
| Ordinary chat, immersive reading, deep research, same raw text | Original title model call, persisted title and post-DONE SESSION_META remain |
| Each ordinary capability, empty or failed title provider | Original raw-user title fallback still persists and publishes |

The research request uses its required ordinary config (`mode=notes`,
`depth=quick`). No request validation or ordinary title expectation is weakened.
On the unmodified baseline, these controls produced **3 math failures and 9
ordinary passes**: the malicious answer became the title, and empty/error cases
used raw `s=x+y` as the title. Thus the controls detect the actual blocker rather
than merely inspecting the added branch. Existing publication controls remain
unchanged.

## Local verification

Two isolated test homes contain shipped agent defaults. PYTHONPATH supplies the
previously prepared complete declared `tiktoken` dependency (including
`tiktoken_ext` and distribution metadata), plus this checkout. No external
`tutor_demo` runtime or production imports are used. SQLite temporary-directory
ACL restrictions require the same local execution permission used in preceding
stages. No real provider/network call is made by these controls.

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = 'F:/demo2/DeepTutor_poc_publication_04/data/test-deps;F:/demo2/DeepTutor_b1_math_session_title'
$env:DEEPTUTOR_HOME = 'F:/demo2/DeepTutor_b1_math_session_title/data/test-home-math'
# Before the production fix: 3 failed, 9 passed, 26 deselected (11.60s).
python -m pytest tests/math_semantic/test_publication.py -q -k 'real_title_owner' --basetemp=data/pytest-b1-red-valid-research
# Final focused verification:
python -m pytest tests/math_semantic/test_publication.py tests/math_semantic/test_routing_isolation.py tests/math_semantic/test_math_turn_capability.py tests/math_semantic/test_recovery.py tests/math_semantic/test_host_boundary.py tests/math_semantic/test_import_boundary.py -q --basetemp=data/pytest-b1-focused
$env:DEEPTUTOR_HOME = 'F:/demo2/DeepTutor_b1_math_session_title/data/test-home-ordinary'
python -m pytest tests/services/session tests/runtime/test_orchestrator.py tests/tools/test_ask_user.py tests/app/test_turn_parked_on_ask_user_is_reclaimable.py tests/app/test_waiting_turn_recovery.py tests/app/test_turn_application_service.py tests/app/test_multiworker_turn_application.py tests/agents/chat/test_ask_user_drafts.py -q -k 'not test_sqlite_store_migrates_legacy_chat_history_db' --basetemp=data/pytest-b1-ordinary
python -m mypy deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py deeptutor/services/session/turns/title_service.py --follow-imports=silent
python -m ruff check deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/services/session/turns/executor.py deeptutor/services/session/turns/title_service.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python -m ruff format --check deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/services/session/turns/executor.py deeptutor/services/session/turns/title_service.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python scripts/check_repo_hygiene.py
git diff --check
# After commit:
python scripts/check_workspace_hygiene.py
```

Final focused suite: **124 passed in 185.39s**, including the existing 26 bounded
publication controls and 12 new real-title controls. Final ordinary suite:
**583 passed, 1 skipped, 1 deselected in 119.82s** (7 warnings). Mypy:
**30 source files pass**. Ruff lint/format: **42 files pass**.
The ordinary suite's one deselection is the previously disclosed
unchanged Windows legacy DB migration fixture whose open connection prevents
moving the DB; it is not counted as passing. Mypy covers the changed title owner
and the native publication chain; this does not claim repository-wide typecheck
or resolution of the preexisting, unchanged executor queue annotation error.

```ini
B1_UNBOUNDED_POST_TURN_SESSION_TITLE = FIXED
MATH_BODY_PUBLICATION_REGRESSION = PASS
ORDINARY_TITLE_REGRESSION = PASS
MATH_CORE_CHANGED = NO
ROUTING_SEMANTICS_CHANGED = NO
NEW_STORE_TABLE_SERVICE_MANAGER_POLICY = NO
GITHUB_ACTIONS = NOT_RUN_QUOTA
PHASE_D_STARTED = NO
```

CI uses `[skip ci]` in the commit; no workflow changes or manual dispatch. This
PR repairs B1 only. Publication containment does not prove high-quality natural
tutoring language. No Phase D, broader policy, recovery framework or product
activation is implemented; closeout is commit/push/PR to dev, then STOP.
