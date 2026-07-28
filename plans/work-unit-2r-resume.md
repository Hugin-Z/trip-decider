# trip-decider · Work Unit 2R Resume Plan

Plan version: v0.1

Status: PENDING_HUGIN_APPROVAL

Prepared on: 2026-07-28

Work unit: WU2R Resume · Multi Identity Acquisition Resume

Required approval phrase:

```text
批准执行 Work Unit 2R Resume
```

This is a new PER work unit. Until Hugin approves this exact file, it
authorizes no Overpass or map-data call, implementation, test, fixture,
anchor, commit, WU2/WU2R continuation, or WU3/WU5 work.

## 1. Current state and repository baseline

### 1.1 Preserved state

The following state is an input and remains historical fact:

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
WU2R-FER:        APPROVED
```

WU2R Resume does not amend, complete, or reopen old WU2 or WU2R commits. It
does not delete the old failed event, overwrite an old ledger, or describe
the old failure as repaired.

The FER Review established only that future offline-injected acquisition
failures can retain complete sanitized evidence. It did not make the old
WU2R C5 event reconstructable and did not authorize another call.

### 1.2 Measured repository baseline

Measured before writing this Plan:

```text
repository: <repo>
branch: main
HEAD: e93f606d193161bfb1bd245a1e9b5e27282bd9a7
worktree: clean
remotes: 0
stashes: 0
Python: 3.11.9 project .venv
```

Explicit regression command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_harness tests.test_wu2_recovery tests.test_wu2r_failure_evidence
```

Measured result:

```text
tests: 169
passed: 169
failures: 0
errors: 0
exit code: 0
```

Current fixture baseline was measured from the six manifests:

```text
fixture directories: 6
embedded documents: 38
dirty cases: 6
all bundle_closure: closed
```

`scripts/verify_wu1.ps1` was also run read-only. It exited 5 with
`ENTRY_UNITTEST_COUNT_MISMATCH` because its frozen expectation is 82 tests.
It is not a valid Resume verification entry and will not be modified or
treated as green. A new Resume-only entry is required.

### 1.3 Loaded and frozen inputs

The required context was read in full. These paths are immutable in Resume:

| Path | Bytes | SHA256 |
|---|---:|---|
| `docs/reviews/work-unit-2r-failure-evidence-review.md` | 15961 | `2F6D893C57C70D5B74F432E96CCB72AFCC65F23BA0903BDF6CCDC6DC5D9E0B85` |
| `docs/wu2-recovery-source-and-capture.md` | 9987 | `B34ED5EB0FA570A11E0B43E9F0A714C30F4A44FC53EE3D5D38302074B1DE9CA1` |
| `docs/wu2a-resume-decision.md` | 23394 | `417F4E89A059CA99A5E96E960B839FA0297935F2438D76B100E7F8F30313B40A` |
| `docs/wu2-identity-boundary-decision.md` | 16670 | `44C1105298AE55FD9B0508B078D4D39124455242F927DAFAAF8E7E2605A77B57` |
| `src/trip_decider/recovery.py` | 15754 | `8105424CAEBD020BDAFBA4048477BF92846AE2B27090CB3EFAFC7C40B6183614` |
| `src/trip_decider/acquisition_evidence.py` | 25561 | `BF7F25FC4A41C8085431450501B86866A7757B125A208363AA5113AD5F82FEDB` |
| `plans/work-unit-2-recovery.md` | 38282 | `D6F6C0A662969D5AE810291CE746F4530594DC9C2A0E018C5FC41122AE606AF8` |
| `plans/work-unit-2r-failure-evidence-remediation.md` | 29728 | `B457E6ECDF2CF6BEAB057BD35D761071AD6100D4926652736E3336726E3C3F95` |
| `scripts/acquisition_harness.py` | 12845 | `AE6487D7F35E6A1CE351C07FD83DA219214705F1D3AC00611F5D7B9EF49559F9` |
| `src/trip_decider/adapters/open_data_poi.py` | 9551 | `F39EBF86B682EDECF182F6148178AEBA434A287B34A270FE84D3FAEE8F80944B` |
| `tests/test_wu2_recovery.py` | 14727 | `8D1341E4A57EA008152059A670CF4876EA48E8D118DF6E82EF15850549E4F43E` |
| `tests/test_wu2r_failure_evidence.py` | 21885 | `09894721531AA422B2C87B03B3F4D3104E47A680FA459E16A4AE11A9E4AD684D` |
| `.gitignore` | 378 | `A6F5AFD044D06F8E04D1CC9DDE26B25D186A0CE9046C0ED50F7ADF734E5FC2A7` |
| `requirements.lock` | 402 | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` |
| `pyproject.toml` | 365 | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` |

All 11 Schema hashes remain the WU2R-FER baselines and are pre/post Resume
invariants. No dependency or lock change is authorized.

### 1.4 Handbook reconciliation

The fixed handbook path was fetched read-only:

```text
<handbook>

local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree before/after: clean
```

Loaded from `origin/main`:

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

- R10: the old deleted ledger is never reconstructed; new dynamic counts and
  hashes come only from commands and persisted evidence.
- PER: approval of this exact Plan is required before the new budget exists.
- Scope: ten repository paths and exactly 20 completion criteria are frozen.
- Fixture-first: the new deterministic integration boundary gets a valid
  interface red before implementation; a real anchor is accepted only after
  independent expected values are authored.

The handbook is not an output and may not be modified.

## 2. Objective and non-goals

Resume has one objective:

> Execute one newly authorized, separately identified WU2R acquisition group
> with the frozen query and multi-identity rules, while FER guarantees that
> either success or failure leaves an auditable result.

Two valid acquisition outcomes exist:

```text
WU2R_ACQUISITION_COMPLETED
WU2R_ACQUISITION_BLOCKED_WITH_COMPLETE_EVIDENCE
```

The second is a valid work-unit outcome, not a silent retry opportunity.

Resume does not:

- restore old WU2 C5/C6 or modify old WU2R C0-C4;
- modify FER, recovery, harness, adapter, Schema, validator, dependency,
  source policy, Decision Gate, or existing fixture;
- resolve one “correct” identity;
- call a route provider;
- implement recommendation, evidence scoring, feasibility, planner, or UI;
- begin WU3/WU5.

## 3. Old budget analysis and decision

### 3.1 What is knowable

The old WU2R C5 helper reported a terminal `internal_failure`, then deleted
its ledger. The exact physical-attempt and retry counts are not independently
provable.

Therefore the old budget state is:

```text
OLD_WU2R_ATTEMPT_BUDGET:
UNRECONCILABLE_FROM_DELETED_LEDGER
```

It must not be labeled consumed or unconsumed.

### 3.2 Option comparison

Option A continues the old budget. It appears strict, but would require
guessing how many old attempts were consumed and would merge incomplete and
complete evidence.

Option B creates a new attempt group whose authority exists only after this
Plan is approved. It preserves the old failure as a predecessor and gives
the new execution independent identifiers, ledger, and call accounting.

### 3.3 Decision

```text
BUDGET_DECISION:
NEW_RESUME_ATTEMPT_GROUP

attempt_group_id:
WU2R-resume-001

run_id:
run_wu2r_resume_001
```

Option B is selected because it does not make any claim about the deleted
ledger. The new budget is additional explicit authority, not a declaration
that the old budget was unused.

The predecessor link is by immutable document identity:

```text
prior_blocker_ref:
  path: docs/reviews/work-unit-2r-failure-evidence-review.md
  sha256: 2F6D893C57C70D5B74F432E96CCB72AFCC65F23BA0903BDF6CCDC6DC5D9E0B85
  historical_status: WU2R_BLOCKED
  old_ledger_complete: false
```

No old attempt ID, response state, or retry count is invented.

## 4. Exact call budget

Approval of this Plan authorizes only:

```text
scheduled Overpass POST: 1
byte-identical retry after an explicit transport failure: at most 1
maximum physical Overpass attempts: 2

OSRM: 0
Nominatim: 0
commercial maps: 0
alternate Overpass instance: 0
Geofabrik: 0
other data sources: 0
web crawlers: 0
```

Only DNS, timeout, connection reset, or an equivalent typed transport failure
may schedule the one retry. HTTP status failure, UTF-8/JSON/shape failure,
empty elements, adapter rejection, identity/coverage failure, policy failure,
ledger failure, cleanup failure, or internal failure is terminal and
non-retryable.

No retry may change request bytes, query, endpoint, headers, names,
categories, relation ID, timeout, or provider.

Official OSM copyright, ODbL, attribution, and Overpass policy pages may be
reopened read-only before the call. They are policy verification, not a
second POI data source. If their primary-source basis is inaccessible or no
longer supports the frozen persistence policy, execution stops before the
Overpass call.

## 5. Frozen acquisition recipe

Source:

```text
OpenStreetMap data via Overpass
```

Endpoint:

```text
https://overpass-api.de/api/interpreter
```

Method:

```text
POST
```

Query bytes are the exact UTF-8 code block in
`docs/wu2-recovery-source-and-capture.md` section 4. They may not be edited,
normalized, re-indented, re-encoded, expanded, or reconstructed from memory.

Frozen hashes:

```text
query_sha256:
5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F

form_request_sha256:
6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045
```

The helper must compute both hashes before transport. Any mismatch stops
before a network attempt.

Source policy remains:

```text
source_class: open_data
capture_mode: persistent_anchor
storage_policy: persistent_allowed
replay_allowed: true
fixture_allowed: true
license: ODbL-1.0
attribution: © OpenStreetMap contributors
```

No missing value means permission. No new source policy is created.

## 6. FER linkage

The following five values are written to the acquisition decision before the
call and passed explicitly to the integration boundary:

```text
run_id:
run_wu2r_resume_001

attempt_group_id:
WU2R-resume-001

failure_evidence_path:
runtime/wu2r-failure-evidence/run_wu2r_resume_001/failure-evidence.json

request_sha256:
6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045

query_sha256:
5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F
```

Association is by exact values. Timestamp, log order, “latest file,”
directory scanning, or filename inference is forbidden.

The authoritative sanitized FER ledger is written under the ignored runtime
path. The harness may use one subordinate random system-temp ledger. A raw
response may exist only in memory or a random system-temp file until all
acceptance gates pass.

The decision records the FER ledger SHA256 and path after the run. It never
copies raw response bytes, exception text, credentials, or coordinates from
the ledger.

## 7. Why a new integration module is required

A documents-only work unit cannot satisfy the required executable boundary:

```text
acquisition success -> candidate pool
acquisition failure -> FER evidence
committed success anchor -> offline replay
```

The current components are intentionally separate:

- `acquisition_harness.py` owns injected transport/retry attempt mechanics;
- `acquisition_evidence.py` owns durable sanitized FER evidence;
- `recovery.py` owns candidate ingestion and multi-identity accounting.

No approved function currently composes all three. Using only an
execution-time helper would leave the integration untested and
non-reproducible. Therefore Resume adds one new integration module while all
three existing components remain frozen.

The new module:

```text
src/trip_decider/resume_acquisition.py
```

may only:

1. validate explicit run/group/query/request identifiers and hashes;
2. adapt an injected capture effect into FER `RunnerObservation`;
3. strictly parse captured bytes without coercion;
4. call the frozen adapter/recovery candidate ingestion;
5. require the multi-identity coverage gate;
6. return an eligible raw byte value only after FER and candidate gates pass;
7. replay committed bytes through the same deterministic candidate helper
   with networking denied.

It may not implement HTTP, endpoint selection, transport, retry scheduling,
identity selection, route lookup, evidence rating, or planning.

Public interfaces are frozen in the interface commit:

```text
run_wu2r_resume_acquisition(...)
replay_wu2r_resume_anchor(...)
ResumeAcquisitionResult
ResumeReplayResult
```

Both functions are explicit `NotImplementedError` stubs before the red.

`src/trip_decider/recovery.py`, including its existing
`run_wu2_recovery` stub, remains byte-identical. Resume does not claim to
implement the old WU2R offline pipeline.

## 8. Success boundary

The consumed Decision Gate token remains:

```text
Decision: MULTI_IDENTITY_CANDIDATE
Rejected: UNIQUE_IDENTITY_REQUIRED_AT_ADAPTER
```

`WU2R_ACQUISITION_COMPLETED` requires every condition:

1. FER reports a durable successful run for the fixed run/group/hash link.
2. HTTP is successful and raw bytes are readable strict UTF-8 JSON.
3. `elements` is non-empty and contains no contributor account fields.
4. Every element passes the frozen OSM adapter with explicit provider,
   operation, CRS, source policy, retrieval time, locator, and fingerprint.
5. Every valid `(type,id)` provider identity is retained exactly once.
6. No identity is removed or preferred by label, category, order, distance,
   popularity, nearest, first, manual judgment, or LLM.
7. The frozen seed set has at least one `matched`, one `ambiguous`, and one
   `unmatched` result with resolving candidate references.
8. Independently authored request/candidate artifacts, seed accounting,
   record-local fact expectations, and hashes agree with the captured bytes.
9. License, attribution, persistence, and replay metadata are complete.
10. The committed anchor replays offline with zero network attempts.

The frozen seeds remain:

```text
篁岭
江岭
李坑
庆源
```

An unmatched seed creates no placeholder and is not a claim that the place
does not exist in OSM or reality.

Dynamic response bytes, response hash, source-base timestamp, provider
identity count, candidate count, and per-state seed counts are measured at
execution. This Plan does not predict them.

## 9. Success anchor and replay

Only the success branch may create:

```text
fixtures/jiangxi_multi_identity_smoke/
  README.md
  case.json
  replay.json
  osm-pois.json
```

`osm-pois.json` is the exact eligible response bytes. It may be copied from
memory/system temp only after every section 8 gate passes.

The fixture remains the WU2R design:

```text
fixture_type: real_anchor
source.kind: open_data_anchor
bundle_closure: closed
root artifact type: candidates
embedded documents: 2
  request
  candidates
dirty cases: 1
```

The dirty mutation removes one required provider identity field and expects
the exact structural error. It does not mutate or judge an OSM fact.

`replay.json` is a strict control file, not a new artifact type. It records:

- schema/version token;
- run ID and attempt-group ID;
- exact query/request hashes;
- endpoint, retrieval time, response bytes/hash, and source-base timestamp;
- source policy, license, and attribution;
- raw relative path/hash;
- expected request/candidate IDs and payload hashes;
- all frozen seeds and exact matched/ambiguous/unmatched accounting;
- record-local provider facts;
- integration implementation identity;
- `network_required: false`;
- explicit coverage and non-coverage.

Expected values are handwritten from the licensed source bytes and
specification. Neither the adapter, recovery function, nor Resume function
may generate expected fixture values.

Successful repository totals become:

```text
fixture directories: 7
embedded documents: 40
dirty cases: 7
```

Offline replay produces a candidate pool and accounting result only. It does
not call or implement the old `run_wu2_recovery` pipeline.

## 10. Failure boundary

Any terminal acquisition, response, adapter, identity/coverage, persistence,
cleanup, or internal failure produces no anchor.

The terminal code must be one of the frozen FER codes:

```text
ACQUISITION_TRANSPORT_FAILURE
ACQUISITION_HTTP_FAILURE
ACQUISITION_RESPONSE_FAILURE
ACQUISITION_LEDGER_FAILURE
ACQUISITION_CLEANUP_FAILURE
ACQUISITION_INTERNAL_FAILURE
```

A valid failure outcome requires:

```text
decision:
WU2R_ACQUISITION_BLOCKED_WITH_COMPLETE_EVIDENCE
```

and a durable FER envelope containing:

- run/group/request linkage;
- at least one attempt when the runner was invoked;
- terminal failure code;
- retry relationship or an explicit empty retry list;
- cleanup status/items;
- primary/emergency sink status;
- no raw body, secret, exception text, or coordinate list.

The decision records:

```text
failure_evidence_path
failure_evidence_sha256
terminal_failure_code
physical_attempt_count
retry_relation_count
cleanup_status
```

All values are read from the durable ledger, not reconstructed from logs.

If primary and emergency persistence both fail before transport, the runner
is not invoked. If durable evidence is unavailable after an external attempt,
the work unit is `BLOCKED`; it may not use the valid-failure completion state.

No failure authorizes a second group, another query, a new FER work unit, a
harness change, or a provider fallback.

Failure-branch repository totals remain:

```text
tests: 175
fixture directories: 6
embedded documents: 38
dirty cases: 6
```

## 11. Execution-only acquisition helper

The one real call is made by a random helper under the system temporary
directory. The helper is not a repository path and must be deleted in
`finally`.

It:

1. loads the exact checked-in recipe and verifies both frozen hashes;
2. creates the exact runtime FER directory and random harness/raw temp paths;
3. uses the frozen harness for one scheduled POST and its transport-only
   retry budget;
4. translates harness attempts/retries into the frozen FER observation
   types;
5. supplies captured bytes to the Resume integration boundary;
6. persists the FER terminal envelope before reporting outcome;
7. deletes helper, harness ledger, raw temp, and atomic temporary files;
8. retains only the authoritative FER ledger until Hugin Review;
9. reports call counts and cleanup/residue counts from commands.

No repository-local temporary `.py` file is allowed. No response body is
printed or written to logs/runtime. On success only, eligible bytes are
copied byte-for-byte to the approved fixture path.

## 12. Fixture-first test strategy

Resume does not re-test FER internals. The existing 10 FER cases remain
unchanged. New tests cover only composition boundaries.

### 12.1 Interface red/green cases

Exactly six synthetic deterministic cases are pre-registered:

```text
RI01 explicit run/group/query/request/evidence-path linkage is preserved
RI02 one terminal capture failure returns durable FER evidence and no candidate
RI03 success retains every provider identity and all three seed states
RI04 adapter/coverage rejection becomes response failure and no eligible raw
RI05 response order does not change candidate/accounting output
RI06 committed-byte replay is offline and rejects any network attempt
```

Each test declares synthetic source, coverage, and non-coverage. Expected
hashes, IDs, candidates, and accounting are handwritten from the
specification. Network creation is patched to hard-fail.

Character-identical red/green command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2r_resume -v
```

Required C3 red:

```text
tests: 6
passed: 0
failures: 0
errors: 6
cause: explicit public-interface NotImplementedError
network attempts: 0
```

Import, dependency, path, syntax, malformed-test, live-network, and other
error counts must be zero.

Required C4 green:

```text
tests: 6
passed: 6
failures: 0
errors: 0
network attempts: 0
```

C4 may modify only `src/trip_decider/resume_acquisition.py`.

### 12.2 Success-only real-anchor cases

If and only if the live gates pass, C6 extends the same test module with
exactly five data-specific cases:

```text
RA01 raw/query/request/response hashes and source policy are exact
RA02 all valid provider identities are retained in the candidate pool
RA03 independent expected request/candidate artifacts equal replay output
RA04 seed accounting and record-local facts equal independent expectations
RA05 replay from committed bytes performs zero network attempts
```

These cases and the four fixture files must be direct green on their first
run. They validate a new real anchor instance, not new implementation
behavior. If code, Schema, validator, adapter, or an existing assertion must
change, execution stops.

Success command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2r_resume -v
```

Required success result:

```text
tests: 11
passed: 11
failures: 0
errors: 0
network attempts: 0
```

Success full regression becomes:

```text
existing tests: 169
Resume tests: 11
total: 180 passed
```

Failure full regression remains:

```text
existing tests: 169
Resume tests: 6
total: 175 passed
```

## 13. Resume verification entry

The new offline entry is:

```text
scripts/verify_wu2r_resume.ps1
```

The entry accepts one explicit mode:

```text
PreAcquisition
Failure
Success
```

It never infers mode from time, file order, “latest” output, or directory
presence.

Every mode verifies:

1. project `.venv` interpreter/site-packages and locked packages;
2. `pip check`;
3. all 11 Schema metadata/registry checks;
4. the explicit 169-test baseline plus Resume tests;
5. frozen-input and Plan hashes;
6. exact ten-path scope;
7. forbidden network/provider/source patterns;
8. secret, raw-body, fallback, guess/infer, warning-as-pass scans;
9. no unexpected system-temp/runtime residue;
10. deterministic nonzero exit on any failure.

`Failure` additionally verifies the durable FER ledger, exact link, decision
fields, 175 green tests, and unchanged 6/38/6 fixture totals.

`Success` additionally verifies the licensed raw/replay hashes, CLOSED
candidate-root fixture, two embedded documents, one dirty case, candidate
and seed accounting, 180 green tests, 7/40/7 totals, and offline network
attempt count zero.

The entry never performs acquisition. The old failing `verify_wu1.ps1`
remains unchanged and is not called as the Resume authority.

## 14. Exact scope

### 14.1 Ten-path whitelist

Resume may create or modify only:

```text
plans/work-unit-2r-resume.md
docs/wu2r-resume-acquisition-decision.md
src/trip_decider/resume_acquisition.py
tests/test_wu2r_resume.py
scripts/verify_wu2r_resume.ps1
fixtures/jiangxi_multi_identity_smoke/README.md
fixtures/jiangxi_multi_identity_smoke/case.json
fixtures/jiangxi_multi_identity_smoke/replay.json
fixtures/jiangxi_multi_identity_smoke/osm-pois.json
docs/reviews/work-unit-2r-resume-review.md
```

The four fixture paths are success-branch-only. The failure branch must not
create their directory or modify the real-anchor tests.

Ignored runtime output is allowed only at:

```text
runtime/wu2r-failure-evidence/run_wu2r_resume_001/
```

Random helper, raw capture, and harness ledger files are allowed only in the
system temporary directory during the approved call.

### 14.2 Protected paths

Resume may not modify:

- `src/trip_decider/acquisition_evidence.py`;
- `src/trip_decider/recovery.py`;
- `scripts/acquisition_harness.py`;
- all adapters, Schemas, validators, dependencies, lock files, `.gitignore`,
  existing tests, and existing fixtures;
- all WU2/WU2A/WU2R/FER Plans, Reviews, decisions, source policies, and
  commits;
- handbook, user/system configuration, or other repositories.

Any need for an eleventh repository path stops execution.

## 15. Commit sequence

Execution is linear on `main` after approval:

| Commit | Exact message | Paths | Responsibility | Gate |
|---|---|---|---|---|
| WU2R-Resume-C0 | `docs: record approved WU2R resume plan` | approved Plan only | record approved bytes | approved hash exact |
| WU2R-Resume-C1 | `docs: record WU2R resume acquisition gate` | acquisition decision | record new group, budget, FER link, policy, and `READY_TO_ATTEMPT` | no map-data call |
| WU2R-Resume-C2 | `chore: add WU2R resume integration interfaces` | new integration module | value types, injected boundaries, two explicit stubs | existing 169 green |
| WU2R-Resume-C3 | `test: add failing WU2R resume integration cases` | new test module | add RI01-RI06 | exact six-error red |
| WU2R-Resume-C4 | `feat: implement WU2R resume integration` | integration module only | compose FER/candidate/replay boundaries | same command 6/6; full 175 green |
| WU2R-Resume-C5 | `chore: add WU2R resume verification entry` | new verification script | deterministic offline modes | `PreAcquisition` green |
| WU2R-Resume-C6 | outcome-dependent message below | outcome-dependent paths | perform one call and record exactly one outcome | branch gates below |
| WU2R-Resume-C7 | `docs: prepare WU2R resume review` | Resume Review only | independent Review | branch-specific entry green |

C6 failure branch:

```text
message:
docs: record blocked WU2R resume acquisition

path:
docs/wu2r-resume-acquisition-decision.md
```

C6 success branch:

```text
message:
test: add completed WU2R resume acquisition anchor

paths:
docs/wu2r-resume-acquisition-decision.md
tests/test_wu2r_resume.py
four fixture files
```

The success C6 commit is prepared only after the five real-anchor cases and
all fixture gates are direct green. It has one responsibility: record and
verify the eligible anchor produced by the approved call.

No commit may be amended, squashed, reset, rebased, or rewritten. C3 remains
the valid interface red. Except C3, every commit ends green. C6 has exactly
one branch and never combines success and failure assertions.

## 16. Outcome and downstream authorization

The decision document ends with exactly one token:

```text
WU2R_ACQUISITION_COMPLETED
```

or:

```text
WU2R_ACQUISITION_BLOCKED_WITH_COMPLETE_EVIDENCE
```

Even after success:

```text
OLD_WU2_C5_C6_UNCHANGED:
PROHIBITED

AUTOMATIC_WU2R_RESUME:
PROHIBITED

AUTOMATIC_WU3_WU5_START:
PROHIBITED
```

Only after a successful Resume Review is accepted by Hugin may a new Plan
stage be proposed for downstream offline Recovery work:

```text
DOWNSTREAM_RECOVERY_PLANNING:
ELIGIBLE_AFTER_HUGIN_ACCEPTANCE
```

On the complete-evidence failure branch:

```text
DOWNSTREAM_RECOVERY_PLANNING:
NOT_AUTHORIZED
```

No outcome itself starts another work unit.

## 17. Completion criteria

Exactly 20 criteria are pre-registered:

1. Execute starts at the approved `main` HEAD with only the approved Plan,
   zero remotes/stashes, and the exact approved hash.
2. Handbook fetch/reconciliation and all eight `origin/main` reads are
   recorded; handbook HEAD/worktree remain unchanged.
3. WU2 and WU2R remain historically `BLOCKED`; WU2R-FER remains approved and
   all old history/documents are unchanged.
4. All 15 targeted frozen inputs and all 11 Schema hashes match before and
   after.
5. The old budget is recorded as unreconcilable, not guessed; only the new
   `WU2R-resume-001` budget is consumed.
6. Run ID, group ID, FER path, query hash, and request hash are explicit and
   identical across decision, runner, FER ledger, and replay where present.
7. Policy, endpoint, query/request bytes, ODbL attribution, and persistence
   gate match the frozen source decision before transport.
8. Actual calls stay within one scheduled Overpass POST, at most one
   byte-identical transport retry, and zero forbidden provider/source calls.
9. The FER ledger has started and terminal states, exact attempts/retries,
   cleanup, sink state, and no raw/secret/exception content.
10. Failure branch only: no anchor exists, the decision is
    `WU2R_ACQUISITION_BLOCKED_WITH_COMPLETE_EVIDENCE`, all values come from
    the durable ledger, and 175 tests plus 6/38/6 fixture totals are green.
11. Success branch only: every valid provider identity becomes one candidate
    and no same-label identity is selected, ranked, merged, or removed.
12. Success branch only: every frozen seed has one exact
    matched/ambiguous/unmatched record with resolving refs and no placeholder.
13. Success branch only: the raw anchor is byte-exact, licensed, attributed,
    free of prohibited account/secret fields, and committed only after gates.
14. Success branch only: replay reproduces independent request/candidate,
    accounting, record-local fact, and hash expectations with zero network.
15. C3 records the exact six-error interface red and C4 uses the
    character-identical command for 6/6 green without changing tests.
16. Branch verification is exact: failure is 175 green with no new fixture;
    success is 180 green with an 11/11 Resume module and 7/40/7 fixture totals.
17. Final Git diff stays within the ten-path whitelist; protected-file,
    dependency, Schema, validator, adapter, FER, recovery, and harness diffs
    are zero.
18. R10 scans find no secret, raw-body log, silent fallback, guessed identity,
    first/nearest/popularity/category selection, LLM judgment, warning-as-pass,
    or capability overclaim; temporary residue is zero.
19. The decision states the exact downstream-planning token and never
    automatically restores old WU2/WU2R or starts WU3/WU5.
20. C7 independently reports Git, hashes, call budget, FER evidence,
    red/green, branch outcome, fixture/replay where applicable, scope, R10,
    and all 20 statuses, then stops at an allowed Review state.

Criteria 10 and 11-14 are mutually exclusive branch criteria. Review marks
the non-applicable branch `— 不适用`, not failed or silently omitted.

## 18. Blocking and terminal conditions

Stop before transport if:

- branch, HEAD, worktree, remote/stash, approved Plan hash, frozen-input,
  Schema, or handbook gate differs;
- primary license/attribution/persistence/Overpass basis is inaccessible or
  no longer supports the planned anchor;
- query/request bytes or either frozen hash differs;
- the FER authoritative started envelope cannot be durably written;
- a secret, credential, non-project Python environment, or unapproved
  provider/source is required.

After the one scheduled call, do not retry or change parameters when:

- HTTP, response, JSON/shape, empty-elements, adapter, identity/coverage,
  policy, cleanup, ledger, or internal failure occurs;
- the single byte-identical transport retry is exhausted.

Record the complete-evidence failure branch and continue only to Review when
the FER ledger is durable and complete.

Stop the work unit as `BLOCKED` or `INCOMPLETE` if:

- an external attempt occurs but durable FER evidence is unavailable;
- an eleventh repository path or a change to FER, recovery, harness, adapter,
  Schema, validator, existing fixture/test, dependency, lock, `.gitignore`,
  Decision Gate, source policy, or old history is needed;
- integration cannot be implemented without HTTP/retry logic or identity
  selection in the new module;
- C3 red is not exactly six explicit `NotImplementedError` errors, C4 needs a
  test change, or any non-red commit ends with failed tests;
- a success anchor needs code/Schema/test repair after its five data-specific
  cases are authored;
- expected fixture output would have to be generated by the function under
  test or a real provider identity would need manual repair;
- raw response persistence is unauthorized or prohibited account/secret
  fields cannot be excluded;
- another data call, query, endpoint, retry, source, attempt group, FER work
  unit, route provider, planner, WU3, or WU5 becomes necessary;
- a push, remote, PR, history rewrite, handbook edit, or old-state change is
  needed.

The final Review status is exactly one:

```text
READY_FOR_HUGIN_REVIEW
BLOCKED
INCOMPLETE
```

`READY_FOR_HUGIN_REVIEW` is allowed for either a completed acquisition or a
blocked acquisition with complete FER evidence. It is not allowed when
evidence itself is incomplete.

## 19. Review contract

C7 may create only:

```text
docs/reviews/work-unit-2r-resume-review.md
```

It records:

- start/final HEAD, linear commits, full diff/stat, and ten-path scope;
- preserved WU2/WU2R/FER states and old failure;
- approved Plan and all frozen hashes before/after;
- handbook reconciliation;
- old-budget non-claim and new group authority;
- exact policy/query/request preflight;
- actual scheduled/physical/retry/forbidden call counts;
- FER run/group/path/hash, attempts, terminal code, cleanup, and sink;
- RI01-RI06 red/green;
- branch-specific tests and fixture/replay evidence;
- temporary/runtime residue and secret/fallback/identity-selection scans;
- all 20 completion criteria with non-applicable branch items explicit.

After C7 the work unit stops. It does not perform another call, resume an old
work unit, or create a downstream Plan.
