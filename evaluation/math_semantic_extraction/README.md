# Frozen semantic oracle

The runtime oracle is `tutor_demo@76d5d9697186d086fb967e79a9e08e394b0d5474`.
Planning authority is separately pinned to `a2a1905dc41eed3e5a574304993c2747dcb0838c`.
Every capture checks the runtime worktree HEAD and rejects changes under
`src/`, `tests/` or `evaluation/`; the main capture records SHA-256 for all 83
runtime source files. These tools never import the native implementation.

The committed fixtures are inert evaluation data. Default pytest imports only
`deeptutor.math_semantic`, reads captured outcomes and compares canonical
mathematical content, identities, relations, paths, applicability, scopes,
confirmation state and rejection. Wall-clock `duration_ms` is the only removed
outcome field. Decoder tests restore its neutral `0.0` schema default.

Run each capture against a clean detached checkout of the exact runtime pin,
with the old project's evaluation dependencies installed:

```powershell
python evaluation/math_semantic_extraction/freeze_oracle.py --source F:\demo2\_math_engine_frozen\tutor_demo --output data\oracle-new.json
python evaluation/math_semantic_extraction/capture_negative_trajectory.py --source F:\demo2\_math_engine_frozen\tutor_demo --output data\trajectory-negative-new.json
python evaluation/math_semantic_extraction/capture_confirmation_wrapper.py --source F:\demo2\_math_engine_frozen\tutor_demo --output data\confirmation-wrapper-new.json
```

Existing output paths are rejected. Review each fresh old-source capture before
replacing a fixture. One compact case per line keeps each semantic observation
separate. `--base-capture` can reuse an earlier independent old capture only
after checking its exact runtime SHA and every source hash; it then re-captures
trajectory, state and protected-boundary behavior from the old implementation.
It never reads native outcomes.

The comparator capture explicitly names `ArtifactSummary` content, normalized
form and role fields. A regression control rejects positional-input mistakes
that could otherwise make both implementations agree while comparing a role
label as mathematics.

The suite contains CA02 and independent second-seed single/two/three/opaque path
tasks; grounded comparison and full alignment; unknown, uncertain, unparsed,
contradictory, refuted, conflicting and superseded trajectory observations;
issuing, exact token mapping, resolved cutoff and subsequent-turn semantics;
real old confirmation ledger and reviewed-boundary invalidation; mathematical
validation, exact support binding and region ceiling; domain proposal parsing,
materialization, local dependencies, supersession and consumed-call states;
relative transformations, restart, replay and the eight-attempt limit.

The state tests use explicit fixture submission records, not a product
acceptance lifecycle. Real accepted-row and host commit-authority proof belongs
to `tests/math_semantic/test_host_boundary.py`. The native domain mock mutation
port in wrapper-equivalence tests proves domain commit effects; it makes no
lease/fencing claim.

Validation keeps the original five-second worker budget. A worker timeout is a
closed `not_checkable` result, not truth. Capture and compare materialization
sequentially: CPU contention can legitimately make the old implementation time
out, and its timed result must never be silently normalized to `verified`.
The explicit zero-budget controls compare timeout status/scope separately.

```powershell
$env:DEEPTUTOR_HOME = 'F:\demo2\DeepTutor_math_semantic_extraction_01\data\extraction-validation-home'
python -m pytest tests/math_semantic -q --basetemp=data\semantic-oracle-tests
```
