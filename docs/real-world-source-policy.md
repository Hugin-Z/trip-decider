# Real-world Source, Storage, and Replay Policy

Status: WU1C contract policy

Checked on: 2026-07-28

This document defines how `trip-decider` may describe external-data origin,
capture lifetime, persistence, replay, and fixture eligibility. It is an
engineering policy, not legal advice and not a provider selection.

No map API, account console, credential, or real provider response was used
to prepare this policy.

## 1. Why source is not one enum

Labels such as `commercial_live`, `temporary_capture`, and
`open_data_anchor` combine different questions:

- who controls or licenses the data;
- how it was captured;
- whether it may persist;
- whether it may be replayed;
- whether it may be committed as a fixture;
- which authorization or license supports those permissions.

Those questions are independent. A single label would allow one property to
silently imply another. WU1C therefore uses a closed, orthogonal
`data_policy` object.

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

Missing values never mean permission. Unknown or unsupported values fail
validation instead of falling back to a permissive class.

## 2. Field meanings

### `source_class`

| Value | Meaning |
|---|---|
| `commercial` | Data controlled by a commercial provider under provider terms or a separate agreement |
| `open_data` | Data distributed under an identified open-data license |
| `synthetic` | Deterministic data authored from a written specification, not represented as an observation |
| `user_supplied` | Data supplied and controlled by the user within an explicit consent or control scope |

### `capture_mode`

| Value | Meaning |
|---|---|
| `live` | Consumed during a live operation without a replay artifact |
| `temporary_capture` | Held only in a bounded execution buffer for normalization |
| `persistent_anchor` | Retained as an auditable, replayable anchor under an explicit permission basis |

### `storage_policy`

| Value | Meaning |
|---|---|
| `prohibited` | No persistence is permitted by this contract |
| `temporary_only` | Only bounded memory or system-temporary storage is permitted |
| `persistent_allowed` | Persistence is allowed by a recorded license |
| `persistent_authorized` | Persistence is allowed by an explicit provider authorization |
| `user_controlled` | Persistence remains under explicit user control or consent |

### Permission and provenance fields

- `replay_allowed` is an explicit boolean. It is never derived from
  persistence alone.
- `fixture_allowed` is an explicit boolean. It is never derived from replay
  alone.
- `policy_checked_at` records when the policy basis was checked.
- `terms_url` identifies the applicable public terms or policy page.
- `authorization_ref` is a non-secret opaque reference to an authorization or
  user-control record. It must not contain an API key, account identifier,
  contract text, personal data, or credential.
- `license` records the license identifier, URL, and required attribution.
  It is not replaced by a provider name or a generic `open` label.

## 3. Deterministic policy classes

The names in this section are documentation labels. Validation is performed
against the orthogonal fields.

| Named class | Required combination | Raw persistence | Replay | Fixture |
|---|---|---|---:|---:|
| `commercial_live` | `commercial` + `live` + `prohibited` | no | false | false |
| `temporary_capture` | `commercial` + `temporary_capture` + `temporary_only` | bounded temporary buffer only | false | false |
| `open_data_anchor` | `open_data` + `persistent_anchor` + `persistent_allowed` + complete license | under license | true | true |
| `provider_authorized_anchor` | `commercial` + `persistent_anchor` + `persistent_authorized` + authorization reference | within authorization | true | true |
| `synthetic_fixture` | `synthetic` + `persistent_anchor` + `persistent_allowed` | yes | true | true |
| `user_supplied_anchor` | `user_supplied` + `persistent_anchor` + `user_controlled` + control reference | within user control | true | true |

Hard-invalid combinations include:

- commercial persistence without explicit authorization;
- temporary capture with replay or fixture permission;
- open data without a license URL and attribution;
- a provider-authorized anchor without a non-secret authorization reference;
- a user-supplied anchor without a non-secret user-control reference;
- fixture metadata with either replay or fixture permission set to false;
- an unknown enum value or an extra policy field.

Commercial live or temporary data may not be relabeled as synthetic,
user-supplied, or open data after collection.

## 4. Temporary capture

Temporary capture is an execution buffer, not a fixture:

```text
provider response
  -> bounded memory or system-temporary file
  -> normalization
  -> permitted normalized artifact
  -> deterministic deletion in finally
```

Required properties for a future adapter:

- no repository path and no Git tracking;
- no default long-term cache;
- no replay claim;
- no credential in request fingerprints, logs, filenames, or errors;
- provider-specific preflight before retaining even normalized fields;
- deletion failure produces a hard failure, not a warning.

WU1C defines the policy only. It does not implement temporary capture.

## 5. Persistent replay

A source may become a persistent replay fixture only if all of the following
are explicit:

```text
fixture_allowed = true
replay_allowed = true
storage_policy in:
  persistent_allowed
  persistent_authorized
  user_controlled
required license, authorization, or user-control metadata is present
```

Persistence does not imply replay. Replay does not imply publication.
Publication rights are outside this contract and must not be inferred.

## 6. Fixture-source variants

WU1C extends fixture metadata with these persistent variants:

### `open_data_anchor`

Requires:

- origin URL;
- `open_data` source class;
- persistent-anchor capture;
- persistent-allowed storage;
- replay and fixture permission true;
- license identifier, URL, and attribution.

### `provider_authorized_anchor`

Requires:

- provider name;
- applicable terms URL;
- non-secret authorization reference;
- `commercial` source class;
- persistent-authorized storage;
- replay and fixture permission true.

### `synthetic_fixture`

Requires:

- specification reference;
- `synthetic` source class;
- persistent-anchor capture;
- persistent-allowed storage;
- replay and fixture permission true;
- no external-provider claim.

Synthetic data verifies deterministic structural behavior. It is not a real
anchor and is not evidence that an external fact is true.

### `user_supplied_anchor`

Requires:

- non-secret user-control or consent reference;
- `user_supplied` source class;
- user-controlled storage;
- replay and fixture permission true.

The metadata does not establish that consent is legally sufficient. It makes
the asserted basis auditable and prevents an absent basis from becoming a
silent permission.

### Explicitly forbidden fixture kinds

```text
commercial_live
temporary_capture
```

The existing `frozen_contract` fixture kind remains unchanged for the six WU1
contract fixtures. It describes frozen internal contracts, not external
source permission.

## 7. Official-source observations

This section records the engineering basis available on 2026-07-28. Terms
may change. A future live integration must recheck the applicable terms and
account authorization.

### 7.1 高德地图开放平台

Relevant official pages:

- POI 2.0:
  <https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch>
- Route 2.0:
  <https://lbs.amap.com/api/webservice/guide/api/newroute>
- Service terms:
  <https://lbs.amap.com/pages/terms/>

Access result:

- POI and route documentation were accessible during research.
- The service-terms page was accessible during the initial check and exposed
  a current terms document dated 2025-12-03; section 3.5 was read as
  restricting direct storage or caching without separate cooperation.
- A later retrieval attempt timed out. The access instability is recorded
  rather than treated as permission.

Engineering consequence:

- POI search and routing are candidate WU2 capabilities.
- Provider coordinates must carry the operation's explicit CRS; the provider
  name is not a CRS rule.
- No raw response is persistable or replayable by default.
- A persistent fixture requires explicit provider authorization.

### 7.2 百度地图开放平台

Relevant official pages:

- Place API:
  <https://lbsyun.baidu.com/docs/webapi?title=placev3%2Fguide%2Fwebservice-placeapiV3%2FinterfaceDocumentV3>
- Platform terms:
  <https://lbsyun.baidu.com/docs/pcsa?title=law%2Fopen%2Flaw>

Access result:

- Both pages were accessible.
- The documentation distinguishes coordinate-system choices including
  WGS84, GCJ-02, and BD-09 and warns that the wrong coordinate type produces
  an offset.
- The platform terms allow documented service use but do not grant a default
  raw-response replay right. They restrict unauthorized access, extraction,
  storage, caching, download, or independent use of service content.

Engineering consequence:

- A future operation must record its actual coordinate contract.
- Commercial live or temporary capture is the conservative default.
- Persistence requires a separately verified authorization.

### 7.3 腾讯位置服务

Relevant official pages:

- Web Service overview:
  <https://lbs.qq.com/service/webService/webServiceGuide/webServiceOverview>
- Terms:
  <https://lbs.qq.com/terms.html>

Access result:

- The terms page was accessible.
- The overview page was identified from the official documentation but one
  retrieval attempt timed out.
- The accessible terms reserve ungranted rights and do not establish a
  default right to persist provider responses as replay fixtures.

Engineering consequence:

- Place-query and route capability must be confirmed again during WU2
  preflight.
- The operation's CRS must be explicit.
- Commercial live or temporary capture is the conservative default;
  persistence requires explicit authorization.

### 7.4 OpenStreetMap

Relevant official page:

- Copyright and license:
  <https://www.openstreetmap.org/copyright>

Access result:

- The page was accessible.
- It identifies OpenStreetMap data as Open Database License data and states
  attribution and share-alike obligations for covered uses.

Engineering consequence:

- OSM-derived data may be eligible for `open_data_anchor`.
- License identifier, URL, attribution, and transformation/distribution
  obligations must remain recorded.
- Open licensing does not prove data completeness or routing suitability in
  China.

### 7.5 Nominatim and OSRM

Relevant official/project pages:

- Nominatim usage policy:
  <https://operations.osmfoundation.org/policies/nominatim/>
- OSRM HTTP API:
  <https://project-osrm.org/docs/v26.6.1/http>

Access result:

- Both pages were accessible.
- Nominatim's public service has an explicit usage policy and no general SLA.
- OSRM documents an HTTP routing protocol with explicit coordinate ordering.

Engineering consequence:

- Open protocol or open data does not make a shared public endpoint an
  unrestricted production dependency.
- Endpoint policy, rate limits, availability, coordinate order, OSM license,
  and China coverage are distinct checks.
- Targeted WU2 experiments may use an eligible open-data path only after
  those checks pass.

## 8. Safe WU2 source classes

WU1C does not choose a production provider. It permits WU2 to investigate:

1. open data with complete license and attribution metadata;
2. provider-authorized data within the exact authorization scope;
3. deterministic synthetic data for structural tests;
4. user-supplied data within explicit user control;
5. commercial live data only through a no-persistence or bounded-temporary
   path whose provider terms have been checked.

Unresolved WU2 questions include:

- China POI and road completeness;
- route quality and travel-mode semantics;
- quota, account eligibility, and service availability;
- live response shape and versioning;
- whether normalized commercial fields may persist;
- operational deletion guarantees for temporary capture.

None of these unresolved questions is answered by a Schema field.

## 9. R10 invariants

- No absent policy field becomes permission.
- No provider name becomes an inferred CRS.
- No temporary or commercial-live response becomes a replay fixture.
- No synthetic value is represented as an external observation.
- No LLM is a data source.
- No source-policy label establishes legal permission by itself.
- No documentation claim exceeds the actual structural contract.
