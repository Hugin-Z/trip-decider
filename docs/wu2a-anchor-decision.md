# WU2A Anchor Acquisition Decision

Status: INVESTIGATION_BLOCKED

Checked on: 2026-07-28

Scope: WU2A open-data anchor recovery only

This document records a stopped investigation. It does not approve an
acquisition recipe, create a fixture, or change the frozen WU2 adapter,
Schema, validator, source policy, or history.

## 1. WU2 blocker preserved

WU2 remains:

```text
BLOCKED
```

Its original bounded Overpass acquisition returned HTTP 200 with a valid
424-byte JSON response and zero elements. The response SHA256 was
`AD3054C0F768292F03758BC4901C35E21758829D6387A008E864EA4232EBECCB`.
That result proves only that the approved query produced no elements at that
time. It does not prove that OSM contains no relevant data.

WU2 stopped before C5. Its five commits remain unchanged.
`docs/reviews/work-unit-2-review.md` remains absent because WU2 never reached
C7 Review.

## 2. Official-source observations

The official/project pages were checked during the approved WU2A Plan stage:

| Source | Observation | WU2A consequence |
|---|---|---|
| <https://www.openstreetmap.org/copyright> | OSM data is distributed under ODbL with attribution/share-alike obligations | OSM can structurally support the existing `open_data_anchor` policy |
| <https://osmfoundation.org/wiki/Licence/Attribution_Guidelines> | attribution applies to uses including routing output | attribution cannot be omitted from any later fixture |
| <https://wiki.openstreetmap.org/wiki/Elements> | OSM has node, way and relation elements; nodes use WGS84 coordinates | no element type or CRS may be guessed |
| <https://wiki.openstreetmap.org/wiki/Names> | `name=*` is the primary real-world label; other name keys have distinct roles | the frozen adapter continues to require primary `tags.name` |
| <https://wiki.openstreetmap.org/wiki/Key:tourism> | tourism features can be nodes or areas | acquisition must inspect node/way/relation rather than assuming points |
| <https://wiki.openstreetmap.org/wiki/Key:historic> | `historic=*` is open-valued and can occur on different OSM elements | no closed tourism-only taxonomy is assumed |
| <https://wiki.openstreetmap.org/wiki/Key:place> | `place=*` identifies named settlements/places and can be a node or area | settlement records are structurally different from administrative areas |
| <https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL> | area creation is selective and delayed; bbox order is south/west/north/east | a zero area result is not proof of absent OSM data |
| <https://download.geofabrik.de/asia/china/jiangxi.html> | the public Jiangxi extract page offers ODbL-attributed PBF/GIS files and omits contributor account metadata | the regional `.poly` was eligible only as a bbox diagnostic |
| <https://download.geofabrik.de/technical.html> | `.poly` is an extract clipping boundary, not an administrative boundary | it cannot establish county identity |
| <https://extract.bbbike.org/extract.html> | BBBike requires an extract workflow and emits formats outside the frozen adapter | not selected and not called |
| <https://www.wikidata.org/wiki/Wikidata:Licensing> | Wikidata structured data is CC0 | open licensing does not make it an OSM/Overpass response |

These observations are engineering inputs, not legal advice. No policy page
was treated as proof of POI truth or completeness.

## 3. OSM tag/element/query analysis

The original WU2 query coupled exact target names to an exact Overpass area
lookup. Because Overpass areas may lag or be absent even when the underlying
relation exists, WU2A approved a query ladder:

```text
G0  derive a Jiangxi investigation bbox from the Geofabrik .poly
O1  discover an exact Wuyuan administrative relation inside that bbox
O2  query exact names/categories inside a unique relation area
O3  query the same exact names/categories inside the sourced Jiangxi bbox
```

The frozen category keys were:

```text
amenity
historic
leisure
natural
place
tourism
```

No fuzzy, nearest, first-result, LLM, manual-coordinate, guessed-ID, or
guessed-CRS rule was authorized.

## 4. Candidate-source decision matrix

| Candidate | License/replay | Adapter compatibility | Investigation result |
|---|---|---|---|
| OSM through the approved Overpass instance | existing ODbL policy can support persistence/replay with attribution | exact intended input family | attempted, but the bounded run did not produce a complete auditable ledger |
| Geofabrik Jiangxi `.poly` | ODbL-attributed regional clipping data | not an anchor document | one GET used only for bbox derivation; bytes deleted |
| Geofabrik PBF/GIS extract | ODbL, but requires another format/parser | incompatible without dependency or adapter change | not downloaded |
| BBBike | OSM-derived but external extract workflow | incompatible format/workflow | not called |
| Wikidata | CC0 | wrong provider and record contract | not queried |
| Nominatim | prohibited | prohibited | not called |
| OSRM | outside WU2A | outside WU2A | not called |
| Commercial maps | no approved persistence basis | prohibited | not called |

No alternative source was used after the investigation failure.

## 5. Machine-readable acquisition ledger

The acquisition harness was supplied through stdin to the project `.venv`
Python and was not written to the repository. It was intended to emit the
complete ledger only after the full bounded sequence. It terminated before
that emission. Missing fields below remain `null`; they are not reconstructed
from memory or estimates.

```json
{
  "decision_status": "INVESTIGATION_BLOCKED",
  "ledger_complete": false,
  "network_budget": {
    "allowed_get": 1,
    "allowed_overpass_post": 3,
    "allowed_byte_identical_retry": 1,
    "accounting_rule": "treat the observed control path as consuming 1 GET, 2 POST and the single retry; make no further calls",
    "exact_call_count_independently_emitted": false
  },
  "attempts": [
    {
      "attempt_id": "G0",
      "purpose": "derive sourced Jiangxi investigation bbox",
      "request_utf8": "https://download.geofabrik.de/asia/china/jiangxi.poly",
      "request_sha256": "892ACC39C74B24269C8200D2EAD351E0E9F9A436F5FD388FCD777792315F48F8",
      "endpoint": "https://download.geofabrik.de/asia/china/jiangxi.poly",
      "method": "GET",
      "started_at": null,
      "completed_at": null,
      "http_status": null,
      "response_bytes": null,
      "response_sha256": null,
      "content_type": null,
      "source_base_timestamp": null,
      "element_count": null,
      "selection_predicate": "strict poly parse and mechanical min/max bbox",
      "selection_result": "parse path completed before O1",
      "selection_reason": "program control reached O1; exact response measurements were not emitted before process termination",
      "temporary_path_category": "system_temp_random_file",
      "temporary_deleted": true,
      "temporary_residue_count": 0,
      "selected_summary": []
    },
    {
      "attempt_id": "O1",
      "purpose": "discover exact Wuyuan scope inside sourced Jiangxi bbox",
      "request_utf8": null,
      "request_sha256": null,
      "endpoint": "https://overpass-api.de/api/interpreter",
      "method": "POST",
      "started_at": null,
      "completed_at": null,
      "http_status": null,
      "response_bytes": null,
      "response_sha256": null,
      "content_type": null,
      "source_base_timestamp": null,
      "element_count": null,
      "selection_predicate": "exact administrative boundary name/name:zh plus explicit admin_level",
      "selection_result": "HTTPError entered the retry branch",
      "selection_reason": "HTTPError is a URLError subclass; the harness misclassified it as a transport failure and did not emit its status or body",
      "temporary_path_category": "none_http_error_body_not_read",
      "temporary_deleted": true,
      "temporary_residue_count": 0,
      "selected_summary": []
    },
    {
      "attempt_id": "O1-R1",
      "purpose": "byte-identical O1 retry",
      "request_utf8": null,
      "request_sha256": null,
      "endpoint": "https://overpass-api.de/api/interpreter",
      "method": "POST",
      "started_at": null,
      "completed_at": null,
      "http_status": 400,
      "response_bytes": null,
      "response_sha256": null,
      "content_type": null,
      "source_base_timestamp": null,
      "element_count": null,
      "selection_predicate": "transport retry only",
      "selection_result": "HTTP 400",
      "selection_reason": "uncaught final urllib.error.HTTPError: HTTP Error 400: Bad Request",
      "temporary_path_category": "none_http_error_body_not_read",
      "temporary_deleted": true,
      "temporary_residue_count": 0,
      "selected_summary": []
    }
  ],
  "post_failure_residue_check": {
    "pattern": "trip-decider-wu2a-*.capture",
    "system_temp_matching_files": 0
  },
  "forbidden_call_counts": {
    "nominatim": 0,
    "commercial_maps": 0,
    "osrm": 0,
    "alternate_overpass_instances": 0,
    "bbbike": 0,
    "wikidata_query_service": 0,
    "national_extracts": 0
  },
  "committed_raw_response_count": 0,
  "committed_coordinate_pair_count": 0,
  "approved_acquisition_recipe": null
}
```

The absence of a complete G0/O1 measurement record directly violates the
approved requirement that every call retain its exact request/response
evidence. The conservative budget treatment prevents another call from being
used to conceal that gap.

## 6. Selection analysis

No response element was selected.

The final HTTP 400 is a query/request failure, not evidence that OSM lacks
data. The lost substituted query bytes and bbox prevent an honest diagnosis
of whether the issue was request serialization, query syntax, or a derived
value. WU2A does not guess the cause and does not issue O2 or O3.

## 7. License, attribution, and replay decision

The OSM/Geofabrik ODbL basis remains suitable in principle for an attributed
open-data anchor. That legal/source-policy conclusion is separate from this
execution's missing acquisition evidence.

No raw response is approved for replay because none was retained under a
complete audited ledger. No policy field is allowed to compensate for missing
request/response evidence.

## 8. Final decision

```text
INVESTIGATION_BLOCKED
```

There is no `APPROVED_ACQUISITION_RECIPE`.

Reason:

> The bounded acquisition harness retried an HTTP error contrary to the
> transport-only retry rule and exited before emitting the mandatory
> per-attempt hashes, timestamps and counts. Those facts cannot be recovered
> without another call or reconstruction from memory. Both are prohibited.

This is a technical evidence-capture blocker. It is not a conclusion that the
open-data route is intrinsically infeasible.

## 9. WU2 compatibility classification

```text
not evaluated
```

Neither `WU2_C5_COMPATIBLE` nor `ADAPTER_COMPATIBLE_ONLY` can be assigned
without a valid non-empty captured response and deterministic selection.
WU2 C5/C6 remain stopped.

## 10. Limitations and non-capabilities

WU2A did not:

- create or persist a real anchor;
- save response bytes or a coordinate list;
- identify an OSM target;
- validate an Overpass query recipe;
- call O2, O3, OSRM, Nominatim, BBBike, Wikidata, or a commercial map;
- modify an adapter, Schema, validator, fixture, source policy, dependency, or
  existing test;
- resume WU2 or begin WU3.

The post-failure system-temporary residue check found zero matching capture
files. This deletion result does not repair the incomplete acquisition
ledger.
