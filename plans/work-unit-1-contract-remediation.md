# Work Unit 1C · Real-world Contract Compatibility

Plan version: `v0.1`

Status: `PENDING_HUGIN_APPROVAL`

Planned work unit: `WU1C`

Plan date: `2026-07-28`

This Plan is the only WU1C file created before approval. It does not authorize
Execute. Approval requires the explicit instruction:

```text
批准执行 Work Unit 1 Contract Remediation
```

## 1. Current baseline

### 1.1 Repository

Measured from the project worktree:

```text
repository: <repo>
branch: main
HEAD: 49394356c9fd81f951d439336d6243dc7d9452e9
worktree: clean
remotes: 0
stashes: 0
```

The HEAD above is the final WU1R Review commit. WU0, WU1 and WU1R are
historical approved inputs. WU1C will not amend, reset, rebase, squash, or
rewrite any existing commit.

### 1.2 Frozen project inputs

| Path | Bytes | SHA256 |
|---|---:|---|
| `PLAN.md` | 9,914 | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `docs/architecture.md` | 7,054 | `CA5B6F7D345E11623C94C13CDD73C0E774282AFD88F9E2E036035ED2396BB6F4` |
| `docs/artifact-contracts.md` | 18,478 | `695C0AC6738B71852DC60ADAFD2A98B974C5EC65BB744D19B0E22EC3550497BF` |
| `docs/reviews/work-unit-1-review.md` | 26,427 | `C3E7CCF3D0F1A0181AD36E0435FCC481E56E3B3DAF42A921DB4E2E7EC72A659E` |
| `docs/reviews/work-unit-1-remediation-review.md` | 18,132 | `C7769D8DFEF0AE636D992475E40DB6C7E4498AB084B32B571D10BE8574256FF0` |

These five paths are read-only in WU1C. The two WU1 Reviews retain their
historical meanings. WU1C documents an additive compatibility correction; it
does not rewrite the claim that WU1 originally implemented the structural
contract available at that time.

### 1.3 Schema baseline

The current registry contains exactly 11 JSON Schema files:

| Schema | SHA256 |
|---|---|
| `candidates.schema.json` | `B93BF742F87193D85FA776967A31C404BF0C7578B3C456B7661713705A3BCA93` |
| `common.schema.json` | `A1D97F210F8DC66743DBEFB5ECE2CC4BB6F70F6FBBDDDE1BB7A4EC913BE1FA6F` |
| `constraint-parse.schema.json` | `0D41493B52B6178AEE8DE44B2F3607B193B62C263AD79DEF380B638B22B400A4` |
| `constraints.schema.json` | `25069E0DEFBDC03FEA7E92E83EE10F952A31A2B18BDC3678D17786C537EE4473` |
| `evidence.schema.json` | `54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B` |
| `fixture-case.schema.json` | `8556FDD9699298E91D558589B8FC48D028C7F925F923FB284ACE78013F799067` |
| `plan.schema.json` | `81EEB5899C33F19DC6FA059C7D447D747E72E355F3084D925FD9410272389BD3` |
| `plan-diff.schema.json` | `37B94FE5E03A73B046D7E6D79BEABF31C4105E50CD54DE520CA6C293AB3E8B43` |
| `previous-plan.schema.json` | `59692D17EB79C7EA2D4A2E2866898DD97A0E49B97834EC8AFC5EAB46A80BEDAC` |
| `request.schema.json` | `BC7F46E9A85CE9697F9BA01FF1506A5B56C161F2F6B5140D91FCF0B100762914` |
| `violations.schema.json` | `C117415030993C24649B17837EC2A35C69A2F1CEC7D923742ABD383BA85B394F` |

WU1C will keep the count at 11. It will modify only the three existing Schema
files explicitly listed in §5. No new Schema file, artifact type, registry
entry, or version-dispatch implementation is planned.

### 1.4 Executable verification baseline

Measured command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu1.ps1
```

Result:

```text
exit: 0
schemas: 11
tests: 82
fixtures: 6
documents: 38
dirty cases: 6
```

Toolchain:

```text
Python: 3.11.9, project .venv
Windows PowerShell: 5.1.26100.8875
Git: 2.53.0.windows.1
```

WU1C adds no dependency and does not recreate `.venv`.

## 2. Handbook state and effects

Fixed path:

```text
<handbook>
```

After `git fetch origin --prune`:

```text
local HEAD: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
branch: main
worktree: clean
```

The following files were reread from `origin/main`:

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

Effects on WU1C:

- R10: CRS, provider identity, source class, retention permission, and replay
  permission must be explicit. No field overloading, guessed provider, guessed
  CRS, warning-as-pass, or default authorization is allowed.
- PER: this document must be approved before C0—C6 Execute; one whole-unit
  Review follows execution.
- Scope: the nine-path whitelist and 18 completion criteria are exact. Any
  extra path or required implementation logic stops the work unit.
- Fixture-first: the compatibility cases are committed red before Schema
  changes. Expected pointers and rules are authored from this Plan, never
  generated from validator output.

The handbook repository is fully protected and will not be modified.

## 3. Evidence of the WU1 gaps

### 3.1 Candidate provider identity gap

`docs/artifact-contracts.md` describes optional `provider_ids`, `categories`
and candidate status. The implemented `candidates.schema.json` permits only:

```text
candidate_id
candidate_kind
label
parent_candidate_id
location
source_refs
evidence_fact_refs
generation_reason
coarse_feasibility_refs
coarse_plan_refs
```

Because `additionalProperties` is false, a real provider ID, provider-native
category, and provider-native status cannot be retained as entity properties.
Encoding them in `source_refs` or prose would overload provenance or
explanation fields and is explicitly prohibited.

### 3.2 CRS and location provenance gap

The current coordinate location requires only:

```json
{
  "kind": "coordinates",
  "latitude": 28.0,
  "longitude": 117.0
}
```

It has no CRS and no fact-local coordinate provenance. Provider inference is
not acceptable: coordinate APIs distinguish WGS84, GCJ-02 and BD-09, and
official documentation warns that an incorrect coordinate type causes
positional offset. A longitude/latitude pair without CRS therefore cannot be
a safe GIS value.

### 3.3 Fixture/source-policy gap

`fixture-case.schema.json` allows `fixture_type=real_anchor`, but its `source`
kind is limited to:

```text
frozen_contract
user_supplied_anchor
```

It cannot distinguish open licensed data, explicit provider authorization, or
synthetic contract data. It also cannot record why persistence and replay are
allowed.

### 3.4 Historical verification constraint

`verification_entry.py` freezes:

```text
schema count: 11
default discovery: 82
WU1/WU1R historical scope
```

WU1C therefore will:

- modify existing Schema files rather than add a twelfth Schema;
- name its new test module `wu1c_contract_compatibility_cases.py`, which is
  outside default `test*.py` discovery;
- use a new WU1C entry to run the explicit combined suite;
- keep `verification_entry.py` and `verify_wu1.ps1` byte-identical.

The WU1 entry is a historical WU1/WU1R verifier, not a WU1C capability claim.
At WU1C HEAD its frozen cumulative scope check would reject legitimate later
work-unit paths. WU1C does not weaken or modify that check; it reruns the same
82 tests and 6/38/6 fixture surface through its own bounded entry.

## 4. Goal and non-goals

### 4.1 Goal

WU1C makes the existing artifact system structurally able to carry real-world
external records without ambiguity:

```text
provider identity + native metadata
explicit coordinate CRS + location provenance
orthogonal data-use policy
fixture persistence/replay justification
```

The existing generic validator must enforce the extension from Schema alone.

### 4.2 WU1C does

- extend the candidate contract with nested provider metadata;
- extend coordinate location with an explicit CRS and coordinate source refs;
- define orthogonal source, capture, retention, replay, and authorization
  policy fields;
- extend fixture metadata for eligible persistent anchors;
- add deterministic synthetic contract tests and a WU1C verification entry;
- prove all legacy artifacts and fixtures remain valid.

### 4.3 WU1C does not

- implement any map adapter, client, HTTP call, crawl, POI query, or route;
- select a production provider;
- save commercial API responses or create a real anchor;
- convert coordinates or infer a CRS;
- implement evidence mapping, truth scoring, freshness, planning, routing,
  optimization, rendering, or v1 discovery;
- add an artifact type, a Schema file, a dependency, or a validator branch;
- alter existing fixture bytes, tests, validator modules, WU1R entry, Reviews,
  frozen product plan, or Git history;
- create WU2 content.

## 5. Exact scope

### 5.1 Nine-path whitelist

WU1C Execute may create or modify exactly:

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

Maximum changed path count: `9`.

### 5.2 Explicitly protected

```text
PLAN.md
docs/architecture.md
docs/artifact-contracts.md
docs/reviews/work-unit-1-review.md
docs/reviews/work-unit-1-remediation-review.md
plans/work-unit-0-bootstrap-d0.md
plans/work-unit-1-contracts-fixtures.md
plans/work-unit-1-remediation.md
src/trip_decider/schema_validation.py
src/trip_decider/fixture_validation.py
src/trip_decider/verification_entry.py
scripts/verify_wu1.ps1
tests/test_schema_validation.py
tests/test_fixture_validation.py
tests/wu1r_verify_entry_cases.py
fixtures/**
all other schemas/**
pyproject.toml
requirements.lock
.venv/**
the handbook repository
user/system configuration
all other repositories
```

## 6. Candidate contract design

### 6.1 Q1 decision: nested provider metadata

Two designs were considered.

| Criterion | A: top-level `provider_id/category` | B: nested `provider` |
|---|---|---|
| Schema complexity | initially smaller, grows one top-level field per provider fact | one closed object and one discriminator boundary |
| Downstream stability | candidate namespace accumulates provider-native fields | downstream can ignore the whole provider object |
| Provider evolution | encourages `amap_*`, `baidu_*` fields | provider-neutral keys with raw codes |
| Planner impact | provider identity becomes easy to couple to planner | planner consumes stable candidate/location fields only |
| R10 | provenance and entity fields can drift together | identity, native metadata and policy remain explicit |

Decision: **B, a closed nested `provider` object**.

Proposed shape:

```yaml
provider:
  name: amap
  record_id: provider-native-stable-id
  record_type: scenic_poi
  categories:
    - code: provider-native-category-code
      label: provider-native-label-or-null
  external_status:
    kind: reported
    code: provider-native-status-code
    label: provider-native-label-or-null
  data_policy:
    source_class: commercial
    capture_mode: temporary_capture
    storage_policy: temporary_only
    replay_allowed: false
    fixture_allowed: false
    policy_checked_at: 2026-07-28T00:00:00+08:00
    terms_url: https://provider.example/terms
    authorization_ref: null
    license: null
```

Rules:

- `name` is a provider-neutral lowercase token, not an enum of selected
  vendors. The contract must not require a code change for a new provider.
- `record_id`, `record_type`, and `categories` are provider-native strings.
  They are not translated into planner semantics in WU1C.
- `categories` is required and non-empty for provider-backed candidates.
- `external_status` is required and is a closed union:
  - `reported`: requires `code`; label may be null;
  - `not_reported`: forbids code and label.
- Provider data cannot be placed in candidate-level `source_refs`,
  `generation_reason`, or provider-specific top-level fields.
- `provider` is optional only to preserve legacy/user/synthetic candidates.
  Any WU2 provider-backed candidate must include it.
- No provider field changes evidence display status or candidate ranking.

## 7. Location and CRS design

### 7.1 Q2 decision: CRS belongs to the coordinate value

Options:

- A: `location.crs`
- B: put CRS only in provenance

Decision: **A**. CRS changes the meaning of the numeric pair, so it must be
co-located with latitude/longitude. Provenance answers where the value came
from; it cannot substitute for the coordinate reference system.

Provider-backed coordinate shape:

```yaml
location:
  kind: coordinates
  latitude: 29.000000
  longitude: 117.000000
  crs: GCJ-02
  source_refs:
    - kind: provider_item
      value: provider-record-locator
```

CRS enum:

```text
WGS84
GCJ-02
BD-09
```

No alias, lowercase variant, EPSG guess, or `unknown` CRS is accepted.

### 7.2 Unknown handling

If coordinates exist but their CRS is unknown, normalization must not emit
them as usable coordinates. The candidate uses:

```yaml
location:
  kind: unresolved
  query: original location query
  reason: crs_unknown
  source_refs:
    - kind: provider_item
      value: provider-record-locator
```

Rules:

- an unresolved location forbids latitude, longitude and CRS;
- a provider-backed coordinates location requires non-empty source refs;
- a provider-backed unresolved location requires a reason and source refs;
- no default CRS exists;
- no conversion occurs in WU1C;
- later conversion must be an explicit adapter operation with input CRS,
  output CRS, rule/version, and provenance.

Candidate structure has no evidence display-state authority. `unresolved`
means the candidate has no usable coordinate. If a later evidence fact exposes
that condition, its user-facing state must be `unknown`; WU1C does not
implement that WU3 mapping.

### 7.3 Backward compatibility

The current six fixtures contain legacy coordinates without CRS. WU1C will
not edit them.

Schema compatibility rule:

- candidate without `provider`: current coordinate and unresolved forms remain
  structurally valid;
- candidate with `provider`: the stricter coordinate/unresolved rules above
  apply conditionally.

This is a deliberate legacy boundary, not a default-CRS rule. WU2 must reject
provider-derived output that omits the provider object.

## 8. Source Policy contract

### 8.1 Orthogonal model

`commercial_live`, `temporary_capture`, `open_data_anchor`,
`provider_authorized_anchor`, `synthetic_fixture`, and
`user_supplied_anchor` mix origin, lifecycle, and authorization if represented
by one enum. WU1C follows the same orthogonalization principle as Evidence:

```yaml
data_policy:
  source_class:
    # commercial / open_data / synthetic / user_supplied
  capture_mode:
    # live / temporary_capture / persistent_anchor
  storage_policy:
    # prohibited / temporary_only / persistent_allowed
    # persistent_authorized / user_controlled
  replay_allowed:
  fixture_allowed:
  policy_checked_at:
  terms_url:
  authorization_ref:
  license:
    identifier:
    url:
    attribution:
```

`license` and `authorization_ref` may be null only where the selected variant
allows null. No missing field is interpreted as permission.

### 8.2 Deterministic policy combinations

| Named class | Orthogonal fields | Raw persistence | Replay | Fixture |
|---|---|---|---:|---:|
| `commercial_live` | commercial + live | prohibited unless terms say otherwise | false | false |
| `temporary_capture` | commercial + temporary_capture | memory/system-temp only, bounded lifetime | false | false |
| `open_data_anchor` | open_data + persistent_anchor + verified license | allowed under license | true | true |
| `provider_authorized_anchor` | commercial + persistent_anchor + explicit authorization | authorized scope only | true | true |
| `synthetic_fixture` | synthetic + persistent_anchor | allowed | true | true |
| `user_supplied_anchor` | user_supplied + persistent_anchor + user control/consent | user-controlled scope | true only if consented | true only if consented |

Hard failures:

- `commercial + persistent_allowed` without authorization;
- temporary capture with replay or fixture enabled;
- open data without license URL and attribution;
- provider-authorized anchor without a non-secret authorization reference;
- user anchor without a non-secret consent/control reference;
- fixture source whose policy says `fixture_allowed=false` or
  `replay_allowed=false`;
- unknown policy enum or extra policy field.

`authorization_ref` and user consent refs are opaque identifiers only. They
must not contain API keys, contract text, account identifiers, or personal
data.

## 9. Data-source policy evidence and safe WU2 classes

Research was limited to official provider documentation, official terms, and
official/open-project license pages. Retrieval date: `2026-07-28`. No API
request, key, account console, or real data was used.

| Source | Capability relevant later | CRS observation | Persistence/replay observation | WU1C policy result |
|---|---|---|---|---|
| 高德 Web Service | official POI 2.0 and route 2.0 pages expose search and route operations | provider coordinates must be declared by the future adapter; WU1C does not infer from provider name | service agreement §3.5 says results may be displayed but may not be directly stored or cached without separate cooperation | `commercial_live` or `temporary_capture`; persistent fixture only with explicit provider authorization |
| 百度 Web API | official place search and direction APIs; place API exposes coordinate-type controls | official docs distinguish WGS84, GCJ-02 and BD-09 and warn wrong type causes offset | platform terms allow documented service use but do not provide a default raw-response replay grant; older API terms explicitly prohibit direct/offline storage | `commercial_live` or `temporary_capture`; authorization required for persistence |
| 腾讯位置服务 | official agreement covers place queries and route planning | future adapter must record the operation's actual coordinate contract | agreement reserves ungranted rights, interaction/operational data rights, and restricts copying/derivative use; no default replay permission was verified | `commercial_live` or `temporary_capture`; authorization required for persistence |
| OpenStreetMap | open map data includes POIs and roads | future adapter must explicitly record the selected OSM coordinate contract | ODbL permits copy/adapt/distribute with attribution and share-alike obligations | eligible `open_data_anchor` when license/attribution fields are complete |
| Nominatim/OSRM | Nominatim search and OSRM route protocol can support targeted experiments | protocol uses explicit coordinate order; no implicit conversion | public services have usage policies/no SLA; OSM data license remains distinct from service availability | potentially open-data replay; public endpoint suitability and China coverage remain WU2 empirical checks |

Primary sources:

- 高德 POI 2.0:
  `https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch`
- 高德 route 2.0:
  `https://lbs.amap.com/api/webservice/guide/api/newroute`
- 高德 terms:
  `https://lbs.amap.com/pages/terms/`
- 百度 place 3.0:
  `https://lbsyun.baidu.com/docs/webapi?title=placev3%2Fguide%2Fwebservice-placeapiV3%2FinterfaceDocumentV3`
- 百度 platform terms:
  `https://lbsyun.baidu.com/docs/pcsa?title=law%2Fopen%2Flaw`
- 腾讯 Web Service overview:
  `https://lbs.qq.com/service/webService/webServiceGuide/webServiceOverview`
- 腾讯 terms:
  `https://lbs.qq.com/terms.html`
- OSM copyright/license:
  `https://www.openstreetmap.org/copyright`
- Nominatim usage policy:
  `https://operations.osmfoundation.org/policies/nominatim/`
- OSRM HTTP API:
  `https://project-osrm.org/docs/v26.6.1/http`

WU1C does **not** select a production provider. It decides only:

> WU2 may persist/replay open data with complete license obligations,
> explicitly provider-authorized data within the authorization scope,
> synthetic deterministic data, and user-supplied data within explicit user
> control. Commercial live data has no default persistence or fixture right.

China coverage, route quality, quota, account eligibility, and live API
behavior remain WU2 preflight/empirical questions.

## 10. Raw, replay, and fixture metadata

### 10.1 Temporary capture

Temporary capture is an execution buffer, not a fixture:

```text
provider response
  -> bounded in-memory or system-temp capture
  -> normalization
  -> permitted normalized output
  -> deterministic deletion in finally
```

Rules:

- no repository path;
- no Git;
- no default long-term cache;
- no replay claim;
- no secret in request fingerprints, logs, filenames, or errors;
- provider terms may prohibit even normalized persistence; WU2 must preflight
  that separately;
- deletion failure is a hard failure, not a warning.

WU1C does not implement this lifecycle.

### 10.2 Persistent replay

Persistent replay is allowed only when:

```text
fixture_allowed = true
replay_allowed = true
storage_policy is persistent_allowed, persistent_authorized, or user_controlled
required license/authorization/consent metadata is present
```

Commercial live/temporary capture can never be relabeled as synthetic or
user-supplied after collection.

### 10.3 Fixture metadata design

`fixture-case.schema.json` will retain the current `frozen_contract` variant
unchanged and add closed source variants:

```yaml
source:
  kind: open_data_anchor
  description: ...
  origin_url: ...
  data_policy:
    source_class: open_data
    capture_mode: persistent_anchor
    storage_policy: persistent_allowed
    replay_allowed: true
    fixture_allowed: true
    policy_checked_at: ...
    terms_url: ...
    authorization_ref: null
    license:
      identifier: ODbL-1.0
      url: https://opendatacommons.org/licenses/odbl/1-0/
      attribution: © OpenStreetMap contributors
```

Other persistent variants:

- `provider_authorized_anchor`: requires provider name, terms URL,
  authorization ref, `persistent_authorized`, replay and fixture true;
- `synthetic_fixture`: requires a specification ref and no external provider
  claim;
- `user_supplied_anchor`: requires a non-secret user-control/consent ref,
  `user_controlled`, replay and fixture true.

Explicitly excluded fixture kinds:

```text
commercial_live
temporary_capture
```

The three required conceptual cases are therefore:

1. open data: valid persistent/replay fixture with license and attribution;
2. commercial API without authorization: temporary only and rejected from
   fixture metadata;
3. user supplied: persistent/replay only under explicit user control.

WU1C creates no actual fixture and changes none of the current six.

## 11. Fixture-first test strategy

### 11.1 Test module and discovery boundary

New module:

```text
tests/wu1c_contract_compatibility_cases.py
```

It is intentionally outside `test*.py` default discovery so the historical
WU1 count remains 82. It contains exactly 33 deterministic synthetic contract
methods. Inputs and expected errors are hand-authored from §§6—10.

The module header must state:

- source: frozen WU1C specification, synthetic deterministic only;
- covers: structure, closed unions, compatibility and hard failures;
- does not cover: real provider payloads, terms compliance as legal advice,
  API behavior, coordinate conversion, GIS accuracy, or WU2 ingestion.

### 11.2 Thirty-three named cases

Candidate/provider:

| ID | Independent behavior |
|---|---|
| CC-01 | valid closed nested provider object |
| CC-02 | missing provider name rejected |
| CC-03 | missing record ID rejected |
| CC-04 | missing record type rejected |
| CC-05 | empty categories rejected |
| CC-06 | reported external status requires code |
| CC-07 | not-reported status forbids code/label |
| CC-08 | provider-native fields at candidate top level rejected |
| CC-09 | legacy candidate without provider remains valid |
| CC-10 | unknown provider metadata field rejected |

Location/CRS:

| ID | Independent behavior |
|---|---|
| LC-01 | provider coordinate with WGS84 passes |
| LC-02 | provider coordinate with GCJ-02 passes |
| LC-03 | provider coordinate with BD-09 passes |
| LC-04 | provider coordinate missing CRS rejected |
| LC-05 | unknown/unrecognized CRS rejected |
| LC-06 | provider coordinate missing location source refs rejected |
| LC-07 | empty location source refs rejected |
| LC-08 | unresolved `crs_unknown` form passes without coordinates |
| LC-09 | unresolved form carrying numeric coordinates/CRS rejected |

Data policy:

| ID | Independent behavior |
|---|---|
| SP-01 | commercial live/temporary policy with replay false passes |
| SP-02 | commercial persistence without authorization rejected |
| SP-03 | licensed open-data persistent/replay policy passes |
| SP-04 | open data missing license/attribution rejected |
| SP-05 | provider-authorized persistent policy passes |
| SP-06 | authorized persistence missing authorization ref rejected |
| SP-07 | synthetic persistent/replay policy passes |
| SP-08 | user-controlled persistent/replay policy requires consent ref |

Fixture source:

| ID | Independent behavior |
|---|---|
| FC-01 | open-data anchor with complete policy passes |
| FC-02 | provider-authorized anchor with complete scope passes |
| FC-03 | commercial-live fixture kind rejected |
| FC-04 | temporary-capture fixture kind rejected |
| FC-05 | synthetic fixture with specification ref passes |
| FC-06 | user-supplied anchor with consent/control ref passes |

### 11.3 Red → green

One exact command is used for C3 red and C4 green:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases -v
```

Pre-registered C3 red:

```text
tests discovered: 115
existing WU1 tests: 82/82 pass
WU1C methods: 33
expected current-compatible passes: 4
expected WU1C assertion failures: 29
unexpected errors: 0
```

The four current-compatible passes are the legacy candidate, rejection of
provider-native top-level fields, and rejection of the two forbidden fixture
kinds. The 29 red cases must fail on exact missing contract behavior, never
import, path, dependency, JSON syntax, malformed test construction, or absent
files. If the measured distribution differs, execution stops before C4.

Pre-registered C4 green:

```text
tests discovered: 115
passed: 115
failures: 0
errors: 0
```

C4 may modify only the three approved Schema files. No test correction is
allowed in C4.

### 11.4 Full WU1C entry

`scripts/verify_wu1c.ps1` will:

1. require the project `.venv` Python with no fallback;
2. run the exact 115-test suite;
3. independently confirm default discovery remains 82;
4. validate the registry remains 11 Schemas;
5. validate all six current fixtures remain 6/38/6;
6. confirm existing validators, WU1R entry/script, tests and fixtures retain
   their frozen hashes;
7. enforce the nine-path WU1C scope;
8. scan for secret patterns, silent fallback, guessed CRS/provider, map API
   endpoints/keys, adapters and real data;
9. check the 18 completion criteria inputs;
10. exit nonzero on any failed check.

It will not call a map API or the historical `verify_wu1.ps1`. It verifies the
same structural behaviors directly while keeping the historical WU1R entry
byte-identical.

## 12. Linear commit sequence

### WU1C-C0

```text
docs: record approved WU1 contract remediation plan
```

- Paths: `plans/work-unit-1-contract-remediation.md`
- Responsibility: commit only the exact approved Plan bytes.
- Precondition: Plan SHA256 matches the approval instruction; baseline HEAD,
  branch, clean-worktree, remote/stash, frozen hashes and handbook gate pass.
- Verify: hash, `git diff --check`, one-file diff, clean post-commit status.
- Done: approved Plan is independently addressable; no other path changed.

### WU1C-C1

```text
docs: define real-world source and replay policy
```

- Paths: `docs/real-world-source-policy.md`
- Responsibility: source classes, temporary capture, persistence/replay
  matrix, official source observations and non-legal-advice boundary.
- Precondition: C0 complete; no API call or real data.
- Verify: primary-source links present; policy combinations and forbidden
  relabeling stated; no provider selected.
- Done: source/replay policy is reviewable without Schema implementation.

### WU1C-C2

```text
docs: define candidate and location compatibility extension
```

- Paths: `docs/real-world-contract-extension.md`
- Responsibility: nested provider object, CRS/location provenance, legacy
  compatibility, fixture metadata and exact Schema implications.
- Precondition: C1 source vocabulary frozen.
- Verify: field-level tables match §§6—10; no planner/evidence behavior claim.
- Done: tests can be authored solely from the document and this Plan.

### WU1C-C3

```text
test: add failing real-world contract compatibility cases
```

- Paths: `tests/wu1c_contract_compatibility_cases.py`
- Responsibility: exactly 33 cases and valid red.
- Precondition: C2 complete; existing 82 tests green.
- Verify: exact §11.3 command; 115/86/29/0 distribution; every red ID and
  reason recorded; no test expected generated by validator output.
- Done: valid red committed without Schema or implementation change.

### WU1C-C4

```text
feat: extend candidate location and fixture source contracts
```

- Paths:
  - `schemas/common.schema.json`
  - `schemas/candidates.schema.json`
  - `schemas/fixture-case.schema.json`
- Responsibility: implement only the approved closed structural extensions.
- Precondition: committed valid C3 red.
- Verify: identical §11.3 command becomes 115/115; Schema count remains 11;
  Draft 2020-12 checks pass; old fixtures remain 6/38/6.
- Done: no validator/test/fixture change and no silent default.

### WU1C-C5

```text
chore: add WU1C verification entry
```

- Paths: `scripts/verify_wu1c.ps1`
- Responsibility: one bounded verification entry for WU1C.
- Precondition: C4 green.
- Verify:

  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu1c.ps1
  ```

- Done: one invocation proves 115 explicit tests, 82 default tests, 11
  Schemas, 6/38/6 legacy fixtures, protected hashes, scope and scans.

### WU1C-C6

```text
docs: prepare WU1 contract remediation review
```

- Paths: `docs/reviews/work-unit-1-contract-remediation-review.md`
- Responsibility: Review evidence only.
- Precondition: committed C5 entry reruns green.
- Verify: identical C5 command; Git log/diff/stat; hashes; 18 criteria.
- Done: Review ends in exactly one of
  `READY_FOR_HUGIN_REVIEW`, `BLOCKED`, or `INCOMPLETE`.

No commit mixes tests and Schema implementation. No commit is amended,
squashed, rebased, or pushed.

## 13. Eighteen completion criteria

Review must report every item as `✓`, `⚠`, or `✗`; none may be omitted.

1. WU1C started from the approved clean `4939435` baseline on `main`, with no
   remote or stash.
2. Handbook was fetched/reconciled, all eight mandatory files were reread
   from `origin/main`, and handbook bytes/worktree were unchanged.
3. The approved WU1C Plan was committed alone and remained byte-identical.
4. Final WU1C history is exactly C0—C6, linear, with commit messages matching
   their diffs.
5. Final changed paths equal the exact nine-path whitelist.
6. `PLAN.md`, WU0/WU1/WU1R Plans/Reviews/history and all protected paths
   remain unchanged.
7. No dependency, twelfth Schema, artifact type, validator logic, existing
   test, existing fixture, adapter, API call or real data was added.
8. Candidate provider identity, record type, non-empty categories, explicit
   external-status absence/reporting and data policy are structurally
   expressible.
9. Provider-backed coordinates require exactly one supported CRS and non-empty
   coordinate source refs; unknown CRS cannot become coordinates.
10. Legacy candidates remain valid without an inferred/default CRS, while
    provider-backed candidates cannot use that compatibility path.
11. Source class, capture mode, storage policy, replay permission, fixture
    permission, authorization and license are orthogonal and closed.
12. Open, provider-authorized, synthetic and user-controlled fixture metadata
    are expressible; commercial live and temporary capture are rejected.
13. C3 records a valid 115-test red with 82 existing tests green, 4
    current-compatible WU1C passes, 29 expected assertion failures and zero
    unexpected errors.
14. C4 uses the identical command for 115/115 green without modifying tests,
    validators or fixtures.
15. The final entry proves default discovery 82, Schema count 11, and the
    existing fixture surface 6/38/6.
16. R10 scans find no guessed CRS/provider, silent fallback, secret, retained
    commercial raw response, provider-specific planner branch, or claim beyond
    structural compatibility.
17. Source-policy documentation uses primary sources, records access results
    and limitations, does not give legal advice, and selects no production
    provider.
18. Final Review provides Git/hash/test/scope evidence, worktree is clean, and
    no remote, push, WU2 file or WU2 execution exists.

Completion criterion count is exactly `18`.

## 14. Blocking conditions

WU1C Execute stops immediately if:

- approved Plan hash, start HEAD, branch, worktree, frozen hashes or handbook
  gate differs;
- any required change falls outside the nine paths;
- generic Schema validation cannot enforce the design without changing
  `schema_validation.py` or `fixture_validation.py`;
- a twelfth Schema, registry version dispatch, artifact redesign, dependency,
  adapter, API call, real response, or real fixture becomes necessary;
- any existing fixture or existing test must be edited;
- preserving legacy artifacts would require guessing/defaulting CRS or
  provider metadata;
- the C3 measured 115/86/29/0 red distribution differs;
- C4 changes a test or fails to reach 115/115 with the identical command;
- Schema count differs from 11, default discovery differs from 82, or the
  existing fixture surface differs from 6/38/6;
- commercial data would need to be saved without explicit permission;
- a secret, account identifier, commercial response value, personal data, or
  provider authorization document would enter Git;
- completing WU1C would require changing WU1/WU1R history or claiming WU2
  capability.

On a blocker, no workaround, fallback, field overloading, test weakening, or
scope expansion is permitted. Review status must be `BLOCKED` or
`INCOMPLETE`, and WU2 remains stopped.
