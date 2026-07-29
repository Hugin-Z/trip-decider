# WU5-E2E · End-to-End Orchestration + HTML Result MVP Review

Review status: `READY_FOR_HUGIN_REVIEW`

Decision: `ORCHESTRATE_EXISTING_STAGES_AND_RENDER`

## 1. Outcome

WU5-E2E now exposes one library entry and one standard-library CLI that invoke
the approved Recovery, Evidence Runtime, and Coarse Planner exactly once per
E2E invocation.  It then renders only the facts and planning state already
present in those stage outputs.

The current committed real-anchor run produces:

```text
Day 1: 江岭
Day 2: 李坑
timing_status: day_assigned_unscheduled
plan_status: conditionally_feasible
draft_created: true
publishable: false
generation_allowed_input: false
```

篁岭 remains `BLOCKED_IDENTITY_AMBIGUOUS` with both original alternative
Candidate refs.  庆源 remains `BLOCKED_IDENTITY_UNMATCHED` with an empty
Candidate-ref list.  The HTML does not select an identity or create a
placeholder.

The report states that route evidence, opening hours, activity duration,
specific activity times, and an identity blocker remain unresolved.  It does
not present a recommendation, route, duration, distance, ranking, real-time
status, or verified source claim.

## 2. Baseline and approval identity

Execution started from:

```text
branch: main
HEAD: e008d9e6fbdd81f7642f32bd0d6488a61bb6d539
worktree: only the approved WU5-E2E Plan
remotes: 0
stashes: 0
tests: 204/204
schemas: 11
fixtures/documents/dirty cases: 7/40/7
```

Approved Plan:

```text
path: plans/work-unit-5-e2e-html-demo.md
version: v0.1
SHA256: 653529395335CF422C1D02A206826DAFC32D10ECEE90A2125FFB37886D61AB54
lines: 220
status at approval: PENDING_HUGIN_APPROVAL
```

The Plan bytes and status text were not changed after approval.

The execution gate independently ran the 12 historical test modules and
observed:

```text
Ran 204 tests
OK
fixtures/documents/dirty cases: 7/40/7
```

The historical WU4 verifier was not changed or bypassed.  Its old scope gate
would correctly reject the newly approved WU5 Plan, so the exact module list
frozen by that verifier was run directly for the execution baseline.

Handbook state remained:

```text
local HEAD: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree: clean
```

The eight mandatory handbook files were re-read from `origin/main`; no
handbook file was modified.

## 3. Actual interfaces and stage boundaries

The new public interface is:

```python
run_e2e_demo(
    anchor_root: Path,
    planning_input_root: Path,
    output_root: Path,
) -> ValidationResult[E2EDemoSummary]
```

It calls the actual existing entrypoints in this fixed sequence:

```text
run_wu2_recovery
run_evidence_runtime
run_coarse_planner
_render_html
_install_directory
```

An independent injected-boundary check observed:

```json
{
  "install_calls": 1,
  "llm_calls": 0,
  "network_attempts": 0,
  "stage_calls": [1, 1, 1],
  "temporary_residue": 0
}
```

Each stage wrapper also asserted that its output child directory did not exist
when the stage was called.  The orchestrator creates only the same-parent
staging root; each existing runtime creates its own `recovery`, `evidence`, or
`planning` child.

The E2E module does not contain Recovery validation, Evidence mapping,
identity selection, constraint projection, Candidate admission, allocation,
or no-plan decision logic.  It consumes the named stage outputs and checks
only the fields required to compose, render, and audit the result.

## 4. Git history and scope

Starting commit:

```text
e008d9e6fbdd81f7642f32bd0d6488a61bb6d539
```

Linear commits through C4:

```text
25b74982397ff6ba6e693ff89e0d8a4010c6db4f docs: record WU5 end-to-end HTML demo plan
668f77fdd08b098bcdf45bc47a59d3b247f4d61d chore: add end-to-end demo interface
7c28d1c427eb16c8fc5f63923fdf3cbc13a54704 test: add failing end-to-end demo cases
ddfe7ba364e276dbb406a10958084a36eb97a424 feat: implement end-to-end HTML demo
a45eb815a58db35a0eda5abc53fbc7d7dcf6afa5 chore: add end-to-end demo verification entry
```

C5 is the single-purpose commit containing this Review.

The final WU5 diff is restricted to:

```text
plans/work-unit-5-e2e-html-demo.md
src/trip_decider/e2e_demo.py
tests/test_wu5_e2e_demo.py
scripts/verify_wu5_e2e_demo.ps1
docs/reviews/work-unit-5-e2e-html-demo-review.md
```

Pre-C5 stat was:

```text
4 files changed, 3602 insertions
```

The Review adds only the fifth approved path.  No amend, squash, reset,
rebase, push, remote, or stash operation occurred.

## 5. Frozen hash evidence

```text
Plan:
653529395335CF422C1D02A206826DAFC32D10ECEE90A2125FFB37886D61AB54

e2e_demo.py:
BA934DE551056533DBDBE59BC51B007DDA9272C4DF2A8FC300C31A6E8040C6C7

test_wu5_e2e_demo.py:
DCA808033245AE055AA46F6E10434F238ECFF3460735AE183EF8A97A21AD15B2

verify_wu5_e2e_demo.ps1:
23DC08AD9DC929F230C752BDB13B0331763C0C73023E572A7839911DA627DF6D

PLAN.md:
563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456
```

Protected runtime hashes remained:

```text
recovery.py:
C0E098DD4AB997727A0EFBCCC9C396AC480DEEB3477DBF4CDCB5E31A34E0D8BA

evidence_runtime.py:
626D052F068537D050D350E8404948286670405D0B75C2E793CAA71656C89C04

coarse_planner.py:
8098F75190E279419D704E9135B896DE84D88691D4B2A942142671C870E25D8C
```

The verifier also checks the four committed anchor files, WU4 planning-input
builder, `pyproject.toml`, `requirements.lock`, and all 11 exact Schema hashes.

## 6. C2 Red evidence

Exact command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu5_e2e_demo -v
```

C2 result:

```text
exit code: 1
tests: 6
passed: 0
failures: 0
errors: 6
```

Every error was the explicit public interface state:

```text
NotImplementedError: WU5-E2E interface awaiting implementation
```

All six failures originated at `run_e2e_demo(...)`.  There were no import,
dependency, syntax, path, malformed-input, network, or LLM errors.

The C2 commit was preserved and was not amended or rewritten.

## 7. C3 Green evidence and implementation correction

The first C3 run used the same exact command and observed:

```text
tests: 6
passed: 5
failures: 1
errors: 0
```

The single E2E01 failure showed that the top-level summary hash for a stage
summary was calculated from a reserialized JSON document.  The reserialization
bytes differed from the actual stage `run-summary.json` bytes.  This was an
implementation defect, not a test, fixture, stage, or product-contract defect.

Only `e2e_demo.py` was changed.  The implementation now reads each prepared
stage summary file and hashes its exact bytes.  It does not use the parsed
document or regenerated JSON as hash input.

The same command then produced:

```text
tests: 6
passed: 6
failures: 0
errors: 0
network attempts: 0
LLM calls: 0
```

The full explicit suite then produced:

```text
Ran 210 tests
OK
```

C3 changed only `src/trip_decider/e2e_demo.py`; no test was modified to fit
the implementation.

## 8. Directory transaction and rollback

Windows system-temp probes before implementation established:

```text
os.replace(staging_dir, missing_target): success
os.replace(staging_dir, existing_empty_target): PermissionError
```

The public precondition therefore requires:

```text
output parent: existing regular non-symlink directory
output root: absent
```

Existing empty and non-empty roots both fail without deletion or overwrite.

For a valid run:

1. one random staging directory is created under the output parent;
2. three stage outputs are completed inside that staging root;
3. HTML and top-level summary are written exclusively;
4. all 13 files, report bytes, summary bytes, JSON, HTML, paths, and hashes are
   read back and checked;
5. `_install_directory` invokes one `os.replace(staging_root, output_root)`;
6. installed report, summary, and exact file inventory are checked again.

The random staging name is absent from every output byte and business ID.

Failure injection at Evidence Runtime proved:

```text
Recovery calls: 1
Evidence Runtime calls: 1
Coarse Planner calls: 0
renderer calls: 0
output root exists: false
staging residue: 0
```

The original safe upstream `ValidationProblem` was propagated rather than
converted into success or partial success.

## 9. Exact output and top-level summary

Successful output contains exactly 13 files:

```text
recovery/candidates.json
recovery/seed-accounting.json
recovery/record-local-facts.json
recovery/run-summary.json
evidence/evidence.json
evidence/evidence-gate.json
evidence/run-summary.json
planning/plan.json
planning/violations.json
planning/planning-gate.json
planning/run-summary.json
report/index.html
run-summary.json
```

No debug file, manifest, cache, copied artifact, or repository runtime output
is added.

The top-level summary contains:

```text
schema_version
run_id
completion_status
input
stages
result
report
network_attempts
llm_calls
```

Its run ID equals the Planner run ID.  It stores the exact-byte SHA256 for
the three stage summaries and `report/index.html`; it does not store its own
hash.  Tests and the verifier compute the top-level summary hash externally.

All paths in the summary and HTML are relative.  Absolute staging, repository,
anchor, planning-input, and output paths are absent.

Two independent clean output roots had the exact same 13-path inventory and
byte-for-byte identical contents.

## 10. Conditional HTML result

The report is:

```text
UTF-8 without BOM
single file
inline CSS only
no JavaScript
no image
no external stylesheet
no external link or CDN
```

The fixed section order is:

```text
status
itinerary
blockers
evidence
conditions
audit
```

The conditional page visibly states:

```text
条件化粗计划
不可直接发布
未进行路线、营业时间或时长验证
plan_status: conditionally_feasible
publishable: false
generation_allowed_input: false
```

The two day cards show only:

```text
第1天：江岭
具体时刻：尚未安排

第2天：李坑
具体时刻：尚未安排
```

They do not expose `start_at`, `end_at`, route, duration, distance, opening
hours, transport time, ranking, recommendation, heat, or optimization values.

Blockers are rendered in planning-gate order.  Every 篁岭 alternative ref is
shown and none is selected.  庆源 shows an empty ref state and explicitly
states that no placeholder was created.

Evidence facts are read from the formal Evidence artifact.  The current page
shows:

```text
support_status: unknown
display_status: unknown
```

It also states that the extracted offline Candidate records cannot be treated
as verified facts.  It does not claim verified, reliable, official, or
real-time data.

Planner conditions are emitted in their original array order with the original
condition ID and description.  They are not translated, merged, reordered, or
used to derive a new conclusion.

All artifact-derived strings flow through:

```python
html.escape(value, quote=True)
```

An independent renderer check replaced a Candidate label in memory with
script-like markup and verified that only escaped text appeared in the output.
No fixture or artifact file was modified.

## 11. no_plan_found page

The one-day explicit planning input produced:

```text
status=no_plan_found
scheduled=0
blocked=2
publishable=false
```

Its page uses `id="no-plan"` and does not create an itinerary section.
It shows the exact Planner reason:

```text
INSUFFICIENT_DAY_CAPACITY_FOR_ONE_PER_DAY_ALLOCATOR
```

It retains both unscheduled required Candidate refs and their existing labels.
It also retains the identity blockers and states:

```text
这不等于已证明不可行
```

The page does not show a proof, partial allocation, “无法旅行”, “行程不可行”,
or “约束无解”.

## 12. CLI evidence

The verifier actually executed:

```powershell
.\.venv\Scripts\python.exe -m trip_decider.e2e_demo `
  --anchor-root <committed anchor> `
  --planning-input-root <system-temp explicit input> `
  --output-root <system-temp missing output>
```

Because the repository uses an uninstalled `src/` layout and modification of
`pyproject.toml` was prohibited, the verifier sets `PYTHONPATH` to the project
`src` directory only for the child CLI process and restores the prior
environment immediately afterward.  It does not install the project or alter
user configuration.

Conditional success:

```text
exit code: 0
stdout:
status=conditionally_feasible scheduled=2 blocked=2 publishable=false report=report/index.html
stderr: empty
```

No-plan success:

```text
exit code: 0
stdout:
status=no_plan_found scheduled=0 blocked=2 publishable=false report=report/index.html
stderr: empty
```

An existing output root produced exit 4, empty stdout, and one seven-field
`ValidationProblem` JSON Line on stderr.  Its `artifact_path` was the safe token
`output_root`; no absolute path or input value appeared.  The existing marker
file was unchanged.

`main()` calls `run_e2e_demo(...)`; it does not contain a second orchestration
chain.

## 13. C4 verification-entry history

The first full C4 attempt reached:

```text
targeted tests: 6/6
full tests: 210/210
```

It then attempted all three CLI runs.  Each stopped before module execution
with:

```text
ModuleNotFoundError: No module named 'trip_decider'
```

Cause: the new CLI child process did not inherit a source import path for the
repository's uninstalled `src/` layout.

Under the approved low-risk “temporary checker import path” correction, only
the verifier was changed to set and restore `PYTHONPATH=<repo>/src` around
the exact CLI command.  No module, test, `pyproject.toml`, dependency, or user
environment configuration changed.

The second full attempt passed:

```text
three CLI runs
13-file inventory
byte-identical clean roots
no-plan checks
seven-field failure JSONL
210/210 tests
7/40/7 fixtures
```

It then stopped because the separate system-temp library-boundary checker
also lacked the `src/` import path.  This was another checker bootstrap error,
not a runtime, HTML, artifact, or test failure.

The checker received the same approved repo/src insertion in its temporary
Python code.  No assertion or expected value changed.

The corrected pre-commit run and the independent post-C4-commit rerun both
reported:

```text
WU5-E2E verification PASS:
tests=210
schemas=11
fixtures=7
documents=40
dirty_cases=7
output_files=13
network_attempts=0
llm_calls=0
temporary_residue=0
```

The two failed attempts are retained here and are not described as successful
or removed from the execution history.

## 14. R10 and boundary review

- No `NotImplementedError` remains in the WU5 runtime.
- No silent fallback, guessing, semantic inference, or warning-as-pass exists.
- No network client, socket call, LLM client, map service, or external asset
  exists in `e2e_demo.py`.
- No city-specific planning branch or hard-coded Jiangxi place name exists in
  the production module.
- No raw provider body, coordinate list, secret, absolute machine path, input
  value, or third-party exception text is rendered or printed.
- Upstream validation problems fail the run and stop later stages.
- Unknown Evidence remains unknown.
- `generation_allowed_input=false` and `publishable=false` are not promoted.
- `no_plan_found` is not described as infeasible.
- Stage summaries are hashed from actual bytes, not regenerated values.
- HTML strings are escaped with the frozen standard-library boundary.
- The CLI has one orchestration path through `run_e2e_demo(...)`.
- Git commit messages and diffs match their single responsibilities.

## 15. Completion criteria

1. ✓ Baseline and handbook were independently checked.
2. ✓ Approved Plan hash and bytes remained unchanged.
3. ✓ Each real stage is called once per E2E invocation in fixed order.
4. ✓ Stage failure stops later work and fully rolls back.
5. ✓ Same-parent staging and one final directory installation are enforced.
6. ✓ Successful output contains exactly 13 approved files.
7. ✓ Top-level summary, relative paths, run ID, and actual-byte hashes read back.
8. ✓ HTML is escaped, static, single-file, UTF-8, and offline.
9. ✓ Five result sections plus ordered audit links render proven data only.
10. ✓ Ambiguous and unmatched blockers retain their exact identity state.
11. ✓ Unknown Evidence and both false gates are not elevated.
12. ✓ no-plan preserves required refs and does not claim infeasibility.
13. ✓ CLI success/failure streams, exit codes, and safe JSONL are verified.
14. ✓ C2 exact Red and same-command C3 Green are preserved.
15. ✓ Full regression is 210/210; fixtures remain 7/40/7.
16. ✓ Five-path scope, frozen hashes, R10 scans, and Review are independently
   reproducible.

## 16. Preserved exclusions

WU5-E2E did not modify Schema, fixture, validator, existing tests, Recovery,
Evidence Runtime, Coarse Planner, Resume/FER, adapter, dependency,
`pyproject.toml`, `PLAN.md`, handbook, or historical verifier files.

It did not call network or an LLM and did not add map, route, distance, time,
opening-hours, hotel, dining, weather, cost, rating, image, attraction
description, recommendation, ranking, optimization, or UI-framework behavior.

No later Work Unit was started.

Final state:

```text
READY_FOR_HUGIN_REVIEW
```
