"""Live, city-neutral discovery and destination profile collection.

The static destination catalog is deliberately absent from this module.  All
production candidates and planning facts originate in the current run's AMap
queries; missing opening hours, ticket prices and hotel prices stay unknown.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import re

from trip_decider.adapters.contracts import stable_identifier
from trip_decider.simple_live import (
    list_live_top_level_regions,
    search_live_places,
)
from trip_decider.travel_agent import (
    EvidenceItem,
    EvidenceStatus,
    TaskMode,
    TravelAgentError,
    TravelIntent,
)


_THEME_QUERIES = {
    # Start from an explicitly marine facility.  A generic ``海滩`` keyword
    # also returns inland water parks and artificial river beaches, which is
    # not evidence that a destination satisfies a user's coastal intent.
    "海": ("海水浴场", "海滩", "海岛"),
    "海边": ("海水浴场", "海滩", "海岛"),
    "山": ("风景区", "名山"),
    "山水": ("风景区", "自然风光"),
    "古村": ("古村", "古镇"),
    "城市": ("博物馆", "城市广场"),
}


def dynamic_destination_seeds(
    intent: TravelIntent,
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    """Generate current-run candidates from live AMap POI results."""

    if intent.task_mode not in {
        TaskMode.OPEN_DISCOVERY,
        TaskMode.GUIDED_DISCOVERY,
    }:
        raise TravelAgentError("dynamic discovery requires a discovery mode")
    if limit not in {2, 3, 4, 5}:
        raise TravelAgentError("dynamic discovery limit is invalid")
    if intent.task_mode is TaskMode.OPEN_DISCOVERY:
        return _open_destination_seeds(intent, limit=limit)
    region_expression = (
        _clean_region_expression(intent.destination_anchor)
        if intent.task_mode is TaskMode.GUIDED_DISCOVERY else None
    )
    queries = _discovery_queries(intent)
    region = _resolve_guided_region(region_expression, queries[0])
    if region is None:
        raise TravelAgentError(
            "guided destination region could not be resolved live"
        )
    with ThreadPoolExecutor(
        max_workers=min(3, len(queries)),
        thread_name_prefix="dynamic-destination-search",
    ) as executor:
        responses = list(
            executor.map(
                lambda keyword: _safe_live_search(
                    keyword,
                    region,
                    region is not None,
                    25,
                ),
                queries,
            )
        )
    sourced = [
        response
        for response in responses
        if response.get("evidence_status") == "sourced"
    ]
    if not sourced:
        raise TravelAgentError("live destination search returned no evidence")
    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for response in sourced:
        places = response.get("places")
        if not isinstance(places, list):
            continue
        for place in places:
            if not isinstance(place, Mapping):
                continue
            label = (
                place.get("district")
                if region is not None
                else place.get("city")
            )
            if not isinstance(label, str) or not label.strip():
                continue
            identity = str(
                place.get("district_code")
                if region is not None
                else place.get("city_code")
                or label
            )
            groups[identity].append(place)
    ranked = sorted(
        groups.items(),
        key=lambda item: (
            -len({str(value.get("provider_record_id")) for value in item[1]}),
            _group_label(item[1], guided=region is not None),
        ),
    )
    seeds: list[dict[str, object]] = []
    for identity, places in ranked:
        label = _group_label(places, guided=region is not None)
        if not label:
            continue
        gateway = _dynamic_gateway(label, places)
        unique_places: list[Mapping[str, object]] = []
        seen_names: set[str] = set()
        for place in places:
            name = place.get("name")
            if not isinstance(name, str) or name in seen_names:
                continue
            seen_names.add(name)
            unique_places.append(place)
            if len(unique_places) == 4:
                break
        seeds.append(
            {
                "id": stable_identifier(
                    "destination",
                    "trip-decider:dynamic-discovery",
                    identity,
                ),
                "name": label,
                "region_label": label,
                "province": str(places[0].get("province") or ""),
                "planning_city": label,
                "planning_adcode": str(
                    places[0].get("district_code")
                    if region is not None
                    else places[0].get("city_code")
                    or ""
                ),
                "rail_gateway": gateway,
                "gateway_label": gateway or "待核验",
                "themes": list(intent.themes),
                "intensity": "待核验",
                "dynamic_attractions": [
                    {
                        "name": value.get("name"),
                        "category": value.get("category"),
                        "location": deepcopy(value.get("location")),
                    }
                    for value in unique_places
                ],
                "candidate_source": "AMAP_LIVE_POI_SEARCH",
                "retrieved_at": max(
                    str(response.get("retrieved_at") or "")
                    for response in sourced
                ),
            }
        )
        if len(seeds) == limit:
            break
    if len(seeds) < 2:
        raise TravelAgentError(
            "live destination search produced fewer than two candidates"
        )
    return seeds


def _open_destination_seeds(
    intent: TravelIntent,
    *,
    limit: int,
) -> list[dict[str, object]]:
    queries = _discovery_queries(intent)
    try:
        region_response = list_live_top_level_regions()
    except Exception as error:
        raise TravelAgentError(
            "live map region index could not be loaded"
        ) from error
    raw_regions = region_response.get("regions")
    if (
        region_response.get("evidence_status") != "sourced"
        or not isinstance(raw_regions, list)
    ):
        raise TravelAgentError(
            "live map region index did not produce discovery scopes"
        )
    regions = [
        str(item["name"])
        for item in raw_regions
        if isinstance(item, Mapping)
        and isinstance(item.get("name"), str)
    ]
    jobs = [
        (region, queries[0])
        for region in regions
    ]
    with ThreadPoolExecutor(
        max_workers=min(6, len(jobs)),
        thread_name_prefix="open-destination-map-check",
    ) as executor:
        checks = list(
            executor.map(
                lambda job: (
                    job[0],
                    _safe_live_search(job[1], job[0], True, 12),
                ),
                jobs,
            )
        )
    seeds: list[dict[str, object]] = []
    seen_labels: set[str] = set()
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    retrieved_at_by_city: dict[str, str] = {}
    for _region, response in checks:
        places = response.get("places")
        values = [
            value for value in places if isinstance(value, Mapping)
        ] if isinstance(places, list) else []
        if response.get("evidence_status") != "sourced":
            continue
        for value in values:
            label = str(value.get("city") or "").strip()
            if not label:
                continue
            grouped[label].append(value)
            retrieved_at_by_city[label] = max(
                retrieved_at_by_city.get(label, ""),
                str(response.get("retrieved_at") or ""),
            )
    ranked = sorted(
        grouped.items(),
        key=lambda item: (
            -len({str(value.get("provider_record_id")) for value in item[1]}),
            item[0],
        ),
    )
    for label, values in ranked:
        if label in seen_labels:
            continue
        seen_labels.add(label)
        portal = _dynamic_gateway(label, values)
        if portal is None:
            continue
        seeds.append(
            {
                "id": stable_identifier(
                    "destination",
                    "trip-decider:live-open-discovery",
                    f"{label}:{portal}",
                ),
                "name": label,
                "region_label": label,
                "province": str(values[0].get("province") or ""),
                "planning_city": label,
                "planning_adcode": str(
                    values[0].get("city_code") or ""
                ),
                "rail_gateway": portal,
                "gateway_label": portal,
                "themes": list(intent.themes),
                "intensity": "待核验",
                "dynamic_attractions": [
                    {
                        "name": value.get("name"),
                        "category": value.get("category"),
                        "location": deepcopy(value.get("location")),
                    }
                    for value in values[:4]
                ],
                "candidate_source": "AMAP_LIVE_REGION_AND_POI_SEARCH",
                "retrieved_at": retrieved_at_by_city.get(label, ""),
            }
        )
        if len(seeds) == limit:
            break
    if len(seeds) < 2:
        raise TravelAgentError(
            "live station and map checks produced fewer than two candidates"
        )
    return seeds


def collect_live_destination_profile(intent: TravelIntent) -> EvidenceItem:
    """Collect attractions, hotel candidates and a temporary base live."""

    destination = (intent.destination_anchor or "").strip()
    if not destination:
        return EvidenceItem(
            evidence_id="web-live-profile",
            domain="web",
            status=EvidenceStatus.MISSING,
            value=None,
            missing_reason="destination_anchor_not_supplied",
        )
    attraction_queries = _profile_queries(intent)
    jobs = [
        ("attraction", keyword, destination, True)
        for keyword in attraction_queries
    ] + [
        ("hotel", "酒店", destination, True),
        ("station", "火车站", destination, True),
        (
            "origin_station",
            f"{intent.origin}站" if intent.origin else "火车站",
            intent.origin,
            True,
        ),
    ]
    with ThreadPoolExecutor(
        max_workers=min(5, len(jobs)),
        thread_name_prefix="destination-profile-search",
    ) as executor:
        results = list(
            executor.map(
                _search_profile_job,
                jobs,
            )
        )
    sourced = [
        (kind, response)
        for kind, response in results
        if response.get("evidence_status") == "sourced"
    ]
    if not sourced:
        return EvidenceItem(
            evidence_id="web-live-profile",
            domain="web",
            status=EvidenceStatus.MISSING,
            value={"attempted_destination": destination},
            missing_reason="live_destination_profile_unavailable",
        )
    attraction_places: list[Mapping[str, object]] = []
    hotel_places: list[Mapping[str, object]] = []
    station_places: list[Mapping[str, object]] = []
    origin_station_places: list[Mapping[str, object]] = []
    for kind, response in sourced:
        places = response.get("places")
        values = [
            value for value in places if isinstance(value, Mapping)
        ] if isinstance(places, list) else []
        if kind == "attraction":
            attraction_places.extend(values)
        elif kind == "hotel":
            hotel_places.extend(values)
        elif kind == "station":
            station_places.extend(values)
        elif kind == "origin_station":
            origin_station_places.extend(values)
    attractions = _profile_attractions(attraction_places)
    hotels = _profile_hotels(hotel_places)
    base = _temporary_base(destination, station_places)
    retrieved_at = max(
        str(response.get("retrieved_at") or "")
        for _kind, response in sourced
    )
    sources = tuple(
        deepcopy(dict(response["source"]))
        for _kind, response in sourced
        if isinstance(response.get("source"), Mapping)
    )
    value: dict[str, object] = {
        "destination_official_name": destination,
        "retrieved_at": retrieved_at,
        "attractions": attractions,
        "hotel_candidates": hotels,
        "hotel_price_status": "UNKNOWN",
        "hotel_area": base,
        "route_sequence": (
            [str(base["route_query_name"]), *[
                str(item["route_query_name"])
                for item in attractions[:3]
            ]]
            if base is not None and len(attractions) >= 3
            else []
        ),
        "route_segments": (
            [
                [str(base["route_query_name"]), str(item["route_query_name"])]
                for item in attractions[:3]
            ]
            + [
                [str(item["route_query_name"]), str(base["route_query_name"])]
                for item in attractions[:3]
            ]
            if base is not None and len(attractions) >= 3
            else []
        ),
        "map_points": _rail_map_points(
            origin=intent.origin,
            destination=destination,
            origin_stations=origin_station_places,
            destination_stations=station_places,
        ),
        "verified_facts": [
            {
                "field": "poi_identity_and_location",
                "support": "amap_live_poi_search",
                "retrieved_at": retrieved_at,
            },
            {
                "field": "hotel_price",
                "support": "unknown_no_price_source",
                "retrieved_at": retrieved_at,
            },
        ],
        "missing_fields": [
            "酒店实时价格与可订状态",
            "景点开放时间的一手来源",
            "景点门票价格的一手来源",
        ],
    }
    if not attractions:
        return EvidenceItem(
            evidence_id="web-live-profile",
            domain="web",
            status=EvidenceStatus.MISSING,
            value=value,
            sources=sources,
            missing_reason="no_live_attraction_candidates",
        )
    return EvidenceItem(
        evidence_id="web-live-profile",
        domain="web",
        status=EvidenceStatus.SOURCED,
        value=value,
        sources=sources,
    )


def _discovery_queries(intent: TravelIntent) -> tuple[str, ...]:
    values: list[str] = []
    for theme in intent.themes:
        values.extend(_THEME_QUERIES.get(theme, (theme,)))
    if not values:
        values = ["风景区", "旅游景点"]
    return tuple(dict.fromkeys(values))[:3]


def _safe_live_search(
    keyword: str,
    region: str | None,
    city_limit: bool,
    page_size: int,
) -> dict[str, object]:
    try:
        return search_live_places(
            keyword=keyword,
            region=region,
            city_limit=city_limit,
            page_size=page_size,
        )
    except Exception as error:
        return {
            "evidence_status": "missing",
            "missing_reason": "live_search_failed",
            "failure_type": type(error).__name__,
            "network_attempts": 0,
        }


def _search_profile_job(
    job: tuple[str, str, str | None, bool],
) -> tuple[str, dict[str, object]]:
    kind, keyword, region, city_limit = job
    return (
        kind,
        _safe_live_search(keyword, region, city_limit, 20),
    )


def _profile_queries(intent: TravelIntent) -> tuple[str, ...]:
    theme_queries = _discovery_queries(intent)
    return tuple(dict.fromkeys((*theme_queries, "风景区", "旅游景点")))[:3]


def _clean_region_expression(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    result = value
    for token in ("倾向", "优先", "大概想去", "考虑", "那块", "一带", "附近", "区域", "地区"):
        result = result.replace(token, "")
    result = re.sub(r"[\s、/,]+", "", result).strip()
    return result or None


def _resolve_guided_region(
    expression: str | None,
    probe_keyword: str,
) -> str | None:
    if not expression:
        return None
    variants = [expression]
    for width in (2, 3, 4):
        if len(expression) > width:
            variants.append(expression[-width:] + "市")
    for candidate in dict.fromkeys(variants):
        response = _safe_live_search(
            probe_keyword,
            candidate,
            True,
            5,
        )
        places = response.get("places")
        values = [
            item for item in places if isinstance(item, Mapping)
        ] if isinstance(places, list) else []
        root = re.sub(r"[省市县区]$", "", candidate)
        if values and all(
            any(
                root in str(item.get(field) or "")
                for field in ("province", "city", "district")
            )
            for item in values
        ):
            return candidate
    return None


def _group_label(
    places: list[Mapping[str, object]],
    *,
    guided: bool,
) -> str:
    field = "district" if guided else "city"
    value = places[0].get(field) if places else None
    return str(value).strip() if isinstance(value, str) else ""


def _dynamic_gateway(
    label: str,
    places: list[Mapping[str, object]],
) -> str | None:
    region_code = label
    try:
        response = search_live_places(
            keyword="火车站",
            region=str(region_code),
            city_limit=True,
            page_size=20,
        )
    except Exception:
        return None
    values = response.get("places")
    stations = [
        value
        for value in values
        if isinstance(value, Mapping)
        and isinstance(value.get("name"), str)
        and str(value["name"]).endswith("站")
    ] if isinstance(values, list) else []
    root = re.sub(r"[市县区]$", "", label)
    exact = [
        station
        for station in stations
        if str(station["name"]) == f"{root}站"
    ]
    if len(exact) == 1:
        return str(exact[0]["name"]).removesuffix("站")
    matching = [
        station for station in stations if root and root in str(station["name"])
    ]
    selected = matching if matching else stations
    identities = {str(item["name"]) for item in selected}
    if len(identities) != 1:
        return None
    return next(iter(identities)).removesuffix("站")


def _profile_attractions(
    places: list[Mapping[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for place in places:
        name = place.get("name")
        record_id = place.get("provider_record_id")
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(record_id, str)
            or name in seen
        ):
            continue
        seen.add(name)
        result.append(
            {
                "attraction_id": stable_identifier(
                    "attraction",
                    "trip-decider:amap-live-profile",
                    record_id,
                ),
                "name": name,
                "route_query_name": name,
                "features": [str(place.get("category") or "类型待核验")],
                "suitable_for": ["用户需根据实际强度确认"],
                "scheduling_traits": [],
                "visit_minutes": 120,
                "visit_duration_origin": "planner_default",
                "opening_hours": {"status": "unknown"},
                "ticket": {"status": "unknown", "amount_cny": None},
                "location": deepcopy(place.get("location")),
                "district": place.get("district"),
                "address": place.get("address"),
            }
        )
        if len(result) == 3:
            break
    return result


def _profile_hotels(
    places: list[Mapping[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for place in places:
        name = place.get("name")
        if not isinstance(name, str) or not name.strip() or name in seen:
            continue
        seen.add(name)
        result.append(
            {
                "hotel_id": stable_identifier(
                    "hotel",
                    "trip-decider:amap-live-hotel",
                    str(place.get("provider_record_id") or name),
                ),
                "name": name,
                "area": place.get("district"),
                "address": place.get("address"),
                "location": deepcopy(place.get("location")),
                "price": {"status": "UNKNOWN", "amount_cny": None},
                "source": "高德地图 POI Search 2.0",
            }
        )
        if len(result) == 5:
            break
    return result


def _temporary_base(
    destination: str,
    stations: list[Mapping[str, object]],
) -> dict[str, object] | None:
    values = [
        station for station in stations
        if isinstance(station.get("name"), str)
        and str(station["name"]).endswith("站")
        and isinstance(station.get("location"), Mapping)
    ]
    if not values:
        return None
    root = re.sub(r"[市县区]$", "", destination)
    exact = [value for value in values if root and root in str(value["name"])]
    selected = exact[0] if exact else values[0]
    return {
        "name": str(selected["name"]),
        "route_query_name": str(selected["name"]),
        "kind": "temporary_transport_hub",
        "temporary_base": True,
        "specific_hotel_selected": False,
        "location": deepcopy(selected.get("location")),
        "longitude": (
            selected.get("location", {}).get("longitude")
            if isinstance(selected.get("location"), Mapping)
            else None
        ),
        "latitude": (
            selected.get("location", {}).get("latitude")
            if isinstance(selected.get("location"), Mapping)
            else None
        ),
        "coordinate_system": "GCJ-02",
        "price": {"status": "UNKNOWN", "amount_cny": None},
    }


def _rail_map_points(
    *,
    origin: str | None,
    destination: str,
    origin_stations: list[Mapping[str, object]],
    destination_stations: list[Mapping[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for role, label, stations in (
        ("origin", origin, origin_stations),
        ("destination", destination, destination_stations),
    ):
        selected = _station_point(label, stations)
        if selected is None:
            continue
        location = selected.get("location")
        if not isinstance(location, Mapping):
            continue
        station_name = str(selected["name"])
        rail_name = station_name.removesuffix("站")
        result.append(
            {
                "name": rail_name,
                "display_name": station_name,
                "aliases": [station_name],
                "kind": "station",
                "rail_role": role,
                "longitude": location.get("longitude"),
                "latitude": location.get("latitude"),
                "coordinate_system": "GCJ-02",
                "evidence_status": "LIVE",
            }
        )
    return result


def _station_point(
    label: str | None,
    stations: list[Mapping[str, object]],
) -> Mapping[str, object] | None:
    values = [
        station
        for station in stations
        if isinstance(station.get("name"), str)
        and str(station["name"]).endswith("站")
        and isinstance(station.get("location"), Mapping)
    ]
    if not values:
        return None
    root = re.sub(r"[市县区]$", "", str(label or ""))
    exact = [value for value in values if str(value["name"]) == f"{root}站"]
    if len(exact) == 1:
        return exact[0]
    matching = [value for value in values if root and root in str(value["name"])]
    return matching[0] if len(matching) == 1 else None


__all__ = [
    "collect_live_destination_profile",
    "dynamic_destination_seeds",
]
