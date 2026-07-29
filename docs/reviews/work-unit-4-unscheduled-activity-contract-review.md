# Work Unit 4 Unscheduled Activity Contract Remediation Review

Review status: `READY_FOR_HUGIN_REVIEW`

Work unit: `WU4-UC · Unscheduled Activity Contract Remediation`

Approved Plan:

```text
plans/work-unit-4-unscheduled-activity-contract.md
Version: v0.1
SHA256: D01FBAC9642EF2790A19F3E502D0213DE03D85CB6B45F7E462BF1D15381E83B6
Lines: 207
Bytes: 8442
Decision: DISCRIMINATED_DAY_ASSIGNED_UNSCHEDULED
```

This Review covers the approved contract-only C0-C4 execution plus one
approved low-risk C1.1 formatting correction. It does not implement a
Planner, add a time-ordering rule, modify a validator or fixture, call a
network or LLM, or begin WU4-CP.

## 1. Execution gate

The immutable execution gate matched:

```text
branch: main
start HEAD: 1d5bf5ddf84634a5ba62a00a5e2f32d92c33886e
worktree: ?? plans/work-unit-4-unscheduled-activity-contract.md
remotes: 0
stashes: 0
Plan SHA256: D01FBAC9642EF2790A19F3E502D0213DE03D85CB6B45F7E462BF1D15381E83B6
Schema files: 11
```

The approved Plan was the only worktree entry. Before C0, the exact existing
suite and fixture validator were run:

```text
Ran 192 tests in 14.517s
OK
schemas: 11
fixture directories/documents/dirty cases: 7/40/7
```

The handbook was fetched and remained read-only:

```text
fixed path: <handbook>
local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree entries: 0
```

## 2. Actual shared contract and boundary

Before C2, `common.schema.json#/$defs/activity` globally required both
`start_at` and `end_at`. Both fields referenced the unchanged offset
`date_time` definition. The object used `additionalProperties: false`.

`common#/$defs/day.properties.activities.items` is the only activity
reference. Both consumers remain unchanged:

```text
plan.payload.days[].activities[]
previous-plan.payload.snapshot.days[].activities[]
```

Each containing day already requires `day_id` and `date`. Therefore the new
unscheduled form obtains its day assignment only from its existing parent
day; no day field or reference was added to activity.

Only `schemas/common.schema.json` changed. The new public base required set is:

```text
activity_id
candidate_ref
constraint_refs
evidence_fact_refs
```

`timing_status` is a closed enum:

```text
timed
day_assigned_unscheduled
```

The mutually exclusive `oneOf` branches are:

1. timed: requires both start/end; status is absent or exactly `timed`;
2. unscheduled: requires `day_assigned_unscheduled` and forbids either
   start/end property from being present.

The old timed byte shape remains valid without migration or a new field.
Explicit timed is also valid. The unscheduled branch cannot use null, empty
strings, default midnight, a partial pair, or omission without explicit
status.

The Schema `$id`, `0.1.0` version references, date-time definition,
`additionalProperties: false`, and total Schema count remain unchanged.

## 3. Time-ordering fact

The Plan-stage and execution source audits found no existing
`start_at < end_at` business comparison in `schema_validation.py` or the
existing tests. This work unit preserves date-time syntax but does not add or
claim chronology validation. Adding that behavior would require a separately
approved validator scope.

## 4. Git history and scope

Linear history before this Review:

```text
af525120732a106100bab7d497e89871e83424ef docs: record unscheduled activity contract plan
c35d103fc7cf10ec2d419a1e529bd45de50e5738 test: expose unscheduled activity contract gap
ad6a9ea82d5dd030475add25d033dd04ff3e998f test: remove WU4 contract test trailing blank line
3d0decd589d5a7afd3a744c2fb48e58665396bc5 feat: allow day-assigned unscheduled activities
0b02c7ffeb344a1304ce6c07f08cdd739a9aa80b chore: add unscheduled activity contract verification
```

C4 adds only this Review with:

```text
docs: prepare unscheduled activity contract review
```

The C1.1 commit is not an amend or rewrite. C1's pre-commit
`git diff --cached --check` reported one extra blank line at EOF, but the
non-fail-fast command sequence still committed C1. Hugin's approval allowed
low-risk test formatting corrections inside the five paths. C1.1 removed
only that blank line, then re-established the same valid Red. No assertion,
test name, test count, input, expected result, or contract changed.

Pre-C4 diff stat:

```text
plans/work-unit-4-unscheduled-activity-contract.md | 207 +++++++
schemas/common.schema.json                         |  25 +-
scripts/verify_wu4_unscheduled_activity_contract.ps1 | 598 +++++++++++++++++++++
tests/test_wu4_unscheduled_activity_contract.py    | 297 ++++++++++
4 files changed, 1125 insertions(+), 2 deletions(-)
```

C4 completes the exact five-path whitelist:

```text
plans/work-unit-4-unscheduled-activity-contract.md
schemas/common.schema.json
tests/test_wu4_unscheduled_activity_contract.py
scripts/verify_wu4_unscheduled_activity_contract.ps1
docs/reviews/work-unit-4-unscheduled-activity-contract-review.md
```

No plan/previous-plan/fixture-case Schema, validator, fixture, existing test,
dependency, `PLAN.md`, handbook, WU2/WU3 module, or sixth path changed. No
amend, squash, reset, rebase, remote creation, push, or PR occurred.

## 5. Red evidence

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu4_unscheduled_activity_contract -v
```

C1 result:

```text
tests: 6
passed: 4
failures: 2
errors: 0
exit code: 1
```

The only failures were:

```text
UC02 test_uc02_day_assigned_unscheduled_activity_becomes_valid
UC03 test_uc03_conditionally_feasible_plan_accepts_unscheduled_activity
```

Each failed only at the nested activity pointer and contained exactly two
`SCHEMA_VALIDATION_ERROR` problems with Schema rule `required`, corresponding
to the old start/end requirement. Import, dependency, path, syntax,
malformed-input, unexpected-exception, and network errors were zero.

After C1.1, the byte-for-byte same command re-established:

```text
Ran 6 tests in 0.140s
FAILED (failures=2)
same UC02/UC03 required failures
```

UC01 covered the legacy timed form at Red. Explicit `timing_status: timed`
cannot be expected green against the old Schema without becoming a third Red
failure, which would violate the approved exact 4/2 gate. It was therefore
verified independently after C2 and is permanently enforced by the C3
contract matrix.

## 6. Green and compatibility evidence

C2 modified only `schemas/common.schema.json`. The character-identical
targeted command produced:

```text
Ran 6 tests in 0.138s
OK
passed/failures/errors: 6/0/0
```

An independent nine-case matrix then checked the actual shared day definition:

```text
legacy_timed=true
explicit_timed=true
unscheduled=true
missing_mode=false
partial_timed=false
mixed_unscheduled=false
null_timed=false
empty_timed=false
unknown_mode=false
CONTRACT_MATRIX=9/9
```

The full regression after C2 produced:

```text
Ran 198 tests in 14.450s
OK
schemas: 11
fixtures/documents/dirty cases: 7/40/7
network attempts: 0
temporary residue: 0
```

All existing Plan and previous-plan fixtures remained valid without byte
changes or migration.

## 7. Hash evidence

WU4-UC files before C4:

| Path | SHA256 |
|---|---|
| `plans/work-unit-4-unscheduled-activity-contract.md` | `D01FBAC9642EF2790A19F3E502D0213DE03D85CB6B45F7E462BF1D15381E83B6` |
| `schemas/common.schema.json` | `A9134A705C67CF955228A28844AA2C5C42812AA2E0167E1256DB72F0ACAC36D7` |
| `tests/test_wu4_unscheduled_activity_contract.py` | `052BA5FA2149EE6CA58B61C65FD683AB11DDE6AF0BCEE74E2A87D8AD3A1A3308` |
| `scripts/verify_wu4_unscheduled_activity_contract.ps1` | `317F4D69F7E8E90C84DAA9099B0ED7F495445318AF05BC4B661C8266186410DD` |

Common changed from:

```text
83FE17127A545D168A16F58911564E53D2E17AFF826B6D34437D873ECF8E75BE
```

to the hash above. The other 10 Schema hashes remain:

| Schema | SHA256 |
|---|---|
| `candidates.schema.json` | `3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2` |
| `constraint-parse.schema.json` | `0D41493B52B6178AEE8DE44B2F3607B193B62C263AD79DEF380B638B22B400A4` |
| `constraints.schema.json` | `25069E0DEFBDC03FEA7E92E83EE10F952A31A2B18BDC3678D17786C537EE4473` |
| `evidence.schema.json` | `54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B` |
| `fixture-case.schema.json` | `630E57E7F27A660F388407A8FF1B81D851B8B3A047E5B98DCB70E1920177E45A` |
| `plan.schema.json` | `81EEB5899C33F19DC6FA059C7D447D747E72E355F3084D925FD9410272389BD3` |
| `plan-diff.schema.json` | `37B94FE5E03A73B046D7E6D79BEABF31C4105E50CD54DE520CA6C293AB3E8B43` |
| `previous-plan.schema.json` | `59692D17EB79C7EA2D4A2E2866898DD97A0E49B97834EC8AFC5EAB46A80BEDAC` |
| `request.schema.json` | `BC7F46E9A85CE9697F9BA01FF1506A5B56C161F2F6B5140D91FCF0B100762914` |
| `violations.schema.json` | `C117415030993C24649B17837EC2A35C69A2F1CEC7D923742ABD383BA85B394F` |

## 8. Independent verification entry

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu4_unscheduled_activity_contract.ps1
```

Before C3 commit:

```text
exit code: 0
targeted: 6/6
full: 198/198 in 14.304s
contract matrix: 9/9
WU4-UC verification PASS:
tests=198 schemas=11 fixtures=7 documents=40 dirty_cases=7
contract_cases=9 network_attempts=0 temporary_residue=0
```

After C3 commit, the identical entry independently produced:

```text
exit code: 0
targeted: 6/6 in 0.137s
full: 198/198 in 14.179s
contract matrix: 9/9
WU4-UC verification PASS:
tests=198 schemas=11 fixtures=7 documents=40 dirty_cases=7
contract_cases=9 network_attempts=0 temporary_residue=0
```

The entry checks project `.venv`, exact lock inventory, `pip check`, Plan
hash, exact scope and commit prefix including C1.1, new common/test hashes,
10 frozen Schema hashes, 11 Schema count, targeted/full suites, fixture
counts, parent-day references, both valid timing forms, all prohibited
forms, zero network attempts, and zero system-temporary residue.

`pip check` reported:

```text
No broken requirements found.
```

Historical WU2/WU3 verifiers and their frozen old common hash were not
modified, invoked as acceptance for this unit, or bypassed.

## 9. EOL, R10, and security audit

`git diff --check` over the full tracked WU4-UC diff is clean. Independent
EOL inspection reports index and working-tree LF for all four pre-C4 files.
The repository attribute labels PowerShell as `eol=crlf`, causing a
checkout-policy warning during C3 commit, but both the committed blob and
current working file were measured as LF with no BOM, no trailing whitespace,
and a final LF. No content changed after the warning.

Mechanical scans found:

```text
infer/guess/silent fallback tokens: 0
warning-as-pass/default-when-missing tokens: 0
network transport in the new test: 0
secret patterns: 0
NotImplementedError introduced: 0
```

No default time, midnight, null coercion, empty-string coercion, day field,
Schema version change, migration, or hidden fallback exists. Documentation
does not claim a Planner or a start/end chronology check.

## 10. Completion criteria

1. ✓ 已完成 — approved Plan bytes and SHA256 remain unchanged.
2. ✓ 已完成 — start HEAD, branch, worktree, remotes, and stashes matched.
3. ✓ 已完成 — final diff is restricted to the exact five approved paths.
4. ✓ 已完成 — legacy timed activities remain valid without migration.
5. ✓ 已完成 — explicit day-assigned unscheduled activities are valid.
6. ✓ 已完成 — unscheduled day ownership comes from the existing parent day.
7. ✓ 已完成 — null and empty start/end values remain invalid.
8. ✓ 已完成 — partial, mixed, missing, and unknown timing modes hard-fail.
9. ✓ 已完成 — a conditionally feasible Plan accepts an unscheduled activity.
10. ✓ 已完成 — all old tests and fixtures remain valid.
11. ✓ 已完成 — 198/198 and Schema/fixture counts 11 and 7/40/7 pass.
12. ✓ 已完成 — this Review records diff, Red/Green, compatibility, Scope,
    hashes, boundaries, and the C1.1 correction.

## 11. Final boundary

WU4-UC stops after C4. It does not authorize WU4-CP execution or any Planner,
network, LLM, route, recommendation, feasibility, or UI work.

Final status:

```text
READY_FOR_HUGIN_REVIEW
```
