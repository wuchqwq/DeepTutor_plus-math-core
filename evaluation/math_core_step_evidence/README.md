# MATH-CORE-STEP-EVIDENCE-01

Base: dev `b196b6a5f216cbe2fdc438e5f9076883fc959a79` (remote checked at start).
Independent clean clone: `F:\demo2\DeepTutor_math_core_step_evidence_01`, branch
`math-core-step-evidence-01`. Existing checkouts and S4 evidence are preserved.
PR19 is read-only context. PR20 remains Draft/HOLD; no commits are taken from it.
Phase D stays PAUSED. No real Provider/browser run, roadmap change, new phase,
Clean Break, mastery update, or merge is part of this change.

## Scope and ownership

The live MathTurnCapability opts into the existing alignment/validation/tool
connection for up to four grounded equation/identity claims, independently of
novel paths. The default extraction interpretation remains available for frozen
historical oracles. Providers only propose exact accepted-content spans.

The supported domain is explicitly sourced real scalars: declarations such as
`x,y are real` in ProblemModel.domain. Only single ASCII letter variables (except
reserved E/I), at most four free variables, finite rational-coefficient
polynomials, and finite acyclic explicit definitions are supported. A target
of the exact form `range of Q=...` can name Q's definition; an absent definition
does not silently become an assumption. Matrix, noncommutative, unspecified,
inferred, conflicting, unsupported, or unparseable domains remain UNKNOWN.
SymPy's default commuting symbols supply no domain evidence.

Each polynomial is limited to 256 characters / 64 AST nodes, integer constants
of magnitude at most 10000, constant nonnegative exponents at most eight,
constant integer denominators, and 2048-bit host arithmetic. Explicit products
and adjacent single-letter products are interpreted consistently with the
existing tools. Functions, variable denominators, chained comparisons and
general condition solving are unsupported. At most twelve source premise and
definition records are interpreted; unsupported applicable premises are never
discarded. Given/definition artifacts must be sourced to the reviewed question.

Results distinguish IDENTITY over the explicit real domain; CONDITIONAL after
finite explicit definition replacement; COUNTEREXAMPLE at an exactly verified
point satisfying every interpreted constraint and definition; and UNKNOWN.
Nonzero symbolic residuals and False equivalence results do not refute a claim.
The generic search considers only the Cartesian grid {-1,0,1} for each free
variable (at most 81 points). Host exact arithmetic proposes a point; existing
substitute tools verify definitions, all constraints, and the unequal residual.
This search is incomplete. Failure, no witness, exhausted calls, or uncertainty
remain UNKNOWN with a reason and actual failure receipts. The batch has 32 typed
calls maximum, a ten-second remaining deadline, and two seconds per new worker.

Existing ToolEvidence records carry actual tool inputs/outputs. A scoped summary
binds the accepted response, exact span/claim, episode, input workspace revision,
source model/domain/premises, mathematical basis digest, and tool receipt refs.
Existing evidence-only snapshots advance revisions and retain every referenced
receipt. Immutable replay inputs reuse saved results without executing tools;
foreign, stale, modified, or dangling evidence is rejected when reconstructed.
These are host-protected, content-addressed records, not cryptographic attestation
against wholesale malicious rewriting of the trusted database.

Private teaching context is derived from the host-certified accepted episode
prefix and its existing accepted publication ledger. A prior typed operation is
recognized only by its actual receipt and supported exact content. Correct local
AST subexpressions can contribute locally; exact whole-operation equalities can
correspond to the whole assignment. Merely repeating the unexpanded expression
does not establish completion. Unsupported correspondence is UNKNOWN. Pure
clarification can retain the preceding claim/evidence only across unchanged
mathematical scope and compatible path interpretation. No new pending-work state
machine is persisted. A receipt denotes accepted assignment, not receipt by,
understanding of, or mastery by the student.

The existing selector receives this context and actual receipts through its
existing request. It still selects only supplied grants. Renderer mathematics,
result eligibility, canonical trajectory admission, and publication grant kinds
and support permissions are unchanged. Private local evidence enters neither
matched/contradicted nor validated artifact refs. Evidence-only revision changes
can cause the existing operation support to rebind content/support IDs; they do
not enlarge target/act/support permissions. There is no correctness/justification
feedback offer and no E2E teaching-success claim.

## Verification and evidence

The new regression exercises true/false squares, explicit Q and missing Q,
the conditional `a+b=2, Z=a-b, Z=2a-2` case, other variables, local/whole sum
operations, clarification, unsupported domains/premises, parser/time/resource
failure, exact witness constraints/definitions, revisions, immutable replay,
foreign/altered/missing evidence, changed premises/path, receipt scope, and real
offline host selector/publication/replay. Existing frozen oracles are retained.

Final verification runs the entire `tests/math_semantic` after committing, with
no maxfail, using Python 3.13.2 / pytest 9.1.1 / pytest-asyncio 1.4.0 / SymPy 1.14.0.
The existing integration venv and phase-d-deps are reused without installing
packages. All generation I/O in these tests is replaced at the existing offline
provider seam. Exact commands, environment, before/after SHA and status, exit,
logs, JUnit counts and hashes are captured by the local `run_checks.py` in
`F:\demo2\StepEvidence01_evidence`. Its final manifest is the source of truth for
the completed run; earlier setup/test failures remain there. The full pre-commit
entry point is unavailable in this venv (`No module named pre_commit`); focused
Ruff and repository hygiene checks are reported separately, without calling the
missing full hook suite a pass. CI is queried separately after pushing and is
not inferred from local tests or an absent check list.

Read-only inputs: baseline AGENTS.md / CONTRIBUTING.md; relevant Math Core
responsibility, alignment and migration documents under `F:\demo2\tutor_demo\docs`;
S4_multiturn_20261009 transcripts.md, protocol.json, repetition-attribution.json,
REPORT.md; PR19 metadata; and existing core contracts/state/support/publication.
No .agents/skills tree is present in the clean baseline checkout or workspace
root; none was imported from another checkout as instructions.
