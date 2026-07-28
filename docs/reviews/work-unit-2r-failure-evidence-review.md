# Work Unit 2R Failure Evidence Remediation Review

Review date: 2026-07-28

Plan:
`plans/work-unit-2r-failure-evidence-remediation.md`

Plan version: v0.1

Approved Plan SHA256:
`B457E6ECDF2CF6BEAB057BD35D761071AD6100D4926652736E3336726E3C3F95`

Review status:

```text
READY_FOR_HUGIN_REVIEW
```

This Review covers only WU2R-FER. It does not close or resume WU2R, acquire
data, create an anchor, or prove facts that were lost during the old WU2R C5
attempt.

## 1. Preserved historical state

The historical state remains:

```text
WU2:  BLOCKED
WU2R: BLOCKED
```

The original WU2R Review remains absent:

```text
docs/reviews/work-unit-2-recovery-review.md: absent
```

WU2R C0-C4 remain the same five commits ending at:

```text
bca00a4792247bcd334f1b8742d7a4fa22589b72
feat: implement candidate accounting and route guard
```

No old WU2/WU2A/WU2R Plan, decision, source policy, implementation, test,
fixture, or Review was modified.

The old C5 observation remains an incomplete historical record:

```text
acquisition terminal: internal_failure
WU2R_ACQUISITION_EXIT_CODE=1
```

Its deleted ledger still cannot independently prove physical attempts,
retry consumption, per-attempt request hash, response state, detailed
failure classification, or the complete cleanup sequence. FER does not
reconstruct those facts.

## 2. Repository and handbook gates

Execution started from:

```text
branch: main
HEAD: bca00a4792247bcd334f1b8742d7a4fa22589b72
worktree: only the approved FER Plan
remotes: 0
stashes: 0
```

The exact approved Plan hash was verified before C0 and remains unchanged.

The handbook was fetched and all eight required files were reread from
`origin/main`:

```text
local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree before/after: clean
```

Loaded paths:

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

The handbook was not modified.

## 3. Git history

Start:

```text
bca00a4792247bcd334f1b8742d7a4fa22589b72
```

Pre-C4 implementation HEAD:

```text
eb0c438d5cc1589507a24178f96e8288d57527f3
```

Linear history through C3:

```text
e0076dd103b05333780ea942181561a754923f9d docs: record failure evidence remediation plan
3bf5e45ecb7dce48f681b41033bb56420f016a23 chore: add failure evidence interface
ef1a78b41dc48e8d0db980433c4c230c4989d257 test: add failure evidence contract cases
d7b6ff20cfb7c04434f741f8085912e84396deca test: correct FE09 invalid sha256 fixture
eb0c438d5cc1589507a24178f96e8288d57527f3 feat: implement failure evidence persistence
```

C4 is the commit containing this Review:

```text
docs: prepare failure evidence remediation review
```

The concrete C4/final HEAD is obtained with `git rev-parse HEAD` after the
commit and reported in the Review handoff. A commit cannot truthfully contain
its own content-derived hash.

No commit was amended, squashed, reset, rebased, or rewritten. No push,
remote, or PR was created.

## 4. Approved C2.1 correction

The first C3 green attempt produced:

```text
tests: 10
passed: 9
failures: 1
errors: 0
exit code: 1
failed case: FE09
```

FE09 contained a 63-character `response_sha256`. The implementation correctly
rejected it and classified the inconsistent runner observation as
`ACQUISITION_INTERNAL_FAILURE`; it did not accept the malformed hash to make
the assertion pass.

Execution stopped. Hugin then explicitly approved one C2.1 test correction.
The uncommitted C3 source diff was saved with a path-limited stash containing
only:

```text
src/trip_decider/acquisition_evidence.py
```

C2.1 changed only the FE09 SHA256 literal to the valid 64-character lowercase
SHA256 for its three-byte `bad` response fixture:

```text
2f05d4b689d270cafb02285f35f44866f7dc8a2d368a3f9d1124373eeab31fb1
```

It did not change the test name, business assertion, failure classification,
hash validator, any other FE case, or implementation. C2 was not amended.

The valid red was re-established while the C3 source remained stashed. The
same source diff was then applied without conflict. After C3 committed and
the worktree was clean, the single-file stash was dropped. Final stash count
is zero.

The approved correction adds one commit. Final FER history therefore has six
commits rather than the five originally pre-registered; the repository path
whitelist remains unchanged.

## 5. C2 and C2.1 red evidence

Exact command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2r_failure_evidence -v
```

Original C2 result:

```text
tests: 10
passed: 0
failures: 0
errors: 10
exit code: 1
```

After C2.1, the character-identical command again produced:

```text
tests: 10
passed: 0
failures: 0
errors: 10
exit code: 1
```

Every error in both valid reds was:

```text
NotImplementedError:
WU2R-FER failure evidence persistence is not implemented
```

All FE01-FE10 IDs were discovered. Import, dependency, path, syntax,
malformed-test, network, assertion-failure, and other-exception counts were
zero.

## 6. C3 green evidence

The character-identical command produced:

```text
tests: 10
passed: 10
failures: 0
errors: 0
exit code: 0
network mock attempts: 0
```

No test changed in C3. `acquisition_evidence.py` has no reachable
`NotImplementedError`.

Case evidence:

| Case | Observed contract |
|---|---|
| FE01 | a transport failure and subsequent success retain two attempts, the computed request hash, exact original/retry IDs, transport code, and `same_request_sha256=true` |
| FE02 | HTTP 400 retains status/body metadata, has `ACQUISITION_HTTP_FAILURE`, and has no retry |
| FE03 | explicit invalid JSON retains response byte count/hash, records `ACQUISITION_RESPONSE_FAILURE`, and retains no body |
| FE04 | an unexpected runner exception leaves a terminal internal attempt without exception type/message or injected secret text |
| FE05 | initial primary write failure explicitly uses the emergency sink and invokes neither runner nor cleanup |
| FE06 | failure of both started sinks returns `durable_evidence=false` and invokes neither runner nor cleanup |
| FE07 | cleanup failure preserves the original HTTP failure and adds `ACQUISITION_CLEANUP_FAILURE` with residue evidence |
| FE08 | transport retry exhaustion contains exactly two attempts and one resolving retry relation |
| FE09 | terminal primary write failure preserves HTTP evidence in the emergency ledger and adds `ACQUISITION_LEDGER_FAILURE` |
| FE10 | clean success is silent, reloadable, atomically persisted, and leaves zero atomic temporary residue |

The six closed classifications are present and exercised:

```text
ACQUISITION_TRANSPORT_FAILURE
ACQUISITION_HTTP_FAILURE
ACQUISITION_RESPONSE_FAILURE
ACQUISITION_LEDGER_FAILURE
ACQUISITION_CLEANUP_FAILURE
ACQUISITION_INTERNAL_FAILURE
```

Known HTTP, response, ledger, and cleanup states are not collapsed to
internal failure.

## 7. Ledger, retry, cleanup, and sink design evidence

The implementation sequence is:

```text
validate
-> hash request bytes
-> atomically persist started envelope
-> call injected runner
-> validate attempts/retries and classify
-> persist pre-cleanup terminal observation
-> call injected cleanup
-> persist final terminal envelope
```

The module contains no HTTP client, endpoint, provider logic, socket use, or
retry scheduler. Runner and cleanup effects are injected. Retry relations are
validated but never scheduled by FER.

Each retry requires:

```text
original_attempt_id
retry_attempt_id
same_request_sha256=true
retry_reason=transport_failure
```

Both IDs must resolve in order, both attempt hashes must equal the computed
request hash, and only an explicitly scheduled transport failure may be an
original.

Primary persistence uses the caller-supplied ignored-runtime path.
Emergency persistence uses a separately supplied system-temporary path and
is marked with:

```text
emergency_attempted
emergency_status
emergency_path_kind
```

The emergency sink is not silent. If both started sinks fail, the runner is
not invoked and the result does not claim durable evidence.

Cleanup evidence records only allowlisted resource kinds, booleans, status,
and residue count. No raw filesystem path or content is retained. Cleanup
failure is terminal and does not erase the underlying acquisition failure.

## 8. Full regression

Command run after C3 implementation and independently again before C4:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_harness tests.test_wu2_recovery tests.test_wu2r_failure_evidence -v
```

Independent C4 rerun:

```text
existing tests: 159
FER tests: 10
total: 169
passed: 169
failures: 0
errors: 0
exit code: 0
```

All FER tests patch `socket.create_connection` and assert a call count of
zero. The implementation has no network import or call. No map-data or other
data-source call occurred in FER.

## 9. Scope and diff evidence

Pre-C4 diff:

```text
plans/work-unit-2r-failure-evidence-remediation.md | 827 insertions
src/trip_decider/acquisition_evidence.py           | 769 insertions
tests/test_wu2r_failure_evidence.py                | 609 insertions
3 files changed, 2205 insertions
```

C4 adds only:

```text
docs/reviews/work-unit-2r-failure-evidence-review.md
```

Final changed-path set is exactly the four-path whitelist:

```text
plans/work-unit-2r-failure-evidence-remediation.md
src/trip_decider/acquisition_evidence.py
tests/test_wu2r_failure_evidence.py
docs/reviews/work-unit-2r-failure-evidence-review.md
```

Diffs are zero for:

```text
PLAN.md
.gitignore
pyproject.toml
requirements.lock
scripts/acquisition_harness.py
src/trip_decider/recovery.py
schemas/
fixtures/
all existing tests
```

No dependency, runtime ledger, raw data, anchor, fixture, or generated
temporary Python file was added.

## 10. Frozen hash evidence

Targeted inputs after C3:

| Path | SHA256 |
|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `plans/work-unit-2-recovery.md` | `D6F6C0A662969D5AE810291CE746F4530594DC9C2A0E018C5FC41122AE606AF8` |
| `docs/wu2-recovery-source-and-capture.md` | `B34ED5EB0FA570A11E0B43E9F0A714C30F4A44FC53EE3D5D38302074B1DE9CA1` |
| `docs/wu2a-resume-decision.md` | `417F4E89A059CA99A5E96E960B839FA0297935F2438D76B100E7F8F30313B40A` |
| `src/trip_decider/recovery.py` | `8105424CAEBD020BDAFBA4048477BF92846AE2B27090CB3EFAFC7C40B6183614` |
| `scripts/acquisition_harness.py` | `AE6487D7F35E6A1CE351C07FD83DA219214705F1D3AC00611F5D7B9EF49559F9` |
| `tests/test_wu2_recovery.py` | `8D1341E4A57EA008152059A670CF4876EA48E8D118DF6E82EF15850549E4F43E` |
| FER Plan | `B457E6ECDF2CF6BEAB057BD35D761071AD6100D4926652736E3336726E3C3F95` |

All 11 Schema hashes equal their Plan baselines:

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

## 11. R10 and residue checks

Source scans returned zero hits for:

```text
infer_*
guess_*
silent_fallback
default_when_missing
warning-as-pass patterns
urllib / requests / httpx / socket / subprocess
Invoke-Expression
NotImplementedError
response_body
query_text
coordinates
authorization / cookie / password / api_key
```

The ledger serializes hashes and byte counts, never request or response
bodies. FE04 proves exception type/message and injected secret text do not
enter the document. FE10 proves stdout/stderr remain empty.

Measured after the test runs:

```text
trip-decider-fer-test-* temporary directories: 0
runtime/wu2r-failure-evidence exists: false
stashes: 0
remotes: 0
```

No secret, raw bytes, coordinate list, provider response, anchor, fixture, or
runtime evidence entered Git.

## 12. Completion criteria

1. ✓ 已完成 — execution began at the approved `main` HEAD with only the
   approved Plan, zero remotes/stashes, and the exact Plan hash.
2. ✓ 已完成 — handbook fetch/reconciliation and eight reads were recorded;
   local/origin HEAD and worktree remained unchanged.
3. ✓ 已完成 — WU2/WU2R remain `BLOCKED`; old history and documents are
   unchanged.
4. ✓ 已完成 — all seven targeted frozen inputs and 11 Schemas match; the old
   WU2R Review remains absent.
5. ⚠ 已知限制 — final diff is exactly the four-path whitelist, but final
   history has six commits rather than five because Hugin explicitly approved
   the separate C2.1 FE09 test correction. No commit was rewritten and all six
   responsibilities remain isolated.
6. ✓ 已完成 — harness, recovery, adapters, Schemas, validators, existing
   fixtures/tests, dependencies, lock, `.gitignore`, and `PLAN.md` have zero
   diff.
7. ✓ 已完成 — the started envelope is persisted before runner invocation;
   failure of both started sinks prevents runner/transport execution.
8. ✓ 已完成 — all six failure classes are deterministic and known failures
   are not collapsed into internal failure.
9. ✓ 已完成 — terminal evidence preserves request hash, observed metadata,
   attempts, failure ordering, persistence state, and genuine nulls.
10. ✓ 已完成 — retry IDs, order, hash equality, reason, and transport-only
    eligibility are validated.
11. ✓ 已完成 — primary failure visibly selects the emergency sink; no silent
    fallback or false durability claim exists.
12. ✓ 已完成 — cleanup state/residue are explicit and cleanup failure
    preserves the underlying failure.
13. ✓ 已完成 — C2 and C2.1 both have valid 10-error interface reds; C3 uses
    the character-identical command for 10/10 green without a test change.
14. ✓ 已完成 — independent full regression is 169 passed, zero
    failures/errors, zero FER network mock attempts, and zero unintended
    temporary residue.
15. ✓ 已完成 — R10 scans and tests find no raw body, secret, coordinate list,
    third-party exception text, guessed classification, silent fallback,
    warning-as-pass, anchor, fixture, or capability overclaim.
16. ✓ 已完成 — this Review provides Git, hash, red/green, classification,
    retry, cleanup, sink, scope, and all 16 statuses, then stops without
    resuming WU2R or starting WU3/WU5.

The single warning is the explicitly approved, isolated C2.1 correction. It
does not leave a missing behavior or failing verification.

## 13. Final boundary

FER establishes only this verified statement:

> Offline-injected future acquisition failures can persist explicit,
> sanitized, independently reviewable failure evidence, including retry,
> persistence, and cleanup incidents.

It does not establish:

- what happened in the old deleted WU2R C5 ledger;
- that OSM/Overpass acquisition now succeeds;
- that an anchor or fixture exists;
- that WU2R C5/C6 may resume;
- that WU3 or WU5 may start.

Final status:

```text
READY_FOR_HUGIN_REVIEW
```
