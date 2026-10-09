# B2: neutral Math MethodConfirmation display labels

Baseline: `wuchqwq/DeepTutor_plus-math-core`,
`dev@f83ea8abe664c2ee0bc30a3087f308834a671ea9` (fetched dev matched).
Related counterexample: [PR #13](https://github.com/wuchqwq/DeepTutor_plus-math-core/pull/13).

## Minimal fix

Previously MathTurnCapability copied arbitrary reviewed `SolutionPath.method`
into ask_user option labels and resolved PROGRESS, before protected final-body
acceptance. UNKNOWN/orientation-only authority did not authorize that text.

The existing capability now checks issued paths against the authored path-ID
set, then assigns `Method 1`, `Method 2`, etc. to the issued opaque tokens in
display order. Both AskUserOption.label and resolved `answers[*].text` use this
same local token-to-display-label map. Raw method text stays private semantic
data; it is not sanitized, classified, filtered or used for presentation.

Display ordinals do not select paths. Existing confirmation IDs, opaque tokens,
token-to-exact-path mapping, membership validation, reply validation and native
ledger commits remain unchanged. No Core, routing, publication authority,
episode ownership, generic ask_user protocol/renderer or schema changes occur.
No new guard, service, store, table or policy framework is introduced.

## Formal regressions

`tests/math_semantic/test_method_confirmation_presentation.py` turns PR #13's
real counterexample into a default pytest safety regression. The source still
contains `Factorization` and `Final answer x = 42` as method fields, while all
artifacts lack independent verification. Existing test-only DI registers an
observer that delegates to production MathTurnCapability, using the actual
application/runtime/SQLite/trusted-routing/Core/reply/protected-publication
chain. Provider IO alone is deterministic; the title owner runs the real B1
implementation.

| Control | Required result |
| --- | --- |
| Pending card / TOOL_RESULT / WAIT_FOR_INPUT | Labels exactly `Method 1`, `Method 2`; neither raw method occurs anywhere in the events; current turn has no accepted output or publication receipt. |
| Choose Method 2 token with contradictory client text Method 1 | Core resolves to original authored path B; original option_paths unchanged; one ledger entry; resolved PROGRESS echoes Method 2. |
| Pause real generation before publication acceptance | UNKNOWN, no verified grounded refs, orientation grants only; safe PROGRESS already emitted; no CONTENT/RESULT or receipt yet. |
| Continue protected publication | Existing acknowledgement body and protected receipt remain unchanged; default title retained, no SESSION_META. |
| Persisted events / fresh replay | No raw method in either turn's events; after closing old runtime/coordinator, fresh store/runtime/coordinator replay the same safe metadata without reviewed-source DI or reexecution. |
| Eight rejected replies | Forged token, actual foreign-episode token, stale confirmation ID, label, ordinal, raw method, path ID and free text cannot resolve; ledger stays pending/unchanged, no accepted output. |
| Ordinary ask_user negative control | Generic builder preserves its authored labels and option IDs, including the same strings; existing ordinary tool/runtime regressions also run. |

The pre-fix baseline run produced **1 failed, 1 passed, 8 deselected**: the real
card leaked both authored methods, while ordinary ask_user remained valid.
The existing six-case token/ledger regression changes only its obsolete raw-label
expectation to a neutral label and explicit authored membership assertion.
Exact resolution, future path constraint, forged/label/path/stale rejection and
head-drift invalidation assertions remain intact, including restart controls.
Recovery coverage is for newly generated safe events; historical event rows are
not rewritten by this presentation fix.

## Local verification

Isolated homes contain shipped agent defaults. PYTHONPATH supplies only this
checkout plus the existing local tiktoken dependency installation, not an
external math runtime. No actual model request is made.

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='F:/demo2/DeepTutor_poc_publication_04/data/test-deps;F:/demo2/DeepTutor_b2_neutral_method_labels'
$env:DEEPTUTOR_HOME='F:/demo2/DeepTutor_b2_neutral_method_labels/data/test-home-math'
# Before the production fix:
python -m pytest tests/math_semantic/test_method_confirmation_presentation.py -q -k 'hostile_method_text_is_private or ordinary_ask_user' --basetemp=data/pytest-b2-red
# Final focused regression:
python -m pytest tests/math_semantic/test_method_confirmation_presentation.py tests/math_semantic/test_publication.py tests/math_semantic/test_routing_isolation.py tests/math_semantic/test_math_turn_capability.py tests/math_semantic/test_recovery.py tests/math_semantic/test_host_boundary.py tests/math_semantic/test_import_boundary.py -q --basetemp=data/pytest-b2-focused
$env:DEEPTUTOR_HOME='F:/demo2/DeepTutor_b2_neutral_method_labels/data/test-home-ordinary'
python -m pytest tests/services/session tests/runtime/test_orchestrator.py tests/tools/test_ask_user.py tests/app/test_turn_parked_on_ask_user_is_reclaimable.py tests/app/test_waiting_turn_recovery.py tests/app/test_turn_application_service.py tests/app/test_multiworker_turn_application.py tests/agents/chat/test_ask_user_drafts.py -q -k 'not test_sqlite_store_migrates_legacy_chat_history_db' --basetemp=data/pytest-b2-ordinary
python -m mypy deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py deeptutor/services/session/turns/title_service.py --follow-imports=silent
python -m ruff check deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/services/session/turns/executor.py deeptutor/services/session/turns/title_service.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python -m ruff format --check deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/services/session/turns/executor.py deeptutor/services/session/turns/title_service.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python scripts/check_repo_hygiene.py
git diff --check
# After commit:
python scripts/check_workspace_hygiene.py
```

Final focused suite: **134 passed in 152.51s**, including ten new controls.
Final ordinary suite: **583 passed, 1 skipped, 1 deselected in 104.26s**
(7 warnings).
Mypy passes **30 source files**; Ruff lint/format passes **43 files**.
This is scoped typecheck, not repository-wide typecheck. The ordinary suite
retains the previously disclosed Windows legacy DB migration deselection
(fixture connection prevents moving the DB); it is not counted as passing.
GitHub Actions are not run due to quota; commit uses `[skip ci]`.

```ini
B2_METHOD_CONFIRMATION_DISCLOSURE = FIXED
HOSTILE_METHOD_TEXT_NOT_STUDENT_VISIBLE = PASS
OPAQUE_TOKEN_PATH_MAPPING = PASS
CONFIRMATION_LEDGER_SEMANTICS = PASS
DURABLE_REPLAY_DISCLOSURE = PASS
MATH_BODY_PUBLICATION_REGRESSION = PASS
ORDINARY_ASK_USER_REGRESSION = PASS
MATH_CORE_CHANGED = NO
ROUTING_SEMANTICS_CHANGED = NO
NEW_GENERIC_POLICY_FRAMEWORK = NO
PHASE_D_STARTED = NO
GITHUB_ACTIONS = NOT_RUN_QUOTA
```

Closeout is commit/push/PR to dev, then STOP. No merge or Phase D work.
Publication safety does not establish high-quality natural tutoring language.
