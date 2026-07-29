"""Structured live-place resolution for WU7 Stage A.

Stage A accepts only injected, handwritten synthetic provider responses.  It
does not read credentials, open sockets, call a provider, or establish that
real provider data may be stored.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import tempfile
import unicodedata
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

import yaml

from trip_decider.acquisition_evidence import (
    AttemptObservation,
    CleanupItemObservation,
    ResponsePhaseObservation,
    RunnerObservation,
    run_failure_evidenced_acquisition,
)
from trip_decider.adapters.contracts import (
    safe_type,
    stable_artifact_id,
    stable_identifier,
)
from trip_decider.schema_validation import (
    BundleClosure,
    LoadedDocument,
    ValidationProblem,
    ValidationResult,
    canonical_payload_sha256,
    load_document,
    validate_artifact,
    validate_bundle,
    validate_schema_registry,
)


AMAP_PERSISTENCE_POLICY_STATUS = "AMAP_PERSISTENCE_POLICY_UNRESOLVED"
LIVE_SMOKE_STATUS = (
    "LIVE_SMOKE_NOT_AUTHORIZED_STORAGE_POLICY_UNRESOLVED"
)

_PROBLEM_MESSAGES = {
    "LIVE_PLACE_CONTRACT_INVALID": (
        "Generated Stage A artifacts violate a frozen contract."
    ),
    "LIVE_PLACE_INPUT_INVALID": (
        "Structured live-place input is invalid."
    ),
    "LIVE_PLACE_OUTPUT_HASH_MISMATCH": (
        "Installed Stage A bytes differ from prepared bytes."
    ),
    "LIVE_PLACE_OUTPUT_ROOT_INVALID": (
        "Output root must be missing under an existing regular parent."
    ),
    "LIVE_PLACE_PROVIDER_FAILURE": (
        "Injected synthetic provider execution failed."
    ),
    "LIVE_PLACE_PROVIDER_RESPONSE_INVALID": (
        "Injected synthetic provider response is invalid."
    ),
    "LIVE_PLACE_REPLAY_INVALID": (
        "Synthetic normalized snapshot is invalid."
    ),
    "LIVE_PLACE_SELECTION_INVALID": (
        "Interactive selection is not an offered Candidate ID or zero."
    ),
}
_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"
_PLANNING_FILENAMES = (
    "request.yaml",
    "constraint-parse.json",
    "constraints.yaml",
)
_RESOLUTION_FILENAMES = (
    "candidates.json",
    "seed-accounting.json",
    "record-local-facts.json",
    "run-summary.json",
)
_PROVIDER_FILENAMES = (
    "manifest.json",
    "normalized-snapshot.json",
    "acquisition-evidence.json",
)
_TRANSPORT_MODES = frozenset(
    {
        "driving",
        "walking",
        "transit",
        "cycling",
        "shuttle",
        "rail",
        "other",
    }
)


class _InputIssue(ValueError):
    """Expected structured-input violation."""


class _ProviderIssue(ValueError):
    """Expected synthetic-provider response violation."""


class _SelectionIssue(ValueError):
    """Expected explicit-selection violation."""


class _ContractIssue(ValueError):
    """Expected generated-artifact contract violation."""


@dataclass(frozen=True)
class StructuredTripInput:
    """Explicit structured user fields; no natural-language inference."""

    city: str
    start_at: str
    end_at: str
    input_recorded_at: str
    party_count: int
    transport_modes: tuple[str, ...]
    must_visit: tuple[str, ...]
    excluded: tuple[str, ...] = ()
    city_adcode: str | None = None
    locale: str = "zh-CN"
    interactive: bool = False


@dataclass(frozen=True)
class SyntheticProviderRequest:
    """De-keyed request descriptor passed to an injected fake transport."""

    operation: str
    endpoint_path: str
    parameters: Mapping[str, object]
    synthetic_test_data: bool = True


class SyntheticTransport(Protocol):
    """Injected Stage A boundary; implementations must not use the network."""

    def __call__(
        self,
        request: SyntheticProviderRequest,
    ) -> Mapping[str, object]:
        ...


SelectionReader = Callable[[str, tuple[tuple[str, str], ...]], str]


@dataclass(frozen=True)
class LivePlaceResolutionSummary:
    """Auditable paths and measured counts for one synthetic Stage A run."""

    run_id: str
    output_root: Path
    planning_input_root: Path
    provider_observation_root: Path
    resolution_root: Path
    selection_path: Path
    run_summary_path: Path
    candidate_count: int
    seed_status_counts: Mapping[str, int]
    synthetic_transport_calls: int
    network_attempts: int
    llm_calls: int
    synthetic_test_data: bool
    generation_allowed: bool
    output_sha256: Mapping[str, str]


class AmapObservationMode(str, Enum):
    """Closed provenance modes accepted by the shared AMap parser contract."""

    SYNTHETIC_TEST = "synthetic_test"
    EPHEMERAL_LIVE = "ephemeral_live"


@dataclass(frozen=True)
class ParsedAmapDistrict:
    """Controlled district identity parsed from an AMap-shaped response."""

    name: str
    adcode: str
    level: str


@dataclass(frozen=True)
class ParsedAmapPoi:
    """Controlled POI fields parsed without policy or persistence decisions."""

    record_id: str
    name: str
    location: str
    category_label: str
    category_code: str
    address: str | None
    province_name: str | None
    city_name: str | None
    district_name: str | None
    province_code: str | None
    city_code: str | None
    district_code: str | None


@dataclass(frozen=True)
class ParsedAmapDistrictResponse:
    """Immutable district response value before observation-policy binding."""

    status: str
    infocode: str
    synthetic_test_data: bool | None
    districts: tuple[ParsedAmapDistrict, ...]


@dataclass(frozen=True)
class ParsedAmapPoiResponse:
    """Immutable POI response value before observation-policy binding."""

    status: str
    infocode: str
    synthetic_test_data: bool | None
    count: str | None
    pois: tuple[ParsedAmapPoi, ...]


@dataclass(frozen=True, init=False)
class PolicyBoundAmapObservation:
    """Sealed policy binding produced only by the public binding function."""

    mode: AmapObservationMode
    response: ParsedAmapDistrictResponse | ParsedAmapPoiResponse
    data_policy: Mapping[str, object]
    locator_prefix: str
    persistence_capability: str
    provenance_label: str


@dataclass(frozen=True)
class AmapCandidateProjection:
    """In-memory shared Candidate projection without persistence methods."""

    mode: AmapObservationMode
    candidates: tuple[Mapping[str, object], ...]
    record_local_facts: tuple[Mapping[str, object], ...]
    seed_matches: tuple[Mapping[str, object], ...]
    selections: tuple[Mapping[str, object], ...]
    selection_choices: Mapping[str, str]


def parse_amap_district_response(
    response: bytes | Mapping[str, object],
) -> ValidationResult[ParsedAmapDistrictResponse]:
    """Parse a decoded or UTF-8 JSON AMap-shaped district response."""

    raise NotImplementedError


def parse_amap_poi_response(
    response: bytes | Mapping[str, object],
) -> ValidationResult[ParsedAmapPoiResponse]:
    """Parse a decoded or UTF-8 JSON AMap-shaped POI response."""

    raise NotImplementedError


def bind_amap_observation_policy(
    parsed: ParsedAmapDistrictResponse | ParsedAmapPoiResponse,
    *,
    mode: AmapObservationMode,
    policy_checked_at: str,
) -> ValidationResult[PolicyBoundAmapObservation]:
    """Bind one parsed response to an explicit closed observation mode."""

    raise NotImplementedError


def project_amap_candidates(
    *,
    city: str,
    city_adcode: str | None,
    seeds: Sequence[str],
    district_observation: PolicyBoundAmapObservation,
    poi_observations: Sequence[tuple[str, PolicyBoundAmapObservation]],
    selection_reader: SelectionReader | None = None,
    selection_choices: Mapping[str, str] | None = None,
) -> ValidationResult[AmapCandidateProjection]:
    """Project policy-bound observations through the shared identity core."""

    raise NotImplementedError


@dataclass(frozen=True)
class _PreparedRun:
    run_id: str
    structured_input: StructuredTripInput
    requests: tuple[SyntheticProviderRequest, ...]
    responses: tuple[Mapping[str, object], ...]
    selection_choices: Mapping[str, str]


def _problem(
    code: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual: object = None,
    artifact_path: str = "",
) -> ValidationProblem:
    if code not in _PROBLEM_MESSAGES:
        raise ValueError("unknown WU7 problem code")
    return ValidationProblem(
        error_code=code,
        artifact_path=artifact_path,
        json_pointer=pointer,
        schema_rule=rule,
        expected=expected,
        actual_type=safe_type(actual),
        message=_PROBLEM_MESSAGES[code],
    )


def _failure(
    code: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual: object = None,
    artifact_path: str = "",
) -> ValidationResult[LivePlaceResolutionSummary]:
    return ValidationResult(
        None,
        (
            _problem(
                code,
                pointer,
                rule,
                expected=expected,
                actual=actual,
                artifact_path=artifact_path,
            ),
        ),
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _yaml_bytes(value: object) -> bytes:
    return yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
    ).encode("utf-8")


def _normalized_text(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def _date_time(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise _InputIssue("date-time must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _InputIssue("date-time is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _InputIssue("date-time requires an explicit offset")
    return parsed


def _validate_input(value: object) -> StructuredTripInput:
    if not isinstance(value, StructuredTripInput):
        raise _InputIssue("input type is invalid")
    if (
        not isinstance(value.city, str)
        or not value.city.strip()
        or (
            value.city_adcode is not None
            and (
                not isinstance(value.city_adcode, str)
                or not value.city_adcode.strip()
            )
        )
        or type(value.party_count) is not int
        or value.party_count < 1
        or type(value.interactive) is not bool
        or not isinstance(value.locale, str)
        or not value.locale
    ):
        raise _InputIssue("scalar structured input is invalid")
    start = _date_time(value.start_at)
    end = _date_time(value.end_at)
    _date_time(value.input_recorded_at)
    if start >= end:
        raise _InputIssue("travel window is not increasing")
    if (
        type(value.transport_modes) is not tuple
        or not value.transport_modes
        or len(set(value.transport_modes)) != len(value.transport_modes)
        or any(item not in _TRANSPORT_MODES for item in value.transport_modes)
    ):
        raise _InputIssue("transport modes are invalid")
    if (
        type(value.must_visit) is not tuple
        or not value.must_visit
        or type(value.excluded) is not tuple
        or any(
            not isinstance(item, str) or not item.strip()
            for item in value.must_visit + value.excluded
        )
    ):
        raise _InputIssue("place seeds are invalid")
    seeds = _unique_seeds(value.must_visit + value.excluded)
    if len(seeds) > 8:
        raise _InputIssue("unique place seed limit exceeded")
    return value


def _unique_seeds(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _normalized_text(value)
        if normalized not in seen:
            seen.add(normalized)
            result.append(value.strip())
    return tuple(result)


def _artifact_ref(document: Mapping[str, object]) -> dict[str, object]:
    integrity = document["integrity"]
    if not isinstance(integrity, Mapping):
        raise _ContractIssue("artifact integrity is invalid")
    return {
        "artifact_id": document["artifact_id"],
        "artifact_type": document["artifact_type"],
        "schema_version": document["schema_version"],
        "payload_sha256": integrity["payload_sha256"],
    }


def _envelope(
    artifact_type: str,
    payload: dict[str, object],
    *,
    run_id: str,
    created_at: str,
    parent_artifact_ids: Sequence[str] = (),
    input_hashes: Sequence[Mapping[str, str]] = (),
    stage: str,
) -> dict[str, object]:
    payload_hash = canonical_payload_sha256(payload)
    return {
        "schema_version": "0.1.0",
        "artifact_id": stable_artifact_id(artifact_type, payload_hash),
        "artifact_type": artifact_type,
        "created_at": created_at,
        "producer": {
            "name": "trip-decider-live-place-resolution",
            "version": "0.1.0",
            "run_id": run_id,
        },
        "provenance": {
            "parent_artifact_ids": list(parent_artifact_ids),
            "input_hashes": [dict(item) for item in input_hashes],
            "pipeline_stage": stage,
        },
        "integrity": {
            "payload_sha256": payload_hash,
            "canonicalization": "canonical-json-v1",
        },
        "payload": payload,
    }


def _planning_documents(
    value: StructuredTripInput,
    run_id: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    input_locator = {
        "kind": "user_input",
        "value": "wu7-structured-cli:explicit-fields",
    }
    request_id = stable_identifier(
        "request",
        "trip-decider:wu7:request",
        "|".join(
            (
                value.city,
                value.start_at,
                value.end_at,
                str(value.party_count),
                ",".join(value.transport_modes),
                "\0".join(value.must_visit),
                "\0".join(value.excluded),
                value.locale,
            )
        ),
    )
    request_payload: dict[str, object] = {
        "request_id": request_id,
        "natural_language": (
            "Structured CLI input: "
            f"city={value.city}; start={value.start_at}; "
            f"end={value.end_at}; party={value.party_count}."
        ),
        "explicit": {
            "origin": {
                "kind": "user_input",
                "value": "wu7-structured-cli:origin-not-supplied",
            },
            "travel_window": {
                "start": value.start_at,
                "end": value.end_at,
                "timezone": "Asia/Shanghai",
            },
            "party": {"count": value.party_count},
            "transport_modes": list(value.transport_modes),
            "destination": {
                "selection_mode": "fixed",
                "name": value.city,
            },
            "preferences_raw": [
                "Structured CLI input; no natural-language inference or travel defaults."
            ],
            "must_visit": list(value.must_visit),
            "excluded": list(value.excluded),
            "locale": value.locale,
        },
        "user_input_refs": [input_locator],
    }
    request = _envelope(
        "request",
        request_payload,
        run_id=run_id,
        created_at=value.input_recorded_at,
        stage="wu7-structured-request",
    )
    request_ref = _artifact_ref(request)

    constraint_specs: list[tuple[str, str, object, str | None, str]] = [
        (
            "time_window",
            "within",
            f"{value.start_at}/{value.end_at}",
            None,
            "travel_window",
        ),
        (
            "must_visit",
            "include",
            list(value.must_visit),
            None,
            "must_visit",
        ),
    ]
    if value.excluded:
        constraint_specs.append(
            ("excluded", "exclude", list(value.excluded), None, "excluded")
        )

    parsed: list[dict[str, object]] = []
    constraints: list[dict[str, object]] = []
    for index, (category, operator, item_value, unit, scope) in enumerate(
        constraint_specs,
        start=1,
    ):
        seed = (
            f"{request_id}|{index}|{category}|{operator}|"
            f"{canonical_payload_sha256(item_value)}"
        )
        constraint_id = stable_identifier(
            "constraint",
            "trip-decider:wu7:constraint",
            seed,
        )
        parse_item_id = stable_identifier(
            "parse_item",
            "trip-decider:wu7:parse-item",
            seed,
        )
        quote = (
            item_value
            if isinstance(item_value, str)
            else json.dumps(item_value, ensure_ascii=False, separators=(",", ":"))
        )
        parsed.append(
            {
                "parse_item_id": parse_item_id,
                "constraint_id": constraint_id,
                "user_quote": quote,
                "user_quote_locator": input_locator,
                "origin_kind": "explicit",
                "category": category,
                "layer": "hard",
                "normalized_expression": {
                    "operator": operator,
                    "value": copy.deepcopy(item_value),
                    "unit": unit,
                },
                "explanation": (
                    "Copied from an explicit structured field without inference."
                ),
                "needs_confirmation": False,
            }
        )
        constraints.append(
            {
                "constraint_id": constraint_id,
                "layer": "hard",
                "category": category,
                "operator": operator,
                "target_refs": [
                    {
                        "target_type": "request_scope",
                        "request_id": request_id,
                        "scope_kind": scope,
                    }
                ],
                "value": copy.deepcopy(item_value),
                "unit": unit,
                "origin": {
                    "kind": "explicit",
                    "refs": [
                        {
                            "parse_item_id": parse_item_id,
                            "locator": input_locator,
                        }
                    ],
                },
                "enabled": True,
            }
        )

    parse_payload: dict[str, object] = {
        "request_id": request_id,
        "request_ref": request_ref,
        "parser": {
            "name": "wu7-structured-input-compiler",
            "version": "0.1.0",
            "kind": "user_structured",
        },
        "parsed_constraints": parsed,
        "parse_notes": [
            "Only explicit structured fields were compiled; no LLM or default travel constraint was used."
        ],
        "needs_confirmation": False,
    }
    parse = _envelope(
        "constraint-parse",
        parse_payload,
        run_id=run_id,
        created_at=value.input_recorded_at,
        parent_artifact_ids=(str(request["artifact_id"]),),
        stage="wu7-structured-constraint-parse",
    )
    parse_ref = _artifact_ref(parse)
    constraints_payload: dict[str, object] = {
        "constraint_set_id": stable_identifier(
            "constraint_set",
            "trip-decider:wu7:constraint-set",
            request_id,
        ),
        "request_ref": request_ref,
        "parse_ref": parse_ref,
        "revision": 1,
        "constraints": constraints,
        "user_edit_policy": {
            "constraints_are_solver_ssot": True,
            "request_auto_overwrite": False,
        },
    }
    constraint_document = _envelope(
        "constraints",
        constraints_payload,
        run_id=run_id,
        created_at=value.input_recorded_at,
        parent_artifact_ids=(
            str(request["artifact_id"]),
            str(parse["artifact_id"]),
        ),
        stage="wu7-structured-constraints",
    )
    return request, parse, constraint_document


def _request_descriptors(
    value: StructuredTripInput,
) -> tuple[SyntheticProviderRequest, ...]:
    requests = [
        SyntheticProviderRequest(
            operation="district",
            endpoint_path="/v3/config/district",
            parameters={
                "keywords": value.city,
                "subdistrict": 0,
                "page": 1,
                "offset": 20,
                "extensions": "base",
                "output": "JSON",
            },
        )
    ]
    for seed in _unique_seeds(value.must_visit + value.excluded):
        requests.append(
            SyntheticProviderRequest(
                operation="place_text",
                endpoint_path="/v5/place/text",
                parameters={
                    "keywords": seed,
                    "region": value.city_adcode or value.city,
                    "city_limit": True,
                    "langCode": "zh",
                    "page_size": 25,
                    "page_num": 1,
                    "output": "json",
                },
            )
        )
    return tuple(requests)


def _descriptor_document(
    request: SyntheticProviderRequest,
) -> dict[str, object]:
    return {
        "synthetic_test_data": request.synthetic_test_data,
        "operation": request.operation,
        "endpoint_path": request.endpoint_path,
        "parameters": dict(request.parameters),
    }


def _acquire_synthetic(
    *,
    value: StructuredTripInput,
    run_id: str,
    requests: tuple[SyntheticProviderRequest, ...],
    transport: SyntheticTransport,
    failure_root: Path,
) -> tuple[
    tuple[Mapping[str, object], ...] | None,
    Mapping[str, object],
]:
    descriptor_bytes = _json_bytes(
        {
            "synthetic_test_data": True,
            "requests": [_descriptor_document(item) for item in requests],
        }
    )
    captured: list[Mapping[str, object]] = []
    request_hash = _sha256(descriptor_bytes)

    def runner(_: bytes) -> RunnerObservation:
        for request in requests:
            response = transport(request)
            if not isinstance(response, Mapping):
                raise _ProviderIssue("synthetic transport result is not an object")
            captured.append(copy.deepcopy(dict(response)))
        response_bytes = _json_bytes(captured)
        response_status = "accepted"
        failure_kind = None
        try:
            _validate_provider_responses(
                value,
                requests,
                captured,
            )
        except _ProviderIssue:
            response_status = "rejected"
            failure_kind = "synthetic_provider_response_invalid"
        return RunnerObservation(
            attempts=(
                AttemptObservation(
                    attempt_id="attempt-0001",
                    request_sha256=request_hash,
                    started_at=value.input_recorded_at,
                    completed_at=value.input_recorded_at,
                    status="succeeded",
                    http_status=200,
                    response_bytes=len(response_bytes),
                    response_sha256=_sha256(response_bytes),
                    content_type="application/json",
                    retry_decision="not_applicable",
                ),
            ),
            retries=(),
            response_phase=ResponsePhaseObservation(
                status=response_status,
                failure_kind=failure_kind,
            ),
        )

    def cleanup() -> tuple[CleanupItemObservation, ...]:
        return (
            CleanupItemObservation(
                resource_kind="synthetic_transport_temporary_file",
                existed_before=False,
                deletion_attempted=False,
                status="not_present",
                residue_count=0,
            ),
        )

    failure_root.mkdir()
    evidence_path = failure_root / "acquisition-evidence.json"
    emergency_path = (
        Path(tempfile.gettempdir())
        / f"trip-decider-wu7-fer-{run_id}.json"
    )
    evidence = run_failure_evidenced_acquisition(
        run_id=run_id,
        purpose="wu7-synthetic-live-place-resolution",
        request_bytes=descriptor_bytes,
        primary_path=evidence_path,
        emergency_path=emergency_path,
        runner=runner,
        cleanup=cleanup,
        clock=lambda: value.input_recorded_at,
    )
    if evidence.document.get("status") != "succeeded":
        return None, evidence.document
    return tuple(captured), evidence.document


def _require_synthetic_response(
    response: Mapping[str, object],
) -> None:
    if (
        response.get("synthetic_test_data") is not True
        or response.get("status") != "1"
        or response.get("infocode") != "10000"
    ):
        raise _ProviderIssue("synthetic response status is invalid")


def _resolve_city(
    value: StructuredTripInput,
    response: Mapping[str, object],
) -> str:
    _require_synthetic_response(response)
    districts = response.get("districts")
    if not isinstance(districts, list):
        raise _ProviderIssue("district collection is invalid")
    matches: list[str] = []
    for item in districts:
        if not isinstance(item, Mapping):
            raise _ProviderIssue("district item is invalid")
        name = item.get("name")
        adcode = item.get("adcode")
        level = item.get("level")
        if not all(isinstance(field, str) and field for field in (name, adcode, level)):
            raise _ProviderIssue("district identity is invalid")
        name_matches = _normalized_text(name) == _normalized_text(value.city)
        adcode_matches = (
            value.city_adcode is None or adcode == value.city_adcode
        )
        if name_matches and adcode_matches:
            matches.append(adcode)
    if len(matches) != 1:
        raise _ProviderIssue("district identity is not unique")
    return matches[0]


def _synthetic_policy(created_at: str) -> dict[str, object]:
    return {
        "source_class": "synthetic",
        "capture_mode": "persistent_anchor",
        "storage_policy": "persistent_allowed",
        "replay_allowed": True,
        "fixture_allowed": True,
        "policy_checked_at": created_at,
        "terms_url": None,
        "authorization_ref": None,
        "license": None,
    }


def _coordinates(value: object) -> tuple[float, float]:
    if not isinstance(value, str):
        raise _ProviderIssue("POI location is not a string")
    parts = value.split(",")
    if len(parts) != 2:
        raise _ProviderIssue("POI location shape is invalid")
    try:
        longitude = float(parts[0])
        latitude = float(parts[1])
    except ValueError as error:
        raise _ProviderIssue("POI location is not numeric") from error
    if (
        not math.isfinite(longitude)
        or not math.isfinite(latitude)
        or not -180 <= longitude <= 180
        or not -90 <= latitude <= 90
    ):
        raise _ProviderIssue("POI location is out of range")
    return longitude, latitude


def _candidate_from_poi(
    poi: Mapping[str, object],
    seed: str,
    created_at: str,
) -> tuple[dict[str, object], dict[str, object]]:
    record_id = poi.get("id")
    name = poi.get("name")
    type_value = poi.get("type")
    typecode = poi.get("typecode")
    if not all(
        isinstance(item, str) and item
        for item in (record_id, name, type_value, typecode)
    ):
        raise _ProviderIssue("POI identity or category is invalid")
    longitude, latitude = _coordinates(poi.get("location"))
    candidate_id = stable_identifier(
        "candidate",
        "trip-decider:wu7:amap-poi",
        f"amap|poi|{record_id}",
    )
    source = {
        "kind": "provider_item",
        "value": f"synthetic-amap:poi:{record_id}",
    }
    categories = [{"code": typecode, "label": type_value}]
    location = {
        "kind": "coordinates",
        "latitude": latitude,
        "longitude": longitude,
        "crs": "GCJ-02",
        "source_refs": [source],
    }
    candidate = {
        "candidate_id": candidate_id,
        "candidate_kind": "poi",
        "label": seed,
        "parent_candidate_id": None,
        "location": location,
        "provider": {
            "name": "amap",
            "record_id": record_id,
            "record_type": "poi",
            "categories": categories,
            "external_status": {"kind": "not_reported"},
            "data_policy": _synthetic_policy(created_at),
        },
        "source_refs": [source],
        "evidence_fact_refs": [],
        "generation_reason": (
            "Exact-name synthetic provider alternative; no ranking or recommendation."
        ),
    }
    fact = {
        "candidate_id": candidate_id,
        "provider_name": "amap",
        "provider_record_type": "poi",
        "provider_record_id": record_id,
        "categories": categories,
        "location": copy.deepcopy(location),
        "source_refs": [source],
    }
    return candidate, fact


def _validate_provider_responses(
    value: StructuredTripInput,
    requests: Sequence[SyntheticProviderRequest],
    responses: Sequence[Mapping[str, object]],
) -> None:
    if len(requests) != len(responses) or not responses:
        raise _ProviderIssue("response cardinality is invalid")
    _resolve_city(value, responses[0])
    for request, response in zip(
        requests[1:],
        responses[1:],
        strict=True,
    ):
        _require_synthetic_response(response)
        pois = response.get("pois")
        if not isinstance(pois, list):
            raise _ProviderIssue("POI collection is invalid")
        seed = str(request.parameters["keywords"])
        for item in pois:
            if not isinstance(item, Mapping):
                raise _ProviderIssue("POI item is invalid")
            name = item.get("name")
            if not isinstance(name, str) or not name:
                raise _ProviderIssue("POI name is invalid")
            if _normalized_text(name) == _normalized_text(seed):
                _candidate_from_poi(
                    item,
                    seed,
                    value.input_recorded_at,
                )


def _resolution_documents(
    *,
    value: StructuredTripInput,
    run_id: str,
    request_document: Mapping[str, object],
    seed_responses: Sequence[tuple[str, Mapping[str, object]]],
    selection_reader: SelectionReader | None,
    replay_choices: Mapping[str, str],
    snapshot_sha256: str,
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, str],
]:
    candidates_by_id: dict[str, dict[str, object]] = {}
    facts_by_id: dict[str, dict[str, object]] = {}
    alternatives_by_seed: list[tuple[str, tuple[str, ...]]] = []
    for seed, response in seed_responses:
        _require_synthetic_response(response)
        pois = response.get("pois")
        if not isinstance(pois, list):
            raise _ProviderIssue("POI collection is invalid")
        alternatives: list[str] = []
        for item in pois:
            if not isinstance(item, Mapping):
                raise _ProviderIssue("POI item is invalid")
            name = item.get("name")
            if not isinstance(name, str) or not name:
                raise _ProviderIssue("POI name is invalid")
            if _normalized_text(name) != _normalized_text(seed):
                continue
            candidate, fact = _candidate_from_poi(
                item,
                seed,
                value.input_recorded_at,
            )
            candidate_id = str(candidate["candidate_id"])
            previous = candidates_by_id.get(candidate_id)
            if previous is not None and previous != candidate:
                raise _ProviderIssue("provider identity content is inconsistent")
            candidates_by_id[candidate_id] = candidate
            facts_by_id[candidate_id] = fact
            alternatives.append(candidate_id)
        alternatives_by_seed.append(
            (seed, tuple(sorted(set(alternatives))))
        )

    candidates = [
        candidates_by_id[candidate_id]
        for candidate_id in sorted(candidates_by_id)
    ]
    candidate_payload: dict[str, object] = {
        "candidate_set_id": stable_identifier(
            "candidate_set",
            "trip-decider:wu7:candidate-set",
            f"{run_id}|{snapshot_sha256}",
        ),
        "request_ref": _artifact_ref(request_document),
        "generation_stage": "poi_discovery",
        "candidates": candidates,
        "rejected_inputs": [],
    }
    candidate_document = _envelope(
        "candidates",
        candidate_payload,
        run_id=run_id,
        created_at=value.input_recorded_at,
        parent_artifact_ids=(str(request_document["artifact_id"]),),
        input_hashes=(
            {
                "name": "synthetic-normalized-snapshot",
                "sha256": snapshot_sha256,
            },
        ),
        stage="wu7-synthetic-place-resolution",
    )

    selection_records: list[dict[str, object]] = []
    seed_matches: list[dict[str, object]] = []
    choices: dict[str, str] = {}
    for seed, refs in alternatives_by_seed:
        selected: str | None = None
        source = "not_applicable"
        if len(refs) > 1:
            source = "non_interactive_none"
            if seed in replay_choices:
                selected = replay_choices[seed]
                source = "user_explicit"
            elif value.interactive and selection_reader is not None:
                offered = tuple(
                    (candidate_id, str(candidates_by_id[candidate_id]["label"]))
                    for candidate_id in refs
                )
                answer = selection_reader(seed, offered)
                if answer == "0":
                    source = "user_explicit_none"
                elif answer in refs:
                    selected = answer
                    source = "user_explicit"
                else:
                    raise _SelectionIssue("selection is not an offered Candidate ID")
            if selected is not None:
                choices[seed] = selected
                status = "matched"
                accounted_refs = [selected]
            else:
                status = "ambiguous"
                accounted_refs = list(refs)
        elif len(refs) == 1:
            status = "matched"
            accounted_refs = list(refs)
        else:
            status = "unmatched"
            accounted_refs = []
        seed_matches.append(
            {
                "seed": seed,
                "status": status,
                "candidate_refs": accounted_refs,
            }
        )
        selection_records.append(
            {
                "seed": seed,
                "alternatives": list(refs),
                "selected_candidate_ref": selected,
                "selection_source": source,
            }
        )

    seed_document = {
        "schema_version": "wu2r-downstream-seed-accounting/1.0",
        "run_id": run_id,
        "seed_matches": seed_matches,
    }
    facts_document = {
        "schema_version": "wu2r-downstream-record-local-facts/1.0",
        "run_id": run_id,
        "record_local_facts": [
            facts_by_id[candidate_id]
            for candidate_id in sorted(facts_by_id)
        ],
    }
    candidate_bytes = _json_bytes(candidate_document)
    seed_bytes = _json_bytes(seed_document)
    facts_bytes = _json_bytes(facts_document)
    status_counts = {
        status: sum(item["status"] == status for item in seed_matches)
        for status in ("matched", "ambiguous", "unmatched")
    }
    declared_hashes = {
        "candidates.json": _sha256(candidate_bytes),
        "seed-accounting.json": _sha256(seed_bytes),
        "record-local-facts.json": _sha256(facts_bytes),
    }
    resolution_summary = {
        "schema_version": "wu2r-downstream-recovery-run/1.0",
        "run_id": run_id,
        "input_fixture_identity": {
            "source_kind": "synthetic_test_data",
            "synthetic_test_data": True,
            "normalized_snapshot_sha256": snapshot_sha256,
        },
        "output_paths": {
            "candidate_artifact_path": "candidates.json",
            "seed_accounting_path": "seed-accounting.json",
            "record_local_facts_path": "record-local-facts.json",
            "run_summary_path": "run-summary.json",
        },
        "candidate_count": len(candidates),
        "seed_status_counts": status_counts,
        "network_attempts": 0,
        "output_sha256": declared_hashes,
        "completion_status": "completed",
    }
    selection_document = {
        "schema_version": "wu7-selection/1.0",
        "run_id": run_id,
        "synthetic_test_data": True,
        "normalization": "unicode-nfc-outer-trim-casefold",
        "selections": selection_records,
    }
    return (
        candidate_document,
        seed_document,
        facts_document,
        resolution_summary,
        selection_document,
        choices,
    )


def _validate_generated_contracts(
    planning_root: Path,
    resolution_root: Path,
) -> None:
    registry = validate_schema_registry(
        tuple(sorted(_SCHEMA_ROOT.glob("*.schema.json")))
    )
    if registry.problems or registry.value is None:
        raise _ContractIssue("schema registry is invalid")
    loaded_planning: list[LoadedDocument] = []
    for filename in _PLANNING_FILENAMES:
        loaded = load_document(planning_root / filename)
        if loaded.problems or loaded.value is None:
            raise _ContractIssue("planning artifact cannot be loaded")
        loaded_planning.append(loaded.value)
    constraints = loaded_planning[-1].data
    if not isinstance(constraints, Mapping):
        raise _ContractIssue("constraints artifact is invalid")
    closed = validate_bundle(
        tuple(loaded_planning),
        registry.value,
        closure=BundleClosure.CLOSED,
        root_artifact_id=str(constraints["artifact_id"]),
    )
    if closed.problems:
        raise _ContractIssue("planning CLOSED bundle is invalid")
    candidate = load_document(
        resolution_root / "candidates.json",
        expected_artifact_type="candidates",
    )
    if candidate.problems or candidate.value is None:
        raise _ContractIssue("Candidate artifact cannot be loaded")
    validated = validate_artifact(candidate.value, registry.value)
    if validated.problems:
        raise _ContractIssue("Candidate artifact is invalid")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _clean_stage(stage: Path) -> None:
    if not stage.exists():
        return
    if stage.parent == stage or ".staging-" not in stage.name:
        raise RuntimeError("refusing to clean an unexpected staging path")
    shutil.rmtree(stage)


def _output_root_problem(output_root: Path) -> ValidationProblem | None:
    if output_root.exists():
        return _problem(
            "LIVE_PLACE_OUTPUT_ROOT_INVALID",
            "/output_root",
            "missingDirectory",
            expected="non-existing output root",
            artifact_path=str(output_root),
        )
    if not output_root.parent.is_dir() or output_root.parent.is_symlink():
        return _problem(
            "LIVE_PLACE_OUTPUT_ROOT_INVALID",
            "/output_root",
            "parentDirectory",
            expected="existing regular parent directory",
            artifact_path=str(output_root),
        )
    return None


def _snapshot_document(
    value: StructuredTripInput,
    requests: Sequence[SyntheticProviderRequest],
    responses: Sequence[Mapping[str, object]],
    selection_choices: Mapping[str, str],
) -> dict[str, object]:
    input_value = asdict(value)
    input_value["transport_modes"] = list(value.transport_modes)
    input_value["must_visit"] = list(value.must_visit)
    input_value["excluded"] = list(value.excluded)
    return {
        "schema_version": "wu7-synthetic-normalized-snapshot/1.0",
        "synthetic_test_data": True,
        "provider_shape": "amap",
        "provider_authorization_claimed": False,
        "structured_input": input_value,
        "requests": [_descriptor_document(item) for item in requests],
        "responses": [copy.deepcopy(dict(item)) for item in responses],
        "selection_choices": dict(selection_choices),
    }


def _manifest_document(
    run_id: str,
    snapshot_bytes: bytes,
    requests: Sequence[SyntheticProviderRequest],
    responses: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": "wu7-synthetic-provider-observation/1.0",
        "run_id": run_id,
        "synthetic_test_data": True,
        "provider_shape": "amap",
        "live_evidence": False,
        "provider_authorization_claimed": False,
        "persistence_policy_status": AMAP_PERSISTENCE_POLICY_STATUS,
        "live_smoke_status": LIVE_SMOKE_STATUS,
        "request_count": len(requests),
        "request_sha256": [
            _sha256(_json_bytes(_descriptor_document(item)))
            for item in requests
        ],
        "response_sha256": [
            _sha256(_json_bytes(item)) for item in responses
        ],
        "normalized_snapshot_sha256": _sha256(snapshot_bytes),
        "network_attempts": 0,
    }


def _prepare_and_install(
    prepared: _PreparedRun,
    output_root: Path,
    *,
    selection_reader: SelectionReader | None,
    evidence_document: Mapping[str, object],
) -> ValidationResult[LivePlaceResolutionSummary]:
    failure_root = output_root.with_name(
        output_root.name + ".failure-evidence"
    )
    stage = output_root.with_name(
        f".{output_root.name}.staging-{uuid.uuid4().hex}"
    )
    try:
        stage.mkdir()
        planning_root = stage / "planning-input"
        provider_root = stage / "provider-observation"
        resolution_root = stage / "resolution"
        planning_root.mkdir()
        provider_root.mkdir()
        resolution_root.mkdir()

        request, parse, constraints = _planning_documents(
            prepared.structured_input,
            prepared.run_id,
        )
        _write(planning_root / "request.yaml", _yaml_bytes(request))
        _write(
            planning_root / "constraint-parse.json",
            _json_bytes(parse),
        )
        _write(
            planning_root / "constraints.yaml",
            _yaml_bytes(constraints),
        )

        seed_responses = tuple(
            (
                str(request_item.parameters["keywords"]),
                response,
            )
            for request_item, response in zip(
                prepared.requests[1:],
                prepared.responses[1:],
                strict=True,
            )
        )
        candidate_input_snapshot = _snapshot_document(
            prepared.structured_input,
            prepared.requests,
            prepared.responses,
            {},
        )
        candidate_input_snapshot["structured_input"]["interactive"] = False
        candidate_input_hash = _sha256(
            _json_bytes(candidate_input_snapshot)
        )
        (
            candidate,
            accounting,
            facts,
            resolution_summary,
            selection,
            selected_choices,
        ) = _resolution_documents(
            value=prepared.structured_input,
            run_id=prepared.run_id,
            request_document=request,
            seed_responses=seed_responses,
            selection_reader=selection_reader,
            replay_choices=prepared.selection_choices,
            snapshot_sha256=candidate_input_hash,
        )
        snapshot = _snapshot_document(
            prepared.structured_input,
            prepared.requests,
            prepared.responses,
            selected_choices,
        )
        snapshot_bytes = _json_bytes(snapshot)

        _write(provider_root / "normalized-snapshot.json", snapshot_bytes)
        _write(
            provider_root / "manifest.json",
            _json_bytes(
                _manifest_document(
                    prepared.run_id,
                    snapshot_bytes,
                    prepared.requests,
                    prepared.responses,
                )
            ),
        )
        _write(
            provider_root / "acquisition-evidence.json",
            _json_bytes(evidence_document),
        )
        _write(resolution_root / "candidates.json", _json_bytes(candidate))
        _write(
            resolution_root / "seed-accounting.json",
            _json_bytes(accounting),
        )
        _write(
            resolution_root / "record-local-facts.json",
            _json_bytes(facts),
        )
        _write(
            resolution_root / "run-summary.json",
            _json_bytes(resolution_summary),
        )
        _write(stage / "selection.json", _json_bytes(selection))

        _validate_generated_contracts(planning_root, resolution_root)
        output_hashes = {
            path.relative_to(stage).as_posix(): _sha256(path.read_bytes())
            for path in sorted(stage.rglob("*"))
            if path.is_file()
        }
        status_counts = dict(resolution_summary["seed_status_counts"])
        root_summary = {
            "schema_version": "wu7-live-place-resolution-run/1.0",
            "run_id": prepared.run_id,
            "status": "completed",
            "synthetic_test_data": True,
            "provider_shape": "amap",
            "implementation_status": "stage_a_complete",
            "provider_authorization_status": AMAP_PERSISTENCE_POLICY_STATUS,
            "live_smoke_status": LIVE_SMOKE_STATUS,
            "generation_allowed": False,
            "candidate_count": resolution_summary["candidate_count"],
            "seed_status_counts": status_counts,
            "synthetic_transport_calls": len(prepared.requests),
            "real_network_calls": 0,
            "real_amap_output_files": 0,
            "llm_calls": 0,
            "output_sha256": output_hashes,
        }
        _write(stage / "run-summary.json", _json_bytes(root_summary))

        os.replace(stage, output_root)
        if failure_root.exists():
            evidence_path = failure_root / "acquisition-evidence.json"
            evidence_path.unlink(missing_ok=True)
            failure_root.rmdir()
    except _SelectionIssue:
        _clean_stage(stage)
        return _failure(
            "LIVE_PLACE_SELECTION_INVALID",
            "/selection",
            "offeredCandidateOrZero",
            expected="one displayed Candidate ID or 0",
        )
    except _ProviderIssue:
        _clean_stage(stage)
        return _failure(
            "LIVE_PLACE_PROVIDER_RESPONSE_INVALID",
            "/provider_response",
            "syntheticAmapShape",
            expected="valid handwritten synthetic response",
        )
    except _ContractIssue:
        _clean_stage(stage)
        return _failure(
            "LIVE_PLACE_CONTRACT_INVALID",
            "/outputs",
            "frozenContracts",
            expected="Schema-valid planning and Candidate artifacts",
        )
    except (OSError, ValueError, TypeError):
        _clean_stage(stage)
        return _failure(
            "LIVE_PLACE_OUTPUT_ROOT_INVALID",
            "/output_root",
            "atomicInstall",
            expected="exclusive writable output root",
            artifact_path=str(output_root),
        )

    installed_hashes = {
        relative: _sha256((output_root / relative).read_bytes())
        for relative in output_hashes
    }
    if installed_hashes != output_hashes:
        return _failure(
            "LIVE_PLACE_OUTPUT_HASH_MISMATCH",
            "/outputs",
            "installedBytes",
            expected="prepared output bytes",
            artifact_path=str(output_root),
        )
    return ValidationResult(
        LivePlaceResolutionSummary(
            run_id=prepared.run_id,
            output_root=output_root,
            planning_input_root=output_root / "planning-input",
            provider_observation_root=output_root / "provider-observation",
            resolution_root=output_root / "resolution",
            selection_path=output_root / "selection.json",
            run_summary_path=output_root / "run-summary.json",
            candidate_count=int(resolution_summary["candidate_count"]),
            seed_status_counts=status_counts,
            synthetic_transport_calls=len(prepared.requests),
            network_attempts=0,
            llm_calls=0,
            synthetic_test_data=True,
            generation_allowed=False,
            output_sha256=installed_hashes,
        ),
        (),
    )


def run_synthetic_live_place_resolution(
    structured_input: StructuredTripInput,
    output_root: Path,
    transport: SyntheticTransport,
    *,
    selection_reader: SelectionReader | None = None,
) -> ValidationResult[LivePlaceResolutionSummary]:
    """Compile input and resolve places using only an injected fake transport."""

    try:
        value = _validate_input(structured_input)
        checked_output_root = Path(output_root)
    except (TypeError, _InputIssue):
        return _failure(
            "LIVE_PLACE_INPUT_INVALID",
            "/structured_input",
            "explicitStructuredFields",
            expected="valid explicit structured trip input",
        )
    if not callable(transport) or (
        selection_reader is not None and not callable(selection_reader)
    ):
        return _failure(
            "LIVE_PLACE_INPUT_INVALID",
            "/effects",
            "callable",
            expected="injected synthetic transport and optional selection reader",
        )
    root_problem = _output_root_problem(checked_output_root)
    if root_problem is not None:
        return ValidationResult(None, (root_problem,))
    failure_root = checked_output_root.with_name(
        checked_output_root.name + ".failure-evidence"
    )
    if failure_root.exists():
        return _failure(
            "LIVE_PLACE_OUTPUT_ROOT_INVALID",
            "/failure_evidence_root",
            "missingDirectory",
            expected="non-existing sibling failure-evidence root",
            artifact_path=str(failure_root),
        )

    requests = _request_descriptors(value)
    identity = _sha256(
        _json_bytes(
            {
                "structured_input": {
                    key: item
                    for key, item in asdict(value).items()
                    if key != "interactive"
                },
                "requests": [_descriptor_document(item) for item in requests],
            }
        )
    )
    run_id = stable_identifier(
        "run",
        "trip-decider:wu7:live-place-resolution",
        identity,
    )
    try:
        responses, evidence = _acquire_synthetic(
            value=value,
            run_id=run_id,
            requests=requests,
            transport=transport,
            failure_root=failure_root,
        )
    except (OSError, TypeError, ValueError):
        return _failure(
            "LIVE_PLACE_PROVIDER_FAILURE",
            "/provider",
            "failureEvidence",
            expected="secret-safe FER terminal evidence",
        )
    if responses is None:
        if (
            evidence.get("terminal_failure_code")
            == "ACQUISITION_RESPONSE_FAILURE"
        ):
            return _failure(
                "LIVE_PLACE_PROVIDER_RESPONSE_INVALID",
                "/provider_response",
                "syntheticAmapShape",
                expected="valid handwritten synthetic response",
            )
        return _failure(
            "LIVE_PLACE_PROVIDER_FAILURE",
            "/provider",
            "syntheticTransport",
            expected="successful injected synthetic provider execution",
        )
    try:
        _resolve_city(value, responses[0])
        if len(responses) != len(requests):
            raise _ProviderIssue("response cardinality is invalid")
    except _ProviderIssue:
        return _failure(
            "LIVE_PLACE_PROVIDER_RESPONSE_INVALID",
            "/provider_response",
            "syntheticAmapShape",
            expected="one district and one response per unique seed",
        )
    prepared = _PreparedRun(
        run_id=run_id,
        structured_input=value,
        requests=requests,
        responses=responses,
        selection_choices={},
    )
    return _prepare_and_install(
        prepared,
        checked_output_root,
        selection_reader=selection_reader,
        evidence_document=evidence,
    )


def _load_snapshot(
    snapshot_root: Path,
) -> tuple[
    StructuredTripInput,
    tuple[SyntheticProviderRequest, ...],
    tuple[Mapping[str, object], ...],
    Mapping[str, str],
] | None:
    if (
        not snapshot_root.is_dir()
        or snapshot_root.is_symlink()
        or {item.name for item in snapshot_root.iterdir()}
        != set(_PROVIDER_FILENAMES)
    ):
        return None
    path = snapshot_root / "normalized-snapshot.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(document, Mapping)
        or document.get("synthetic_test_data") is not True
        or document.get("provider_shape") != "amap"
        or document.get("provider_authorization_claimed") is not False
        or not isinstance(document.get("structured_input"), Mapping)
        or not isinstance(document.get("requests"), list)
        or not isinstance(document.get("responses"), list)
        or not isinstance(document.get("selection_choices"), Mapping)
    ):
        return None
    input_value = dict(document["structured_input"])
    try:
        input_value["transport_modes"] = tuple(input_value["transport_modes"])
        input_value["must_visit"] = tuple(input_value["must_visit"])
        input_value["excluded"] = tuple(input_value["excluded"])
        structured = _validate_input(StructuredTripInput(**input_value))
    except (KeyError, TypeError, _InputIssue):
        return None
    requests: list[SyntheticProviderRequest] = []
    for item in document["requests"]:
        if (
            not isinstance(item, Mapping)
            or item.get("synthetic_test_data") is not True
            or not isinstance(item.get("operation"), str)
            or not isinstance(item.get("endpoint_path"), str)
            or not isinstance(item.get("parameters"), Mapping)
        ):
            return None
        requests.append(
            SyntheticProviderRequest(
                operation=str(item["operation"]),
                endpoint_path=str(item["endpoint_path"]),
                parameters=dict(item["parameters"]),
            )
        )
    responses: list[Mapping[str, object]] = []
    for item in document["responses"]:
        if not isinstance(item, Mapping):
            return None
        responses.append(copy.deepcopy(dict(item)))
    choices = document["selection_choices"]
    if any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in choices.items()
    ):
        return None
    if tuple(requests) != _request_descriptors(structured):
        return None
    if len(requests) != len(responses):
        return None
    return structured, tuple(requests), tuple(responses), dict(choices)


def replay_synthetic_normalized_snapshot(
    snapshot_root: Path,
    output_root: Path,
) -> ValidationResult[LivePlaceResolutionSummary]:
    """Replay a Stage A synthetic snapshot without provider or network access."""

    try:
        checked_snapshot_root = Path(snapshot_root)
        checked_output_root = Path(output_root)
    except TypeError:
        return _failure(
            "LIVE_PLACE_REPLAY_INVALID",
            "/paths",
            "pathType",
            expected="Path-compatible values",
        )
    root_problem = _output_root_problem(checked_output_root)
    if root_problem is not None:
        return ValidationResult(None, (root_problem,))
    loaded = _load_snapshot(checked_snapshot_root)
    if loaded is None:
        return _failure(
            "LIVE_PLACE_REPLAY_INVALID",
            "/snapshot_root",
            "syntheticNormalizedSnapshot",
            expected="complete Stage A synthetic provider observation",
            artifact_path=str(checked_snapshot_root),
        )
    structured, requests, responses, choices = loaded
    identity = _sha256(
        _json_bytes(
            {
                "structured_input": {
                    key: item
                    for key, item in asdict(structured).items()
                    if key != "interactive"
                },
                "requests": [_descriptor_document(item) for item in requests],
            }
        )
    )
    run_id = stable_identifier(
        "run",
        "trip-decider:wu7:live-place-resolution",
        identity,
    )
    evidence_path = checked_snapshot_root / "acquisition-evidence.json"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _failure(
            "LIVE_PLACE_REPLAY_INVALID",
            "/acquisition_evidence",
            "validJson",
            expected="synthetic FER document",
            artifact_path=str(evidence_path),
        )
    if (
        not isinstance(evidence, Mapping)
        or evidence.get("run_id") != run_id
        or evidence.get("status") != "succeeded"
    ):
        return _failure(
            "LIVE_PLACE_REPLAY_INVALID",
            "/acquisition_evidence",
            "successfulSyntheticFer",
            expected="matching successful synthetic FER document",
            artifact_path=str(evidence_path),
        )
    prepared = _PreparedRun(
        run_id=run_id,
        structured_input=structured,
        requests=requests,
        responses=responses,
        selection_choices=choices,
    )
    return _prepare_and_install(
        prepared,
        checked_output_root,
        selection_reader=None,
        evidence_document=evidence,
    )


__all__ = [
    "AMAP_PERSISTENCE_POLICY_STATUS",
    "AmapCandidateProjection",
    "AmapObservationMode",
    "LIVE_SMOKE_STATUS",
    "LivePlaceResolutionSummary",
    "ParsedAmapDistrict",
    "ParsedAmapDistrictResponse",
    "ParsedAmapPoi",
    "ParsedAmapPoiResponse",
    "PolicyBoundAmapObservation",
    "SelectionReader",
    "StructuredTripInput",
    "SyntheticProviderRequest",
    "SyntheticTransport",
    "bind_amap_observation_policy",
    "parse_amap_district_response",
    "parse_amap_poi_response",
    "project_amap_candidates",
    "replay_synthetic_normalized_snapshot",
    "run_synthetic_live_place_resolution",
]
