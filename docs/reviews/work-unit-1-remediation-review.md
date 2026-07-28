# Work Unit 1 Remediation Review

Review date: `2026-07-28`

Plan:

```text
plans/work-unit-1-remediation.md
Plan version: v0.1
SHA256: 77231B6DA9552377855FBCE16C2D9C057E5D8C9341490D4D60D694B37FF47F9F
```

Work unit start:

```text
80395c24612056eff6ff07f81eb3ac5df8c1660b
docs: prepare Work Unit 1 review evidence
```

Historical statement:

```text
WU1 Review at 80395c2: INCOMPLETE
WU1R later closes the two recorded gaps
```

This Review does not revise the historical WU1 result. It reviews the later,
separate remediation only.

## 1. Outcome

WU1R closes the two gaps recorded by the WU1 Review:

1. `scripts/verify_wu1.ps1` now invokes one complete entry that verifies the
   project runtime, exact lock state, `pip check`, Schema registry, frozen
   unittest discovery, six formal fixtures, historical and remediation scope,
   suspicious fallback, secret patterns, and eight frozen hashes.
2. The entry reuses the existing seven-field `ValidationProblem`, emits
   machine problems as JSON Lines on stderr, keeps stdout human-only, and
   deterministically distinguishes exit `0/2/3/4/5`.

No artifact Schema, existing validator, existing test, formal fixture,
dependency, business behavior, API adapter, or WU2 content changed.

## 2. Git history and commit responsibilities

The WU1R commits before this Review document:

```text
7fe79241c8b2de82fc9dde1f8cec6d949e4f0d4d
docs: record approved WU1 remediation plan

ace5baec27868183fe4672b56c7cdabbb872bd45
chore: add importable WU1 remediation verification interface

7ae24c1bfa5b9d4c9649f6a99d787f58aedf72db
test: add failing full-entry contract cases

f828f16f51c385ec0d5a79cae75425461fe2de2e
fix: complete WU1 verification entry contract
```

R4 is this document's single-file commit:

```text
docs: prepare WU1 remediation review
```

Its final commit hash is necessarily produced after this file is committed and
is included in the terminal Hugin handoff. R0—R4 remain linear on `main`; none
of the original WU1 commits was amended, rebased, squashed, reset, or deleted.

Commit/file mapping:

| Commit | Paths | Responsibility |
|---|---:|---|
| R0 | 1 | approved Plan bytes only |
| R1 | 1 | importable interface with explicit `NotImplementedError` |
| R2 | 1 | 18 deterministic contract cases and valid red |
| R3 | 2 | entry orchestration and PowerShell transport |
| R4 | 1 | this Review only |

Before R4, the measured WU1R diff was:

```text
plans/work-unit-1-remediation.md       |  870
scripts/verify_wu1.ps1                 |  245
src/trip_decider/verification_entry.py | 1309
tests/wu1r_verify_entry_cases.py       |  649
4 files changed, 2920 insertions(+), 153 deletions(-)
```

R4 adds only
`docs/reviews/work-unit-1-remediation-review.md`, producing the approved
five-path surface. The final five-path diff/stat is emitted again after R4.

## 3. Scope

The final WU1R path set is exactly:

```text
plans/work-unit-1-remediation.md
src/trip_decider/verification_entry.py
tests/wu1r_verify_entry_cases.py
scripts/verify_wu1.ps1
docs/reviews/work-unit-1-remediation-review.md
```

Measured before R4:

```text
WU1 historical path set: 36
WU1R committed path set: 4
worktree changes: 0
remote: 0
stash: 0
```

The final entry itself verifies two separate scope invariants:

- `21d8508..80395c2` equals the exact frozen 36-path set;
- `80395c2..HEAD` plus tracked and unknown untracked worktree paths is a
  subset of the five WU1R paths.

It does not use a count-only comparison, blanket untracked exclusion, or an
unknown-file allowlist.

Protected hashes after R3:

| Path | SHA256 |
|---|---|
| `plans/work-unit-1-contracts-fixtures.md` | `B1C2517EE7B9579EFA85C5998FA5E29170589A650CBB051F1F5C00400EB39212` |
| `docs/reviews/work-unit-1-review.md` | `C3E7CCF3D0F1A0181AD36E0435FCC481E56E3B3DAF42A921DB4E2E7EC72A659E` |
| `src/trip_decider/schema_validation.py` | `2061084E8AC27DF4C08F63DC264A2612685980D966AA5291A46660BE3F1CC017` |
| `src/trip_decider/fixture_validation.py` | `6C720C5F4D72356F2909854E6C1B605B891BC40787A4D87739CCA69C2590EBBF` |
| `tests/test_schema_validation.py` | `A4075DC19E2D923E25862D589DA4DA83AEE39B2D2355BF9B553683C7E24C0DAA` |
| `tests/test_fixture_validation.py` | `E748784A658FFD098A97269F7C3864A9CFB6612839207640A0CA0B900908BC7B` |
| `requirements.lock` | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` |
| `pyproject.toml` | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` |

## 4. Frozen hashes and history

The single entry checks these eight hashes:

| Path | SHA256 |
|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `plans/work-unit-0-bootstrap-d0.md` | `4C7FE14CD5D2CE0CC8E8D624D93C24338EAF61A9DBC0778D101AB3565602DE3B` |
| `docs/architecture.md` | `CA5B6F7D345E11623C94C13CDD73C0E774282AFD88F9E2E036035ED2396BB6F4` |
| `docs/artifact-contracts.md` | `695C0AC6738B71852DC60ADAFD2A98B974C5EC65BB744D19B0E22EC3550497BF` |
| `docs/prior-art.md` | `C1195E816DB5F21FE83B4208B6258BA9F138C9AB9404373A132CE75C457893E7` |
| `docs/handbook-context.md` | `1933DBA1B3697A394EDCC0238B60A032A18EA10B920F8C4358169490492115EB` |
| `docs/reviews/work-unit-0-review.md` | `D93373ECC7398DEE95FFCC04E0143DE80612B4FE948FD36282FA98F793477128` |
| `plans/work-unit-1-contracts-fixtures.md` | `B1C2517EE7B9579EFA85C5998FA5E29170589A650CBB051F1F5C00400EB39212` |

Separate historical/approval checks:

```text
WU1R Plan:
77231B6DA9552377855FBCE16C2D9C057E5D8C9341490D4D60D694B37FF47F9F

Original WU1 Review:
C3E7CCF3D0F1A0181AD36E0435FCC481E56E3B3DAF42A921DB4E2E7EC72A659E

Original WU1 Review final line:
INCOMPLETE
```

The original WU1 11-commit sequence was checked before R0 and was unchanged.

## 5. Runtime, lock, and pip

Independent runtime measurement:

```text
sys.executable:
<repo>\.venv\Scripts\python.exe

sys.prefix:
<repo>\.venv

site-packages:
<repo>\.venv
<repo>\.venv\Lib\site-packages

requirements.lock entries: 21
installed distributions: 23
non-bootstrap distributions: 21
bootstrap exclusions: pip, setuptools
exact lock/runtime match: true
pip check exit: 0
pip check result: No broken requirements found.
```

The entry:

- requires the exact project executable and prefix;
- checks every site-packages and distribution location is within `.venv`;
- parses strict UTF-8 `name==version` lock lines;
- rejects duplicate canonical names, paths, URLs, credentials, or malformed
  values;
- compares exact PEP 503-canonical names and exact versions;
- excludes only `pip` and `setuptools`;
- invokes `[sys.executable, "-m", "pip", "check"]` without a shell;
- captures and sanitizes failed command output instead of copying it.

It never installs, changes the lock, permits a wide allowlist, or falls back
to global Python.

## 6. Schema, tests, and fixtures

The success entry executes all of the following before reporting PASS:

```text
Schema files: 11
Draft: 2020-12
unique local registry: pass
required format checker self-test: pass
local/relative $ref resolution: pass

default unittest discovery: 82
failures: 0
errors: 0

closed fixture directories: 6
documents: 38
dirty cases: 6
manifest roots: 6 explicit actual envelope IDs
```

Existing `validate_schema_registry`, `validate_fixture_manifest`, and
`validate_fixture_directory` remain the structure validators. WU1R only
orchestrates them and verifies the frozen surface.

The two test-count surfaces remain intentionally distinct:

```text
Explicit WU1R contract suite: 100 tests
Single-entry default discovery: 82 tests
```

The remediation file is named `tests/wu1r_verify_entry_cases.py`; the default
discovery pattern was not changed.

## 7. R1 interface evidence

R1 created only `src/trip_decider/verification_entry.py` with:

```python
run_verification(repo_root, *, dependencies, stdout, stderr) -> int
main() -> int
```

Both functions were importable. Both implementation paths explicitly raised
`NotImplementedError`; the existing default discovery then passed:

```text
tests: 82
passed: 82
failures: 0
errors: 0
```

The first local R1 harness attempt did not establish a valid result because
the fresh PowerShell process lacked the project `src` import path and native
stderr handling stopped the wrapper. No commit was made from that attempt.
The same approved command was rerun with a process-local project
`PYTHONPATH`; it produced the valid 82/82 evidence above. No user or system
environment was modified.

## 8. R2 valid red

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1r_verify_entry_cases -v
```

Valid red result:

```text
exit code: 1
Ran: 100 tests
original WU1 tests: 82/82 green
WU1R test methods: 18
existing transport green: 1
specific contract failures: 2
approved NotImplementedError reports: 16
unexpected errors: 0
import/path/dependency/PowerShell/syntax/malformed-input errors: 0
```

VE-02 has two explicit subTest values (`prefix`, `site_packages`), so its
single unittest method produced two approved `NotImplementedError` reports.
The two specific assertion failures were:

```text
VE-17: failed transport cleanup/function boundary not yet implemented
VE-18: complete-entry stderr/stdout contract not yet implemented
```

An initial evidence-wrapper count used only output lines carrying a terminal
status and therefore counted 99: VE-02's parent line has no terminal status
when its subTests error. `unittest` itself correctly reported
`Ran 100 tests`. The wrapper was corrected without changing the test file,
the identical command was rerun, and the valid red above was committed.

R2 expected values are manually frozen in the test module. No expected output
is generated by the entry.

## 9. R3 green

R3 modified only:

```text
src/trip_decider/verification_entry.py
scripts/verify_wu1.ps1
```

The exact R2 command produced:

```text
exit code: 0
Ran: 100 tests
passed: 100
failures: 0
errors: 0
```

The formal entry produced:

```text
WU1 verification PASS: schemas=11 tests=82 fixtures=6 documents=38 dirty_cases=6
exit code: 0
temporary Python files before: 0
temporary Python files after: 0
residue delta: 0
```

During R3 implementation, the contract suite caught and drove three
in-scope corrections before the commit:

1. vendor-prefixed `AMAP_API_KEY` required a secret pattern that recognizes
   the prefix without printing the value;
2. relative Schema `$ref` values required resolution against the current
   Schema `$id` before registry membership comparison;
3. scanner self-check found its own complete suspicious token, so the token
   was assembled from segments rather than excluding the scanner file;
4. PowerShell function output capture consumed the success summary, so the
   transport changed to explicit child-process stdout/stderr forwarding.

No test, Schema, fixture, validator, lock, or Plan changed while resolving
these R3 implementation defects.

Static R3 checks:

```text
reachable NotImplementedError in verification entry: 0
python -c in verification script: 0
Invoke-Expression in verification script: 0
nested powershell -Command in verification script: 0
repository temporary trip-decider-wu1-*.py: 0
```

## 10. Exit-code and output evidence

| Case | Injected surface | Exit | Evidence |
|---|---|---:|---|
| VE-05 | frozen hash mismatch | 2 | no expected/actual hash value emitted |
| VE-09 | artifact/Schema problem | 2 | original code, seven fields, stderr |
| VE-13 | artifact problem from fixture stage | 2 | not collapsed into fixture exit 3 |
| VE-10 | fixture manifest/expectation | 3 | seven fields, stderr |
| VE-11 | read/UTF-8/JSON/YAML class | 4 | sanitized project error |
| VE-01—08 | runtime/lock/pip/scope/scan | 5 | sanitized project error |
| VE-12 | registry/internal | 5 | third-party marker absent |
| VE-14 | mixed and unknown problem | 5 | priority `5 > 4 > 2 > 3` |
| VE-18 | complete real success | 0 | stderr empty, fixed human stdout |

Each machine line contains exactly:

```text
error_code
artifact_path
json_pointer
schema_rule
expected
actual_type
message
```

Tests assert no eighth field, deterministic
`artifact_path/json_pointer/error_code` ordering, stderr-only machine JSON,
human-only stdout, and absence of input values, secrets, tracebacks, and
third-party exception text.

An unknown `error_code` becomes `ENTRY_UNCLASSIFIED_PROBLEM` and exit 5; it
cannot be guessed into an artifact or fixture class.

## 11. PowerShell transport

The final transport uses:

- the system temporary directory;
- a random GUID filename;
- UTF-8 without BOM;
- the exact project `.venv` Python;
- a child-only `PYTHONPATH=<repo>\src`;
- `try/finally` deletion;
- explicit stdout/stderr forwarding;
- fixed seven-field bootstrap failure if Python cannot start.

VE-16 and VE-17 independently prove residue 0 for success and failure.
There is no repository temporary `.py`, global/system `PYTHONPATH` change,
global Python fallback, command-string evaluation, or nested PowerShell.

## 12. Complete-entry internal checks

The success path means all 18 approved checks ran in one invocation:

1. project `.venv` exists, no global fallback;
2. exact `sys.executable`;
3. exact `sys.prefix`;
4. all site-packages and distribution locations inside `.venv`;
5. strict lock parsing;
6. exact 21-package non-bootstrap match;
7. bootstrap set limited to `pip`, `setuptools`;
8. subprocess `pip check`;
9. 11 Schema registry/format checks;
10. 82-test default discovery;
11. 6/38/6 formal fixture validation;
12. exact historical 36-path set;
13. five-path WU1R cumulative/worktree subset;
14. fallback/guess/infer/warning scan;
15. secret scan;
16. eight frozen hashes;
17. seven-field stderr JSONL;
18. deterministic `0/2/3/4/5`.

Review-only commands were used as independent observations, not substitutes
for entry behavior.

## 13. R4 independent rerun

Before writing this Review, the committed R3 state was independently rerun:

```text
Explicit WU1R contract suite:
exit 0
100 tests
100 passed
0 failures
0 errors

Single-entry default discovery:
exit 0
82 tests
6 fixture directories
38 documents
6 dirty cases
temporary residue 0
```

After this document's final byte is formed, the same two approved commands are
the final R4 gate. R4 is committed only if both remain green while this
untracked Review path is included in the five-path scope check. The terminal
handoff supplies that final-byte command evidence and resulting R4 commit.

## 14. Handbook, remote, and prohibited work

Handbook after fetch/reconciliation:

```text
local HEAD: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree changes: 0
```

No handbook file was changed. No remote was created. No push occurred. No
WU2 file, WU2 Plan, business planner, API adapter, HTML renderer, real trip,
or destination-discovery behavior was added.

## 15. R10 self-check

```text
silent fallback: none
automatic field/value repair: none
global Python fallback: none
wide package allowlist: none
warning-as-pass: none
reachable NotImplementedError in final entry: 0
machine JSON on stdout: 0
third-party raw error copied to machine problem: 0
input/secret/hash value emitted: 0
artifact issue mapped to fixture exit 3: 0
repository temporary Python residue: 0
protected path modification: 0
```

The implementation is structural verification only. Documentation does not
claim travel behavior, evidence truth, feasibility, route quality, proof
correctness, or optimization.

## 16. Eighteen completion criteria

1. ✓ 已完成 — WU1 final HEAD, all 11 historical commits, and the original
   `INCOMPLETE` Review bytes remain unchanged.
2. ✓ 已完成 — approved WU1R Plan was committed alone in R0 and retains its
   approved SHA256.
3. ✓ 已完成 — `pyproject.toml`, `requirements.lock`, and the dependency set
   were not changed or expanded.
4. ✓ 已完成 — WU1R uses only the five approved paths; the original WU1 set is
   exactly 36 paths.
5. ✓ 已完成 — R1 created only the importable interface and retained explicit
   unimplemented behavior until R2.
6. ✓ 已完成 — R2 recorded a valid 100-test red with all original 82 green and
   no import/path/dependency/PowerShell/syntax/malformed-input regression.
7. ✓ 已完成 — R3 used the identical command for 100/100 green; all 18 WU1R
   methods pass.
8. ✓ 已完成 — the entry asserts executable, prefix, site-packages, and
   distribution locations within the project `.venv`, with no fallback.
9. ✓ 已完成 — the entry compares 21 exact locked packages, permits only the
   two named bootstrap distributions, and runs `pip check`.
10. ✓ 已完成 — the entry validates 11 Schema files, registry/format, 82-test
    discovery, and the 6/38/6 closed/root fixture surface.
11. ✓ 已完成 — historical scope, remediation scope, fallback/guess/infer/
    warning, and secret checks run inside the entry and pass with zero hits.
12. ✓ 已完成 — all seven original frozen inputs plus the WU1 Plan hash match.
13. ✓ 已完成 — fault injection proves exits 2, 3, 4, and 5; artifact problems
    retain exit 2 and mixed priority is deterministic.
14. ✓ 已完成 — machine problems are exact seven-field stderr JSONL; stdout is
    human-only and no third-party/input/secret value leaks.
15. ✓ 已完成 — PowerShell uses the approved system-temp transport; success and
    failure residue are zero and prohibited invocation forms are absent.
16. ✓ 已完成 — the R3 and R4 independent entries both report
    82 tests, 6 fixtures, 38 documents, and 6 dirty cases with exit 0.
17. ✓ 已完成 — existing validators, Schema, formal fixtures, original tests,
    WU0, handbook, and user configuration remain unchanged; no business or
    WU2 content exists.
18. ✓ 已完成 — R0—R4 are linear and independently reviewable; final Git
    status/remote/stash/push evidence is supplied after the R4 commit.

No completion criterion is `⚠` or `✗`.

## 17. Final status

READY_FOR_HUGIN_REVIEW
