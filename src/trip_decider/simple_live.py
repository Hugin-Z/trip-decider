"""Local planning service built on real AMap place and route capabilities.

This is not the trip-decider product entry or its Discover stage. It serves
the Plan stage after a destination and local place names are supplied. It
keeps provider responses in memory, reuses the provider-neutral parser and
identity projector, and installs only ``plan.json`` plus ``index.html``.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, time as wall_time, timedelta
from pathlib import Path

from trip_decider.adapters.contracts import stable_identifier
from trip_decider.amap_parsers import (
    AmapCandidateProjection,
    AmapObservationMode,
    ParsedAmapDistrictResponse,
    ParsedAmapPoi,
    ParsedAmapPoiResponse,
    PolicyBoundAmapObservation,
    bind_amap_observation_policy,
    parse_amap_district_response,
    parse_amap_poi_response,
    project_amap_candidates,
)


_AMAP_ORIGIN = "https://restapi.amap.com"
_DISTRICT_PATH = "/v3/config/district"
_POI_PATH = "/v5/place/text"
_ROUTE_PATHS = {
    "walking": "/v5/direction/walking",
    "driving": "/v5/direction/driving",
}
_TRANSIT_PATH = "/v5/direction/transit/integrated"
_TIMEOUT_SECONDS = 15
_TRANSPORT_RETRIES = 1
_RETRY_WAIT_SECONDS = 1
_MAX_RESPONSE_BYTES = 2_000_000
_MAX_POIS = 25


@dataclass(frozen=True)
class _Response:
    body: bytes
    http_status: int
    attempts: int
    amap_status: str | None
    amap_infocode: str | None


@dataclass(frozen=True)
class _Route:
    origin_candidate_id: str
    destination_candidate_id: str
    distance_meters: int
    duration_seconds: int
    attempts: int
    estimated_taxi_cost_cny: float | None = None
    polyline: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class _TransitRoute:
    distance_meters: int
    duration_seconds: int
    walking_distance_meters: int
    fare_cny: float | None
    services: tuple[dict[str, object], ...]
    attempts: int
    polyline: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class _LiveFailure(Exception):
    stage: str
    http_status: int | None = None
    amap_status: str | None = None
    amap_infocode: str | None = None
    python_exception_type: str = "RuntimeError"
    response_bytes_received: bool = False
    attempts: int = 0


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip().casefold()


def _safe_provider_header(
    body: bytes,
) -> tuple[str | None, str | None]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(value, Mapping):
        return None, None
    status = value.get("status")
    infocode = value.get("infocode")
    return (
        status if isinstance(status, str) else None,
        infocode if isinstance(infocode, str) else None,
    )


def _http_get(
    *,
    operation: str,
    endpoint_path: str,
    parameters: Mapping[str, str],
    credential: str,
) -> _Response:
    request_parameters = dict(parameters)
    request_parameters["key"] = credential
    encoded = urllib.parse.urlencode(request_parameters)
    request = urllib.request.Request(
        f"{_AMAP_ORIGIN}{endpoint_path}?{encoded}",
        method="GET",
        headers={"Accept": "application/json"},
    )
    attempts = 0
    for retry_index in range(_TRANSPORT_RETRIES + 1):
        attempts += 1
        try:
            with urllib.request.urlopen(
                request,
                timeout=_TIMEOUT_SECONDS,
            ) as response:
                body = response.read(_MAX_RESPONSE_BYTES + 1)
                http_status = int(response.status)
        except urllib.error.HTTPError as error:
            try:
                body = error.read(_MAX_RESPONSE_BYTES + 1)
            except Exception:
                body = b""
            finally:
                error.close()
            status, infocode = _safe_provider_header(body)
            raise _LiveFailure(
                stage=f"{operation}_http",
                http_status=int(error.code),
                amap_status=status,
                amap_infocode=infocode,
                python_exception_type=type(error).__name__,
                response_bytes_received=bool(body),
                attempts=attempts,
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            if retry_index < _TRANSPORT_RETRIES:
                time.sleep(_RETRY_WAIT_SECONDS)
                continue
            raise _LiveFailure(
                stage=f"{operation}_transport",
                python_exception_type=type(error).__name__,
                response_bytes_received=False,
                attempts=attempts,
            ) from None
        except Exception as error:
            raise _LiveFailure(
                stage=f"{operation}_transport",
                python_exception_type=type(error).__name__,
                response_bytes_received=False,
                attempts=attempts,
            ) from None
        if len(body) > _MAX_RESPONSE_BYTES:
            raise _LiveFailure(
                stage=f"{operation}_response_window",
                http_status=http_status,
                python_exception_type="ResponseTooLargeError",
                response_bytes_received=True,
                attempts=attempts,
            )
        status, infocode = _safe_provider_header(body)
        if status is None or infocode is None:
            raise _LiveFailure(
                stage=f"{operation}_parse",
                http_status=http_status,
                python_exception_type="JSONDecodeError",
                response_bytes_received=bool(body),
                attempts=attempts,
            )
        if status != "1" or infocode != "10000":
            raise _LiveFailure(
                stage=f"{operation}_api_status",
                http_status=http_status,
                amap_status=status,
                amap_infocode=infocode,
                python_exception_type="ProviderStatusError",
                response_bytes_received=bool(body),
                attempts=attempts,
            )
        return _Response(
            body=bytes(body),
            http_status=http_status,
            attempts=attempts,
            amap_status=status,
            amap_infocode=infocode,
        )
    raise AssertionError("unreachable transport state")


def _policy_checked_at() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_and_bind_district(
    response: _Response,
) -> PolicyBoundAmapObservation:
    parsed = parse_amap_district_response(response.body)
    if parsed.problems or parsed.value is None:
        raise _LiveFailure(
            stage="district_parse",
            http_status=response.http_status,
            amap_status=response.amap_status,
            amap_infocode=response.amap_infocode,
            python_exception_type="ValidationProblem",
            response_bytes_received=True,
        )
    bound = bind_amap_observation_policy(
        parsed.value,
        mode=AmapObservationMode.EPHEMERAL_LIVE,
        policy_checked_at=_policy_checked_at(),
    )
    if bound.problems or bound.value is None:
        raise _LiveFailure(
            stage="district_observation_policy",
            http_status=response.http_status,
            amap_status=response.amap_status,
            amap_infocode=response.amap_infocode,
            python_exception_type="ValidationProblem",
            response_bytes_received=True,
        )
    return bound.value


def _parse_and_bind_poi(
    response: _Response,
) -> tuple[ParsedAmapPoiResponse, PolicyBoundAmapObservation]:
    parsed = parse_amap_poi_response(response.body)
    if parsed.problems or parsed.value is None:
        raise _LiveFailure(
            stage="poi_parse",
            http_status=response.http_status,
            amap_status=response.amap_status,
            amap_infocode=response.amap_infocode,
            python_exception_type="ValidationProblem",
            response_bytes_received=True,
        )
    bound = bind_amap_observation_policy(
        parsed.value,
        mode=AmapObservationMode.EPHEMERAL_LIVE,
        policy_checked_at=_policy_checked_at(),
    )
    if bound.problems or bound.value is None:
        raise _LiveFailure(
            stage="poi_observation_policy",
            http_status=response.http_status,
            amap_status=response.amap_status,
            amap_infocode=response.amap_infocode,
            python_exception_type="ValidationProblem",
            response_bytes_received=True,
        )
    return parsed.value, bound.value


def _district_identity(
    *,
    city: str,
    city_adcode: str,
    observation: PolicyBoundAmapObservation,
    response: _Response,
) -> dict[str, str]:
    parsed = observation.response
    if not isinstance(parsed, ParsedAmapDistrictResponse):
        raise _LiveFailure(
            stage="district_parse",
            http_status=response.http_status,
            amap_status=response.amap_status,
            amap_infocode=response.amap_infocode,
            python_exception_type="TypeError",
            response_bytes_received=True,
        )
    matches = [
        item
        for item in parsed.districts
        if _normalized(item.name) == _normalized(city)
        and item.adcode == city_adcode
    ]
    if len(matches) != 1:
        raise _LiveFailure(
            stage="district_resolution",
            http_status=response.http_status,
            amap_status=response.amap_status,
            amap_infocode=response.amap_infocode,
            python_exception_type="DistrictIdentityError",
            response_bytes_received=True,
        )
    match = matches[0]
    return {
        "name": match.name,
        "adcode": match.adcode,
        "level": match.level,
    }


def query_destination_district(
    destination: str,
) -> dict[str, object]:
    """Resolve one destination district without persisting provider bytes."""

    anchor = destination.strip()
    if not anchor:
        raise ValueError("destination must be non-empty text")
    credential = os.environ.get("AMAP_WEB_SERVICE_KEY")
    if not isinstance(credential, str) or not credential:
        return {
            "support": "unknown",
            "domain": "map",
            "missing_reason": "amap_web_service_key_not_configured",
            "network_attempts": 0,
        }
    response = _http_get(
        operation="district",
        endpoint_path=_DISTRICT_PATH,
        parameters={
            "extensions": "base",
            "keywords": anchor,
            "subdistrict": "0",
        },
        credential=credential,
    )
    observation = _parse_and_bind_district(response)
    parsed = observation.response
    if not isinstance(parsed, ParsedAmapDistrictResponse):
        raise _LiveFailure(
            stage="district_parse",
            http_status=response.http_status,
            amap_status=response.amap_status,
            amap_infocode=response.amap_infocode,
            python_exception_type="TypeError",
            response_bytes_received=True,
            attempts=response.attempts,
        )
    matches = [
        item
        for item in parsed.districts
        if _normalized(item.name) == _normalized(anchor)
    ]
    if not matches:
        anchor_root = re.sub(r"[省市县区]$", "", _normalized(anchor))
        suffix_matches = [
            item
            for item in parsed.districts
            if anchor_root
            and re.sub(
                r"[省市县区]$",
                "",
                _normalized(item.name),
            ) == anchor_root
        ]
        if len(suffix_matches) == 1:
            matches = suffix_matches
    retrieved_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    if not matches:
        return {
            "support": "unknown",
            "domain": "map",
            "missing_reason": "exact_destination_district_not_found",
            "network_attempts": response.attempts,
            "retrieved_at": retrieved_at,
        }
    if len(matches) > 1:
        return {
            "support": "conflicting",
            "domain": "map",
            "conflict_details": [
                "multiple_exact_destination_districts"
            ],
            "alternatives": [
                {
                    "name": item.name,
                    "adcode": item.adcode,
                    "level": item.level,
                }
                for item in matches
            ],
            "network_attempts": response.attempts,
            "retrieved_at": retrieved_at,
            "source": {
                "provider": "高德地图 Web 服务",
                "scope": "行政区查询",
                "retrieved_at": retrieved_at,
            },
        }
    match = matches[0]
    return {
        "support": "sourced",
        "domain": "map",
        "destination": {
            "name": match.name,
            "adcode": match.adcode,
            "level": match.level,
        },
        "network_attempts": response.attempts,
        "retrieved_at": retrieved_at,
        "source": {
            "provider": "高德地图 Web 服务",
            "scope": "行政区查询",
            "retrieved_at": retrieved_at,
        },
    }


def list_live_top_level_regions() -> dict[str, object]:
    """Read the current AMap country district tree without retaining bytes."""

    credential = os.environ.get("AMAP_WEB_SERVICE_KEY")
    if not isinstance(credential, str) or not credential:
        return {
            "support": "unknown",
            "domain": "map_region_index",
            "missing_reason": "amap_web_service_key_not_configured",
            "network_attempts": 0,
        }
    response = _http_get(
        operation="district",
        endpoint_path=_DISTRICT_PATH,
        parameters={
            "extensions": "base",
            "keywords": "中国",
            "subdistrict": "1",
        },
        credential=credential,
    )
    try:
        document = json.loads(response.body.decode("utf-8"))
        roots = document.get("districts")
        if not isinstance(roots, list) or len(roots) != 1:
            raise ValueError("country district root is invalid")
        children = roots[0].get("districts")
        if not isinstance(children, list):
            raise ValueError("country district children are invalid")
        regions = []
        for item in children:
            if not isinstance(item, Mapping):
                raise ValueError("country district child is invalid")
            name = item.get("name")
            adcode = item.get("adcode")
            level = item.get("level")
            if not all(
                isinstance(value, str) and value
                for value in (name, adcode, level)
            ):
                raise ValueError("country district identity is invalid")
            regions.append(
                {"name": name, "adcode": adcode, "level": level}
            )
    except (UnicodeError, json.JSONDecodeError, ValueError, AttributeError):
        raise _LiveFailure(
            stage="district_parse",
            http_status=response.http_status,
            amap_status=response.amap_status,
            amap_infocode=response.amap_infocode,
            python_exception_type="ValidationProblem",
            response_bytes_received=True,
            attempts=response.attempts,
        ) from None
    retrieved_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    return {
        "support": "sourced",
        "domain": "map_region_index",
        "regions": regions,
        "retrieved_at": retrieved_at,
        "network_attempts": response.attempts,
        "source": {
            "provider": "高德地图 Web 服务",
            "scope": "实时省级行政区索引",
            "retrieved_at": retrieved_at,
        },
    }


def resolve_live_place_points(
    *,
    place_names: Sequence[str],
    region: str | None = None,
) -> dict[str, object]:
    """Resolve unique exact POIs to GCJ-02 points without route queries."""

    seeds = tuple(name.strip() for name in place_names)
    if (
        not seeds
        or any(not seed for seed in seeds)
        or len({_normalized(seed) for seed in seeds}) != len(seeds)
        or (region is not None and not region.strip())
    ):
        raise _LiveFailure(
            stage="map_point_input_validation",
            python_exception_type="ValueError",
        )
    credential = os.environ.get("AMAP_WEB_SERVICE_KEY")
    if not isinstance(credential, str) or not credential:
        raise _LiveFailure(
            stage="credential",
            python_exception_type="KeyError",
        )

    def collect(seed: str) -> tuple[str, _Response, tuple[ParsedAmapPoi, ...]]:
        parameters = {
            "keywords": seed,
            "page_num": "1",
            "page_size": str(_MAX_POIS),
            "show_fields": "business,navi",
        }
        if region is not None:
            parameters["region"] = region.strip()
            parameters["city_limit"] = "true"
        response = _http_get(
            operation="poi",
            endpoint_path=_POI_PATH,
            parameters=parameters,
            credential=credential,
        )
        parsed, _observation = _parse_and_bind_poi(response)
        exact = tuple(
            poi
            for poi in parsed.pois
            if _normalized(poi.name) == _normalized(seed)
        )
        return seed, response, exact

    with ThreadPoolExecutor(
        max_workers=min(6, len(seeds)),
        thread_name_prefix="amap-map-point",
    ) as executor:
        results = list(executor.map(collect, seeds))
    retrieved_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    points: dict[str, dict[str, object]] = {}
    network_attempts = 0
    for seed, response, exact in results:
        network_attempts += response.attempts
        if len(exact) != 1:
            points[seed] = {
                "status": "AMBIGUOUS" if exact else "UNMATCHED",
                "exact_candidate_count": len(exact),
            }
            continue
        values = exact[0].location.split(",")
        if len(values) != 2:
            raise _LiveFailure(
                stage="poi_location_parse",
                http_status=response.http_status,
                amap_status=response.amap_status,
                amap_infocode=response.amap_infocode,
                python_exception_type="ValueError",
                response_bytes_received=True,
                attempts=response.attempts,
            )
        try:
            longitude = float(values[0])
            latitude = float(values[1])
        except ValueError:
            raise _LiveFailure(
                stage="poi_location_parse",
                http_status=response.http_status,
                amap_status=response.amap_status,
                amap_infocode=response.amap_infocode,
                python_exception_type="ValueError",
                response_bytes_received=True,
                attempts=response.attempts,
            ) from None
        points[seed] = {
            "status": "MATCHED",
            "exact_candidate_count": 1,
            "resolved_name": exact[0].name,
            "location": {
                "longitude": longitude,
                "latitude": latitude,
                "coordinate_system": "GCJ-02",
            },
        }
    return {
        "status": (
            "AVAILABLE"
            if all(value["status"] == "MATCHED" for value in points.values())
            else "PARTIAL"
        ),
        "place_resolutions": points,
        "network_attempts": network_attempts,
        "retrieved_at": retrieved_at,
        "source": {
            "provider": "高德地图 Web 服务",
            "scope": "POI Search 2.0 exact-name map points",
            "coordinate_system": "GCJ-02",
        },
    }


def search_live_places(
    *,
    keyword: str,
    region: str | None = None,
    city_limit: bool = False,
    page_size: int = 20,
) -> dict[str, object]:
    """Search provider POIs without persisting raw response bytes.

    This is the generic discovery/profile boundary.  It intentionally returns
    only parsed provider fields and GCJ-02 coordinates; opening hours, prices
    and editorial recommendations are not inferred from a POI response.
    """

    normalized_keyword = keyword.strip()
    normalized_region = region.strip() if isinstance(region, str) else None
    if (
        not normalized_keyword
        or (normalized_region is not None and not normalized_region)
        or not isinstance(city_limit, bool)
        or not isinstance(page_size, int)
        or isinstance(page_size, bool)
        or not 1 <= page_size <= _MAX_POIS
    ):
        raise ValueError("invalid live place search input")
    credential = os.environ.get("AMAP_WEB_SERVICE_KEY")
    if not isinstance(credential, str) or not credential:
        return {
            "support": "unknown",
            "missing_reason": "amap_web_service_key_not_configured",
            "network_attempts": 0,
            "places": [],
        }
    parameters = {
        "keywords": normalized_keyword,
        "page_num": "1",
        "page_size": str(page_size),
        "show_fields": "business,navi",
    }
    if normalized_region is not None:
        parameters["region"] = normalized_region
        parameters["city_limit"] = "true" if city_limit else "false"
    response = _http_get(
        operation="poi",
        endpoint_path=_POI_PATH,
        parameters=parameters,
        credential=credential,
    )
    parsed, _observation = _parse_and_bind_poi(response)
    retrieved_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    places: list[dict[str, object]] = []
    for poi in parsed.pois:
        values = poi.location.split(",")
        location: dict[str, object] | None = None
        if len(values) == 2:
            try:
                location = {
                    "longitude": float(values[0]),
                    "latitude": float(values[1]),
                    "coordinate_system": "GCJ-02",
                }
            except ValueError:
                location = None
        places.append(
            {
                "provider_record_id": poi.record_id,
                "name": poi.name,
                "category": poi.category_label,
                "category_code": poi.category_code,
                "address": poi.address,
                "province": poi.province_name,
                "city": poi.city_name,
                "district": poi.district_name,
                "province_code": poi.province_code,
                "city_code": poi.city_code,
                "district_code": poi.district_code,
                "location": location,
            }
        )
    return {
        "support": "sourced",
        "keyword": normalized_keyword,
        "region": normalized_region,
        "city_limit": city_limit,
        "retrieved_at": retrieved_at,
        "network_attempts": response.attempts,
        "places": places,
        "source": {
            "provider": "高德地图 Web 服务",
            "scope": "POI Search 2.0",
            "retrieved_at": retrieved_at,
            "coordinate_system": "GCJ-02",
        },
    }


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _candidate_id(record_id: str) -> str:
    return stable_identifier(
        "candidate",
        "trip-decider:wu7:amap-poi",
        f"amap|poi|{record_id}",
    )


def _selection_reader(
    poi_by_candidate: Mapping[str, ParsedAmapPoi],
):
    def read(
        seed: str,
        offered: tuple[tuple[str, str], ...],
    ) -> str:
        print(f"\n“{seed}”有 {len(offered)} 个精确匹配：")
        for index, (candidate_id, label) in enumerate(offered, start=1):
            poi = poi_by_candidate[candidate_id]
            district = poi.district_name or "地区未报告"
            address = poi.address or "地址未报告"
            print(
                f"  {index}. {label} | {poi.category_label} | "
                f"{district} | {address}"
            )
        while True:
            try:
                answer = input(
                    f"请选择 1-{len(offered)}；输入 0 保持 unresolved："
                ).strip().lstrip("\ufeff")
            except EOFError:
                raise _LiveFailure(
                    stage="poi_selection",
                    python_exception_type="EOFError",
                    response_bytes_received=True,
                ) from None
            if answer == "0":
                return "0"
            if answer.isdigit() and 1 <= int(answer) <= len(offered):
                return offered[int(answer) - 1][0]
            print("输入无效，请输入候选序号或 0。")

    return read


def _project(
    *,
    city: str,
    city_adcode: str,
    seeds: tuple[str, ...],
    district: PolicyBoundAmapObservation,
    pois: tuple[tuple[str, PolicyBoundAmapObservation], ...],
    poi_by_candidate: Mapping[str, ParsedAmapPoi],
    selection_reader: (
        Callable[[str, tuple[tuple[str, str], ...]], str] | None
    ) = None,
    selection_choices: Mapping[str, str] | None = None,
    interactive_selection: bool = True,
) -> AmapCandidateProjection:
    projected = project_amap_candidates(
        city=city,
        city_adcode=city_adcode,
        seeds=seeds,
        district_observation=district,
        poi_observations=pois,
        selection_reader=(
            selection_reader
            if selection_reader is not None
            else _selection_reader(poi_by_candidate)
            if interactive_selection
            else None
        ),
        selection_choices=selection_choices,
    )
    if projected.problems or projected.value is None:
        raise _LiveFailure(
            stage="poi_projection",
            python_exception_type="ValidationProblem",
            response_bytes_received=True,
        )
    return projected.value


def _normalized_candidate(
    candidate: Mapping[str, object],
    poi_by_candidate: Mapping[str, ParsedAmapPoi],
) -> dict[str, object]:
    value = _plain(candidate)
    if not isinstance(value, dict):
        raise _LiveFailure(
            stage="plan_build",
            python_exception_type="TypeError",
        )
    candidate_id = str(value["candidate_id"])
    provider = value.get("provider")
    location = value.get("location")
    if not isinstance(provider, dict) or not isinstance(location, dict):
        raise _LiveFailure(
            stage="plan_build",
            python_exception_type="TypeError",
        )
    poi = poi_by_candidate[candidate_id]
    return {
        "candidate_id": candidate_id,
        "name": str(value["label"]),
        "provider": "amap",
        "provider_record_id": str(provider["record_id"]),
        "category": {
            "label": poi.category_label,
            "typecode": poi.category_code,
        },
        "address": poi.address,
        "district_name": poi.district_name,
        "location": {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "crs": "GCJ-02",
        },
    }


def _place_resolution(
    *,
    seeds: tuple[str, ...],
    projection: AmapCandidateProjection,
    poi_by_candidate: Mapping[str, ParsedAmapPoi],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, int],
]:
    candidate_by_id = {
        str(candidate["candidate_id"]): candidate
        for candidate in projection.candidates
    }
    selection_by_seed = {
        str(item["seed"]): item for item in projection.selections
    }
    match_by_seed = {
        str(item["seed"]): item for item in projection.seed_matches
    }
    place_results: list[dict[str, object]] = []
    selected_places: list[dict[str, object]] = []
    status_counts = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    for seed in seeds:
        match = match_by_seed[seed]
        selection = selection_by_seed[seed]
        alternatives = [
            _normalized_candidate(
                candidate_by_id[str(candidate_id)],
                poi_by_candidate,
            )
            for candidate_id in selection["alternatives"]
        ]
        selected_ref = selection["selected_candidate_ref"]
        projector_status = str(match["status"])
        if selected_ref is None and len(alternatives) == 1:
            refs = list(match["candidate_refs"])
            selected_ref = refs[0] if len(refs) == 1 else None
        selected = (
            _normalized_candidate(
                candidate_by_id[str(selected_ref)],
                poi_by_candidate,
            )
            if selected_ref is not None
            else None
        )
        match_status = (
            "unmatched"
            if not alternatives
            else "matched"
            if len(alternatives) == 1
            else "ambiguous"
        )
        if selected is not None:
            status = "matched"
            resolution_method = (
                "unique_exact"
                if len(alternatives) == 1
                else "user_selected_exact"
            )
        elif match_status == "ambiguous":
            status = "ambiguous"
            resolution_method = "user_kept_unresolved"
        else:
            status = "unmatched"
            resolution_method = "no_exact_candidate"
        status_counts[status] += 1
        place_results.append(
            {
                "input_name": seed,
                "status": status,
                "match_status": match_status,
                "projector_status": projector_status,
                "resolution_method": resolution_method,
                "selected": selected,
                "alternatives": alternatives,
            }
        )
        if selected is not None:
            selected_places.append(selected)
    return place_results, selected_places, status_counts


def _route_coordinates(place: Mapping[str, object]) -> str:
    location = place.get("location")
    if not isinstance(location, Mapping):
        raise _LiveFailure(
            stage="route_input",
            python_exception_type="TypeError",
        )
    longitude = location.get("longitude")
    latitude = location.get("latitude")
    if (
        not isinstance(longitude, (int, float))
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or isinstance(latitude, bool)
    ):
        raise _LiveFailure(
            stage="route_input",
            python_exception_type="TypeError",
        )
    return f"{float(longitude):.6f},{float(latitude):.6f}"


def _polyline_points(value: object) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, str) or not value.strip():
        return ()
    points: list[tuple[float, float]] = []
    for raw_point in value.split(";"):
        values = raw_point.split(",")
        if len(values) != 2:
            raise ValueError("polyline point must contain longitude,latitude")
        longitude = float(values[0])
        latitude = float(values[1])
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("polyline coordinate is out of range")
        point = (longitude, latitude)
        if not points or points[-1] != point:
            points.append(point)
    return tuple(points)


def _nested_polyline(value: object) -> tuple[tuple[float, float], ...]:
    """Collect provider-returned route geometry in response order."""

    points: list[tuple[float, float]] = []

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if key == "polyline":
                    for point in _polyline_points(nested):
                        if not points or points[-1] != point:
                            points.append(point)
                else:
                    visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return tuple(points)


def _route_value(
    *,
    origin: Mapping[str, object],
    destination: Mapping[str, object],
    transport_mode: str,
    credential: str,
) -> _Route:
    parameters = {
        "origin": _route_coordinates(origin),
        "destination": _route_coordinates(destination),
        "show_fields": "cost,navi,polyline",
    }
    if isinstance(origin.get("provider_record_id"), str):
        parameters["origin_id"] = str(origin["provider_record_id"])
    if isinstance(destination.get("provider_record_id"), str):
        parameters["destination_id"] = str(
            destination["provider_record_id"]
        )
    if transport_mode == "driving":
        parameters["strategy"] = "32"
    response = _http_get(
        operation=f"route_{transport_mode}",
        endpoint_path=_ROUTE_PATHS[transport_mode],
        parameters=parameters,
        credential=credential,
    )
    try:
        document = json.loads(response.body.decode("utf-8"))
        route = document["route"]
        paths = route["paths"]
        if not isinstance(paths, list) or not paths:
            raise ValueError("route paths must be a non-empty array")
        taxi_cost_value = route.get("taxi_cost")
        if taxi_cost_value in (None, ""):
            estimated_taxi_cost_cny = None
        else:
            estimated_taxi_cost_cny = float(taxi_cost_value)
            if estimated_taxi_cost_cny < 0:
                raise ValueError("negative taxi cost")
        metrics: list[tuple[int, int, int]] = []
        for index, path in enumerate(paths):
            if not isinstance(path, Mapping):
                raise TypeError("route path must be an object")
            cost = path["cost"]
            if not isinstance(cost, Mapping):
                raise TypeError("route cost must be an object")
            distance = int(path["distance"])
            duration = int(cost["duration"])
            if distance < 0 or duration < 0:
                raise ValueError("negative route metric")
            metrics.append((duration, distance, index))
        duration, distance, selected_index = min(metrics)
        polyline = _nested_polyline(paths[selected_index])
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        raise _LiveFailure(
            stage=f"route_{transport_mode}_parse",
            http_status=response.http_status,
            amap_status=response.amap_status,
            amap_infocode=response.amap_infocode,
            python_exception_type=type(error).__name__,
            response_bytes_received=True,
            attempts=response.attempts,
        ) from None
    return _Route(
        origin_candidate_id=str(origin["candidate_id"]),
        destination_candidate_id=str(destination["candidate_id"]),
        distance_meters=distance,
        duration_seconds=duration,
        attempts=response.attempts,
        estimated_taxi_cost_cny=estimated_taxi_cost_cny,
        polyline=polyline,
    )


def _optional_nonnegative_number(value: object) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    if result < 0:
        raise ValueError("negative route cost")
    return result


def _service_clock(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if len(value) == 4 and value.isdigit():
        return f"{value[:2]}:{value[2:]}"
    return value


def _transit_route_value(
    *,
    origin: Mapping[str, object],
    destination: Mapping[str, object],
    city_adcode: str,
    credential: str,
) -> _TransitRoute | None:
    parameters = {
        "origin": _route_coordinates(origin),
        "destination": _route_coordinates(destination),
        "city1": city_adcode,
        "city2": city_adcode,
        "strategy": "0",
        "show_fields": "cost,navi,polyline",
    }
    if isinstance(origin.get("provider_record_id"), str):
        parameters["origin_id"] = str(origin["provider_record_id"])
    if isinstance(destination.get("provider_record_id"), str):
        parameters["destination_id"] = str(
            destination["provider_record_id"]
        )
    response = _http_get(
        operation="route_transit",
        endpoint_path=_TRANSIT_PATH,
        parameters=parameters,
        credential=credential,
    )
    try:
        document = json.loads(response.body.decode("utf-8"))
        route = document["route"]
        transits = route.get("transits")
        if not isinstance(transits, list):
            raise TypeError("transits must be an array")
        if not transits:
            return None
        parsed: list[
            tuple[
                tuple[int, float, int, int],
                int,
                int,
                int,
                float | None,
                tuple[dict[str, object], ...],
                tuple[tuple[float, float], ...],
            ]
        ] = []
        for index, transit in enumerate(transits):
            if not isinstance(transit, Mapping):
                raise TypeError("transit option must be an object")
            cost = transit["cost"]
            if not isinstance(cost, Mapping):
                raise TypeError("transit cost must be an object")
            duration = int(cost["duration"])
            distance = int(transit["distance"])
            walking_distance = int(transit["walking_distance"])
            if duration < 0 or distance < 0 or walking_distance < 0:
                raise ValueError("negative transit metric")
            fare = _optional_nonnegative_number(cost.get("transit_fee"))
            services: list[dict[str, object]] = []
            polyline = _nested_polyline(transit)
            segments = transit.get("segments")
            if not isinstance(segments, list):
                raise TypeError("transit segments must be an array")
            for segment in segments:
                if not isinstance(segment, Mapping):
                    raise TypeError("transit segment must be an object")
                bus = segment.get("bus")
                if not isinstance(bus, Mapping):
                    continue
                buslines = bus.get("buslines")
                if buslines in (None, []):
                    continue
                if not isinstance(buslines, list):
                    raise TypeError("buslines must be an array")
                for line in buslines:
                    if not isinstance(line, Mapping):
                        raise TypeError("bus line must be an object")
                    departure_stop = line.get("departure_stop")
                    arrival_stop = line.get("arrival_stop")
                    if not isinstance(departure_stop, Mapping) or not isinstance(
                        arrival_stop, Mapping
                    ):
                        raise TypeError("bus stop must be an object")
                    name = line.get("name")
                    boarding = departure_stop.get("name")
                    alighting = arrival_stop.get("name")
                    if not all(
                        isinstance(value, str) and value
                        for value in (name, boarding, alighting)
                    ):
                        raise TypeError("bus service identity is missing")
                    services.append(
                        {
                            "service": name,
                            "board_at": boarding,
                            "alight_at": alighting,
                            "operating_start": _service_clock(
                                line.get("start_time")
                            ),
                            "operating_end": _service_clock(
                                line.get("end_time")
                            ),
                        }
                    )
            fare_sort = fare if fare is not None else float("inf")
            parsed.append(
                (
                    (duration, fare_sort, walking_distance, index),
                    distance,
                    duration,
                    walking_distance,
                    fare,
                    tuple(services),
                    polyline,
                )
            )
        (
            _,
            distance,
            duration,
            walking_distance,
            fare,
            services,
            polyline,
        ) = min(parsed, key=lambda item: item[0])
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        raise _LiveFailure(
            stage="route_transit_parse",
            http_status=response.http_status,
            amap_status=response.amap_status,
            amap_infocode=response.amap_infocode,
            python_exception_type=type(error).__name__,
            response_bytes_received=True,
            attempts=response.attempts,
        ) from None
    return _TransitRoute(
        distance_meters=distance,
        duration_seconds=duration,
        walking_distance_meters=walking_distance,
        fare_cny=fare,
        services=services,
        attempts=response.attempts,
        polyline=polyline,
    )


def _route_warning(
    *,
    origin: Mapping[str, object],
    destination: Mapping[str, object],
    error: _LiveFailure,
) -> dict[str, object]:
    return {
        "stage": error.stage,
        "from": str(origin["name"]),
        "to": str(destination["name"]),
        "http_status": error.http_status,
        "amap_status": error.amap_status,
        "amap_infocode": error.amap_infocode,
        "python_exception_type": error.python_exception_type,
        "response_bytes_received": error.response_bytes_received,
    }


def _greedy_route_order(
    *,
    selected_places: Sequence[Mapping[str, object]],
    transport_mode: str,
    credential: str,
) -> tuple[
    list[Mapping[str, object]],
    dict[tuple[str, str], _Route],
    list[dict[str, object]],
    list[dict[str, object]],
    int,
    int,
    int,
]:
    if not selected_places:
        return [], {}, [], [], 0, 0, 0
    input_order = {
        str(place["candidate_id"]): index
        for index, place in enumerate(selected_places)
    }
    ordered: list[Mapping[str, object]] = [selected_places[0]]
    remaining = list(selected_places[1:])
    route_cache: dict[tuple[str, str], _Route] = {}
    warnings: list[dict[str, object]] = []
    evaluations: list[dict[str, object]] = []
    attempts = 0
    succeeded = 0
    failed = 0
    while remaining:
        origin = ordered[-1]
        ranked: list[
            tuple[float, int, Mapping[str, object]]
        ] = []
        for destination in remaining:
            key = (
                str(origin["candidate_id"]),
                str(destination["candidate_id"]),
            )
            try:
                route = _route_value(
                    origin=origin,
                    destination=destination,
                    transport_mode=transport_mode,
                    credential=credential,
                )
            except _LiveFailure as error:
                attempts += error.attempts
                failed += 1
                warnings.append(
                    _route_warning(
                        origin=origin,
                        destination=destination,
                        error=error,
                    )
                )
                evaluations.append(
                    {
                        "from": str(origin["name"]),
                        "to": str(destination["name"]),
                        "status": "warning",
                        "distance_meters": None,
                        "duration_seconds": None,
                    }
                )
                ranked.append(
                    (
                        float("inf"),
                        input_order[str(destination["candidate_id"])],
                        destination,
                    )
                )
                continue
            attempts += route.attempts
            succeeded += 1
            route_cache[key] = route
            evaluations.append(
                {
                    "from": str(origin["name"]),
                    "to": str(destination["name"]),
                    "status": "succeeded",
                    "distance_meters": route.distance_meters,
                    "duration_seconds": route.duration_seconds,
                    "estimated_taxi_cost_cny": (
                        route.estimated_taxi_cost_cny
                    ),
                }
            )
            ranked.append(
                (
                    float(route.duration_seconds),
                    input_order[str(destination["candidate_id"])],
                    destination,
                )
            )
        ranked.sort(key=lambda item: (item[0], item[1]))
        chosen = ranked[0][2]
        ordered.append(chosen)
        remaining.remove(chosen)
    used_pairs = {
        (
            str(origin["candidate_id"]),
            str(destination["candidate_id"]),
        )
        for origin, destination in zip(ordered, ordered[1:])
    }
    for evaluation in evaluations:
        origin_name = str(evaluation["from"])
        destination_name = str(evaluation["to"])
        evaluation["used_for_order"] = any(
            str(origin["name"]) == origin_name
            and str(destination["name"]) == destination_name
            and (
                str(origin["candidate_id"]),
                str(destination["candidate_id"]),
            )
            in used_pairs
            for origin, destination in zip(ordered, ordered[1:])
        )
    return (
        ordered,
        route_cache,
        warnings,
        evaluations,
        attempts,
        succeeded,
        failed,
    )


def _time_text(value: datetime) -> str:
    return value.strftime("%H:%M")


def _schedule_days(
    *,
    ordered_places: Sequence[Mapping[str, object]],
    route_cache: Mapping[tuple[str, str], _Route],
    start_date: date,
    days: int,
    daily_start: wall_time,
    daily_end: wall_time,
    visit_minutes: int,
    warnings: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    day_values = [
        {
            "day_number": day_number,
            "date": (
                start_date + timedelta(days=day_number - 1)
            ).isoformat(),
            "daily_start": daily_start.strftime("%H:%M"),
            "daily_end": daily_end.strftime("%H:%M"),
            "activities": [],
        }
        for day_number in range(1, days + 1)
    ]
    unscheduled: list[dict[str, object]] = []
    day_index = 0
    current_end: datetime | None = None
    previous_place: Mapping[str, object] | None = None
    previous_activity: dict[str, object] | None = None
    for place in ordered_places:
        placed = False
        while day_index < len(day_values):
            day = day_values[day_index]
            day_date = date.fromisoformat(str(day["date"]))
            window_start = datetime.combine(day_date, daily_start)
            window_end = datetime.combine(day_date, daily_end)
            travel: _Route | None = None
            start_at = window_start
            if day["activities"] and previous_place is not None:
                key = (
                    str(previous_place["candidate_id"]),
                    str(place["candidate_id"]),
                )
                travel = route_cache.get(key)
                if travel is None:
                    if day_index + 1 < len(day_values):
                        day_index += 1
                        current_end = None
                        previous_place = None
                        previous_activity = None
                        continue
                    unscheduled.append(
                        {
                            "name": str(place["name"]),
                            "reason": "route_unavailable_and_no_day_remaining",
                        }
                    )
                    placed = True
                    break
                if current_end is None:
                    raise _LiveFailure(
                        stage="plan_build",
                        python_exception_type="RuntimeError",
                    )
                start_at = current_end + timedelta(
                    seconds=travel.duration_seconds
                )
            end_at = start_at + timedelta(minutes=visit_minutes)
            if end_at <= window_end:
                activity = {
                    "name": str(place["name"]),
                    "candidate_id": str(place["candidate_id"]),
                    "start_at": _time_text(start_at),
                    "end_at": _time_text(end_at),
                    "visit_minutes": visit_minutes,
                    "location": place["location"],
                    "category": place["category"],
                    "address": place["address"],
                    "travel_from_previous": (
                        {
                            "distance_meters": travel.distance_meters,
                            "duration_seconds": travel.duration_seconds,
                            "estimated_taxi_cost_cny": (
                                travel.estimated_taxi_cost_cny
                            ),
                            "estimated_by": "amap_route_planning_2.0",
                        }
                        if travel is not None
                        else None
                    ),
                    "to_next": None,
                }
                day["activities"].append(activity)
                if previous_activity is not None and travel is not None:
                    previous_activity["to_next"] = {
                        "destination": str(place["name"]),
                        "distance_meters": travel.distance_meters,
                        "duration_seconds": travel.duration_seconds,
                        "estimated_taxi_cost_cny": (
                            travel.estimated_taxi_cost_cny
                        ),
                        "estimated_by": "amap_route_planning_2.0",
                    }
                current_end = end_at
                previous_place = place
                previous_activity = activity
                placed = True
                break
            if day["activities"] and day_index + 1 < len(day_values):
                day_index += 1
                current_end = None
                previous_place = None
                previous_activity = None
                continue
            unscheduled.append(
                {
                    "name": str(place["name"]),
                    "reason": (
                        "daily_window_exceeded"
                        if day["activities"]
                        else "visit_duration_exceeds_daily_window"
                    ),
                }
            )
            placed = True
            break
        if not placed:
            unscheduled.append(
                {
                    "name": str(place["name"]),
                    "reason": "all_days_used",
                }
            )
    return day_values, unscheduled


def _build_plan(
    *,
    city: str,
    city_adcode: str,
    district: Mapping[str, str],
    start_date: date,
    days: int,
    transport_mode: str,
    daily_start: wall_time,
    daily_end: wall_time,
    visit_minutes: int,
    place_results: list[dict[str, object]],
    status_counts: Mapping[str, int],
    ordered_places: Sequence[Mapping[str, object]],
    route_cache: Mapping[tuple[str, str], _Route],
    warnings: list[dict[str, object]],
    route_evaluations: list[dict[str, object]],
    network_attempts: int,
    route_calls_succeeded: int,
    route_calls_failed: int,
) -> dict[str, object]:
    day_values, unscheduled = _schedule_days(
        ordered_places=ordered_places,
        route_cache=route_cache,
        start_date=start_date,
        days=days,
        daily_start=daily_start,
        daily_end=daily_end,
        visit_minutes=visit_minutes,
        warnings=warnings,
    )
    unresolved = [
        {
            "name": str(place["input_name"]),
            "candidate_count": len(place["alternatives"]),
        }
        for place in place_results
        if place["status"] == "ambiguous"
    ]
    unmatched = [
        {"name": str(place["input_name"])}
        for place in place_results
        if place["status"] == "unmatched"
    ]
    scheduled_count = sum(
        len(day["activities"]) for day in day_values
    )
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "schema_version": "simple-live/1.1",
        "city": city,
        "city_adcode": city_adcode,
        "start_date": start_date.isoformat(),
        "days_requested": days,
        "transport_mode": transport_mode,
        "daily_window": {
            "start": daily_start.strftime("%H:%M"),
            "end": daily_end.strftime("%H:%M"),
        },
        "visit_minutes": visit_minutes,
        "district": {
            "status": "matched",
            **dict(district),
        },
        "plan_status": (
            "conditionally_feasible"
            if scheduled_count
            else "no_plan_found"
        ),
        "publishable": False,
        "days": day_values,
        "place_results": place_results,
        "unresolved": unresolved,
        "unmatched": unmatched,
        "unscheduled": unscheduled,
        "warnings": warnings,
        "route_evaluations": route_evaluations,
        "summary": {
            "poi_candidate_count": sum(
                len(place["alternatives"]) for place in place_results
            ),
            "matched": status_counts["matched"],
            "ambiguous": status_counts["ambiguous"],
            "unmatched": status_counts["unmatched"],
            "scheduled": scheduled_count,
            "unscheduled": len(unscheduled),
            "network_attempts": network_attempts,
            "route_calls_succeeded": route_calls_succeeded,
            "route_calls_failed": route_calls_failed,
        },
        "data_sources": [
            {
                "provider": "高德地图",
                "scope": "district_and_poi_search",
                "coordinate_system": "GCJ-02",
            },
            {
                "provider": "高德地图",
                "scope": "route_planning_2.0",
                "transport_mode": transport_mode,
            },
        ],
        "generated_at": generated_at,
        "limitations": [
            "第一站按用户输入顺序确定，后续仅按已取得的交通时间贪心排序，不代表最佳路线。",
            "未核验营业时间。",
            "未估算排队时间。",
            "未核验门票。",
            "未估算停留时长。",
            "visit_minutes是用户提供的统一规划输入，不是系统推荐时长。",
            "每天第一站默认从景点现场开始，未计算住宿地到第一站的交通。",
        ],
    }


def _render_html(plan: Mapping[str, object]) -> str:
    day_sections: list[str] = []
    for day in plan["days"]:
        if not isinstance(day, Mapping):
            continue
        timeline: list[str] = []
        for item in day["activities"]:
            name = html.escape(str(item["name"]))
            address = html.escape(str(item.get("address") or "地址未报告"))
            category = item.get("category")
            category_text = (
                html.escape(str(category.get("label")))
                if isinstance(category, Mapping)
                else "类型未报告"
            )
            timeline.append(
                '<article class="activity">'
                f'<div class="time">{html.escape(str(item["start_at"]))}'
                f'–{html.escape(str(item["end_at"]))}</div>'
                f"<div><h3>{name}</h3>"
                f"<p>{category_text} · {address}</p>"
                f'<p>预计游览 {int(item["visit_minutes"])} 分钟'
                "（用户输入）</p></div></article>"
            )
            to_next = item.get("to_next")
            if isinstance(to_next, Mapping):
                duration_minutes = (
                    int(to_next["duration_seconds"]) + 59
                ) // 60
                distance_km = int(to_next["distance_meters"]) / 1000
                destination = html.escape(str(to_next["destination"]))
                timeline.append(
                    '<div class="leg">↓ '
                    f"{html.escape(str(plan['transport_mode']))} 前往"
                    f" {destination}：{distance_km:.1f} km，"
                    f"约 {duration_minutes} 分钟</div>"
                )
        timeline_html = "".join(timeline)
        if not timeline_html:
            timeline_html = '<p class="empty">本日暂无已安排地点。</p>'
        day_sections.append(
            '<section class="day-card">'
            f"<h2>Day {int(day['day_number'])} · "
            f"{html.escape(str(day['date']))}</h2>"
            f'<p class="window">{html.escape(str(day["daily_start"]))}'
            f'–{html.escape(str(day["daily_end"]))}</p>'
            f"{timeline_html}</section>"
        )
    status_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(place['input_name']))}</td>"
        f"<td>{html.escape(str(place['status']))}</td>"
        f"<td>{len(place['alternatives'])}</td>"
        "</tr>"
        for place in plan["place_results"]
    )

    def issue_list(
        values: object,
        empty_text: str,
        *,
        include_reason: bool = False,
    ) -> str:
        if not isinstance(values, list) or not values:
            return f'<p class="empty">{html.escape(empty_text)}</p>'
        entries = []
        for value in values:
            if not isinstance(value, Mapping):
                continue
            text = html.escape(str(value["name"]))
            if include_reason and value.get("reason"):
                text += " — " + html.escape(str(value["reason"]))
            entries.append(f"<li>{text}</li>")
        return "<ul>" + "".join(entries) + "</ul>"

    warnings = plan.get("warnings")
    warning_items: list[str] = []
    if isinstance(warnings, list):
        for warning in warnings:
            if not isinstance(warning, Mapping):
                continue
            warning_items.append(
                "<li>"
                f"{html.escape(str(warning.get('from', ''))) } → "
                f"{html.escape(str(warning.get('to', ''))) }: "
                f"{html.escape(str(warning.get('stage', 'route_warning')))}"
                "</li>"
            )
    warning_html = (
        "<ul>" + "".join(warning_items) + "</ul>"
        if warning_items
        else '<p class="empty">无路线警告。</p>'
    )
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>trip-decider · 实时粗行程</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#202124;background:#f6f7f9}}
h1{{margin-bottom:.35rem}}.meta{{color:#5f6368}}
.notice{{background:#fff7e6;border:1px solid #efc36d;border-radius:10px;padding:1rem}}
.day-card{{background:white;border-radius:14px;padding:1.25rem;margin:1.25rem 0;box-shadow:0 2px 10px #00000010}}
.window{{color:#5f6368}}.activity{{display:grid;grid-template-columns:110px 1fr;gap:1rem;border-left:4px solid #2f6fed;padding:.65rem 1rem;margin:.6rem 0}}
.activity h3{{margin:0 0 .35rem}}.activity p{{margin:.25rem 0;color:#5f6368}}
.time{{font-weight:700;color:#2f6fed}}.leg{{margin:.4rem 0 .8rem 126px;color:#35694a;background:#eef8f1;padding:.6rem;border-radius:8px}}
table{{border-collapse:collapse;width:100%;background:white}}th,td{{border:1px solid #ddd;padding:.55rem;text-align:left}}
.issues{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:1rem}}.issue{{background:white;border-radius:10px;padding:1rem}}
.empty{{color:#777}}footer{{margin:2rem 0;color:#666}}
</style>
</head>
<body>
<h1>{city} · {days_requested} 日实时粗行程</h1>
<p class="meta">{start_date} 起 · {transport_mode} · 每站 {visit_minutes} 分钟</p>
<p class="notice"><strong>publishable=false</strong>。路线时间来自高德路线规划 2.0；营业时间、排队、门票均未核实。游览时长是用户输入，不是系统推荐。</p>
{days}
<h2>地点解析</h2>
<table>
<thead><tr><th>地点</th><th>解析状态</th><th>精确候选数</th></tr></thead>
<tbody>{status_rows}</tbody>
</table>
<div class="issues">
<section class="issue"><h2>未解决</h2>{unresolved}</section>
<section class="issue"><h2>未匹配</h2>{unmatched}</section>
<section class="issue"><h2>未安排</h2>{unscheduled}</section>
<section class="issue"><h2>路线警告</h2>{warnings}</section>
</div>
<footer>数据来源：高德地图行政区、POI Search 2.0 与路线规划 2.0。GCJ-02。生成时间：{generated_at}。原始响应未保存。</footer>
</body>
</html>
""".format(
        city=html.escape(str(plan["city"])),
        days_requested=int(plan["days_requested"]),
        start_date=html.escape(str(plan["start_date"])),
        transport_mode=html.escape(str(plan["transport_mode"])),
        visit_minutes=int(plan["visit_minutes"]),
        days="".join(day_sections),
        status_rows=status_rows,
        unresolved=issue_list(plan["unresolved"], "无未解决地点。"),
        unmatched=issue_list(plan["unmatched"], "无未匹配地点。"),
        unscheduled=issue_list(
            plan["unscheduled"],
            "无未安排地点。",
            include_reason=True,
        ),
        warnings=warning_html,
        generated_at=html.escape(str(plan["generated_at"])),
    )


def _install_output(
    output_root: Path,
    plan: Mapping[str, object],
) -> tuple[Path, Path]:
    root = output_root.resolve()
    if root.exists():
        raise _LiveFailure(
            stage="output_prepare",
            python_exception_type="FileExistsError",
        )
    if not root.parent.is_dir():
        raise _LiveFailure(
            stage="output_prepare",
            python_exception_type="FileNotFoundError",
        )
    stage = Path(
        tempfile.mkdtemp(
            prefix=f".{root.name}.simple-live-",
            dir=root.parent,
        )
    )
    try:
        plan_path = stage / "plan.json"
        html_path = stage / "index.html"
        plan_path.write_text(
            json.dumps(
                plan,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        html_path.write_text(_render_html(plan), encoding="utf-8")
        if {item.name for item in stage.iterdir()} != {
            "plan.json",
            "index.html",
        }:
            raise _LiveFailure(
                stage="output_install",
                python_exception_type="OutputShapeError",
            )
        os.replace(stage, root)
        return root / "plan.json", root / "index.html"
    except _LiveFailure:
        raise
    except Exception as error:
        raise _LiveFailure(
            stage="output_install",
            python_exception_type=type(error).__name__,
        ) from None
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def estimate_live_route_segments(
    *,
    city: str,
    city_adcode: str,
    place_names: Sequence[str],
    segments: Sequence[tuple[str, str]],
) -> dict[str, object]:
    """Resolve exact AMap places once and estimate requested driving legs."""

    seeds = tuple(name.strip() for name in place_names)
    if (
        not city.strip()
        or not city_adcode.isdigit()
        or not seeds
        or any(not seed for seed in seeds)
        or len({_normalized(seed) for seed in seeds}) != len(seeds)
        or any(
            len(segment) != 2
            or segment[0] not in seeds
            or segment[1] not in seeds
            or segment[0] == segment[1]
            for segment in segments
        )
    ):
        raise _LiveFailure(
            stage="route_matrix_input_validation",
            python_exception_type="ValueError",
        )
    credential = os.environ.get("AMAP_WEB_SERVICE_KEY")
    if not isinstance(credential, str) or not credential:
        raise _LiveFailure(
            stage="credential",
            python_exception_type="KeyError",
        )
    district_response = _http_get(
        operation="district",
        endpoint_path=_DISTRICT_PATH,
        parameters={
            "extensions": "base",
            "keywords": city,
            "subdistrict": "0",
        },
        credential=credential,
    )
    district_observation = _parse_and_bind_district(district_response)
    _district_identity(
        city=city,
        city_adcode=city_adcode,
        observation=district_observation,
        response=district_response,
    )
    network_attempts = district_response.attempts
    poi_observations: list[
        tuple[str, PolicyBoundAmapObservation]
    ] = []
    poi_by_candidate: dict[str, ParsedAmapPoi] = {}
    for seed in seeds:
        poi_response = _http_get(
            operation="poi",
            endpoint_path=_POI_PATH,
            parameters={
                "city_limit": "true",
                "keywords": seed,
                "page_num": "1",
                "page_size": str(_MAX_POIS),
                "region": city_adcode,
                "show_fields": "business",
            },
            credential=credential,
        )
        network_attempts += poi_response.attempts
        parsed, observation = _parse_and_bind_poi(poi_response)
        poi_observations.append((seed, observation))
        for poi in parsed.pois:
            if _normalized(poi.name) == _normalized(seed):
                poi_by_candidate[_candidate_id(poi.record_id)] = poi
    projection = _project(
        city=city,
        city_adcode=city_adcode,
        seeds=seeds,
        district=district_observation,
        pois=tuple(poi_observations),
        poi_by_candidate=poi_by_candidate,
        interactive_selection=False,
    )
    place_results, _, _ = _place_resolution(
        seeds=seeds,
        projection=projection,
        poi_by_candidate=poi_by_candidate,
    )
    selected_by_input = {
        str(result["input_name"]): result["selected"]
        for result in place_results
        if isinstance(result["selected"], Mapping)
    }
    resolutions: dict[str, dict[str, object]] = {}
    for result in place_results:
        input_name = str(result["input_name"])
        resolution: dict[str, object] = {
            "status": result["status"],
            "exact_candidate_count": len(result["alternatives"]),
        }
        selected = result.get("selected")
        location = (
            selected.get("location")
            if isinstance(selected, Mapping)
            else None
        )
        if isinstance(location, Mapping):
            resolution["location"] = {
                "longitude": location.get("longitude"),
                "latitude": location.get("latitude"),
                "coordinate_system": "GCJ-02",
            }
            resolution["resolved_name"] = selected.get("name")
        resolutions[input_name] = resolution
    route_values: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    for origin_name, destination_name in segments:
        origin = selected_by_input.get(origin_name)
        destination = selected_by_input.get(destination_name)
        if not isinstance(origin, Mapping) or not isinstance(
            destination, Mapping
        ):
            route_values.append(
                {
                    "from": origin_name,
                    "to": destination_name,
                    "status": "UNKNOWN",
                    "distance_meters": None,
                    "duration_seconds": None,
                    "estimated_taxi_cost_cny": None,
                    "reason": "place_identity_not_uniquely_resolved",
                }
            )
            continue
        try:
            route = _route_value(
                origin=origin,
                destination=destination,
                transport_mode="driving",
                credential=credential,
            )
        except _LiveFailure as error:
            network_attempts += error.attempts
            warnings.append(
                _route_warning(
                    origin=origin,
                    destination=destination,
                    error=error,
                )
            )
            route_values.append(
                {
                    "from": origin_name,
                    "to": destination_name,
                    "status": "UNKNOWN",
                    "distance_meters": None,
                    "duration_seconds": None,
                    "estimated_taxi_cost_cny": None,
                    "reason": error.stage,
                }
            )
            continue
        network_attempts += route.attempts
        route_values.append(
            {
                "from": origin_name,
                "to": destination_name,
                "status": "AVAILABLE",
                "distance_meters": route.distance_meters,
                "duration_seconds": route.duration_seconds,
                "estimated_taxi_cost_cny": (
                    route.estimated_taxi_cost_cny
                ),
            }
        )
    return {
        "status": (
            "AVAILABLE"
            if all(route["status"] == "AVAILABLE" for route in route_values)
            else "PARTIAL"
        ),
        "place_resolutions": resolutions,
        "segments": route_values,
        "warnings": warnings,
        "network_attempts": network_attempts,
        "source": {
            "provider": "高德地图 Web 服务",
            "scope": "POI Search 2.0 与驾车路线规划 2.0",
            "coordinate_system": "GCJ-02",
            "fare_semantics": "provider_estimated_taxi_cost",
        },
    }


def estimate_live_public_transport_segments(
    *,
    city: str,
    city_adcode: str,
    place_names: Sequence[str],
    segments: Sequence[tuple[str, str]],
) -> dict[str, object]:
    """Resolve exact places and query transit before any road fallback.

    A driving route is requested only when AMap returns no public-transport
    option for a segment. Its distance and duration describe self-driving.
    ``taxi_cost`` is retained only when AMap explicitly returns that estimate;
    this function never derives a taxi fare from distance.
    """

    overall_started = time.monotonic()
    seeds = tuple(name.strip() for name in place_names)
    if (
        not city.strip()
        or not city_adcode.isdigit()
        or not seeds
        or any(not seed for seed in seeds)
        or len({_normalized(seed) for seed in seeds}) != len(seeds)
        or any(
            len(segment) != 2
            or segment[0] not in seeds
            or segment[1] not in seeds
            or segment[0] == segment[1]
            for segment in segments
        )
    ):
        raise _LiveFailure(
            stage="public_route_matrix_input_validation",
            python_exception_type="ValueError",
        )
    credential = os.environ.get("AMAP_WEB_SERVICE_KEY")
    if not isinstance(credential, str) or not credential:
        raise _LiveFailure(
            stage="credential",
            python_exception_type="KeyError",
        )
    district_started = time.monotonic()
    district_response = _http_get(
        operation="district",
        endpoint_path=_DISTRICT_PATH,
        parameters={
            "extensions": "base",
            "keywords": city,
            "subdistrict": "0",
        },
        credential=credential,
    )
    district_observation = _parse_and_bind_district(district_response)
    _district_identity(
        city=city,
        city_adcode=city_adcode,
        observation=district_observation,
        response=district_response,
    )
    district_duration_ms = round(
        (time.monotonic() - district_started) * 1000,
        3,
    )
    network_attempts = district_response.attempts
    def collect_poi(
        seed: str,
    ) -> tuple[
        str,
        int,
        PolicyBoundAmapObservation,
        dict[str, ParsedAmapPoi],
    ]:
        poi_response = _http_get(
            operation="poi",
            endpoint_path=_POI_PATH,
            parameters={
                "city_limit": "true",
                "keywords": seed,
                "page_num": "1",
                "page_size": str(_MAX_POIS),
                "region": city_adcode,
                "show_fields": "business",
            },
            credential=credential,
        )
        parsed, observation = _parse_and_bind_poi(poi_response)
        exact: dict[str, ParsedAmapPoi] = {}
        for poi in parsed.pois:
            if _normalized(poi.name) == _normalized(seed):
                exact[_candidate_id(poi.record_id)] = poi
        return seed, poi_response.attempts, observation, exact

    poi_started = time.monotonic()
    with ThreadPoolExecutor(
        max_workers=min(6, len(seeds)),
        thread_name_prefix="amap-poi",
    ) as executor:
        poi_results = list(executor.map(collect_poi, seeds))
    poi_observations: list[tuple[str, PolicyBoundAmapObservation]] = []
    poi_by_candidate: dict[str, ParsedAmapPoi] = {}
    for seed, attempts, observation, exact in poi_results:
        network_attempts += attempts
        poi_observations.append((seed, observation))
        poi_by_candidate.update(exact)
    poi_duration_ms = round(
        (time.monotonic() - poi_started) * 1000,
        3,
    )
    projection = _project(
        city=city,
        city_adcode=city_adcode,
        seeds=seeds,
        district=district_observation,
        pois=tuple(poi_observations),
        poi_by_candidate=poi_by_candidate,
        interactive_selection=False,
    )
    place_results, _, _ = _place_resolution(
        seeds=seeds,
        projection=projection,
        poi_by_candidate=poi_by_candidate,
    )
    selected_by_input = {
        str(result["input_name"]): result["selected"]
        for result in place_results
        if isinstance(result["selected"], Mapping)
    }
    resolutions: dict[str, dict[str, object]] = {}
    for result in place_results:
        input_name = str(result["input_name"])
        resolution: dict[str, object] = {
            "status": result["status"],
            "exact_candidate_count": len(result["alternatives"]),
        }
        selected = result.get("selected")
        location = (
            selected.get("location")
            if isinstance(selected, Mapping)
            else None
        )
        if isinstance(location, Mapping):
            resolution["location"] = {
                "longitude": location.get("longitude"),
                "latitude": location.get("latitude"),
                "coordinate_system": "GCJ-02",
            }
            resolution["resolved_name"] = selected.get("name")
        resolutions[input_name] = resolution
    def collect_segment(
        segment: tuple[str, str],
    ) -> tuple[dict[str, object], list[dict[str, object]], int]:
        origin_name, destination_name = segment
        origin = selected_by_input.get(origin_name)
        destination = selected_by_input.get(destination_name)
        if not isinstance(origin, Mapping) or not isinstance(
            destination, Mapping
        ):
            return (
                {
                    "from": origin_name,
                    "to": destination_name,
                    "status": "UNKNOWN",
                    "primary": None,
                    "alternatives": [],
                    "reason": "place_identity_not_uniquely_resolved",
                },
                [],
                0,
            )
        segment_attempts = 0
        segment_warnings: list[dict[str, object]] = []
        try:
            transit = _transit_route_value(
                origin=origin,
                destination=destination,
                city_adcode=city_adcode,
                credential=credential,
            )
        except _LiveFailure as error:
            segment_attempts += error.attempts
            segment_warnings.append(
                _route_warning(
                    origin=origin,
                    destination=destination,
                    error=error,
                )
            )
            return (
                {
                    "from": origin_name,
                    "to": destination_name,
                    "status": "UNKNOWN",
                    "primary": None,
                    "alternatives": [],
                    "reason": error.stage,
                },
                segment_warnings,
                segment_attempts,
            )
        if transit is not None:
            segment_attempts += transit.attempts
            return (
                {
                    "from": origin_name,
                    "to": destination_name,
                    "status": "AVAILABLE",
                    "primary": {
                        "mode": "public_transit",
                        "support": "api_estimate",
                        "duration_seconds": transit.duration_seconds,
                        "distance_meters": transit.distance_meters,
                        "walking_distance_meters": (
                            transit.walking_distance_meters
                        ),
                        "fare_cny": transit.fare_cny,
                        "services": list(transit.services),
                        "polyline": [
                            [longitude, latitude]
                            for longitude, latitude in transit.polyline
                        ],
                        "source": "高德公交路线规划2.0",
                    },
                    "alternatives": [],
                    "reason": None,
                },
                segment_warnings,
                segment_attempts,
            )
        # Public transport was queried first and returned no option. Only this
        # branch requests a road route for explicit fallback comparison.
        segment_attempts += 1
        try:
            driving = _route_value(
                origin=origin,
                destination=destination,
                transport_mode="driving",
                credential=credential,
            )
        except _LiveFailure as error:
            segment_attempts += error.attempts
            segment_warnings.append(
                _route_warning(
                    origin=origin,
                    destination=destination,
                    error=error,
                )
            )
            driving = None
        else:
            segment_attempts += driving.attempts
        alternatives: list[dict[str, object]] = [
            {
                "mode": "chartered_vehicle",
                "status": "UNKNOWN",
                "duration_seconds": None,
                "cost_cny": None,
                "reason": "no_date_specific_quote",
            }
        ]
        if driving is not None:
            alternatives.extend(
                [
                    {
                        "mode": "taxi",
                        "status": (
                            "ESTIMATED"
                            if driving.estimated_taxi_cost_cny is not None
                            else "UNKNOWN"
                        ),
                        "duration_seconds": driving.duration_seconds,
                        "distance_meters": driving.distance_meters,
                        "cost_cny": driving.estimated_taxi_cost_cny,
                        "polyline": [
                            [longitude, latitude]
                            for longitude, latitude in driving.polyline
                        ],
                        "cost_semantics": (
                            "amap_explicit_taxi_estimate_not_distance_derived"
                        ),
                    },
                    {
                        "mode": "self_driving",
                        "status": "ESTIMATED",
                        "duration_seconds": driving.duration_seconds,
                        "distance_meters": driving.distance_meters,
                        "cost_cny": None,
                        "polyline": [
                            [longitude, latitude]
                            for longitude, latitude in driving.polyline
                        ],
                        "reason": "fuel_tolls_and_parking_not_queried",
                    },
                ]
            )
        return (
            {
                "from": origin_name,
                "to": destination_name,
                "status": "PUBLIC_TRANSIT_UNAVAILABLE",
                "primary": None,
                "alternatives": alternatives,
                "reason": "amap_returned_zero_transit_options",
            },
            segment_warnings,
            segment_attempts,
        )

    route_started = time.monotonic()
    with ThreadPoolExecutor(
        max_workers=min(6, max(1, len(segments))),
        thread_name_prefix="amap-route",
    ) as executor:
        segment_results = list(executor.map(collect_segment, segments))
    values = [value for value, _warnings, _attempts in segment_results]
    warnings = [
        warning
        for _value, segment_warnings, _attempts in segment_results
        for warning in segment_warnings
    ]
    network_attempts += sum(
        attempts for _value, _warnings, attempts in segment_results
    )
    route_duration_ms = round(
        (time.monotonic() - route_started) * 1000,
        3,
    )
    return {
        "status": (
            "AVAILABLE"
            if all(value["status"] == "AVAILABLE" for value in values)
            else "PARTIAL"
        ),
        "place_resolutions": resolutions,
        "segments": values,
        "warnings": warnings,
        "network_attempts": network_attempts,
        "timings_ms": {
            "district": district_duration_ms,
            "poi": poi_duration_ms,
            "local_transit": route_duration_ms,
            "total": round(
                (time.monotonic() - overall_started) * 1000,
                3,
            ),
        },
        "retrieved_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "source": {
            "provider": "高德地图 Web 服务",
            "scope": "POI Search 2.0、公交路线规划2.0；无公交时才调用驾车路线规划2.0",
            "coordinate_system": "GCJ-02",
            "fare_semantics": (
                "transit fare is provider-returned; taxi cost is never "
                "derived from driving distance"
            ),
        },
    }


def estimate_public_transport_from_points(
    *,
    city_adcode: str,
    place_points: Mapping[str, Mapping[str, object]],
    segments: Sequence[tuple[str, str]],
) -> dict[str, object]:
    """Query routes from already parsed same-run GCJ-02 place evidence."""

    if not city_adcode.isdigit() or not place_points or not segments:
        raise _LiveFailure(
            stage="public_route_points_input_validation",
            python_exception_type="ValueError",
        )
    credential = os.environ.get("AMAP_WEB_SERVICE_KEY")
    if not isinstance(credential, str) or not credential:
        raise _LiveFailure(
            stage="credential",
            python_exception_type="KeyError",
        )
    selected: dict[str, dict[str, object]] = {}
    resolutions: dict[str, dict[str, object]] = {}
    for name, location in place_points.items():
        if not isinstance(name, str) or not name.strip():
            raise _LiveFailure(
                stage="public_route_points_input_validation",
                python_exception_type="ValueError",
            )
        point = {
            "longitude": location.get("longitude"),
            "latitude": location.get("latitude"),
            "coordinate_system": location.get(
                "coordinate_system",
                "GCJ-02",
            ),
        }
        candidate = {
            "candidate_id": stable_identifier(
                "route-point",
                "trip-decider:same-run-map-evidence",
                name,
            ),
            "name": name,
            "location": point,
        }
        _route_coordinates(candidate)
        selected[name] = candidate
        resolutions[name] = {
            "status": "MATCHED",
            "exact_candidate_count": 1,
            "resolved_name": name,
            "location": point,
        }
    values: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    attempts = 0
    started = time.monotonic()
    for origin_name, destination_name in segments:
        origin = selected.get(origin_name)
        destination = selected.get(destination_name)
        if origin is None or destination is None or origin_name == destination_name:
            raise _LiveFailure(
                stage="public_route_points_input_validation",
                python_exception_type="ValueError",
            )
        try:
            transit = _transit_route_value(
                origin=origin,
                destination=destination,
                city_adcode=city_adcode,
                credential=credential,
            )
        except _LiveFailure as error:
            attempts += error.attempts
            warnings.append(
                _route_warning(
                    origin=origin,
                    destination=destination,
                    error=error,
                )
            )
            values.append(
                {
                    "from": origin_name,
                    "to": destination_name,
                    "status": "UNKNOWN",
                    "primary": None,
                    "alternatives": [],
                    "reason": error.stage,
                }
            )
            continue
        if transit is not None:
            attempts += transit.attempts
            values.append(
                {
                    "from": origin_name,
                    "to": destination_name,
                    "status": "AVAILABLE",
                    "primary": {
                        "mode": "public_transit",
                        "support": "api_estimate",
                        "duration_seconds": transit.duration_seconds,
                        "distance_meters": transit.distance_meters,
                        "walking_distance_meters": (
                            transit.walking_distance_meters
                        ),
                        "fare_cny": transit.fare_cny,
                        "services": list(transit.services),
                        "polyline": [
                            [longitude, latitude]
                            for longitude, latitude in transit.polyline
                        ],
                        "source": "高德公交路线规划2.0",
                    },
                    "alternatives": [],
                    "reason": None,
                }
            )
            continue
        try:
            driving = _route_value(
                origin=origin,
                destination=destination,
                transport_mode="driving",
                credential=credential,
            )
        except _LiveFailure as error:
            attempts += 1 + error.attempts
            warnings.append(
                _route_warning(
                    origin=origin,
                    destination=destination,
                    error=error,
                )
            )
            driving = None
        else:
            attempts += 1 + driving.attempts
        alternatives: list[dict[str, object]] = []
        if driving is not None:
            alternatives.append(
                {
                    "mode": "self_driving",
                    "status": "ESTIMATED",
                    "duration_seconds": driving.duration_seconds,
                    "distance_meters": driving.distance_meters,
                    "cost_cny": None,
                    "polyline": [
                        [longitude, latitude]
                        for longitude, latitude in driving.polyline
                    ],
                    "reason": "public_transit_unavailable",
                }
            )
        values.append(
            {
                "from": origin_name,
                "to": destination_name,
                "status": "PUBLIC_TRANSIT_UNAVAILABLE",
                "primary": None,
                "alternatives": alternatives,
                "reason": "amap_returned_zero_transit_options",
            }
        )
    retrieved_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    return {
        "status": (
            "AVAILABLE"
            if all(value["status"] == "AVAILABLE" for value in values)
            else "PARTIAL"
        ),
        "place_resolutions": resolutions,
        "segments": values,
        "warnings": warnings,
        "network_attempts": attempts,
        "timings_ms": {
            "district": 0.0,
            "poi": 0.0,
            "local_transit": round(
                (time.monotonic() - started) * 1000,
                3,
            ),
            "total": round((time.monotonic() - started) * 1000, 3),
        },
        "retrieved_at": retrieved_at,
        "source": {
            "provider": "高德地图 Web 服务",
            "scope": (
                "同一run已解析GCJ-02地点证据与公交路线规划2.0；"
                "无公交时才调用驾车路线规划2.0"
            ),
            "coordinate_system": "GCJ-02",
        },
    }


def estimate_local_roundtrip_transfer(
    *,
    city: str,
    city_adcode: str,
    station_name: str,
    lodging_area_name: str,
) -> dict[str, object]:
    """Resolve two exact places and estimate both driving directions.

    Provider responses stay in memory. Taxi amounts are provider estimates,
    not observed fares or binding quotations.
    """

    seeds = (station_name.strip(), lodging_area_name.strip())
    if (
        not city.strip()
        or not city_adcode.isdigit()
        or any(not seed for seed in seeds)
        or _normalized(seeds[0]) == _normalized(seeds[1])
    ):
        raise _LiveFailure(
            stage="transfer_input_validation",
            python_exception_type="ValueError",
        )
    credential = os.environ.get("AMAP_WEB_SERVICE_KEY")
    if not isinstance(credential, str) or not credential:
        raise _LiveFailure(
            stage="credential",
            python_exception_type="KeyError",
        )
    district_response = _http_get(
        operation="district",
        endpoint_path=_DISTRICT_PATH,
        parameters={
            "extensions": "base",
            "keywords": city,
            "subdistrict": "0",
        },
        credential=credential,
    )
    district_observation = _parse_and_bind_district(district_response)
    _district_identity(
        city=city,
        city_adcode=city_adcode,
        observation=district_observation,
        response=district_response,
    )
    network_attempts = district_response.attempts
    poi_observations: list[
        tuple[str, PolicyBoundAmapObservation]
    ] = []
    poi_by_candidate: dict[str, ParsedAmapPoi] = {}
    for seed in seeds:
        poi_response = _http_get(
            operation="poi",
            endpoint_path=_POI_PATH,
            parameters={
                "city_limit": "true",
                "keywords": seed,
                "page_num": "1",
                "page_size": str(_MAX_POIS),
                "region": city_adcode,
                "show_fields": "business",
            },
            credential=credential,
        )
        network_attempts += poi_response.attempts
        parsed, observation = _parse_and_bind_poi(poi_response)
        poi_observations.append((seed, observation))
        for poi in parsed.pois:
            if _normalized(poi.name) == _normalized(seed):
                poi_by_candidate[_candidate_id(poi.record_id)] = poi
    projection = _project(
        city=city,
        city_adcode=city_adcode,
        seeds=seeds,
        district=district_observation,
        pois=tuple(poi_observations),
        poi_by_candidate=poi_by_candidate,
        interactive_selection=False,
    )
    place_results, selected_places, status_counts = _place_resolution(
        seeds=seeds,
        projection=projection,
        poi_by_candidate=poi_by_candidate,
    )
    if len(selected_places) != 2 or status_counts["matched"] != 2:
        return {
            "status": "UNKNOWN",
            "station_resolution": place_results[0]["status"],
            "lodging_area_resolution": place_results[1]["status"],
            "network_attempts": network_attempts,
            "condition": (
                "站点或住宿片区没有得到唯一精确身份，未调用路线接口。"
            ),
        }
    selected_by_input = {
        str(result["input_name"]): result["selected"]
        for result in place_results
    }
    station = selected_by_input.get(station_name)
    lodging_area = selected_by_input.get(lodging_area_name)
    if not isinstance(station, Mapping) or not isinstance(
        lodging_area, Mapping
    ):
        raise _LiveFailure(
            stage="transfer_place_resolution",
            python_exception_type="RuntimeError",
            response_bytes_received=True,
            attempts=network_attempts,
        )
    inbound = _route_value(
        origin=station,
        destination=lodging_area,
        transport_mode="driving",
        credential=credential,
    )
    outbound = _route_value(
        origin=lodging_area,
        destination=station,
        transport_mode="driving",
        credential=credential,
    )
    network_attempts += inbound.attempts + outbound.attempts
    return {
        "status": "AVAILABLE",
        "station_resolution": "matched",
        "lodging_area_resolution": "matched",
        "network_attempts": network_attempts,
        "inbound": {
            "distance_meters": inbound.distance_meters,
            "duration_seconds": inbound.duration_seconds,
            "estimated_taxi_cost_cny": (
                inbound.estimated_taxi_cost_cny
            ),
        },
        "outbound": {
            "distance_meters": outbound.distance_meters,
            "duration_seconds": outbound.duration_seconds,
            "estimated_taxi_cost_cny": (
                outbound.estimated_taxi_cost_cny
            ),
        },
        "source": {
            "provider": "高德地图 Web 服务",
            "scope": "POI Search 2.0 与驾车路线规划 2.0",
            "coordinate_system": "GCJ-02",
            "fare_semantics": "provider_estimated_taxi_cost",
        },
    }


def run_simple_live(
    *,
    city: str,
    city_adcode: str,
    start_date: str,
    must_visit: Sequence[str],
    days: int,
    transport_mode: str,
    daily_start: str,
    daily_end: str,
    visit_minutes: int,
    output_root: Path,
    selection_reader: (
        Callable[[str, tuple[tuple[str, str], ...]], str] | None
    ) = None,
    selection_choices: Mapping[str, str] | None = None,
    interactive_selection: bool = True,
) -> dict[str, object]:
    seeds = tuple(must_visit)
    try:
        parsed_start_date = date.fromisoformat(start_date)
        parsed_daily_start = datetime.strptime(
            daily_start,
            "%H:%M",
        ).time()
        parsed_daily_end = datetime.strptime(
            daily_end,
            "%H:%M",
        ).time()
    except ValueError:
        raise _LiveFailure(
            stage="input_validation",
            python_exception_type="ValueError",
        ) from None
    if (
        not city.strip()
        or not city_adcode.isdigit()
        or not seeds
        or any(not item.strip() for item in seeds)
        or len({_normalized(item) for item in seeds}) != len(seeds)
        or type(days) is not int
        or days < 1
        or transport_mode not in _ROUTE_PATHS
        or parsed_daily_end <= parsed_daily_start
        or type(visit_minutes) is not int
        or visit_minutes < 1
    ):
        raise _LiveFailure(
            stage="input_validation",
            python_exception_type="ValueError",
        )
    credential = os.environ.get("AMAP_WEB_SERVICE_KEY")
    if not isinstance(credential, str) or not credential:
        raise _LiveFailure(
            stage="credential",
            python_exception_type="KeyError",
        )
    district_response = _http_get(
        operation="district",
        endpoint_path=_DISTRICT_PATH,
        parameters={
            "extensions": "base",
            "keywords": city,
            "subdistrict": "0",
        },
        credential=credential,
    )
    district_observation = _parse_and_bind_district(district_response)
    district = _district_identity(
        city=city,
        city_adcode=city_adcode,
        observation=district_observation,
        response=district_response,
    )
    poi_observations: list[tuple[str, PolicyBoundAmapObservation]] = []
    poi_by_candidate: dict[str, ParsedAmapPoi] = {}
    network_attempts = district_response.attempts
    for seed in seeds:
        poi_response = _http_get(
            operation="poi",
            endpoint_path=_POI_PATH,
            parameters={
                "city_limit": "true",
                "keywords": seed,
                "page_num": "1",
                "page_size": str(_MAX_POIS),
                "region": city_adcode,
                "show_fields": "business",
            },
            credential=credential,
        )
        network_attempts += poi_response.attempts
        parsed, observation = _parse_and_bind_poi(poi_response)
        poi_observations.append((seed, observation))
        for poi in parsed.pois:
            if _normalized(poi.name) == _normalized(seed):
                poi_by_candidate[_candidate_id(poi.record_id)] = poi
    projection = _project(
        city=city,
        city_adcode=city_adcode,
        seeds=seeds,
        district=district_observation,
        pois=tuple(poi_observations),
        poi_by_candidate=poi_by_candidate,
        selection_reader=selection_reader,
        selection_choices=selection_choices,
        interactive_selection=interactive_selection,
    )
    place_results, selected_places, status_counts = _place_resolution(
        seeds=seeds,
        projection=projection,
        poi_by_candidate=poi_by_candidate,
    )
    (
        ordered_places,
        route_cache,
        warnings,
        route_evaluations,
        route_attempts,
        route_calls_succeeded,
        route_calls_failed,
    ) = _greedy_route_order(
        selected_places=selected_places,
        transport_mode=transport_mode,
        credential=credential,
    )
    network_attempts += route_attempts
    plan = _build_plan(
        city=city,
        city_adcode=city_adcode,
        district=district,
        start_date=parsed_start_date,
        days=days,
        transport_mode=transport_mode,
        daily_start=parsed_daily_start,
        daily_end=parsed_daily_end,
        visit_minutes=visit_minutes,
        place_results=place_results,
        status_counts=status_counts,
        ordered_places=ordered_places,
        route_cache=route_cache,
        warnings=warnings,
        route_evaluations=route_evaluations,
        network_attempts=network_attempts,
        route_calls_succeeded=route_calls_succeeded,
        route_calls_failed=route_calls_failed,
    )
    plan_path, html_path = _install_output(output_root, plan)
    summary = plan["summary"]
    return {
        "district_success": True,
        "poi_candidate_count": summary["poi_candidate_count"],
        "matched": summary["matched"],
        "ambiguous": summary["ambiguous"],
        "unmatched": summary["unmatched"],
        "scheduled": summary["scheduled"],
        "unscheduled": summary["unscheduled"],
        "route_calls_succeeded": summary["route_calls_succeeded"],
        "route_calls_failed": summary["route_calls_failed"],
        "place_statuses": {
            str(item["input_name"]): {
                "status": str(item["status"]),
                "match_status": str(item["match_status"]),
                "resolution_method": str(item["resolution_method"]),
                "exact_candidate_count": len(item["alternatives"]),
            }
            for item in plan["place_results"]
        },
        "plan_json": str(plan_path),
        "index_html": str(html_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local planning service for a selected destination."
        )
    )
    parser.add_argument("--city", required=True)
    parser.add_argument("--city-adcode", required=True)
    parser.add_argument(
        "--start-date",
        default=date.today().isoformat(),
        help="Trip start date in YYYY-MM-DD format (default: today).",
    )
    parser.add_argument(
        "--must-visit",
        action="append",
        required=True,
        help="Repeat for each requested place.",
    )
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument(
        "--transport-mode",
        choices=tuple(_ROUTE_PATHS),
        required=True,
    )
    parser.add_argument("--daily-start", default="09:00")
    parser.add_argument("--daily-end", default="18:00")
    parser.add_argument("--visit-minutes", type=int, default=120)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def _failure_payload(error: _LiveFailure) -> dict[str, object]:
    return {
        "failure_stage": error.stage,
        "http_status": error.http_status,
        "amap_status": error.amap_status,
        "amap_infocode": error.amap_infocode,
        "python_exception_type": error.python_exception_type,
        "response_bytes_received": error.response_bytes_received,
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        summary = run_simple_live(
            city=arguments.city,
            city_adcode=arguments.city_adcode,
            start_date=arguments.start_date,
            must_visit=tuple(arguments.must_visit),
            days=arguments.days,
            transport_mode=arguments.transport_mode,
            daily_start=arguments.daily_start,
            daily_end=arguments.daily_end,
            visit_minutes=arguments.visit_minutes,
            output_root=arguments.output_root,
        )
    except _LiveFailure as error:
        print(
            json.dumps(
                _failure_payload(error),
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
