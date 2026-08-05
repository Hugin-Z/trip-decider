"""高德响应解析与候选投影。

从 ``live_place_resolution`` 原样搬出——``simple_live`` 只消费这一组解析器，
而原模块其余部分随离线 artifact 管线一并删除（persistence-v2.md 裁决 13.5）。

**纯移动**：函数体、签名、docstring 与原实现逐字符一致。搬动本身不改行为。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import copy
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
import math
from pathlib import Path
from types import MappingProxyType
import unicodedata

from trip_decider.adapters.contracts import (
    ValidationProblem,
    ValidationResult,
    safe_type,
    stable_identifier,
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
    "OBSERVATION_POLICY_MISMATCH": (
        "AMap observation does not match the explicit closed policy mode."
    ),
}

_OBSERVATION_CONTRACT_TOKEN = object()

class _InputIssue(ValueError):
    """Expected structured-input violation."""

class _ProviderIssue(ValueError):
    """Expected synthetic-provider response violation."""

class _SelectionIssue(ValueError):
    """Expected explicit-selection violation."""

class _ObservationPolicyIssue(ValueError):
    """Expected sealed observation-policy violation."""

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
    reference_price_cny: float | None

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

@dataclass(frozen=True)
class PolicyBoundAmapObservation:
    """Sealed policy binding produced only by the public binding function."""

    mode: AmapObservationMode
    response: ParsedAmapDistrictResponse | ParsedAmapPoiResponse
    data_policy: Mapping[str, object]
    locator_prefix: str
    persistence_capability: str
    provenance_label: str
    _contract_token: object

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

    try:
        document = _controlled_response_document(response)
        status, infocode, marker = _parsed_response_header(document)
        raw_districts = document.get("districts")
        if not isinstance(raw_districts, list):
            raise _ProviderIssue("district collection is invalid")
        districts: list[ParsedAmapDistrict] = []
        for item in raw_districts:
            if not isinstance(item, Mapping):
                raise _ProviderIssue("district item is invalid")
            name = item.get("name")
            adcode = item.get("adcode")
            level = item.get("level")
            if not all(
                isinstance(value, str) and value
                for value in (name, adcode, level)
            ):
                raise _ProviderIssue("district identity is invalid")
            districts.append(
                ParsedAmapDistrict(
                    name=name,
                    adcode=adcode,
                    level=level,
                )
            )
    except _ProviderIssue:
        return _failure(
            "LIVE_PLACE_PROVIDER_RESPONSE_INVALID",
            "/provider_response",
            "amapDistrictShape",
            expected="valid AMap-shaped district response",
        )
    return ValidationResult(
        ParsedAmapDistrictResponse(
            status=status,
            infocode=infocode,
            synthetic_test_data=marker,
            districts=tuple(districts),
        ),
        (),
    )

def parse_amap_poi_response(
    response: bytes | Mapping[str, object],
) -> ValidationResult[ParsedAmapPoiResponse]:
    """Parse a decoded or UTF-8 JSON AMap-shaped POI response."""

    try:
        document = _controlled_response_document(response)
        status, infocode, marker = _parsed_response_header(document)
        count = document.get("count")
        if count is not None and not isinstance(count, str):
            raise _ProviderIssue("POI count is invalid")
        raw_pois = document.get("pois")
        if not isinstance(raw_pois, list):
            raise _ProviderIssue("POI collection is invalid")
        pois: list[ParsedAmapPoi] = []
        for item in raw_pois:
            if not isinstance(item, Mapping):
                raise _ProviderIssue("POI item is invalid")
            record_id = item.get("id")
            name = item.get("name")
            location = item.get("location")
            category_label = item.get("type")
            category_code = item.get("typecode")
            if not all(
                isinstance(value, str) and value
                for value in (
                    record_id,
                    name,
                    location,
                    category_label,
                    category_code,
                )
            ):
                raise _ProviderIssue("POI identity or category is invalid")
            _coordinates(location)
            pois.append(
                ParsedAmapPoi(
                    record_id=record_id,
                    name=name,
                    location=location,
                    category_label=category_label,
                    category_code=category_code,
                    address=_optional_provider_text(item.get("address")),
                    province_name=_optional_provider_text(item.get("pname")),
                    city_name=_optional_provider_text(item.get("cityname")),
                    district_name=_optional_provider_text(item.get("adname")),
                    province_code=_optional_provider_text(item.get("pcode")),
                    city_code=_optional_provider_text(item.get("citycode")),
                    district_code=_optional_provider_text(item.get("adcode")),
                    reference_price_cny=_optional_provider_price(item),
                )
            )
    except _ProviderIssue:
        return _failure(
            "LIVE_PLACE_PROVIDER_RESPONSE_INVALID",
            "/provider_response",
            "amapPoiShape",
            expected="valid AMap-shaped POI response",
        )
    return ValidationResult(
        ParsedAmapPoiResponse(
            status=status,
            infocode=infocode,
            synthetic_test_data=marker,
            count=count,
            pois=tuple(pois),
        ),
        (),
    )

def bind_amap_observation_policy(
    parsed: ParsedAmapDistrictResponse | ParsedAmapPoiResponse,
    *,
    mode: AmapObservationMode,
    policy_checked_at: str,
) -> ValidationResult[PolicyBoundAmapObservation]:
    """Bind one parsed response to an explicit closed observation mode."""

    if (
        not isinstance(
            parsed,
            (ParsedAmapDistrictResponse, ParsedAmapPoiResponse),
        )
        or not isinstance(mode, AmapObservationMode)
        or not isinstance(policy_checked_at, str)
    ):
        return _policy_mismatch("/observation_policy")
    try:
        _date_time(policy_checked_at)
    except _InputIssue:
        return _policy_mismatch("/observation_policy/policy_checked_at")
    marker = parsed.synthetic_test_data
    if mode is AmapObservationMode.SYNTHETIC_TEST:
        if marker is not True:
            return _policy_mismatch("/provider_response/synthetic_test_data")
        policy = _synthetic_policy(policy_checked_at)
        locator_prefix = "synthetic-amap:poi:"
        persistence = "synthetic_snapshot_allowed"
        provenance = "synthetic_test_data"
    elif mode is AmapObservationMode.EPHEMERAL_LIVE:
        if marker is True:
            return _policy_mismatch("/provider_response/synthetic_test_data")
        policy = _ephemeral_policy(policy_checked_at)
        locator_prefix = "ephemeral-amap:poi:"
        persistence = "ephemeral_memory_only"
        provenance = "ephemeral_live_observation"
    else:
        return _policy_mismatch("/observation_policy/mode")
    bound = object.__new__(PolicyBoundAmapObservation)
    object.__setattr__(bound, "mode", mode)
    object.__setattr__(bound, "response", parsed)
    object.__setattr__(bound, "data_policy", _freeze_value(policy))
    object.__setattr__(bound, "locator_prefix", locator_prefix)
    object.__setattr__(bound, "persistence_capability", persistence)
    object.__setattr__(bound, "provenance_label", provenance)
    object.__setattr__(bound, "_contract_token", _OBSERVATION_CONTRACT_TOKEN)
    return ValidationResult(bound, ())

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

    try:
        mode = _observation_mode(district_observation)
        if not isinstance(
            district_observation.response,
            ParsedAmapDistrictResponse,
        ):
            raise _ProviderIssue("district observation kind is invalid")
        if (
            not isinstance(city, str)
            or not city
            or (
                city_adcode is not None
                and (
                    not isinstance(city_adcode, str)
                    or not city_adcode
                )
            )
        ):
            raise _ProviderIssue("district query identity is invalid")
        checked_seeds = _projection_seeds(seeds)
        checked_pois = _projection_poi_observations(
            checked_seeds,
            poi_observations,
            mode,
        )
        _resolved_district(
            city,
            city_adcode,
            district_observation.response,
        )
        choices = _checked_selection_choices(selection_choices)
        (
            candidates,
            facts,
            seed_matches,
            selections,
            selected_choices,
        ) = _project_candidate_values(
            checked_seeds,
            checked_pois,
            selection_reader,
            choices,
        )
    except _SelectionIssue:
        return _failure(
            "LIVE_PLACE_SELECTION_INVALID",
            "/selection",
            "offeredCandidateOrZero",
            expected="one displayed Candidate ID or 0",
        )
    except _ProviderIssue:
        return _failure(
            "LIVE_PLACE_PROVIDER_RESPONSE_INVALID",
            "/provider_response",
            "providerNeutralProjection",
            expected="compatible policy-bound AMap observations",
        )
    except _ObservationPolicyIssue:
        return _policy_mismatch("/observation_policy/mode")
    return ValidationResult(
        AmapCandidateProjection(
            mode=mode,
            candidates=tuple(_freeze_value(item) for item in candidates),
            record_local_facts=tuple(
                _freeze_value(item) for item in facts
            ),
            seed_matches=tuple(
                _freeze_value(item) for item in seed_matches
            ),
            selections=tuple(
                _freeze_value(item) for item in selections
            ),
            selection_choices=_freeze_value(selected_choices),
        ),
        (),
    )

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

def _policy_mismatch(
    pointer: str,
) -> ValidationResult[PolicyBoundAmapObservation]:
    return _failure(
        "OBSERVATION_POLICY_MISMATCH",
        pointer,
        "closedObservationMode",
        expected="explicit compatible AmapObservationMode",
    )

def _controlled_response_document(
    response: bytes | Mapping[str, object],
) -> dict[str, object]:
    if isinstance(response, bytes):
        try:
            decoded = response.decode("utf-8")
            document = json.loads(decoded)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise _ProviderIssue("provider response bytes are invalid") from error
        if not isinstance(document, Mapping):
            raise _ProviderIssue("provider response is not an object")
        return copy.deepcopy(dict(document))
    if not isinstance(response, Mapping):
        raise _ProviderIssue("provider response is not bytes or an object")
    return copy.deepcopy(dict(response))

def _parsed_response_header(
    document: Mapping[str, object],
) -> tuple[str, str, bool | None]:
    status = document.get("status")
    infocode = document.get("infocode")
    if status != "1" or infocode != "10000":
        raise _ProviderIssue("provider response status is invalid")
    if (
        "synthetic_test_data" in document
        and not isinstance(document["synthetic_test_data"], bool)
    ):
        raise _ProviderIssue("synthetic marker is invalid")
    marker = document.get("synthetic_test_data")
    return status, infocode, marker if isinstance(marker, bool) else None

def _optional_provider_text(value: object) -> str | None:
    if value is None or value == "" or value == []:
        return None
    if not isinstance(value, str):
        raise _ProviderIssue("optional provider text is invalid")
    return value


def _optional_provider_price(item: Mapping[str, object]) -> float | None:
    """Read only an explicitly returned AMap POI reference price.

    POI Search 2.0 exposes the field under ``business.cost``; older AMap
    responses used ``biz_ext.cost``.  Both are provider-reported reference
    prices, not live bookable hotel rates.  Missing, zero/non-positive,
    non-numeric, and non-finite values stay absent instead of being inferred
    from ratings or other POI metadata.
    """

    raw: object = None
    for container_name in ("business", "biz_ext"):
        container = item.get(container_name)
        if isinstance(container, Mapping) and container.get("cost") not in (
            None,
            "",
            [],
        ):
            raw = container.get("cost")
            break
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    return value

def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze_value(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value

def _thaw_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _thaw_value(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_thaw_value(item) for item in value]
    return value

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

def _ephemeral_policy(created_at: str) -> dict[str, object]:
    return {
        "source_class": "commercial",
        "capture_mode": "temporary_capture",
        "storage_policy": "temporary_only",
        "replay_allowed": False,
        "fixture_allowed": False,
        "policy_checked_at": created_at,
        "terms_url": "https://lbs.amap.com/pages/terms/",
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
    poi: ParsedAmapPoi,
    seed: str,
    observation: PolicyBoundAmapObservation,
) -> tuple[dict[str, object], dict[str, object]]:
    record_id = poi.record_id
    longitude, latitude = _coordinates(poi.location)
    candidate_id = stable_identifier(
        "candidate",
        "trip-decider:wu7:amap-poi",
        f"amap|poi|{record_id}",
    )
    source = {
        "kind": "provider_item",
        "value": f"{observation.locator_prefix}{record_id}",
    }
    categories = [
        {
            "code": poi.category_code,
            "label": poi.category_label,
        }
    ]
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
            "data_policy": _thaw_value(observation.data_policy),
        },
        "source_refs": [source],
        "evidence_fact_refs": [],
        "generation_reason": (
            (
                "Exact-name synthetic provider alternative; "
                "no ranking or recommendation."
            )
            if observation.mode is AmapObservationMode.SYNTHETIC_TEST
            else (
                "Exact-name ephemeral provider alternative; "
                "no ranking or recommendation."
            )
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

def _observation_mode(
    observation: object,
) -> AmapObservationMode:
    if (
        not isinstance(observation, PolicyBoundAmapObservation)
        or getattr(observation, "_contract_token", None)
        is not _OBSERVATION_CONTRACT_TOKEN
        or not isinstance(observation.mode, AmapObservationMode)
        or not isinstance(observation.data_policy, Mapping)
        or not isinstance(observation.locator_prefix, str)
        or not isinstance(observation.persistence_capability, str)
        or not isinstance(observation.provenance_label, str)
    ):
        raise _ObservationPolicyIssue("observation policy is not sealed")
    return observation.mode

def _projection_seeds(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise _ProviderIssue("seed collection is invalid")
    seeds = tuple(values)
    if any(not isinstance(seed, str) or not seed for seed in seeds):
        raise _ProviderIssue("seed identity is invalid")
    normalized = tuple(_normalized_text(seed) for seed in seeds)
    if len(set(normalized)) != len(normalized):
        raise _ProviderIssue("seed identity is not unique")
    return seeds

def _projection_poi_observations(
    seeds: tuple[str, ...],
    values: Sequence[tuple[str, PolicyBoundAmapObservation]],
    mode: AmapObservationMode,
) -> tuple[tuple[str, PolicyBoundAmapObservation], ...]:
    if isinstance(values, (str, bytes)):
        raise _ProviderIssue("POI observations are invalid")
    observations = tuple(values)
    if len(observations) != len(seeds):
        raise _ProviderIssue("POI observation cardinality is invalid")
    checked: list[tuple[str, PolicyBoundAmapObservation]] = []
    for expected_seed, item in zip(seeds, observations, strict=True):
        if (
            not isinstance(item, tuple)
            or len(item) != 2
            or item[0] != expected_seed
        ):
            raise _ProviderIssue("POI observation seed is invalid")
        observation = item[1]
        if _observation_mode(observation) is not mode:
            raise _ObservationPolicyIssue("observation modes differ")
        if not isinstance(observation.response, ParsedAmapPoiResponse):
            raise _ProviderIssue("POI observation kind is invalid")
        checked.append((expected_seed, observation))
    return tuple(checked)

def _resolved_district(
    city: str,
    city_adcode: str | None,
    response: ParsedAmapDistrictResponse,
) -> str:
    matches = [
        item.adcode
        for item in response.districts
        if _normalized_text(item.name) == _normalized_text(city)
        and (city_adcode is None or item.adcode == city_adcode)
    ]
    if len(matches) != 1:
        raise _ProviderIssue("district identity is not unique")
    return matches[0]

def _checked_selection_choices(
    values: Mapping[str, str] | None,
) -> dict[str, str]:
    if values is None:
        return {}
    if not isinstance(values, Mapping) or any(
        not isinstance(seed, str)
        or not seed
        or not isinstance(candidate_id, str)
        or not candidate_id
        for seed, candidate_id in values.items()
    ):
        raise _SelectionIssue("selection choices are invalid")
    return dict(values)

def _project_candidate_values(
    seeds: tuple[str, ...],
    poi_observations: tuple[
        tuple[str, PolicyBoundAmapObservation],
        ...,
    ],
    selection_reader: SelectionReader | None,
    replay_choices: Mapping[str, str],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, str],
]:
    if selection_reader is not None and not callable(selection_reader):
        raise _SelectionIssue("selection reader is not callable")
    candidates_by_id: dict[str, dict[str, object]] = {}
    facts_by_id: dict[str, dict[str, object]] = {}
    alternatives_by_seed: list[tuple[str, tuple[str, ...]]] = []
    for seed, observation in poi_observations:
        response = observation.response
        if not isinstance(response, ParsedAmapPoiResponse):
            raise _ProviderIssue("POI observation kind is invalid")
        alternatives: list[str] = []
        for poi in response.pois:
            if _normalized_text(poi.name) != _normalized_text(seed):
                continue
            candidate, fact = _candidate_from_poi(
                poi,
                seed,
                observation,
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
    facts = [
        facts_by_id[candidate_id]
        for candidate_id in sorted(facts_by_id)
    ]
    selections: list[dict[str, object]] = []
    seed_matches: list[dict[str, object]] = []
    selected_choices: dict[str, str] = {}
    for seed, refs in alternatives_by_seed:
        selected: str | None = None
        source = "not_applicable"
        if len(refs) > 1:
            source = "non_interactive_none"
            if seed in replay_choices:
                selected = replay_choices[seed]
                if selected not in refs:
                    raise _SelectionIssue(
                        "selection is not an offered Candidate ID"
                    )
                source = "user_explicit"
            elif selection_reader is not None:
                offered = tuple(
                    (
                        candidate_id,
                        str(candidates_by_id[candidate_id]["label"]),
                    )
                    for candidate_id in refs
                )
                answer = selection_reader(seed, offered)
                if answer == "0":
                    source = "user_explicit_none"
                elif answer in refs:
                    selected = answer
                    source = "user_explicit"
                else:
                    raise _SelectionIssue(
                        "selection is not an offered Candidate ID"
                    )
            if selected is not None:
                selected_choices[seed] = selected
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
        selections.append(
            {
                "seed": seed,
                "alternatives": list(refs),
                "selected_candidate_ref": selected,
                "selection_source": source,
            }
        )
    if set(replay_choices) - set(seeds):
        raise _SelectionIssue("selection seed is not part of the projection")
    return (
        candidates,
        facts,
        seed_matches,
        selections,
        selected_choices,
    )
