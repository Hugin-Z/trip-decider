# Work Unit 2R Resume Review

Review date: 2026-07-28

Plan:
`plans/work-unit-2r-resume.md`

Plan version: v0.1

Approved Plan SHA256:
`AAE5DA96F11C367E450522CBAFDD1A7648AD527B42FBFC642C0FCDF355699674`

Review status:

```text
READY_FOR_HUGIN_REVIEW
```

This Review covers only WU2R Resume. It records the successful acquisition
branch and its offline replay evidence. It does not restore old WU2 C5/C6,
reinterpret the old WU2R attempt, call a route provider, or authorize WU3 or
WU5.

## 1. Outcome and preserved historical state

The new, isolated attempt group reached:

```text
WU2R_ACQUISITION_COMPLETED
```

Historical state remains:

```text
WU2:       BLOCKED
WU2R:      BLOCKED
WU2R-FER:  APPROVED
```

The old deleted WU2R ledger remains unrecoverable and is not reinterpreted.
Its attempt and retry budget is still:

```text
UNRECONCILABLE_FROM_DELETED_LEDGER
```

Only the new `WU2R-resume-001` authority was consumed. No old commit, Plan,
Review, decision, source policy, fixture, adapter, Schema, validator, FER,
recovery module, or harness was amended or rewritten.

The decision preserves the downstream prohibitions:

```text
OLD_WU2_C5_C6_UNCHANGED:
PROHIBITED

AUTOMATIC_WU2R_RESUME:
PROHIBITED

AUTOMATIC_WU3_WU5_START:
PROHIBITED
```

## 2. Repository and approval gate

Execution started from the approved gate:

```text
branch: main
HEAD: e93f606d193161bfb1bd245a1e9b5e27282bd9a7
worktree: only plans/work-unit-2r-resume.md
remotes: 0
stashes: 0
```

The approved Plan remained byte-identical:

```text
bytes: 32922
lines: 1015
sha256: AAE5DA96F11C367E450522CBAFDD1A7648AD527B42FBFC642C0FCDF355699674
```

The pre-C7 implementation HEAD is:

```text
bad377706f291f0ef0b11fd302bbdb6f1b665ce8
test: add completed WU2R resume acquisition anchor
```

C7 is the commit containing this Review:

```text
docs: prepare WU2R resume review
```

Its content-derived commit hash cannot truthfully be embedded in the file it
contains. The concrete C7/final HEAD is reported in the handoff after commit.

## 3. Linear history

The linear history before C7 is:

```text
f8cfcc68245b5282949275cb1718fc97f490f11b docs: record approved WU2R resume plan
39068e30c479e63789ad1bd0f8b883a78b28a0b3 docs: record WU2R resume acquisition gate
d8aa142afa2477226fa7b9e756a8209da5601fd6 chore: add WU2R resume integration interfaces
e00aa9ff8d618f4117bd53003efa9c79e7a1f22b test: add failing WU2R resume integration cases
45fda416521e5369803a6a0427fd2e592130181a test: correct RI03 candidate order expectation
706995fc4dab880a443aa76be022995fbe29a6c5 feat: implement WU2R resume integration
463727b2d67c07f228047dde418541e9f22676fa chore: add WU2R resume verification entry
bad377706f291f0ef0b11fd302bbdb6f1b665ce8 test: add completed WU2R resume acquisition anchor
```

The additional C3.1 commit was explicitly approved by Hugin and was not
amended or squashed into C3. It changes only
`tests/test_wu2r_resume.py`. C7 makes the actual WU2R Resume history nine
commits rather than the original eight-commit outline.

## 4. Handbook reconciliation

The handbook was fetched read-only at the approved fixed path and the eight
required files were loaded from `origin/main`:

```text
<handbook>

STATE.md
INDEX.md
SUMMARY.md
tools/context-injection.md
principles/r10-honesty.rule.md
principles/per-protocol.rule.md
principles/scope-control.rule.md
principles/fixture-first.rule.md
```

The post-C6 check remains:

```text
local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
branch: main
worktree: clean
```

No handbook file or history was modified.

## 5. Frozen inputs and Schema hashes

All 15 targeted frozen inputs match:

| Path | SHA256 |
|---|---|
| `docs/reviews/work-unit-2r-failure-evidence-review.md` | `2F6D893C57C70D5B74F432E96CCB72AFCC65F23BA0903BDF6CCDC6DC5D9E0B85` |
| `docs/wu2-recovery-source-and-capture.md` | `B34ED5EB0FA570A11E0B43E9F0A714C30F4A44FC53EE3D5D38302074B1DE9CA1` |
| `docs/wu2a-resume-decision.md` | `417F4E89A059CA99A5E96E960B839FA0297935F2438D76B100E7F8F30313B40A` |
| `docs/wu2-identity-boundary-decision.md` | `44C1105298AE55FD9B0508B078D4D39124455242F927DAFAAF8E7E2605A77B57` |
| `src/trip_decider/recovery.py` | `8105424CAEBD020BDAFBA4048477BF92846AE2B27090CB3EFAFC7C40B6183614` |
| `src/trip_decider/acquisition_evidence.py` | `BF7F25FC4A41C8085431450501B86866A7757B125A208363AA5113AD5F82FEDB` |
| `plans/work-unit-2-recovery.md` | `D6F6C0A662969D5AE810291CE746F4530594DC9C2A0E018C5FC41122AE606AF8` |
| `plans/work-unit-2r-failure-evidence-remediation.md` | `B457E6ECDF2CF6BEAB057BD35D761071AD6100D4926652736E3336726E3C3F95` |
| `scripts/acquisition_harness.py` | `AE6487D7F35E6A1CE351C07FD83DA219214705F1D3AC00611F5D7B9EF49559F9` |
| `src/trip_decider/adapters/open_data_poi.py` | `F39EBF86B682EDECF182F6148178AEBA434A287B34A270FE84D3FAEE8F80944B` |
| `tests/test_wu2_recovery.py` | `8D1341E4A57EA008152059A670CF4876EA48E8D118DF6E82EF15850549E4F43E` |
| `tests/test_wu2r_failure_evidence.py` | `09894721531AA422B2C87B03B3F4D3104E47A680FA459E16A4AE11A9E4AD684D` |
| `.gitignore` | `A6F5AFD044D06F8E04D1CC9DDE26B25D186A0CE9046C0ED50F7ADF734E5FC2A7` |
| `requirements.lock` | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` |
| `pyproject.toml` | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` |

All 11 Schema hashes also match:

```text
candidates.schema.json        3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2
common.schema.json            83FE17127A545D168A16F58911564E53D2E17AFF826B6D34437D873ECF8E75BE
constraint-parse.schema.json  0D41493B52B6178AEE8DE44B2F3607B193B62C263AD79DEF380B638B22B400A4
constraints.schema.json       25069E0DEFBDC03FEA7E92E83EE10F952A31A2B18BDC3678D17786C537EE4473
evidence.schema.json          54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B
fixture-case.schema.json      630E57E7F27A660F388407A8FF1B81D851B8B3A047E5B98DCB70E1920177E45A
plan.schema.json              81EEB5899C33F19DC6FA059C7D447D747E72E355F3084D925FD9410272389BD3
plan-diff.schema.json         37B94FE5E03A73B046D7E6D79BEABF31C4105E50CD54DE520CA6C293AB3E8B43
previous-plan.schema.json     59692D17EB79C7EA2D4A2E2866898DD97A0E49B97834EC8AFC5EAB46A80BEDAC
request.schema.json           BC7F46E9A85CE9697F9BA01FF1506A5B56C161F2F6B5140D91FCF0B100762914
violations.schema.json        C117415030993C24649B17837EC2A35C69A2F1CEC7D923742ABD383BA85B394F
```

## 6. C3 red, C3.1 correction, and C4 green

C3 used:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2r_resume -v
```

The valid interface red was:

```text
tests: 6
passed: 0
failures: 0
errors: 6
cause: explicit NotImplementedError
network attempts: 0
```

There were no import, dependency, path, syntax, malformed-test, or network
errors.

During C4, RI03 exposed a test expectation whose candidate sequence did not
follow the already frozen adapter order `(record_type, record_id)`. Hugin
approved C3.1:

```text
45fda416521e5369803a6a0427fd2e592130181a
test: correct RI03 candidate order expectation
```

The uncommitted C4 implementation was held by a path-limited stash. C3.1
changed only the four expected RI03 candidates, after which the same command
again produced six explicit interface errors. The identical implementation
was restored without conflict. C4 then used the character-identical command:

```text
tests: 6
passed: 6
failures: 0
errors: 0
network attempts: 0
```

C4 changed only `src/trip_decider/resume_acquisition.py`; C3 and C3.1 were
not rewritten. The full C4 regression was 175/175 green.

## 7. Source, call budget, and FER evidence

The source gate remained the previously approved OSM/Overpass open-data
policy:

```text
endpoint: https://overpass-api.de/api/interpreter
method: POST
license: ODbL-1.0
attribution: © OpenStreetMap contributors
storage: persistent anchor allowed
replay: allowed
fixture: allowed
```

The fixed link is:

```text
attempt_group_id: WU2R-resume-001
run_id: run_wu2r_resume_001
query_sha256: 5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F
request_sha256: 6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045
```

Actual call accounting:

```text
scheduled Overpass POST: 1
physical attempts: 1
retry relations: 0
forbidden provider/source calls: 0
second acquisition: 0
route acquisition: 0
```

The single attempt returned HTTP 200 and terminated successfully. No retry,
query change, endpoint change, alternate source, or new attempt group was
used.

The authoritative ignored-runtime FER envelope is:

```text
path: runtime/wu2r-failure-evidence/run_wu2r_resume_001/failure-evidence.json
sha256: 817197DA1D64AC660455C20725A11B03D8BAD7E9EACC9945FAEC815D7AD36CA3
status: succeeded
attempts: 1
retries: 0
response phase: accepted
response bytes: 4362
response sha256: 41520443BB370919F184CF46441DB897A809EB1B86119B7CF2B6007F20A5B382
cleanup: succeeded
cleanup residue: 0
primary persistence: succeeded
emergency persistence: not attempted
```

The FER envelope contains no raw body, exception text, credential, or
coordinate list. Its attempt, terminal, cleanup, and persistence records are
complete.

## 8. C6 RA expectation corrections

The acquisition itself succeeded once with no retry. The two RA deviations
were test expectations, not data, adapter, or product-contract failures.

### 8.1 First RA run

The first run of:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2r_resume -v
```

produced:

```text
tests: 11
passed: 10
failures: 1
errors: 0
```

RA02 sorted stringified OSM IDs lexicographically. The adapter and frozen
provider identity contract order is `(record_type, numeric record_id)`.
Hugin approved changing only the RA02 test-side sorting key to:

```python
key=lambda item: (item[0], int(item[1]))
```

No assertion structure, identity set, fixture byte, adapter, or implementation
changed.

### 8.2 Second RA run

After the sorting correction, the same command again produced:

```text
tests: 11
passed: 10
failures: 1
errors: 0
```

RA02 still contained the old fixed expectation `婺源县 = 2`, while the
candidate pool retained three identities with that exact label.

The first independent raw check passed a direct Chinese literal through a
PowerShell-to-Python pipe and returned zero matches. Hugin ruled that result
to be a:

```text
verification-command encoding defect
```

It is not recorded or interpreted as evidence that the raw response contained
zero matching identities.

### 8.3 Encoding-safe raw verification

Hugin approved a second, pure-ASCII standard-library check using:

```python
TARGET = "\u5a7a\u6e90\u53bf"
```

The check read only the frozen `osm-pois.json` bytes. It did not import the
adapter or Resume implementation, read the candidate artifact as the expected
source, call a network boundary, change the fixture, or output coordinates.

Measured result:

```text
exit code: 0
raw sha256: 41520443BB370919F184CF46441DB897A809EB1B86119B7CF2B6007F20A5B382
element count: 7
matched count: 3
unique provider identities: 3
all category tuples non-empty: true
all location shapes valid: true
```

The three independently observed identities are:

```text
node:244082160     place=county
node:673351120     place=city
relation:3046784   place=county
```

No coordinates are reproduced in this Review.

Only after that check did Hugin authorize changing the RA02 expected count
from 2 to 3. The expected value therefore comes from current frozen raw bytes,
not adapter output, Resume output, the failing assertion, memory, or a new
acquisition.

### 8.4 Final RA gate

The same RA command then produced:

```text
tests: 11
passed: 11
failures: 0
errors: 0
network attempts: 0
```

Neither correction changed fixture bytes, adapter behavior, candidate ID
generation, Resume implementation, FER, recovery, harness, Schema, or product
contract. No second acquisition occurred.

## 9. Anchor and replay evidence

The success anchor contains:

```text
fixture directories after C6: 7
embedded documents after C6: 40
dirty cases after C6: 7

new fixture root type: candidates
new fixture bundle closure: CLOSED
new fixture documents: 2
new fixture dirty cases: 1
provider identities: 7
candidates: 7
seed states: matched=2, ambiguous=1, unmatched=1
```

The four new fixture hashes are:

| Path | Bytes | SHA256 |
|---|---:|---|
| `fixtures/jiangxi_multi_identity_smoke/README.md` | 1035 | `49049A94B0DF039C430506BBA9827B599F417CF3A97AEB069D3099AEE9F59223` |
| `fixtures/jiangxi_multi_identity_smoke/case.json` | 19361 | `6052797C4FE43B0E1BE216187EAD6AC10FB1617F07CD7784CF81F8403843F3C8` |
| `fixtures/jiangxi_multi_identity_smoke/replay.json` | 10878 | `5D8086E128FE1B33FD0314151C49256A459DB401233B1C548843791AFAC1919A` |
| `fixtures/jiangxi_multi_identity_smoke/osm-pois.json` | 4362 | `41520443BB370919F184CF46441DB897A809EB1B86119B7CF2B6007F20A5B382` |

Every valid `(record_type, record_id)` is retained once. Same-label identities
are not selected, merged, ranked, or removed. The unmatched seed creates no
placeholder and makes no real-world absence claim. RA03 proves the replay
output equals the independently authored request and candidate artifacts;
RA05 proves the committed bytes replay with zero network attempts.

## 10. Success verification

The complete entry was run before C6 commit and independently again after C6:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu2r_resume.ps1 -Mode Success
```

Both runs exited 0. The post-C6 output was:

```text
tests: 180
passed: 180
failures: 0
errors: 0
schemas: 11
fixture directories: 7
embedded documents: 40
dirty cases: 7
offline network attempts: 0
```

The direct full regression was also run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_harness tests.test_wu2_recovery tests.test_wu2r_failure_evidence tests.test_wu2r_resume -v
```

Result:

```text
existing tests: 169
Resume tests: 11
total: 180 passed
failures: 0
errors: 0
```

The verification entry additionally proved the project `.venv`, lock match,
`pip check`, 11 Schema registry/load checks, frozen hashes, scope, scans,
fixture closure/root/counts, decision/FER link, and deterministic failure
gates.

## 11. Scope, diff, and commit evidence

The pre-C7 diff from the approved start contains exactly nine of the ten
whitelist paths:

```text
docs/wu2r-resume-acquisition-decision.md
fixtures/jiangxi_multi_identity_smoke/README.md
fixtures/jiangxi_multi_identity_smoke/case.json
fixtures/jiangxi_multi_identity_smoke/osm-pois.json
fixtures/jiangxi_multi_identity_smoke/replay.json
plans/work-unit-2r-resume.md
scripts/verify_wu2r_resume.ps1
src/trip_decider/resume_acquisition.py
tests/test_wu2r_resume.py
```

Pre-C7 stat:

```text
9 files changed
3828 insertions
0 deletions
```

C7 adds only:

```text
docs/reviews/work-unit-2r-resume-review.md
```

The C6 commit is:

```text
bad377706f291f0ef0b11fd302bbdb6f1b665ce8
test: add completed WU2R resume acquisition anchor
6 files changed, 1001 insertions, 10 deletions
```

Its six paths are exactly the success-branch whitelist: the decision, Resume
test module, and four fixture files. It contains no implementation, Schema,
validator, FER, recovery, harness, source-policy, or dependency change.

## 12. R10, scans, and residue

The Success entry completed all configured checks for:

- fallback or guessed/defaulted behavior;
- warning treated as pass;
- credentials and private-key patterns;
- raw-body or exception serialization;
- network transport in the offline Resume surface;
- forbidden provider clients;
- path scope and frozen hashes;
- unsupported capability claims.

All checks passed. The measured residue is:

```text
WU2R Resume system-temp files: 0
verification system-temp files: 0
repository .tmp files: 0
runtime files: 1
```

The one runtime file is exactly the approved ignored FER envelope. No
acquisition helper, subordinate harness ledger, raw-capture temporary file, or
atomic temporary file remains.

No credential was added to Git. No remote was created, no push occurred, and
no history rewrite was performed.

## 13. Completion criteria

Exactly the 20 Plan criteria are reviewed:

1. ✓ 已完成 — execution started at the approved `main` HEAD with only the
   approved Plan, zero remotes/stashes, and the exact Plan hash.
2. ✓ 已完成 — handbook fetch/reconciliation and all eight `origin/main`
   reads are recorded; handbook HEAD and worktree remain unchanged.
3. ✓ 已完成 — WU2/WU2R remain historically `BLOCKED`, WU2R-FER remains
   approved, and old history/documents remain unchanged.
4. ✓ 已完成 — all 15 targeted frozen inputs and all 11 Schema hashes match.
5. ✓ 已完成 — the old budget remains unreconcilable; only the isolated new
   group budget was consumed.
6. ✓ 已完成 — run/group IDs, FER path, query hash, and request hash match
   across the decision, FER ledger, and replay.
7. ✓ 已完成 — source policy, endpoint, exact hashes, ODbL attribution, and
   persistence gate were established before transport.
8. ✓ 已完成 — one scheduled POST produced one physical attempt, zero retry
   relations, and zero forbidden source calls.
9. ✓ 已完成 — FER records started/terminal states, the exact attempt and
   empty retries, cleanup, sink state, and sanitized content.
10. — 不适用 — the complete-evidence failure branch was not taken.
11. ✓ 已完成 — all seven provider identities became seven candidates; no
    same-label identity was selected, ranked, merged, or removed.
12. ✓ 已完成 — all four seeds have exact accounting with `matched`,
    `ambiguous`, and `unmatched` states, resolving refs, and no placeholder.
13. ⚠ 已知限制 — the final raw/license/attribution/persistence and commit
    gates passed, but the RA suite was not green on its first run. Two
    Hugin-approved test expectation corrections were required: numeric OSM ID
    ordering and the raw-proven `婺源县` identity count. The first direct
    Chinese-literal raw command also had a verification-command encoding
    defect; the pure-ASCII standard-library rerun established the count before
    the second correction. Fixture bytes, adapter, implementation, and product
    contract were unchanged, and no second acquisition occurred.
14. ✓ 已完成 — offline replay reproduces independently authored artifacts,
    accounting, local facts, and hashes with zero network attempts.
15. ✓ 已完成 — C3 has the exact six-error interface red; after the separately
    approved C3.1 expectation correction, the effective red was reacquired and
    C4 used the same command for 6/6 green without changing tests in C4.
16. ✓ 已完成 — success verification is exactly 180/180, Resume 11/11, and
    fixture totals 7/40/7.
17. ✓ 已完成 — the final diff uses only the ten whitelist paths; protected
    implementation, dependency, Schema, validator, adapter, FER, recovery, and
    harness diffs are zero.
18. ✓ 已完成 — R10, credential, provider, fallback, unsupported-claim, and
    residue gates pass; temporary residue is zero.
19. ✓ 已完成 — the decision has the exact terminal and downstream-prohibition
    tokens and does not restore old work or start WU3/WU5.
20. ✓ 已完成 — this Review independently reports Git, hashes, call budget,
    FER, red/green, branch outcome, fixture/replay, scope, R10, and all 20
    statuses, then stops for Hugin review.

## 14. Final state

The acquisition branch is complete and independently replayable within the
frozen WU2R Resume boundary. This does not authorize any subsequent work unit.

```text
READY_FOR_HUGIN_REVIEW
```
