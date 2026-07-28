"""OpenStreetMap/Overpass snapshot to candidate-artifact interface."""

from __future__ import annotations

import copy
import math
from typing import Mapping

from trip_decider.schema_validation import ValidationResult

from .contracts import (
    IngestionContext,
    artifact_envelope,
    exact_open_policy,
    problem,
    stable_identifier,
)


_SNAPSHOT_KEYS = {
    "format_version",
    "provider",
    "operation",
    "crs",
    "retrieved_at",
    "request_fingerprint",
    "response_locator",
    "data_policy",
    "result",
}
_CATEGORY_KEYS = frozenset(
    {"amenity", "historic", "leisure", "natural", "place", "tourism"}
)


def _failure(code: str, pointer: str, rule: str, actual: object = None):
    return ValidationResult(
        None,
        (problem(code, pointer, rule, actual=actual),),
    )


def _finite_coordinate(value: object, lower: float, upper: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and lower <= float(value) <= upper
    )


def normalize_open_data_pois(
    snapshot: Mapping[str, object],
    context: IngestionContext,
) -> ValidationResult[dict[str, object]]:
    """Normalize one strict open-data POI snapshot."""

    if not isinstance(snapshot, Mapping):
        return _failure(
            "INGESTION_INPUT_INVALID", "", "type", snapshot
        )
    if "provider" not in snapshot:
        return _failure(
            "INGESTION_PROVIDER_MISSING", "/provider", "required"
        )
    if "crs" not in snapshot:
        return _failure("INGESTION_CRS_MISSING", "/crs", "required")
    if set(snapshot) != _SNAPSHOT_KEYS:
        return _failure(
            "INGESTION_INPUT_INVALID", "", "closedSnapshot", snapshot
        )
    if snapshot["provider"] != "osm":
        return _failure(
            "INGESTION_INPUT_INVALID",
            "/provider",
            "const",
            snapshot["provider"],
        )
    if snapshot["crs"] != "WGS84":
        return _failure(
            "INGESTION_CRS_UNSUPPORTED",
            "/crs",
            "supportedCrs",
            snapshot["crs"],
        )
    if (
        snapshot["format_version"] != "0.1.0"
        or snapshot["operation"] != "overpass-poi-snapshot"
        or not isinstance(snapshot["retrieved_at"], str)
        or not isinstance(snapshot["request_fingerprint"], str)
        or len(snapshot["request_fingerprint"]) != 64
        or not isinstance(snapshot["response_locator"], Mapping)
    ):
        return _failure(
            "INGESTION_INPUT_INVALID", "", "snapshotMetadata", snapshot
        )
    if not exact_open_policy(snapshot["data_policy"]):
        return _failure(
            "INGESTION_POLICY_INVALID",
            "/data_policy",
            "openDataAnchorPolicy",
            snapshot["data_policy"],
        )
    result = snapshot["result"]
    if not isinstance(result, Mapping):
        return _failure(
            "INGESTION_INPUT_INVALID", "/result", "type", result
        )
    if result.get("status") == "error":
        if set(result) != {"status", "provider_error_code"}:
            return _failure(
                "INGESTION_INPUT_INVALID",
                "/result",
                "closedErrorResult",
                result,
            )
        return _failure(
            "INGESTION_PROVIDER_ERROR",
            "/result/provider_error_code",
            "providerStatus",
            result.get("provider_error_code"),
        )
    if result.get("status") != "success" or set(result) != {
        "status",
        "document",
    }:
        return _failure(
            "INGESTION_INPUT_INVALID", "/result", "resultStatus", result
        )
    document = result["document"]
    if not isinstance(document, Mapping):
        return _failure(
            "INGESTION_INPUT_INVALID",
            "/result/document",
            "type",
            document,
        )
    elements = document.get("elements")
    if not isinstance(elements, list):
        return _failure(
            "INGESTION_INPUT_INVALID",
            "/result/document/elements",
            "type",
            elements,
        )
    if not elements:
        return _failure(
            "INGESTION_RESPONSE_EMPTY",
            "/result/document/elements",
            "minItems",
            elements,
        )

    normalized: list[tuple[str, int, dict[str, object]]] = []
    seen: set[tuple[str, int]] = set()
    for index, element in enumerate(elements):
        base_pointer = f"/result/document/elements/{index}"
        if not isinstance(element, Mapping):
            return _failure(
                "INGESTION_RECORD_INVALID", base_pointer, "type", element
            )
        element_type = element.get("type")
        element_id = element.get("id")
        if (
            element_type not in {"node", "way", "relation"}
            or not isinstance(element_id, int)
            or isinstance(element_id, bool)
            or element_id <= 0
        ):
            return _failure(
                "INGESTION_RECORD_INVALID",
                base_pointer,
                "providerIdentity",
                element,
            )
        identity = (str(element_type), element_id)
        if identity in seen:
            return _failure(
                "INGESTION_RECORD_INVALID",
                base_pointer,
                "uniqueProviderIdentity",
                element,
            )
        seen.add(identity)
        tags = element.get("tags")
        if not isinstance(tags, Mapping):
            return _failure(
                "INGESTION_RECORD_INVALID",
                f"{base_pointer}/tags",
                "type",
                tags,
            )
        name = tags.get("name")
        if not isinstance(name, str) or not name:
            return _failure(
                "INGESTION_RECORD_INVALID",
                f"{base_pointer}/tags/name",
                "required",
                name,
            )
        categories = [
            {"code": f"{key}={tags[key]}", "label": str(tags[key])}
            for key in sorted(_CATEGORY_KEYS.intersection(tags))
            if isinstance(tags[key], str) and tags[key]
        ]
        if not categories:
            return _failure(
                "INGESTION_RECORD_INVALID",
                f"{base_pointer}/tags",
                "providerCategory",
                tags,
            )
        if element_type == "node":
            latitude = element.get("lat")
            longitude = element.get("lon")
        else:
            center = element.get("center")
            if not isinstance(center, Mapping):
                return _failure(
                    "INGESTION_RECORD_INVALID",
                    base_pointer,
                    "coordinates",
                    element,
                )
            latitude = center.get("lat")
            longitude = center.get("lon")
        if not _finite_coordinate(latitude, -90, 90) or not _finite_coordinate(
            longitude, -180, 180
        ):
            return _failure(
                "INGESTION_RECORD_INVALID",
                base_pointer,
                "coordinates",
                element,
            )
        locator = {
            "kind": "provider_item",
            "value": f"osm:{element_type}:{element_id}",
        }
        candidate = {
            "candidate_id": stable_identifier(
                "candidate",
                "trip-decider:wu2:candidate",
                f"osm:{element_type}:{element_id}",
            ),
            "candidate_kind": "poi",
            "label": name,
            "parent_candidate_id": None,
            "location": {
                "kind": "coordinates",
                "latitude": latitude,
                "longitude": longitude,
                "crs": "WGS84",
                "source_refs": [locator],
            },
            "provider": {
                "name": "osm",
                "record_id": str(element_id),
                "record_type": element_type,
                "categories": categories,
                "external_status": {"kind": "not_reported"},
                "data_policy": dict(snapshot["data_policy"]),
            },
            "source_refs": [locator],
            "evidence_fact_refs": [],
            "generation_reason": (
                "Imported from an OSM open-data anchor; no ranking performed."
            ),
        }
        normalized.append((str(element_type), element_id, candidate))

    normalized.sort(key=lambda item: (item[0], item[1]))
    candidates = [item[2] for item in normalized]
    identity_seed = ",".join(
        f"osm:{item[0]}:{item[1]}" for item in normalized
    )
    payload = {
        "candidate_set_id": stable_identifier(
            "candidate_set",
            "trip-decider:wu2:candidate-set",
            f"{context.request_ref['artifact_id']}|{identity_seed}",
        ),
        "request_ref": dict(context.request_ref),
        "generation_stage": "poi_discovery",
        "candidates": candidates,
        "rejected_inputs": [],
    }
    provenance_snapshot = copy.deepcopy(snapshot)
    provenance_document = provenance_snapshot["result"]["document"]
    provenance_document["elements"] = sorted(
        provenance_document["elements"],
        key=lambda item: (str(item["type"]), int(item["id"])),
    )
    return ValidationResult(
        artifact_envelope(
            "candidates", payload, context, [provenance_snapshot]
        ),
        (),
    )
