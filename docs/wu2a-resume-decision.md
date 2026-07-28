# WU2A Resume Acquisition Decision

Status: APPROVED_ACQUISITION_RECIPE

Checked on: 2026-07-28

Scope: WU2A-Resume bounded open-data acquisition investigation only

This document records a new, independently authorized attempt group. It does
not rewrite the stopped WU2 or WU2A outcomes, create or persist an anchor,
execute the approved recipe a second time, resume WU2 C5/C6, or change an
adapter, Schema, validator, source policy, dependency, fixture, or test.

## 1. Preserved historical states

```text
WU2: BLOCKED
WU2A: INVESTIGATION_BLOCKED
WU2A-R: APPROVED
```

The prior WU2A investigation remains a separate incomplete-ledger attempt.
Its decision path, status, and byte hash are frozen in the ledger below. No
prior commit or decision document was amended.

## 2. New authorization and actual budget

The independent group `WU2A-resume-001` used one Geofabrik Jiangxi `.poly`
GET and two scheduled POST operations to the original Overpass instance.
Each scheduled operation produced one physical attempt. No transport retry
was used, so the single shared retry relation remained unused. Conditional
O3 was not called because O2 returned a non-empty deterministic selection.

## 3. Source, license, attribution, and replay basis

The source basis remains the frozen WU2/WU1C policy: OpenStreetMap data under
ODbL 1.0 with `© OpenStreetMap contributors` attribution. Geofabrik's
Jiangxi `.poly` supplied only an extract-clipping bbox diagnostic; it is not
represented as an administrative boundary, POI, candidate, or anchor.

The approved recipe may be executed later only as a new, separately
authorized and recorded attempt. OSM is mutable, so replay means reissuing
the exact query and comparing a new result; it does not promise the response
hash observed here will recur. This work unit committed no response bytes.

## 4. Executed frozen query ladder

```text
G0  completed: strict .poly parse and mechanical bbox
O1  completed: one exact administrative relation
O2  completed: seven structurally selectable OSM objects
O3  not applicable: O2 selection was non-empty
```

No fuzzy, nearest, first-result, popularity, manual-coordinate, guessed-ID,
language-fallback, LLM, or alternate-endpoint rule was used.

## 5. Machine-readable resume ledger

<!-- WU2A_RESUME_LEDGER_BEGIN -->
```json
{
  "schema_version": "wu2a-resume-decision/1.0",
  "decision_status": "APPROVED_ACQUISITION_RECIPE",
  "attempt_group": "WU2A-resume-001",
  "previous_investigation": {
    "path": "docs/wu2a-anchor-decision.md",
    "sha256": "570649D6B7287B48F3C396E536AC05EF31D949FC7AF960EF2D3DFEB17D4A9F6D",
    "status": "INVESTIGATION_BLOCKED",
    "ledger_complete": false
  },
  "authorization": {
    "plan_path": "plans/work-unit-2a-resume.md",
    "plan_sha256": "B363FA80F1E62168E7AF654DE1195A24812F890352FB6C15852D65C488EE9BDB",
    "source_policy_ref": {
      "path": "docs/real-world-source-policy.md",
      "sha256": "B89D0836BCC17DD1D52CA215F38EF290134251295ECAC183BA7D54C45A1C4989"
    }
  },
  "budget": {
    "old_investigation_accounting": {
      "decision_path": "docs/wu2a-anchor-decision.md",
      "ledger_complete": false,
      "merged_into_new_group": false
    },
    "new_authorization": {
      "scheduled_operations": {
        "geofabrik_poly_get": 1,
        "overpass_post": 3
      },
      "transport_retry": {
        "total_across_group": 1
      },
      "allowed_endpoints": {
        "geofabrik_poly_get": "https://download.geofabrik.de/asia/china/jiangxi.poly",
        "overpass_post": "https://overpass-api.de/api/interpreter"
      }
    },
    "actual": {
      "scheduled_operations": {
        "geofabrik_poly_get": 1,
        "overpass_post": 2
      },
      "physical_attempts": 3,
      "retry_relations": 0
    }
  },
  "source_policy": {
    "source_class": "open_data",
    "capture_mode": "persistent_anchor",
    "storage_policy": "persistent_allowed",
    "replay_allowed": true,
    "fixture_allowed": true,
    "policy_checked_at": "2026-07-28T00:00:00+08:00",
    "terms_url": "https://www.openstreetmap.org/copyright",
    "authorization_ref": null,
    "license": {
      "identifier": "ODbL-1.0",
      "url": "https://opendatacommons.org/licenses/odbl/1-0/",
      "attribution": "© OpenStreetMap contributors"
    }
  },
  "query_ladder": {
    "operation_order": [
      "G0",
      "O1",
      "O2",
      "O3"
    ],
    "frozen_names": [
      "婺源县",
      "婺源",
      "江岭",
      "篁岭",
      "李坑",
      "庆源"
    ],
    "frozen_category_keys": [
      "amenity",
      "historic",
      "leisure",
      "natural",
      "place",
      "tourism"
    ]
  },
  "operations": [
    {
      "operation_id": "G0",
      "purpose": "derive sourced Jiangxi investigation bbox",
      "endpoint": "https://download.geofabrik.de/asia/china/jiangxi.poly",
      "method": "GET",
      "headers_profile": {
        "user_agent": "trip-decider-wu2a-resume/0.1 non-production-research",
        "content_type": null,
        "http_timeout_seconds": 40,
        "overpass_query_timeout_seconds": null
      },
      "query_utf8": null,
      "query_sha256": null,
      "request_ascii": "https://download.geofabrik.de/asia/china/jiangxi.poly",
      "request_sha256": "892ACC39C74B24269C8200D2EAD351E0E9F9A436F5FD388FCD777792315F48F8",
      "observed": {
        "source_base_timestamp": null,
        "observed_element_count": null,
        "response_bytes": 17003,
        "response_sha256": "B874AF22600165D6110F69472338720B4E210214E2EC681BF933F276BC858BBC",
        "vertex_count": 548,
        "ring_count": 1,
        "bbox": {
          "south": "24.47809",
          "west": "113.5688",
          "north": "30.08841",
          "east": "118.4865"
        },
        "selection_result": "bbox_derived",
        "selection_reason": "strict_poly_vertices_mechanically_bounded",
        "selected_count": 0,
        "selected_summary": []
      },
      "attempts": [
        {
          "qualified_attempt_id": "WU2A-resume-001:G0:attempt-0001",
          "attempt_group": "WU2A-resume-001",
          "operation_id": "G0",
          "harness_attempt": {
            "attempt_id": "attempt-0001",
            "purpose": "derive sourced Jiangxi investigation bbox",
            "endpoint": "https://download.geofabrik.de/asia/china/jiangxi.poly",
            "method": "GET",
            "request_sha256": "892acc39c74b24269c8200d2ead351e0e9f9a436f5fd388fcd777792315f48f8",
            "started_at": "2026-07-28T05:56:03.862Z",
            "completed_at": "2026-07-28T05:56:06.101Z",
            "status": "succeeded",
            "http_status": 200,
            "response_bytes": 17003,
            "response_sha256": "b874af22600165d6110f69472338720b4e210214e2ec681bf933f276bc858bbc",
            "content_type": null,
            "error_class": null,
            "retry_decision": "not_applicable"
          },
          "query_sha256": null,
          "observed_element_count": null,
          "source_base_timestamp": null,
          "selection_result": "bbox_derived",
          "selection_reason": "strict_poly_vertices_mechanically_bounded",
          "attempt_cleanup": {
            "raw_capture_created": false,
            "raw_capture_deletion_status": "not_applicable_no_capture_file",
            "ledger_path_category": "system_temp_random_file",
            "ledger_deleted": true,
            "ledger_residue_count": 0
          }
        }
      ]
    },
    {
      "operation_id": "O1",
      "purpose": "discover exact Wuyuan administrative relation",
      "endpoint": "https://overpass-api.de/api/interpreter",
      "method": "POST",
      "headers_profile": {
        "user_agent": "trip-decider-wu2a-resume/0.1 non-production-research",
        "content_type": "application/x-www-form-urlencoded; charset=UTF-8",
        "http_timeout_seconds": 40,
        "overpass_query_timeout_seconds": 25
      },
      "query_utf8": "[out:json][timeout:25][bbox:24.47809,113.5688,30.08841,118.4865];\n(\n  rel[\"boundary\"=\"administrative\"][\"name\"=\"婺源县\"];\n  rel[\"boundary\"=\"administrative\"][\"name:zh\"=\"婺源县\"];\n  nwr[\"place\"][\"name\"=\"婺源\"];\n  nwr[\"place\"][\"name:zh\"=\"婺源\"];\n);\nout center tags;\n",
      "query_sha256": "BE9D88846226229A626B3BB6A91BF6AD77425C5368950A8B0287FA4635AFEA64",
      "request_ascii": "data=%5Bout%3Ajson%5D%5Btimeout%3A25%5D%5Bbbox%3A24.47809%2C113.5688%2C30.08841%2C118.4865%5D%3B%0A%28%0A++rel%5B%22boundary%22%3D%22administrative%22%5D%5B%22name%22%3D%22%E5%A9%BA%E6%BA%90%E5%8E%BF%22%5D%3B%0A++rel%5B%22boundary%22%3D%22administrative%22%5D%5B%22name%3Azh%22%3D%22%E5%A9%BA%E6%BA%90%E5%8E%BF%22%5D%3B%0A++nwr%5B%22place%22%5D%5B%22name%22%3D%22%E5%A9%BA%E6%BA%90%22%5D%3B%0A++nwr%5B%22place%22%5D%5B%22name%3Azh%22%3D%22%E5%A9%BA%E6%BA%90%22%5D%3B%0A%29%3B%0Aout+center+tags%3B%0A",
      "request_sha256": "E88E8BFD82CC64B80CB09480C3ADD47F3B8003D6D665F4B2A56C639B461FE3AC",
      "observed": {
        "source_base_timestamp": "2026-07-28T05:54:59Z",
        "observed_element_count": 1,
        "response_bytes": 1354,
        "response_sha256": "FC5D7965965055B4FA61C1194B997233086D7AE8D5AB6BA9625AB47BF4796122",
        "selection_result": "unique_administrative_relation",
        "selection_reason": "unique_exact_administrative_relation_observed",
        "selected_count": 1,
        "selected_summary": [
          {
            "type": "relation",
            "id": 3046784,
            "name": "婺源县",
            "admin_level": "6"
          }
        ],
        "captured_relation_id": 3046784
      },
      "attempts": [
        {
          "qualified_attempt_id": "WU2A-resume-001:O1:attempt-0001",
          "attempt_group": "WU2A-resume-001",
          "operation_id": "O1",
          "harness_attempt": {
            "attempt_id": "attempt-0001",
            "purpose": "discover exact Wuyuan administrative relation",
            "endpoint": "https://overpass-api.de/api/interpreter",
            "method": "POST",
            "request_sha256": "e88e8bfd82cc64b80cb09480c3add47f3b8003d6d665f4b2a56c639b461fe3ac",
            "started_at": "2026-07-28T05:56:13.969Z",
            "completed_at": "2026-07-28T05:56:17.430Z",
            "status": "succeeded",
            "http_status": 200,
            "response_bytes": 1354,
            "response_sha256": "fc5d7965965055b4fa61c1194b997233086d7ae8d5ab6ba9625ab47bf4796122",
            "content_type": "application/json",
            "error_class": null,
            "retry_decision": "not_applicable"
          },
          "query_sha256": "BE9D88846226229A626B3BB6A91BF6AD77425C5368950A8B0287FA4635AFEA64",
          "observed_element_count": 1,
          "source_base_timestamp": "2026-07-28T05:54:59Z",
          "selection_result": "unique_administrative_relation",
          "selection_reason": "unique_exact_administrative_relation_observed",
          "attempt_cleanup": {
            "raw_capture_created": false,
            "raw_capture_deletion_status": "not_applicable_no_capture_file",
            "ledger_path_category": "system_temp_random_file",
            "ledger_deleted": true,
            "ledger_residue_count": 0
          }
        }
      ]
    },
    {
      "operation_id": "O2",
      "purpose": "query exact frozen names and categories in unique relation area",
      "endpoint": "https://overpass-api.de/api/interpreter",
      "method": "POST",
      "headers_profile": {
        "user_agent": "trip-decider-wu2a-resume/0.1 non-production-research",
        "content_type": "application/x-www-form-urlencoded; charset=UTF-8",
        "http_timeout_seconds": 40,
        "overpass_query_timeout_seconds": 25
      },
      "query_utf8": "[out:json][timeout:25];\nrel(id:3046784)->.county;\n.county map_to_area->.scope;\n(\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"amenity\"];\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"historic\"];\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"leisure\"];\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"natural\"];\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"place\"];\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"tourism\"];\n);\nout center tags;\n",
      "query_sha256": "5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F",
      "request_ascii": "data=%5Bout%3Ajson%5D%5Btimeout%3A25%5D%3B%0Arel%28id%3A3046784%29-%3E.county%3B%0A.county+map_to_area-%3E.scope%3B%0A%28%0A++nwr%28area.scope%29%5B%22name%22~%22%5E%28%E5%A9%BA%E6%BA%90%E5%8E%BF%7C%E5%A9%BA%E6%BA%90%7C%E6%B1%9F%E5%B2%AD%7C%E7%AF%81%E5%B2%AD%7C%E6%9D%8E%E5%9D%91%7C%E5%BA%86%E6%BA%90%29%24%22%5D%5B%22amenity%22%5D%3B%0A++nwr%28area.scope%29%5B%22name%22~%22%5E%28%E5%A9%BA%E6%BA%90%E5%8E%BF%7C%E5%A9%BA%E6%BA%90%7C%E6%B1%9F%E5%B2%AD%7C%E7%AF%81%E5%B2%AD%7C%E6%9D%8E%E5%9D%91%7C%E5%BA%86%E6%BA%90%29%24%22%5D%5B%22historic%22%5D%3B%0A++nwr%28area.scope%29%5B%22name%22~%22%5E%28%E5%A9%BA%E6%BA%90%E5%8E%BF%7C%E5%A9%BA%E6%BA%90%7C%E6%B1%9F%E5%B2%AD%7C%E7%AF%81%E5%B2%AD%7C%E6%9D%8E%E5%9D%91%7C%E5%BA%86%E6%BA%90%29%24%22%5D%5B%22leisure%22%5D%3B%0A++nwr%28area.scope%29%5B%22name%22~%22%5E%28%E5%A9%BA%E6%BA%90%E5%8E%BF%7C%E5%A9%BA%E6%BA%90%7C%E6%B1%9F%E5%B2%AD%7C%E7%AF%81%E5%B2%AD%7C%E6%9D%8E%E5%9D%91%7C%E5%BA%86%E6%BA%90%29%24%22%5D%5B%22natural%22%5D%3B%0A++nwr%28area.scope%29%5B%22name%22~%22%5E%28%E5%A9%BA%E6%BA%90%E5%8E%BF%7C%E5%A9%BA%E6%BA%90%7C%E6%B1%9F%E5%B2%AD%7C%E7%AF%81%E5%B2%AD%7C%E6%9D%8E%E5%9D%91%7C%E5%BA%86%E6%BA%90%29%24%22%5D%5B%22place%22%5D%3B%0A++nwr%28area.scope%29%5B%22name%22~%22%5E%28%E5%A9%BA%E6%BA%90%E5%8E%BF%7C%E5%A9%BA%E6%BA%90%7C%E6%B1%9F%E5%B2%AD%7C%E7%AF%81%E5%B2%AD%7C%E6%9D%8E%E5%9D%91%7C%E5%BA%86%E6%BA%90%29%24%22%5D%5B%22tourism%22%5D%3B%0A%29%3B%0Aout+center+tags%3B%0A",
      "request_sha256": "6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045",
      "observed": {
        "source_base_timestamp": "2026-07-28T05:54:59Z",
        "observed_element_count": 7,
        "response_bytes": 4362,
        "response_sha256": "29616F1DA00680B3253D0341EF78095664382A7D070C12CF3DB7FFC048C96A4C",
        "selection_result": "selected_nonempty",
        "selection_reason": "frozen_predicate_selected_unique_elements",
        "selected_count": 7,
        "selected_summary": [
          {
            "type": "node",
            "id": 244082160,
            "name": "婺源县",
            "matched_categories": [
              {
                "key": "place",
                "value": "county"
              }
            ],
            "coordinate_shape": "node_lat_lon"
          },
          {
            "type": "node",
            "id": 673351120,
            "name": "婺源县",
            "matched_categories": [
              {
                "key": "place",
                "value": "city"
              }
            ],
            "coordinate_shape": "node_lat_lon"
          },
          {
            "type": "node",
            "id": 4818081345,
            "name": "篁岭",
            "matched_categories": [
              {
                "key": "place",
                "value": "hamlet"
              }
            ],
            "coordinate_shape": "node_lat_lon"
          },
          {
            "type": "node",
            "id": 5136917928,
            "name": "李坑",
            "matched_categories": [
              {
                "key": "place",
                "value": "village"
              }
            ],
            "coordinate_shape": "node_lat_lon"
          },
          {
            "type": "node",
            "id": 5139051592,
            "name": "江岭",
            "matched_categories": [
              {
                "key": "place",
                "value": "hamlet"
              }
            ],
            "coordinate_shape": "node_lat_lon"
          },
          {
            "type": "node",
            "id": 5404580598,
            "name": "篁岭",
            "matched_categories": [
              {
                "key": "tourism",
                "value": "attraction"
              }
            ],
            "coordinate_shape": "node_lat_lon"
          },
          {
            "type": "relation",
            "id": 3046784,
            "name": "婺源县",
            "matched_categories": [
              {
                "key": "place",
                "value": "county"
              }
            ],
            "coordinate_shape": "reported_center"
          }
        ]
      },
      "attempts": [
        {
          "qualified_attempt_id": "WU2A-resume-001:O2:attempt-0001",
          "attempt_group": "WU2A-resume-001",
          "operation_id": "O2",
          "harness_attempt": {
            "attempt_id": "attempt-0001",
            "purpose": "query exact frozen names and categories in unique relation area",
            "endpoint": "https://overpass-api.de/api/interpreter",
            "method": "POST",
            "request_sha256": "6765abdaa3bbbb4a70f1e28ea7b4a339f81ed7a2f9ccc8b9a4ce8ba1de275045",
            "started_at": "2026-07-28T05:56:23.110Z",
            "completed_at": "2026-07-28T05:56:33.991Z",
            "status": "succeeded",
            "http_status": 200,
            "response_bytes": 4362,
            "response_sha256": "29616f1da00680b3253d0341ef78095664382a7d070c12cf3db7ffc048c96a4c",
            "content_type": "application/json",
            "error_class": null,
            "retry_decision": "not_applicable"
          },
          "query_sha256": "5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F",
          "observed_element_count": 7,
          "source_base_timestamp": "2026-07-28T05:54:59Z",
          "selection_result": "selected_nonempty",
          "selection_reason": "frozen_predicate_selected_unique_elements",
          "attempt_cleanup": {
            "raw_capture_created": false,
            "raw_capture_deletion_status": "not_applicable_no_capture_file",
            "ledger_path_category": "system_temp_random_file",
            "ledger_deleted": true,
            "ledger_residue_count": 0
          }
        }
      ]
    }
  ],
  "retry_relations": [],
  "forbidden_call_counts": {
    "nominatim": 0,
    "osrm": 0,
    "commercial_maps": 0,
    "alternate_overpass_instances": 0,
    "bbbike": 0,
    "wikidata_query_service": 0,
    "web_crawlers": 0
  },
  "committed_raw_response_count": 0,
  "committed_coordinate_pair_count": 0,
  "fixture_count_created": 0,
  "approved_acquisition_recipe": {
    "source": "OSM through Overpass",
    "endpoint": "https://overpass-api.de/api/interpreter",
    "method": "POST",
    "query_utf8": "[out:json][timeout:25];\nrel(id:3046784)->.county;\n.county map_to_area->.scope;\n(\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"amenity\"];\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"historic\"];\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"leisure\"];\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"natural\"];\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"place\"];\n  nwr(area.scope)[\"name\"~\"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$\"][\"tourism\"];\n);\nout center tags;\n",
    "query_sha256": "5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F",
    "request_sha256": "6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045",
    "geographic_scope": {
      "type": "captured_relation_area",
      "relation_id": 3046784,
      "discovery_operation": "O1"
    },
    "selection_predicate": "unique OSM (type,id), exact primary tags.name in frozen set, non-empty frozen category, explicit node lat/lon or reported way/relation center",
    "observed_element_count": 7,
    "selected_count": 7,
    "observed_response_sha256": "29616F1DA00680B3253D0341EF78095664382A7D070C12CF3DB7FFC048C96A4C",
    "license": {
      "identifier": "ODbL-1.0",
      "url": "https://opendatacommons.org/licenses/odbl/1-0/",
      "attribution": "© OpenStreetMap contributors"
    },
    "replay_policy": "Reissue the exact query only as a new authorized attempt; compare and revalidate the new response because OSM data and response hashes may change.",
    "compatibility": "ADAPTER_COMPATIBLE_ONLY",
    "limitations": [
      "No raw response or anchor bytes were persisted by WU2A-Resume.",
      "The frozen result did not select 庆源.",
      "婺源县 and 篁岭 each had multiple distinct qualifying OSM identities; none was preferred as the first or nearest.",
      "No OSRM route prerequisite was acquired.",
      "This recipe does not authorize restoration of WU2 C5/C6."
    ]
  },
  "negative_conclusion": null,
  "compatibility": "ADAPTER_COMPATIBLE_ONLY",
  "runtime_cleanup": {
    "raw_capture_created": false,
    "raw_capture_deletion_status": "not_applicable_no_capture_file",
    "helper_deleted": true,
    "helper_residue_count": 0,
    "validator_deleted": true,
    "validator_residue_count": 0,
    "ledger_residue_count": 0,
    "atomic_tmp_residue_count": 0
  }
}
```
<!-- WU2A_RESUME_LEDGER_END -->

## 6. Deterministic selection analysis

G0 parsed 548 explicit `.poly` vertices and mechanically bounded them without
retaining a vertex list. O1 returned one exact administrative relation with
an explicit `admin_level`. O2 returned seven elements; every retained
summary has a unique `(type,id)`, an exact primary `tags.name`, a non-empty
frozen category, and an explicit coordinate shape. Numeric POI coordinates,
response excerpts, and full tags are not recorded.

The result is not enough to restore the old WU2 target set: no `庆源` object
was selected, while `婺源县` and `篁岭` each produced multiple distinct
qualifying identities. The investigation does not choose among them.

## 7. Final decision

```text
APPROVED_ACQUISITION_RECIPE
```

The O2 relation-area query is legal under the recorded ODbL basis,
traceable, replayable as a new attempt, and structurally compatible with the
frozen OSM adapter. Approval applies to the recipe, not to a persisted
anchor or a claim that the observed response will remain unchanged.

## 8. WU2 compatibility

```text
ADAPTER_COMPATIBLE_ONLY
```

The response shape satisfies the adapter boundary, but old WU2 target
coverage and route prerequisites are incomplete. `WU2_C5_COMPATIBLE` is not
claimed, and WU2 remains `BLOCKED`.

## 9. Cleanup, forbidden calls, and non-capabilities

All three harness ledgers and their atomic temporary files were deleted from
the system temporary directory. Response bodies existed only in memory.
The helper was deleted before final validation; the final validator deletes
itself after reading the final decision and verifies zero matching validator
residue. The committed raw-response, numeric-coordinate-pair, and fixture
counts are zero.

Actual forbidden-call counts are all zero. WU2A-Resume did not call O3,
OSRM, Nominatim, a commercial map, a second Overpass instance, BBBike,
Wikidata Query Service, or a crawler. It did not create an anchor or fixture,
execute a route request, modify prior work, restore WU2, or begin WU3.
