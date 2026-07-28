# Work Unit 2A Resume Review

Review status: READY_FOR_HUGIN_REVIEW

Reviewed on: 2026-07-28

Scope: `WU2A-Resume C0-C2`

Start HEAD:
`f4e778f7fe2fc92ac6698ee96c36447f3d24aab1`

C2 materialization base HEAD:
`026cfa0be4658341fd7e14e3a42526996654c9fa`

The final C2 commit cannot contain its own Git object ID. The handoff records
the resulting final HEAD after this review document is committed.

## 1. Outcome

The independent attempt group `WU2A-resume-001` produced an:

```text
APPROVED_ACQUISITION_RECIPE
```

Its compatibility is deliberately narrower:

```text
ADAPTER_COMPATIBLE_ONLY
```

The O2 response is structurally consumable by the frozen OSM adapter, but it
does not complete the old WU2 target set or either route prerequisite.
Therefore:

```text
WU2: BLOCKED
WU2A: INVESTIGATION_BLOCKED
WU2 C5/C6: not resumed
WU3: not started
```

No anchor or fixture was created. The result approves only the exact
acquisition recipe recorded in `docs/wu2a-resume-decision.md`.

## 2. Approved Plan and preserved history

Approved Plan:

```text
path: plans/work-unit-2a-resume.md
version: v0.1
sha256: B363FA80F1E62168E7AF654DE1195A24812F890352FB6C15852D65C488EE9BDB
```

C0 committed those approved bytes without editing the Plan:

```text
7fe3cf3 docs: record approved WU2A resume plan
```

C1 committed only the new decision:

```text
026cfa0 docs: record resumed acquisition investigation
```

The following frozen facts were rechecked after C1:

| Item | Actual SHA256 / state | Result |
|---|---|---|
| old WU2A decision | `570649D6B7287B48F3C396E536AC05EF31D949FC7AF960EF2D3DFEB17D4A9F6D` | match |
| WU2A-R Review | `DBA77226011F013D687FB3C6AF6085C692217167803E3280246EC70ABA93338F` | match |
| WU2A Plan | `432318A68D13774646CF3A1E5BE6057D5C92DE7CE600E06FA6CF52BD0CD92E90` | match |
| WU2A-R Plan | `FD0DA659873A275944DE7FCC9C1E4D1D27EE9BD7F61F40F4A3371493173008B9` | match |
| WU2 source decision | `E667ABCF6BEBFB522AE0EA76AFDD6EB628E11214B33773045AA5EC8B8C7FEA62` | match |
| WU2A-R harness | `AE6487D7F35E6A1CE351C07FD83DA219214705F1D3AC00611F5D7B9EF49559F9` | match |
| WU2 Plan | `894D5844E140BF62EC1DB89B1BE318EB4945FF4A0BF8B139E9B82C0B4929BA2C` | match |
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` | match |
| source policy | `B89D0836BCC17DD1D52CA215F38EF290134251295ECAC183BA7D54C45A1C4989` | match |
| contract extension | `BD2280BFA2C51F2FEC8521F16BB7DE73667A39142FD89E04F6A515CB42B8963E` | match |
| harness tests | `C924608383A6382C18E232368809F81114CA44C6384638C4B18B35A43F9FA12B` | match |
| `pyproject.toml` | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` | match |
| `requirements.lock` | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` | match |
| WU2 Review | absent | preserved |

All 11 Schema hashes also matched the approved baseline:

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

## 3. Handbook recheck

The fixed handbook repository was fetched read-only with
`git fetch origin --prune`. Before and after the C2 recheck:

```text
local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree: clean
```

The following files were actually read from `origin/main`:

```text
STATE.md
INDEX.md
SUMMARY.md
tools/context-injection.md
principles/r10-honesty.rule.md
principles/per-protocol.rule.md
principles/scope-control.rule.md
principles/fixture-first.rule.md
```

The handbook repository was not modified.

## 4. New authorization and actual call accounting

| Metric | Approved maximum | Actual |
|---|---:|---:|
| scheduled Geofabrik `.poly` GET | 1 | 1 |
| scheduled Overpass POST | 3 | 2 |
| physical HTTP attempts | scheduled plus at most one retry | 3 |
| transport retry relations | 1 across group | 0 |
| O3 calls | conditional | 0 |
| alternate Overpass instances | 0 | 0 |
| Nominatim / OSRM / commercial map | 0 | 0 |
| BBBike / Wikidata service / crawler | 0 | 0 |

Only these endpoints were called:

```text
https://download.geofabrik.de/asia/china/jiangxi.poly
https://overpass-api.de/api/interpreter
```

The old investigation accounting remains present by frozen decision
reference and was not merged into the new budget.

## 5. Attempt ledger and cleanup evidence

| Qualified attempt | Status | HTTP | Bytes | Response SHA256 | Elements | Selection |
|---|---|---:|---:|---|---:|---|
| `WU2A-resume-001:G0:attempt-0001` | succeeded | 200 | 17003 | `B874AF22600165D6110F69472338720B4E210214E2EC681BF933F276BC858BBC` | n/a | bbox derived |
| `WU2A-resume-001:O1:attempt-0001` | succeeded | 200 | 1354 | `FC5D7965965055B4FA61C1194B997233086D7AE8D5AB6BA9625AB47BF4796122` | 1 | unique relation |
| `WU2A-resume-001:O2:attempt-0001` | succeeded | 200 | 4362 | `29616F1DA00680B3253D0341EF78095664382A7D070C12CF3DB7FFC048C96A4C` | 7 | 7 structurally selectable objects |

Every qualified record embeds the original 14-field harness attempt,
operation/group IDs, query hash where applicable, observed count, source base
timestamp, stable selection tokens, and an explicit cleanup sidecar.

For every operation:

```text
raw_capture_created: false
raw_capture_deletion_status: not_applicable_no_capture_file
ledger_deleted: true
ledger_residue_count: 0
atomic_tmp_residue_count: 0
```

After acquisition and final validation:

```text
helper residue: 0
validator residue: 0
ledger residue: 0
atomic ledger temp residue: 0
raw capture residue: 0
```

The helper SHA256 before execution and deletion was:

```text
8E79A48534FA74B5BD61B2CDD31F04185C922857B755DA1771670D730D7451C6
```

Response bytes remained in process memory. No response body, vertex list,
numeric POI coordinate pair, helper path, or ledger path entered Git.

## 6. Query and request integrity

| Operation | Query/URL SHA256 | Request SHA256 |
|---|---|---|
| G0 | URL `892ACC39C74B24269C8200D2EAD351E0E9F9A436F5FD388FCD777792315F48F8` | same |
| O1 | `BE9D88846226229A626B3BB6A91BF6AD77425C5368950A8B0287FA4635AFEA64` | `E88E8BFD82CC64B80CB09480C3ADD47F3B8003D6D665F4B2A56C639B461FE3AC` |
| O2 | `5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F` | `6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045` |

The final validator recomputed URL/query/request hashes from recorded bytes
and checked response metadata types. O1 mechanically captured relation ID
`3046784`; O2 substituted only that ID into the frozen template.

## 7. Selection and compatibility

G0 strictly parsed 548 numeric vertices from one polygon ring and derived:

```text
south: 24.47809
west: 113.5688
north: 30.08841
east: 118.4865
```

Those values describe the Geofabrik extract clipping bbox, not an
administrative boundary.

O1 returned one exact `boundary=administrative` relation whose `name` or
`name:zh` was `婺源县` and whose `admin_level` was explicit.

O2 retained all seven objects satisfying the frozen predicate. It did not
rank or choose a first result. It stored only type, ID, primary name, matched
category, and coordinate shape; numeric coordinate pairs and full tags were
omitted.

The result is `ADAPTER_COMPATIBLE_ONLY`: `庆源` was not selected, while
`婺源县` and `篁岭` each had multiple distinct qualifying OSM identities.
No identity was preferred by proximity, popularity, first position, fuzzy
matching, language fallback, LLM, or manual knowledge. No route prerequisite
was acquired.

## 8. D12-only red and same-validator green

Official validator SHA256 used for both recorded gates:

```text
A853386D12FE12010E73B6425A0E32CCF97A69B1E622517E22147434FD04B0AC
```

Command used at both gates:

```powershell
.\.venv\Scripts\python.exe <temp>\trip-decider-wu2a-resume-validator-<redacted-amap-key>.py
```

Pending pre-network red:

```text
checks: 12
passed: 11
failures: 1
errors: 0
failure: D12
network attempts: 0
exit code: 1
```

Final green:

```text
checks: 12
passed: 12
failures: 0
errors: 0
network attempts: 0
exit code: 0
validator residue after run: 0
```

Before the official red, two provisional system-temp validator versions were
discarded without any network call. The first over-constrained all SHA text
to uppercase even though the frozen harness's original 14-field record uses
lowercase hex. The final validator compares hash values case-insensitively
while preserving the original harness bytes, and deletes itself only on a
final-status run. The official red and green used the same final bytes shown
above.

A non-contract read-only preflight initially failed before loading validator
logic because PowerShell stripped quotes from a `python -c` argument. It
produced only Python `SyntaxError`, made no data call, and changed no file.
The preflight was then transported through stdin and returned D01-D12 all
true. Neither preflight is represented as the official red or green.

## 9. Non-network regression

C1 regression command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_harness -v
```

Actual C1 result:

```text
Ran 143 tests in 11.544s
OK
exit code: 0
```

C2 independent rerun:

```text
Ran 143 tests in 11.149s
OK
exit code: 0
```

## 10. Git, scope, secret, and fallback review

Pre-C2 history:

```text
026cfa0 docs: record resumed acquisition investigation
7fe3cf3 docs: record approved WU2A resume plan
```

Pre-C2 diff from the approved start:

```text
docs/wu2a-resume-decision.md | 539 insertions
plans/work-unit-2a-resume.md | 959 insertions
2 files changed, 1498 insertions
```

C2 may add only this Review, producing the exact three-path whitelist:

```text
plans/work-unit-2a-resume.md
docs/wu2a-resume-decision.md
docs/reviews/work-unit-2a-resume-review.md
```

Dependency, source, Schema, test, fixture, prior Plan, prior Review, and
handbook diffs are zero. `git remote -v` and `git stash list` are empty.

The decision scan found only explicit zero-count/non-capability mentions of
Nominatim and OSRM. It found no credential assignment, bearer token,
password, silent fallback, `guess_*`, or `infer_*` behavior. Endpoint,
license, and attribution strings are public provenance, not secrets.

## 11. Completion criteria

1. ✓ 已完成 — approved Plan bytes match the approved SHA256 and C0 did not edit them.
2. ✓ 已完成 — WU2/WU2A history and old decision are unchanged; WU2 Review remains absent.
3. ✓ 已完成 — WU2A-R Plan, harness, test, Review, and approval history are unchanged.
4. ✓ 已完成 — handbook fetch, eight `origin/main` reads, clean state, and `0/0` are evidenced.
5. ✓ 已完成 — final whitelist is limited to the three approved paths; code/dependency/test diff is zero.
6. ✓ 已完成 — `WU2A-resume-001` is independent and old conservative accounting remains referenced.
7. ✓ 已完成 — actual budget is 1 GET, 2 POST, 3 physical attempts, and 0 retry relations.
8. ✓ 已完成 — only the two allowlisted endpoints were called; every forbidden-call count is zero.
9. ✓ 已完成 — all three attempts have 14-field harness records, qualified IDs, hashes, response evidence, and cleanup.
10. ✓ 已完成 — URL/query/entity bytes and all query/request/response hashes are mechanically recheckable.
11. ✓ 已完成 — raw data was memory-only; committed raw, coordinate pair, anchor, and fixture counts are zero.
12. ✓ 已完成 — helper, validator, ledger, atomic temp, and raw-capture residue counts are zero.
13. ✓ 已完成 — selection used only the frozen exact predicate; prohibited inference/fallback behavior is absent.
14. ✓ 已完成 — the final result is one complete approved recipe with an explicit narrow compatibility classification.
15. ✓ 已完成 — D12-only red and 12/12 green used the same `A853...B0AC` validator bytes and command.
16. ✓ 已完成 — C1 and C2 independent runs both completed 143/143 green.
17. ✓ 已完成 — Review contains call, retry, source-policy, cleanup, hash, scope, secret/fallback, and commit evidence.
18. ✓ 已完成 — WU2 was not restored; WU3/remote/push/new Plan activity is absent.

## 12. R10 and known limitations

- No HTTP success, OSM identity, or compatibility statement was reconstructed
  from memory; all values come from the recorded harness output and frozen
  predicates.
- API/route/POI truth is not claimed. The recipe is a repeatable acquisition
  procedure, not a stable-data or geographic-completeness guarantee.
- The O2 response is not represented as WU2-ready because original target
  identity and route prerequisites remain incomplete.
- No raw response exists in the repository, so this Review cannot replay the
  observed bytes; it can only audit the hashes and approve a future exact
  acquisition attempt under a new authorization.
- The provisional validator and read-only preflight launch issues are
  disclosed above and are not relabeled as contract failures or hidden.

## 13. Final status

```text
READY_FOR_HUGIN_REVIEW
```

The C2 independent non-network suite passed with this Review as the only
worktree addition. Execution stops after the Review commit; WU2 is not
restored and no later work unit is started.
