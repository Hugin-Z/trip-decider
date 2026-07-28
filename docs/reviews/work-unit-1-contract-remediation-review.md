# Work Unit 1C Review · Real-world Contract Compatibility

Review date: 2026-07-28

Plan:
`plans/work-unit-1-contract-remediation.md` v0.1

Approved Plan SHA256:
`815D399A6F30D0993DAB699FF73F0BC0F8F0BF62F8E812EA0C4586133A2A258E`

Start HEAD:
`49394356c9fd81f951d439336d6243dc7d9452e9`

C6 parent HEAD:
`f337ee16e9ebabb9e2d06d41514c9e9dd29fc1c7`

The final C6 HEAD is the commit containing this Review and is reported by
`git rev-parse HEAD` in the WU1C handoff. This document does not modify itself
after commit to insert its own hash.

## 1. Outcome

WU1C adds structural compatibility for:

- closed provider identity and native metadata on candidates;
- explicit coordinate CRS and coordinate-local provenance;
- unresolved provider locations when CRS is unknown;
- orthogonal source, capture, storage, replay, fixture, authorization, and
  license policy;
- persistent fixture metadata for open, explicitly provider-authorized,
  synthetic, and user-controlled sources;
- deterministic rejection of commercial-live and temporary-capture fixture
  kinds.

The implementation is backward compatible with the six existing WU1
fixtures. It does not add a Schema, artifact type, dependency, adapter, API
call, real POI, coordinate conversion, evidence behavior, planner behavior,
or WU2 work.

## 2. Baseline and handbook gate

Execution began only after these gates passed:

```text
branch: main
HEAD: 49394356c9fd81f951d439336d6243dc7d9452e9
worktree: only ?? plans/work-unit-1-contract-remediation.md
Plan SHA256: 815D399A6F30D0993DAB699FF73F0BC0F8F0BF62F8E812EA0C4586133A2A258E
Schema files: 11
```

The handbook was fetched with:

```powershell
git -C $Handbook fetch origin --prune
```

Pre- and post-fetch state:

```text
local HEAD: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
branch: main
worktree: clean
```

Files reread from `origin/main`:

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

The post-execution handbook check returned the same local and remote HEAD,
`0/0`, and a clean worktree. No handbook file was modified.

## 3. Linear Git history

Measured C0-C5 history:

```text
834e07e8a692ba1fdb95da34a1b4c80d9860258a
docs: record approved WU1 contract remediation plan

b04449643bde65a80bbdc516a899e1f72219e0ae
docs: define real-world source and replay policy

ea20e1e7ff4b88cbdb183e4c6736b62512bc7c34
docs: define candidate and location compatibility extension

f25ca48ba55a4df23a4c3978c81313efa194a87f
test: add failing real-world contract compatibility cases

3ad45f36734c8594014181fe2e07400d75c895e8
feat: extend candidate location and fixture source contracts

f337ee16e9ebabb9e2d06d41514c9e9dd29fc1c7
chore: add WU1C verification entry
```

C6 is this document:

```text
docs: prepare WU1 contract remediation review
```

No commit was amended, squashed, rebased, reset, or rewritten. The WU1 and
WU1R histories remain ancestors of the WU1C start HEAD and are unchanged.

## 4. Diff and scope evidence

Measured C0-C5 diff:

```text
8 files changed, 3359 insertions(+), 9 deletions(-)
```

```text
docs/real-world-contract-extension.md             +575
docs/real-world-source-policy.md                  +387
plans/work-unit-1-contract-remediation.md         +961
schemas/candidates.schema.json                     +61 -2
schemas/common.schema.json                        +250
schemas/fixture-case.schema.json                   +79 -7
scripts/verify_wu1c.ps1                           +410
tests/wu1c_contract_compatibility_cases.py         +636
```

C6 adds only this Review as the ninth approved path. Final WU1C paths are
therefore exactly:

```text
plans/work-unit-1-contract-remediation.md
docs/real-world-source-policy.md
docs/real-world-contract-extension.md
schemas/common.schema.json
schemas/candidates.schema.json
schemas/fixture-case.schema.json
tests/wu1c_contract_compatibility_cases.py
scripts/verify_wu1c.ps1
docs/reviews/work-unit-1-contract-remediation-review.md
```

Measured protected-path diff count through C5: `0`.

Protected scope includes:

```text
PLAN.md
docs/architecture.md
docs/artifact-contracts.md
docs/reviews/work-unit-1-review.md
docs/reviews/work-unit-1-remediation-review.md
src/trip_decider/**
scripts/verify_wu1.ps1
tests/test_schema_validation.py
tests/test_fixture_validation.py
tests/wu1r_verify_entry_cases.py
fixtures/**
pyproject.toml
requirements.lock
```

`git diff --check` returned exit code `0`.

## 5. Frozen-input hash evidence

| Path | Final SHA256 |
|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `docs/architecture.md` | `CA5B6F7D345E11623C94C13CDD73C0E774282AFD88F9E2E036035ED2396BB6F4` |
| `docs/artifact-contracts.md` | `695C0AC6738B71852DC60ADAFD2A98B974C5EC65BB744D19B0E22EC3550497BF` |
| `docs/reviews/work-unit-1-review.md` | `C3E7CCF3D0F1A0181AD36E0435FCC481E56E3B3DAF42A921DB4E2E7EC72A659E` |
| `docs/reviews/work-unit-1-remediation-review.md` | `C7769D8DFEF0AE636D992475E40DB6C7E4498AB084B32B571D10BE8574256FF0` |
| WU1C Plan | `815D399A6F30D0993DAB699FF73F0BC0F8F0BF62F8E812EA0C4586133A2A258E` |
| `schema_validation.py` | `2061084E8AC27DF4C08F63DC264A2612685980D966AA5291A46660BE3F1CC017` |
| `fixture_validation.py` | `6C720C5F4D72356F2909854E6C1B605B891BC40787A4D87739CCA69C2590EBBF` |
| `verification_entry.py` | `E5698D276AC23B9A12DA8CB7943750AC5F45CC8C248B582A67A0DC18CE8F6D0E` |
| `scripts/verify_wu1.ps1` | `E20DE35F7597070C7554702421241ADD7809B4CDC3DC2034DC072274C243656B` |
| `tests/test_schema_validation.py` | `A4075DC19E2D923E25862D589DA4DA83AEE39B2D2355BF9B553683C7E24C0DAA` |
| `tests/test_fixture_validation.py` | `E748784A658FFD098A97269F7C3864A9CFB6612839207640A0CA0B900908BC7B` |
| `tests/wu1r_verify_entry_cases.py` | `2F4213F7789C18C15E0FDAA0D4012834D4325E97DA9221C4E64F9D571F5D1900` |
| `pyproject.toml` | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` |
| `requirements.lock` | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` |

The frozen fixture tree contains 13 files and retains aggregate SHA256:

```text
4860AD9409671EDFA8FAF5E51AF781E33762691F0CE09D0A4FF96738A252FB86
```

No dependency file changed and no package was installed.

## 6. Final Schema evidence

Schema file count remains `11`.

| Schema | Final SHA256 |
|---|---|
| `candidates.schema.json` | `3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2` |
| `common.schema.json` | `83FE17127A545D168A16F58911564E53D2E17AFF826B6D34437D873ECF8E75BE` |
| `fixture-case.schema.json` | `630E57E7F27A660F388407A8FF1B81D851B8B3A047E5B98DCB70E1920177E45A` |

The other eight Schema hashes remain identical to the execution baseline.

The registry gate independently proves:

```text
Draft 2020-12 Schema validation: pass
unique $id and local refs: pass
artifact schema registry entries: 9
fixture schema registry entry: present
Schema files: 11
format capability: pass through the existing registry self-check
```

No validator or registry implementation changed.

## 7. Fixture-first Red → Green

Exact command for both phases:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases -v
```

### 7.1 Uncommitted test-design iteration

The first complete draft run produced:

```text
tests: 115
passed: 89
failures: 26
errors: 0
exit: 1
```

Three missing-field cases were accidentally satisfied by an old `oneOf`
branch's generic `required` leaf. Before C3 was committed, only those three
assertions were tightened to require the new contract to remove the old
location-level `additionalProperties` misclassification.

No Schema, validator, fixture, product contract, test name, or test count
changed. This was test construction inside C3, not a correction to a
committed red.

An earlier attempt to capture the same command through a PowerShell variable
was interrupted because Windows PowerShell represented unittest stderr as a
native-command error record. The command was then run directly, without
changing its characters or the test file, for the measured complete results.

### 7.2 Committed C3 valid red

Measured result:

```text
tests: 115
existing WU1 tests: 82 passed
WU1C tests: 33
WU1C current-compatible passes: 4
WU1C expected assertion failures: 29
unexpected errors: 0
exit: 1
summary: FAILED (failures=29)
```

The four current-compatible passes were:

```text
CP-01 legacy candidate remains valid
CP-09 provider-native top-level field remains rejected
FXSRC-05 commercial_live remains rejected as a fixture kind
FXSRC-06 temporary_capture remains rejected as a fixture kind
```

The 29 red IDs comprised:

```text
CP-02 through CP-08, and CP-10                       8
LOC-01 through LOC-09                               9
POL-01 through POL-08                               8
FXSRC-01 through FXSRC-04                           4
total                                               29
```

All failures were `AssertionError` contract gaps. Import, dependency, path,
syntax, malformed-input, and unexpected-exception counts were all zero.

### 7.3 C4 green

Only these files changed:

```text
schemas/common.schema.json
schemas/candidates.schema.json
schemas/fixture-case.schema.json
```

The character-identical command produced:

```text
Ran 115 tests
passed: 115
failures: 0
errors: 0
exit: 0
summary: OK
```

Existing tests, WU1C tests, validators, and fixtures were not modified in C4.
The independent fixture check returned:

```text
fixtures=6 documents=38 dirty_cases=6
exit=0
```

## 8. Full WU1C verification entry

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu1c.ps1
```

The entry actually performs:

1. project `.venv` interpreter, prefix, and site-packages checks;
2. the exact 115-test explicit suite;
3. independent default discovery of 82 tests;
4. 11-Schema registry and format checks;
5. all existing fixtures with exact 6/38/6 counts;
6. frozen project, validator, WU1R, dependency, and fixture-tree hashes;
7. nine-path WU1C scope enforcement;
8. C0-C6 commit-message prefix enforcement;
9. fallback, guessed-CRS/provider, commercial endpoint, real-anchor, and
   secret scans;
10. deterministic nonzero exit on any failed gate.

The entry does not call `scripts/verify_wu1.ps1`, a map API, or a nested
PowerShell command.

First pre-commit C5 acceptance run:

```text
exit: 0
schemas: 11
explicit tests: 115
default tests: 82
fixtures: 6
documents: 38
dirty cases: 6
criteria inputs: 18
```

Independent post-C5-commit rerun:

```text
exit: 0
schemas: 11
explicit tests: 115
default tests: 82
fixtures: 6
documents: 38
dirty cases: 6
temporary residue: 0
```

## 9. Contract behavior verified

Candidate/provider cases prove:

- provider name, record ID, record type, category code/label, explicit
  external status, and data policy are representable;
- categories are non-empty and closed;
- reported status requires a code;
- not-reported status forbids invented code/label fields;
- provider data at candidate top level remains rejected.

Location cases prove:

- provider-backed coordinates accept exactly `WGS84`, `GCJ-02`, or `BD-09`;
- provider-backed coordinates require CRS and non-empty local source refs;
- unknown CRS is rejected as a coordinate CRS;
- unknown CRS is representable only as `unresolved` with
  `reason: crs_unknown` and source refs;
- legacy candidates without provider remain valid without acquiring an
  implied CRS.

Policy cases prove:

- commercial live, temporary capture, open-data anchor,
  provider-authorized anchor, synthetic fixture, and user-supplied anchor
  combinations are closed;
- temporary capture cannot enable replay;
- open-data anchors require complete license metadata;
- authorization and user-control references use non-secret closed patterns.

Fixture-source cases prove:

- open, explicitly authorized-provider, synthetic, and user-controlled
  persistent fixture metadata is representable;
- `commercial_live` and `temporary_capture` have no fixture-source branch.

Schema acceptance proves structure only. It does not prove source truth,
license or authorization validity, coordinate correctness, evidence support,
feasibility, route quality, or planning behavior.

## 10. Source research evidence

`docs/real-world-source-policy.md` contains ten links to official provider,
official project, or official license pages covering:

```text
高德 POI and route documentation and service terms
百度 place documentation and platform terms
腾讯 Web Service documentation and terms
OpenStreetMap copyright/license
Nominatim usage policy
OSRM HTTP API documentation
```

It records accessible pages, later timeouts, unverified questions, the
retrieval date, and the non-legal-advice boundary. It selects no production
provider.

The policy permits persistent replay only for:

- open data with complete license obligations;
- explicitly provider-authorized data within authorization scope;
- deterministic synthetic data;
- user-supplied data within explicit user control.

Commercial live data has no default persistence or fixture right.

## 11. R10 and scope audit

Measured or enforced results:

```text
silent fallback / default_when_missing / warning_as_pass: 0
infer_* / guess_* executable logic: 0
commercial map endpoints in executable WU1C surface: 0
real Jiangxi anchor names in structural test/Schema surface: 0
potential secret assignments or private-key markers: 0
source/adapter implementation changes: 0
validator changes: 0
existing fixture changes: 0
new dependencies: 0
new Schema files: 0
remote count: 0
stash count: 0
temporary verification residue: 0
```

Documentation mentions guessing, APIs, and provider terms only to prohibit or
analyze them. The executable scan excludes those explanatory prose matches
and scans the Schema/test surface where such behavior could be encoded.

No LLM is recorded as a source. No provider name supplies a default CRS. No
commercial response is present. No example is represented as a real
observation.

## 12. Completion criteria

1. ✓ WU1C started from approved clean `4939435` on `main`, with zero remotes
   and stashes.
2. ✓ Handbook fetch/reconciliation and all eight mandatory rereads completed;
   handbook remained unchanged.
3. ✓ The approved Plan was committed alone and retains the approved SHA256.
4. ✓ C0-C6 are linear and each commit message matches its single
   responsibility.
5. ✓ Final changed paths equal the exact nine-path whitelist.
6. ✓ `PLAN.md`, WU0/WU1/WU1R history, Plans, Reviews, and protected paths are
   unchanged.
7. ✓ No dependency, twelfth Schema, artifact type, validator logic, existing
   test, existing fixture, adapter, API call, or real data was added.
8. ✓ Candidate provider identity, native metadata, explicit external status,
   and data policy are structurally expressible.
9. ✓ Provider-backed coordinates require a supported CRS and non-empty local
   source refs; unknown CRS cannot become coordinates.
10. ✓ Legacy candidates remain structurally valid without an inferred CRS,
    while the provider branch activates strict location requirements.
11. ✓ Source class, capture, storage, replay, fixture, authorization, and
    license fields are orthogonal and closed.
12. ✓ Open, authorized-provider, synthetic, and user-controlled fixture
    metadata is expressible; live-commercial and temporary fixture kinds are
    rejected.
13. ✓ C3 recorded valid `115 / 82 existing pass / 4 WU1C pass / 29 expected
    failures / 0 errors` red evidence.
14. ✓ C4 used the identical command for `115/115` green without test,
    validator, or fixture changes.
15. ✓ The final entry proves default discovery 82, Schema count 11, and
    existing fixture surface 6/38/6.
16. ✓ R10 scans found no guessed CRS/provider, silent fallback, secret,
    retained commercial response, provider-specific planner branch, or
    capability overclaim.
17. ✓ Source-policy documentation uses primary sources, records access
    results and limitations, gives no legal advice, and selects no production
    provider.
18. ✓ Review evidence covers Git, hashes, tests, scope, and scans; no remote,
    push, WU2 file, or WU2 execution exists.

Completion status count:

```text
✓ 18
⚠ 0
✗ 0
```

## 13. Review status

```text
READY_FOR_HUGIN_REVIEW
```
