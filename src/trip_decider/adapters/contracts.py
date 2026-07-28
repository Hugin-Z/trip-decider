"""Shared WU2 adapter contracts.

The wire inputs remain mappings. These dataclasses carry only explicit
run-scoped values and do not infer provider, CRS, policy, timestamps, or IDs.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from trip_decider.schema_validation import (
    ValidationProblem,
    canonical_payload_sha256,
)


INGESTION_PROBLEM_CODES = frozenset(
    {
        "INGESTION_INPUT_INVALID",
        "INGESTION_PROVIDER_MISSING",
        "INGESTION_CRS_MISSING",
        "INGESTION_CRS_UNSUPPORTED",
        "INGESTION_POLICY_INVALID",
        "INGESTION_RESPONSE_EMPTY",
        "INGESTION_PROVIDER_ERROR",
        "INGESTION_RECORD_INVALID",
        "INGESTION_ROUTE_COUNT_INVALID",
        "INGESTION_DURATION_INVALID",
    }
)


@dataclass(frozen=True)
class IngestionContext:
    """Explicit artifact-envelope and relation inputs for normalization."""

    request_ref: Mapping[str, object]
    run_id: str
    created_at: str
    producer_name: str = "trip-decider-wu2"
    producer_version: str = "0.1.0"


@dataclass(frozen=True)
class RunSummary:
    """Measured outputs from one offline replay run."""

    run_id: str
    output_root: Path
    candidate_artifact_path: Path
    evidence_artifact_path: Path
    metadata_path: Path
    candidate_count: int
    evidence_fact_count: int
    network_attempt_count: int


def stable_identifier(prefix: str, namespace: str, seed: str) -> str:
    """Return the frozen SHA256-derived UUID-shaped identifier."""

    if not prefix or not namespace or not seed:
        raise ValueError("identifier inputs must be non-empty")
    digest = bytearray(
        hashlib.sha256(f"{namespace}\0{seed}".encode("utf-8")).digest()[:16]
    )
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return f"{prefix}_{uuid.UUID(bytes=bytes(digest))}"


def stable_artifact_id(artifact_type: str, payload_hash: str) -> str:
    value = stable_identifier(
        "artifact",
        "trip-decider:wu2:artifact",
        f"{artifact_type}|{payload_hash}",
    )
    return f"urn:uuid:{value.removeprefix('artifact_')}"


def safe_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


_PROBLEM_MESSAGES = {
    "INGESTION_INPUT_INVALID": "External snapshot structure is invalid.",
    "INGESTION_PROVIDER_MISSING": "External snapshot provider is required.",
    "INGESTION_CRS_MISSING": "External snapshot CRS is required.",
    "INGESTION_CRS_UNSUPPORTED": "External snapshot CRS is not supported.",
    "INGESTION_POLICY_INVALID": "External snapshot replay policy is invalid.",
    "INGESTION_RESPONSE_EMPTY": "External snapshot response is empty.",
    "INGESTION_PROVIDER_ERROR": "External provider reported an error.",
    "INGESTION_RECORD_INVALID": "External provider record is invalid.",
    "INGESTION_ROUTE_COUNT_INVALID": "Route response must contain exactly one route.",
    "INGESTION_DURATION_INVALID": "Route duration must be a finite non-negative number.",
}


def problem(
    code: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual: object = None,
    artifact_path: str = "",
) -> ValidationProblem:
    if code not in INGESTION_PROBLEM_CODES:
        raise ValueError("unknown WU2 ingestion problem code")
    return ValidationProblem(
        error_code=code,
        artifact_path=artifact_path,
        json_pointer=pointer,
        schema_rule=rule,
        expected=expected,
        actual_type=safe_type(actual),
        message=_PROBLEM_MESSAGES[code],
    )


def exact_open_policy(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    expected_keys = {
        "source_class",
        "capture_mode",
        "storage_policy",
        "replay_allowed",
        "fixture_allowed",
        "policy_checked_at",
        "terms_url",
        "authorization_ref",
        "license",
    }
    if set(value) != expected_keys:
        return False
    license_value = value.get("license")
    if not isinstance(license_value, Mapping):
        return False
    return (
        value.get("source_class") == "open_data"
        and value.get("capture_mode") == "persistent_anchor"
        and value.get("storage_policy") == "persistent_allowed"
        and value.get("replay_allowed") is True
        and value.get("fixture_allowed") is True
        and isinstance(value.get("policy_checked_at"), str)
        and bool(value.get("policy_checked_at"))
        and value.get("terms_url") == "https://www.openstreetmap.org/copyright"
        and value.get("authorization_ref") is None
        and set(license_value) == {"identifier", "url", "attribution"}
        and license_value.get("identifier") == "ODbL-1.0"
        and license_value.get("url")
        == "https://opendatacommons.org/licenses/odbl/1-0/"
        and license_value.get("attribution") == "© OpenStreetMap contributors"
    )


def canonical_snapshot_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def artifact_envelope(
    artifact_type: str,
    payload: dict[str, object],
    context: IngestionContext,
    snapshots: Sequence[object],
) -> dict[str, object]:
    payload_hash = canonical_payload_sha256(payload)
    input_hashes = [
        {
            "name": f"external-snapshot-{index + 1}",
            "sha256": canonical_snapshot_sha256(snapshot),
        }
        for index, snapshot in enumerate(snapshots)
    ]
    return {
        "schema_version": "0.1.0",
        "artifact_id": stable_artifact_id(artifact_type, payload_hash),
        "artifact_type": artifact_type,
        "created_at": context.created_at,
        "producer": {
            "name": context.producer_name,
            "version": context.producer_version,
            "run_id": context.run_id,
        },
        "provenance": {
            "parent_artifact_ids": [],
            "input_hashes": input_hashes,
            "pipeline_stage": "wu2-open-data-ingestion",
        },
        "integrity": {
            "payload_sha256": payload_hash,
            "canonicalization": "canonical-json-v1",
        },
        "payload": payload,
    }
