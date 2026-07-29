# WU4-CP · Constraint Projection + Coarse Plan MVP Review

Review status: `READY_FOR_HUGIN_REVIEW`

Decision: `PARTIAL_CONDITIONAL_PLAN_WITH_BLOCKERS`

## 1. Outcome

WU4-CP now consumes the named WU2R-DOR outputs, named WU3 Evidence Runtime
outputs, and a CLOSED three-artifact planning input bundle.  It produces a
deterministic, non-publishable conditional coarse plan without network, LLM,
route, duration, opening-hours, recommendation, ranking, or identity-selection
behavior.

The current two-day real-anchor replay produces:

```text
Day 1: 江岭
Day 2: 李坑
timing_status: day_assigned_unscheduled
legs: []
plan_status: conditionally_feasible
draft_created: true
publishable: false
generation_allowed_input: false
```

篁岭 remains `BLOCKED_IDENTITY_AMBIGUOUS` with both original alternative
candidate refs.  庆源 remains `BLOCKED_IDENTITY_UNMATCHED` with an empty
candidate-ref list.  Neither becomes an activity or placeholder.

## 2. Baseline and approval identity

Execution started from:

```text
branch: main
HEAD: e3660ee4fb93e27b27e7486b8bc1b1c75a67da21
worktree: only the approved WU4-CP Plan
remotes: 0
stashes: 0
schemas: 11
fixtures/documents/dirty cases: 7/40/7
```

Approved Plan:

```text
path: plans/work-unit-4-coarse-planner.md
version: v0.1
SHA256: 463A57AC09A8C6671CE67C1EB753BAFBD30B454F5D313B2EFC0F8A0DECED5DD0
```

The hash remained unchanged through C5 preparation.

The historical WU4-UC verifier was also invoked at the execution gate.  It
correctly rejected the new, approved WU4-CP Plan as outside the old WU4-UC
whitelist.  That result was not described as a test failure and the historical
verifier was not changed or bypassed.  The same explicit baseline module list
then ran independently:

```text
Ran 198 tests
OK
```

An independent fixture counter returned `7/40/7`.

## 3. Git history

Starting commit:

```text
e3660ee4fb93e27b27e7486b8bc1b1c75a67da21
```

Linear commits before this Review commit:

```text
5ae6ed3f46f2f8d8e355afe85862a3eda81985eb docs: record WU4 coarse planner plan
d2568b853dd9f6b0d4cff4b0aa41f3d6ca339551 chore: add coarse planner interface
6195ab98f4b3caed4ebc32dc4e9645e85f28c7b7 test: add failing coarse planner cases
2ce0782654787590d2b00fe4ebbc04b81bf70b35 feat: implement conditional coarse planner
51a3725c10c4543b818e264fcde8fbffa294df06 chore: add coarse planner verification entry
```

C5 adds only this document with:

```text
docs: prepare WU4 coarse planner review
```

Pre-C5 diff statistics were mechanically reported as:

```text
4 files changed, 3423 insertions(+)
plan: 240 lines
runtime: 1879 lines
tests: 664 lines
verifier: 640 lines
```

The final Git log, final diff/stat, and final HEAD are re-read after C5 rather
than predicted inside the commit being described.

## 4. Scope evidence

The approved whitelist is exactly:

```text
plans/work-unit-4-coarse-planner.md
src/trip_decider/coarse_planner.py
tests/test_wu4_coarse_planner.py
scripts/verify_wu4_coarse_planner.ps1
docs/reviews/work-unit-4-coarse-planner-review.md
```

Before C5, `git diff --name-status` showed only the first four paths, all added.
C5 adds only the fifth.  No Schema, fixture, validator, existing test,
Recovery, Evidence Runtime, Resume/FER, adapter, dependency, `PLAN.md`,
handbook, or historical verifier changed.

Frozen hashes:

```text
PLAN.md
563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456

common.schema.json
A9134A705C67CF955228A28844AA2C5C42812AA2E0167E1256DB72F0ACAC36D7

coarse_planner.py
8098F75190E279419D704E9135B896DE84D88691D4B2A942142671C870E25D8C

test_wu4_coarse_planner.py
1A9A090F32E9C785F36034A23B66D76F0173EDA95069882F514E3AFCE4C289E4

verify_wu4_coarse_planner.ps1
962D01FAB9CDE7712B5A81DCC4B4C344D830A8A873350D37A8FC749C087F48CE
```

The verifier independently checks all 11 Schema hashes plus the approved Plan,
`PLAN.md`, `requirements.lock`, `pyproject.toml`, Recovery, Evidence Runtime,
the Schema validator, runtime, and test hashes.

## 5. Constraint authority and profile

The runtime validates the planning artifacts as a CLOSED bundle rooted at
`constraints.yaml`.  The planning request must exactly match the request ref
already carried by `candidates.json`.

Only enabled hard constraints with these exact profiles are accepted:

```text
time_window / within / request_scope travel_window
must_visit / include / request_scope must_visit
excluded / exclude / request_scope excluded
```

The date value must be an ordered `YYYY-MM-DD/YYYY-MM-DD` closed range.
Must/excluded values must be unique, non-empty string arrays.  Origins must be
`explicit` or `user_edited`.  Any other enabled category, operator, target,
origin, duplicate profile, unresolved reference, or must/excluded overlap
returns a deterministic validation problem.

The runtime does not read `request.payload.natural_language` or request
defaults to derive solver constraints.  It implements no user-locked order.
Ordering is must-visit array order when present, otherwise seed-accounting
order.

## 6. Candidate admission and blocker preservation

An activity candidate must be:

```text
generation_status == ELIGIBLE
one unique and resolvable candidate_ref
evidence_complete == true
hard_conflict == false
not explicitly excluded
```

Candidate, evidence fact, candidate-result, seed-result, Recovery run, and
Evidence run references/counts/hashes are checked before planning.

The hard must-visit test input contains all four seed names:

```text
江岭
李坑
篁岭
庆源
```

The first two resolve to admissible candidates and are allocated.  The last
two are retained in `blocked_seeds` and detailed
`MUST_VISIT_TARGET_NOT_ADMISSIBLE` gate conditions, including their original
input, complete alternative refs, generation status, and block reasons.
The must-visit constraint evaluation is `conditional`, never `satisfied`.

Excluded seeds map to all real candidate refs.  That mapping never selects a
remaining identity from ambiguous alternatives.

## 7. Plan and violations semantics

The conditional branch emits one day object for every explicit date and at
most one activity per day.  Activities contain only stable IDs, candidate and
constraint refs, candidate-local fact refs, and:

```text
timing_status: day_assigned_unscheduled
```

They contain no `start_at` or `end_at`.  Every day has `legs=[]`.
`base_selections=[]` and `objective_breakdown.components=[]`.

Conditions explicitly state that route evidence, opening-hours evidence,
activity duration, and specific times are unavailable.  Missing operational
facts receive no fabricated Evidence fact refs.

When required count is zero or exceeds day capacity:

```text
plan_status: no_plan_found
days: []
proof_refs: []
draft_created: false
scheduled_candidate_refs: []
```

The capacity message states that the one-per-day coarse allocator found no
plan and did not prove infeasibility.  It never emits `proven_infeasible`,
proofs, or a partial allocation.

Both branches emit exactly:

```text
plan.json
violations.json
planning-gate.json
run-summary.json
```

Plan and violations pass CLOSED validation over the caller-provided planning,
Candidate, Evidence, and newly generated artifacts.  No directory discovery
or “latest artifact” selection supplies references.

Identity alternatives exist only in `planning-gate.json`;
`candidate_conflict_sets=[]` and `proofs=[]`.

## 8. C2 Red evidence

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu4_coarse_planner -v
```

Observed:

```text
tests: 6
passed: 0
failures: 0
errors: 6
exit code: 1
```

Error IDs:

```text
CP01
CP02
CP03
CP04
CP05
CP06
```

Every traceback ended at the approved public interface with an explicit
`NotImplementedError`.  Import, path, dependency, syntax, malformed input,
setup, network, and unexpected exceptions were all zero.  The C2 commit
remains in history and was not amended or squashed.

## 9. C3 Green and regression evidence

The exact same command produced:

```text
tests: 6
passed: 6
failures: 0
errors: 0
network attempts: 0
LLM calls: 0
```

The explicit full command over the 12 frozen test modules produced:

```text
Ran 204 tests
OK
```

C3 modified only `src/trip_decider/coarse_planner.py`; the C2 tests did not
change.  `py_compile` passed and no reachable `NotImplementedError` remained.

## 10. C4 verifier execution note

The first complete C4 script run reached:

```text
targeted tests: 6/6
full regression: 204/204
```

It then failed before the independent matrix because the randomly named
system-temporary Python file did not automatically have the repository root
on `sys.path`:

```text
ModuleNotFoundError: No module named 'tests'
```

This was a verifier launch-path defect, not a planner, Schema, fixture,
Candidate, Evidence, or contract failure.  Before the C4 commit, the only
change was to prepend `Path.cwd()` and `Path.cwd() / "src"` to that temporary
checker’s `sys.path`.  No validation assertion, expected output, count, hash,
scope, network, LLM, or residue gate changed.  The failed attempt is retained
here and is not relabeled as a successful first run.

The corrected run and the independent rerun after C4 both returned exit 0:

```text
tests: 204
schemas: 11
fixtures: 7
documents: 40
dirty cases: 7
outputs: 4
network attempts: 0
LLM calls: 0
temporary residue: 0
```

The independent real-anchor matrix also reported:

```text
blocked_seeds: 2
scheduled_candidates: 2
planning_status: conditionally_feasible
draft_created: true
publishable: false
generation_allowed_input: false
```

## 11. Determinism and transaction evidence

CP06 verifies byte-identical output across two clean roots for all four files.
A non-empty output root returns `COARSE_PLANNER_OUTPUT_ROOT_INVALID` and keeps
its marker unchanged.

An injected failure on the second `os.replace` returns the same stable output
root error, removes the first installed file, removes the newly created output
directory, and leaves no partial output.  Installed files are reread and
compared with prepared bytes.

All temporary Python, DOR, Evidence, planning-input, output, and staging
directories are system-temporary and cleaned.  Repository temporary `.py`
files are never created.

## 12. R10 review

- No silent fallback or warning-as-pass path exists.
- No `infer_*`, `guess_*`, `default_when_missing`, or `silent_fallback` logic exists.
- No network transport library or external endpoint exists in the runtime.
- No LLM call or model-derived planning input exists.
- No city or江西-specific branch exists in the runtime.
- No actual input value, secret, absolute path, or third-party exception text is copied into stable problems.
- No Candidate, Evidence, route, time, duration, opening-hours, ranking, or recommendation fact is fabricated.
- `generation_allowed_input=false` is preserved and never promoted.
- `no_plan_found` is never described as infeasible.
- Identity ambiguity is not written as a candidate conflict.
- All four output hashes derive from bytes; run summary omits its own hash.
- Secret scans found no key, token, client-secret, OpenAI-key, or AWS-key pattern.
- Commit messages and per-commit file ownership match C0—C5.

## 13. Completion criteria (18/18)

1. ✓ Baseline and handbook state were recorded and independently checked.
2. ✓ Approved Plan SHA256 remained unchanged.
3. ✓ Three roots consume only their fixed named files.
4. ✓ Planning input passes constraints-root CLOSED validation.
5. ✓ Constraints are the only solver SSOT.
6. ✓ Natural language and defaults are not converted into constraints.
7. ✓ All four candidate-admission conditions are enforced.
8. ✓ Blocked refs, original inputs, statuses, and reasons are retained.
9. ✓ Ordering uses only must-visit or seed-accounting order.
10. ✓ Each day has at most one unscheduled activity and no legs.
11. ✓ Conditional conditions are complete and publishable remains false.
12. ✓ No-plan has a valid plan, zero days/proofs, and no infeasibility claim.
13. ✓ Four outputs and both formal CLOSED bundles validate.
14. ✓ IDs, hashes, parents, input hashes, and summaries are readable.
15. ✓ C2 Red and same-command C3 Green are preserved.
16. ✓ Complete regression is 204/204 and fixtures remain 7/40/7.
17. ✓ Five-path scope, secret/fallback/network/LLM/residue gates pass.
18. ✓ Git, hash, command, output, and limitation evidence is independently reviewable.

## 14. Preserved boundaries

WU4-CP did not modify Schema, fixtures, validators, historical tests,
Recovery, Evidence Runtime, Resume/FER, adapters, dependencies, `PLAN.md`,
handbook, or historical verifiers.  It did not call network or an LLM.

It did not implement route lookup, travel time, distance, opening hours,
activity duration, identity selection, recommendation, ranking, optimization,
UI, WU5, or any later Work Unit.

Final state:

```text
READY_FOR_HUGIN_REVIEW
```
