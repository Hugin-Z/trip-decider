# Work Unit 2R Downstream Offline Recovery Review

Review status: `READY_FOR_HUGIN_REVIEW`

Work unit: `WU2R-DOR · Downstream Offline Recovery`

Approved Plan:

```text
plans/work-unit-2r-downstream-offline-recovery.md
Version: v0.1
SHA256: 1D671D9C1777755305526A05F82CEBB4279D4B9FA743762A0769C825E4770F8D
Lines: 545
Bytes: 17980
```

This document preserves the original WU2R-DOR C0-C4 Review and adds the
subsequently approved boundary-remediation evidence. It does not reinterpret
the old WU2 or WU2R attempts, authorize WU3/WU5, acquire data, or implement
routing, evidence rating, recommendation, or planning.

## 0. Boundary remediation status history

The original C4 commit
`3f1c636c8d2cedc799f24f870efd4511bbb1dbcf` declared
`READY_FOR_HUGIN_REVIEW`. A final audit after that commit found that Recovery
computed and compared the actual response SHA256 with replay declarations
before calling Resume replay. The original statements that Recovery copied
no response-hash validation and that criterion 5 was complete were therefore
invalid. WU2R-DOR was reclassified as `INCOMPLETE`.

Hugin first approved a narrow correction limited to the test, Recovery, and
this Review. The execution preflight then found that the unchanged verifier
froze the old test/Recovery hashes and allowed only the original 3-5 commit
prefix. Codex stopped before modifying any file and reported `BLOCKED`
instead of producing a verification result that could not pass. Hugin then
supplemented the approval with the verifier's minimal hash and exact
8-or-9-commit gate update.

The remediation history is additive:

```text
0e749257923965f57257b623b1b4d457f0fc61c3 test: require Resume-owned response hash validation
4b811362b275a1d829ec51abf2a6a2f7e271b301 fix: delegate response hash validation to Resume replay
ede70f1ab7b70c026d6edd0ddc2eaa6b2104cbdf chore: update downstream recovery verifier after remediation
R4: docs: correct downstream recovery review after boundary remediation
```

The original C4 Review conclusion is superseded by this later remediation
evidence, while its Git history remains intact.

```text
原C4 Review结论已被后续remediation证据取代，
但其Git历史被完整保留。
```

## 1. Preserved state and execution baseline

The immutable execution gate was checked before C0:

```text
branch: main
start HEAD: 276221d860950e6940d344fe2889312104da4290
worktree: ?? plans/work-unit-2r-downstream-offline-recovery.md
remotes: 0
stashes: 0
Plan SHA256: 1D671D9C1777755305526A05F82CEBB4279D4B9FA743762A0769C825E4770F8D
```

The only worktree entry was the approved Plan. WU2 and the old WU2R remain
historically `BLOCKED`; WU2R Resume remains a later completed acquisition
work unit. This work unit adds a downstream offline replay without amending,
resetting, rebasing, squashing, or reinterpreting those histories.

The preserved state tokens remain in the frozen Resume decision:

```text
WU2:  BLOCKED
WU2R: BLOCKED
WU2R_ACQUISITION_COMPLETED
```

No remote was created, no stash was retained, and no push or PR occurred.

## 2. Git evidence

Linear history through C3:

```text
c04b104184c421c0478cbf3e0085c9f1b4d25caa docs: record downstream offline recovery plan
f469301be2b45b71d36a1471152b8c5e33c2af16 test: add failing downstream recovery cases
e58acc5fd69555c37561be9001c52819d2861ceb feat: implement downstream offline recovery
a017bf331fc6ae236ac94998db4576f45b9def29 chore: add downstream recovery verification entry
```

C4 is this document and uses the approved message:

```text
docs: prepare downstream offline recovery review
```

The C0-C3 diff from the approved start was independently read in full:

```text
git diff --no-ext-diff 276221d860950e6940d344fe2889312104da4290..HEAD --
exit code: 0
diff lines: 2545
diff characters: 92790
```

Stat before C4:

```text
plans/work-unit-2r-downstream-offline-recovery.md | 545 ++++++++++++
scripts/verify_wu2r_downstream_recovery.ps1       | 602 ++++++++++++++
src/trip_decider/recovery.py                      | 956 +++++++++++++++++++++-
tests/test_wu2r_downstream_recovery.py            | 386 +++++++++
4 files changed, 2487 insertions(+), 2 deletions(-)
```

C4 adds only this Review, producing the exact five-path approved scope:

```text
plans/work-unit-2r-downstream-offline-recovery.md
src/trip_decider/recovery.py
tests/test_wu2r_downstream_recovery.py
scripts/verify_wu2r_downstream_recovery.ps1
docs/reviews/work-unit-2r-downstream-offline-recovery-review.md
```

No Schema, fixture, Resume, FER, adapter, validator, existing test,
dependency, source-policy, acquisition, or handbook path changed.

## 3. Handbook, frozen inputs, and Schema hashes

Handbook remained read-only:

```text
fixed path: <handbook>
local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree entries: 0
```

All 15 immutable inputs matched:

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

All 11 Schema hashes matched:

| Schema | SHA256 |
|---|---|
| `candidates.schema.json` | `3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2` |
| `common.schema.json` | `83FE17127A545D168A16F58911564E53D2E17AFF826B6D34437D873ECF8E75BE` |
| `constraint-parse.schema.json` | `0D41493B52B6178AEE8DE44B2F3607B193B62C263AD79DEF380B638B22B400A4` |
| `constraints.schema.json` | `25069E0DEFBDC03FEA7E92E83EE10F952A31A2B18BDC3678D17786C537EE4473` |
| `evidence.schema.json` | `54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B` |
| `fixture-case.schema.json` | `630E57E7F27A660F388407A8FF1B81D851B8B3A047E5B98DCB70E1920177E45A` |
| `plan.schema.json` | `81EEB5899C33F19DC6FA059C7D447D747E72E355F3084D925FD9410272389BD3` |
| `plan-diff.schema.json` | `37B94FE5E03A73B046D7E6D79BEABF31C4105E50CD54DE520CA6C293AB3E8B43` |
| `previous-plan.schema.json` | `59692D17EB79C7EA2D4A2E2866898DD97A0E49B97834EC8AFC5EAB46A80BEDAC` |
| `request.schema.json` | `BC7F46E9A85CE9697F9BA01FF1506A5B56C161F2F6B5140D91FCF0B100762914` |
| `violations.schema.json` | `C117415030993C24649B17837EC2A35C69A2F1CEC7D923742ABD383BA85B394F` |

WU2R-DOR committed implementation/test/verifier hashes before C4:

```text
src/trip_decider/recovery.py
870FB097B4E9059D7D5DCCAD41A4522B31AB79ACBA7DC961BAD40970E8DB6511

tests/test_wu2r_downstream_recovery.py
1CEAD6C418A19789C0AEABDE2E5CBC461D436D074256A73948B89580D0815E09

scripts/verify_wu2r_downstream_recovery.ps1
6299CD4AB0F312E55DBC91E529D1D4F9FFC9EC20830797DB50B4B5AEA3BA85ED
```

Mechanically measured post-remediation hashes:

```text
src/trip_decider/recovery.py
C0E098DD4AB997727A0EFBCCC9C396AC480DEEB3477DBF4CDCB5E31A34E0D8BA

tests/test_wu2r_downstream_recovery.py
E52AE191B5D244CD810F4E0648459BF7B6F3E4B891B4A0FDDA72E8957133A3FF

scripts/verify_wu2r_downstream_recovery.ps1
BB26BA892ACB6714A295C5A0B9FD283C65F6B7337C179B22FC5A0CB1476F4FFC
```

## 4. C1 red evidence

Character-identical C1/C2 command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2r_downstream_recovery -v
```

The committed C1 test surface produced:

```text
exit code: 1
tests: 6
passed: 0
failures: 0
errors: 6
```

The six failing IDs were DR01-DR06. Every traceback ended at the public
`run_wu2_recovery` stub with:

```text
NotImplementedError: WU2 Recovery offline replay is not implemented
```

Import, dependency, syntax, path, malformed-input, fixture, network, and
other unexpected errors were all 0.

### Pre-commit C1 test-structure correction

The first uncommitted run reported six tests but seven error instances because
DR05 invoked the stub twice under two subtests. The Plan requires exactly six
errors and permits tampering either one raw byte or the declared replay hash.
Before C1 was committed, DR05 was narrowed to the raw-byte variant. This did
not change the test name, failure code, independent expected data, fixture,
public contract, or implementation. The corrected uncommitted test was then
run and produced the exact 6/0/0/6 baseline above. No committed history was
rewritten and no extra correction commit was needed.

## 5. C2 green and implementation boundary

The first implementation attempt returned one pass, two assertion failures,
and three follow-on file errors because the implementation incorrectly
required `behavior_expected` to be an array. The frozen case defines it as an
object. Only `recovery.py` was corrected; no test or fixture changed.

The same C1/C2 command then produced:

```text
exit code: 0
tests: 6
passed: 6
failures: 0
errors: 0
network attempts: 0
```

C2 changed only `src/trip_decider/recovery.py`. It:

- reads only the exact four-file anchor root and strict JSON controls;
- verifies safe immediate-child paths and independent Candidate integrity;
- reconstructs the exact frozen query/form bytes from the frozen source doc;
- calls `replay_wu2r_resume_anchor` for response/provider normalization,
  candidate IDs, seed accounting, and record-local facts;
- compares the delegated result to independently authored fixture expected
  values before writing;
- writes four deterministic UTF-8 JSON outputs through same-directory,
  fsynced, atomic replacements, with `run-summary.json` last;
- rolls back invocation-created temp/final files on failure;
- rejects a caller-owned non-empty output root without overwriting it.

The original source gate confirmed that `run_wu2_recovery` referenced the
Resume boundary and did not directly reference adapter normalization,
candidate-ID, seed-accounting, or record-local-fact generators. It did not
detect the response-hash comparison in the private `_prepare_replay` helper.
That audit gap caused the original completion statement to overclaim the
boundary.

### R1/R2 response-hash boundary remediation

R1 strengthened the existing DR05 without adding a seventh test. It wrapped
the real Resume replay function, retained the original error/output/fixture
and zero-network assertions, and added an exact one-call assertion.

The character-identical command produced the remediation red:

```text
exit code: 1
tests: 6
passed: 5
failures: 1
errors: 0
unique failure: expected Resume replay call count 1, actual 0
network attempts: 0
```

R2 changed only `recovery.py`. It removed both comparisons between actual raw
response SHA256 and the replay declarations before Resume. Raw bytes are now
passed to Resume first. A failed Resume result is mapped to the existing
Recovery problem; only after Resume succeeds does Recovery calculate the
actual raw SHA256 for `input_fixture_identity`.

The same command then produced:

```text
exit code: 0
tests: 6
passed: 6
failures: 0
errors: 0
network attempts: 0
```

The explicit full regression after R2 produced:

```text
exit code: 0
Ran 186 tests in 11.516s
OK
```

Source-order inspection confirms the call to Resume precedes actual-response
hash calculation. No pre-Resume actual-response hash comparison or
hash-driven skip remains. Resume replay is the sole authority deciding
query/request/response hash validity. Recovery retains exact paths, strict
control shape, independent Candidate/seed/fact comparisons, output-root
safety, atomic writes, and rollback. No route call or identity selection is
performed.

## 6. Outputs, independent expectations, and rollback

An independent system-temp replay produced:

```text
candidate_count: 7
seed_status_counts: matched=2, ambiguous=1, unmatched=1
completion_status: completed
network_attempts: 0
temporary residue: 0
```

Actual installed-byte SHA256 values:

| Output | SHA256 |
|---|---|
| `candidates.json` | `66ECE7AD3C26096459D8BD1D461E67F4CE6118C6046B8B70E5968E53A9E3CE79` |
| `seed-accounting.json` | `82F7DFA3FE028936256F7A420DEEE5990EF0D20E0EE959A481019E794063E966` |
| `record-local-facts.json` | `C33A0942A8D0E56BFF37E655D7798D26DA3D2A3936063E41CB64ABC6B7FAAFE3` |
| `run-summary.json` | `6D130EBEF731CCF2031C8CB3040DD4ECBEF9A1719344D3AF09C7BCFC3A42E64E` |

The first three hashes equal the hashes recorded inside the summary. The
summary is externally hashed to avoid recursive self-hashing. Two clean roots
produced pairwise-identical bytes for all four files.

Candidate equality was checked against the unique embedded
`candidates.json`, including artifact/root identity, canonical payload hash,
seven provider identities, and the unchanged Candidate envelope. Seed
accounting and record-local facts were checked against the frozen replay
expected arrays, not generated from the function under test.

DR05 changed one byte only in a system-temp copy of the raw anchor. It
returned one `RECOVERY_REPLAY_INVALID` problem, wrote zero outputs, and left
all repository fixture hashes unchanged. DR06 confirmed a non-empty
caller-owned root retained its byte-identical sentinel and gained no other
file. All network patches recorded zero calls.

No provider coordinates or raw response body are reproduced in this Review.

## 7. C3 verification entry

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu2r_downstream_recovery.ps1
```

Result:

```text
exit code: 0
locked entries: 21
pip check: No broken requirements found.
tests: 186 passed
failures: 0
errors: 0
Schemas: 11
fixture directories: 7
embedded documents: 40
dirty cases: 7
Recovery outputs: 4
network attempts: 0
temporary residue: 0
```

The entry uses the project `.venv` and confirms `sys.executable`,
`sys.prefix`, and every site-packages path are inside it. Installed package
names/versions match `requirements.lock` exactly after excluding only pip's
bootstrap packages. It validates the Schema registry, fixture bundle, all
frozen hashes, handbook state, exact scope, commit prefix, output hashes,
Resume delegation, R10 scans, and the full explicit unittest module list.

Its temporary Python helper uses a random system-temp path, UTF-8 without BOM,
project `.venv` Python, and `finally` deletion. It uses no repository temp
Python, `python -c`, `Invoke-Expression`, nested PowerShell command, or
network.

### C3 submission check observation

After the successful C3 run, an initial submission guard used
`git diff --name-only HEAD`, which correctly returned no path because the new
script was still untracked. The guard stopped before staging or committing.
The check was rerun using the exact `git status --short` entry, confirmed the
script as the sole untracked path, and C3 was then committed. No script,
validation logic, contract, or history changed as a result.

## 8. Full regression

The explicit full-suite command was run at C2:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_harness tests.test_wu2_recovery tests.test_wu2r_failure_evidence tests.test_wu2r_resume tests.test_wu2r_downstream_recovery -v
```

Measured result:

```text
Ran 186 tests in 24.098s
OK
exit code: 0
```

The C3 single entry independently reran the same 186-test module surface and
reported:

```text
Ran 186 tests in 11.312s
OK
exit code: 0
```

After mechanically updating only the verifier's Recovery/test hashes and
exact 8-or-9-commit prefix, the unchanged verification checks produced:

```text
exit code: 0
Ran 186 tests in 11.663s
OK
Schemas: 11
fixtures/documents/dirty cases: 7/40/7
outputs: 4
network attempts: 0
temporary residue: 0
```

The corrected R4 Review content was then checked through the same entry before
its documentation-only commit:

```text
exit code: 0
Ran 186 tests in 11.608s
OK
Schemas: 11
fixtures/documents/dirty cases: 7/40/7
outputs: 4
network attempts: 0
temporary residue: 0
```

Remediation modified only the approved test, Recovery implementation,
verifier, and this Review. Fixture, Resume, FER, adapter, Schema, validator,
Plan, dependencies, and all other paths remained unchanged. It made no
network call, did not rewrite history, and did not start WU3/WU5.

## 9. R10, secret, fallback, and scope audit

Measured/inspected results:

```text
silent recovery / semantic inference / guessing / warning promotion: 0
reachable NotImplementedError in recovery.py: 0
network transport implementation in recovery.py: 0
forbidden provider fallback token in recovery.py: 0
secret pattern findings in changed files: 0
new dependencies: 0
fixture modifications: 0
Schema modifications: 0
Resume/FER/adapter/validator modifications: 0
network calls: 0
repository atomic-temp residue: 0
system-temp verification residue: 0
remote/push/PR: 0
WU3/WU5 paths: 0
```

Runtime control documents contain only relative logical output paths.
ValidationProblem `artifact_path` may identify the caller-supplied filesystem
path, but it contains no raw input value, response body, credential, or
exception text. Known fixture/control mismatches map to existing Recovery
problem codes; unexpected programming/storage errors are rolled back and
re-raised rather than relabeled as valid input failure.

### C4 Review scan observation

The first C4 independent entry run stopped before its Python helper and
unittest gate because this Review initially spelled the scanner's forbidden
identifier patterns verbatim while reporting zero findings. That made the
Review self-trigger the changed-file scan. Only the reporting line in this
uncommitted Review was rephrased; the scanner, implementation, tests,
fixtures, and contract were unchanged. The character-identical entry command
was then rerun and produced:

```text
exit code: 0
Ran 186 tests in 21.853s
OK
fixtures/documents/dirty cases: 7/40/7
network attempts: 0
temporary residue: 0
```

## 10. Exactly 12 completion criteria

1. ✓ 已完成 — Start HEAD, `main`, sole approved Plan worktree entry, zero
   remotes/stashes, and exact Plan hash were verified before C0.
2. ✓ 已完成 — Handbook, all 15 immutable inputs, and all 11 Schema hashes
   remain unchanged.
3. ✓ 已完成 — WU2/WU2R historical `BLOCKED` states and their commits/docs
   were not rewritten or reinterpreted.
4. ✓ 已完成 — Only the committed anchor is consumed; acquisition and all
   other data/network calls are 0.
5. ✓ 已完成 — Post-remediation source-order audit and wrapped-function DR05
   prove Resume replay is the sole response-hash validity authority. Recovery
   retains no pre-Resume actual-response hash acceptance gate and copies no
   adapter, candidate-ID, seed-accounting, or record-local-fact logic.
6. ✓ 已完成 — Four complete deterministic outputs are installed and their
   actual bytes are independently hash-readable.
7. ✓ 已完成 — Candidate output equals the independently embedded Candidate
   expectation and its artifact/payload/provider identities.
8. ✓ 已完成 — Ordered seeds and candidate-local facts equal the independent
   replay expected values.
9. ✓ 已完成 — Tampered replay leaves zero partial output; a non-empty
   caller-owned root remains byte-identical and is not overwritten.
10. ✓ 已完成 — The committed C1 surface produced exact six-error
    `NotImplementedError` red; C2 used the character-identical command for
    6/6 green. The later DR05 remediation produced exact 5/1 red before R2
    restored 6/6 green. Both earlier test-structure and later boundary
    corrections are recorded without rewriting history.
11. ✓ 已完成 — Full regression is 186/186; fixture counts remain 7/40/7;
    outputs remain 4; network attempts and temporary residue are 0.
12. ✓ 已完成 — This Review records Git, hashes, outputs, red/green, scope,
    boundaries, and execution observations, then stops without WU3/WU5.

## Final status

```text
READY_FOR_HUGIN_REVIEW
```
