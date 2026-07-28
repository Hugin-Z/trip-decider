# WU2 Recovery Source and Capture Gate

Status: APPROVED_EXECUTION_GATE_RECORDED

Checked on: 2026-07-28

Scope: WU2R multi-identity OSM anchor only

This document records the source, persistence, query, call budget, and stop
conditions for the newly approved WU2 Recovery work unit. It is an
engineering decision, not legal advice. It does not itself call a data
service, capture a response, create an anchor, select a POI, or authorize any
provider outside the exact WU2R Plan.

## 1. Preserved history and new authority

The historical states remain:

```text
WU2: BLOCKED
WU2 C5/C6: NOT AUTHORIZED
WU2A: INVESTIGATION_BLOCKED
WU2A-R: APPROVED
WU2A-Resume: APPROVED
WU2 Decision Gate: APPROVED
```

WU2R is a new PER work unit. Its approval does not amend or resume old WU2
C5/C6.

The consumed Decision Gate tokens are:

```text
Decision: MULTI_IDENTITY_CANDIDATE
Rejected: UNIQUE_IDENTITY_REQUIRED_AT_ADAPTER
WU2_C5_C6_RESUME: NOT_AUTHORIZED_NOW
OLD_WU2_C5_C6_UNCHANGED: PROHIBITED
```

## 2. Primary-source access record

The following pages were opened directly on 2026-07-28. No search result or
search summary is used as the authority.

| Primary page | Access result | Observed basis | WU2R consequence |
|---|---|---|---|
| <https://www.openstreetmap.org/copyright> | accessible; 70 rendered lines | OSM identifies its data as ODbL, permits copying/adaptation subject to attribution/share-alike, and requires credit plus a visible license basis | the small OSM response may be retained only with `© OpenStreetMap contributors`, the ODbL identifier, and license URL |
| <https://opendatacommons.org/licenses/odbl/1-0/> | accessible; 237 rendered lines | ODbL 1.0 grants database use, extraction, temporary/permanent reproduction, and distribution subject to its conditions and notices | persistence is recorded as `persistent_allowed`, not inferred merely from the endpoint |
| <https://osmfoundation.org/wiki/Licence/Attribution_Guidelines> | accessible; 217 rendered lines | OSM attribution is required for covered uses; the page also explicitly requires OSM credit for routing engines and incorporating applications | fixture metadata and README retain OSM credit even though WU2R performs no route acquisition |
| <https://wiki.openstreetmap.org/wiki/Overpass_API> | accessible; 935 rendered lines | Overpass is a third-party selected-extract service; the listed main endpoint is `https://overpass-api.de/api/interpreter`; the page says Overpass is suitable for selected regional data and reports an `osm_base` timestamp | exactly one small pre-registered POST is allowed; no SLA, completeness, freshness, or production-service claim is made |

The recorded access results support the narrow non-production fixture
classification. They do not prove every item in OSM has no additional
rights, that OSM is accurate/complete, or that the shared endpoint will
remain available.

## 3. Data policy

The frozen WU1C `open_data_anchor` policy is used exactly:

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

No missing policy value means permission. No commercial, temporary,
synthetic, or user-supplied policy is substituted.

## 4. Exact acquisition recipe

Allowed endpoint:

```text
https://overpass-api.de/api/interpreter
```

Method:

```text
POST
```

Exact UTF-8 query:

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

Frozen query SHA256:

```text
5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F
```

The request body is:

```text
data=<application/x-www-form-urlencoded encoding of the exact query>
```

Frozen request-body SHA256:

```text
6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045
```

Request profile:

```text
User-Agent: trip-decider-wu2r/0.1 non-production-research
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
HTTP timeout: bounded
Overpass query timeout: 25 seconds
```

The user-agent value is public identification, not a credential.

## 5. Exact call budget

```text
scheduled Overpass POST: 1
byte-identical retry after transport failure: at most 1
maximum physical Overpass attempts: 2

Geofabrik GET: 0
O1/O3 queries: 0
alternate Overpass instance: 0
OSRM: 0
Nominatim: 0
commercial maps: 0
other data source: 0
```

Only DNS, timeout, connection-reset, or equivalent transport failure may
consume the one retry. The retry must have the same endpoint, method,
request bytes, and request SHA256.

These conditions are terminal and non-retryable:

```text
HTTP response failure
provider/content error
invalid UTF-8 or JSON
empty elements
unexpected response shape
adapter rejection
coverage-gate failure
license/persistence-gate failure
```

No parameter, name set, relation ID, category set, endpoint, or query may be
changed after failure.

## 6. Capture and ledger sequence

The existing `scripts/acquisition_harness.py` remains byte-identical.

An execution-only helper may be created under the system temporary directory
and must be removed. It performs:

```text
frozen request bytes
  -> ledger-first started record
  -> injected HTTPS transport
  -> exact response metadata
  -> system-temporary raw capture
  -> source/policy/content/adapter/coverage gates
  -> eligible raw bytes copied to the approved fixture path
  -> finally cleanup and residue check
```

Every physical attempt records:

```text
attempt ID
purpose
endpoint
method
request SHA256
start/completion timestamps
terminal status
HTTP status
response bytes
response SHA256
content type
error class
retry decision
```

Any retry records the original/retry attempt IDs and byte-identical request
relationship.

Response bodies may exist before the persistence gate only in memory or a
random system-temporary file. No raw bytes enter logs, stdout, `runtime/`, or
Git before all gates pass.

## 7. Candidate-pool acceptance

The raw response is eligible only when all conditions hold:

1. HTTP status is successful and the body is readable UTF-8 JSON.
2. The JSON has a non-empty `elements` list.
3. No contributor account fields such as `user`, `uid`, or `changeset` are
   present in retained elements.
4. Every returned element passes the frozen `normalize_open_data_pois`
   adapter with explicit provider `osm`, operation
   `overpass-poi-snapshot`, CRS `WGS84`, retrieval time, response locator,
   request fingerprint, and the exact open-data policy.
5. Every unique `(type,id)` is retained; none is dropped by label, category,
   array order, distance, popularity, or manual judgment.
6. The exact frozen seed set has at least one `matched`, one `ambiguous`, and
   one `unmatched` state under exact candidate-label equality.
7. `unmatched` creates no placeholder candidate and is not described as
   absence from OSM or reality.
8. Independently authored expected request/candidate bytes, seed accounting,
   and record-local facts are complete before pipeline implementation.

“All candidates” means all elements in this exact response accepted by the
frozen adapter. It is not an OSM-completeness claim.

## 8. Persistent fixture boundary

If every gate passes, the only raw repository path is:

```text
fixtures/jiangxi_multi_identity_smoke/osm-pois.json
```

The adjacent fixture README and metadata must carry:

```text
© OpenStreetMap contributors
ODbL-1.0
https://opendatacommons.org/licenses/odbl/1-0/
https://www.openstreetmap.org/copyright
```

The response is committed byte-for-byte. Numeric coordinates are allowed
inside the licensed raw anchor and independently authored Candidate
document, but are not copied into the Review as a coordinate list.

No route response, commercial response, credential, contributor-account
metadata, or second source is persisted.

## 9. Replay boundary

The committed replay is offline:

```text
network_required: false
```

It verifies:

- raw response path and SHA256;
- query and form-request SHA256;
- response byte count and SHA256;
- provider identities and actual count;
- all candidate fields and canonical payload hash;
- exact seed accounting and resolving candidate refs;
- record-local source facts per candidate;
- CLOSED candidate-root fixture validation;
- no unexpected fixture file;
- zero socket/network attempts.

Reissuing the query later is a new acquisition requiring separate authority.
OSM mutability means response hash stability is not promised.

## 10. Hard exclusions

The acquisition may not:

- use first, nearest, popularity, category preference, fuzzy matching,
  language fallback, manual coordinates, guessed IDs, or LLM judgment;
- add or remove a seed;
- select one 婺源县 or 篁岭 identity;
- fabricate or manually add 庆源;
- call OSRM, Nominatim, a commercial map, another Overpass instance, a
  crawler, or another data source;
- modify an adapter, Schema, validator, source policy, old fixture, old WU2
  file, or Decision Gate;
- create an ambiguity artifact or route-by-label lookup;
- continue to WU3 or WU5.

If any gate fails, no anchor is committed. WU2R stops and records the
observed result without changing query, provider, product contract, or old
history.

