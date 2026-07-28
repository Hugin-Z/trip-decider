# trip-decider · Work Unit 2R Failure Evidence Remediation Plan

Plan version: v0.1

Status: PENDING_HUGIN_APPROVAL

Prepared on: 2026-07-28

Work unit: WU2R-FER · Failure Evidence Remediation

Approval phrase required:

```text
批准执行 Work Unit 2R Failure Evidence Remediation
```

This Plan is the first PER gate for a new work unit. It authorizes no
implementation, test, commit, data acquisition, WU2R continuation, or WU3
work until Hugin approves this exact file. It does not rewrite the stopped
WU2R execution or reconstruct evidence that was not retained.

## 1. Current states, baseline, and preserved history

### 1.1 Historical state

The following states are inputs and remain unchanged:

```text
WU0:             APPROVED
WU1:             APPROVED
WU1R:            APPROVED
WU1C:            APPROVED
WU2:             BLOCKED
WU2A:            INVESTIGATION_BLOCKED
WU2A-R:          APPROVED
WU2A-Resume:     APPROVED
WU2 Decision Gate: APPROVED
WU2R:            BLOCKED
```

WU2R completed and committed C0 through C4:

```text
d944786 docs: record approved WU2 recovery plan
b5e6b25 docs: record WU2 recovery source and capture gate
d2d71b3 chore: add WU2 recovery interfaces
66d3cdb test: add failing multi identity recovery cases
bca00a4 feat: implement candidate accounting and route guard
```

WU2R C5 has no commit. WU2R C6 and C7 did not start. The old WU2 C5/C6
remain unauthorized. This work unit may not amend, reset, rebase, squash,
delete, or reinterpret any of that history.

### 1.2 Repository baseline

Measured before writing this Plan:

```text
repository: <repo>
branch: main
HEAD: bca00a4792247bcd334f1b8742d7a4fa22589b72
worktree: clean
remotes: 0
stashes: 0
tracked files: 80
Schema files: 11
Python: 3.11.9
interpreter: <repo>\.venv\Scripts\python.exe
platform: Windows-10-10.0.26200-SP0
```

The current explicit regression command was run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_harness tests.test_wu2_recovery -v
```

Measured result:

```text
tests: 159
passed: 159
failures: 0
errors: 0
exit code: 0
```

No network-backed test or acquisition is part of that command.

### 1.3 Read inputs and frozen hashes

The required WU2R Review path is absent:

```text
docs/reviews/work-unit-2-recovery-review.md: absent
```

Its absence is expected because WU2R stopped at C5. FER may not create,
backfill, or edit that old Review.

These inputs are read-only throughout FER:

| Path | Bytes | SHA256 |
|---|---:|---|
| `PLAN.md` | 9914 | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `plans/work-unit-2-recovery.md` | 38282 | `D6F6C0A662969D5AE810291CE746F4530594DC9C2A0E018C5FC41122AE606AF8` |
| `docs/wu2-recovery-source-and-capture.md` | 9987 | `B34ED5EB0FA570A11E0B43E9F0A714C30F4A44FC53EE3D5D38302074B1DE9CA1` |
| `docs/wu2a-resume-decision.md` | 23394 | `417F4E89A059CA99A5E96E960B839FA0297935F2438D76B100E7F8F30313B40A` |
| `src/trip_decider/recovery.py` | 15754 | `8105424CAEBD020BDAFBA4048477BF92846AE2B27090CB3EFAFC7C40B6183614` |
| `scripts/acquisition_harness.py` | 12845 | `AE6487D7F35E6A1CE351C07FD83DA219214705F1D3AC00611F5D7B9EF49559F9` |
| `tests/test_wu2_recovery.py` | 14727 | `8D1341E4A57EA008152059A670CF4876EA48E8D118DF6E82EF15850549E4F43E` |

The 11 Schema baselines are:

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

All listed paths and hashes are pre/post FER invariants.

### 1.4 Handbook reconciliation

The fixed handbook path was fetched read-only and the required rules were
read from `origin/main`:

```text
<handbook>

local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree before/after: clean
```

Loaded:

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

Concrete effects:

- R10: no missing attempt, hash, retry, or cleanup fact may be reconstructed
  from memory or exception text; missing evidence is a hard failure.
- PER: this Plan must be approved before C0-C4 Execute; FER ends at its own
  Review and may not resume WU2R.
- Scope: four repository paths and exactly 16 completion criteria are frozen
  here; any additional path stops execution.
- Fixture-first: deterministic injected failures are authored before the
  implementation and must produce a valid interface-level red.

The handbook repository is not a FER output and must remain byte-identical.

## 2. Blocker evidence and honesty boundary

### 2.1 What was observed at WU2R C5

The approved request/query hashes had been matched before the acquisition:

```text
query SHA256:
5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F

request SHA256:
6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045
```

The corrected execution reached this terminal report:

```text
acquisition terminal: internal_failure
WU2R_ACQUISITION_EXIT_CODE=1
```

The cleanup report said:

```json
{"cleanup":{"ledger_atomic_tmp_count":0,"ledger_exists":false,"raw_temp_exists":false}}
```

The helper removed the ledger and raw temporary file in `finally` before
emitting an independently reviewable failure envelope. No anchor or fixture
was created and no C5 commit exists.

### 2.2 What cannot be claimed

The deleted ledger means the following are not independently provable:

- exact physical attempt count;
- whether the transport retry was consumed;
- per-attempt request hash;
- HTTP/response status and metadata;
- the phase and cause represented by `internal_failure`;
- the relationship between a possible original attempt and retry;
- cleanup results beyond the final existence counters printed by the helper.

FER must not reconstruct those facts. It may cite this gap as the reason for
the new contract, but its tests and implementation apply only to future
injected executions. WU2R stays `BLOCKED`.

## 3. Objective and non-goals

FER has one objective:

> Before any future acquisition effect, persist a sanitized started record;
> after every observable outcome, persist explicit attempt, classification,
> retry, persistence, and cleanup evidence without retaining response bodies.

FER completes only the failure-evidence mechanism. It does not:

- call Overpass, OSRM, Nominatim, or a commercial map;
- acquire, save, normalize, select, or rank any real data;
- create an anchor or fixture;
- modify the Overpass query or request bytes;
- modify candidate, seed, identity, evidence, route, planner, or feasibility
  behavior;
- modify an adapter, Schema, validator, old test, dependency, lock, source
  policy, old Plan, or old Review;
- resume WU2R C5/C6 or start WU3.

## 4. Decision Q1: evidence ownership

### 4.1 Options

Option A makes `scripts/acquisition_harness.py` own the new durable failure
ledger. It would be central, but the harness is frozen, already tested, and
outside the approved modification boundary.

Option B adds a WU2R-FER orchestration layer. It owns durable evidence while
transport and transport-only retry execution remain delegated to the frozen
harness through an injected callable boundary.

### 4.2 Decision

```text
FAILURE_EVIDENCE_OWNER:
WU2R_FER_ORCHESTRATION

FROZEN_HARNESS:
READ_ONLY_INJECTED_EFFECT
```

FER selects Option B.

The new `src/trip_decider/acquisition_evidence.py` module will:

1. compute the request SHA256 from the provided bytes;
2. persist the authoritative run-level `started` envelope;
3. invoke one injected acquisition runner;
4. consume only its structured attempts/retries and an explicit response
   phase result;
5. verify every recorded attempt uses the computed request hash;
6. map explicit phase/status information to the frozen FER failure codes;
7. run an injected cleanup boundary;
8. persist the terminal envelope.

It will not implement HTTP, endpoints, request construction, provider
selection, response normalization, or retry scheduling. The future caller,
under separate approval, may inject the existing harness. This avoids both a
second transport implementation and a change to the frozen harness.

If implementation cannot use the frozen harness through this boundary
without editing it or duplicating its transport/retry behavior, FER stops.

## 5. Decision Q2: ledger location and data boundary

### 5.1 Compared locations

| Location | Benefit | Risk | Decision |
|---|---|---|---|
| system temporary directory | outside Git; usable as an emergency sink | OS or cleanup may remove it; it recreated the C5 loss when used as the only ledger | emergency only |
| ignored project `runtime/` | stable for local Review; already ignored; no repository commit | local-only and must be explicitly cleaned after human acceptance | authoritative sink |
| repository tracked path | durable in Git | runtime evidence or raw could be committed and history polluted | prohibited |

`.gitignore` already matches:

```text
runtime/wu2r-failure-evidence/probe.json
```

No `.gitignore` change is required or allowed.

### 5.2 Authoritative location

Future callers supply a path under:

```text
runtime/wu2r-failure-evidence/<run_id>/failure-evidence.json
```

The path is the authoritative sanitized ledger. Atomic replacement uses a
random sibling temporary file. Tests use their own system temporary
directories and do not create repository-local runtime output.

The ledger never stores:

- request bytes;
- response bytes;
- query text;
- coordinates;
- credentials, headers, cookies, tokens, or environment values;
- third-party exception messages or stack traces.

It may store only hashes, byte counts, allowlisted status/type tokens,
timestamps supplied by the caller, safe operation identifiers, and explicit
persistence/cleanup state.

Tracked repository paths may never receive runtime ledger or raw data.

## 6. Decision Q3: primary-ledger failure

### 6.1 Explicit two-sink protocol

Primary and emergency persistence are distinct injected boundaries:

```text
primary:   ignored runtime path
emergency: random system-temp failure-evidence JSON path
```

The emergency path is attempted only after an explicit primary persistence
failure. It is never a silent substitute. The evidence envelope records:

```text
primary_status
primary_path_kind
emergency_attempted
emergency_status
emergency_path_kind
failure_codes
```

It records no exception text or secret-bearing path value. A returned result
identifies which sink contains the envelope.

### 6.2 Pre-transport rule

The authoritative `started` envelope must exist before the injected runner
is called.

If its primary write fails:

1. classify `ACQUISITION_LEDGER_FAILURE`;
2. write the sanitized preflight failure to the emergency sink;
3. do not invoke acquisition or transport;
4. return a deterministic failed result.

If primary and emergency writes both fail, transport is still not invoked.
The function returns/raises a deterministic evidence-persistence failure and
makes no claim that a durable ledger exists. Because no external attempt
occurred, it does not create an unaudited acquisition. Review records this
as an explicit blocked persistence precondition.

### 6.3 Post-transport rule

If a terminal primary write fails after the runner returns, the complete
in-memory sanitized envelope is written to the emergency sink. It preserves
the underlying acquisition failure and adds
`ACQUISITION_LEDGER_FAILURE`; it does not overwrite the original
classification with a generic error.

The emergency evidence file is intentional evidence, not cleanup residue,
and is not automatically deleted before Review. Its existence and path kind
are reported explicitly.

## 7. Ledger contract and state machine

### 7.1 Envelope

The implementation uses a closed, versioned internal document, not a new
artifact Schema:

```yaml
schema_version: "0.1.0"
run_id:
purpose:
request_sha256:
started_at:
completed_at:
status: started | succeeded | failed | evidence_persistence_failed
terminal_failure_code:
failure_codes: []
attempts: []
retries: []
response_phase:
cleanup:
  status: pending | succeeded | failed
  items: []
persistence:
  primary_status:
  primary_path_kind: ignored_runtime
  emergency_attempted:
  emergency_status:
  emergency_path_kind: system_temp
```

`terminal_failure_code` is the operationally decisive code.
`failure_codes` is an ordered, duplicate-free list that preserves a primary
acquisition failure plus later ledger or cleanup incidents.

Each attempt contains:

```text
attempt_id
request_sha256
started_at
completed_at
status
http_status
response_bytes
response_sha256
content_type
failure_code
retry_decision
```

Null is retained when a value was not observed. No default value is invented.

### 7.2 State order

The required order is:

```text
validate inputs
-> compute request hash
-> persist started envelope
-> invoke injected runner
-> validate/import structured attempts and retries
-> classify acquisition/response outcome
-> persist pre-cleanup terminal observation
-> invoke cleanup
-> record cleanup outcome
-> persist final terminal envelope
-> return result
```

Every write is atomic. A write failure follows section 6. Cleanup cannot
erase the authoritative ledger.

## 8. Failure classification

The closed codes are:

```text
ACQUISITION_TRANSPORT_FAILURE
ACQUISITION_HTTP_FAILURE
ACQUISITION_RESPONSE_FAILURE
ACQUISITION_LEDGER_FAILURE
ACQUISITION_CLEANUP_FAILURE
ACQUISITION_INTERNAL_FAILURE
```

Classification is phase- and type-based:

| Observed condition | Code | Retry |
|---|---|---|
| explicit timeout/DNS/connection-reset transport status | `ACQUISITION_TRANSPORT_FAILURE` | preserve harness decision |
| `HTTPError` or structured non-2xx HTTP status | `ACQUISITION_HTTP_FAILURE` | no retry |
| successful HTTP transport followed by explicit UTF-8/JSON/shape rejection | `ACQUISITION_RESPONSE_FAILURE` | no retry |
| atomic primary/emergency evidence persistence failure | `ACQUISITION_LEDGER_FAILURE` | no acquisition retry |
| injected cleanup returns/raises an explicit failure | `ACQUISITION_CLEANUP_FAILURE` | no acquisition retry |
| unrecognized exception in orchestration or an inconsistent runner result | `ACQUISITION_INTERNAL_FAILURE` | no retry |

The implementation may inspect exception types at an explicit boundary. It
may not parse exception messages, infer phase from prose, copy a third-party
exception, or collapse known HTTP/response/ledger/cleanup failures into
`ACQUISITION_INTERNAL_FAILURE`.

## 9. Retry evidence

Retry scheduling remains owned by the injected frozen harness. FER validates
and persists each reported relationship:

```text
original_attempt_id
retry_attempt_id
same_request_sha256
retry_reason
```

Rules:

- both attempt IDs must resolve exactly once;
- the retry attempt must follow the original attempt;
- both attempt request hashes must equal the orchestration-computed hash;
- `same_request_sha256` must be `true`;
- only an explicit transport failure may have a retry;
- HTTP, response, ledger, cleanup, and internal failures are not retryable;
- missing, duplicate, dangling, reordered, or contradictory relations hard
  fail as `ACQUISITION_INTERNAL_FAILURE`;
- no relation means no retry; it is not inferred from attempt count.

## 10. Cleanup evidence

Cleanup is an injected, deterministic boundary executed after the
pre-cleanup terminal observation is persisted.

Each allowlisted cleanup item records:

```text
resource_kind
existed_before
deletion_attempted
status: removed | not_present | failed
residue_count
```

It stores a safe resource kind, not a raw path or file content.

On cleanup failure:

1. retain the acquisition/response classification;
2. add `ACQUISITION_CLEANUP_FAILURE`;
3. set cleanup status to `failed`;
4. persist the final envelope to primary or explicit emergency sink;
5. return failure even if transport succeeded.

`not_present` is a measured state, not silently treated as `removed`.
Emergency evidence intentionally retained for Review is excluded from
temporary-residue counts and is reported through the persistence section.

## 11. Interface boundary

WU2R-FER-C1 adds only
`src/trip_decider/acquisition_evidence.py`. It defines:

- the six failure-code constants;
- frozen result/observation value types;
- injected runner, persistence, clock, response-check, and cleanup callable
  contracts;
- one public `run_failure_evidenced_acquisition(...)` interface that raises
  an explicit `NotImplementedError`.

The public interface accepts request bytes and computes their hash itself.
It accepts explicit primary/emergency paths and injected effects. It does not
discover files, scan the environment, choose an endpoint, or supply defaults
for missing required values.

No second artifact-validator error model is created. These value types model
an acquisition execution record, not Schema validation. Existing
`ValidationProblem`, validators, and Schemas remain untouched.

WU2R-FER-C3 fills only that interface in the same file. If a reliable
implementation requires another source file, a harness edit, a Schema, a
dependency, or a caller change, execution stops.

## 12. Fixture-first test design

The test module is a deterministic transformation fixture. Its docstring
records:

- source: synthetic injected outcomes authored from this Plan;
- expected fields: handwritten from the closed ledger and classification
  rules, never generated by the function under test;
- coverage: failure evidence, retry relation, persistence, cleanup, and
  redaction;
- non-coverage: network, provider correctness, real OSM identity, adapters,
  candidates, anchors, planning, or WU2R replay.

Every test patches network creation to fail if reached unexpectedly and uses
temporary directories. Exactly 10 cases are frozen:

| ID | Injected condition | Required assertions |
|---|---|---|
| FE01 | transport timeout then byte-identical retry result | two attempts exist; transport code; exact retry IDs; `same_request_sha256=true`; both hashes equal computed hash |
| FE02 | HTTP 400 | one attempt; HTTP status 400; HTTP code; no retry; complete terminal ledger |
| FE03 | HTTP success with explicit invalid-JSON response result | response byte count/hash retained; response code; no body; no retry |
| FE04 | unexpected orchestration/runner exception | attempt/run terminal remains present; internal code; no exception text or input value |
| FE05 | primary `started` write fails, emergency succeeds | ledger code; emergency status visible; runner/transport call count zero; no fake success |
| FE06 | primary and emergency `started` writes both fail | deterministic persistence failure; runner/transport zero; no durable-ledger claim |
| FE07 | cleanup fails after an acquisition failure | original code retained; cleanup code added; cleanup item and residue state visible |
| FE08 | transport retry exhausts | two terminal attempts; one exact relation; exhausted decision; no third attempt |
| FE09 | terminal primary write fails after runner result | complete sanitized envelope reaches emergency sink; original code plus ledger code; primary failure visible |
| FE10 | clean terminal persistence and cleanup | atomic ledger reload matches returned document; cleanup succeeds; atomic temporary residue zero; stdout/log payload contains no raw or secret |

Each case tests one primary behavior and uses multiple exact field assertions.
FE05/FE06 are the dirty pair for persistence; FE07/FE10 are the dirty/clean
pair for cleanup.

## 13. Red-to-green and regression gates

### 13.1 C2 red

C1 must leave all current 159 tests green. C2 then runs only:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2r_failure_evidence -v
```

Required red:

```text
tests: 10
passed: 0
failures: 0
errors: 10
cause: explicit run_failure_evidenced_acquisition NotImplementedError
network attempts: 0
```

Import, dependency, path, syntax, malformed-test, unintended I/O, and other
exception counts must be zero. If the distribution differs, C3 may not start.

### 13.2 C3 green

C3 uses the character-identical command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2r_failure_evidence -v
```

Required green:

```text
tests: 10
passed: 10
failures: 0
errors: 0
network attempts: 0
```

C3 may not modify the test.

### 13.3 Full regression

After C3 and independently before C4 Review:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_harness tests.test_wu2_recovery tests.test_wu2r_failure_evidence -v
```

Pre-registered successful result:

```text
existing tests: 159
FER tests: 10
total: 169 passed
failures: 0
errors: 0
network attempts: 0
```

Actual counts must come from command output. No live acquisition is a test.

## 14. Scope

### 14.1 Exact four-path whitelist

FER may create or modify only:

```text
plans/work-unit-2r-failure-evidence-remediation.md
src/trip_decider/acquisition_evidence.py
tests/test_wu2r_failure_evidence.py
docs/reviews/work-unit-2r-failure-evidence-review.md
```

Expected repository diff: four new files.

Ignored test output may exist only inside test-managed system temporary
directories. Execute does not create a repository runtime ledger because it
performs no real acquisition.

### 14.2 Protected paths

FER may not change:

- `scripts/acquisition_harness.py`;
- `src/trip_decider/recovery.py`;
- all adapters, ingestion code, validators, and Schemas;
- all existing tests and fixtures;
- `PLAN.md`, `.gitignore`, dependency and lock files;
- all WU2/WU2A/WU2R Plans, decisions, source policies, reviews, and commits;
- handbook, user configuration, other repositories, or system configuration.

Any need for a fifth repository path is a blocker, not an implicit scope
extension.

## 15. Commit sequence

Execution is linear on `main` after approval:

| Commit | Exact message | Files | Single responsibility | Gate |
|---|---|---|---|---|
| WU2R-FER-C0 | `docs: record failure evidence remediation plan` | approved Plan only | record the approved bytes | approved SHA256 exact; no Plan edit |
| WU2R-FER-C1 | `chore: add failure evidence interface` | `src/trip_decider/acquisition_evidence.py` | constants, types, injected boundaries, explicit interface stub | imports and existing 159 tests green |
| WU2R-FER-C2 | `test: add failure evidence contract cases` | `tests/test_wu2r_failure_evidence.py` | add the 10 deterministic failing cases | exact 10-error `NotImplementedError` red |
| WU2R-FER-C3 | `feat: implement failure evidence persistence` | `src/trip_decider/acquisition_evidence.py` | ledger-first orchestration, classification, retry validation, cleanup, explicit emergency persistence | same command 10/10; full 169 green |
| WU2R-FER-C4 | `docs: prepare failure evidence remediation review` | FER Review only | independently report Git, hashes, red/green, scope, and criteria | repeated 169 green; clean worktree |

C2 must remain a valid red commit. Tests and implementation may not share a
commit. No amend, squash, reset, rebase, push, remote, or PR is permitted.

## 16. Review contract

C4 may create only:

```text
docs/reviews/work-unit-2r-failure-evidence-review.md
```

It must include:

- start/final HEAD and the five-commit linear log;
- full diff/stat and four-path whitelist reconciliation;
- proof that WU2/WU2R states and C0-C4 history did not change;
- Plan, frozen inputs, 11 Schemas, and handbook before/after hashes;
- C2 red and character-identical C3 green commands, counts, IDs, and causes;
- the independent 169-test regression;
- FE01-FE10 evidence for classifications, retry relations, sink selection,
  cleanup, and zero network;
- proof that no response/request bytes, exception text, secret, coordinate,
  anchor, or fixture entered Git or ledger test output;
- scope, secret, fallback, `guess_*`/`infer_*`, warning-as-pass, and
  capability-overclaim scans;
- all 16 completion criteria below with one status each.

Final status must be exactly one:

```text
READY_FOR_HUGIN_REVIEW
BLOCKED
INCOMPLETE
```

C4 does not close or resume WU2R.

## 17. Completion criteria

Exactly 16 criteria are pre-registered:

1. Execute starts from the approved HEAD with `main`, zero unrelated
   worktree changes, zero remotes, zero stashes, and the approved Plan hash.
2. Handbook fetch/reconciliation and all eight `origin/main` reads are
   recorded; handbook HEAD and worktree remain unchanged.
3. WU2 and WU2R remain `BLOCKED`; no old WU2/WU2A/WU2R commit, Plan,
   decision, source policy, or Review changes.
4. All seven targeted frozen-input hashes and all 11 Schema hashes match
   before and after; the absent old WU2R Review remains absent.
5. The Git diff contains exactly the four whitelist paths and five
   single-responsibility commits.
6. Harness, recovery, adapter, Schema, validator, existing test/fixture,
   dependency/lock, `.gitignore`, and `PLAN.md` diffs are zero.
7. The authoritative started envelope is atomically persisted before the
   injected runner is called; failure of both evidence sinks prevents any
   transport call.
8. Transport, HTTP, response, ledger, cleanup, and internal failures have
   distinct deterministic codes and known failures are not collapsed to
   internal.
9. Every terminal result preserves request hash, observed response metadata,
   attempt state, original failure, persistence state, and nulls without
   inventing missing values.
10. Every retry relation has resolving attempt IDs, a true same-request-hash
    assertion, explicit reason, and transport-only eligibility.
11. Primary write failure is visibly routed to the explicit emergency sink;
    no fallback is silent and no false durable-ledger claim is emitted.
12. Cleanup success/failure and residue are explicit; cleanup failure cannot
    hide or replace the underlying acquisition failure.
13. C2 records the valid 10-case `NotImplementedError` red and C3 uses the
    character-identical command for 10/10 green without changing tests.
14. Full regression reports 169 passed, zero failures/errors, zero network
    attempts, and zero unintended atomic temporary residue.
15. R10 scans show no raw request/response body, secret, coordinate list,
    third-party exception text, guessed classification, silent fallback,
    warning-as-pass, anchor, fixture, or capability overclaim.
16. C4 independently provides all Git, hash, red/green, classification,
    retry, cleanup, scope, and 16-item evidence, then stops with an allowed
    Review status without resuming WU2R or starting WU3.

FER completion means only:

> offline-injected future acquisition failures can leave explicit,
> sanitized, independently reviewable evidence.

It does not mean that the prior C5 failure is now provable, that an anchor
exists, or that WU2R may resume.

## 18. Blocking conditions

Stop immediately if:

- the approved Plan SHA256, start HEAD, branch, clean worktree, remote/stash
  count, frozen input, Schema, or handbook gate differs;
- a change to `scripts/acquisition_harness.py`, `recovery.py`, an adapter,
  Schema, validator, existing test/fixture, dependency, source policy,
  `.gitignore`, or another non-whitelist path is needed;
- the orchestration cannot wrap the frozen harness without duplicating HTTP
  or retry behavior;
- the primary/emergency persistence contract would require silent fallback,
  an invented fact, exception-message parsing, or an inaccurate completion
  claim;
- a test would require network, real provider data, a new anchor/fixture,
  repository runtime evidence, or output generated by the function under
  test as expected data;
- C2 red is not exactly 10 explicit interface `NotImplementedError` errors,
  or C3 needs a test change;
- a known failure can only be represented as generic internal failure;
- request/response raw bytes, secrets, coordinates, or unauthorized data
  would be persisted or printed;
- any Overpass, OSRM, Nominatim, commercial-map, or other data call becomes
  necessary;
- WU2R C5/C6, WU3, planner, recommendation, evidence scoring, or product
  contract work becomes necessary;
- any history rewrite, push, remote creation, or handbook modification is
  needed.

On a blocker, preserve only valid FER commits, report the exact observed
condition, and stop as `BLOCKED` or `INCOMPLETE`. Do not repair old WU2R,
acquire data, expand scope, or start another work unit.
