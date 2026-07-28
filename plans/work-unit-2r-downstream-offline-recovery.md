# WU2R-DOR · Downstream Offline Recovery Plan

Plan version: v0.1

Status: PENDING_HUGIN_APPROVAL

Prepared on: 2026-07-28

Execution authority: not granted

## 1. Objective and non-goals

WU2R-DOR consumes the committed `jiangxi_multi_identity_smoke` anchor and
implements the existing public entry:

```python
run_wu2_recovery(
    replay_root: Path,
    output_root: Path,
) -> ValidationResult[RecoveryRunSummary]
```

Its complete production responsibility is:

```text
committed anchor
→ existing Resume replay boundary
→ validated candidate result
→ four deterministic runtime outputs
→ RecoveryRunSummary
```

Historical state remains:

```text
WU2:          BLOCKED
WU2R:         BLOCKED
WU2R-FER:     APPROVED
WU2R Resume:  APPROVED by the current Hugin instruction
decision:     WU2R_ACQUISITION_COMPLETED
```

Non-goals:

- no acquisition, network, new data, source, fixture, or decision;
- no identity resolver, ranking, recommendation, evidence, route,
  feasibility, planner, destination discovery, HTML, or UI;
- no Schema, artifact type, dependency, production module, or second Recovery
  entry;
- no restoration of old WU2/WU2R and no WU3/WU5 work.

## 2. Measured baseline and handbook

Repository gate measured:

```text
root: <repo>
branch: main
HEAD: 276221d860950e6940d344fe2889312104da4290
worktree entries: 0
remotes: 0
stashes: 0
```

Existing read-only verification command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu2r_resume.ps1 -Mode Success
```

Measured result:

```text
tests: 180/180
schemas: 11
fixture directories/documents/dirty cases: 7/40/7
network attempts: 0
```

Plan-stage data-service calls are 0. No runtime output was created.

Handbook fixed path:

```text
<handbook>
```

Network is prohibited before approval, so the Plan stage did not fetch. It
read the existing local `origin/main` reference:

```text
local/origin:
6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
branch: main
worktree entries: 0
```

Read in full from `origin/main`: `STATE.md`, `INDEX.md`, `SUMMARY.md`,
`tools/context-injection.md`, and the R10, PER, Scope, and Fixture-first rule
files under `principles/`.

Effects: R10 requires measured hashes/counts and hard failure; PER blocks
Execute pending approval; Scope fixes five paths; Fixture-first requires the
six-error red before implementation. No handbook file is copied or modified.

## 3. Frozen inputs

Approved mutable baseline:

```text
src/trip_decider/recovery.py
8105424CAEBD020BDAFBA4048477BF92846AE2B27090CB3EFAFC7C40B6183614
```

The following 15 paths are immutable:

| Path | SHA256 |
|---|---|
| `docs/reviews/work-unit-2r-resume-review.md` | `BF4AEC6B68CF69EB9DA04E2119E0AD5F3880B610A41CC8418CFF8D64CDA6E365` |
| `docs/wu2r-resume-acquisition-decision.md` | `DFA53FF72699752DCEE18B1E5BB736479F1351B24E705A55A24C2A9FB13A6CE0` |
| `docs/wu2-recovery-source-and-capture.md` | `B34ED5EB0FA570A11E0B43E9F0A714C30F4A44FC53EE3D5D38302074B1DE9CA1` |
| `src/trip_decider/resume_acquisition.py` | `86229BA52695D3B4725DFDB54D709C8D79580DD35B8FCEE010D3AD59B7D0A6AE` |
| `src/trip_decider/acquisition_evidence.py` | `BF7F25FC4A41C8085431450501B86866A7757B125A208363AA5113AD5F82FEDB` |
| `src/trip_decider/adapters/open_data_poi.py` | `F39EBF86B682EDECF182F6148178AEBA434A287B34A270FE84D3FAEE8F80944B` |
| `tests/test_wu2_recovery.py` | `8D1341E4A57EA008152059A670CF4876EA48E8D118DF6E82EF15850549E4F43E` |
| `tests/test_wu2r_resume.py` | `88F0CD41F69BCDB535798B8329AFD02297F305E7DE95FCE5F73F219941953B01` |
| `fixtures/jiangxi_multi_identity_smoke/README.md` | `49049A94B0DF039C430506BBA9827B599F417CF3A97AEB069D3099AEE9F59223` |
| `fixtures/jiangxi_multi_identity_smoke/case.json` | `6052797C4FE43B0E1BE216187EAD6AC10FB1617F07CD7784CF81F8403843F3C8` |
| `fixtures/jiangxi_multi_identity_smoke/replay.json` | `5D8086E128FE1B33FD0314151C49256A459DB401233B1C548843791AFAC1919A` |
| `fixtures/jiangxi_multi_identity_smoke/osm-pois.json` | `41520443BB370919F184CF46441DB897A809EB1B86119B7CF2B6007F20A5B382` |
| `requirements.lock` | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` |
| `pyproject.toml` | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` |
| `.gitignore` | `A6F5AFD044D06F8E04D1CC9DDE26B25D186A0CE9046C0ED50F7ADF734E5FC2A7` |

All 11 Schema hashes remain the baselines recorded in the Resume Review.
The verifier compares them byte-for-byte.

## 4. Interface and reuse decision

Frozen public surface:

- function name, parameters, and return annotation;
- `RecoveryRunSummary` name and its nine fields;
- seven-field `ValidationProblem`;
- all six Recovery error codes/messages.

Summary fields remain `run_id`, four output Path fields, `candidate_count`,
`seed_status_counts`, `network_attempts`, and `output_sha256`.

Only private helpers may be added inside `recovery.py`.

`replay_root` is a `Path` containing exact anchor filenames:

```text
README.md
case.json
replay.json
osm-pois.json
```

The implementation uses exact paths, never a “latest” scan, first document,
or inferred root. It must:

1. strictly load the two controls and reject BOM, duplicate keys, non-finite
   values, unsafe paths, malformed shape, and missing files;
2. resolve exactly one embedded `candidates.json`, then verify its file and
   canonical payload hashes;
3. read only the declared immediate-child raw file and reconstruct exact
   query/form bytes from `docs/wu2-recovery-source-and-capture.md`;
4. build explicit metadata/context and invoke
   `replay_wu2r_resume_anchor(...)` with fixture seed order;
5. require empty problems/zero network, then compare Candidate, seeds, facts,
   counts, and refs to independent fixture expectations before writing.

The source document is needed because the fixture stores query/request hashes,
not a duplicate of those bytes. Its hash is frozen above.

Forbidden duplication:

- no raw OSM parser in Recovery;
- no direct adapter normalization;
- no candidate ID generation;
- no seed matching or record-local fact generation;
- no query/request/response hash validation copied from Resume;
- no inferred provider, CRS, seed order, metadata, or artifact identity.

Resume rejection is mapped without copying exception text or matching message
strings. Unexpected programming or OS errors propagate after rollback rather
than being falsely labeled as invalid input.

## 5. Output contracts

Success layout:

```text
<output_root>/
  candidates.json
  seed-accounting.json
  record-local-facts.json
  run-summary.json
```

`candidates.json` is the existing Candidate artifact returned by Resume. Its
JSON object must equal the unique independently authored Candidate artifact
embedded in `case.json`; no new Schema/type is introduced.

`seed-accounting.json` is a runtime control document with
`schema_version=wu2r-downstream-seed-accounting/1.0`, `run_id`, and ordered
`seed_matches`. Each record has exactly `seed`, `status`, and
`candidate_refs`; status is `matched`, `ambiguous`, or `unmatched`.

`record-local-facts.json` is a runtime control document with
`schema_version=wu2r-downstream-record-local-facts/1.0`, `run_id`, and
`record_local_facts`. Each fact has exactly `candidate_id`, `provider_name`,
`provider_record_type`, `provider_record_id`, `categories`, `location`, and
`source_refs`.

Facts sort by `candidate_id`. No preferred identity, rating, recommendation,
intent, or correctness claim is allowed.

`run-summary.json` is a runtime control document with:

- `schema_version=wu2r-downstream-recovery-run/1.0`, `run_id`;
- `input_fixture_identity`: case ID/version, root artifact ID, and actual
  case/replay/raw hashes;
- `output_paths`: the four fixed relative filenames;
- candidate count and matched/ambiguous/unmatched counts;
- `network_attempts`, `output_sha256`;
- `completion_status=completed`.

Output documents contain relative logical paths, never machine-absolute paths.

### Dataclass reconciliation

The frozen dataclass cannot gain `input_fixture_identity` or
`completion_status`; the disk summary is therefore a strict superset.
Consistency means:

- every dataclass field has an exact disk counterpart;
- returned Paths equal `output_root` plus disk relative paths;
- run ID, counts, network count, and hash map are exact;
- a value exists only with disk `completion_status == completed`;
- tests independently assert both disk-only fields.

Approval accepts this reconciliation. If field-for-field structural identity
is required, Execute blocks because public-field changes are forbidden.

## 6. Determinism, hashes, and transaction

Reuse `canonical_payload_sha256(...)` for Candidate payload integrity.
Complete output bytes use one private standard-library rule:

```python
(
    json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    + "\n"
).encode("utf-8")
```

Thus every output is UTF-8, BOM-free, finite JSON with sorted object keys,
compact separators, and one trailing LF.

Ordering:

- candidates: existing Resume artifact order;
- seeds: fixture order;
- facts: ascending candidate ID.

`output_sha256` contains actual-byte hashes for:

```text
candidates.json
seed-accounting.json
record-local-facts.json
```

The summary cannot contain its own actual-byte hash without recursion. The
verifier independently hashes completed `run-summary.json` bytes and compares
that hash across clean roots.

All validation, replay, comparisons, serialization, and non-summary hashing
complete before final writes.

`output_root` rules:

- missing root may be created;
- existing empty directory is allowed;
- file, non-directory link, or non-empty directory hard-fails;
- no existing entry is overwritten/deleted.

Each output uses a same-directory UUID temp, flush, `fsync`, and `os.replace`.
Write order is candidates, seeds, facts, then summary as commit marker.

Any failure removes invocation-created temps/finals. A caller-supplied empty
root remains; a function-created root is removed only when empty. Installed
bytes are reread and checked before success.

## 7. Stable failures

No error code/message changes.

| Condition | Existing code |
|---|---|
| fixture/control/path/output-root violation | `RECOVERY_REPLAY_INVALID` |
| independent Candidate mismatch | `RECOVERY_CANDIDATE_ARTIFACT_INVALID` |
| nonzero network count | `RECOVERY_NETWORK_ATTEMPTED` |
| installed output hash mismatch | `RECOVERY_REPLAY_HASH_MISMATCH` |

Resume hash/replay rejection maps to `RECOVERY_REPLAY_INVALID`; Recovery does
not repeat validation or classify from exception text. Problems use fixed
pointers/rules and safe types, never actual values, bodies, credentials, or
exception messages.

Unexpected storage/programming errors are re-raised after transaction cleanup.

## 8. Exactly six offline tests

Create only:

```text
tests/test_wu2r_downstream_recovery.py
```

The module declares the committed real-anchor source, independent expected
values, coverage, and non-coverage. All cases use system temp directories,
patch network creation to fail, and never modify repository fixtures.

### DR01 valid anchor emits four files

Assert typed success, exact filenames, strict UTF-8 JSON/no BOM, path mapping,
candidate count 7, and network count 0.

### DR02 Candidate equals independent artifact

Assert exact object equality to embedded `candidates.json`, root/artifact IDs,
canonical payload hash, seven provider identities, and no new type/field.

### DR03 seed accounting equals replay expectations

Assert all four records/order/refs, counts 2/1/1, ref resolution, and no
placeholder for unmatched.

### DR04 facts and hashes are deterministic across roots

Run two clean roots. Assert independent fact equality/order, pairwise-equal
bytes for all four outputs, equal external summary hashes, actual installed
hashes, and returned/disk summary consistency.

### DR05 tampered raw/replay hash fails with zero outputs

Copy the fixture to system temp, alter one raw byte or declared replay hash,
and assert no value, one stable problem, zero output entries, unchanged repo
fixture hashes, and zero network. Expected values never come from the SUT.

### DR06 network forbidden; non-empty root preserved

Assert valid replay makes zero network calls. Add a sentinel to a second root;
assert `RECOVERY_REPLAY_INVALID`, byte-identical sentinel, and no other
output/temp.

## 9. Red → Green and regression

C1/C2 character-identical command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2r_downstream_recovery -v
```

Required C1 red:

```text
tests: 6
passed: 0
failures: 0
errors: 6
cause: run_wu2_recovery explicit NotImplementedError
network attempts: 0
```

Import, dependency, syntax, path, fixture, malformed-test, network, and other
errors must each be zero. C2 changes only `recovery.py`, not tests.

Required C2 green:

```text
tests: 6
passed: 6
failures: 0
errors: 0
network attempts: 0
```

Full target:

```text
existing tests: 180
DOR tests: 6
total: 186 passed
failures/errors: 0/0
fixtures/documents/dirty cases: 7/40/7
network attempts: 0
temporary residue: 0
```

## 10. Verification entry

Create:

```text
scripts/verify_wu2r_downstream_recovery.ps1
```

Offline-only checks:

1. project `.venv`, prefix/site-packages, exact lock, and `pip check`;
2. complete 186-test module list;
3. all 11 Schema and 15 immutable-input hashes;
4. anchor case/replay/raw and query/request hashes;
5. one real offline Recovery under a random system-temp root;
6. four outputs, relative paths, actual hashes, and summary consistency;
7. zero network and unchanged 7/40/7;
8. exact five-path scope and R10/credential/provider/fallback scans;
9. helper/output cleanup in `finally`;
10. zero system-temp and repository residue.

Any Python helper uses a GUID system-temp file, UTF-8 without BOM, project
Python, and `finally` deletion. No repository temp Python, `python -c`,
expression evaluation, or nested shell command is allowed.

The script does not change the old verifier or create repository runtime
output.

## 11. Exact five-path scope

Allowed:

```text
plans/work-unit-2r-downstream-offline-recovery.md
src/trip_decider/recovery.py
tests/test_wu2r_downstream_recovery.py
scripts/verify_wu2r_downstream_recovery.ps1
docs/reviews/work-unit-2r-downstream-offline-recovery-review.md
```

A sixth repository path blocks Execute.

Protected: `PLAN.md`, `schemas/`, `fixtures/`, Resume, FER, adapters,
validators, acquisition harness, old Resume verifier, existing Recovery and
Resume tests, dependency/lock/config files, handbook, and user/system
configuration.

No dependency is installed or changed.

## 12. Five linear commits

| Commit | Exact message | Only path | Gate |
|---|---|---|---|
| C0 | `docs: record downstream offline recovery plan` | approved Plan | approved hash exact |
| C1 | `test: add failing downstream recovery cases` | new DOR test | exact six-error red |
| C2 | `feat: implement downstream offline recovery` | `recovery.py` | same command 6/6; full 186 |
| C3 | `chore: add downstream recovery verification entry` | new verifier | entry 186 and 7/40/7 |
| C4 | `docs: prepare downstream offline recovery review` | new Review | independent entry green |

No amend, squash, reset, rebase, or history rewrite.

## 13. Review and exactly 12 completion criteria

C4 Review records Git log/diff, five paths, Plan/frozen/Schema/handbook
hashes, red/green, four outputs and actual hashes, independent expectations,
rollback, non-empty-root preservation, zero network/residue, and R10 scans.
It does not reproduce coordinates or a raw provider body.

Exactly 12 criteria:

1. Start HEAD, branch, worktree, remote, stash, and Plan hash are exact.
2. Handbook and frozen inputs remain unchanged.
3. WU2/WU2R historical states are not rewritten.
4. Only the committed anchor is consumed; data calls are 0.
5. Recovery reuses Resume replay and copies no adapter/candidate/seed/fact/raw
   validation logic.
6. Four outputs are complete, deterministic, and hash-readable.
7. Candidate equals the independent embedded expectation.
8. Seeds and record-local facts equal independent replay expectations.
9. Failure leaves no partial output; a non-empty root is not overwritten.
10. C1 is exact six-error red; C2 is 6/6 green with the same command.
11. Regression is 186/186; fixtures remain 7/40/7; network/residue are 0.
12. Review records Git, hashes, outputs, red/green, scope, and boundaries,
    then stops.

Review marks each `✓ 已完成`, `⚠ 已知限制`, or `✗ 未完成`; it adds no
thirteenth criterion.

Allowed final status:

```text
READY_FOR_HUGIN_REVIEW
BLOCKED
INCOMPLETE
```

## 14. Blocking and approval gate

Stop before C0 if branch, HEAD, worktree, remote/stash, Plan hash, Resume
Review/decision, anchor, frozen input, Schema, or handbook differs.

Stop during Execute if:

- Resume replay cannot be reused without copying forbidden logic;
- exact return/disk consistency requires a public dataclass change;
- fixture, Resume, adapter, Schema, validator, dependency, old test/policy,
  decision, or history must change;
- a sixth path, network, new source, or generated expected value is needed;
- C1 is not six explicit `NotImplementedError` errors;
- C2 needs a test change;
- rollback cannot guarantee zero partial output;
- credential, raw-body copy, coordinate list in Review, or capability
  overclaim is required;
- WU3/WU5, route, evidence, planner, push, remote, PR, or history rewrite is
  needed.

On a blocker: stop, preserve evidence, do not expand scope, and report
`BLOCKED` or `INCOMPLETE`.

Plan-stage output is only this file. Before approval there is no implementation
or test change, commit, runtime output, fixture change, data call, or WU3/WU5
work.

Execute requires:

```text
批准执行 Work Unit 2R Downstream Offline Recovery
```

Until then:

```text
PENDING_HUGIN_APPROVAL
```
