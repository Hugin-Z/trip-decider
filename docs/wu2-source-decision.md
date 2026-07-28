# WU2 Source and Capture Gate

Status: approved WU2 execution record

Checked at: 2026-07-28

Scope: `jiangxi_smoke` non-production real anchor only

This document records the source, persistence, replay and capture gate used
by Work Unit 2. It is an engineering decision, not legal advice and not a
production-provider selection.

## 1. Decision

WU2 permits only these real-data paths:

```text
POI:
OpenStreetMap data
  -> one bounded Overpass JSON snapshot
  -> committed ODbL open-data anchor
  -> offline normalization

Route:
OSM-derived OSRM demo response
  -> exactly two bounded non-commercial requests
  -> committed ODbL-attributed open-data anchor
  -> offline normalization
```

The committed anchor is classified as:

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

The classification rests on OSM's express permission to copy, distribute,
transmit and adapt OSM data subject to attribution and share-alike. The
repository retains the ODbL identifier, URL and attribution adjacent to the
fixture. It does not infer permission from an endpoint name.

## 2. Primary-source checks

| Source | Access result | Relevant fact | WU2 consequence |
|---|---|---|---|
| <https://www.openstreetmap.org/copyright> | accessible; 70 rendered lines | OSM data is ODbL; copying/adaptation is allowed with attribution and share-alike | OSM response bytes may be retained as an attributed open-data anchor |
| <https://osmfoundation.org/wiki/Licence/Attribution_Guidelines> | accessible; 217 rendered lines | database notices belong in metadata/README; OSM routing use requires attribution | fixture README and metadata carry OSM/ODbL notice |
| <https://wiki.openstreetmap.org/wiki/Elements> | accessible; 270 rendered lines | OSM node latitude/longitude is WGS84 | replay metadata records `WGS84`; adapter still rejects a missing CRS |
| <https://wiki.openstreetmap.org/wiki/Overpass_API> | accessible; 935 rendered lines | Overpass is a read-only selected-extract path; the global instance is third-party | one bounded query only; no service/SLA claim |
| <https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL> | accessible; 2476 rendered lines | `out center` exposes a bounding-box center for ways/relations and does not guarantee it lies inside | center is preserved as provider-reported center, never called an entrance |
| <https://github.com/Project-OSRM/osrm-backend/blob/master/docs/http.md> | accessible; 1158 rendered lines | coordinates are longitude,latitude; route responses expose duration | request order and duration/second mapping are explicit |
| <https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server> | accessible; 426 rendered lines | demo use is limited to reasonable non-commercial use, <=1 request/s, without uptime/update guarantee | exactly two serialized anchor requests; no live test or production dependency |
| <https://github.com/Project-OSRM/osrm-backend/blob/master/LICENSE.TXT> | accessible; 314 rendered lines | OSRM software uses BSD-2-Clause | BSD applies to software only; fixture data is not labeled BSD |
| <https://operations.osmfoundation.org/policies/nominatim/> | accessible; 50 rendered lines | systematic POI downloads are forbidden; public service is capacity-limited | no Nominatim call or fallback |
| <https://lbs.amap.com/pages/terms/> | current retrieval failed before content; the same official page was previously read on 2026-07-28 | prior check found direct storage/cache restricted absent cooperation | zero 高德 calls; failed recheck does not create permission |
| <https://lbsyun.baidu.com/docs/pcsa?title=law%2Fopen%2Flaw> | accessible; 170 rendered lines | terms restrict direct storage/cache/download outside authorization | zero 百度 calls |
| <https://lbs.qq.com/terms.html> | accessible; 204 rendered lines | ungranted rights require written permission and interaction data belongs to Tencent | zero 腾讯 calls |

No web search summary is treated as the source. The URLs above identify the
pages actually opened. Page accessibility and rendered line counts are
retrieval evidence, not assertions that the pages will remain unchanged.

## 3. OSRM replay retention ruling

WU2 retains only two small route responses produced by a routing engine over
OSM data. The basis is:

1. the OSM data license expressly permits copying and adaptation under ODbL;
2. OSMF's routing guidance expressly contemplates routing output from OSM
   data and requires OSM attribution;
3. the OSRM demo policy permits reasonable non-commercial use and the planned
   two serialized requests remain within its published rate boundary;
4. the fixture is published with ODbL metadata and attribution;
5. the OSRM BSD license is recorded only as the engine software license and
   is not misrepresented as the response-data license.

This is a narrow fixture decision. It does not establish that arbitrary OSRM
responses, a substantial route database, commercial use, or a production
dependency may be stored.

The gate fails before fixture commit if:

- the actual response is not identifiable as OSM-derived;
- the endpoint reports a policy or attribution inconsistent with this basis;
- the response includes a credential, personal data or unapproved field that
  cannot be removed without changing the raw-response claim;
- either requested Wuyuan route is absent or ambiguous;
- storage would require a permission not represented above.

## 4. Capture protocol

Eligible source capture is bounded:

```text
HTTPS response
  -> random system-temporary file
  -> status/content/policy/hash check
  -> exact eligible replay bytes copied into fixture
  -> temporary file removed in finally
  -> residue check
```

POI capture:

- one Overpass query;
- supplied names only;
- `out center tags`;
- no `out meta`, user, uid, changeset or contributor metadata;
- one identified User-Agent;
- one bounded timeout and at most one transport retry.

Route capture:

- exactly two requests;
- serialized with at least one second between starts;
- profile `driving`;
- longitude before latitude;
- `alternatives=false`;
- `overview=false`;
- `steps=false`;
- `annotations=false`;
- `generate_hints=false`;
- `skip_waypoints=true`;
- no API key or account.

Tests and the final smoke run read only committed fixture bytes. They patch
socket creation to fail and report network-attempt count zero.

## 5. Hard exclusions

WU2 does not:

- call Nominatim, 高德, 百度 or 腾讯;
- scrape a webpage for POI facts;
- cache a commercial response;
- use a synthetic response as a real anchor;
- let an LLM identify, fill or normalize a fact;
- infer CRS/provider/permission from a name;
- use the OSRM demo as a production service;
- implement recommendation, routing, route choice, feasibility or planning.

If the OSM identities or both OSRM routes cannot be obtained under this gate,
WU2 stops as `BLOCKED`. It does not change provider.
