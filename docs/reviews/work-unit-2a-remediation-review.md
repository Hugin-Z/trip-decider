# Work Unit 2A Remediation Review

Review date: 2026-07-28

Review status:

```text
READY_FOR_HUGIN_REVIEW
```

## 1. Outcome and preserved history

WU2A-R implemented only the acquisition harness failure-path evidence
contract. It did not acquire data, create an anchor or fixture, modify a
provider adapter, or resume either WU2 or WU2A.

Historical states remain:

```text
WU2:  BLOCKED
WU2A: INVESTIGATION_BLOCKED
```

The WU2/WU2A history immediately before WU2A-R remains:

| Commit | Message |
|---|---|
| `4a3242f43954f805ed9faf8e03c1b6a3deba93e3` | `docs: record approved WU2 plan` |
| `a4a91fcdc243cdd05566e714836f9ea388fdd7fa` | `docs: record WU2 source and capture gate` |
| `cd4f577cb83af8e7508f8ec35c5dd61a58e83ce2` | `chore: add WU2 ingestion interfaces` |
| `d01d198aab219a5e8b9003502553b6408bd50517` | `test: add failing WU2 adapter contract cases` |
| `352dbbcd0b73b3104c85cd02c38442748dcd4b96` | `feat: implement open-data artifact adapters` |
| `0327e9fffb0cd37ad6ca6b1baa1041a10ebfd61a` | `docs: record approved anchor recovery plan` |
| `0a19f5ea9053f018e5d3ba341500c97556fb65b7` | `docs: record open-data investigation` |

`docs/reviews/work-unit-2-review.md` remains absent. No WU2 Review was
backfilled.

## 2. Git evidence

WU2A-R start:

```text
0a19f5ea9053f018e5d3ba341500c97556fb65b7
```

Review-preparation HEAD:

```text
35bb3f78ac92923043f827c934a2808f326150c2
```

Linear history through C3:

| Step | Commit | Message |
|---|---|---|
| C0 | `e0f3296dee0f2fc1495e209e14b16b9d4cac03c3` | `docs: record acquisition remediation plan` |
| C1 | `c661a1dd24dfa9719bc49cbddac14c585127e090` | `chore: add acquisition harness interface` |
| C2 | `a1d9382b83823dac8607a30e9bb5b1a2e58175f2` | `test: add acquisition failure contract cases` |
| C2.1 | `be9dfd93673c5c32ad0e7ff45f391cefc40e31f3` | `test: correct A06 unreadable HTTP body fixture` |
| C3 | `35bb3f78ac92923043f827c934a2808f326150c2` | `feat: fix acquisition ledger and error classification` |
| C4 | this review file | `docs: prepare acquisition remediation review` |

C2 was not amended or rewritten. C2.1 is the separately approved test-data
correction. The C4 commit hash is reported by the post-commit handoff because
a commit cannot truthfully contain its own hash without rewriting itself.

Pre-C4 diff stat:

```text
plans/work-unit-2a-remediation.md      | 755
scripts/acquisition_harness.py         | 431
tests/test_wu2a_acquisition_harness.py | 400
3 files changed, 1586 insertions(+)
```

The final C4 diff adds only this Review file.

## 3. Scope evidence

Approved four-path whitelist:

```text
plans/work-unit-2a-remediation.md
scripts/acquisition_harness.py
tests/test_wu2a_acquisition_harness.py
docs/reviews/work-unit-2a-remediation-review.md
```

Before C4, `git diff --name-only <start>..HEAD` returned exactly the first
three paths. C4 adds only the fourth. No existing tracked file outside the
whitelist changed.

Protected surfaces remained untouched:

- `PLAN.md`;
- WU2 and WU2A Plans and decision documents;
- `src/trip_decider/` including adapters and validators;
- all 11 Schema files;
- `fixtures/`;
- `pyproject.toml` and `requirements.lock`;
- source policy documents;
- handbook;
- Git remote configuration.

No dependency was added. Hashes:

| Path | SHA256 |
|---|---|
| `pyproject.toml` | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` |
| `requirements.lock` | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` |

## 4. C2 original Red

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2a_acquisition_harness -v
```

Actual result after C2:

```text
Ran 10 tests
passed: 0
failures: 0
errors: 10
exit code: 1
```

All ten errors were raised at the approved public `run_acquisition` interface:

```text
NotImplementedError: WU2A-R acquisition behavior is not implemented
```

Import, path, dependency, syntax, network and unexpected errors were zero.

## 5. C3 initial attempts and blocking discovery

The first C3 run used the identical command and returned:

```text
Ran 10 tests
passed: 9
failures: 1
errors: 0
exit code: 1
```

Only A06 failed:

```text
expected response_bytes: null
actual response_bytes: 0
```

An uncommitted check for `error.fp is None` was added within the approved C3
file, but a second run correctly showed the same 9/1 result. Read-only
inspection then established the reason:

```python
def HTTPError.__init__(..., fp):
    self.fp = fp
    if fp is None:
        fp = io.BytesIO()
    self.__super_init(fp, ...)
```

On Python 3.11 both inputs below became a readable `BytesIO` and returned
`b""`:

```text
HTTPError(fp=None)
HTTPError(fp=BytesIO(b""))
```

Therefore the original A06 fake did not represent its intended unreadable
body. Treating every readable empty HTTP error body as unknown would have
weakened the approved contract, so execution stopped before C3 commit.

## 6. Approved C2.1 correction

Hugin approved one test-only correction and a path-limited stash.

The uncommitted C3 implementation was saved with:

```powershell
git stash push -m "wu2ar-c3-before-a06-test-correction" -- scripts/acquisition_harness.py
```

The stash contained exactly:

```text
scripts/acquisition_harness.py
```

C2.1 modified only the A06 input inside
`tests/test_wu2a_acquisition_harness.py`:

- a local `BytesIO` subclass raises `OSError` from `read()`;
- the `HTTPError` receives that stream;
- the stream contains bytes but cannot be read;
- the test name, expected `null` fields and all assertions remain unchanged;
- A01—A05 and A07—A10 remain unchanged;
- the test count remains 10.

Commit:

```text
be9dfd93673c5c32ad0e7ff45f391cefc40e31f3
test: correct A06 unreadable HTTP body fixture
```

This correction changed fixture construction only. It did not change HTTP
body semantics, the Plan, the harness contract or an existing C2 commit.

## 7. C2.1 corrected Red

Before restoring C3, the identical command was rerun.

Actual result:

```text
Ran 10 tests
passed: 0
failures: 0
errors: 10
exit code: 1
```

Every error was again the approved interface `NotImplementedError`. Import,
path, dependency, syntax, malformed-input and unexpected errors were zero.

The C3 stash was then restored with `git stash apply`, not `pop`. Verification
showed:

```text
modified worktree path: scripts/acquisition_harness.py
test worktree: clean
conflicts: 0
stash retained: yes
```

## 8. C3 Green and body semantics

After restoration, the same command returned:

```text
Ran 10 tests
OK
passed: 10
failures: 0
errors: 0
exit code: 0
```

The result distinguishes:

| Case | Observed body | Stored metadata |
|---|---|---|
| A06 | stream exists but `read()` raises | `response_bytes=null`, `response_sha256=null` |
| A10 | readable `b""` | `response_bytes=0`, SHA256 of empty bytes |

The implementation was not changed to treat readable empty bodies as
unknown. C3 changed only `scripts/acquisition_harness.py` and C3 commit
`35bb3f78ac92923043f827c934a2808f326150c2` contains no test change.

After C3 committed and the worktree was clean, the retained stash was checked
again. It still contained only the harness path and was dropped under the
explicit approval. Final stash count is zero.

## 9. Full regression

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_harness -v
```

C3 result:

```text
Ran 143 tests in 11.468s
OK
exit code: 0
```

C4 independent rerun:

```text
Ran 143 tests in 11.496s
OK
exit code: 0
```

C4 also independently reran the focused command:

```text
Ran 10 tests in 0.091s
OK
exit code: 0
```

## 10. Contract evidence

### 10.1 Ledger-first ordering

Source ordering:

```text
line 125: persist started ledger
line 130: call injected transport
line 131: catch HTTPError
line 148: catch URLError
line 169: finally
line 175/177: persist terminal ledger
```

An independent offline probe made the injected transport read the ledger at
the instant of each call. It reported:

```json
{
  "network_attempts": 0,
  "injected_transport_calls": 2,
  "events": [
    {
      "call": 1,
      "attempt_count": 1,
      "last_status": "started",
      "last_completed_at": null,
      "retry_count": 0
    },
    {
      "call": 2,
      "attempt_count": 2,
      "last_status": "started",
      "last_completed_at": null,
      "retry_count": 1
    }
  ],
  "final_statuses": [
    "transport_failure",
    "succeeded"
  ]
}
```

Both final attempts had non-null `completed_at`.

### 10.2 HTTPError classification

`except HTTPError` appears before `except URLError`. Behavior evidence:

- A01: HTTP 400, one transport call, no retry, body metadata retained;
- A08: HTTP 429, one transport call despite retry budget 3;
- A07: returned HTTP 500, one transport call, no retry.

All use `status=http_response_failure`,
`error_class=http_response_failure` and
`retry_decision=not_retryable_http`.

### 10.3 Transport-only retry

A02, A03, A04 and A09 cover timeout, DNS, exhaustion and connection reset.
The independent probe returned:

```json
{
  "original_attempt_id": "attempt-0001",
  "retry_attempt_id": "attempt-0002",
  "same_request_sha256": true,
  "reason": "transport_failure"
}
```

No HTTP or internal failure creates a retry relation.

### 10.4 Null preservation and exception privacy

- unreadable HTTP body metadata remains explicit JSON `null`;
- readable empty response metadata records zero bytes and the empty SHA256;
- private DNS, connection, timeout, postprocess and HTTP reason strings are
  not copied into the ledger;
- response bodies are measured but not stored;
- unknown fields are not reconstructed from logs, exception strings, memory
  or `docs/wu2a-anchor-decision.md`.

## 11. Temporary files and network

The harness accepts only an injected transport. It contains no `urlopen`,
`requests`, `httpx` or provider endpoint implementation.

Measured results:

```text
real network attempts: 0
map API calls: 0
probe atomic *.tmp residue: 0
probe temporary-directory residue: 0
test temporary-directory residue: 0
committed raw responses: 0
committed anchors: 0
new fixture directories: 0
```

## 12. Hash evidence

Approved WU2A-R Plan:

```text
FD0DA659873A275944DE7FCC9C1E4D1D27EE9BD7F61F40F4A3371493173008B9
```

Implemented surfaces:

| Path | SHA256 |
|---|---|
| `scripts/acquisition_harness.py` | `AE6487D7F35E6A1CE351C07FD83DA219214705F1D3AC00611F5D7B9EF49559F9` |
| `tests/test_wu2a_acquisition_harness.py` | `C924608383A6382C18E232368809F81114CA44C6384638C4B18B35A43F9FA12B` |

Frozen inputs after C3:

| Path | SHA256 |
|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `plans/work-unit-2-real-world-ingestion.md` | `894D5844E140BF62EC1DB89B1BE318EB4945FF4A0BF8B139E9B82C0B4929BA2C` |
| `plans/work-unit-2-anchor-recovery.md` | `432318A68D13774646CF3A1E5BE6057D5C92DE7CE600E06FA6CF52BD0CD92E90` |
| `docs/wu2-source-decision.md` | `E667ABCF6BEBFB522AE0EA76AFDD6EB628E11214B33773045AA5EC8B8C7FEA62` |
| `docs/real-world-source-policy.md` | `B89D0836BCC17DD1D52CA215F38EF290134251295ECAC183BA7D54C45A1C4989` |
| `docs/wu2a-anchor-decision.md` | `570649D6B7287B48F3C396E536AC05EF31D949FC7AF960EF2D3DFEB17D4A9F6D` |

All 11 Schema hashes match the approved baseline:

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

Handbook after execution:

```text
local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree changes: 0
```

## 13. R10 and safety scans

Executed scans over the executable/test surface:

| Scan | Matches |
|---|---:|
| `infer_`, `guess_`, missing-default, silent-fallback and warning-as-pass family | 0 |
| live HTTP client and prohibited provider endpoint family in harness | 0 |
| assignment-shaped secret patterns in Plan, harness and test | 0 |

Manual diff review also confirmed:

- no automatic field filling from exception text;
- no type coercion of request, response or clock values;
- no retry for HTTP response failures;
- no silent acceptance of unknown `URLError` causes;
- no real endpoint, credential, raw response, coordinate or anchor;
- no business planner, evidence scoring or recommendation logic;
- test expected values are handwritten, not generated by the harness.

## 14. Completion criteria

The 20 Plan criteria are checked without omission:

1. ✓ 已完成 — approved Plan was committed at its approved SHA256 and not changed.
2. ✓ 已完成 — WU2/WU2A history and states were not rewritten.
3. ✓ 已完成 — `docs/wu2a-anchor-decision.md` retains the frozen SHA256.
4. ✓ 已完成 — the other five frozen inputs, 11 Schemas and handbook are unchanged.
5. ✓ 已完成 — the final work unit uses exactly the four whitelisted paths.
6. ✓ 已完成 — no dependency or environment configuration changed.
7. ✓ 已完成 — C1 was importable and retained only explicit `NotImplementedError` behavior.
8. ✓ 已完成 — C2 and corrected C2.1 each produced ten interface-state errors; C2.1 is separately recorded.
9. ✓ 已完成 — C3 used the identical command and reached 10/10 green.
10. ✓ 已完成 — full regression reached 143/143 green and was independently rerun.
11. ✓ 已完成 — source order and offline probe prove started persistence precedes transport.
12. ✓ 已完成 — every attempt contains all 14 frozen fields; unknown values remain null.
13. ✓ 已完成 — HTTP 400/404/429/500+ behavior is non-retryable HTTP failure.
14. ✓ 已完成 — DNS, connection, timeout and reset behavior is transport-only retry.
15. ✓ 已完成 — retry relation has four fields and equal request hashes.
16. ✓ 已完成 — postprocess failure retains response metadata and terminal completion.
17. ✓ 已完成 — unreadable body metadata is not reconstructed; readable empty body remains measurable.
18. ✓ 已完成 — real network attempts and temporary residue are both zero.
19. ✓ 已完成 — no anchor, fixture, adapter, Schema, validator or policy changed; no later work unit started.
20. ✓ 已完成 — this Review provides Git, hash, scope, red/green, R10, secret and no-push evidence.

## 15. Known boundary

The harness covers ordinary Python response, exception and `finally` paths.
For forced process termination or power loss, it guarantees only that a
successfully started attempt was persisted before transport; it does not
invent a terminal timestamp or status that could not be observed.

The harness contains no real transport. A later, separately approved WU2A
execution must inject one. This Review does not claim an acquisition recipe,
open-data feasibility, an anchor, WU2 recovery or WU2 completion.

## 16. Final status

```text
READY_FOR_HUGIN_REVIEW
```
