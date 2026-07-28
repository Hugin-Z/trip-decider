# Real-world Contract Compatibility Extension

Status: WU1C structural contract

Schema family: `0.1.0`

This document freezes the candidate, location, data-policy, and fixture-source
extensions implemented by WU1C. It extends three existing Schemas. It does not
add an artifact type, a twelfth Schema, validator behavior, provider adapter,
coordinate conversion, evidence mapping, or planning logic.

## 1. Compatibility boundary

WU1C modifies only:

```text
schemas/common.schema.json
schemas/candidates.schema.json
schemas/fixture-case.schema.json
```

The existing `$id` values and artifact `schema_version` remain `0.1.0`.
Draft 2020-12 remains the dialect. All new objects are closed with
`additionalProperties: false`.

Legacy behavior is preserved deliberately:

- a candidate without `provider` may retain the existing coordinate shape
  without CRS;
- a candidate without `provider` may retain the existing unresolved shape;
- the existing `frozen_contract` fixture-source shape remains valid;
- all six WU1 fixtures remain byte-identical;
- the generic validators and registry remain unchanged.

Compatibility is not permission for WU2 to omit real-world metadata.
Provider-derived candidates must include `provider`, which activates the
strict location rules.

## 2. Candidate design decision

### 2.1 Compared shapes

Top-level provider fields were rejected:

```yaml
candidate:
  provider_id: ...
  provider_category: ...
```

They would grow the candidate namespace for every provider-native property,
invite provider-specific planner branches, and allow provenance text fields
to substitute for entity attributes.

WU1C chooses one optional, closed `provider` object:

```yaml
candidate:
  candidate_id: candidate_...
  candidate_kind: poi
  label: Example
  provider:
    name: provider_name
    record_id: provider-native-record-id
    record_type: provider-native-record-type
    categories:
      - code: provider-native-category-code
        label: Provider category label
    external_status:
      kind: reported
      code: provider-native-status-code
      label: Provider status label
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

The candidate-level object stays provider-neutral. Provider fields may not be
stored in `source_refs`, `generation_reason`, description text, or invented
provider-specific top-level properties.

### 2.2 `provider` field contract

`provider` is optional only for legacy, user-authored, or synthetic
candidates. When present, it requires:

| Field | Type | Constraint |
|---|---|---|
| `name` | string | lowercase provider-neutral token matching `^[a-z][a-z0-9_-]*$` |
| `record_id` | string | non-empty provider-native identifier |
| `record_type` | string | non-empty provider-native type |
| `categories` | array | at least one closed category object |
| `external_status` | closed union | explicit reported/not-reported state |
| `data_policy` | object | common closed policy union |

No provider is enumerated or selected by the Schema.

### 2.3 Category contract

Each `categories` item is closed:

```yaml
code: provider-native-category-code
label: provider-native-label-or-null
```

Both fields are required. `code` is a non-empty string. `label` is either a
non-empty string or null. The code remains provider-native; WU1C does not map
it into planner semantics.

An empty category array is invalid.

### 2.4 External-status contract

Absence of an external status must be represented, not inferred.

Reported:

```yaml
external_status:
  kind: reported
  code: provider-native-status-code
  label: provider-native-label-or-null
```

All three fields are required. `code` is non-empty. `label` is non-empty or
null.

Not reported:

```yaml
external_status:
  kind: not_reported
```

`code` and `label` are forbidden in this branch. Unknown enum values and extra
fields fail validation.

External status is provider metadata. It does not establish opening status,
evidence support, feasibility, ranking, or display-state truth.

## 3. Location and CRS

### 3.1 CRS belongs to the coordinate value

WU1C chooses:

```yaml
location:
  kind: coordinates
  latitude: 29.0
  longitude: 117.0
  crs: GCJ-02
```

CRS changes the meaning of the numeric pair, so it belongs with latitude and
longitude. A locator records where a value came from; it cannot replace the
coordinate reference system.

The closed CRS enum is:

```text
WGS84
GCJ-02
BD-09
```

The contract accepts no `unknown`, lowercase alias, provider-derived default,
or guessed EPSG representation.

### 3.2 Provider-backed coordinates

A candidate containing `provider` and a coordinate location requires:

```yaml
location:
  kind: coordinates
  latitude: 29.0
  longitude: 117.0
  crs: GCJ-02
  source_refs:
    - kind: provider_item
      value: provider-record-locator
```

Rules:

- latitude remains within `[-90, 90]`;
- longitude remains within `[-180, 180]`;
- `crs` is exactly one supported enum value;
- `source_refs` is non-empty;
- every source ref uses the existing closed `locator` definition;
- no additional location field is allowed.

Candidate-level `source_refs` remains part of the legacy candidate contract.
It does not satisfy the provider-backed coordinate's local `source_refs`.
The local refs explain the coordinate value specifically.

### 3.3 Unknown CRS

Coordinates whose CRS is unknown cannot be emitted as usable coordinates.
The structural representation is:

```yaml
location:
  kind: unresolved
  query: original location query
  reason: crs_unknown
  source_refs:
    - kind: provider_item
      value: provider-record-locator
```

For a provider-backed unresolved location:

- `query`, `reason`, and non-empty `source_refs` are required;
- `reason` is exactly `crs_unknown` in WU1C;
- latitude, longitude, and CRS are forbidden;
- no default, conversion, or coordinate recovery occurs.

If a later evidence fact exposes this condition, the display state may not
exceed `unknown`. That WU3 mapping is not implemented by WU1C.

### 3.4 Legacy location branch

For a candidate without `provider`, these existing values remain valid:

```yaml
location:
  kind: coordinates
  latitude: 29.0
  longitude: 117.0
```

```yaml
location:
  kind: unresolved
  query: user text
```

The Schema does not assign those coordinates a CRS. It merely preserves the
accepted WU1 bytes. Any WU2 provider output that attempts this compatibility
path violates the adapter contract even though the legacy shape exists.

### 3.5 Future conversion boundary

Coordinate conversion, if added later, must be an explicit adapter operation
that records:

- input CRS;
- output CRS;
- conversion rule and version;
- source coordinate locator;
- output provenance.

Planner, constraints, and evidence code may not convert or guess coordinates
implicitly.

## 4. Common data-policy definitions

`common.schema.json` gains the following `$defs`:

```text
license
commercial_live_policy
temporary_capture_policy
open_data_anchor_policy
provider_authorized_anchor_policy
synthetic_fixture_policy
user_supplied_anchor_policy
data_policy
provider_category
provider_external_status
provider_metadata
```

The final names are part of the WU1C contract. No second error model or
validator registry entry is added.

### 4.1 `license`

Closed object requiring:

```yaml
identifier: ODbL-1.0
url: https://opendatacommons.org/licenses/odbl/1-0/
attribution: © OpenStreetMap contributors
```

Every field is a non-empty string; `url` uses URI format validation.

### 4.2 Common policy fields

Every policy branch requires all nine fields:

```text
source_class
capture_mode
storage_policy
replay_allowed
fixture_allowed
policy_checked_at
terms_url
authorization_ref
license
```

`policy_checked_at` uses the existing offset-aware date-time definition.
Every policy object is closed.

### 4.3 Commercial live policy

Exact values:

```yaml
source_class: commercial
capture_mode: live
storage_policy: prohibited
replay_allowed: false
fixture_allowed: false
policy_checked_at: 2026-07-28T00:00:00+08:00
terms_url: https://provider.example/terms
authorization_ref: null
license: null
```

### 4.4 Temporary-capture policy

Exact values:

```yaml
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

### 4.5 Open-data-anchor policy

Exact values and types:

```yaml
source_class: open_data
capture_mode: persistent_anchor
storage_policy: persistent_allowed
replay_allowed: true
fixture_allowed: true
policy_checked_at: 2026-07-28T00:00:00+08:00
terms_url: https://www.openstreetmap.org/copyright
authorization_ref: null
license:
  identifier: ODbL-1.0
  url: https://opendatacommons.org/licenses/odbl/1-0/
  attribution: © OpenStreetMap contributors
```

### 4.6 Provider-authorized-anchor policy

Exact values and types:

```yaml
source_class: commercial
capture_mode: persistent_anchor
storage_policy: persistent_authorized
replay_allowed: true
fixture_allowed: true
policy_checked_at: 2026-07-28T00:00:00+08:00
terms_url: https://provider.example/terms
authorization_ref: authorization_fixture_scope_001
license: null
```

`authorization_ref` must match `^authorization_[a-z0-9_-]+$`. It is an
opaque repository-safe reference, not authorization evidence itself.

### 4.7 Synthetic-fixture policy

Exact values and types:

```yaml
source_class: synthetic
capture_mode: persistent_anchor
storage_policy: persistent_allowed
replay_allowed: true
fixture_allowed: true
policy_checked_at: 2026-07-28T00:00:00+08:00
terms_url: null
authorization_ref: null
license: null
```

### 4.8 User-supplied-anchor policy

Exact values and types:

```yaml
source_class: user_supplied
capture_mode: persistent_anchor
storage_policy: user_controlled
replay_allowed: true
fixture_allowed: true
policy_checked_at: 2026-07-28T00:00:00+08:00
terms_url: null
authorization_ref: user_control_fixture_scope_001
license: null
```

`authorization_ref` must match `^user_control_[a-z0-9_-]+$`. It is an opaque
control reference and contains no personal data.

### 4.9 `data_policy`

`data_policy` is a `oneOf` over the six exact policy definitions. It has no
fallback branch. The combination itself determines the policy class.

## 5. Fixture-source contract

`fixture-case.schema.json` keeps `source` as a closed union.

### 5.1 Frozen internal contract

This existing branch is byte-shape compatible:

```yaml
source:
  kind: frozen_contract
  description: frozen internal contract case
```

It does not claim that an external source may be persisted.

### 5.2 Open-data anchor

Required closed shape:

```yaml
source:
  kind: open_data_anchor
  description: licensed open-data anchor
  origin_url: https://www.openstreetmap.org/
  data_policy:
    # exact open_data_anchor_policy
```

### 5.3 Provider-authorized anchor

Required closed shape:

```yaml
source:
  kind: provider_authorized_anchor
  description: explicitly authorized provider anchor
  provider_name: provider_name
  data_policy:
    # exact provider_authorized_anchor_policy
```

`provider_name` uses the same provider-neutral token pattern.

### 5.4 Synthetic fixture

Required closed shape:

```yaml
source:
  kind: synthetic_fixture
  description: deterministic structural case
  specification_ref: docs/real-world-contract-extension.md
  data_policy:
    # exact synthetic_fixture_policy
```

`specification_ref` is a non-empty repository-relative or documentation
reference. It does not identify a real source.

### 5.5 User-supplied anchor

Required closed shape:

```yaml
source:
  kind: user_supplied_anchor
  description: user-controlled anchor
  user_control_ref: user_control_fixture_scope_001
  data_policy:
    # exact user_supplied_anchor_policy
```

`user_control_ref` must equal the policy's `authorization_ref` by producer
discipline. JSON Schema validates the format and presence of both fields but
does not implement cross-value equality. No validator extension is authorized
in WU1C.

### 5.6 Forbidden fixture kinds

No branch exists for:

```text
commercial_live
temporary_capture
```

Using either as `source.kind` fails the closed union. A commercial policy
cannot be placed under another fixture kind because each branch references
one exact policy definition.

## 6. Cross-contract invariants

1. Provider identity is an entity property, not a locator or prose field.
2. CRS is part of a coordinate value, not inferred from provenance.
3. Provider-backed coordinates require local coordinate source refs.
4. Unknown CRS produces an unresolved location without numeric coordinates.
5. A legacy coordinate without CRS remains legacy and gains no implied CRS.
6. Source class does not imply storage, replay, or fixture permission.
7. Missing license or authorization does not imply permission.
8. Commercial live and temporary capture are not fixture sources.
9. Open, authorized-provider, synthetic, and user-controlled fixtures use
   distinct closed branches.
10. Schema acceptance proves structure only. It does not prove license
    validity, authorization validity, source truth, CRS correctness, evidence
    support, feasibility, route quality, or planning behavior.

## 7. Test implications

The WU1C compatibility suite contains exactly 33 deterministic cases:

- 10 candidate/provider cases;
- 9 location/CRS cases;
- 8 policy cases;
- 6 fixture-source cases.

The suite writes expected structures manually from this document. It does not
use validator output to generate expected values and contains no semantic or
retrieval anchor.

Four cases are expected to pass before the Schema extension:

1. the unchanged legacy candidate;
2. rejection of provider fields at candidate top level;
3. rejection of `commercial_live` as a fixture source;
4. rejection of `temporary_capture` as a fixture source.

The other 29 cases fail against the pre-WU1C Schemas because the required new
structure is not yet accepted or the new conditional restriction is not yet
enforced.

After the three approved Schema files are changed, the identical 115-test
command must pass all 82 existing tests and all 33 WU1C cases. Existing tests,
fixtures, validators, and registries remain unchanged.

## 8. Explicit non-capabilities

WU1C does not implement or claim:

- provider connectivity or response parsing;
- storage authorization discovery;
- temporary-file lifecycle;
- CRS conversion or coordinate correctness;
- semantic category mapping;
- external-status truth;
- evidence support or display-state mapping;
- POI recommendation, feasibility, routing, or planning;
- a real Jiangxi dataset or trip.
