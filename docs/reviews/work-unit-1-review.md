# Work Unit 1 Review

Review date: 2026-07-26
Plan: `plans/work-unit-1-contracts-fixtures.md` v0.5
Approved Plan SHA256: `B1C2517EE7B9579EFA85C5998FA5E29170589A650CBB051F1F5C00400EB39212`
WU1 start: `21d8508a8f96472ecc4d7f798cdd6af3d7f54f68`
C7 HEAD / C8 pre-commit HEAD: `5ed0c327d494d9a9600ed5d604a958008d5d1354`
Review status: `INCOMPLETE`

## 1. Outcome

WU1 implemented and independently exercised:

- strict JSON/YAML/UTF-8 loading;
- Draft 2020-12 Schema registry and format checking;
- canonical payload hashes;
- explicit artifact, definition and reference registries;
- `ARTIFACT_ONLY` and explicit-root `CLOSED` bundle validation;
- root-reachable closure and rejection of extra artifacts;
- fact-local source and plan-version scopes;
- strict fixture manifests, embedded bytes/hash, safe paths, single mutations,
  and exact expected-error matching;
- six synthetic deterministic fixtures containing 38 embedded documents and
  six dirty cases.

Both `C7 second corrected acceptance run` and `C8 Independent Rerun` exited 0:
82/82 unittests passed, all six fixture contracts passed, and no temporary
Python file remained.

WU1 is nevertheless `INCOMPLETE`. The committed `verify_wu1.ps1` does not
perform all checks required inside the single entry by Plan §10.2: lock-state,
strict interpreter/site-packages identity, scope, suspicious fallback, secret,
and frozen-hash checks are absent. Those checks were run separately during
Review, but R10 prohibits describing separate manual commands as capabilities
of the script. The entry also has no exit-code-2 artifact-validation path, and
its fixture failure serialization does not emit the complete seven-field JSON
Lines object to stderr required by Plan §10.3. C8 is documentation-only, so
these implementation gaps were not repaired.

## 2. Git evidence

### 2.1 Linear history

The approved final history has 11 commits, including two separately approved
test corrections and no C7.1 commit:

| Step | Commit | Message |
|---|---|---|
| C0 | `c1c1e01` | `docs: record approved Work Unit 1 plan` |
| C1 | `a3e1c4d` | `chore: add WU1 dependency and importable validation interfaces` |
| C2 | `9a340d6` | `chore: add loadable schema contract interfaces` |
| C3 | `bb626c7` | `test: add failing artifact schema contract cases` |
| C3.1 | `c8ad499` | `test: correct CS-03 plan-root reachable bundle` |
| C3.2 | `5bb9fe5` | `test: correct BASE-02 duplicate definition pointer` |
| C4 | `3762af8` | `feat: implement strict artifact schema validation` |
| C5 | `d8c1d1f` | `test: add failing fixture validation cases` |
| C6 | `e426847` | `feat: implement strict fixture validation` |
| C7 | `5ed0c32` | `test: add six structured fixtures and full verification entry` |
| C8 | this commit | `docs: prepare Work Unit 1 review evidence` |

No commit was amended, reset, rebased, squashed, or rewritten. No remote was
created and nothing was pushed.

Reproduction commands:

```powershell
git status --short
git log --oneline --decorate 21d8508a8f96472ecc4d7f798cdd6af3d7f54f68..HEAD
git diff --stat 21d8508a8f96472ecc4d7f798cdd6af3d7f54f68..HEAD
git diff 21d8508a8f96472ecc4d7f798cdd6af3d7f54f68..HEAD
```

At C7, the measured diff from the WU1 start was 35 paths and 7,185 insertions.
C8 adds only this Review as the 36th approved path. The post-commit Git
commands above are the authoritative full diff/stat; embedding the Review's
own final commit hash or full diff in itself would be self-referential.

### 2.2 Thirty-six-path whitelist

The final path allocation is exact:

| Group | Count |
|---|---:|
| approved Plan | 1 |
| dependency metadata and lock | 2 |
| `src/trip_decider` | 3 |
| Schema and HTML contract | 12 |
| fixture README/case paths | 13 |
| tests | 3 |
| verification script | 1 |
| Review | 1 |
| total | 36 |

No WU0 file, frozen product plan, handbook file, user configuration, or other
repository was modified.

## 3. Frozen-input hashes

All values were re-read with `Get-FileHash -Algorithm SHA256`; mismatches: 0.

| Input | SHA256 | Status |
|---|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` | unchanged |
| `plans/work-unit-0-bootstrap-d0.md` | `4C7FE14CD5D2CE0CC8E8D624D93C24338EAF61A9DBC0778D101AB3565602DE3B` | unchanged |
| `docs/architecture.md` | `CA5B6F7D345E11623C94C13CDD73C0E774282AFD88F9E2E036035ED2396BB6F4` | unchanged |
| `docs/artifact-contracts.md` | `695C0AC6738B71852DC60ADAFD2A98B974C5EC65BB744D19B0E22EC3550497BF` | unchanged |
| `docs/prior-art.md` | `C1195E816DB5F21FE83B4208B6258BA9F138C9AB9404373A132CE75C457893E7` | unchanged |
| `docs/handbook-context.md` | `1933DBA1B3697A394EDCC0238B60A032A18EA10B920F8C4358169490492115EB` | unchanged |
| `docs/reviews/work-unit-0-review.md` | `D93373ECC7398DEE95FFCC04E0143DE80612B4FE948FD36282FA98F793477128` | unchanged |
| WU1 Plan | `B1C2517EE7B9579EFA85C5998FA5E29170589A650CBB051F1F5C00400EB39212` | unchanged |

## 4. Handbook reconciliation

Fixed path: `<handbook>`

Before and after the final `git fetch origin --prune`:

- local HEAD: `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`;
- `origin/main`: `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`;
- ahead/behind: `0/0`;
- branch: `main`;
- worktree: clean.

The eight mandatory files were read again from `origin/main`:

| Path | Blob |
|---|---|
| `STATE.md` | `cd2def5cb59993125480ac0bc52191d33595e14f` |
| `INDEX.md` | `feed762c97b1a3452b90991d722b757099828346` |
| `SUMMARY.md` | `ddc9963950a7b5c8691c0a295d0ef5b039d437d7` |
| `tools/context-injection.md` | `afd4f9756e5861e0791046e5da56957d307e75d7` |
| `principles/r10-honesty.rule.md` | `7b1111dd1f52609d7e4b6e4af72305f6c81e6f5b` |
| `principles/per-protocol.rule.md` | `ea43c185e208bf196b566560b09a2f4739febe13` |
| `principles/scope-control.rule.md` | `762675ab33129c0d5bf3717161fef6311f827738` |
| `principles/fixture-first.rule.md` | `398fc74122462e03354e714a76b38e82f4168255` |

The handbook working tree was not modified.

## 5. Dependencies, lock replay, and licenses

### 5.1 Environment and replay

- Python: 3.11.9.
- Interpreter:
  `<repo>\.venv\Scripts\python.exe`.
- Prefix: `<repo>\.venv`.
- Site-packages:
  `<repo>\.venv\Lib\site-packages`.
- Direct dependencies: 2.
- Transitive runtime dependencies: 19.
- Runtime lock entries: 21.
- `pip check`: `No broken requirements found`.
- Runtime lock versus installed runtime packages: exact match; the only
  `pip freeze --all` extras were the venv bootstrap tools `pip==24.0` and
  `setuptools==65.5.0`, intentionally not runtime lock entries.

The first `pip install . --no-build-isolation` could not build because the
clean environment did not contain wheel. No extra dependency was installed.
The two approved dependencies were read mechanically from `pyproject.toml`
with stdlib `tomllib`, installed from public PyPI, and locked. The environment
was cleared/recreated with `py -3.11 -m venv --clear`, replayed only from the
lock, and the resolved runtime package list compared with zero differences.
No global freeze, private index, credential, absolute local path, or user
Python/pip configuration entered the lock.

### 5.2 License audit

Every locked distribution contains an installed license file. License fields,
classifiers, files, and official project/PyPI records were inspected.

| Package | Version | License evidence | Official record |
|---|---:|---|---|
| arrow | 1.4.0 | Apache-2.0 | `https://pypi.org/project/arrow/1.4.0/` |
| attrs | 26.1.0 | MIT | `https://pypi.org/project/attrs/26.1.0/` |
| fqdn | 1.5.1 | MPL-2.0 | `https://pypi.org/project/fqdn/1.5.1/` |
| idna | 3.18 | BSD-3-Clause | `https://pypi.org/project/idna/3.18/` |
| isoduration | 20.11.0 | ISC classifier and repository license | `https://pypi.org/project/isoduration/20.11.0/` |
| jsonpointer | 3.1.1 | Modified BSD | `https://pypi.org/project/jsonpointer/3.1.1/` |
| jsonschema | 4.26.0 | MIT | `https://pypi.org/project/jsonschema/4.26.0/` |
| jsonschema-specifications | 2025.9.1 | MIT | `https://pypi.org/project/jsonschema-specifications/2025.9.1/` |
| lark | 1.3.1 | MIT | `https://pypi.org/project/lark/1.3.1/` |
| python-dateutil | 2.9.0.post0 | Apache-2.0/BSD dual license | `https://pypi.org/project/python-dateutil/2.9.0.post0/` |
| PyYAML | 6.0.3 | MIT | `https://pypi.org/project/PyYAML/6.0.3/` |
| referencing | 0.37.0 | MIT | `https://pypi.org/project/referencing/0.37.0/` |
| rfc3339-validator | 0.1.4 | MIT | `https://pypi.org/project/rfc3339-validator/0.1.4/` |
| rfc3986-validator | 0.1.1 | MIT | `https://pypi.org/project/rfc3986-validator/0.1.1/` |
| rfc3987-syntax | 1.1.0 | MIT expression; metadata also has Apache classifier | `https://pypi.org/project/rfc3987-syntax/1.1.0/` |
| rpds-py | 2026.6.3 | MIT | `https://pypi.org/project/rpds-py/2026.6.3/` |
| six | 1.17.0 | MIT | `https://pypi.org/project/six/1.17.0/` |
| typing_extensions | 4.16.0 | PSF-2.0 | `https://pypi.org/project/typing-extensions/4.16.0/` |
| tzdata | 2026.3 | Apache-2.0 | `https://pypi.org/project/tzdata/2026.3/` |
| uri-template | 1.3.0 | MIT | `https://pypi.org/project/uri-template/1.3.0/` |
| webcolors | 25.10.0 | BSD-3-Clause | `https://pypi.org/project/webcolors/25.10.0/` |

No incompatible or unverified runtime dependency was substituted.

## 6. Schema and contract evidence

Measured results:

```text
JSON Schema files: 11
unique $id values: 11
local $ref occurrences: 101
remote $ref occurrences: 0
Draft 2020-12 check_schema: PASS
FormatChecker valid offset date-time: true
FormatChecker rejects date-only as date-time: true
constraint-parse output_payload_sha256 occurrences: 0
trip-card non-rendering contract exists: true
```

The 11 JSON schemas are common, fixture-case, and nine machine-artifact
schemas. `trip-card.html` is represented only by the approved non-rendering
contract. WU1 did not implement HTML rendering.

The implementation requires explicit `BundleClosure` and
`root_artifact_id`; it does not select a first document, newest timestamp,
filename, or city-specific branch. `ARTIFACT_ONLY` records the limited
validation mode. `CLOSED` computes the explicit root-reachable closure,
resolves registered artifact/entity/local/plan-version references, and rejects
unreachable extras.

WU1 validates evidence structure only. It does not implement evidence truth,
five-state mapping, feasibility, proof correctness, conflict minimization,
route planning, or replan optimality.

## 7. Artifact-schema red to green

Exact command for all schema red/green runs:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation -v
```

| Boundary | Tests | Passed | Failures | Errors | Exit |
|---|---:|---:|---:|---:|---:|
| C3 original red | 63 | 5 | 0 | 58 | 1 |
| C3.1 valid red baseline | 63 | 5 | 0 | 58 | 1 |
| first C4 implementation run | 63 | 61 | 2 | 0 | 1 |
| C3.2 valid red baseline | 63 | 5 | 0 | 58 | 1 |
| C4 green | 63 | 63 | 0 | 0 | 0 |

All 58 C3/C3.1/C3.2 errors were the approved public-interface
`NotImplementedError`. Import, path/file, dependency, Schema syntax, malformed
test construction, assertion, and unexpected exceptions were all zero.

### 7.1 C3.1 approved correction

The original CS-03 test incorrectly placed downstream `violations` in a
plan-root `CLOSED` bundle. C3.1 changed only the test bundle to the six
plan-root-reachable artifacts: request, constraint-parse, constraints,
candidates, evidence, and plan. It did not alter the test name, assertion,
Schema, validator, or product contract. C3 was not rewritten.

### 7.2 C3.2 approved correction and scoped stash

The first C4 run correctly reported the appended duplicate candidate at
`/payload/candidates/2/candidate_id`; BASE-02 incorrectly expected index 1.
BASE-04 also exposed artifact-reference ordering and was corrected in the
implementation without changing its test.

The uncommitted C4 validator was stored using the approved single-path stash:

```powershell
git stash push -m "wu1-c4-before-c3.2-test-correction" -- src/trip_decider/schema_validation.py
```

The stash contained only `src/trip_decider/schema_validation.py`. C3.2 changed
only one JSON Pointer in `tests/test_schema_validation.py`; C3/C3.1 were not
rewritten. After C3.2, the exact command re-established 63/5/0/58. The stash
was applied, remained as recovery evidence, and the same command produced
63/63/0/0. After C4 commit and a one-file comparison, stash
`b8135403f1f184c41f4d868940a281ca83368cf1` was dropped. Final stash list is
empty.

## 8. Fixture-validator red to green

Exact command for C5/C6:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation -v
```

| Boundary | Total | Schema passed | Fixture passed | Fixture errors | Exit |
|---|---:|---:|---:|---:|---:|
| C5 red | 82 | 63 | 0 | 19 | 1 |
| C6 green | 82 | 63 | 19 | 0 | 0 |

All 19 C5 errors were the approved fixture-validator `NotImplementedError`;
failures and unexpected exceptions were zero. C6 used the identical command
and made all 82 tests green. The six Plan public interfaces contain zero
reachable `NotImplementedError`.

The fixture tests cover both closure modes, exact root forwarding, order
independence, missing/invalid root, safe relative paths, UTF-8/LF, exact file
hash, expected Schema identity, add/remove/replace single mutations, exact
expected-error matching, missing mutation target, invalid pointer, and
deterministic directory discovery.

## 9. C7 verification-entry history

### C7 Initial Verification Attempt

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu1.ps1
```

- exit code: 1;
- unittests: 82/82 passed;
- failure stage: starting fixture validation;
- failure: Python `SyntaxError`;
- cause: Windows PowerShell 5.1 corrupted quotes in the multiline source passed
  through `python -c`;
- C7 commit did not yet exist;
- validator/Schema/test/Plan changes: 0.

The failed script SHA256 was
`1C9BBD7F2239C7B597BA36826ADB6A873B260DBBF5CC6D42E049295F23F64394`;
its computed Git blob was `ab750c64281f77442686c1d1e83f9ea58858bc0c`.
This was a transport failure before fixture contract execution, not a fixture
contract failure.

### C7 First Approved Transport Correction

Hugin approved changing only the call boundary to an argument array. The
multiline Python body and all validation logic remained unchanged. The
corrected script SHA256 was
`F0E590D8D33AFC748E97B11B9F86797C7C04AB49E3188B3513CCE9BADDE641F7`.
No commit was created.

### C7 First Corrected Acceptance Attempt

- exact command: unchanged;
- exit code: 1;
- unittests: 82/82 passed;
- failure: the same `SyntaxError` before fixture contract execution;
- cause: PowerShell 5.1 still corrupted multiline `-c` source under argument
  array splatting;
- validator/Schema/test/fixture data/Plan failures: none reported;
- C7 commit still did not exist.

Execution stopped and requested a second written ruling.

### C7 Second Approved Transport Correction

Hugin explicitly superseded the no-second-correction restriction and approved
only replacing `python -c` transport with a random system-temporary `.py`
file:

- path starts at `[System.IO.Path]::GetTempPath()`;
- filename uses a random GUID and `.py`;
- repository-inside-path check hard-fails;
- encoding is UTF-8 without BOM;
- interpreter remains the project `.venv` Python;
- `finally` removes the temporary file;
- Python exit code is propagated unchanged;
- no repository temporary Python file is created.

The embedded Python body SHA256 was measured before and after:

```text
9AFCF70CC6EC38B13E1B7A2EA8C454EBD7863BC188681C26D8A708CB68BE979D
```

The identical hash proves the embedded validation body did not change. The
final script SHA256 is
`A8BC52F8A648FF40029BF369768F36C04200832DD8DFC429154F8CBA028471FE`.
Searches for `python -c`, pipe-to-stdin transport, `Invoke-Expression`, and
nested `powershell -Command` returned zero.

### C7 Second Corrected Acceptance Run

The exact Plan command exited 0:

```text
unittests: 82 passed, 0 failures, 0 errors
fixture directories: 6
documents: 38
dirty cases: 6
schema files: 11
Python SyntaxError: 0
fixture validation errors: 0
temporary trip-decider-wu1-*.py residue: 0
```

Every fixture printed `status: PASS`, `bundle_closure: closed`, its explicit
actual envelope root, document count, and dirty count. The run required no
validator, Schema, test, fixture-data, Plan, or dependency change.

C7 was then committed as `5ed0c32` with exactly 14 approved paths and 803
insertions.

### C8 Independent Rerun

Before creating this Review, the exact same command again exited 0 with:

```text
82 passed, 0 failures, 0 errors
6 fixture directories
38 documents
6 dirty cases
all closures closed
all roots passed
temporary trip-decider-wu1-*.py residue: 0
```

The result is independent of C7's successful run and did not modify the
worktree.

## 10. Formal fixture evidence

| Fixture | Root envelope | Root type | Closure | Documents | Dirty |
|---|---|---|---|---:|---:|
| `fixture_01_feasible` | `urn:uuid:00000007-0000-4000-8000-000000000007` | post-plan violations | closed | 7 | 1 |
| `fixture_02_direct_conflict` | `urn:uuid:00000008-0000-4000-8000-000000000008` | pre-plan violations | closed | 6 | 1 |
| `fixture_03_uncertain_dependency` | `urn:uuid:00000007-0000-4000-8000-000000000007` | post-plan violations | closed | 7 | 1 |
| `fixture_04_replan_stability` | `urn:uuid:0000000a-0000-4000-8000-00000000000a` | plan-diff | closed | 8 | 1 |
| `fixture_05_evidence_state_mapping` | `urn:uuid:00000005-0000-4000-8000-000000000005` | evidence | closed | 3 | 1 |
| `fixture_06_no_plan_found_not_infeasible` | `urn:uuid:00000007-0000-4000-8000-000000000007` | post-plan violations | closed | 7 | 1 |

An independent manifest/content pass found exactly one embedded envelope whose
`artifact_id` equals each manifest root. Total root hits: 6/6.

All data is synthetic deterministic and derived from the frozen structural
contract. No real Jiangxi anchor, retrieved fact, route, proof, feasibility
result, evidence mapping, or replan optimum was invented or claimed.
`behavior_expected` is stored as opaque deferred specification and was not
executed.

## 11. Error model and ten stable codes

`ValidationProblem` has the seven frozen fields:

```text
error_code
artifact_path
json_pointer
schema_rule
expected
actual_type
message
```

The problem builder exposes only a safe type for actual input and fixed
project messages. Third-party exception text and input values are not copied
into the public problem object. Ordering is deterministic by artifact path,
JSON Pointer, and error code.

Eight stable codes are exercised directly by the 63 committed schema tests.
The two remaining codes were independently probed with synthetic deterministic
in-memory inputs during Review:

| Code | Evidence |
|---|---|
| `DUPLICATE_DEFINITION_ID` | committed test |
| `UNRESOLVED_REFERENCE` | committed tests |
| `REFERENCE_KIND_MISMATCH` | Review probe returned `/payload/request_ref`, `referenceIdentity` |
| `DUPLICATE_ARTIFACT_ID` | committed tests |
| `DUPLICATE_LOCAL_SOURCE_ID` | committed test |
| `UNRESOLVED_LOCAL_SOURCE_REFERENCE` | committed test |
| `UNRESOLVED_PLAN_VERSION_ENTITY` | committed tests |
| `AMBIGUOUS_PLAN_VERSION_ENTITY` | Review probe returned `/payload/previous_plan_id`, `planVersionReference` |
| `UNRESOLVED_BUNDLE_ROOT` | committed test |
| `UNEXPECTED_BUNDLE_ARTIFACT` | committed tests |

The two probes exited 0 only when the exact expected code was returned.

### Known exit/output gap

Plan §10.3 is not fully implemented by the complete entry:

- success 0, fixture 3, input/encoding 4, and internal/registry 5 are present;
- no artifact-validation invocation exposes exit code 2;
- fixture failure JSON currently serializes only four of the seven frozen
  fields;
- fixture failure JSON uses standard output rather than the required JSON
  Lines on standard error.

This is an implementation gap, not a claim that tested valid inputs failed.

## 12. R10, fallback, secret, and scope review

Measured scans over source, Schema, tests, fixtures, script, project metadata,
and lock:

```text
infer_: 0
guess_: 0
silent_fallback: 0
warning-as-pass / --lenient: 0
reachable NotImplementedError in src: 0
credential-pattern matches: 0
city-specific names/branches in src and test data: 0
High德/AMap/HTTP client integration: 0
```

The evidence source discriminator permits only webpage/official notice, API
response, and direct observation variants. `model` is a dirty fixture value
that must fail; an LLM is not modeled as a fact source.

No API was called. No real key, fake key, Web collector, route planner,
feasibility solver, proof checker, replan optimizer, HTML renderer, Web UI,
Jiangxi itinerary, or v1 destination-discovery implementation exists.

Commit message/diff checks:

- C3.1 only corrected CS-03 data;
- C3.2 only corrected one BASE-02 JSON Pointer;
- C4 only changed artifact validation;
- C5 only added fixture tests;
- C6 only changed fixture validation;
- C7 only added the 14 formal fixture/script paths;
- C8 only adds this Review.

## 13. Verification-entry requirement audit

Plan §10.2 requires eight properties inside the single C7 entry.

| Requirement | Current script |
|---|---|
| use project `.venv` Python, no global fallback | present |
| prove interpreter and site-packages are inside `.venv` | incomplete; constructed path is checked for existence, runtime identity is not asserted |
| validate lock installation state | absent |
| validate Schema metadata/registry | present |
| run unittest discovery | present |
| run six explicit-root fixture contracts | present |
| run scope/fallback/secret/frozen-hash checks | absent |
| nonzero on implemented-stage failure | present |

Literal occurrence checks in the committed script returned zero for
`requirements.lock`, `pip check`, `sys.executable`, `site-packages`,
`git status`, `git diff`, `Get-FileHash`, `SHA256`, `secret`,
`silent_fallback`, `infer_`, `guess_`, `PLAN.md`, and the WU1 Plan path.

The missing checks were all run separately and passed during Review:

- runtime lock versus installed runtime packages: zero differences;
- `pip check`: pass;
- interpreter/prefix/site-packages: project `.venv`;
- 36-path scope: pass;
- secret and fallback scans: zero;
- eight frozen input hashes: exact match.

Those external commands do not satisfy the requirement that the single entry
perform them.

## 14. Twenty completion criteria

1. ✓ Handbook fetch/reconciliation and 8/8 mandatory `origin/main` reads are
   recorded; local/origin HEAD match and worktree is clean.
2. ✓ Python target, two direct dependencies, 19 transitive dependencies,
   precise versions, installed license files, official records, and Windows
   Python 3.11 compatibility were measured.
3. ✓ Runtime lock was produced and replayed in a cleared project `.venv`;
   global freeze was not used and runtime lock/environment differ by zero.
4. ✓ Nine machine-artifact schemas and the trip-card contract exist;
   constraint-parse has one envelope payload-hash authority and rejects the
   removed self-referential field.
5. ✓ Envelope, canonical payload hash, unknown-major and hash mismatch hard
   failures are implemented; request/parse/constraints use complete artifact
   references.
6. ✓ Source is a closed union; model/LLM is not a source; candidate source refs
   remain provenance and evidence sources are fact-local.
7. ✓ Origin and constraint-target unions are closed; request-scope targets do
   not invent future plan entities.
8. ✓ Evidence subjects, immutable candidate snapshots, estimate structure,
   proof presence, and four plan states are structurally represented.
9. ✗ Strict loading and stable seven-field problem objects exist, but the
   complete entry does not expose the full §10.3 exit/output contract: exit
   code 2 is absent and fixture failure JSONL is incomplete/on stdout.
10. ✓ Plan-version resolution, explicit closure/root, root-reachable CLOSED
    validation, extra-artifact rejection, and all ten frozen codes are
    implemented and verified by committed tests or the two explicit Review
    probes.
11. ✓ Violations stage/status, explicit `BundleClosure`, root-aware
    `ValidatedBundle`, and all six public interfaces are implemented with zero
    reachable `NotImplementedError`.
12. ✓ Six README/case pairs use closed closure, fixed actual roots, and minimal
    root-reachable document sets; C7 changed no validator, Schema, or test.
13. ✓ Every formal fixture has one clean/dirty pair with exact
    code/pointer/rule expectation.
14. ✓ `behavior_expected` is separate and WU1 neither executes nor claims its
    business behavior.
15. ✓ Schema tests used one exact command for valid red/green, ran 63 cases
    including at least the 47 preregistered cases, and never invoked the full
    C7 script.
16. ✓ Fixture tests used one exact command for valid red/green, cover both
    closure modes and explicit root, and preserve all 63 Schema tests.
17. ✓ Tests use multiple concrete field and exact error assertions; expected
    values are specification-authored rather than generated by validators.
18. ✓ Separate R10/silent-fallback/warning/secret scans are zero; no allowed
    hit is misreported as zero.
19. ✓ No business planner/API/HTML/v1 implementation exists; frozen project
    inputs and handbook remain unchanged; no push occurred.
20. ✗ The C7 second corrected acceptance run and C8 identical rerun are green,
    and the Hugin-approved transport limitation remains recorded. However,
    `verify_wu1.ps1` is not the full Plan §10.2 entry because lock, runtime
    identity, scope, fallback, secret, and frozen-hash checks are absent. This
    additional limitation was not covered by the transport-correction ruling.

The prescribed transport-history warning also remains:

> ⚠ 已知限制 — 首次 C7 完整验证因 PowerShell→Python 参数传递缺陷失败；
> 第一次获批参数数组修正仍失败；经第二次书面批准改用系统临时 UTF-8
> 无 BOM Python 文件后，第二次 C7 验收运行和 C8 相同命令复核均 green。

Because criteria 9 and 20 are incomplete for reasons beyond the approved
transport warning, `READY_FOR_HUGIN_REVIEW` would overstate WU1 completion.

## 15. Final status

INCOMPLETE
