# Bounded Math Teaching Support Slice — Draft review, not Phase D PASS

## Root cause and base

PR18's real evidence showed only orientation offers, legal empty selector choices,
and acknowledgement-only publication. This was a missing support/publication path,
not a prompt-choice diagnosis. Its failures and raw evidence remain unchanged:
[PR18 root cause](https://github.com/wuchqwq/DeepTutor_plus-math-core/blob/b8d2ac2aad38c587859b9bbedabe3fb72c66f4da/evaluation/phase_d_minimal/results/root_cause.md).

Product base: `dev`, `143e41784bdd2c34d765a50c754869ef3a2d9830`.
New branch: `feat/bounded-math-teaching-support`, independent worktree
`F:\demo2\DeepTutor_bounded_math_teaching`. Original checkout work was preserved,
including PR18 checkout's uncommitted `web/next-env.d.ts`. No CleanBreak was started.
PR18 is a read-only evaluation dependency at
`b8d2ac2aad38c587859b9bbedabe3fb72c66f4da`; none of its old experiment artifacts or
commits are copied into this branch. `rerun.py` reuses its retained protocol and
instrumentation in ignored local directories.

## Small implementation in existing owners

* Math Core `support.py` enumerates finite expand/substitute requests from named
  applicable equations and explicit symbol definitions. It executes the existing
  `MathToolRegistry` and retains its actual, unchanged ToolEvidence. Operation
  artifacts bind exact parameters, premise refs, workspace identity and revision.
  The resolver checks the whole relation and refuses stale or foreign support.
* `MathTurnCapability` executes tools outside the existing protected transaction,
  rechecks the exact input snapshot at commit, and adopts only native supported
  chosen_operation/operation_options. Each turn has at most four tool calls.
  Identical supported batches on the same current snapshot reuse evidence without
  calls or revision changes. Changed batches are rebound completely.
* Existing host `output.py` chooses a useful authorized operation and renders a
  next-step instruction. Core owns mathematics; host owns wording and selection.
  Existing authority/basis checks and durable publication precede response bytes.

No question identity, CA02 name, specific polynomial, Guard, Manager or new runtime
layer was added. No verified status is handwritten. Tool execution checks algebra
relative to premises; it does not establish premise truth, a student's correctness,
attainability, a proof, or permission to disclose the complete answer. The existing
matched + applicable + verified result restriction remains. Arbitrary model prose
cannot enter the accepted response.

## Actual teaching smoke test

Before the full rerun, a fresh S4 browser submission produced an actual operation
grant and this canonical host response:

> Mathematical evidence recorded.
>
> Try this next step: Expand (3*(x^2-x*y+y^2)-(x^2+x*y+y^2))-(2*(x-y)^2). Then compare the coefficients. This checks the algebra relative to the named premises; their truth and the complete answer are not yet confirmed.

This is non-acknowledgement, executable, retains the square method, and supplies no
final range. Native receipts, live events, assistant rows and their content digests
agree. Refresh was actually performed. Raw evidence is local under
`data/support-evidence/smoke-v2-S4`, with browser retry evidence in `browser-v3`;
the earlier frontend failure remains.

Actual HTTP verified `deepseek-flash`, `thinking.type=disabled`,
`reasoning_effort=none`, `temperature=0`, `top_p=1`. Three requests, including the
existing follow-up suggestion owner, reported 8,105 usage tokens. Standard Catalog
authentication was reused through its existing service; no key/header was inspected,
copied or printed. The source remained AI-reviewed, with `Q=9-2*s^2` and no source
truth upgrade.

## Original eight scenarios

The frozen original inputs, background, followups, real method button and independent
session/home/SQLite/episode rules were reused. Only the integrated arm was rerun;
PR18's ordinary-arm comparison remains historical evidence, not a newly executed
control or proof of learning improvement.

| Scenario | Actual teaching result and remaining limit |
|---|---|
| S1 correct intermediate step | Executable expansion prompt; no visible correctness confirmation or useful product-bound derivation. |
| S2 sign error | Executable prompt; does not explicitly locate and correct the sign error. |
| S3 conceptual error | Executable prompt; does not explicitly refute the assumption that real products are nonnegative. |
| S4 alternate square method | Non-ack expansion of the square relation; no forced method switch or final range. |
| S5 small hint | One operation prompt, but still too generic to meet the requested product-bound hint. |
| S6 full answer request | Does not widen mathematical permissions or disclose an unverified final answer; complete range/attainability remain unanswered. |
| S7 ambiguity | First turn fails before support: provider returns interaction_type question together with asserted claims. Native schema refuses it. No followup submission or retry after failure. |
| S8 five turns | Real Method 2 opaque-token confirmation, all five completed replies and refresh; coefficient errors remain insufficiently explained, final matching is not treated as proof or answer authority. |

The first bounded implementation rerun (`teaching-v1`) completed 11 non-ack replies,
one failed S7 turn, and 35 actual HTTP requests with 93,679 observed usage tokens.
Its failures and evidence remain. Recovery regression then exposed repeated
operation execution/revision advancement and worker-timeout pressure; the final
same-snapshot reuse and four-call bound address that local issue. The second rerun
(`teaching-v2`) is retained separately. Exact execution diff hashes distinguish
configuration/code revisions; neither run overwrites the other.

Structured per-case counts, receipt digests, actual wire checks, usage and method
confirmation observations are in `results.json`. Raw logs/screenshots remain local;
their aggregate and archive hashes are in `evidence_manifest.json`.

The UI renders Markdown, so a raw response literal may differ from visible DOM text
(for example multiplication asterisks). Replay verification compares live/durable
canonical bytes and digests, and separately compares the rendered response segments
before/after actual refresh. This is not a claim that every DOM character equals the
raw literal.

## Commands, regressions and limits

Interpreter reused from the successful prior experiment:
`F:\demo2\DeepTutor_upstream_v1_6_14\data\integration-venv\Scripts\python.exe`,
Python 3.13.2. Existing additional dependencies were reused. Browser combination:
Playwright 1.57.0, Chromium 153.0.8010.12, headless cache 1243. Next 16.2.3 webpack
uses an ignored same-drive copy of the installed Next package plus dependency links.
No browser/version reinstall was performed. Only this task's localhost API/frontend
and independent headless contexts were controlled.

```powershell
# Set PYTHONPATH to PR18 checkout's data/phase-d-deps; use the interpreter above.
python -m pytest tests/math_semantic -q --disable-warnings --maxfail=2 --basetemp=data/test-tmp-math-final -o cache_dir=data/pytest-cache
python evaluation/bounded_math_teaching/rerun.py --original-checkout <retained-PR18-checkout> --run teaching-v2 --chromium <headless-cache-1243-executable>
python -m ruff check <changed Python files>
git diff --check
```

Meaningful controls cover real valid expand/substitute evidence; wrong support
relationships, absent definitions, failed tools, foreign workspaces and stale
revisions; read-only evidence reuse; operation publication/replay; existing stale
publication, commit failure, ownership loss, routing and recovery checks. Existing
method-card/recovery test scaffolds were updated to admit actual supported operation
relations while continuing to forbid unverified results and private method prose.
Frozen math oracle and source fixtures were not changed.

Preserved unsuccessful checks: global-interpreter pytest temporary-directory access
failure; global-interpreter missing `jose` before API startup; Next cross-drive module
resolution failure before student submission; initial suite 765 passed/2 obsolete
orientation-only assertion failures; recovery runs exposing repeated revision
advancement and subprocess timeout. These are not provider or teaching successes.

Final product-code suite execution: **901 passed, 2 failed** (455.76 s). Both
failures were remaining old orientation-only assertions in cross-process recovery
and journal isolation; their UNKNOWN/empty verified-ref conditions had passed. After
updating those test assertions, the selected recovery scenarios, journal integration
and the suite's remaining submission integration tests were **15 passed** (96.86 s).
Independent real-tool wall-clock durations are omitted only when comparing two
hosts' journal-independent semantic records; all mathematical/support fields remain
compared. The entire suite was not repeated after these test-only edits. Ruff and
`git diff --check` passed. The initial real operation controls were 7 passed; the
cache control also ran in the final product-code suite. The dedicated operation
publication/replay positive was separately 1 passed.

Second real rerun: 11 non-ack replies, 35 HTTP requests, **82,400 observed tokens**.
S8's receipt revisions were `2,3,4,4,4`, demonstrating same-head evidence reuse in
actual turns. All 11 accepted canonical contents match live events/durable assistant
rows/receipts and content digests; rendered response segments survive refresh in all
seven completed cases. S7 has no accepted publication or refresh-success claim.
Total new paid experiment activity including the smoke test and both retained rounds:
**73 actual HTTP requests, 184,184 observed usage tokens**. No unobserved usage is
silently counted as zero.

Intermediate execution used uncommitted changes, captured by per-case exact diff
hashes. The final batch-reuse refinement was in place before second-round S8; earlier
single-turn cases do not exercise reuse. Final owner source files are saved and
hashed locally. These facts are recorded rather than claiming every historical run
executed the subsequently committed SHA.

914 mathematical tests were collected. The 15-case final selection covers the
two corrected failures, the eleven cases after the full-run stop, and two already
passing recovery controls. This is coverage across actual commands, not a claim
that a single final full-suite invocation exited zero.

CI outcome for the created Draft PR head is recorded in its description and final
response; no successful CI run is implied by local verification. CI was not dispatched
manually; a lack of observed runs is not quota evidence. No Phase D PASS, overall
teaching success or learning improvement is claimed. Final action is a new Draft PR,
then STOP for owner review; neither PR is merged.
