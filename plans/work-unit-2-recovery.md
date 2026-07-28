# Work Unit 2 Recovery Plan · Multi Identity Candidate Ingestion

Plan version: v0.1

Status: PENDING_HUGIN_APPROVAL

Prepared on: 2026-07-28

Execution authorization required:

```text
批准执行 Work Unit 2 Recovery
```

This Plan defines a new PER work unit. It does not amend, resume, reinterpret,
or complete the stopped WU2 C5/C6. Until Hugin approves this exact Plan, it
does not authorize a map-data call, an Overpass call, an anchor, a fixture,
an implementation change, a test change, a commit, WU3, or WU5.

## 1. 当前 WU2 状态、基线与冻结输入

### 1.1 Preserved project state

The state supplied by Hugin and checked against the repository is:

```text
WU0:              APPROVED
WU1:              APPROVED
WU1R:             APPROVED
WU1C:             APPROVED
WU2:              BLOCKED
WU2A:             INVESTIGATION_BLOCKED
WU2A-R:           APPROVED
WU2A-Resume:      APPROVED
WU2 Decision Gate: APPROVED
```

The following historical statements remain true:

```text
WU2 C5/C6: NOT AUTHORIZED
old WU2 Review: absent
old WU2 Plan/history: immutable
```

WU2 is `BLOCKED`, not failed. It correctly stopped because the originally
required unique target identities were not available. WU2 Recovery is a new
work unit and may not be described as continuing, fixing, or completing old
WU2 C5/C6.

### 1.2 Repository baseline

Measured before writing this Plan:

```text
repository: <repo>
branch: main
HEAD: 82ab40029e33423331dab412c1090a48553df2dd
worktree: clean
remotes: 0
stashes: 0
recovery Plan existed: no
```

The WU2R Execute gate will remeasure these values. It stops before WU2R-C0
unless:

```text
branch == main
HEAD == 82ab40029e33423331dab412c1090a48553df2dd
worktree contains only this approved, untracked Plan
remote count == 0
stash count == 0
approved Plan SHA256 matches Hugin's approval
```

The measured non-network regression baseline is:

```text
command:
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_harness -v

tests: 143
passed: 143
failures: 0
errors: 0
exit code: 0
```

### 1.3 Frozen historical and implementation inputs

These 17 paths are read-only throughout WU2R:

| Path | Bytes | SHA256 |
|---|---:|---|
| `PLAN.md` | 9914 | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `plans/work-unit-2-real-world-ingestion.md` | 32985 | `894D5844E140BF62EC1DB89B1BE318EB4945FF4A0BF8B139E9B82C0B4929BA2C` |
| `docs/wu2-source-decision.md` | 7235 | `E667ABCF6BEBFB522AE0EA76AFDD6EB628E11214B33773045AA5EC8B8C7FEA62` |
| `docs/real-world-source-policy.md` | 13095 | `B89D0836BCC17DD1D52CA215F38EF290134251295ECAC183BA7D54C45A1C4989` |
| `docs/real-world-contract-extension.md` | 14969 | `BD2280BFA2C51F2FEC8521F16BB7DE73667A39142FD89E04F6A515CB42B8963E` |
| `plans/work-unit-2-decision-gate.md` | 28521 | `CFD545EAFE52EB21CC504B99FA9756AD16D2C1E01DFCAAB74562EBDC43F6FA1C` |
| `docs/wu2-identity-boundary-decision.md` | 16670 | `44C1105298AE55FD9B0508B078D4D39124455242F927DAFAAF8E7E2605A77B57` |
| `docs/reviews/work-unit-2-decision-gate-review.md` | 12132 | `ABA6289752AFD621A91CBC3809BAE22B938C0726094F855CD8220CF5F120DFDA` |
| `docs/wu2a-resume-decision.md` | 23394 | `417F4E89A059CA99A5E96E960B839FA0297935F2438D76B100E7F8F30313B40A` |
| `docs/reviews/work-unit-2a-resume-review.md` | 14311 | `9CE29F71B065768B4BEE173144944A13003BC2838FCB42007ABCD8EAEEE4C64C` |
| `src/trip_decider/adapters/contracts.py` | 6817 | `0B82C64518CDF7BE0F3692C45405E31A2C80ACB28B7AAB2062992C52419AEE3B` |
| `src/trip_decider/adapters/open_data_poi.py` | 9551 | `F39EBF86B682EDECF182F6148178AEBA434A287B34A270FE84D3FAEE8F80944B` |
| `src/trip_decider/adapters/route_evidence.py` | 11273 | `DD290E6DB944E017C78C6CB6A34E6C8D771F55D234AA64CEBE2C001BC2E87BD9` |
| `src/trip_decider/ingestion.py` | 473 | `FD332377207278B9A4CB34EA9E900DEFFE6EEC69C1B169E03CABE98DBFA7176E` |
| `scripts/acquisition_harness.py` | 12845 | `AE6487D7F35E6A1CE351C07FD83DA219214705F1D3AC00611F5D7B9EF49559F9` |
| `schemas/candidates.schema.json` | 7786 | `3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2` |
| `schemas/evidence.schema.json` | 7479 | `54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B` |

All 11 Schemas remain frozen:

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

No dependency or lock change is authorized. The project continues to use
only the already locked WU1 dependency set.

### 1.4 Handbook state

The fixed handbook path is:

```text
<handbook>
```

The read-only fetch and reconciliation performed during this Plan found:

```text
local HEAD before/after fetch:
6502e423ad2a1ab30db7f805e8ebc8fb31fc500b

origin/main:
6502e423ad2a1ab30db7f805e8ebc8fb31fc500b

ahead/behind:
0/0

branch:
main

worktree:
clean
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

WU2R consequences:

- **R10:** all provider identities, seed states, query/response hashes,
  candidate references, counts, and call budgets come from bytes and
  commands. An unmatched seed is not represented as a nonexistent place.
- **PER:** this file is Plan only. Execute requires Hugin approval; Review
  occurs after the approved linear commit sequence.
- **Scope:** only the ten repository paths in §11 may change. A need for an
  eleventh path stops execution.
- **Fixture-first:** deterministic multi-identity and route-guard cases fail
  before implementation. The real anchor and offline-pipeline case are then
  committed in a second red before pipeline implementation.
- **No silent fallback:** array order, category, distance, popularity,
  provider label similarity, LLM judgment, and city-specific knowledge
  never resolve identity.

The handbook remains read-only.

## 2. Decision Gate 引用与授权边界

WU2R consumes the approved fixed decision:

```text
Decision: MULTI_IDENTITY_CANDIDATE
Rejected: UNIQUE_IDENTITY_REQUIRED_AT_ADAPTER
WU2_C5_C6_RESUME: NOT_AUTHORIZED_NOW
OLD_WU2_C5_C6_UNCHANGED: PROHIBITED
```

The accepted direction is:

```text
provider response
  -> preserve every valid provider identity
  -> one candidate per provider identity
  -> exact seed accounting
  -> record-local source facts
  -> route eligibility only after a stable candidate reference exists
```

The Decision Gate approval authorizes this Plan phase only. It does not
authorize Execute. Approval of WU2R will authorize only the new commits,
paths, data-call budget, and behavior in this Plan; it will not change the
historical WU2 state.

## 3. 新 Recovery 目标与非目标

### 3.1 Goal

WU2R will prove, with one legal replayable OSM anchor and deterministic
offline behavior, that:

1. all structurally valid provider identities in the authorized response can
   enter the candidate pool;
2. one provider identity maps to one candidate;
3. one input seed is classified as `matched`, `unmatched`, or `ambiguous`
   without selecting an alternative;
4. source facts remain bound to individual candidate IDs;
5. a route-preparation boundary accepts only resolved stable candidate refs;
6. unresolved identity prevents route preparation without calling a route
   provider.

“Complete candidate pool” in WU2R means:

> every element in the exact authorized response that passes the frozen
> adapter contract is retained.

It does not mean OSM is globally complete, the query found every real place,
or the candidates are all useful for a trip.

### 3.2 Explicit non-goals

WU2R does not implement or claim:

```text
planner
identity resolver
user-confirmation UI
recommendation
ranking
route optimization
OSRM acquisition
route evidence
evidence scoring
support/freshness/display-state mapping
feasibility
destination discovery
HTML/UI
real itinerary
WU3 or WU5 behavior
```

It does not prove which 篁岭 or 婺源县 identity the user intended.

## 4. 与旧 WU2 的区别

The stopped WU2 assumed:

```text
seed
  -> one unambiguous POI
  -> route acquisition
```

It also planned an approximately-five-target anchor and two route responses.
That sequence cannot be recovered honestly from the observed source.

WU2R instead freezes:

```text
seed set
  -> exact authorized OSM response
  -> complete valid provider-identity candidate pool
  -> explicit seed accounting
  -> record-local candidate facts
  -> route guard
  -> no route acquisition in this work unit
```

Differences are deliberate:

| Old WU2 assumption | WU2R ruling |
|---|---|
| approximately five unique target POIs | all valid identities in the authorized response |
| label can identify a route endpoint after POI lookup | route endpoints are candidate IDs only |
| route acquisition follows POI capture | no route call while the identity boundary remains unresolved |
| zero dirty cases planned for the real fixture | one deterministic dirty mutation, because the frozen fixture Schema requires `minItems: 1` |
| expected 7 fixtures / 41 documents / 6 dirty cases | expected 7 fixtures / 40 documents / 7 dirty cases |
| old `run_jiangxi_smoke` implementation | protected and unchanged |

The fixture-count correction follows the current Schema bytes. It does not
rewrite or retroactively correct the old WU2 Plan.

## 5. Candidate 模型与 ingestion 边界

### 5.1 One provider identity equals one candidate

The fixed identity tuple is:

```text
(provider.name, provider.record_type, provider.record_id)
```

For WU2R:

```text
provider.name == osm
provider.record_type in node | way | relation
provider.record_id == exact OSM ID string
```

Each unique tuple produces exactly one candidate through the frozen
`normalize_open_data_pois` adapter. Multiple candidates may have the same
`label`. Candidate IDs remain the adapter's existing stable SHA256-derived
IDs over the complete provider identity.

WU2R will not modify that adapter, its namespace, its stable-ID function, or
the Candidate Schema.

### 5.2 Candidate fields preserved

Every candidate retains:

```text
candidate_id
candidate_kind
label
provider.name
provider.record_type
provider.record_id
provider.categories
provider.external_status
provider.data_policy
location + explicit WGS84
location.source_refs
candidate.source_refs
generation_reason
```

No category is converted into a recommendation or travel taxonomy. A
`tourism=attraction` record does not outrank a `place=hamlet` record.

### 5.3 No candidate-local ambiguity object

WU2R will not add:

```yaml
ambiguity:
  alternatives: []
```

Ambiguity belongs to a seed/context and a set of candidates, not to an
individual candidate. Adding such a field would require a separately
approved contract remediation because the Candidate Schema is closed.

## 6. Seed 状态模型

### 6.1 Frozen seed set for the real replay

The real replay uses the exact frozen names already present in the approved
acquisition recipe:

```text
婺源县
婺源
江岭
篁岭
李坑
庆源
```

No name is added, normalized, translated, fuzzed, or replaced during
execution.

### 6.2 Deterministic matching rule

For each seed, compare it with candidate `label` by exact Unicode string
equality:

```text
0 candidate refs -> unmatched
1 candidate ref  -> matched
2+ candidate refs -> ambiguous
```

Candidate refs are sorted by stable candidate ID. Source response order,
category order, location, distance, popularity, and first result do not
affect status.

### 6.3 State meanings

`matched`:

> this exact seed has one candidate in this candidate-pool snapshot.

It does not prove global uniqueness or user intent.

`ambiguous`:

> this exact seed has multiple candidates in this candidate-pool snapshot.

Every alternative candidate ref is retained. There is no preferred ref.

`unmatched`:

> this exact seed has no candidate in this candidate-pool snapshot.

It does not mean the place is absent from OSM or the real world.

### 6.4 Where seed accounting lives

The current artifact Schemas do not define a seed-accounting artifact or an
N-way identity relation. WU2R therefore freezes seed accounting in two
non-artifact locations:

1. the strict `replay.json` control document in the new fixture;
2. typed WU2R runtime/result objects returned by the recovery module.

It is not inserted into `candidate.ambiguity`, `evidence.json`, or
`candidate.rejected_inputs`.

`rejected_inputs` remains empty because an unmatched seed is not a malformed
provider record. A placeholder candidate is forbidden.

The strict runtime shape is:

```yaml
seed:
status: matched | unmatched | ambiguous
candidate_refs: []
```

Invariants:

- `matched` has exactly one ref;
- `unmatched` has zero refs;
- `ambiguous` has at least two distinct refs;
- every ref resolves in the current candidate artifact;
- every ref's candidate label exactly equals the seed;
- every supplied seed appears exactly once.

## 7. Evidence 边界

WU2R does not create an Evidence artifact and does not implement WU3.

It exposes a typed, execution-local `record-local fact view` for each
candidate:

```yaml
candidate_id:
provider:
  name:
  record_type:
  record_id:
categories:
location:
source_refs:
```

This view is a lossless projection of fields already present in the
Candidate artifact. It contains no:

```text
support_status
derivation
freshness score
display_status
conflict resolution
preferred identity
correctness claim
```

For two same-label records, acceptable statements are:

```text
candidate_A has source category place=hamlet
candidate_B has source category tourism=attraction
```

The following statement is forbidden:

```text
candidate_B is the correct POI
```

WU3 remains responsible for mapping record-local source facts into the
orthogonal Evidence Contract, including identity-ambiguity representation,
support, derivation, freshness, conflict, and display status. If WU3 needs a
new artifact or Schema, it must use a separate contract-remediation PER
cycle.

## 8. Route 边界

### 8.1 Route preparation accepts stable refs only

The WU2R route guard consumes seed-accounting results and produces:

```yaml
from_candidate_ref:
to_candidate_ref:
```

It may produce that pair only when both selected seed records have status
`matched`, each contains exactly one candidate ref, both refs resolve in the
same candidate artifact, and both referenced candidates have explicit
provider-backed coordinates.

Natural-language labels never enter `normalize_route_evidence`.

### 8.2 Unresolved identity blocks the route boundary

If either endpoint is:

```text
ambiguous
unmatched
missing from seed accounting
structurally inconsistent
```

the route guard returns a deterministic `ValidationProblem` and no endpoint
pair. It does not select the first alternative, call a route provider, or
change the seed state.

An explicit future user choice could supply a stable candidate ref through a
separately designed constraint/confirmation path. That path is not
implemented by WU2R.

### 8.3 No route acquisition

WU2R performs:

```text
OSRM calls: 0
route response fixtures: 0
route evidence facts: 0
```

The existing route adapter remains frozen and unused by the real Recovery
replay. Synthetic deterministic tests exercise only the route guard.

## 9. Data acquisition、license 与 replay 策略

### 9.1 Source and authorization

WU2R reuses the approved WU2A-Resume recipe and the frozen WU1C policy:

```text
source: OpenStreetMap through Overpass
license: ODbL-1.0
attribution: © OpenStreetMap contributors
capture mode: persistent_anchor
storage policy: persistent_allowed
replay allowed: true
fixture allowed: true
compatibility basis: ADAPTER_COMPATIBLE_ONLY
```

Before the data call, WU2R-C1 records current direct access results for these
primary pages:

```text
https://www.openstreetmap.org/copyright
https://opendatacommons.org/licenses/odbl/1-0/
https://osmfoundation.org/wiki/Licence/Attribution_Guidelines
https://wiki.openstreetmap.org/wiki/Overpass_API
```

No search summary may substitute for a page. If an applicable license,
attribution, replay, or shared-endpoint basis cannot be checked, WU2R stops
before acquisition.

### 9.2 Exact authorized query

The only data endpoint is:

```text
https://overpass-api.de/api/interpreter
```

The exact UTF-8 query is:

```text
[out:json][timeout:25];
rel(id:3046784)->.county;
.county map_to_area->.scope;
(
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["amenity"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["historic"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["leisure"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["natural"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["place"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["tourism"];
);
out center tags;
```

Frozen hashes from the approved recipe:

```text
query SHA256:
5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F

form-encoded request SHA256:
6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045
```

The Execute acquisition budget is:

```text
Geofabrik GET: 0
Overpass scheduled POST: 1
byte-identical transport retry: at most 1
second Overpass instance: 0
O1/O3 query: 0
OSRM: 0
Nominatim: 0
commercial maps: 0
other data source: 0
```

Only a transport failure may use the one retry. HTTP failure, JSON failure,
empty elements, contract failure, or selection-coverage failure is not
retryable.

### 9.3 Capture protocol

The existing acquisition harness remains unchanged. An execution-only helper
may exist under the system temporary directory and must:

1. use the frozen request bytes;
2. write the ledger before transport;
3. capture response bytes only in system temporary storage;
4. record request hash, attempt IDs, endpoint, timestamps, HTTP status,
   response length/hash, content type, retry relation, and terminal status;
5. parse without coercion and run the frozen POI adapter;
6. verify all acceptance gates before copying the raw bytes into the fixture;
7. delete helper, ledger, atomic ledger temp, and rejected raw captures in
   `finally`;
8. report residue counts from commands.

No repository-local temporary Python file is allowed.

The committed raw anchor may be created only after:

- the response is HTTP 2xx JSON;
- `elements` is non-empty;
- every returned element passes the frozen adapter;
- provider identities are unique;
- all returned elements are retained;
- exact seed accounting contains at least one `matched`, one `ambiguous`,
  and one `unmatched` state, so the fixture covers the Recovery boundary;
- no contributor account fields, credential, secret, or unapproved payload
  are present;
- license and attribution metadata are complete;
- expected candidate and seed-accounting values are authored independently
  from the captured bytes before the pipeline green.

If any gate fails, no anchor commit is created and no query is changed.

## 10. Fixture 设计

### 10.1 Planned real anchor

WU2R creates, only after approval and a successful acquisition gate:

```text
fixtures/jiangxi_multi_identity_smoke/
  README.md
  case.json
  replay.json
  osm-pois.json
```

`osm-pois.json` contains the exact eligible Overpass response bytes.
`replay.json` is a strict WU2R control document, not a new artifact type.
`case.json` is a WU1C `real_anchor` / `open_data_anchor` manifest.

### 10.2 Manifest and bundle

The fixture has:

```text
fixture_type: real_anchor
source.kind: open_data_anchor
bundle_closure: closed
root artifact: candidates
embedded documents: 2
  request artifact
  candidates artifact
dirty cases: 1
```

The candidate root reaches the request through `request_ref`. No evidence or
route document is invented merely to raise the document count.

The one deterministic dirty mutation removes a required provider identity
field from the embedded Candidate artifact and expects the exact Schema
problem. It verifies structural rejection only; it does not mutate or claim
anything about the real OSM fact.

With the six existing fixtures, the repository-level expected totals become:

```text
fixture directories: 7
embedded documents: 40
dirty cases: 7
```

### 10.3 Replay control document

`replay.json` requires:

```text
schema/version token
exact query bytes and query SHA256
exact form request SHA256
endpoint and retrieval time
response SHA256 and byte count
source base timestamp when present
license, attribution, and data-policy fields
raw response relative path and SHA256
expected request/candidate artifact IDs and file hashes
complete frozen seed list
matched/unmatched/ambiguous accounting
candidate ref lists
record-local fact expectations per candidate
adapter mapping/version identity
network_required: false
coverage and non-coverage
```

Paths must be safe fixture-relative paths. Unknown fields, path traversal,
hash drift, missing seeds, duplicate refs, a non-resolving ref, and an extra
fixture file hard-fail.

### 10.4 Fixture provenance and limitations

`README.md` states:

- the real source and exact acquisition attempt;
- license and attribution;
- that expected values were transcribed/calculated from source bytes rather
  than produced by the recovery function under test;
- covered behavior: candidate plurality, exact seed accounting,
  candidate-local provider facts, offline replay;
- non-coverage: OSM completeness, geographic truth, user intent, entrance
  accuracy, routes, route quality, current traffic, opening hours,
  recommendation, evidence rating, feasibility, and planning.

No “unique correct POI” fixture is allowed.

## 11. 精确 Scope

### 11.1 Ten-path repository whitelist

Only these paths may be created or modified:

```text
plans/work-unit-2-recovery.md
docs/wu2-recovery-source-and-capture.md
src/trip_decider/recovery.py
tests/test_wu2_recovery.py
fixtures/jiangxi_multi_identity_smoke/README.md
fixtures/jiangxi_multi_identity_smoke/case.json
fixtures/jiangxi_multi_identity_smoke/replay.json
fixtures/jiangxi_multi_identity_smoke/osm-pois.json
scripts/verify_wu2_recovery.ps1
docs/reviews/work-unit-2-recovery-review.md
```

Ignored outputs may be created only under:

```text
runtime/wu2-recovery/
```

System-temporary helper, ledger, and capture files are permitted only during
the approved acquisition and must be deleted. They are not repository paths.

### 11.2 Protected paths

WU2R may not change:

```text
old WU2 Plan, commits, source decision, interface, or Review absence
WU2A/WU2A-R/WU2A-Resume Plans, decisions, Reviews, code, or tests
Decision Gate Plan, decision, Review, or commits
all Schemas
schema_validation.py
fixture_validation.py
verification_entry.py
all existing adapters and adapter contracts
scripts/acquisition_harness.py
all existing fixtures and tests
dependency and lock files
.gitignore
PLAN.md
handbook
user/system configuration
other repositories
```

A need for an eleventh repository path or any protected-path edit stops
execution. No “small compatibility fix” is allowed inside WU2R.

## 12. 测试与 Red → Green

### 12.1 Public Recovery interfaces

WU2R-C2 adds importable types and functions to
`src/trip_decider/recovery.py`:

```text
SeedMatch
RecordLocalFact
RecoveryCandidateResult
RouteEndpointPair
RecoveryRunSummary

ingest_candidate_pool(snapshot, seeds, context)
prepare_route_endpoints(candidate_result, from_seed, to_seed)
run_wu2_recovery(replay_root, output_root)
```

Dataclasses, field names, and function signatures are real interfaces.
Behavior is explicitly `NotImplementedError` until its approved green
commit. There is no network client, endpoint, query, fallback, or hidden
default in C2.

The implementation reuses the existing `ValidationResult` and seven-field
`ValidationProblem`; it does not create a second error model.

WU2R-specific stable problem codes are:

```text
RECOVERY_SEED_INPUT_INVALID
RECOVERY_CANDIDATE_ARTIFACT_INVALID
RECOVERY_ROUTE_ENDPOINT_UNRESOLVED
RECOVERY_REPLAY_INVALID
RECOVERY_REPLAY_HASH_MISMATCH
RECOVERY_NETWORK_ATTEMPTED
```

Errors use stable pointers/messages and safe type labels. They do not copy
input values, response bodies, third-party exceptions, or secrets.

### 12.2 C3 → C4 deterministic contract red/green

Character-identical command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2_recovery -v
```

C3 pre-registers exactly 16 cases:

```text
MI01 every valid provider identity remains a distinct candidate
MI02 same-label alternatives produce ambiguous with all refs
MI03 one exact candidate produces matched with one ref
MI04 no exact candidate produces unmatched with zero refs
MI05 response order does not change candidate or accounting order
MI06 category differences neither rank nor remove alternatives
MI07 record-local facts retain candidate/provider/category/location/source
MI08 unmatched produces no placeholder and no rejected-input misuse
MI09 duplicate seed hard-fails
MI10 empty/non-string seed hard-fails without coercion
MI11 accounting refs all resolve to same-snapshot candidates

RG01 two matched seeds produce an exact candidate-ref pair
RG02 ambiguous origin blocks route preparation
RG03 ambiguous destination blocks route preparation
RG04 unmatched endpoint blocks route preparation
RG05 missing/inconsistent accounting blocks without label lookup
```

C3 required red:

```text
tests: 16
passed: 0
failures: 0
errors: 16
cause: explicit public-interface NotImplementedError
network attempts: 0
```

Import, dependency, path, syntax, malformed-test, live-network, and
unexpected-error counts must be zero.

C4 uses the same command for:

```text
tests: 16
passed: 16
failures: 0
errors: 0
network attempts: 0
```

C4 may modify only `src/trip_decider/recovery.py`. It may not modify tests,
fixtures, adapters, Schemas, validators, or dependencies.

### 12.3 C5 → C6 real anchor and offline pipeline red/green

C5 performs the one newly authorized acquisition only after §9 gates pass.
It then adds the four fixture files and extends the same test module with
five cases:

```text
JA01 exact raw/query/request hashes and open-data policy
JA02 raw response retains the complete valid provider-identity pool
JA03 independent expected Candidate artifact equals adapter output
JA04 exact seed accounting and record-local facts equal fixture expectations
JA05 offline Recovery run emits expected outputs with no network
```

Before `run_wu2_recovery` is implemented, the character-identical command is:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2_recovery -v
```

C5 required red:

```text
tests: 21
passed: 20
failures: 0
errors: 1
red test: JA05 only
cause: run_wu2_recovery explicit NotImplementedError
network attempts during tests: 0
```

The live acquisition is not a test and is reported separately. JA01-JA04
must be green before the C5 commit. Expected artifact and accounting values
are written from source bytes and the specification before JA05 green. The
adapter or recovery function may not generate expected values.

C6 uses the exact same 21-test command for:

```text
tests: 21
passed: 21
failures: 0
errors: 0
network attempts: 0
```

C6 may modify only:

```text
src/trip_decider/recovery.py
scripts/verify_wu2_recovery.ps1
```

It may not change tests or fixture bytes.

### 12.4 Full verification entry

C6 and C7 run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu2_recovery.ps1
```

The entry performs in one offline execution:

1. project `.venv` interpreter/site-packages assertions;
2. exact `requirements.lock` runtime match and `pip check`;
3. all 11 Schema metadata/registry checks;
4. the existing 143-test explicit suite;
5. all 21 WU2R tests;
6. fixture discovery and manifest validation;
7. raw/replay/document/payload hash checks;
8. candidate, seed-accounting, record-local fact, and route-guard invariants;
9. ten-path scope and all frozen-input hash checks;
10. network denial with attempt count;
11. secret, silent-fallback, guess/infer, first/nearest/popularity/category
    selection, and warning-as-pass scans;
12. system-temp and runtime residue checks;
13. deterministic nonzero exit on any failure.

Expected successful totals:

```text
existing tests: 143
WU2R tests: 21
total tests: 164 passed, 0 failures, 0 errors
fixture directories: 7
embedded documents: 40
dirty cases: 7
recovery anchors: 1
route response fixtures: 0
route evidence facts: 0
offline network attempts: 0
temporary residue: 0
```

The actual candidate count, provider identity count, per-status seed counts,
response byte count, and hashes must come from execution output. The Plan
does not predeclare them as unchanged OSM facts.

## 13. Commit 序列

The approved Execute sequence is linear:

| Step | Exact commit message | Repository paths | Completion gate |
|---|---|---|---|
| WU2R-C0 | `docs: record approved WU2 recovery plan` | approved Plan only | approved SHA256 matches; no Plan edit |
| WU2R-C1 | `docs: record WU2 recovery source and capture gate` | `docs/wu2-recovery-source-and-capture.md` | primary-source basis, exact budget/query, persistence and stop gates recorded |
| WU2R-C2 | `chore: add WU2 recovery interfaces` | `src/trip_decider/recovery.py` | imports green; all three behaviors explicitly unimplemented |
| WU2R-C3 | `test: add failing multi identity recovery cases` | `tests/test_wu2_recovery.py` | valid 16-error interface red |
| WU2R-C4 | `feat: implement candidate accounting and route guard` | `src/trip_decider/recovery.py` | identical 16/16 green; no test change |
| WU2R-C5 | `test: add multi identity open-data anchor and pipeline red` | four fixture files plus `tests/test_wu2_recovery.py` | acquisition gate passed; 20/1 valid red |
| WU2R-C6 | `feat: implement offline WU2 recovery replay` | `src/trip_decider/recovery.py`, `scripts/verify_wu2_recovery.ps1` | identical 21/21 and full 164 green |
| WU2R-C7 | `docs: prepare Work Unit 2 recovery review` | Review only | independent full entry green |

No commit may be amended, squashed, rebased, reset, or rewritten. C3 and C5
remain as valid red commits. Except C3 and C5, every commit must end green.
Tests and implementation never share a commit.

The original WU2 commits and the Decision Gate commits remain unchanged.

## 14. 完成判定

WU2R pre-registers exactly 20 completion criteria:

1. Execute starts from `main@82ab400`, with only the approved Plan untracked,
   zero remotes, zero stashes, and the approved Plan hash exact.
2. Handbook fetch/reconciliation and eight `origin/main` rereads are
   recorded; handbook HEAD/worktree remain unchanged.
3. WU2 remains historically `BLOCKED`; old C5/C6 remain unauthorized and no
   old WU2/WU2A/Decision Gate commit or document changes.
4. All 17 frozen inputs and all 11 Schema hashes match before and after.
5. The final Git diff is restricted to the ten-path whitelist and the eight
   commit messages match their single responsibilities.
6. Dependency, lock, validator, adapter, existing fixture/test, `.gitignore`,
   and `PLAN.md` diffs are zero.
7. C1 records direct primary-source access, ODbL attribution/replay basis,
   exact query/request hashes, and the one-POST acquisition budget.
8. Acquisition uses only the approved Overpass endpoint/query, at most one
   byte-identical transport retry, and zero forbidden provider/data calls.
9. The committed anchor has a complete ledger, eligible raw response hash,
   license/attribution, no secret/account metadata, and zero temp residue.
10. Every valid provider identity in the authorized response yields exactly
    one candidate; no same-label identity is dropped or preferred.
11. Every frozen seed has exactly one matched/unmatched/ambiguous record with
    valid candidate refs and no placeholder or nonexistent-place claim.
12. Record-local facts remain candidate-bound and contain no preference,
    evidence rating, or identity-correctness claim.
13. Route preparation emits only stable candidate refs for two matched
    endpoints and deterministically blocks ambiguous/unmatched/inconsistent
    endpoints without a route call.
14. C3 records the valid 16-case `NotImplementedError` red and C4 uses the
    character-identical command for 16/16 green without changing tests.
15. C5 records 20 green plus JA05-only interface red; C6 uses the
    character-identical command for 21/21 green without changing tests or
    fixture bytes.
16. The real fixture is a valid open-data anchor with a CLOSED candidate
    root, 2 embedded documents, 1 exact dirty mutation, explicit coverage,
    and explicit non-coverage.
17. Offline replay reproduces the independent Candidate artifact, seed
    accounting, record-local facts, and output hashes with networking denied.
18. Full verification reports 164 green tests, 7 fixtures, 40 documents, 7
    dirty cases, 0 route facts, 0 network attempts, and 0 residue; all dynamic
    counts come from commands.
19. R10 scans find no secret, silent fallback, guessed CRS/provider/identity,
    first/nearest/popularity/category selection, LLM source, city-specific
    branch, warning-as-pass, or capability overclaim.
20. C7 independently provides Git, hash, source/call, red/green, fixture,
    scope, R10, and all 20 completion results, then ends only as
    `READY_FOR_HUGIN_REVIEW`, `BLOCKED`, or `INCOMPLETE`.

WU2R completion means only:

> one legal replayable OSM response can be normalized into a plural
> candidate pool with explicit seed accounting, candidate-local source
> facts, and a deterministic pre-route identity guard.

It does not mean original WU2 was retrospectively complete, a route exists,
an identity is resolved, or WU3/WU5 may start automatically.

## 15. Blocking

Stop WU2R before the next commit if:

- branch, HEAD, worktree, remote, stash, Plan hash, frozen hash, or handbook
  gate differs;
- the approved Plan would need editing during Execute;
- a primary license/attribution/replay/Overpass policy page is inaccessible
  or no longer supports the planned persistent anchor;
- the exact query/request bytes or hashes differ;
- the one approved request fails, is empty, is malformed, or requires a
  changed query, second endpoint, extra retry, or another data source;
- the response cannot demonstrate at least one matched, ambiguous, and
  unmatched seed without changing the frozen seed set;
- any returned record requires fuzzy matching, first/nearest/category
  selection, manual coordinates, guessed CRS/ID/provider, or LLM judgment;
- a valid provider record would need to be dropped, merged, or manually
  patched for the adapter to accept it;
- persistence would retain contributor account metadata, secret, credential,
  prohibited bytes, or data without the recorded license basis;
- raw/helper/ledger/atomic-temp deletion cannot be independently verified;
- expected fixture values would have to be generated by the adapter or
  recovery function under test;
- C4 requires a test change or C6 requires a test/fixture change;
- a non-red commit ends with failed tests or an unexpected error appears in a
  red commit;
- the implementation needs an eleventh path, dependency, Schema, validator,
  adapter, old ingestion module, existing fixture, or policy change;
- seed accounting must become a formal artifact or candidate-local field;
- identity ambiguity must be represented in Evidence before WU3;
- an OSRM/route/map provider call becomes necessary;
- planner, recommendation, identity resolver, evidence scoring, feasibility,
  UI, WU3, or WU5 behavior becomes necessary;
- any push, remote, PR, history rewrite, or old WU2 status change is needed.

On a blocker, preserve only already valid commits, report the exact command
and observed result, and stop as `BLOCKED` or `INCOMPLETE`. Do not change the
query, switch source, repair protected files, resume old WU2 C5/C6, create a
new work-unit Plan, or begin WU3/WU5.

## 16. Review contract

WU2R-C7 may create only:

```text
docs/reviews/work-unit-2-recovery-review.md
```

The Review must provide:

- start/final HEAD and all WU2R-C0-C7 commits;
- full diff/stat and ten-path whitelist reconciliation;
- proof that old WU2/WU2A/Decision Gate history and states are unchanged;
- approved Plan and all frozen hash before/after comparisons;
- handbook before/after reconciliation;
- official-source access and exact data-call/retry accounting;
- request/query/response hashes and capture-cleanup evidence;
- C3→C4 and C5→C6 red/green commands, IDs, counts, and classifications;
- fixture root, document, dirty-case, candidate, seed-state, and fact counts;
- route-guard pass/block evidence and zero route-provider calls;
- 164-test full verification and offline-network evidence;
- secret/fallback/guess/scope scans;
- all 20 completion criteria as `✓ 已完成`, `⚠ 已知限制`, or `✗ 未完成`.

If any criterion is incomplete, the Review may not declare completion.
After Review, execution stops. It does not start old WU2, WU3, WU5, another
Plan, a push, or a remote.

