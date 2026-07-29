# Work Unit 7 Live Place Resolution Review

## 1. Outcome

Review date: 2026-07-29.

| Dimension | Status |
| --- | --- |
| Implementation status | `STAGE_A_SYNTHETIC_OFFLINE_IMPLEMENTATION_COMPLETE` |
| Provider authorization status | `AMAP_PERSISTENCE_POLICY_UNRESOLVED` |
| Live smoke status | `LIVE_SMOKE_NOT_AUTHORIZED_STORAGE_POLICY_UNRESOLVED` |
| Final Work Unit status | `BLOCKED_PENDING_AMAP_STORAGE_CONFIRMATION` |

Stage A is implemented and independently green with handwritten synthetic
provider-shaped data. It does not establish that AMap permits persistence,
does not establish that the real API works, and does not verify a real place.
No real network request, real AMap output, credential read, or LLM call
occurred. The Work Unit is therefore intentionally not
`READY_FOR_HUGIN_REVIEW`.

## 2. Approved baseline and context

- Approved Plan: `plans/work-unit-7-live-place-resolution.md`, v0.3.
- Approved and final Plan SHA256:
  `CADA19D6BE716842AE6893A6793E31B0DB90B652903CBCE1388DEEF6073A815D`.
- Start branch/HEAD: `main` /
  `3d3336b96453150b952a2b83fb49c34fe0e94368`.
- Pre-execution worktree: only the approved untracked Plan.
- Baseline: `210/210` tests, `11` schemas, fixtures/documents/dirty cases
  `7/40/7`.
- Remotes/stashes before and after execution: `0/0`.
- Handbook local/origin:
  `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`; ahead/behind `0/0`;
  worktree clean.
- Rules reread from `origin/main`: `STATE.md`, `INDEX.md`, `SUMMARY.md`,
  context injection, R10, PER, Scope, and Fixture-first.

Two exploratory baseline commands were not accepted as baseline evidence.
Plain `unittest discover -s tests -v` lacked the required project
`PYTHONPATH` and failed imports. The historical WU6 verifier correctly
rejected the new untracked WU7 Plan as outside WU6 scope. The valid baseline
was then rerun with project `.venv`, `PYTHONPATH=src`, and the frozen 210-test
module list; it passed `210/210`. Neither invalid command changed files.

## 3. Git and scope evidence

Before C5, the linear history from the approved start was:

```text
0356bd7 docs: record WU7 live place resolution plan
5b67c63 chore: add live place resolution interface
788a450 test: add failing live place resolution cases
896480f feat: implement structured live place resolution
33ef714 chore: add live place resolution run and verification entries
```

C5 adds only this Review with:

```text
docs: prepare WU7 live place resolution review
```

The pre-C5 diff was five files, 3,048 insertions. The final six-path scope is:

```text
plans/work-unit-7-live-place-resolution.md
src/trip_decider/live_place_resolution.py
tests/test_wu7_live_place_resolution.py
scripts/run_live_place_resolution.ps1
scripts/verify_wu7_live_place_resolution.ps1
docs/reviews/work-unit-7-live-place-resolution-review.md
```

No Schema, fixture, existing test, existing runtime, validator, dependency,
README, `PLAN.md`, handbook file, or historical verifier changed. No remote
was created, nothing was pushed, and no history was amended, squashed, reset,
or rebased.

Key final content hashes before this Review:

| Path | SHA256 |
| --- | --- |
| WU7 Plan | `CADA19D6BE716842AE6893A6793E31B0DB90B652903CBCE1388DEEF6073A815D` |
| WU7 runtime | `34E7A01CD0FBA5EC50F24BFF872226F5D9E4E9021B646F3019AC93443FDB04C1` |
| WU7 tests | `443905617A067838C9BED34B63308F8F23403A373425E4FE53BEA523840A0962` |
| Live-blocking run entry | `1547DB9A925875324F948BD53DFDC2CECF086928290130955DD1A96DC7284D34` |
| WU7 verifier | `1C8F2002262660D361DCE8B55327CFBA72E38015BE82835879B865EDAD42055C` |
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `pyproject.toml` | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` |
| `requirements.lock` | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` |

All 11 Schema hashes remained equal to the pre-WU7 snapshot.

## 4. Implemented Stage A boundary

The implementation provides only the approved synthetic offline boundary:

- explicit structured input compilation into deterministic
  `request.yaml`, `constraint-parse.json`, and `constraints.yaml`;
- individual Schema validation and a CLOSED bundle rooted at
  `constraints.yaml`;
- de-keyed injected district and POI request descriptors;
- strict handwritten synthetic AMap-shaped response parsing;
- exact comparison using only Unicode NFC, outer trim, and case-fold;
- official-ID-shaped synthetic provider identity, `provider.name=amap`,
  `record_type=poi`, and `crs=GCJ-02`;
- matched/ambiguous/unmatched accounting without fuzzy, first, nearest,
  popularity, alias, or city-knowledge selection;
- optional explicit selection of a displayed Candidate ID or `0`;
- all alternatives preserved in Candidate output and selection audit;
- the existing FER as the only acquisition failure-evidence implementation;
- the downstream-compatible four-file Recovery boundary;
- synthetic normalized snapshot replay;
- same-parent staging, atomic install, rollback, nonempty-root refusal, and
  residue checks.

Every persisted provider-shaped value has `synthetic_test_data=true` and a
synthetic data policy. Evidence Runtime accepts the generated Recovery
boundary and emits candidate-local facts whose support, display, and
freshness remain unknown. The tested input includes an unmatched seed, so
overall `generation_allowed=false`.

The implementation imports no HTTP client or socket module, contains no AMap
host, and does not read `AMAP_WEB_SERVICE_KEY`. The PowerShell run entry also
does not read that variable. Its current behavior is an unconditional
pre-live gate:

```text
AMAP_DURABLE_STORAGE_CONFIRMATION_MISSING
```

with exit code `5`, no stdout, no output root, and exact `PYTHONPATH`
restoration.

## 5. Fixture-first Red → Green

The C2 command was:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu7_live_place_resolution -v
```

Measured C2 Red:

```text
tests: 6
passed: 0
failures: 0
errors: 6
cause: explicit NotImplementedError
exit code: 1
network attempts: 0
LLM calls: 0
```

All six errors originated at the two approved public stubs. Import,
dependency, path, syntax, malformed input, unexpected exception, network,
and LLM error counts were zero.

C3 used the character-identical command. Its first implementation run was
`5 passed / 1 failure / 0 errors`: AP04 showed that Candidate bytes still
included interactive selection state through the snapshot hash. This was an
implementation defect, not a test-data correction. Before C3 commit, the
Candidate input hash was changed to exclude interaction/selection, while
selection continued to affect only seed accounting and selection audit.
The same command then passed:

```text
tests: 6
passed: 6
failures: 0
errors: 0
network attempts: 0
LLM calls: 0
```

The full C3 regression passed `216/216` in 23.728 seconds. The committed C4
verification rerun passed `216/216` in 23.591 seconds.

## 6. Verification entry

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu7_live_place_resolution.ps1
```

The first two pre-C4-commit verifier attempts stopped in source scanning:
one substring rule confused the field/member name `requests` with the Python
network library, and one self-scan found the verifier's own forbidden-token
literal. The corrections narrowed the rule to actual import statements and
removed the verifier itself from the scanned production/test/run-entry set.
They changed no runtime, test, provider, network, secret, Schema, fixture, or
count gate. The corrected run passed before C4 commit; the same committed
entry independently passed again before C5.

Final measured summary:

```text
WU7_VERIFICATION=PASS
TESTS=216
SCHEMAS=11
FIXTURES_DOCUMENTS_DIRTY_CASES=7/40/7
REAL_NETWORK_CALLS=0
REAL_AMAP_OUTPUT_FILES=0
LLM_CALLS=0
TEMPORARY_RESIDUE=0
LIVE_SMOKE_STATUS=LIVE_SMOKE_NOT_AUTHORIZED_STORAGE_POLICY_UNRESOLVED
FINAL_STATUS=BLOCKED_PENDING_AMAP_STORAGE_CONFIRMATION
```

The entry also passed project `.venv`/prefix/site-packages checks, exact
21-package lock comparison, `pip check`, Plan/runtime/test hashes,
six-path scope, exact commit prefix, protected-input comparison, Schema
count, diff checks, synthetic contracts, FER secrecy, transaction rollback,
environment restoration, secret/fallback/network-import scans, and live-gate
fault injection with a sentinel environment key.

## 7. R10 self-review

- Silent fallback: none.
- Network fallback or second provider: none.
- Credential access: none in runtime or run entry.
- Sentinel leakage: absent from FER, files, problems, summaries, stdout, and
  stderr in AP02/AP05.
- LLM inference or evidence: none.
- Synthetic data overstated as real: no; manifests explicitly deny live
  evidence and provider authorization.
- Identity choice by first/rank/distance/popularity: none.
- Unmatched placeholder: none.
- Provider/parse failure converted to unmatched: none; it terminates through
  existing FER or a stable provider-response problem.
- Evidence support upgraded above unknown: none.
- `generation_allowed` upgraded by this stage: no; WU7 summary remains false.
- Output overwrite or partial success: rejected/rolled back.
- Runtime/test expected self-generation: none; synthetic expected values are
  handwritten in tests.
- Secret or personal provider correspondence committed: none.
- Schema, fixture, historical verifier, dependency, or frozen product Plan
  modification: none.

## 8. Completion determinations

1. ✓ Approved v0.3 Plan hash, handbook state, baseline, and six-path scope
   matched.
2. ✓ Endpoint-shape, identity, GCJ-02, provider, FER, and downstream contracts
   remained within the audited compatibility boundary.
3. ⚠ `AMAP_PERSISTENCE_POLICY_UNRESOLVED` remains active; this is the intended
   provider-policy blocker.
4. ✓ Stage A used only synthetic data; network and LLM calls were zero.
5. ✓ Planning artifacts were deterministic, Schema-valid, CLOSED, and kept
   `constraints.yaml` as solver SSOT.
6. ✓ Provider identities and all exact alternatives survived without rank,
   fuzzy, first-result, or cross-provider choice.
7. ✓ Existing FER received only de-keyed descriptors; the sentinel key reached
   no persisted or displayed surface.
8. ✓ Synthetic transaction and replay were deterministic and were not called
   live evidence or provider authorization.
9. ✓ Red was exactly six interface errors; Green was 6/6; regression was
   216/216; counts remained 11 and 7/40/7.
10. ✓ Before confirmation, real calls/files were zero and the live-smoke state
    was the policy-unresolved token.
11. ✓ No official confirmation or personal/account/contact/transcript data was
    recorded.
12. ✓ No P1/P2/P3 branch was selected without an official answer.
13. ✓ P1 evidence was not claimed; the final status remains honestly blocking.
14. ✓ Git, hashes, tests, live gate, secrets, rollback, policy, and residue
    were independently checked, and execution stops here.

## 9. Required next authority

The remaining blocker is external and intentional:

```text
AMAP_DURABLE_STORAGE_CONFIRMATION_REQUIRED_BEFORE_LIVE_EXECUTION
```

Only a safe summary of an adequate official AMap response may support a later
P1/P2/P3 decision. P1 would still require separate Stage B approval before a
real request. P2 requires a revised Plan. P3 remains provider-policy blocked.
This Review does not authorize Stage B, a live smoke, persistence of real
provider data, routes, Planner/HTML integration, or another Work Unit.

```text
BLOCKED_PENDING_AMAP_STORAGE_CONFIRMATION
```
