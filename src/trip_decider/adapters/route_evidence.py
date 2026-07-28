"""OSRM route snapshot to evidence-artifact interface."""

from __future__ import annotations

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
_CANDIDATE_PATTERN_PREFIX = "candidate_"


def _failure(code: str, pointer: str, rule: str, actual: object = None):
    return ValidationResult(
        None,
        (problem(code, pointer, rule, actual=actual),),
    )


def _duration(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _coordinate(value: object, limit: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and abs(float(value)) <= limit
    )


def normalize_route_evidence(
    snapshot: Mapping[str, object],
    context: IngestionContext,
) -> ValidationResult[dict[str, object]]:
    """Normalize strict open route records into evidence facts."""

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
    if snapshot["provider"] != "osrm":
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
        or snapshot["operation"] != "route/v1/driving"
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
    records = document.get("routes")
    if not isinstance(records, list):
        return _failure(
            "INGESTION_INPUT_INVALID",
            "/result/document/routes",
            "type",
            records,
        )
    if not records:
        return _failure(
            "INGESTION_RESPONSE_EMPTY",
            "/result/document/routes",
            "minItems",
            records,
        )

    facts: list[tuple[str, dict[str, object]]] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        base_pointer = f"/result/document/routes/{index}"
        if not isinstance(record, Mapping):
            return _failure(
                "INGESTION_INPUT_INVALID", base_pointer, "type", record
            )
        route_id = record.get("route_id")
        if not isinstance(route_id, str) or not route_id or route_id in seen:
            return _failure(
                "INGESTION_INPUT_INVALID",
                f"{base_pointer}/route_id",
                "uniqueRouteId",
                route_id,
            )
        seen.add(route_id)
        if record.get("coordinate_order") != "longitude,latitude":
            return _failure(
                "INGESTION_INPUT_INVALID",
                f"{base_pointer}/coordinate_order",
                "coordinateOrder",
                record.get("coordinate_order"),
            )
        from_ref = record.get("from_candidate_ref")
        to_ref = record.get("to_candidate_ref")
        if (
            not isinstance(from_ref, str)
            or not from_ref.startswith(_CANDIDATE_PATTERN_PREFIX)
            or not isinstance(to_ref, str)
            or not to_ref.startswith(_CANDIDATE_PATTERN_PREFIX)
            or record.get("mode") != "driving"
        ):
            return _failure(
                "INGESTION_INPUT_INVALID",
                base_pointer,
                "routeIdentity",
                record,
            )
        coordinates = record.get("request_coordinates")
        if not isinstance(coordinates, list) or len(coordinates) != 2:
            return _failure(
                "INGESTION_INPUT_INVALID",
                f"{base_pointer}/request_coordinates",
                "coordinatePair",
                coordinates,
            )
        for coordinate_index, coordinate in enumerate(coordinates):
            if (
                not isinstance(coordinate, Mapping)
                or set(coordinate) != {"longitude", "latitude"}
                or not _coordinate(coordinate.get("longitude"), 180)
                or not _coordinate(coordinate.get("latitude"), 90)
            ):
                return _failure(
                    "INGESTION_INPUT_INVALID",
                    (
                        f"{base_pointer}/request_coordinates/"
                        f"{coordinate_index}"
                    ),
                    "coordinate",
                    coordinate,
                )
        request_fingerprint = record.get("request_fingerprint")
        response_locator = record.get("response_locator")
        if (
            not isinstance(request_fingerprint, str)
            or len(request_fingerprint) != 64
            or not isinstance(response_locator, Mapping)
        ):
            return _failure(
                "INGESTION_INPUT_INVALID",
                base_pointer,
                "routeMetadata",
                record,
            )
        response = record.get("response")
        if not isinstance(response, Mapping):
            return _failure(
                "INGESTION_INPUT_INVALID",
                f"{base_pointer}/response",
                "type",
                response,
            )
        if response.get("code") != "Ok":
            return _failure(
                "INGESTION_PROVIDER_ERROR",
                f"{base_pointer}/response/code",
                "providerStatus",
                response.get("code"),
            )
        provider_routes = response.get("routes")
        if not isinstance(provider_routes, list) or len(provider_routes) != 1:
            return _failure(
                "INGESTION_ROUTE_COUNT_INVALID",
                f"{base_pointer}/response/routes",
                "exactlyOneRoute",
                provider_routes,
            )
        provider_route = provider_routes[0]
        duration = (
            provider_route.get("duration")
            if isinstance(provider_route, Mapping)
            else None
        )
        if not _duration(duration):
            return _failure(
                "INGESTION_DURATION_INVALID",
                f"{base_pointer}/response/routes/0/duration",
                "durationSecond",
                duration,
            )
        source_id = f"source_osrm_{route_id.lower().replace('_', '-')}"
        fact = {
            "fact_id": stable_identifier(
                "fact",
                "trip-decider:wu2:fact",
                f"{route_id}|{from_ref}|{to_ref}",
            ),
            "subject": {
                "subject_type": "relation",
                "relation_type": "route",
                "from_candidate_ref": from_ref,
                "to_candidate_ref": to_ref,
                "mode": "driving",
            },
            "field": "travel_time",
            "value": duration,
            "unit": "second",
            "support_status": "sourced",
            "derivation": "api_estimate",
            "freshness": {
                "retrieved_at": snapshot["retrieved_at"],
                "effective_at": None,
                "expires_at": None,
                "status": "unknown",
            },
            "sources": [
                {
                    "source_id": source_id,
                    "source_type": "api_response",
                    "provider": "osrm",
                    "operation": "route/v1/driving",
                    "retrieved_at": snapshot["retrieved_at"],
                    "request_fingerprint": request_fingerprint,
                    "response_locator": dict(response_locator),
                }
            ],
            "normalization": {
                "original_value": duration,
                "normalized_value": duration,
                "rule_id": "osrm-duration-second-v1",
            },
            "display_status": "estimated",
            "display_rule": "api-estimate-to-estimated-v1",
            "conflict_source_refs": [],
            "derivation_detail": {
                "input_fact_ids": [],
                "estimate": {
                    "method": "osrm-route-v1-driving",
                    "value": duration,
                    "unit": "second",
                },
            },
        }
        facts.append((route_id, fact))

    facts.sort(key=lambda item: item[0])
    route_seed = ",".join(item[0] for item in facts)
    payload = {
        "evidence_set_id": stable_identifier(
            "evidence_set",
            "trip-decider:wu2:evidence-set",
            route_seed,
        ),
        "facts": [item[1] for item in facts],
        "mapping_rule_version": "wu2-route-evidence-0.1.0",
    }
    return ValidationResult(
        artifact_envelope("evidence", payload, context, [snapshot]),
        (),
    )
