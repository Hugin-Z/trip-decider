"""Protocol-neutral user read models for trip-decider."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone

from trip_decider.evidence_core import TOKEN_UNKNOWN, FactVerdict
from trip_decider.evidence_projection import (
    is_supported,
    item_facts,
    item_retrieved_at,
    project_domain,
    usable_fact_values,
    verdict_payload,
)
from trip_decider.travel_agent import RunStatus, TaskMode


def _has_usable_hotel_price(usable: Mapping[str, object]) -> bool:
    """可用值里还剩得下房价字段即为真。

    入参已经过 ``usable_fact_values`` 过滤——support 不可用的字段根本不在
    里面。旧实现读落盘的 ``hotel_price_status``，那是写入侧对同一件事的判断
    的复制品；字段级 support 直接回答它，不必拉 freshness 入伙（support 为
    unknown 的字段走不到 freshness 那一步）。
    """

    candidates = usable.get("hotel_candidates")
    if not isinstance(candidates, list):
        return False
    return any(
        isinstance(candidate, Mapping)
        and any(
            "price" in str(key).lower() and value is not None
            for key, value in candidate.items()
        )
        for candidate in candidates
    )


def _planning_draft_read_model(
    run: Mapping[str, object],
) -> dict[str, object] | None:
    """Expose draft progress without exposing draft itinerary projections."""

    result = run.get("result")
    draft = (
        result.get("planning_draft")
        if isinstance(result, Mapping)
        and isinstance(result.get("planning_draft"), Mapping)
        else None
    )
    if not isinstance(draft, Mapping):
        return None
    requirements = draft.get("display_requirements")
    missing = draft.get("missing_requirements")
    blockers = draft.get("conditional_blockers")
    planning_input = (
        draft.get("planning_input")
        if isinstance(draft.get("planning_input"), Mapping)
        else {}
    )
    return {
        "planning_state": result.get("planning_state"),
        "missing_requirements": (
            deepcopy(missing) if isinstance(missing, list) else []
        ),
        "collected_information": {
            "destination_resolved": (
                requirements.get("destination_resolved") is True
                if isinstance(requirements, Mapping)
                else False
            ),
            "outbound_transport": (
                requirements.get("outbound_transport") is True
                if isinstance(requirements, Mapping)
                else False
            ),
            "return_transport": (
                requirements.get("return_transport") is True
                if isinstance(requirements, Mapping)
                else False
            ),
            "attraction_count": len(
                planning_input.get("attraction_events", [])
                if isinstance(planning_input.get("attraction_events"), list)
                else []
            ),
            "local_transit_count": len(
                planning_input.get("local_transit_events", [])
                if isinstance(planning_input.get("local_transit_events"), list)
                else []
            ),
            "accommodation_base": (
                requirements.get("accommodation_base") is True
                if isinstance(requirements, Mapping)
                else False
            ),
        },
        "blockers": (
            [
                deepcopy(dict(item))
                for item in blockers
                if isinstance(item, Mapping)
            ]
            if isinstance(blockers, list)
            else []
        ),
    }


def _map_position(value: object) -> dict[str, object] | None:
    """Normalize an explicitly supplied GCJ-02 point without geocoding."""

    if isinstance(value, Mapping):
        nested = next(
            (
                value.get(key)
                for key in ("position", "coordinates", "center", "location")
                if key in value
            ),
            None,
        )
        if nested is not None:
            point = _map_position(nested)
            if point is not None:
                return point
        longitude = value.get("longitude", value.get("lon"))
        latitude = value.get("latitude", value.get("lat"))
        coordinate_system = value.get(
            "coordinate_system",
            value.get("crs", "GCJ-02"),
        )
    elif (
        isinstance(value, (list, tuple))
        and len(value) == 2
    ):
        longitude, latitude = value
        coordinate_system = "GCJ-02"
    else:
        return None
    if (
        not isinstance(longitude, (int, float))
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or isinstance(latitude, bool)
        or not -180 <= float(longitude) <= 180
        or not -90 <= float(latitude) <= 90
    ):
        return None
    return {
        "longitude": float(longitude),
        "latitude": float(latitude),
        "coordinate_system": str(coordinate_system or "GCJ-02"),
    }


def _map_polyline(value: object) -> list[dict[str, object]]:
    """Return only explicitly persisted route points."""

    raw_points: object = value
    if isinstance(value, Mapping):
        raw_points = next(
            (
                value.get(key)
                for key in ("polyline", "path", "points")
                if key in value
            ),
            None,
        )
    if isinstance(raw_points, str):
        parsed: list[list[float]] = []
        for pair in raw_points.split(";"):
            values = pair.split(",")
            if len(values) != 2:
                return []
            try:
                parsed.append([float(values[0]), float(values[1])])
            except ValueError:
                return []
        raw_points = parsed
    if not isinstance(raw_points, (list, tuple)):
        return []
    points = [
        point
        for item in raw_points
        if (point := _map_position(item)) is not None
    ]
    return points if len(points) >= 2 else []


def _map_payload_contract(
    run: Mapping[str, object],
    *,
    plan_version: int | None,
    now: datetime | None = None,
    evidence: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Project the current plan into a map-only, read-only contract.

    The projection never geocodes a name and never requests or reconstructs a
    route. Missing coordinates and geometry remain explicit.

    ``now`` drives the freshness axis; it is injected so two reads at two
    instants can disagree about freshness while agreeing about structure
    (``invariants.md`` I5).
    """

    read_at = now if now is not None else datetime.now(timezone.utc)

    result = run.get("result")
    plan = (
        result.get("plan")
        if isinstance(result, Mapping)
        and isinstance(result.get("plan"), Mapping)
        else {}
    )
    context = (
        result.get("context")
        if isinstance(result, Mapping)
        and isinstance(result.get("context"), Mapping)
        else {}
    )
    # 证据来自容器 B（调用方注入），不再从 context 里的内联副本派生——
    # A 已收敛（persistence-v2.md §2.1.1）。未注入时回落到 context，
    # 保留是为了让直接拿旧 run 字典调用的测试与历史数据仍读得动。
    raw_evidence = (
        context.get("evidence")
        if isinstance(context.get("evidence"), list)
        else []
    )
    evidence = dict(evidence) if evidence is not None else {
        str(item.get("domain")): item
        for item in raw_evidence
        if isinstance(item, Mapping)
        and isinstance(item.get("domain"), str)
    }

    def evidence_value(domain: str) -> Mapping[str, object]:
        return usable_fact_values(item_facts(evidence.get(domain)))

    def retrieved_at(domain: str) -> str | None:
        return item_retrieved_at(evidence.get(domain))

    verdicts: dict[str, FactVerdict] = {}

    def domain_verdict(domain: str) -> FactVerdict:
        """Grade one evidence domain through the kernel.

        This replaces the old ``snapshot_status`` which read a persisted
        ``snapshot.status`` and fell back to ``LIVE`` whenever the domain key
        merely existed — that fallback rendered failed collection as available
        (baseline B2). Grading now depends only on the axes.
        """

        if domain not in verdicts:
            verdicts[domain] = project_domain(evidence, domain, now=read_at)
        return verdicts[domain]

    map_value = evidence_value("map")
    web_value = evidence_value("web")
    days = (
        plan.get("days")
        if isinstance(plan.get("days"), list)
        else []
    )
    event_days: dict[str, int] = {}
    event_values: list[Mapping[str, object]] = []
    for day in days:
        if not isinstance(day, Mapping):
            continue
        day_number = day.get("day")
        if not isinstance(day_number, int) or isinstance(day_number, bool):
            continue
        raw_events = (
            day.get("events")
            if isinstance(day.get("events"), list)
            else []
        )
        for event in raw_events:
            if not isinstance(event, Mapping):
                continue
            event_values.append(event)
            event_id = event.get("event_id")
            if isinstance(event_id, str):
                event_days[event_id] = day_number

    point_by_name: dict[str, dict[str, object]] = {}
    point_by_event_id: dict[str, dict[str, object]] = {}

    def remember_point(name: object, value: object) -> None:
        if not isinstance(name, str) or not name.strip():
            return
        point = _map_position(value)
        if point is not None:
            point_by_name[name.strip()] = point

    planning_input = (
        plan.get("planning_input")
        if isinstance(plan.get("planning_input"), Mapping)
        else {}
    )
    raw_plan_points = (
        planning_input.get("map_points")
        if isinstance(planning_input.get("map_points"), list)
        else []
    )
    raw_places = (
        raw_plan_points
        if raw_plan_points
        else map_value.get("map_points")
        if isinstance(map_value.get("map_points"), list)
        else map_value.get("places")
    )
    if isinstance(raw_places, list):
        for item in raw_places:
            if isinstance(item, Mapping):
                remember_point(item.get("name"), item)
                aliases = (
                    item.get("aliases")
                    if isinstance(item.get("aliases"), list)
                    else []
                )
                for alias in aliases:
                    remember_point(alias, item)
                point = _map_position(item)
                event_ids = (
                    item.get("event_ids")
                    if isinstance(item.get("event_ids"), list)
                    else []
                )
                if point is not None:
                    for event_id in event_ids:
                        if isinstance(event_id, str) and event_id:
                            point_by_event_id[event_id] = point
    raw_resolutions = map_value.get("local_transit_place_resolutions")
    if isinstance(raw_resolutions, Mapping):
        for name, item in raw_resolutions.items():
            remember_point(name, item)
    hotel_area = (
        web_value.get("hotel_area")
        if isinstance(web_value.get("hotel_area"), Mapping)
        else {}
    )
    remember_point(hotel_area.get("name"), hotel_area)
    for event in event_values:
        remember_point(event.get("name"), event.get("location"))
        remember_point(event.get("from"), event.get("from_location"))
        remember_point(event.get("to"), event.get("to_location"))

    markers_by_name: dict[str, dict[str, object]] = {}

    def add_marker(
        name: object,
        *,
        kind: str,
        display_name: str | None = None,
        event_id: object = None,
        day: int | None = None,
        position: object = None,
        verdict: FactVerdict | None = None,
        collected_at: str | None = None,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            return
        normalized_name = name.strip()
        remember_point(normalized_name, position)
        marker = markers_by_name.setdefault(
            normalized_name,
            {
                "marker_id": f"place-{len(markers_by_name) + 1}",
                "name": normalized_name,
                "display_name": display_name or normalized_name,
                "kind": kind,
                "event_ids": [],
                "days": [],
                "position": point_by_name.get(normalized_name),
                "retrieved_at": collected_at,
                **(
                    verdict_payload(verdict)
                    if verdict is not None
                    else {"token": TOKEN_UNKNOWN}
                ),
            },
        )
        kind_priority = {
            "station": 3,
            "accommodation": 2,
            "attraction": 1,
        }
        if kind_priority.get(kind, 0) > kind_priority.get(
            str(marker.get("kind")),
            0,
        ):
            marker["kind"] = kind
        if display_name:
            marker["display_name"] = display_name
        if marker.get("position") is None:
            marker["position"] = point_by_name.get(normalized_name)
        if isinstance(event_id, str) and event_id not in marker["event_ids"]:
            marker["event_ids"].append(event_id)
        if isinstance(day, int) and day not in marker["days"]:
            marker["days"].append(day)
        # 一个地点可能被多条线索命中；已有支撑的不被无支撑的覆盖。
        if (
            marker.get("token") == TOKEN_UNKNOWN
            and verdict is not None
            and verdict.token != TOKEN_UNKNOWN
        ):
            marker.pop("next_action", None)
            marker.update(verdict_payload(verdict))
            marker["retrieved_at"] = collected_at

    railway_verdict = domain_verdict("railway")
    map_verdict = domain_verdict("map")
    web_verdict = domain_verdict("web")
    rail_origin_name: str | None = None
    rail_destination_name: str | None = None
    if isinstance(raw_places, list):
        for item in raw_places:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name")
            event_ids = (
                item.get("event_ids")
                if isinstance(item.get("event_ids"), list)
                else []
            )
            collected_at = (
                str(item.get("retrieved_at"))
                if isinstance(item.get("retrieved_at"), str)
                else retrieved_at("map")
            )
            for event_id in event_ids or [None]:
                add_marker(
                    name,
                    kind=str(item.get("kind") or "place"),
                    display_name=(
                        str(item.get("display_name"))
                        if isinstance(item.get("display_name"), str)
                        else None
                    ),
                    event_id=event_id,
                    day=(
                        event_days.get(str(event_id))
                        if isinstance(event_id, str)
                        else None
                    ),
                    position=item,
                    verdict=map_verdict,
                    collected_at=collected_at,
                )
            if item.get("rail_role") == "origin" and isinstance(name, str):
                rail_origin_name = name
            if item.get("rail_role") == "destination" and isinstance(name, str):
                rail_destination_name = name

    for event in event_values:
        event_id = event.get("event_id")
        day = event_days.get(str(event_id))
        if isinstance(event_id, str) and event_id in point_by_event_id:
            continue
        if (
            event.get("type") == "transit"
            and str(event_id or "").startswith("rail-")
        ):
            add_marker(
                event.get("from"),
                kind="station",
                display_name=(
                    f"{event.get('from')}站"
                    if isinstance(event.get("from"), str)
                    and not str(event.get("from")).endswith("站")
                    else None
                ),
                event_id=event_id,
                day=day,
                position=(
                    event.get("from_location")
                    or point_by_event_id.get(str(event_id))
                ),
                verdict=railway_verdict,
                collected_at=retrieved_at("railway"),
            )
            add_marker(
                event.get("to"),
                kind="station",
                display_name=(
                    f"{event.get('to')}站"
                    if isinstance(event.get("to"), str)
                    and not str(event.get("to")).endswith("站")
                    else None
                ),
                event_id=event_id,
                day=day,
                position=(
                    event.get("to_location")
                    or point_by_event_id.get(str(event_id))
                ),
                verdict=railway_verdict,
                collected_at=retrieved_at("railway"),
            )
        elif event.get("type") == "attraction":
            add_marker(
                event.get("name"),
                kind="attraction",
                display_name=str(event.get("name")).removesuffix("·游览"),
                event_id=event_id,
                day=day,
                position=(
                    event.get("location")
                    or point_by_event_id.get(str(event_id))
                ),
                verdict=web_verdict,
                collected_at=retrieved_at("web"),
            )
        elif event.get("type") in {"hotel", "rest"}:
            add_marker(
                event.get("location"),
                kind="accommodation",
                event_id=event_id,
                day=day,
                position=(
                    event.get("location")
                    or point_by_event_id.get(str(event_id))
                ),
                verdict=web_verdict,
                collected_at=retrieved_at("web"),
            )
    if hotel_area:
        add_marker(
            hotel_area.get("name"),
            kind="accommodation",
            position=hotel_area,
            verdict=web_verdict,
            collected_at=retrieved_at("web"),
        )

    raw_routes = (
        planning_input.get("local_transit_events")
        if isinstance(planning_input.get("local_transit_events"), list)
        else []
    )
    raw_map_routes = (
        map_value.get("local_transit")
        if isinstance(map_value.get("local_transit"), list)
        else []
    )
    map_route_by_id = {
        str(route.get("route_id")): route
        for route in raw_map_routes
        if isinstance(route, Mapping)
        and isinstance(route.get("route_id"), str)
    }
    attraction_day_by_name = {
        str(event.get("name")).removesuffix("·游览"): event_days.get(
            str(event.get("event_id")),
        )
        for event in event_values
        if event.get("type") == "attraction"
        and isinstance(event.get("name"), str)
    }
    route_polylines: list[dict[str, object]] = []
    for index, route in enumerate(raw_routes, start=1):
        if not isinstance(route, Mapping):
            continue
        route_id = str(route.get("event_id") or route.get("route_id") or (
            f"map-route-{index}"
        ))
        source_route = map_route_by_id.get(route_id, {})
        origin_name = route.get("from")
        destination_name = route.get("to")
        route_day = event_days.get(route_id)
        if route_day is None and isinstance(destination_name, str):
            route_day = attraction_day_by_name.get(
                destination_name.removesuffix("景区"),
            )
        # 路线段的定级跟随 map 域：段上原本携带的 schedule_status 是落盘的
        # 展示态（I1 的清理对象），读取层不再消费它。
        add_marker(
            origin_name,
            kind="transit_stop",
            event_id=route_id,
            day=route_day,
            position=route.get("from_location"),
            verdict=map_verdict,
            collected_at=retrieved_at("map"),
        )
        add_marker(
            destination_name,
            kind="transit_stop",
            event_id=route_id,
            day=route_day,
            position=route.get("to_location"),
            verdict=map_verdict,
            collected_at=retrieved_at("map"),
        )
        geometry = _map_polyline(
            route.get("polyline")
            or route.get("path")
            or source_route.get("polyline")
            or source_route.get("path")
        )
        origin_marker = markers_by_name.get(str(origin_name or ""))
        destination_marker = markers_by_name.get(
            str(destination_name or "")
        )
        has_endpoints = bool(
            origin_marker
            and origin_marker.get("position")
            and destination_marker
            and destination_marker.get("position")
        )
        route_polylines.append(
            {
                "route_id": route_id,
                "event_id": route_id,
                "day": route_day,
                "from_marker_id": (
                    origin_marker.get("marker_id")
                    if origin_marker
                    else None
                ),
                "to_marker_id": (
                    destination_marker.get("marker_id")
                    if destination_marker
                    else None
                ),
                "from": origin_name,
                "to": destination_name,
                "transport_mode": (
                    route.get("transport_mode")
                    or route.get("mode")
                    or source_route.get("mode")
                    or "unknown"
                ),
                **verdict_payload(map_verdict),
                "retrieved_at": retrieved_at("map"),
                "geometry_status": (
                    "EXISTING_POLYLINE"
                    if geometry
                    else "ENDPOINTS_ONLY"
                    if has_endpoints
                    else "MISSING_GEOMETRY"
                ),
                "polyline": geometry,
                "distance_meters": route.get("distance_meters"),
                "duration_seconds": route.get("duration_seconds"),
                "route_kind": "local",
            }
        )

    if rail_origin_name and rail_destination_name:
        origin_marker = markers_by_name.get(rail_origin_name)
        destination_marker = markers_by_name.get(rail_destination_name)
        origin_position = (
            origin_marker.get("position") if origin_marker else None
        )
        destination_position = (
            destination_marker.get("position")
            if destination_marker
            else None
        )
        if origin_position is not None and destination_position is not None:
            for event_id in ("rail-outbound", "rail-return"):
                route_polylines.append(
                    {
                        "route_id": f"railway-schematic-{event_id}",
                        "event_id": event_id,
                        "day": event_days.get(event_id),
                        "from_marker_id": origin_marker.get("marker_id"),
                        "to_marker_id": destination_marker.get("marker_id"),
                        "from": rail_origin_name,
                        "to": rail_destination_name,
                        "transport_mode": "railway",
                        **verdict_payload(railway_verdict),
                        "retrieved_at": retrieved_at("railway"),
                        "geometry_status": "SCHEMATIC",
                        "polyline": [origin_position, destination_position],
                        "distance_meters": None,
                        "duration_seconds": None,
                        "route_kind": "railway_schematic",
                    }
                )

    markers = list(markers_by_name.values())
    for marker in markers:
        marker["event_id"] = sorted(marker.pop("event_ids"))
        marker["day"] = sorted(marker.pop("days"))
    return {
        "plan_version": plan_version,
        "day": [
            {
                "day": day.get("day"),
                "date": day.get("date"),
            }
            for day in days
            if isinstance(day, Mapping)
        ],
        "markers": markers,
        "route_polylines": route_polylines,
    }


def _presentation_contract(
    run: Mapping[str, object],
    event_values: list[Mapping[str, object]] | None = None,
    *,
    evidence: Mapping[str, Mapping[str, object]] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Project runtime facts into the canonical user presentation contract.

    ``now`` drives the freshness axis (``invariants.md`` I5); it is injected
    rather than read so the projection stays a pure function of its inputs.
    """

    read_at = now if now is not None else datetime.now(timezone.utc)
    intent_value = run.get("intent")
    guided_confirmation: dict[str, object] = {
        "show_guided_action": False,
    }
    if (
        isinstance(intent_value, Mapping)
        and intent_value.get("task_mode")
        == TaskMode.GUIDED_DISCOVERY.value
    ):
        guided_confirmation = {
            "show_guided_action": True,
        }
    result = run.get("result")
    plan = result.get("plan") if isinstance(result, Mapping) else None
    context = (
        result.get("context")
        if isinstance(result, Mapping)
        and isinstance(result.get("context"), Mapping)
        else {}
    )
    # 此前这里从 context 派生一份证据表，而本函数**同时**还收着一个
    # ``evidence=`` 参数（容器 B）——两份并存正是 A/B 副本问题的现场。
    # A 收敛后只留注入的那一份（persistence-v2.md §2.1.1）；未注入时回落到
    # context，供历史数据与直接传 run 字典的测试使用。
    context_evidence = (
        context.get("evidence")
        if isinstance(context.get("evidence"), list)
        else []
    )
    evidence_by_domain = dict(evidence) if evidence else {
        str(item.get("domain")): item
        for item in context_evidence
        if isinstance(item, Mapping)
        and isinstance(item.get("domain"), str)
    }

    context_verdicts: dict[str, FactVerdict] = {}

    def context_verdict(domain: str) -> FactVerdict:
        if domain not in context_verdicts:
            context_verdicts[domain] = project_domain(
                evidence_by_domain,
                domain,
                now=read_at,
            )
        return context_verdicts[domain]

    def absent_verdict(domain: str, reason: str) -> FactVerdict:
        """A domain with no planned events is unknown, not merely missing."""

        return project_domain({}, domain, now=read_at, absent_reason=reason)

    def context_retrieved_at(domain: str) -> str | None:
        return item_retrieved_at(evidence_by_domain.get(domain))

    days = plan.get("days") if isinstance(plan, Mapping) else None
    safe_days = days if isinstance(days, list) else []
    events = [
        event
        for day in safe_days
        if isinstance(day, Mapping)
        for event in (
            day.get("events")
            if isinstance(day.get("events"), list)
            else []
        )
        if isinstance(event, Mapping)
    ]
    rail_events = [
        event
        for event in events
        if str(event.get("event_id", "")).startswith("rail-")
    ]
    attraction_events = [
        event for event in events if event.get("type") == "attraction"
    ]
    timeline_local_transit = [
        event
        for event in events
        if event.get("type") == "transit"
        and not str(event.get("event_id", "")).startswith("rail-")
    ]
    planning_input = (
        plan.get("planning_input")
        if isinstance(plan, Mapping)
        and isinstance(plan.get("planning_input"), Mapping)
        else {}
    )
    planned_local_transit = (
        plan.get("local_transit_events")
        if isinstance(plan, Mapping)
        and isinstance(plan.get("local_transit_events"), list)
        else planning_input.get("local_transit_events")
        if isinstance(planning_input.get("local_transit_events"), list)
        else timeline_local_transit
    )
    local_transit_events = [
        event
        for event in planned_local_transit
        if isinstance(event, Mapping)
    ]
    requirements = (
        plan.get("display_requirements")
        if isinstance(plan, Mapping)
        and isinstance(plan.get("display_requirements"), Mapping)
        else {}
    )
    # 四个展示域各自映射到一个证据域。有计划事件时定级跟随该证据域；没有事件
    # 时该域根本没有结论，判 unknown——旧代码在这里让「没有事件」与「采集失败」
    # 共用同一个词，两者无法区分。
    railway_verdict = (
        context_verdict("railway")
        if rail_events
        else absent_verdict("railway", "no_source_found")
    )
    attraction_verdict = (
        context_verdict("web")
        if attraction_events
        else absent_verdict("web", "no_source_found")
    )
    local_transit_verdict = (
        context_verdict("map")
        if local_transit_events
        else absent_verdict("map", "no_source_found")
    )
    accommodation_verdict = (
        context_verdict("web")
        if requirements.get("accommodation_base") is True
        else absent_verdict("web", "no_source_found")
    )
    detailed_ready = (
        len(safe_days) > 0
        and len(attraction_events) >= 3
        and len(local_transit_events) >= len(attraction_events)
        and is_supported(railway_verdict)
        and is_supported(accommodation_verdict)
    )
    blockers = (
        plan.get("conditional_blockers")
        if isinstance(plan, Mapping)
        and isinstance(plan.get("conditional_blockers"), list)
        else []
    )
    budget_events = list(events)
    budget_event_ids = {
        str(event.get("event_id"))
        for event in budget_events
        if event.get("event_id") is not None
    }
    for event in local_transit_events:
        event_id = str(event.get("event_id"))
        if event_id not in budget_event_ids:
            budget_events.append(event)
            budget_event_ids.add(event_id)
    web_value = usable_fact_values(item_facts(evidence_by_domain.get("web")))
    return {
        "day_count": len(safe_days),
        "event_count": len(events),
        "attraction_count": len(attraction_events),
        "local_transit_count": len(local_transit_events),
        "detailed_itinerary_ready": detailed_ready,
        "detail_gate": {
            "minimum_attractions": 3,
            "minimum_local_transit": "one base-to-attraction segment plus "
            "the attraction chain",
        },
        "evidence_statuses": [
            {
                "domain": "railway",
                "label": "跨城铁路",
                "count": len(rail_events),
                "retrieved_at": context_retrieved_at("railway"),
                **verdict_payload(railway_verdict),
            },
            {
                "domain": "attraction",
                "label": "景点",
                "count": len(attraction_events),
                "retrieved_at": context_retrieved_at("web"),
                **verdict_payload(attraction_verdict),
            },
            {
                "domain": "local_transit",
                "label": "当地交通",
                "count": len(local_transit_events),
                "retrieved_at": context_retrieved_at("map"),
                **verdict_payload(local_transit_verdict),
            },
            {
                "domain": "accommodation",
                "label": "住宿基地",
                "count": 1 if is_supported(accommodation_verdict) else 0,
                "retrieved_at": context_retrieved_at("web"),
                **verdict_payload(accommodation_verdict),
            },
        ],
        "blockers": [dict(item) for item in blockers if isinstance(item, Mapping)],
        "guided_confirmation": guided_confirmation,
        "compact_progress": _compact_progress_contract(
            run,
            event_values or [],
        ),
        "planning_handoff": _planning_handoff_contract(
            run,
            evidence=evidence,
            now=read_at,
        ),
        "budget_summary": _budget_summary(
            budget_events,
            (
                int(intent_value.get("travelers"))
                if isinstance(intent_value, Mapping)
                and isinstance(intent_value.get("travelers"), int)
                and not isinstance(intent_value.get("travelers"), bool)
                else 1
            ),
        ),
        "accommodation_choices": {
            "budget_total_cny": (
                intent_value.get("accommodation_budget_total_cny")
                if isinstance(intent_value, Mapping)
                else None
            ),
            "budget_per_night_cny": (
                intent_value.get("accommodation_budget_per_night_cny")
                if isinstance(intent_value, Mapping)
                else None
            ),
            "rooms": (
                intent_value.get("rooms")
                if isinstance(intent_value, Mapping)
                else None
            ),
            # 走 support 轴不走 token：房价字段 support 为 unknown 时它根本
            # 到不了 freshness 那一步，拉 freshness 入伙只会多一层无谓判定
            # （p4b-baseline-flip-preview-v2 沿用 v1 §5.2.2）。
            "price_filter_status": (
                "AVAILABLE"
                if _has_usable_hotel_price(web_value)
                else "UNAVAILABLE_NO_PRICE_SOURCE"
            ),
            "current_base": deepcopy(web_value.get("hotel_area")),
            "candidates": deepcopy(
                web_value.get("hotel_candidates", [])
            ),
            "retrieved_at": context_retrieved_at("web"),
        },
    }


def _planning_handoff_contract(
    run: Mapping[str, object],
    *,
    evidence: Mapping[str, Mapping[str, object]] | None = None,
    now: datetime | None = None,
) -> dict[str, object] | None:
    read_at = now if now is not None else datetime.now(timezone.utc)
    intent = run.get("intent")
    result = run.get("result")
    if (
        not isinstance(intent, Mapping)
        or intent.get("task_mode") != TaskMode.DIRECT_PLAN.value
        or not isinstance(result, Mapping)
        or result.get("stage") != "guided_discovery"
    ):
        return None
    destination = intent.get("destination_anchor")
    options = result.get("options")
    if not isinstance(destination, str) or not isinstance(options, list):
        return None
    selected = next(
        (
            option
            for option in options
            if isinstance(option, Mapping)
            and option.get("destination_anchor") == destination
        ),
        None,
    )
    if not isinstance(selected, Mapping):
        return None
    live = evidence or {}
    railway = live.get("railway")
    web = live.get("web")
    map_item = live.get("map")
    web_value = usable_fact_values(item_facts(web))
    map_value = usable_fact_values(item_facts(map_item))
    railway_value = usable_fact_values(item_facts(railway))
    attractions = [
        {
            "attraction_id": item.get("attraction_id") or item.get("id"),
            "name": item.get("name"),
            "features": list(item.get("features", []))
            if isinstance(item.get("features"), list)
            else [],
            "scheduling_traits": list(item.get("scheduling_traits", []))
            if isinstance(item.get("scheduling_traits"), list)
            else [],
            "opening_hours": dict(item.get("opening_hours", {}))
            if isinstance(item.get("opening_hours"), Mapping)
            else {"status": "unknown"},
            "ticket": dict(item.get("ticket", {}))
            if isinstance(item.get("ticket"), Mapping)
            else {"status": "unknown"},
        }
        for item in (
            web_value.get("attractions")
            if isinstance(web_value.get("attractions"), list)
            else []
        )
        if isinstance(item, Mapping)
        and isinstance(item.get("name"), str)
    ]
    local_transit = [
        {
            key: item.get(key)
            for key in (
                "from",
                "to",
                "duration_seconds",
                "distance_meters",
                "fare",
            )
        }
        for item in (
            map_value.get("local_transit")
            if isinstance(map_value.get("local_transit"), list)
            else []
        )
        if isinstance(item, Mapping)
    ]
    dates = _intent_day_skeleton(intent)
    return {
        "destination_anchor": destination,
        "feasibility_status": selected.get("feasibility_status"),
        "roundtrip_transport": dict(
            selected.get("roundtrip_transport")
            if isinstance(selected.get("roundtrip_transport"), Mapping)
            else {}
        ),
        "playable_time_seconds": selected.get("playable_time_seconds"),
        "budget_headroom_after_known_transport_cny": selected.get(
            "budget_headroom_after_known_transport_cny"
        ),
        "evidence_statuses": [
            dict(item)
            for item in (
                selected.get("evidence_statuses")
                if isinstance(selected.get("evidence_statuses"), list)
                else []
            )
            if isinstance(item, Mapping)
        ],
        "evidence_missing": [
            str(item)
            for item in (
                selected.get("evidence_missing")
                if isinstance(selected.get("evidence_missing"), list)
                else []
            )
        ],
        "railway": {
            # 旧实现直接透传落盘的 snapshot.status。那是持久化的展示态，
            # 读取层不再消费它——定级一律走内核。
            **verdict_payload(
                project_domain(
                    {"railway": railway} if isinstance(railway, Mapping) else {},
                    "railway",
                    now=read_at,
                )
            ),
            "retrieved_at": (
                railway_value.get("snapshot", {}).get("retrieved_at")
                if isinstance(railway_value.get("snapshot"), Mapping)
                else None
            ),
            "outbound": dict(railway_value.get("outbound", {}))
            if isinstance(railway_value.get("outbound"), Mapping)
            else None,
            "return": dict(railway_value.get("return", {}))
            if isinstance(railway_value.get("return"), Mapping)
            else None,
            "roundtrip_fare_cny": railway_value.get(
                "roundtrip_fare_cny"
            ),
        },
        "hotel_area": (
            dict(web_value.get("hotel_area", {}))
            if isinstance(web_value.get("hotel_area"), Mapping)
            else None
        ),
        "attractions": attractions,
        "local_transit": local_transit,
        "days": dates,
    }


def _intent_day_skeleton(
    intent: Mapping[str, object],
) -> list[dict[str, object]]:
    earliest = intent.get("earliest_departure_at")
    latest = intent.get("latest_return_at")
    if not isinstance(earliest, str) or not isinstance(latest, str):
        return []
    try:
        first = datetime.fromisoformat(earliest).date()
        last = datetime.fromisoformat(latest).date()
    except ValueError:
        return []
    days: list[dict[str, object]] = []
    cursor = first
    while cursor <= last:
        days.append(
            {
                "day": len(days) + 1,
                "date": cursor.isoformat(),
            }
        )
        cursor = cursor.fromordinal(cursor.toordinal() + 1)
    return days


def _budget_summary(
    events: list[Mapping[str, object]],
    travelers: int,
) -> list[dict[str, object]]:
    rows = {
        "railway": {
            "label": "铁路",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": False,
        },
        "local_transit": {
            "label": "当地交通",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": False,
        },
        "accommodation": {
            "label": "住宿",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": True,
        },
        "tickets": {
            "label": "门票",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": False,
        },
        "meals": {
            "label": "餐饮",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": True,
        },
        "contingency": {
            "label": "机动",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": True,
        },
    }
    for event in events:
        event_id = str(event.get("event_id") or "")
        fare = event.get("fare")
        amount = (
            fare.get("amount_cny")
            if isinstance(fare, Mapping)
            else None
        )
        if event_id in {"rail-outbound", "rail-return"}:
            if isinstance(amount, (int, float)) and not isinstance(
                amount,
                bool,
            ):
                rows["railway"]["known_cny"] += float(amount) * travelers
            else:
                rows["railway"]["unknown"] = True
        elif event.get("type") == "transit":
            if isinstance(amount, (int, float)) and not isinstance(
                amount,
                bool,
            ):
                rows["local_transit"]["estimated_cny"] += (
                    float(amount) * travelers
                )
            else:
                rows["local_transit"]["unknown"] = True
        elif event.get("type") == "attraction":
            ticket = event.get("ticket")
            ticket_amount = (
                ticket.get("amount_cny")
                if isinstance(ticket, Mapping)
                else None
            )
            if isinstance(ticket_amount, (int, float)) and not isinstance(
                ticket_amount,
                bool,
            ):
                rows["tickets"]["known_cny"] += (
                    float(ticket_amount) * travelers
                )
            else:
                rows["tickets"]["unknown"] = True
    return list(rows.values())


def _compact_progress_contract(
    run: Mapping[str, object],
    events: list[Mapping[str, object]],
) -> dict[str, object] | None:
    guided = _guided_progress_contract(run, events)
    if guided is not None:
        candidate_count = max(1, int(guided["candidate_count"]))
        completed_count = min(
            candidate_count,
            int(guided["completed_count"]),
        )
        return {
            "kind": "guided_comparison",
            "state": (
                "running"
                if guided["running"]
                else "completed"
                if guided["completed"]
                else "waiting"
            ),
            "total_count": candidate_count,
            "completed_count": completed_count,
            "percent_complete": min(
                50,
                25 + int(25 * completed_count / candidate_count),
            ),
            "current_task": "比较目的地方案",
            "elapsed_seconds": guided["elapsed_seconds"],
            "last_progress_at": guided["last_progress_at"],
            "partial_options": guided["partial_options"],
        }
    intent = run.get("intent")
    if (
        not isinstance(intent, Mapping)
        or intent.get("task_mode") != TaskMode.DIRECT_PLAN.value
        or run.get("status") == RunStatus.AWAITING_CONFIRMATION.value
    ):
        return None
    phase_events: list[Mapping[str, object]] = []
    phase_started_at = run.get("started_at")
    for index, event in enumerate(events):
        if event.get("event_type") in {
            "discovery.option_selected",
            "revision.started",
        }:
            phase_events = events[index:]
            phase_started_at = event.get("occurred_at")
    if not phase_events:
        phase_events = events
    completed: set[str] = set()
    pending: list[str] = []
    current_task = "查询交通与景点"
    last_progress_at: str | None = None
    planner_started = False
    total_count = len(("railway", "web", "map", "planner"))
    tool_labels = {
        "railway": "正在核验跨城铁路",
        "web": "正在补充网页事实",
        "map": "正在补充当地地图与交通",
        "planner": "正在生成详细行程",
    }
    for event in phase_events:
        occurred_at = event.get("occurred_at")
        if isinstance(occurred_at, str):
            last_progress_at = occurred_at
        details = event.get("details")
        if not isinstance(details, Mapping):
            details = {}
        event_type = event.get("event_type")
        tool = details.get("tool")
        if event_type == "planning.actions.initialized":
            initialized_total = details.get("total_actions")
            if isinstance(initialized_total, int) and not isinstance(
                initialized_total,
                bool,
            ):
                total_count = initialized_total
            completed.update(
                str(item)
                for item in details.get("completed_actions", [])
                if str(item) in tool_labels
            )
            pending = [
                str(item)
                for item in details.get("pending_actions", [])
                if str(item) in tool_labels
            ]
            if pending:
                current_task = (
                    "生成详细行程"
                    if pending[0] == "planner"
                    else "查询交通与景点"
                )
        elif (
            event_type in {"planning.evidence.reused", "tool.completed"}
            and str(tool) in tool_labels
        ):
            completed.add(str(tool))
            if str(tool) == "planner":
                current_task = "生成详细行程"
        elif event_type == "tool.started" and str(tool) in tool_labels:
            planner_started = planner_started or str(tool) == "planner"
            current_task = (
                "生成详细行程"
                if planner_started
                else "查询交通与景点"
            )
    status = run.get("status")
    state = (
        "completed"
        if status == RunStatus.COMPLETED.value
        else "blocked"
        if status in {RunStatus.BLOCKED.value, RunStatus.FAILED.value}
        else "running"
        if status == RunStatus.RUNNING.value
        else "waiting"
    )
    if state == "completed":
        current_task = "生成详细行程"
        completed.add("planner")
    evidence_completed = len(completed & {"railway", "web", "map"})
    percent_complete = 50 + int(25 * evidence_completed / 3)
    if planner_started or "planner" in completed:
        percent_complete = max(percent_complete, 75)
    if state == "completed":
        percent_complete = 100
    else:
        percent_complete = min(percent_complete, 99)
    elapsed_seconds = _elapsed_seconds(phase_started_at)
    return {
        "kind": "detailed_planning",
        "state": state,
        "total_count": total_count,
        "completed_count": min(total_count, len(completed)),
        "percent_complete": percent_complete,
        "current_task": current_task,
        "elapsed_seconds": elapsed_seconds,
        "last_progress_at": last_progress_at,
        "partial_options": [],
    }


def _elapsed_seconds(started_at: object) -> int:
    if not isinstance(started_at, str):
        return 0
    try:
        return max(
            0,
            int(
                (
                    datetime.now().astimezone()
                    - datetime.fromisoformat(started_at)
                ).total_seconds()
            ),
        )
    except ValueError:
        return 0


def _guided_progress_contract(
    run: Mapping[str, object],
    events: list[Mapping[str, object]],
) -> dict[str, object] | None:
    intent = run.get("intent")
    if (
        not isinstance(intent, Mapping)
        or intent.get("task_mode") not in {
            TaskMode.OPEN_DISCOVERY.value,
            TaskMode.GUIDED_DISCOVERY.value,
        }
    ):
        return None
    result = run.get("result")
    final_options = (
        result.get("options")
        if isinstance(result, Mapping)
        and result.get("stage") in {
            "open_discovery",
            "guided_discovery",
        }
        and isinstance(result.get("options"), list)
        else []
    )
    streamed: dict[str, dict[str, object]] = {}
    expected_count = 0
    current_task = "等待开始比较"
    last_progress_at: str | None = None
    for event in events:
        event_type = event.get("event_type")
        occurred_at = event.get("occurred_at")
        details = event.get("details")
        if not isinstance(details, Mapping):
            details = {}
        if isinstance(occurred_at, str):
            last_progress_at = occurred_at
        if event_type == "guided.comparison.started":
            count = details.get("candidate_count")
            if isinstance(count, int) and not isinstance(count, bool):
                expected_count = count
            current_task = "正在启动并行核验"
        elif event_type == "guided.candidate.started":
            count = details.get("candidate_count")
            if isinstance(count, int) and not isinstance(count, bool):
                expected_count = count
            current_task = "正在并行核验候选方案"
        elif event_type == "guided.domain.started":
            current_task = _guided_domain_label(details.get("domain"))
        elif event_type == "guided.domain.timeout":
            current_task = "部分数据源超时，继续处理其他方案"
        elif event_type == "guided.candidate.completed":
            option = details.get("option")
            destination_id = details.get("destination_id")
            if isinstance(option, Mapping) and isinstance(
                destination_id,
                str,
            ):
                streamed[destination_id] = dict(option)
            current_task = "已返回一个方案，继续核验其余方案"
    for option in final_options:
        if not isinstance(option, Mapping):
            continue
        destination_id = option.get("destination_id")
        if isinstance(destination_id, str):
            streamed[destination_id] = dict(option)
    if isinstance(result, Mapping):
        expected = result.get("expected_option_count")
        if isinstance(expected, int) and not isinstance(expected, bool):
            expected_count = expected
    started_at = run.get("started_at")
    elapsed_seconds = _elapsed_seconds(started_at)
    status = run.get("status")
    if status == RunStatus.COMPLETED.value:
        current_task = (
            "比较已取消，以下为已取得的部分结果"
            if isinstance(result, Mapping) and result.get("cancelled") is True
            else "区域方案比较完成"
        )
    return {
        "candidate_count": expected_count,
        "completed_count": len(streamed),
        "current_task": current_task,
        "elapsed_seconds": elapsed_seconds,
        "last_progress_at": last_progress_at,
        "running": status == RunStatus.RUNNING.value,
        "completed": status == RunStatus.COMPLETED.value,
        "partial_options": list(streamed.values()),
    }


def _guided_domain_label(value: object) -> str:
    return {
        "railway": "正在核验往返铁路",
        "map": "正在核验目的地地图信息",
        "web": "正在核验网页事实",
    }.get(str(value), "正在核验真实数据")
