# PRE-PHASE-D-METHOD-CONFIRMATION-PROBE

```ini
REPO = wuchqwq/DeepTutor_plus-math-core
BASE_BRANCH = dev
BASE_SHA = f83ea8abe664c2ee0bc30a3087f308834a671ea9
B2_METHOD_CONFIRMATION_DISCLOSURE = BLOCKER
STUDENT_VISIBLE_OUTPUT_REAUDIT = FAIL
DT_POC_PASS = NO
PHASE_D_READY = NO
PRODUCT_CODE_CHANGED = NO
MATH_CORE_CHANGED = NO
GITHUB_ACTIONS = NOT_RUN_QUOTA
PHASE_D_STARTED = NO
```

## Reproduced disclosure

A trusted reviewed source has two authored paths. Only their `method` fields
are changed: A = `Factorization`, B = `Final answer x = 42`. Path identity,
artifact membership and mathematical statements remain unchanged; no artifact
is independently verified. Neither accepted student submission contains the
disclosure. The resulting current-turn authority is UNKNOWN, with orientation
grants only and no verified grounded references.

The [opt-in probe](../../evaluation/method_confirmation_disclosure/probe.py)
uses existing test-only `RoutingHost` DI to execute real
`TurnApplicationService → TurnRuntimeManager → accepted SQLite row → trusted
routing → MathTurnCapability → native Core → ask_user/reply → generation →
protected publication`. The registered observer delegates to the production
capability. Provider IO is deterministic and local; the generation factory,
title owner, event persistence and publication acceptance remain real.

While the second accepted turn is pending, its card already contains the
disclosure. After the exact Core-issued opaque option token is submitted,
generation is paused before publication acceptance. At that point the ledger
is resolved, current authority remains UNKNOWN/orientation-only, and resolved
PROGRESS repeats the disclosure. The current turn has neither a publication
receipt nor accepted output nor CONTENT/RESULT events in either window.

| Surface | Observed result |
| --- | --- |
| TOOL_RESULT, sequence 2 | `tool_metadata.ask_user.questions[0].options[*].label` contains `Final answer x = 42` before final publication acceptance. |
| ask_user option label | Source method is copied into the real card; the Web renderer displays `option.label` as Markdown. |
| WAIT_FOR_INPUT, sequence 3 | No disclosure in this frame itself; the preceding card is already available while waiting. |
| Resolved PROGRESS, sequence 4 | `answers[0].text` is `Final answer x = 42`, before final publication acceptance. |
| Persisted events / replay | SQLite retains both leaking metadata payloads. After closing the old runtime/coordinator, fresh store/runtime/coordinator objects replay the same payloads without reviewed-source DI or capability reexecution. |
| Final accepted body | Only `Mathematical evidence recorded.`; no disclosure. The protected receipt remains bounded. B1 also preserves the default title and emits no SESSION_META. |

This is an event-metadata publication bypass, independent of the final body.
Reviewed path identity does not grant mathematical disclosure authority.
The exact token still selects the exact authored path; selection integrity
does not prevent disclosure through its display label.

## Source evidence on the pinned baseline

- `deeptutor/capabilities/math_turn/capability.py:104`: labels derive directly
  from `path.method.replace("_", " ").capitalize()`; line 116 uses them in
  AskUserOption, line 125 emits TOOL_RESULT, line 134 emits WAIT_FOR_INPUT,
  and lines 153–159 echo the label in resolved PROGRESS. Final generation and
  protected publication acceptance occur later, at lines 205 and 212.
- `web/components/chat/home/AskUserOptions.tsx:839` normalizes the label for
  display; line 1489 renders `<InlineMarkdown content={option.label} />`.
  Resolved-event parsing at lines 192 and 606 consumes `answers` metadata.
  No browser end-to-end run is claimed; the real host event/replay probe and
  the existing rendering code establish this student-visible surface.

## Local execution and limits

Two independent executions against fresh databases reproduced the blocker
(exit 0). Exit 0 means **counterexample reproduced**, not safety PASS. This
script lives outside default pytest `testpaths` and is explicitly invoked:

```powershell
# From F:\demo2\DeepTutor_method_confirmation_probe, using available local dependencies:
$env:PYTHONUTF8='1'
$env:PYTHONPATH='F:/demo2/DeepTutor_poc_publication_04/data/test-deps;F:/demo2/DeepTutor_method_confirmation_probe'
$env:DEEPTUTOR_HOME='F:/demo2/DeepTutor_method_confirmation_probe/data/probe-home'
python evaluation/method_confirmation_disclosure/probe.py --db data/b2-counterexample-01.db
python evaluation/method_confirmation_disclosure/probe.py --db data/b2-counterexample-02.db
python -m ruff check evaluation/method_confirmation_disclosure/probe.py
python -m ruff format --check evaluation/method_confirmation_disclosure/probe.py
python scripts/check_repo_hygiene.py
git diff --check
```

The ignored probe home contains shipped default `agents.yaml`; the dependency
directory supplies installed tiktoken packages only. No external math runtime
or tutor_demo checkout is loaded. Choose a new DB filename for a repeat run;
the script rejects existing files. Ruff and repository hygiene/diff checks
PASS. Full regression and mypy were not run for this evidence-only change.
GitHub Actions were not run due to quota.

## Minimal repair proposal — not implemented

In the existing MathTurnCapability confirmation presentation, replace raw
`SolutionPath.method` labels with fixed neutral host-authored display labels
(for example `Method 1`, `Method 2`), and echo the same safe label in resolved
PROGRESS. Ordinals remain display-only: preserve exact confirmation ID,
opaque token → authored path mapping, membership validation and Core ledger
semantics. A subsequent authorized fix should verify hostile method text
cannot enter cards, progress or durable replay, while exact-token resolution
and ordinary ask_user behavior remain intact. No new Guard, PolicyManager,
service or table is proposed.

STOP for Owner authorization; no repair or Phase D work is included.

`publication safety proven != high-quality natural tutoring language proven`.
The bounded final-body checks do not establish complete student-visible
publication safety (B2 blocks it), and teaching-language quality is unproven.
