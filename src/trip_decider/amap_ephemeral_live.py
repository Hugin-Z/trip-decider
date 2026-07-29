"""Ephemeral AMap resolution with provider-free final output.

Real provider observations exist only in memory or a random system-temporary
root.  The installed nine-file result contains explicit user input, a
conservative coarse plan, and an escaping-only report.  It is not a route,
recommendation, complete guide, or publishable itinerary.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
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
from trip_decider.coarse_planner import run_coarse_planner
from trip_decider.evidence_runtime import run_evidence_runtime
from trip_decider.live_place_resolution import (
    AmapCandidateProjection,
    AmapObservationMode,
    ParsedAmapDistrictResponse,
    ParsedAmapPoiResponse,
    PolicyBoundAmapObservation,
    StructuredTripInput,
    bind_amap_observation_policy,
    parse_amap_district_response,
    parse_amap_poi_response,
    project_amap_candidates,
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


AMAP_CREDENTIAL_MISSING = "AMAP_CREDENTIAL_MISSING"
AMAP_PROVIDER_FAILURE = "AMAP_PROVIDER_FAILURE"
AMAP_P2_CLEANUP_FAILED = "AMAP_P2_CLEANUP_FAILED"
AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED = (
    "AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED"
)
AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED = (
    "AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED"
)

_INPUT_INVALID = "AMAP_P2_INPUT_INVALID"
_OUTPUT_ROOT_INVALID = "AMAP_P2_OUTPUT_ROOT_INVALID"
_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"
_DISTRICT_ENDPOINT = "/v3/config/district"
_POI_ENDPOINT = "/v5/place/text"
_AMAP_ORIGIN = "https://restapi.amap.com"
_MAX_SEEDS = 8
_MAX_RESPONSE_BYTES = 2_000_000
_MAX_POIS = 25
_PLANNING_FILES = (
    "request.yaml",
    "constraint-parse.json",
    "constraints.yaml",
)
_RECOVERY_FILES = (
    "candidates.json",
    "seed-accounting.json",
    "record-local-facts.json",
    "run-summary.json",
)
_FINAL_FILES = (
    "planning-input/request.yaml",
    "planning-input/constraint-parse.json",
    "planning-input/constraints.yaml",
    "planning/plan.json",
    "planning/planning-gate.json",
    "planning/violations.json",
    "planning/run-summary.json",
    "report/index.html",
    "run-summary.json",
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
_PROBLEM_MESSAGES = {
    AMAP_CREDENTIAL_MISSING: (
        "The required process credential is missing; no request was sent."
    ),
    AMAP_PROVIDER_FAILURE: (
        "The provider acquisition or controlled response evaluation failed."
    ),
    AMAP_P2_CLEANUP_FAILED: (
        "Ephemeral cleanup failed; no final output was installed."
    ),
    AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED: (
        "Final output failed the provider-data redaction gate."
    ),
    AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED: (
        "The approved public parser or downstream contract could not be used."
    ),
    _INPUT_INVALID: "Structured same-run input is invalid.",
    _OUTPUT_ROOT_INVALID: (
        "Output root must be missing beneath an existing regular parent."
    ),
}
_DENIED_FINAL_KEYS = frozenset(
    {
        "address",
        "adcode",
        "categories",
        "coordinates",
        "latitude",
        "location",
        "longitude",
        "provider",
        "provider_locator",
        "record_id",
        "record_local_facts",
        "response_bytes",
        "response_sha256",
        "source_refs",
        "typecode",
    }
)


class _RunIssue(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _WireIssue(RuntimeError):
    def __init__(self, kind: str, http_status: int | None = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.http_status = http_status


@dataclass(frozen=True)
class AmapLiveRequest:
    """De-keyed request descriptor supplied to the wire transport."""

    operation: str
    endpoint_path: str
    parameters: Mapping[str, str]


class AmapLiveTransport(Protocol):
    """Injected wire closure; credential injection occurs only here."""

    def __call__(
        self,
        request: AmapLiveRequest,
        credential: str,
    ) -> bytes:
        ...


@dataclass(frozen=True)
class AmapEphemeralLiveConfig:
    """Explicit structured input plus current-run alternative selections."""

    structured_input: StructuredTripInput
    selection_ordinals: Mapping[str, int]


@dataclass(frozen=True)
class SafeSeedResult:
    """Provider-free identity and allocation result for one user seed."""

    seed: str
    identity_status: str
    explicitly_selected: bool
    day_number: int | None
    blocker: str | None


@dataclass(frozen=True)
class AmapEphemeralLiveSummary:
    """Safe summary of one completed same-run resolution."""

    output_root: Path
    planning_status: str
    publishable: bool
    generation_allowed_input: bool
    seed_results: tuple[SafeSeedResult, ...]
    scheduled_count: int
    blocked_count: int
    network_calls: int
    llm_calls: int
    cleanup_counts: Mapping[str, int]
    output_sha256: Mapping[str, str]


@dataclass
class _AcquisitionState:
    observations: list[PolicyBoundAmapObservation]
    response_hashes: set[str]
    network_calls: int = 0


@dataclass(frozen=True)
class _SafeProjection:
    plan: Mapping[str, object]
    violations: Mapping[str, object]
    gate: Mapping[str, object]
    planning_summary: Mapping[str, object]
    seed_results: tuple[SafeSeedResult, ...]
    scheduled_count: int
    blocked_count: int


def _problem(code: str) -> ValidationProblem:
    return ValidationProblem(
        error_code=code,
        artifact_path="",
        json_pointer="",
        schema_rule="sameRunBoundary",
        expected="approved WU7B-P2 contract",
        actual_type="null",
        message=_PROBLEM_MESSAGES[code],
    )


def _failure(
    code: str,
) -> ValidationResult[AmapEphemeralLiveSummary]:
    return ValidationResult(None, (_problem(code),))


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: object, *, pretty: bool = False) -> bytes:
    if pretty:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
    else:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return (text + "\n").encode("utf-8")


def _yaml_bytes(value: object) -> bytes:
    return yaml.safe_dump(
        value,
        allow_unicode=True,
        sort_keys=True,
        default_flow_style=False,
    ).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)


def _artifact_ref(document: Mapping[str, object]) -> dict[str, object]:
    integrity = document["integrity"]
    if not isinstance(integrity, Mapping):
        raise _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)
    return {
        "artifact_id": document["artifact_id"],
        "artifact_type": document["artifact_type"],
        "payload_sha256": integrity["payload_sha256"],
        "schema_version": document["schema_version"],
    }


def _artifact(
    artifact_type: str,
    payload: Mapping[str, object],
    *,
    created_at: str,
    producer: str,
    run_id: str,
    pipeline_stage: str,
    parents: Sequence[str] = (),
    input_hashes: Sequence[Mapping[str, str]] = (),
) -> dict[str, object]:
    payload_hash = canonical_payload_sha256(payload)
    return {
        "schema_version": "0.1.0",
        "artifact_id": stable_artifact_id(artifact_type, payload_hash),
        "artifact_type": artifact_type,
        "created_at": created_at,
        "producer": {
            "name": producer,
            "version": "0.1.0",
            "run_id": run_id,
        },
        "provenance": {
            "parent_artifact_ids": list(parents),
            "input_hashes": [dict(item) for item in input_hashes],
            "pipeline_stage": pipeline_stage,
        },
        "integrity": {
            "canonicalization": "canonical-json-v1",
            "payload_sha256": payload_hash,
        },
        "payload": dict(payload),
    }


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise _RunIssue(_INPUT_INVALID) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _RunIssue(_INPUT_INVALID)
    return parsed


def _checked_config(
    config: AmapEphemeralLiveConfig,
) -> tuple[StructuredTripInput, tuple[str, ...], dict[str, int]]:
    if not isinstance(config, AmapEphemeralLiveConfig):
        raise _RunIssue(_INPUT_INVALID)
    value = config.structured_input
    if not isinstance(value, StructuredTripInput):
        raise _RunIssue(_INPUT_INVALID)
    text_fields = (
        value.city,
        value.start_at,
        value.end_at,
        value.input_recorded_at,
        value.locale,
    )
    if any(not isinstance(item, str) or not item.strip() for item in text_fields):
        raise _RunIssue(_INPUT_INVALID)
    if (
        not isinstance(value.city_adcode, str)
        or not value.city_adcode
        or not value.city_adcode.isdigit()
        or type(value.party_count) is not int
        or value.party_count < 1
        or type(value.transport_modes) is not tuple
        or not value.transport_modes
        or any(item not in _TRANSPORT_MODES for item in value.transport_modes)
        or type(value.must_visit) is not tuple
        or not value.must_visit
        or type(value.excluded) is not tuple
        or any(
            not isinstance(item, str) or not item.strip()
            for item in (*value.must_visit, *value.excluded)
        )
    ):
        raise _RunIssue(_INPUT_INVALID)
    start = _parse_datetime(value.start_at)
    end = _parse_datetime(value.end_at)
    _parse_datetime(value.input_recorded_at)
    if start > end:
        raise _RunIssue(_INPUT_INVALID)
    seeds = tuple(dict.fromkeys((*value.must_visit, *value.excluded)))
    if len(seeds) > _MAX_SEEDS:
        raise _RunIssue(_INPUT_INVALID)
    selections = config.selection_ordinals
    if not isinstance(selections, Mapping) or any(
        not isinstance(seed, str)
        or seed not in seeds
        or type(ordinal) is not int
        or ordinal < 1
        for seed, ordinal in selections.items()
    ):
        raise _RunIssue(_INPUT_INVALID)
    if selections and not value.interactive:
        raise _RunIssue(_INPUT_INVALID)
    return value, seeds, dict(selections)


def _output_root_ok(output_root: Path) -> bool:
    try:
        root = Path(output_root)
        parent = root.parent
        return (
            not root.exists()
            and not root.is_symlink()
            and parent.is_dir()
            and not parent.is_symlink()
        )
    except (OSError, TypeError, ValueError):
        return False


def _planning_documents(
    value: StructuredTripInput,
    run_id: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    locator = {
        "kind": "user_input",
        "value": "wu7b-structured-live:explicit-fields",
    }
    request_id = stable_identifier(
        "request",
        "trip-decider:wu7b:request",
        _sha256(
            _json_bytes(
                {
                    "city": value.city,
                    "start_at": value.start_at,
                    "end_at": value.end_at,
                    "input_recorded_at": value.input_recorded_at,
                    "party_count": value.party_count,
                    "transport_modes": list(value.transport_modes),
                    "must_visit": list(value.must_visit),
                    "excluded": list(value.excluded),
                    "locale": value.locale,
                }
            )
        ),
    )
    request_payload = {
        "request_id": request_id,
        "natural_language": (
            "Structured explicit input; no natural-language inference, "
            "route, opening-hours, or duration claim."
        ),
        "explicit": {
            "origin": {
                "kind": "user_input",
                "value": "wu7b-structured-live:origin-not-supplied",
            },
            "destination": {
                "name": value.city,
                "selection_mode": "fixed",
            },
            "travel_window": {
                "start": value.start_at,
                "end": value.end_at,
                "timezone": "Asia/Shanghai",
            },
            "party": {"count": value.party_count},
            "transport_modes": list(value.transport_modes),
            "must_visit": list(value.must_visit),
            "excluded": list(value.excluded),
            "preferences_raw": [
                "Explicit structured input; coarse day allocation only."
            ],
            "locale": value.locale,
        },
        "user_input_refs": [dict(locator)],
    }
    request = _artifact(
        "request",
        request_payload,
        created_at=value.input_recorded_at,
        producer="trip-decider-wu7b-structured-input",
        run_id=run_id,
        pipeline_stage="wu7b-structured-request",
    )
    request_ref = _artifact_ref(request)
    date_range = (
        f"{_parse_datetime(value.start_at).date().isoformat()}/"
        f"{_parse_datetime(value.end_at).date().isoformat()}"
    )
    definitions: list[tuple[str, str, str, object, str]] = [
        (
            "time_window",
            "within",
            "travel_window",
            date_range,
            date_range,
        ),
        (
            "must_visit",
            "include",
            "must_visit",
            list(value.must_visit),
            json.dumps(
                list(value.must_visit),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ),
    ]
    if value.excluded:
        definitions.append(
            (
                "excluded",
                "exclude",
                "excluded",
                list(value.excluded),
                json.dumps(
                    list(value.excluded),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
    parsed_constraints: list[dict[str, object]] = []
    constraints_values: list[dict[str, object]] = []
    for index, (
        category,
        operator,
        scope_kind,
        normalized_value,
        quote,
    ) in enumerate(definitions, start=1):
        constraint_id = stable_identifier(
            "constraint",
            "trip-decider:wu7b:constraint",
            f"{request_id}|{index}|{category}",
        )
        parse_item_id = stable_identifier(
            "parse_item",
            "trip-decider:wu7b:parse-item",
            f"{request_id}|{index}|{category}",
        )
        parsed_constraints.append(
            {
                "parse_item_id": parse_item_id,
                "constraint_id": constraint_id,
                "user_quote": quote,
                "user_quote_locator": dict(locator),
                "category": category,
                "layer": "hard",
                "origin_kind": "explicit",
                "normalized_expression": {
                    "operator": operator,
                    "value": normalized_value,
                    "unit": None,
                },
                "explanation": (
                    "Copied from an explicit structured field without inference."
                ),
                "needs_confirmation": False,
            }
        )
        constraints_values.append(
            {
                "constraint_id": constraint_id,
                "category": category,
                "layer": "hard",
                "operator": operator,
                "value": normalized_value,
                "unit": None,
                "enabled": True,
                "origin": {
                    "kind": "explicit",
                    "refs": [
                        {
                            "parse_item_id": parse_item_id,
                            "locator": dict(locator),
                        }
                    ],
                },
                "target_refs": [
                    {
                        "target_type": "request_scope",
                        "request_id": request_id,
                        "scope_kind": scope_kind,
                    }
                ],
            }
        )
    parse_payload = {
        "request_ref": request_ref,
        "request_id": request_id,
        "parsed_constraints": parsed_constraints,
        "parser": {
            "name": "wu7b-structured-input-compiler",
            "version": "0.1.0",
            "kind": "user_structured",
        },
        "needs_confirmation": False,
        "parse_notes": [
            "Only explicit structured fields were compiled; no LLM or travel "
            "default was used."
        ],
    }
    parse = _artifact(
        "constraint-parse",
        parse_payload,
        created_at=value.input_recorded_at,
        producer="trip-decider-wu7b-structured-input",
        run_id=run_id,
        pipeline_stage="wu7b-structured-constraint-parse",
        parents=(str(request["artifact_id"]),),
    )
    constraints_payload = {
        "constraint_set_id": stable_identifier(
            "constraint_set",
            "trip-decider:wu7b:constraint-set",
            request_id,
        ),
        "request_ref": request_ref,
        "parse_ref": _artifact_ref(parse),
        "revision": 1,
        "constraints": constraints_values,
        "user_edit_policy": {
            "constraints_are_solver_ssot": True,
            "request_auto_overwrite": False,
        },
    }
    constraints = _artifact(
        "constraints",
        constraints_payload,
        created_at=value.input_recorded_at,
        producer="trip-decider-wu7b-structured-input",
        run_id=run_id,
        pipeline_stage="wu7b-structured-constraints",
        parents=(str(request["artifact_id"]), str(parse["artifact_id"])),
    )
    return request, parse, constraints


def _write_and_validate_planning(
    root: Path,
    documents: tuple[
        Mapping[str, object],
        Mapping[str, object],
        Mapping[str, object],
    ],
) -> None:
    _write(root / "request.yaml", _yaml_bytes(documents[0]))
    _write(root / "constraint-parse.json", _json_bytes(documents[1]))
    _write(root / "constraints.yaml", _yaml_bytes(documents[2]))
    registry = validate_schema_registry(
        tuple(sorted(_SCHEMA_ROOT.glob("*.schema.json")))
    )
    if registry.problems or registry.value is None:
        raise _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)
    loaded: list[LoadedDocument] = []
    for filename in _PLANNING_FILES:
        result = load_document(root / filename)
        if result.problems or result.value is None:
            raise _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)
        loaded.append(result.value)
    closed = validate_bundle(
        tuple(loaded),
        registry.value,
        closure=BundleClosure.CLOSED,
        root_artifact_id=str(documents[2]["artifact_id"]),
    )
    if closed.problems:
        raise _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)


def _requests(
    value: StructuredTripInput,
    seeds: Sequence[str],
) -> tuple[AmapLiveRequest, ...]:
    district = AmapLiveRequest(
        operation="district",
        endpoint_path=_DISTRICT_ENDPOINT,
        parameters=MappingProxyType(
            {
                "extensions": "base",
                "keywords": value.city,
                "subdistrict": "0",
            }
        ),
    )
    pois = tuple(
        AmapLiveRequest(
            operation="poi",
            endpoint_path=_POI_ENDPOINT,
            parameters=MappingProxyType(
                {
                    "city_limit": "true",
                    "keywords": seed,
                    "page_num": "1",
                    "page_size": str(_MAX_POIS),
                    "region": str(value.city_adcode),
                    "show_fields": "business",
                }
            ),
        )
        for seed in seeds
    )
    return (district, *pois)


def _descriptor_bytes(request: AmapLiveRequest) -> bytes:
    return _json_bytes(
        {
            "method": "GET",
            "endpoint_path": request.endpoint_path,
            "operation": request.operation,
            "parameters": {
                key: request.parameters[key]
                for key in sorted(request.parameters)
            },
        }
    )


def _real_transport(
    request: AmapLiveRequest,
    credential: str,
) -> bytes:
    parameters = {
        key: str(value)
        for key, value in request.parameters.items()
    }
    parameters["key"] = credential
    query = urllib.parse.urlencode(parameters)
    url = f"{_AMAP_ORIGIN}{request.endpoint_path}?{query}"
    wire_request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(wire_request, timeout=20) as response:
            content = response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        try:
            exc.close()
        finally:
            raise _WireIssue("http", int(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise _WireIssue("transport") from None
    except Exception:
        raise _WireIssue("transport") from None
    if len(content) > _MAX_RESPONSE_BYTES:
        raise _WireIssue("response_window")
    return bytes(content)


def _clock() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _acquire_observation(
    *,
    request: AmapLiveRequest,
    index: int,
    credential: str,
    transport: AmapLiveTransport,
    fer_root: Path,
    state: _AcquisitionState,
) -> PolicyBoundAmapObservation:
    descriptor = _descriptor_bytes(request)
    descriptor_hash = _sha256(descriptor)
    raw_holder: list[bytes] = []
    observation_holder: list[PolicyBoundAmapObservation] = []

    def runner(_: bytes) -> RunnerObservation:
        state.network_calls += 1
        started_at = _clock()
        try:
            raw = transport(request, credential)
            if type(raw) is not bytes or len(raw) > _MAX_RESPONSE_BYTES:
                raise _WireIssue("response_window")
        except _WireIssue as exc:
            status = (
                "http_response_failure"
                if exc.kind == "http"
                else "transport_failure"
            )
            return RunnerObservation(
                attempts=(
                    AttemptObservation(
                        attempt_id=f"attempt-{index:04d}",
                        request_sha256=descriptor_hash,
                        started_at=started_at,
                        completed_at=_clock(),
                        status=status,
                        http_status=exc.http_status,
                        response_bytes=None,
                        response_sha256=None,
                        content_type=None,
                        retry_decision=(
                            "not_retryable_http"
                            if status == "http_response_failure"
                            else "retry_exhausted"
                        ),
                    ),
                ),
                retries=(),
                response_phase=ResponsePhaseObservation(
                    status="not_evaluated",
                    failure_kind=None,
                ),
            )
        except Exception:
            return RunnerObservation(
                attempts=(
                    AttemptObservation(
                        attempt_id=f"attempt-{index:04d}",
                        request_sha256=descriptor_hash,
                        started_at=started_at,
                        completed_at=_clock(),
                        status="transport_failure",
                        http_status=None,
                        response_bytes=None,
                        response_sha256=None,
                        content_type=None,
                        retry_decision="retry_exhausted",
                    ),
                ),
                retries=(),
                response_phase=ResponsePhaseObservation(
                    status="not_evaluated",
                    failure_kind=None,
                ),
            )
        raw_holder.append(raw)
        response_hash = _sha256(raw)
        state.response_hashes.add(response_hash)
        if request.operation == "district":
            parsed = parse_amap_district_response(raw)
        else:
            parsed = parse_amap_poi_response(raw)
        accepted = not parsed.problems and parsed.value is not None
        if accepted:
            response = parsed.value
            accepted = response.status == "1" and response.infocode == "10000"
        if accepted and isinstance(response, ParsedAmapPoiResponse):
            try:
                count = int(response.count) if response.count is not None else -1
            except ValueError:
                accepted = False
            else:
                accepted = (
                    count == len(response.pois)
                    and count <= _MAX_POIS
                )
        if accepted:
            bound = bind_amap_observation_policy(
                response,
                mode=AmapObservationMode.EPHEMERAL_LIVE,
                policy_checked_at=_clock(),
            )
            accepted = not bound.problems and bound.value is not None
            if accepted:
                observation_holder.append(bound.value)
        return RunnerObservation(
            attempts=(
                AttemptObservation(
                    attempt_id=f"attempt-{index:04d}",
                    request_sha256=descriptor_hash,
                    started_at=started_at,
                    completed_at=_clock(),
                    status="succeeded",
                    http_status=200,
                    response_bytes=len(raw),
                    response_sha256=response_hash,
                    content_type="application/json",
                    retry_decision="not_applicable",
                ),
            ),
            retries=(),
            response_phase=ResponsePhaseObservation(
                status="accepted" if accepted else "rejected",
                failure_kind=None if accepted else "controlled_response_invalid",
            ),
        )

    def cleanup() -> tuple[CleanupItemObservation, ...]:
        existed = bool(raw_holder)
        raw_holder.clear()
        return (
            CleanupItemObservation(
                resource_kind=f"provider_response_memory_{index:04d}",
                existed_before=existed,
                deletion_attempted=existed,
                status="removed" if existed else "not_present",
                residue_count=0,
            ),
        )

    result = run_failure_evidenced_acquisition(
        run_id=stable_identifier(
            "run",
            "trip-decider:wu7b:fer",
            f"{descriptor_hash}|{index}",
        ),
        purpose="wu7b-amap-ephemeral-live",
        request_bytes=descriptor,
        primary_path=fer_root / f"request-{index:04d}.json",
        emergency_path=fer_root / f"request-{index:04d}.emergency.json",
        runner=runner,
        cleanup=cleanup,
        clock=_clock,
    )
    if result.document.get("terminal_failure_code") == (
        "ACQUISITION_CLEANUP_FAILURE"
    ):
        raise _RunIssue(AMAP_P2_CLEANUP_FAILED)
    if result.document.get("status") != "succeeded" or not observation_holder:
        raise _RunIssue(AMAP_PROVIDER_FAILURE)
    observation = observation_holder[0]
    state.observations.append(observation)
    return observation


def _selection_reader(
    ordinals: Mapping[str, int],
):
    def choose(
        seed: str,
        alternatives: tuple[tuple[str, str], ...],
    ) -> str:
        if seed not in ordinals:
            return "0"
        ordinal = ordinals[seed]
        if ordinal > len(alternatives):
            return ""
        return alternatives[ordinal - 1][0]

    return choose


def _project(
    *,
    value: StructuredTripInput,
    seeds: tuple[str, ...],
    selections: Mapping[str, int],
    observations: Sequence[PolicyBoundAmapObservation],
) -> AmapCandidateProjection:
    if (
        len(observations) != len(seeds) + 1
        or not isinstance(
            observations[0].response,
            ParsedAmapDistrictResponse,
        )
    ):
        raise _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)
    result = project_amap_candidates(
        city=value.city,
        city_adcode=value.city_adcode,
        seeds=seeds,
        district_observation=observations[0],
        poi_observations=tuple(
            (seed, observation)
            for seed, observation in zip(
                seeds,
                observations[1:],
                strict=True,
            )
        ),
        selection_reader=(
            _selection_reader(selections)
            if value.interactive
            else None
        ),
    )
    if result.problems or result.value is None:
        codes = {item.error_code for item in result.problems}
        if "OBSERVATION_POLICY_MISMATCH" in codes:
            raise _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)
        raise _RunIssue(AMAP_PROVIDER_FAILURE)
    if result.value.mode is not AmapObservationMode.EPHEMERAL_LIVE:
        raise _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)
    return result.value


def _recovery_documents(
    *,
    projection: AmapCandidateProjection,
    request: Mapping[str, object],
    run_id: str,
    created_at: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    candidates = [_plain(item) for item in projection.candidates]
    facts = [_plain(item) for item in projection.record_local_facts]
    seed_matches = [_plain(item) for item in projection.seed_matches]
    candidate_payload = {
        "candidate_set_id": stable_identifier(
            "candidate_set",
            "trip-decider:wu7b:temporary-candidate-set",
            str(request["artifact_id"]),
        ),
        "request_ref": _artifact_ref(request),
        "generation_stage": "poi_discovery",
        "candidates": candidates,
        "rejected_inputs": [],
    }
    candidate = _artifact(
        "candidates",
        candidate_payload,
        created_at=created_at,
        producer="trip-decider-wu7b-ephemeral-recovery",
        run_id=run_id,
        pipeline_stage="wu7b-ephemeral-place-resolution",
        parents=(str(request["artifact_id"]),),
    )
    accounting = {
        "schema_version": "wu2r-downstream-seed-accounting/1.0",
        "run_id": run_id,
        "seed_matches": seed_matches,
    }
    fact_document = {
        "schema_version": "wu2r-downstream-record-local-facts/1.0",
        "run_id": run_id,
        "record_local_facts": facts,
    }
    return candidate, accounting, fact_document


def _write_recovery(
    root: Path,
    *,
    projection: AmapCandidateProjection,
    request: Mapping[str, object],
    run_id: str,
    created_at: str,
) -> None:
    candidate, accounting, facts = _recovery_documents(
        projection=projection,
        request=request,
        run_id=run_id,
        created_at=created_at,
    )
    values = {
        "candidates.json": candidate,
        "seed-accounting.json": accounting,
        "record-local-facts.json": facts,
    }
    for filename, document in values.items():
        _write(root / filename, _json_bytes(document))
    output_hashes = {
        filename: _sha256((root / filename).read_bytes())
        for filename in values
    }
    status_counts = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    for item in accounting["seed_matches"]:
        status_counts[str(item["status"])] += 1
    summary = {
        "schema_version": "wu2r-downstream-recovery-run/1.0",
        "run_id": run_id,
        "input_fixture_identity": {
            "source_kind": "amap_ephemeral_live",
            "persistence": "temporary_only",
        },
        "output_paths": {
            "candidate_artifact_path": "candidates.json",
            "seed_accounting_path": "seed-accounting.json",
            "record_local_facts_path": "record-local-facts.json",
            "run_summary_path": "run-summary.json",
        },
        "candidate_count": len(projection.candidates),
        "seed_status_counts": status_counts,
        "network_attempts": 0,
        "output_sha256": output_hashes,
        "completion_status": "completed",
    }
    _write(root / "run-summary.json", _json_bytes(summary))
    evidence_probe = run_evidence_runtime(root, root.parent / "evidence")
    if evidence_probe.problems or evidence_probe.value is None:
        raise _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)


def _replace_exact(value: object, replacements: Mapping[str, str]) -> object:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, Mapping):
        return {
            str(key): _replace_exact(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_exact(item, replacements) for item in value]
    if isinstance(value, tuple):
        return [_replace_exact(item, replacements) for item in value]
    return copy.deepcopy(value)


def _safe_candidate_map(
    projection: AmapCandidateProjection,
    request_artifact_id: str,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for selection_value in projection.selections:
        selection = _plain(selection_value)
        seed = str(selection["seed"])
        alternatives = selection["alternatives"]
        if not isinstance(alternatives, list):
            raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
        for ordinal, candidate_id in enumerate(alternatives, start=1):
            source = str(candidate_id)
            safe = stable_identifier(
                "candidate",
                "trip-decider:wu7b:safe-candidate",
                f"{request_artifact_id}|{seed}|{ordinal}",
            )
            if source in mapping and mapping[source] != safe:
                raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
            mapping[source] = safe
    provider_ids = {
        str(_plain(item)["candidate_id"])
        for item in projection.candidates
    }
    if set(mapping) != provider_ids or len(set(mapping.values())) != len(mapping):
        raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
    return mapping


def _safe_fact_map(
    evidence: Mapping[str, object],
    candidate_map: Mapping[str, str],
) -> dict[str, str]:
    payload = evidence.get("payload")
    if not isinstance(payload, Mapping):
        raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
    facts = payload.get("facts")
    if not isinstance(facts, list):
        raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
    mapping: dict[str, str] = {}
    seen_slots: set[tuple[str, str]] = set()
    for item in facts:
        if not isinstance(item, Mapping):
            raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
        fact_id = item.get("fact_id")
        subject = item.get("subject")
        field = item.get("field")
        if (
            not isinstance(fact_id, str)
            or not isinstance(subject, Mapping)
            or not isinstance(subject.get("entity_id"), str)
            or not isinstance(field, str)
            or subject["entity_id"] not in candidate_map
        ):
            raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
        safe_candidate = candidate_map[str(subject["entity_id"])]
        slot = (safe_candidate, field)
        if slot in seen_slots:
            raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
        seen_slots.add(slot)
        mapping[fact_id] = stable_identifier(
            "fact",
            "trip-decider:wu7b:safe-fact-reference",
            f"{safe_candidate}|{field}",
        )
    if len(mapping) != len(facts) or len(set(mapping.values())) != len(mapping):
        raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
    return mapping


def _safe_logical_ref(
    artifact_type: str,
    manifest: Mapping[str, object],
) -> dict[str, object]:
    payload_hash = canonical_payload_sha256(manifest)
    return {
        "artifact_id": stable_artifact_id(artifact_type, payload_hash),
        "artifact_type": artifact_type,
        "payload_sha256": payload_hash,
        "schema_version": "0.1.0",
    }


def _safe_projection(
    *,
    projection: AmapCandidateProjection,
    request: Mapping[str, object],
    constraints: Mapping[str, object],
    planning_root: Path,
    recovery_root: Path,
    evidence_root: Path,
    planner_root: Path,
    network_calls: int,
    created_at: str,
) -> _SafeProjection:
    candidate_map = _safe_candidate_map(
        projection,
        str(request["artifact_id"]),
    )
    evidence = json.loads(
        (evidence_root / "evidence.json").read_text(encoding="utf-8")
    )
    fact_map = _safe_fact_map(evidence, candidate_map)
    candidate_manifest = {
        "contract": "wu7b-safe-candidate-logical-ref/1.0",
        "request_artifact_id": request["artifact_id"],
        "candidate_ids": sorted(candidate_map.values()),
    }
    evidence_manifest = {
        "contract": "wu7b-safe-evidence-logical-ref/1.0",
        "request_artifact_id": request["artifact_id"],
        "fact_ids": sorted(fact_map.values()),
        "support_ceiling": "unknown",
    }
    safe_candidate_ref = _safe_logical_ref(
        "candidates",
        candidate_manifest,
    )
    safe_evidence_ref = _safe_logical_ref(
        "evidence",
        evidence_manifest,
    )
    temp_candidates = json.loads(
        (recovery_root / "candidates.json").read_text(encoding="utf-8")
    )
    replacements = {
        **candidate_map,
        **fact_map,
        str(temp_candidates["artifact_id"]): str(
            safe_candidate_ref["artifact_id"]
        ),
        str(temp_candidates["integrity"]["payload_sha256"]): str(
            safe_candidate_ref["payload_sha256"]
        ),
        str(evidence["artifact_id"]): str(safe_evidence_ref["artifact_id"]),
        str(evidence["integrity"]["payload_sha256"]): str(
            safe_evidence_ref["payload_sha256"]
        ),
    }
    temp_plan = json.loads(
        (planner_root / "plan.json").read_text(encoding="utf-8")
    )
    plan_payload = _replace_exact(temp_plan["payload"], replacements)
    if not isinstance(plan_payload, dict):
        raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
    plan_payload["candidate_set_ref"] = safe_candidate_ref
    plan_payload["evidence_set_ref"] = safe_evidence_ref
    plan_payload["plan_id"] = stable_identifier(
        "plan",
        "trip-decider:wu7b:safe-plan",
        str(request["artifact_id"]),
    )
    for day_number, day in enumerate(plan_payload.get("days", []), start=1):
        if not isinstance(day, dict):
            raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
        day["day_id"] = stable_identifier(
            "day",
            "trip-decider:wu7b:safe-day",
            f"{request['artifact_id']}|{day_number}|{day.get('date')}",
        )
        activities = day.get("activities")
        if not isinstance(activities, list):
            raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
        for activity_number, activity in enumerate(activities, start=1):
            if not isinstance(activity, dict):
                raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
            activity["activity_id"] = stable_identifier(
                "activity",
                "trip-decider:wu7b:safe-activity",
                (
                    f"{request['artifact_id']}|{day_number}|"
                    f"{activity_number}|{activity.get('candidate_ref')}"
                ),
            )
    planning_hashes = [
        {
            "name": f"planning-input/{filename}",
            "sha256": _sha256((planning_root / filename).read_bytes()),
        }
        for filename in _PLANNING_FILES
    ]
    safe_run_id = stable_identifier(
        "run",
        "trip-decider:wu7b:safe-output",
        str(request["artifact_id"]),
    )
    plan = _artifact(
        "plan",
        plan_payload,
        created_at=created_at,
        producer="trip-decider-safe-live-plan",
        run_id=safe_run_id,
        pipeline_stage="wu7b-provider-free-coarse-plan",
        parents=(
            str(request["artifact_id"]),
            str(constraints["artifact_id"]),
            str(safe_candidate_ref["artifact_id"]),
            str(safe_evidence_ref["artifact_id"]),
        ),
        input_hashes=planning_hashes,
    )
    temp_violations = json.loads(
        (planner_root / "violations.json").read_text(encoding="utf-8")
    )
    violation_payload = _replace_exact(
        temp_violations["payload"],
        replacements,
    )
    if not isinstance(violation_payload, dict):
        raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
    violation_payload["plan_ref"] = _artifact_ref(plan)
    violations = _artifact(
        "violations",
        violation_payload,
        created_at=created_at,
        producer="trip-decider-safe-live-plan",
        run_id=safe_run_id,
        pipeline_stage="wu7b-provider-free-coarse-plan",
        parents=(str(plan["artifact_id"]),),
        input_hashes=(
            {
                "name": "safe-plan-payload",
                "sha256": str(plan["integrity"]["payload_sha256"]),
            },
        ),
    )
    temp_gate = json.loads(
        (planner_root / "planning-gate.json").read_text(encoding="utf-8")
    )
    gate = _replace_exact(temp_gate, replacements)
    if not isinstance(gate, dict):
        raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
    gate["run_id"] = safe_run_id
    gate["generation_allowed_input"] = False
    gate["publishable"] = False
    day_by_candidate: dict[str, int] = {}
    for day_number, day in enumerate(plan_payload.get("days", []), start=1):
        for activity in day.get("activities", []):
            day_by_candidate[str(activity["candidate_ref"])] = day_number
    seed_results: list[SafeSeedResult] = []
    selected_seeds = {
        str(_plain(item)["seed"])
        for item in projection.selections
        if _plain(item).get("selection_source") == "user_explicit"
        and _plain(item).get("selected_candidate_ref") is not None
    }
    for raw_match in projection.seed_matches:
        match = _plain(raw_match)
        seed = str(match["seed"])
        status = str(match["status"])
        refs = [candidate_map[str(item)] for item in match["candidate_refs"]]
        day_number = day_by_candidate.get(refs[0]) if len(refs) == 1 else None
        blocker = None
        if status == "ambiguous":
            blocker = "BLOCKED_IDENTITY_AMBIGUOUS"
        elif status == "unmatched":
            blocker = "BLOCKED_IDENTITY_UNMATCHED"
        elif day_number is None:
            blocker = "BLOCKED_NOT_SCHEDULED"
        seed_results.append(
            SafeSeedResult(
                seed=seed,
                identity_status=status,
                explicitly_selected=seed in selected_seeds,
                day_number=day_number,
                blocker=blocker,
            )
        )
    scheduled_count = sum(item.day_number is not None for item in seed_results)
    blocked_count = sum(item.blocker is not None for item in seed_results)
    planning_summary = {
        "schema_version": "wu7b-safe-planning-run/1.0",
        "status": "completed",
        "planning_status": gate.get("planning_status"),
        "draft_created": gate.get("draft_created"),
        "publishable": False,
        "generation_allowed_input": False,
        "scheduled_count": scheduled_count,
        "blocked_count": blocked_count,
        "network_calls": network_calls,
        "llm_calls": 0,
        "source": "高德地图",
        "validation_scope": "artifact_only",
        "output_paths": {
            "plan": "plan.json",
            "planning_gate": "planning-gate.json",
            "violations": "violations.json",
            "run_summary": "run-summary.json",
        },
    }
    return _SafeProjection(
        plan=plan,
        violations=violations,
        gate=gate,
        planning_summary=planning_summary,
        seed_results=tuple(seed_results),
        scheduled_count=scheduled_count,
        blocked_count=blocked_count,
    )


def _render_html(
    safe: _SafeProjection,
    *,
    network_calls: int,
) -> bytes:
    rows = []
    for item in safe.seed_results:
        day = f"Day {item.day_number}" if item.day_number is not None else "—"
        blocker = item.blocker or "none"
        rows.append(
            "<tr>"
            f"<td>{html.escape(item.seed)}</td>"
            f"<td>{html.escape(day)}</td>"
            f"<td>{html.escape(item.identity_status)}</td>"
            f"<td>{html.escape(blocker)}</td>"
            f"<td>{'yes' if item.explicitly_selected else 'no'}</td>"
            "</tr>"
        )
    document = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>trip-decider · 条件化粗计划</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#202124}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:.55rem;text-align:left}}
.notice{{background:#fff7e6;border:1px solid #f0c36d;padding:1rem}}
</style>
</head>
<body>
<h1>条件化粗计划</h1>
<p class="notice">本结果不可直接发布，不是最佳路线、完整攻略或正式可执行行程。</p>
<p>状态：{status}；publishable=false；generation_allowed_input=false。</p>
<table>
<thead><tr><th>用户输入地点</th><th>日期分配</th><th>身份状态</th><th>未解决条件</th><th>显式选择</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<p>网络调用：{calls}；临时数据清理：完成；数据来源：高德地图。</p>
<p>未包含路线时间、营业时间、活动时长或精细日程。</p>
</body>
</html>
""".format(
        status=html.escape(str(safe.gate.get("planning_status"))),
        rows="".join(rows),
        calls=network_calls,
    )
    return document.encode("utf-8")


def _provider_sensitive_values(
    *,
    observations: Sequence[PolicyBoundAmapObservation],
    projection: AmapCandidateProjection,
    response_hashes: set[str],
    credential: str,
    temp_root: Path,
    recovery_root: Path,
    evidence_root: Path,
    planner_root: Path,
) -> set[str]:
    values = set(response_hashes)
    values.add(credential)
    values.add(str(temp_root.resolve()))
    for observation in observations:
        response = observation.response
        if isinstance(response, ParsedAmapDistrictResponse):
            for item in response.districts:
                values.add(item.adcode)
        elif isinstance(response, ParsedAmapPoiResponse):
            for item in response.pois:
                for value in (
                    item.record_id,
                    item.location,
                    item.category_label,
                    item.category_code,
                    item.address,
                    item.province_code,
                    item.city_code,
                    item.district_code,
                ):
                    if isinstance(value, str) and value:
                        values.add(value)
                values.update(part for part in item.location.split(",") if part)
    for candidate in projection.candidates:
        plain = _plain(candidate)
        values.add(str(plain["candidate_id"]))
        provider = plain.get("provider")
        if isinstance(provider, Mapping):
            for key in ("record_id",):
                item = provider.get(key)
                if isinstance(item, str):
                    values.add(item)
            categories = provider.get("categories")
            if isinstance(categories, list):
                values.update(str(item) for item in categories)
        source_refs = plain.get("source_refs")
        if isinstance(source_refs, list):
            values.update(
                str(item.get("value"))
                for item in source_refs
                if isinstance(item, Mapping) and item.get("value")
            )
        location = plain.get("location")
        if isinstance(location, Mapping):
            for key in ("latitude", "longitude"):
                if key in location:
                    values.add(str(location[key]))
    for root in (recovery_root, evidence_root, planner_root):
        for path in root.rglob("*"):
            if path.is_file():
                values.add(_sha256(path.read_bytes()))
        for name in ("candidates.json", "evidence.json", "plan.json"):
            path = root / name
            if path.is_file():
                document = json.loads(path.read_text(encoding="utf-8"))
                for key in ("artifact_id",):
                    if isinstance(document.get(key), str):
                        values.add(document[key])
    return {item for item in values if item}


def _walk_keys(value: object) -> Sequence[str]:
    keys: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_walk_keys(item))
    return keys


def _redaction_scan(root: Path, sensitive: set[str]) -> None:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED) from exc
        for forbidden in sensitive:
            if forbidden and forbidden in text:
                raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
        if path.suffix in {".json", ".yaml", ".yml"}:
            if path.suffix == ".json":
                document = json.loads(text)
            else:
                document = yaml.safe_load(text)
            if _DENIED_FINAL_KEYS.intersection(_walk_keys(document)):
                raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)


def _validate_final_artifacts(root: Path) -> None:
    registry = validate_schema_registry(
        tuple(sorted(_SCHEMA_ROOT.glob("*.schema.json")))
    )
    if registry.problems or registry.value is None:
        raise _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)
    for filename in ("plan.json", "violations.json"):
        loaded = load_document(root / "planning" / filename)
        if loaded.problems or loaded.value is None:
            raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
        checked = validate_artifact(loaded.value, registry.value)
        if checked.problems:
            raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)


def _prepare_safe_stage(
    *,
    stage: Path,
    planning_root: Path,
    safe: _SafeProjection,
    network_calls: int,
    cleanup_counts: Mapping[str, int],
) -> None:
    for filename in _PLANNING_FILES:
        _write(
            stage / "planning-input" / filename,
            (planning_root / filename).read_bytes(),
        )
    _write(stage / "planning" / "plan.json", _json_bytes(safe.plan, pretty=True))
    _write(
        stage / "planning" / "violations.json",
        _json_bytes(safe.violations, pretty=True),
    )
    _write(
        stage / "planning" / "planning-gate.json",
        _json_bytes(safe.gate, pretty=True),
    )
    _write(
        stage / "planning" / "run-summary.json",
        _json_bytes(safe.planning_summary, pretty=True),
    )
    _write(
        stage / "report" / "index.html",
        _render_html(safe, network_calls=network_calls),
    )
    eight_hashes = {
        path.relative_to(stage).as_posix(): _sha256(path.read_bytes())
        for path in sorted(stage.rglob("*"))
        if path.is_file()
    }
    top_summary = {
        "schema_version": "wu7b-amap-ephemeral-live-run/1.0",
        "status": "completed",
        "planning_status": safe.gate.get("planning_status"),
        "publishable": False,
        "generation_allowed_input": False,
        "scheduled_count": safe.scheduled_count,
        "blocked_count": safe.blocked_count,
        "seed_results": [
            {
                "seed": item.seed,
                "identity_status": item.identity_status,
                "explicitly_selected": item.explicitly_selected,
                "day_number": item.day_number,
                "blocker": item.blocker,
            }
            for item in safe.seed_results
        ],
        "network_calls": network_calls,
        "llm_calls": 0,
        "cleanup_counts": dict(cleanup_counts),
        "source": "高德地图",
        "output_files": list(_FINAL_FILES),
        "output_sha256": eight_hashes,
        "capability_boundary": {
            "coarse_day_allocation_only": True,
            "route_time": False,
            "opening_hours": False,
            "activity_duration": False,
            "fine_schedule": False,
        },
    }
    _write(stage / "run-summary.json", _json_bytes(top_summary, pretty=True))
    actual_files = {
        path.relative_to(stage).as_posix()
        for path in stage.rglob("*")
        if path.is_file()
    }
    if actual_files != set(_FINAL_FILES):
        raise _RunIssue(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
    _validate_final_artifacts(stage)


def _emergency_remove(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                path.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass


def _remove_tree(root: Path | None) -> bool:
    if root is None or not root.exists():
        return True
    try:
        shutil.rmtree(root)
        return not root.exists()
    except OSError:
        _emergency_remove(root)
        return False


def run_amap_ephemeral_live(
    config: AmapEphemeralLiveConfig,
    output_root: Path,
    *,
    transport: AmapLiveTransport | None = None,
) -> ValidationResult[AmapEphemeralLiveSummary]:
    """Resolve live places and install only the safe nine-file output."""

    try:
        value, seeds, selections = _checked_config(config)
        checked_output_root = Path(output_root)
    except (TypeError, ValueError, _RunIssue):
        return _failure(_INPUT_INVALID)
    if not _output_root_ok(checked_output_root):
        return _failure(_OUTPUT_ROOT_INVALID)
    if transport is not None and not callable(transport):
        return _failure(_INPUT_INVALID)

    temp_root: Path | None = None
    safe_stage: Path | None = None
    issue: _RunIssue | None = None
    safe: _SafeProjection | None = None
    state = _AcquisitionState([], set())
    credential = ""
    cleanup_counts = {
        "raw_provider_residue": 0,
        "normalized_provider_residue": 0,
        "temporary_residue": 0,
        "removed_resource_count": 0,
    }
    try:
        temp_root = Path(
            tempfile.mkdtemp(prefix="trip-decider-wu7b-ephemeral-")
        )
        planning_root = temp_root / "planning-input"
        recovery_root = temp_root / "recovery"
        evidence_root = temp_root / "evidence"
        planner_root = temp_root / "planner"
        fer_root = temp_root / "fer"
        planning_root.mkdir()
        recovery_root.mkdir()
        fer_root.mkdir()
        run_id = stable_identifier(
            "run",
            "trip-decider:wu7b:ephemeral-run",
            _sha256(
                _json_bytes(
                    {
                        "city": value.city,
                        "start_at": value.start_at,
                        "end_at": value.end_at,
                        "must_visit": list(value.must_visit),
                        "excluded": list(value.excluded),
                    }
                )
            ),
        )
        planning_documents = _planning_documents(value, run_id)
        _write_and_validate_planning(planning_root, planning_documents)

        credential_value = os.environ.get("AMAP_WEB_SERVICE_KEY")
        if not isinstance(credential_value, str) or not credential_value:
            raise _RunIssue(AMAP_CREDENTIAL_MISSING)
        credential = credential_value
        wire = transport or _real_transport
        observations = [
            _acquire_observation(
                request=request,
                index=index,
                credential=credential,
                transport=wire,
                fer_root=fer_root,
                state=state,
            )
            for index, request in enumerate(
                _requests(value, seeds),
                start=1,
            )
        ]
        projection = _project(
            value=value,
            seeds=seeds,
            selections=selections,
            observations=observations,
        )
        _write_recovery(
            recovery_root,
            projection=projection,
            request=planning_documents[0],
            run_id=run_id,
            created_at=value.input_recorded_at,
        )
        # _write_recovery runs Evidence once as its strict compatibility probe.
        # Its output is the actual temporary Evidence root consumed below.
        if not evidence_root.is_dir():
            raise _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)
        planner = run_coarse_planner(
            recovery_root,
            evidence_root,
            planning_root,
            planner_root,
        )
        if planner.problems or planner.value is None:
            raise _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)
        safe = _safe_projection(
            projection=projection,
            request=planning_documents[0],
            constraints=planning_documents[2],
            planning_root=planning_root,
            recovery_root=recovery_root,
            evidence_root=evidence_root,
            planner_root=planner_root,
            network_calls=state.network_calls,
            created_at=value.input_recorded_at,
        )
        cleanup_counts["removed_resource_count"] = (
            len(observations)
            + len(projection.candidates)
            + len(tuple(temp_root.rglob("*")))
        )
        safe_stage = checked_output_root.with_name(
            f".{checked_output_root.name}.wu7b-stage-{uuid.uuid4().hex}"
        )
        safe_stage.mkdir()
        _prepare_safe_stage(
            stage=safe_stage,
            planning_root=planning_root,
            safe=safe,
            network_calls=state.network_calls,
            cleanup_counts=cleanup_counts,
        )
        sensitive = _provider_sensitive_values(
            observations=observations,
            projection=projection,
            response_hashes=state.response_hashes,
            credential=credential,
            temp_root=temp_root,
            recovery_root=recovery_root,
            evidence_root=evidence_root,
            planner_root=planner_root,
        )
        _redaction_scan(safe_stage, sensitive)
    except _RunIssue as exc:
        issue = exc
    except Exception:
        issue = _RunIssue(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)

    cleanup_ok = _remove_tree(temp_root)
    credential = ""
    state.observations.clear()
    state.response_hashes.clear()
    if not cleanup_ok:
        _remove_tree(safe_stage)
        return _failure(AMAP_P2_CLEANUP_FAILED)
    if issue is not None:
        _remove_tree(safe_stage)
        return _failure(issue.code)
    if safe is None or safe_stage is None:
        _remove_tree(safe_stage)
        return _failure(AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED)
    try:
        os.replace(safe_stage, checked_output_root)
    except OSError:
        _remove_tree(safe_stage)
        return _failure(_OUTPUT_ROOT_INVALID)
    installed_files = {
        path.relative_to(checked_output_root).as_posix(): _sha256(
            path.read_bytes()
        )
        for path in sorted(checked_output_root.rglob("*"))
        if path.is_file()
    }
    if set(installed_files) != set(_FINAL_FILES):
        _remove_tree(checked_output_root)
        return _failure(AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED)
    return ValidationResult(
        AmapEphemeralLiveSummary(
            output_root=checked_output_root,
            planning_status=str(safe.gate.get("planning_status")),
            publishable=False,
            generation_allowed_input=False,
            seed_results=safe.seed_results,
            scheduled_count=safe.scheduled_count,
            blocked_count=safe.blocked_count,
            network_calls=state.network_calls,
            llm_calls=0,
            cleanup_counts=MappingProxyType(dict(cleanup_counts)),
            output_sha256=MappingProxyType(installed_files),
        ),
        (),
    )


def _selection_arguments(values: Sequence[str]) -> dict[str, int]:
    output: dict[str, int] = {}
    for item in values:
        if "=" not in item:
            raise ValueError("selection must be SEED=ORDINAL")
        seed, ordinal_text = item.rsplit("=", 1)
        if not seed or not ordinal_text.isdigit() or int(ordinal_text) < 1:
            raise ValueError("selection must be SEED=ORDINAL")
        output[seed] = int(ordinal_text)
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve AMap places ephemerally and create a provider-free "
            "non-publishable coarse plan."
        )
    )
    parser.add_argument("--city", required=True)
    parser.add_argument("--city-adcode", required=True)
    parser.add_argument("--start-at", required=True)
    parser.add_argument("--end-at", required=True)
    parser.add_argument("--input-recorded-at", required=True)
    parser.add_argument("--party-count", required=True, type=int)
    parser.add_argument("--transport-mode", action="append", required=True)
    parser.add_argument("--must-visit", action="append", required=True)
    parser.add_argument("--excluded", action="append", default=[])
    parser.add_argument("--select", action="append", default=[])
    parser.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the approved structured WU7B command-line interface."""

    parser = _parser()
    args = parser.parse_args(argv)
    try:
        selections = _selection_arguments(args.select)
    except ValueError:
        parser.error("--select must use SEED=ORDINAL with a positive ordinal")
    structured = StructuredTripInput(
        city=args.city,
        city_adcode=args.city_adcode,
        start_at=args.start_at,
        end_at=args.end_at,
        input_recorded_at=args.input_recorded_at,
        party_count=args.party_count,
        transport_modes=tuple(args.transport_mode),
        must_visit=tuple(args.must_visit),
        excluded=tuple(args.excluded),
        locale="zh-CN",
        interactive=bool(selections),
    )
    result = run_amap_ephemeral_live(
        AmapEphemeralLiveConfig(
            structured_input=structured,
            selection_ordinals=selections,
        ),
        args.output_root,
    )
    if result.problems:
        for problem in result.problems:
            print(
                json.dumps(
                    {
                        "error_code": problem.error_code,
                        "artifact_path": problem.artifact_path,
                        "json_pointer": problem.json_pointer,
                        "schema_rule": problem.schema_rule,
                        "expected": problem.expected,
                        "actual_type": problem.actual_type,
                        "message": problem.message,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
            )
        return 1
    summary = result.value
    if summary is None:
        return 1
    print(
        json.dumps(
            {
                "status": summary.planning_status,
                "scheduled": summary.scheduled_count,
                "blocked": summary.blocked_count,
                "publishable": summary.publishable,
                "generation_allowed_input": summary.generation_allowed_input,
                "network_calls": summary.network_calls,
                "llm_calls": summary.llm_calls,
                "output_files": len(summary.output_sha256),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


__all__ = [
    "AMAP_CREDENTIAL_MISSING",
    "AMAP_PROVIDER_FAILURE",
    "AMAP_P2_CLEANUP_FAILED",
    "AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED",
    "AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED",
    "AmapEphemeralLiveConfig",
    "AmapEphemeralLiveSummary",
    "AmapLiveRequest",
    "AmapLiveTransport",
    "SafeSeedResult",
    "main",
    "run_amap_ephemeral_live",
]


if __name__ == "__main__":
    raise SystemExit(main())
