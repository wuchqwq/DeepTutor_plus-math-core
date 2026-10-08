# POC-PUBLICATION-04

Baseline: `wuchqwq/DeepTutor_plus-math-core`,
`dev@5e17d27bb7ffa15111215b6f1a4512932c62c38c` (merged routing isolation PR #9).
Fetched dev matched this SHA before work. Migration Roadmap V2 section 7.7 and
the accepted capability/recovery/routing evidence remain the authority. This
stage ends with a PR to dev; no merge or next stage.

## Concrete publication gaps and existing owners

The baseline math capability calculates canonical trajectory/authority, then
emits a fixed status and full mathematical diagnostic metadata. It has no
teaching-response generation step. The ordinary response path streams CONTENT
as it is emitted and persists it afterwards; RESULT/completion metadata are also
forwarded without a math content relation check. Appending ordinary free-form
generation there would publish candidate text before any authority acceptance.
A prompt or a classifier cannot certify equivalent arbitrary prose against
Core's exact artifact support relations.

Two additional existing output paths matter: the orchestrator publishes exception
text/error-code metadata, which can contain a provider's unapproved answer, and
the executor repairs CJK Markdown after streaming, which can change accepted
bytes. The real integration controls exercise a hostile provider exception and
a reviewed test-only localized status that the existing formatter changes.

The extension stays with the existing owners:

- MathTurnCapability uses the existing scoped DeepTutor completion factory to
  generate a bounded response proposal, then calls its existing native Core and
  protected SQLite adapter before answer emission.
- CapabilityOutput has an optional frozen AcceptedTurnOutput value containing
  accepted bytes, output identity and serialized trace. The value itself grants
  no authority; production math obtains it only after protected acceptance.
- The executor preserves those bytes and trace in the existing assistant row,
  rejecting a stream/content mismatch. Ordinary capabilities leave the optional
  field unset and retain their existing capture/format/persistence behavior.
- Completion uses the accepted snapshot rather than mutable/legacy result text.
  Math failures clear result fields and emit a fixed operational error, including
  a fixed error code. Detailed exceptions remain in operator logs. Non-math error
  and completion behavior are unchanged.

No new coordinator, service, store, table, provider loop, planner, MathTutor,
PublicationManager, PolicyEngine or second OutputGuard is added. Routing selection,
accepted-row ownership, provider selection and Math Core files are unchanged.

## Generation is a proposal, not mathematical authority

`deeptutor/capabilities/math_turn/output.py` is a bounded expression adapter for
the already accepted grant contract, not a prose evaluator or new teaching policy.
The capability's existing authority calculation is unchanged. Full alignment,
trajectory and calculation detail now stay in private `extension_state.math_turn`
instead of student-facing final metadata, avoiding raw claim/ledger leakage.

The response input pins real session/turn/accepted row identity, episode, math
revision, canonical semantic-state digest, exact accepted-prefix digest, trajectory
projection ref and calculated-authority digest. Host transport metadata is excluded
from the semantic-state digest; the actual accepted prefix is independently bound.
SHA values identify these exact inputs and output bytes; they do not verify truth,
invent accepted submission IDs or replace the host commit fence.

The existing completion factory inherits the executor's scoped model selection.
It buffers its response and supplies no stream callback. Generation may propose
exactly `{authority_basis, grant_ids}` with at most eight unique selections from
the supplied existing grants. Extra fields, arbitrary prose, duplicate JSON fields,
confidence, invented grants, unsupported acts and stale/foreign basis reject.
The prompt describes the format; the executable parser, Core recheck and renderer
enforce it even when the model ignores the prompt.

After generation, the existing protected mutation reloads/validates the host
accepted rows and math aggregate, recalculates the same Core authority and requires
exact equality with the input basis. Selected relations must belong to that current
grant set and pass native `state.authorize` again. Publication supports only the
already calculated orientation/result acts:

- Orientation/no selection supplies the baseline operational sentence
  `Mathematical evidence recorded.` It contains no task mathematics or correctness
  claim. There is no model-authored orientation prose.
- Result supplies only the pinned artifact's exact statement, with the exact
  complete-content digest and existing grant relation. The existing capability's
  independently verified and currently grounded subset remains mandatory.
  Verification alone is insufficient for another artifact/turn/path. No explanatory
  prose, proof, praise, grading, next-step plan or new disclosure act is inferred.

This consumes existing authority meaning; it does not broaden literal result support
into justification or mathematical truth. UNKNOWN/unsupported trajectory evidence
still has no verified/result grant. Trusted reviewed source DI supplies authored
content as in previous stages; generation cannot change its verification status.
Positive tests use independently reviewed authored fixtures, not a provider's
verification assertion or a new verification mechanism.

## Acceptance, publication identity and failure windows

The existing math aggregate's host metadata holds `host_math_publications`, bounded
to the episode's existing 32-turn budget. Each immutable turn entry records the
accepted output's ID, bytes and trace. This is host output acceptance metadata,
not another submission, trajectory or confirmation store. Ordinary Core mutations
preserve it. A conflicting second accepted output for the same turn rejects.

The receipt commits under `run_durable_turn_mutation` before the first answer
CONTENT is sent to the existing StreamBus. CONTENT, RESULT, completion and the
assistant row use the same accepted bytes/trace. Trace binds current accepted row
and turn, episode, revision, exact authority basis, selected relations and SHA-256
of output bytes. Reconnect/replay reads existing durable events with the same
output identity; it neither regenerates nor creates another acceptance entry.

Missing authority, ownership loss, revision drift, invalid proposal or failed
transaction produces no answer event and no output acceptance. SQL-failure control
throws after the receipt write inside the actual protected transaction and proves
rollback. Another control commits valid acceptance, then fails the first StreamBus
CONTENT emission: acceptance remains durable, while delivery/completion stay empty
and no ordinary math fallback runs. Regenerate has no new accepted row and rejects
before generation; a newly accepted retry must use its own freshly calculated basis.

This proves authority before the tested emission and safe receipt/delivery failure
windows. It does not introduce automatic resume of an undelivered output or claim
exactly-once network delivery. Approved historic replay stays bound to its original
turn; an old receipt/proposal cannot authorize a different current turn. Existing
MethodConfirmation dialog/opaque-token semantics remain unchanged.

## Real host integration evidence

`tests/math_semantic/test_publication.py` runs actual TurnApplicationService →
TurnRuntimeManager → persisted SQLite user row → existing trusted routing →
production MathTurnCapability/native Core → real scoped completion factory →
protected acceptance → StreamBus/runtime publication → assistant row/completion.
Only provider I/O below `_complete_with_resolved_config` is replaced by deterministic
responses; generation and publication are production code. Test inspection SQLite
connections are closed. The first live CONTENT hook independently reads the committed
receipt before forwarding the event.

The 26 controls cover:

| Control | Required observed result |
| --- | --- |
| Generation paused after native authority calculation | Accepted row exists; no answer event or receipt yet |
| Real scoped result generation and first live emission | Receipt already committed; CONTENT/RESULT/row/completion bytes and trace agree |
| Orientation-only authority | Only the existing status sentence; no task result |
| Unsupported semantics, with unverified and reviewed verified source fixtures | UNKNOWN; no verified subset or result grant; confident prose/JSON cannot upgrade |
| Free prose, extra text, forged grant, duplicate JSON fields, hostile provider exception/error code | No answer leak through CONTENT/RESULT/ERROR/completion; no ordinary fallback |
| Another genuinely reviewed/verified resolver-supported result outside current grounding | Reject despite its valid content identity/support relation |
| Existing CJK formatter would change reviewed display bytes | Accepted live/persisted bytes and output digest remain exact |
| Same text, different accepted turn; different reviewed episode; revision changes while generating | Old/foreign authority rejects; prior accepted receipt remains immutable |
| Protected port disappears, ownership is released, transaction throws after output write | No durable acceptance/answer fallback |
| Receipt commits, first stream publication fails | Receipt survives; no answer delivery or unconstrained completion; regenerate cannot bypass |
| Regenerate and newly accepted retry with old proposal | Regenerate makes no generation call; new turn rejects old basis |
| Durable event replay twice | Same events/identity; no generation or math mutation |
| Math followed by ordinary chat | Existing ordinary stream/completion; math state/receipt unchanged |

Previous native capability/routing/recovery assertions are preserved. Test helpers
read full calculations from private context instead of the deliberately reduced
public metadata. Offline generation setup replaces only provider I/O, including
independent recovery workers; no production fallback is used.

## Local verification

Ignored isolated homes use shipped agent defaults and the already declared complete
`tiktoken`, `tiktoken_ext` and distribution metadata under `data/test-deps`. Initial
ordinary token-budget controls failed when the encoding plugin was omitted; copying
the complete dependency fixed both original assertions without editing context
builder or tests. Final suites use complete dependencies and independent homes.

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = 'F:/demo2/DeepTutor_poc_publication_04/data/test-deps;F:/demo2/DeepTutor_poc_publication_04'
$env:DEEPTUTOR_HOME = 'F:/demo2/DeepTutor_poc_publication_04/data/test-home-math'
python -m pytest tests/math_semantic/test_publication.py tests/math_semantic/test_routing_isolation.py tests/math_semantic/test_math_turn_capability.py tests/math_semantic/test_recovery.py tests/math_semantic/test_host_boundary.py tests/math_semantic/test_import_boundary.py -q --basetemp=data/pytest-publication-focused-complete-deps
$env:DEEPTUTOR_HOME = 'F:/demo2/DeepTutor_poc_publication_04/data/test-home'
python -m pytest tests/services/session tests/runtime/test_orchestrator.py tests/tools/test_ask_user.py tests/app/test_turn_parked_on_ask_user_is_reclaimable.py tests/app/test_waiting_turn_recovery.py tests/app/test_turn_application_service.py tests/app/test_multiworker_turn_application.py tests/agents/chat/test_ask_user_drafts.py -q -k 'not test_sqlite_store_migrates_legacy_chat_history_db' --basetemp=data/pytest-ordinary-publication-complete-deps
python -m mypy deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py --follow-imports=silent
python -m ruff check deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/services/session/turns/executor.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python -m ruff format --check deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/services/session/turns/executor.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py tests/math_semantic
python scripts/check_repo_hygiene.py
git diff --check
# After commit:
python scripts/check_workspace_hygiene.py
```

Final focused suite: **112 passed in 170.99s**, including **26 publication controls**.
Final ordinary suite: **583 passed, 1 skipped, 1 deselected in 114.10s** (7 warnings).
Mypy: **29 relevant source files pass**. Ruff lint/format: **41 files pass**.
Whole-executor mypy continues to
report the preexisting `Queue.put_nowait(None)` annotation error: baseline line
1443, current line 1455. It is not reported as passing or fixed in this stage.

```powershell
# Broader check: one unchanged executor annotation error (30 source files).
python -m mypy deeptutor/core/context.py deeptutor/runtime/orchestrator.py deeptutor/services/session/turns/executor.py deeptutor/math_semantic deeptutor/capabilities/math_turn deeptutor/services/session/math_semantic_persistence.py --follow-imports=silent
# Reproduce on the clean preceding-stage checkout:
Push-Location F:/demo2/DeepTutor_poc_routing_isolation_03
python -m mypy deeptutor/services/session/turns/executor.py --follow-imports=silent
Pop-Location
git diff 67a6b4cbaa92cbfff33c046e8fb04a5fb779761a 5e17d27bb7ffa15111215b6f1a4512932c62c38c -- deeptutor/services/session/turns/executor.py
```

The ordinary suite explicitly deselects the unchanged Windows legacy DB migration
fixture whose open connection prevents moving the DB, already disclosed in prior
stages. It is not counted as passing. GitHub Actions is **NOT_RUN_QUOTA**; commit
uses `[skip ci]`, with no workflow/config change or manual dispatch.

```ini
STAGE = POC_PUBLICATION_04
BASE = 5e17d27bb7ffa15111215b6f1a4512932c62c38c
MATH_PUBLICATION_AUTHORITY = PASS
ORIENTATION_CANNOT_LEAK_RESULT = PASS
UNKNOWN_CANNOT_UPGRADE = PASS
VERIFIED_SCOPE_ENFORCED = PASS
NON_MATH_PUBLICATION_UNCHANGED = PASS
REGENERATE_CANNOT_BYPASS = PASS
STALE_AUTHORITY_REJECTED = PASS
PUBLICATION_FAIL_CLOSED = PASS
MATH_CORE_CHANGED = NO
ROUTING_SEMANTICS_CHANGED = NO
NEW_GENERIC_POLICY_FRAMEWORK = NO
NEW_SERVICE_STORE_TABLE_MANAGER_COORDINATOR = NO
GITHUB_ACTIONS = NOT_RUN_QUOTA
NEXT_STAGE_STARTED = NO
```

Coverage is the existing opt-in SQLite/MemoryCoordinator application chain. No
default routing/product activation, new teaching strategy, arbitrary natural-language
semantic equivalence proof, distributed backend support or teaching-quality claim
is implied. Source/geometry extensions, Memory/Mastery/RAG and Phase D are outside
this PR.
