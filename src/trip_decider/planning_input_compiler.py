"""City-neutral compilation from DestinationContext to itinerary inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone

from trip_decider.evidence_core import is_confirmed_absent
from trip_decider.evidence_projection import item_facts, usable_fact_values
from trip_decider.itinerary_planner import (
    make_attraction_event,
    make_duration_event,
    make_event,
    make_meal_event,
    make_rail_event,
    resolve_pace_settings,
    resolve_planner_defaults,
)
from trip_decider.travel_agent import DestinationContext


_INSTALLABLE_STATES = {"PARTIAL_READY", "PLAN_READY"}


class PlanningInputCompiler:
    """Compile evidence-backed inputs for the existing itinerary planner."""

    def compile(
        self,
        context: DestinationContext | Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """``now`` 是读取时刻，判定 freshness 用。

        本次只接线不使用：铁路段仍读落盘的 ``snapshot.status``。换成读取时
        token 需要连带翻整份表征基线（见 p4b-baseline-flip-preview.md），
        安排在 agent_actions 四子批之后，好让基线在那批期间保持可用。
        """

        read_at = now if now is not None else datetime.now(timezone.utc)
        payload = (
            context.to_dict()
            if isinstance(context, DestinationContext)
            else deepcopy(dict(context))
        )
        intent = _mapping(payload.get("intent"), "context intent")
        evidence = _evidence_by_domain(payload.get("evidence"))
        earliest = _wall_datetime(
            intent.get("earliest_departure_at"),
            "earliest_departure_at",
        )
        latest = _wall_datetime(
            intent.get("latest_return_at"),
            "latest_return_at",
        )
        if latest <= earliest:
            raise ValueError("travel window must be positive")
        pace = str(intent.get("pace") or "standard")
        pace_values, pace_contract = resolve_pace_settings(
            pace=pace,
            physical_level=None,
            early_start=None,
            night_activity=None,
            transport_tolerance=None,
            depth_preference=None,
            overrides=None,
        )
        defaults, default_contract = resolve_planner_defaults(
            None,
            profile_values=pace_values,
        )
        days = _day_shells(earliest, latest)
        events_by_type: dict[str, list[dict[str, object]]] = {
            event_type: []
            for event_type in (
                "transit",
                "attraction",
                "meal",
                "hotel",
                "buffer",
                "rest",
            )
        }
        blockers: list[dict[str, object]] = []
        dependencies: dict[str, list[str]] = {
            event_type: [] for event_type in events_by_type
        }

        railway = evidence.get("railway")
        _compile_railway(
            railway,
            now=read_at,
            days=days,
            events_by_type=events_by_type,
            dependencies=dependencies,
            blockers=blockers,
        )
        map_item = evidence.get("map")
        web_item = evidence.get("web")
        hotel_area = _hotel_area(web_item)
        _compile_local_transit(
            map_item,
            earliest=earliest,
            latest=latest,
            days=days,
            events_by_type=events_by_type,
            dependencies=dependencies,
            blockers=blockers,
        )
        _compile_attractions(
            map_item,
            web_item,
            earliest=earliest,
            latest=latest,
            max_visit_minutes=int(
                pace_values["max_continuous_attraction_minutes"]
            ),
            lunch_minutes=int(defaults["lunch_minutes"]),
            lunch_window_end=time.fromisoformat(
                str(defaults["lunch_window_end"])
            ),
            inter_event_buffer_minutes=int(
                defaults["inter_event_buffer_minutes"]
            ),
            planner_defaults=defaults,
            days=days,
            events_by_type=events_by_type,
            dependencies=dependencies,
            blockers=blockers,
        )
        _compile_defaults(
            earliest=earliest,
            latest=latest,
            defaults=defaults,
            hotel_area=hotel_area,
            days=days,
            events_by_type=events_by_type,
            dependencies=dependencies,
            blockers=blockers,
        )
        _compile_free_time(
            earliest=earliest,
            latest=latest,
            hotel_area=hotel_area,
            days=days,
            events_by_type=events_by_type,
            dependencies=dependencies,
        )
        _record_evidence_blockers(evidence, blockers)
        raw_hard_conflicts = payload.get("hard_constraint_conflicts")
        if isinstance(raw_hard_conflicts, Sequence) and not isinstance(
            raw_hard_conflicts,
            (str, bytes, bytearray),
        ):
            for index, conflict in enumerate(raw_hard_conflicts, start=1):
                blockers.append(
                    _blocker(
                        f"HARD_CONSTRAINT_CONFLICT_{index}",
                        "constraints",
                        reason=(
                            conflict
                            if isinstance(conflict, str)
                            else "unresolved hard constraint conflict"
                        ),
                        severity="hard",
                    )
                )

        for day in days:
            day["events"].sort(
                key=lambda event: (
                    str(event.get("start_at") or "9999"),
                    str(event.get("event_id") or ""),
                )
            )
            day["conditions"] = [
                blocker["blocker_id"]
                for blocker in blockers
                if blocker.get("day") in {None, day["day"]}
            ]

        unique_blockers = _unique_blockers(blockers)
        rail_events = [
            event
            for event in events_by_type["transit"]
            if str(event.get("event_id", "")).startswith("rail-")
        ]
        local_transit_events = [
            event
            for event in events_by_type["transit"]
            if not str(event.get("event_id", "")).startswith("rail-")
        ]
        destination_resolved = _destination_resolved(map_item, web_item)
        attraction_transit_coverage = all(
            isinstance(event.get("inbound_transit_event_id"), str)
            and bool(str(event["inbound_transit_event_id"]).strip())
            for event in events_by_type["attraction"]
        ) and bool(events_by_type["attraction"])
        hard_constraints_clear = not any(
            blocker.get("severity") == "hard" for blocker in unique_blockers
        )
        display_requirements = {
            "destination_resolved": destination_resolved,
            "outbound_transport": any(
                event.get("event_id") == "rail-outbound"
                for event in rail_events
            ),
            "return_transport": any(
                event.get("event_id") == "rail-return"
                for event in rail_events
            ),
            "attraction": bool(events_by_type["attraction"]),
            "local_transit": bool(local_transit_events),
            "attraction_transit_coverage": attraction_transit_coverage,
            "accommodation_base": hotel_area is not None,
            "hard_constraints_clear": hard_constraints_clear,
        }
        display_requirements["cross_city_transport"] = (
            display_requirements["outbound_transport"]
            and display_requirements["return_transport"]
        )
        missing_requirements = [
            name
            for name, present in display_requirements.items()
            if present is not True and name != "cross_city_transport"
        ]
        if not hard_constraints_clear:
            planning_state = "BLOCKED"
        elif missing_requirements:
            planning_state = "COLLECTING_EVIDENCE"
        elif any(
            blocker.get("severity") != "advisory"
            for blocker in unique_blockers
        ):
            planning_state = "PARTIAL_READY"
        else:
            planning_state = "PLAN_READY"
        displayable = planning_state in _INSTALLABLE_STATES
        status = (
            "PARTIAL_PLAN_WITH_BLOCKERS"
            if unique_blockers
            else "CONDITIONALLY_FEASIBLE"
        )
        return {
            "artifact_kind": "PlanningDraft",
            "planning_state": planning_state,
            "status": status,
            "displayable": displayable,
            "display_status": (
                "DISPLAYABLE_CONDITIONAL_ITINERARY"
                if displayable
                else "SUPPLEMENTING_DATA"
            ),
            "display_requirements": display_requirements,
            "missing_requirements": missing_requirements,
            "days": days,
            "cross_city_rail_events": rail_events,
            "attraction_events": events_by_type["attraction"],
            "local_transit_events": local_transit_events,
            "map_points": _compiled_map_points(map_item, web_item),
            "meal_events": events_by_type["meal"],
            "hotel_events": events_by_type["hotel"],
            "buffer_events": events_by_type["buffer"],
            "rest_events": events_by_type["rest"],
            "evidence_dependencies": dependencies,
            "conditional_blockers": unique_blockers,
            "planner_defaults": default_contract,
            "pace_contract": pace_contract,
        }


def _compile_railway(
    evidence: Mapping[str, object] | None,
    *,
    now: datetime,
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
    blockers: list[dict[str, object]],
) -> None:
    # 判定点 3（p3b-gate-inventory.md §2.1，丙型）。旧实现在此静默 return，
    # 连 blocker 都不产——unknown/conflicting 的铁路证据会让整段编译悄悄跳过，
    # 计划照常生成而用户看不到任何提示（I7 第 2 条）。
    if not _is_usable(evidence):
        blockers.append(
            _blocker(
                "RAILWAY_EVIDENCE_MISSING",
                "railway",
                reason=(
                    evidence.get("missing_reason")
                    if evidence is not None
                    else None
                ),
                fact_id=(
                    str(evidence.get("evidence_id"))
                    if evidence is not None
                    else None
                ),
            )
        )
        return
    value = evidence.get("value")
    if not isinstance(value, Mapping):
        blockers.append(_blocker("RAILWAY_EVIDENCE_MISSING", "railway"))
        return
    if is_confirmed_absent(value):
        # 已核实该时间窗内没有直达车。这是一个确定的结论，不是「没查到」。
        blockers.append(
            _blocker(
                "RAILWAY_NO_DIRECT_TRAIN",
                "railway",
                reason=value.get("scope"),
                fact_id=str(evidence.get("evidence_id")),
            )
        )
        return
    snapshot = value.get("snapshot")
    if not isinstance(snapshot, Mapping):
        blockers.append(_blocker("RAILWAY_SNAPSHOT_UNKNOWN", "railway"))
        return
    snapshot_status = snapshot.get("status")
    if snapshot_status == "STALE":
        blockers.extend(
            (
                _blocker("RAILWAY_SNAPSHOT_STALE", "railway"),
                _blocker(
                    "RAILWAY_AVAILABILITY_UNKNOWN",
                    "railway",
                ),
            )
        )
    evidence_id = str(evidence.get("evidence_id"))
    for direction, prefix in (
        ("outbound", "去程"),
        ("return", "返程"),
    ):
        train = value.get(direction)
        if not isinstance(train, Mapping):
            blockers.append(
                _blocker(
                    f"RAILWAY_{direction.upper()}_MISSING",
                    "railway",
                )
            )
            continue
        event = make_rail_event(
            event_id=f"rail-{direction}",
            train=train,
            name_prefix=prefix,
            fact_refs=[
                str(fact["fact_id"])
                for fact in item_facts(evidence)
                if str(fact.get("field", "")).startswith(
                    (f"snapshot.{direction}.", f"{direction}.")
                )
            ],
        )
        event["second_class_availability"] = (
            "UNKNOWN"
            if snapshot_status in {"STALE", "UNKNOWN"}
            else train.get("second_class_availability", "UNKNOWN")
        )
        event["evidence_dependencies"] = [evidence_id]
        event["location"] = {
            "from": train.get("origin_station"),
            "to": train.get("destination_station"),
            "kind": "intercity_rail",
        }
        _add_event(days, event)
        events_by_type["transit"].append(event)
        dependencies["transit"].append(evidence_id)


def _compile_local_transit(
    evidence: Mapping[str, object] | None,
    *,
    earliest: datetime,
    latest: datetime,
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
    blockers: list[dict[str, object]],
) -> None:
    routes = _value_list(evidence, "local_transit")
    if not routes:
        blockers.append(_blocker("LOCAL_TRANSIT_EVIDENCE_MISSING", "map"))
        return
    evidence_id = str(evidence.get("evidence_id"))
    cursor = _bounded_time(earliest, latest, 1, time(8, 30))
    for index, route in enumerate(routes, start=1):
        duration = route.get("duration_seconds")
        if (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration <= 0
        ):
            blockers.append(
                _blocker("LOCAL_TRANSIT_DURATION_MISSING", "map")
            )
            continue
        start_at = cursor + timedelta(minutes=(index - 1) * 45)
        if start_at >= latest:
            break
        event = make_event(
            event_id=str(route.get("route_id") or f"local-transit-{index}"),
            event_type="transit",
            name=(
                f"{str(route.get('from') or '起点')}→"
                f"{str(route.get('to') or '终点')}"
            ),
            start_at=start_at,
            end_at=min(start_at + timedelta(seconds=duration), latest),
            why="使用地图工具返回的当地交通估计",
            value_origin="api_estimate",
            adjustable=("start_at", "transport_choice"),
            extra={
                "from": route.get("from"),
                "to": route.get("to"),
                "location": {
                    "from": route.get("from"),
                    "to": route.get("to"),
                    "kind": "local_transit",
                },
                "transport_mode": route.get("mode"),
                "duration_seconds": duration,
                "distance_meters": route.get("distance_meters"),
                "from_location": deepcopy(route.get("from_location")),
                "to_location": deepcopy(route.get("to_location")),
                "polyline": deepcopy(route.get("polyline")),
                "retrieved_at": route.get("retrieved_at"),
                "evidence_status": route.get("evidence_status"),
                "fare": deepcopy(
                    route.get(
                        "fare",
                        {"status": "unknown", "amount_cny": None},
                    )
                ),
                "evidence_dependencies": [evidence_id],
                "reference_only": True,
                "schedule_status": (
                    evidence.get("value", {}).get("snapshot_status")
                    if isinstance(evidence.get("value"), Mapping)
                    else None
                ),
            },
        )
        events_by_type["transit"].append(event)
        dependencies["transit"].append(evidence_id)


def _compile_attractions(
    map_item: Mapping[str, object] | None,
    web_item: Mapping[str, object] | None,
    *,
    earliest: datetime,
    latest: datetime,
    max_visit_minutes: int,
    lunch_minutes: int,
    lunch_window_end: time,
    inter_event_buffer_minutes: int,
    planner_defaults: Mapping[str, object],
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
    blockers: list[dict[str, object]],
) -> None:
    candidates: list[tuple[Mapping[str, object], str]] = []
    seen: set[str] = set()
    for evidence in (map_item, web_item):
        if not _is_usable(evidence):
            continue
        evidence_id = str(evidence.get("evidence_id"))
        for value in _value_list(evidence, "attractions"):
            attraction_id = str(
                value.get("attraction_id") or value.get("id") or ""
            )
            if not attraction_id or attraction_id in seen:
                continue
            seen.add(attraction_id)
            candidates.append((value, evidence_id))
    if not candidates:
        blockers.append(_blocker("ATTRACTION_EVIDENCE_MISSING", "web"))
        return
    local_routes = [
        event
        for event in events_by_type["transit"]
        if not str(event.get("event_id", "")).startswith("rail-")
    ]

    def route_position(item: tuple[Mapping[str, object], str]) -> int:
        attraction = item[0]
        name = str(attraction.get("name") or "")
        route_query_name = str(attraction.get("route_query_name") or name)
        for route_index, route in enumerate(local_routes):
            destination = str(route.get("to") or "")
            if (
                name
                and name in destination
                or destination
                and destination in route_query_name
            ):
                return route_index
        return len(local_routes) + len(candidates)

    candidates.sort(key=route_position)
    arrival_ready = _rail_time(
        events_by_type["transit"],
        "rail-outbound",
        "end_at",
    )
    if arrival_ready is not None:
        arrival_ready += timedelta(
            minutes=(
                int(planner_defaults["arrival_buffer_minutes"])
                + int(planner_defaults["hotel_checkin_minutes"])
            )
        )
    return_cutoff = _rail_time(
        events_by_type["transit"],
        "rail-return",
        "start_at",
    )
    if return_cutoff is not None:
        return_cutoff -= timedelta(
            minutes=(
                int(planner_defaults["rail_wait_minutes"])
                + int(planner_defaults["hotel_checkout_minutes"])
            )
        )
    for index, (attraction, evidence_id) in enumerate(candidates, start=1):
        start_at = _bounded_time(
            earliest,
            latest,
            min(index, max(0, len(days) - 1)),
            time(9, 30),
        )
        minutes = attraction.get("visit_minutes", 120)
        if (
            not isinstance(minutes, int)
            or isinstance(minutes, bool)
            or minutes <= 0
        ):
            minutes = 120
        minutes = min(minutes, max_visit_minutes)
        if arrival_ready is not None and start_at.date() == arrival_ready.date():
            start_at = max(start_at, arrival_ready)
        if (
            return_cutoff is not None
            and start_at.date() == return_cutoff.date()
            and start_at + timedelta(minutes=minutes) > return_cutoff
        ):
            blockers.append(
                _blocker(
                    "ATTRACTION_RETAINED_UNSCHEDULED",
                    "web",
                    reason=(
                        f"{attraction.get('name')}在返程候车前没有足够时间，"
                        "保留为未排入候选"
                    ),
                )
            )
            continue
        matching_route = next(
            (
                route
                for route in local_routes
                if (
                    str(attraction.get("name") or "")
                    in str(route.get("to") or "")
                    or str(route.get("to") or "")
                    in str(
                        attraction.get("route_query_name")
                        or attraction.get("name")
                        or ""
                    )
                )
            ),
            None,
        )
        if matching_route is not None:
            matching_route["reference_only"] = False
            route_duration = int(
                matching_route.get("duration_seconds") or 0
            )
            route_end_at = start_at - timedelta(minutes=15)
            matching_route["start_at"] = (
                route_end_at - timedelta(seconds=route_duration)
            ).isoformat(timespec="minutes")
            matching_route["end_at"] = route_end_at.isoformat(
                timespec="minutes"
            )
            _add_event(days, matching_route)
            route_end = matching_route.get("end_at")
            if isinstance(route_end, str):
                start_at = max(
                    start_at,
                    datetime.fromisoformat(route_end)
                    + timedelta(minutes=15),
                )
                latest_lunch_start = datetime.combine(
                    start_at.date(),
                    lunch_window_end,
                ) - timedelta(
                    minutes=(
                        lunch_minutes
                        + inter_event_buffer_minutes
                    )
                )
                minutes = min(
                    minutes,
                    max(
                        30,
                        int(
                            (
                                latest_lunch_start - start_at
                            ).total_seconds()
                            // 60
                        ),
                    ),
                )
        else:
            blockers.append(
                _blocker(
                    "ATTRACTION_TRANSIT_MISSING",
                    "map",
                    reason=(
                        f"{attraction.get('name')}缺少对应的到达交通证据"
                    ),
                )
            )
        end_at = min(start_at + timedelta(minutes=minutes), latest)
        payload = {
            "id": str(
                attraction.get("attraction_id")
                or attraction.get("id")
            ),
            "name": str(attraction.get("name")),
            "features": deepcopy(attraction.get("features", [])),
            "suitable_for": deepcopy(
                attraction.get("suitable_for", [])
            ),
            "scheduling_traits": deepcopy(
                attraction.get("scheduling_traits", [])
            ),
            "opening_hours": deepcopy(
                attraction.get(
                    "opening_hours",
                    {"status": "unknown"},
                )
            ),
            "ticket": deepcopy(
                attraction.get("ticket", {"status": "unknown"})
            ),
        }
        event = make_attraction_event(
            event_id=f"attraction-{payload['id']}",
            attraction=payload,
            start_at=start_at,
            end_at=end_at,
            phase="游览",
            why="按已取得的景点证据编入条件化日程",
        )
        event["location"] = deepcopy(
            attraction.get("location")
            or {
                "name": attraction.get("name"),
                "kind": "attraction",
            }
        )
        event["evidence_dependencies"] = [evidence_id]
        event["inbound_transit_event_id"] = (
            matching_route.get("event_id")
            if matching_route is not None
            else None
        )
        _add_event(days, event)
        events_by_type["attraction"].append(event)
        dependencies["attraction"].append(evidence_id)
        return_route = next(
            (
                route
                for route in local_routes
                if (
                    str(attraction.get("name") or "")
                    in str(route.get("from") or "")
                    and route is not matching_route
                )
            ),
            None,
        )
        if return_route is not None:
            route_start = end_at + timedelta(
                minutes=inter_event_buffer_minutes
            )
            route_duration = int(
                return_route.get("duration_seconds") or 0
            )
            route_end = route_start + timedelta(seconds=route_duration)
            if return_cutoff is None or route_end <= return_cutoff:
                return_route["reference_only"] = False
                return_route["start_at"] = route_start.isoformat(
                    timespec="minutes"
                )
                return_route["end_at"] = route_end.isoformat(
                    timespec="minutes"
                )
                _add_event(days, return_route)


def _compile_defaults(
    *,
    earliest: datetime,
    latest: datetime,
    defaults: Mapping[str, object],
    hotel_area: str | None,
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
    blockers: list[dict[str, object]],
) -> None:
    user_dependency = "confirmed-travel-intent"
    if hotel_area is None:
        blockers.append(_blocker("HOTEL_SELECTION_MISSING", "web"))
        hotel_area = "住宿地点待用户确认"
    else:
        blockers.append(
            _blocker(
                "HOTEL_DETAIL_PENDING",
                "web",
                severity="advisory",
                reason=(
                    "具体酒店未选择，当前使用住宿片区或交通枢纽；"
                    "首末段交通待酒店确定后细化"
                ),
            )
        )

    arrival = _rail_time(events_by_type["transit"], "rail-outbound", "end_at")
    if arrival is not None:
        arrival_station = _rail_field(
            events_by_type["transit"],
            "rail-outbound",
            "to",
        )
        buffer_event = make_duration_event(
            event_id="arrival-buffer",
            event_type="buffer",
            name="抵达后缓冲",
            start_at=arrival,
            minutes=int(defaults["arrival_buffer_minutes"]),
            why="使用可编辑的Planner到站缓冲默认约束",
            adjustable=("duration_minutes",),
            extra={"location": arrival_station or "抵达车站"},
        )
        buffer_event["evidence_dependencies"] = [
            "railway-live-query",
            user_dependency,
        ]
        _add_event(days, buffer_event)
        events_by_type["buffer"].append(buffer_event)
        dependencies["buffer"].extend(buffer_event["evidence_dependencies"])
        checkin = make_duration_event(
            event_id="hotel-checkin",
            event_type="hotel",
            name="住宿办理",
            start_at=datetime.fromisoformat(str(buffer_event["end_at"])),
            minutes=int(defaults["hotel_checkin_minutes"]),
            why="使用可编辑的Planner入住默认约束",
            adjustable=("start_at", "duration_minutes", "hotel_choice"),
            extra={"location": hotel_area},
        )
        checkin["evidence_dependencies"] = [user_dependency]
        _add_event(days, checkin)
        events_by_type["hotel"].append(checkin)
        dependencies["hotel"].append(user_dependency)

    departure = _rail_time(
        events_by_type["transit"],
        "rail-return",
        "start_at",
    )
    if departure is not None:
        wait_start = departure - timedelta(
            minutes=int(defaults["rail_wait_minutes"])
        )
        checkout_start = wait_start - timedelta(
            minutes=int(defaults["hotel_checkout_minutes"])
        )
        checkout = make_duration_event(
            event_id="hotel-checkout",
            event_type="hotel",
            name="退房",
            start_at=checkout_start,
            minutes=int(defaults["hotel_checkout_minutes"]),
            why="使用可编辑的Planner退房默认约束",
            adjustable=("start_at", "duration_minutes", "hotel_choice"),
            extra={"location": hotel_area},
        )
        checkout["evidence_dependencies"] = [user_dependency]
        _add_event(days, checkout)
        events_by_type["hotel"].append(checkout)
        dependencies["hotel"].append(user_dependency)
        wait = make_event(
            event_id="rail-wait-buffer",
            event_type="buffer",
            name="高铁候车",
            start_at=wait_start,
            end_at=departure,
            why="使用可编辑的Planner高铁候车默认约束",
            value_origin="planner_default",
            adjustable=("duration_minutes",),
            extra={
                "location": _rail_field(
                    events_by_type["transit"],
                    "rail-return",
                    "from",
                ) or "返程车站",
                "evidence_dependencies": [
                    "railway-live-query",
                    user_dependency,
                ]
            },
        )
        _add_event(days, wait)
        events_by_type["buffer"].append(wait)
        dependencies["buffer"].extend(wait["evidence_dependencies"])

    for attraction in list(events_by_type["attraction"]):
        end_value = attraction.get("end_at")
        attraction_id = attraction.get("attraction_id")
        if not isinstance(end_value, str) or not isinstance(
            attraction_id,
            str,
        ):
            continue
        start_at = datetime.fromisoformat(end_value)
        buffer_end = start_at + timedelta(
            minutes=int(defaults["inter_event_buffer_minutes"])
        )
        day = next(
            (
                item
                for item in days
                if item["date"] == start_at.date().isoformat()
            ),
            None,
        )
        occupied = (
            [
                value
                for value in day["events"]
                if value is not attraction
                and isinstance(value.get("start_at"), str)
                and isinstance(value.get("end_at"), str)
            ]
            if day is not None
            else []
        )
        if any(
            datetime.fromisoformat(str(value["start_at"])) < buffer_end
            and datetime.fromisoformat(str(value["end_at"])) > start_at
            for value in occupied
        ):
            continue
        buffer_event = make_event(
            event_id=f"activity-buffer-{attraction_id}",
            event_type="buffer",
            name="活动间缓冲",
            start_at=start_at,
            end_at=buffer_end,
            why="使用可编辑的Planner活动间缓冲默认约束",
            value_origin="planner_default",
            adjustable=("duration_minutes",),
            extra={
                "remove_with_attraction_id": attraction_id,
                "location": deepcopy(attraction.get("location")),
                "evidence_dependencies": [user_dependency],
            },
        )
        _add_event(days, buffer_event)
        events_by_type["buffer"].append(buffer_event)
        dependencies["buffer"].append(user_dependency)

    def scheduled_meal_start(
        day: Mapping[str, object],
        preferred: datetime,
        minutes: int,
        window_end: datetime | None,
    ) -> tuple[datetime, str | None] | None:
        cursor = max(preferred, earliest)
        events = sorted(
            (
                value
                for value in day["events"]
                if isinstance(value.get("start_at"), str)
                and isinstance(value.get("end_at"), str)
            ),
            key=lambda value: str(value["start_at"]),
        )
        while True:
            end = cursor + timedelta(minutes=minutes)
            overlap = next(
                (
                    value
                    for value in events
                    if datetime.fromisoformat(str(value["start_at"])) < end
                    and datetime.fromisoformat(str(value["end_at"])) > cursor
                ),
                None,
            )
            if overlap is None:
                if end <= latest and (
                    window_end is None or end <= window_end
                ):
                    return cursor, None
                break
            cursor = datetime.fromisoformat(str(overlap["end_at"]))
            if window_end is not None and cursor + timedelta(
                minutes=minutes
            ) > window_end:
                break
        rail = next(
            (
                value
                for value in events
                if str(value.get("event_id"))
                in {"rail-outbound", "rail-return"}
                and datetime.fromisoformat(str(value["start_at"]))
                <= preferred
                < datetime.fromisoformat(str(value["end_at"]))
            ),
            None,
        )
        if rail is not None:
            rail_start = datetime.fromisoformat(str(rail["start_at"]))
            rail_end = datetime.fromisoformat(str(rail["end_at"]))
            meal_at = max(
                rail_start,
                min(preferred, rail_end - timedelta(minutes=minutes)),
            )
            if meal_at + timedelta(minutes=minutes) <= rail_end:
                return meal_at, str(rail["event_id"])
        return None

    for day_index, day in enumerate(days):
        date_value = datetime.fromisoformat(str(day["date"])).date()
        meal_specs = (
            (
                "breakfast",
                time(8, 0),
                int(defaults["breakfast_minutes"]),
                None,
            ),
            (
                "lunch",
                time.fromisoformat(str(defaults["lunch_window_start"])),
                int(defaults["lunch_minutes"]),
                time.fromisoformat(str(defaults["lunch_window_end"])),
            ),
            (
                "dinner",
                time.fromisoformat(str(defaults["dinner_window_start"])),
                int(defaults["dinner_minutes"]),
                time.fromisoformat(str(defaults["dinner_window_end"])),
            ),
        )
        for meal_kind, preferred_clock, minutes, end_clock in meal_specs:
            preferred = datetime.combine(date_value, preferred_clock)
            window_end = (
                datetime.combine(date_value, end_clock)
                if end_clock is not None
                else datetime.combine(date_value, time(10, 0))
            )
            slot = scheduled_meal_start(
                day,
                preferred,
                minutes,
                window_end,
            )
            if slot is None:
                continue
            meal_at, overlaps_event_id = slot
            meal = make_meal_event(
                event_id=f"meal-{meal_kind}-{day_index + 1}",
                meal_kind=meal_kind,
                start_at=meal_at,
                minutes=minutes,
                location=(
                    "列车上（餐食待用户准备）"
                    if overlaps_event_id is not None
                    else _meal_location(
                        meal_at,
                        transit_events=events_by_type["transit"],
                        hotel_area=hotel_area,
                    )
                ),
                why="使用可编辑的Planner餐食默认约束；金额保持unknown",
            )
            if overlaps_event_id is not None:
                meal["overlaps_event_id"] = overlaps_event_id
            meal["evidence_dependencies"] = [user_dependency]
            _add_event(days, meal)
            events_by_type["meal"].append(meal)
            dependencies["meal"].append(user_dependency)

        if day_index < len(days) - 1:
            rest_start = datetime.combine(date_value, time(22, 0))
            rest_end = datetime.combine(
                date_value + timedelta(days=1),
                time(7, 0),
            )
            if rest_start < latest and rest_end > earliest:
                rest = make_event(
                    event_id=f"rest-{day_index + 1}",
                    event_type="rest",
                    name="夜间休息",
                    start_at=max(rest_start, earliest),
                    end_at=min(rest_end, latest),
                    why="使用可编辑的Planner休息默认约束",
                    value_origin="planner_default",
                    adjustable=("start_at", "end_at"),
                    extra={
                        "location": hotel_area,
                        "evidence_dependencies": [user_dependency],
                    },
                )
                _add_event(days, rest)
                events_by_type["rest"].append(rest)
                dependencies["rest"].append(user_dependency)


def _record_evidence_blockers(
    evidence: Mapping[str, Mapping[str, object]],
    blockers: list[dict[str, object]],
) -> None:
    for domain in ("railway", "map", "web"):
        item = evidence.get(domain)
        if item is None:
            blockers.append(_blocker(f"{domain.upper()}_OMITTED", domain))
        elif item.get("status") == "missing":
            blockers.append(
                _blocker(
                    f"{domain.upper()}_MISSING",
                    domain,
                    reason=item.get("missing_reason"),
                )
            )
        elif item.get("status") == "conflicting":
            blockers.append(
                _blocker(f"{domain.upper()}_CONFLICTING", domain)
            )


def _rail_field(
    events: list[dict[str, object]],
    event_id: str,
    field_name: str,
) -> object:
    event = next(
        (value for value in events if value.get("event_id") == event_id),
        None,
    )
    return event.get(field_name) if isinstance(event, Mapping) else None


def _meal_location(
    moment: datetime,
    *,
    transit_events: list[dict[str, object]],
    hotel_area: str,
) -> str:
    outbound = next(
        (
            value
            for value in transit_events
            if value.get("event_id") == "rail-outbound"
        ),
        None,
    )
    returning = next(
        (
            value
            for value in transit_events
            if value.get("event_id") == "rail-return"
        ),
        None,
    )
    if isinstance(outbound, Mapping):
        departure = outbound.get("start_at")
        arrival = outbound.get("end_at")
        if isinstance(departure, str) and moment < datetime.fromisoformat(
            departure
        ):
            return str(outbound.get("from") or "出发地")
        if (
            isinstance(arrival, str)
            and moment < datetime.fromisoformat(arrival)
        ):
            return "列车上（餐食待用户准备）"
    if isinstance(returning, Mapping):
        departure = returning.get("start_at")
        arrival = returning.get("end_at")
        if (
            isinstance(departure, str)
            and isinstance(arrival, str)
            and datetime.fromisoformat(departure)
            <= moment
            < datetime.fromisoformat(arrival)
        ):
            return "列车上（餐食待用户准备）"
        if isinstance(arrival, str) and moment >= datetime.fromisoformat(
            arrival
        ):
            return str(returning.get("to") or "返回地")
    return hotel_area


def _compile_free_time(
    *,
    earliest: datetime,
    latest: datetime,
    hotel_area: str | None,
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
) -> None:
    """Make daytime gaps visible without treating them as attractions."""

    dependency = "confirmed-travel-intent"
    base = hotel_area or "当日所在地"
    for day in days:
        day_date = datetime.fromisoformat(str(day["date"])).date()
        window_start = max(
            earliest,
            datetime.combine(day_date, time(9, 0)),
        )
        window_end = min(
            latest,
            datetime.combine(day_date, time(18, 0)),
        )
        if window_end <= window_start:
            continue
        occupied: list[tuple[datetime, datetime]] = []
        for event in day["events"]:
            start = event.get("start_at")
            end = event.get("end_at")
            if not isinstance(start, str) or not isinstance(end, str):
                continue
            start_at = max(window_start, datetime.fromisoformat(start))
            end_at = min(window_end, datetime.fromisoformat(end))
            if end_at > start_at:
                occupied.append((start_at, end_at))
        occupied.sort()
        merged: list[tuple[datetime, datetime]] = []
        for start_at, end_at in occupied:
            if not merged or start_at > merged[-1][1]:
                merged.append((start_at, end_at))
            else:
                merged[-1] = (
                    merged[-1][0],
                    max(merged[-1][1], end_at),
                )
        cursor = window_start
        gap_index = 0
        for start_at, end_at in [*merged, (window_end, window_end)]:
            if (start_at - cursor).total_seconds() >= 30 * 60:
                gap_index += 1
                free = make_event(
                    event_id=f"free-day-{day['day']}-{gap_index}",
                    event_type="rest",
                    name="自由活动 / 休息",
                    start_at=cursor,
                    end_at=start_at,
                    why="日程空档显式保留，可由用户调整",
                    value_origin="rule_derived",
                    adjustable=("start_at", "end_at"),
                    extra={
                        "location": base,
                        "free_time": True,
                        "evidence_dependencies": [dependency],
                    },
                )
                _add_event(days, free)
                events_by_type["rest"].append(free)
                dependencies["rest"].append(dependency)
            cursor = max(cursor, end_at)


def _compiled_map_points(
    map_item: Mapping[str, object] | None,
    web_item: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    values = [
        deepcopy(dict(item))
        for item in _value_list(map_item, "map_points")
    ]
    if not _is_usable(web_item):
        return values
    web_value = usable_fact_values(item_facts(web_item))
    if not web_value:
        return values
    raw_web_points = web_value.get("map_points")
    if isinstance(raw_web_points, list):
        values.extend(
            deepcopy(dict(item))
            for item in raw_web_points
            if isinstance(item, Mapping)
        )
    for collection, kind in (
        (web_value.get("attractions"), "attraction"),
        (web_value.get("hotel_candidates"), "hotel_candidate"),
    ):
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, Mapping):
                continue
            position = item.get("location")
            if not isinstance(position, Mapping):
                continue
            values.append(
                {
                    "name": item.get("name"),
                    "kind": kind,
                    "location": deepcopy(position),
                    **deepcopy(dict(position)),
                    "evidence_status": "LIVE",
                    "retrieved_at": web_value.get("retrieved_at"),
                }
            )
    base = web_value.get("hotel_area")
    if isinstance(base, Mapping):
        values.append(
            {
                "name": base.get("name"),
                "kind": "accommodation",
                "location": deepcopy(base.get("location")),
                "longitude": base.get("longitude"),
                "latitude": base.get("latitude"),
                "coordinate_system": base.get(
                    "coordinate_system",
                    "GCJ-02",
                ),
                "evidence_status": "LIVE",
                "retrieved_at": web_value.get("retrieved_at"),
            }
        )
    return values


def _evidence_by_domain(value: object) -> dict[str, Mapping[str, object]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise ValueError("context evidence must be an array")
    result: dict[str, Mapping[str, object]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("context evidence items must be objects")
        domain = item.get("domain")
        if isinstance(domain, str):
            result[domain] = item
    return result


def _value_list(
    evidence: Mapping[str, object] | None,
    key: str,
) -> list[Mapping[str, object]]:
    if not _is_usable(evidence):
        return []
    raw = usable_fact_values(item_facts(evidence)).get(key)
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _hotel_area(evidence: Mapping[str, object] | None) -> str | None:
    if not _is_usable(evidence):
        return None
    hotel = usable_fact_values(item_facts(evidence)).get("hotel_area")
    name = hotel.get("name") if isinstance(hotel, Mapping) else None
    return name.strip() if isinstance(name, str) and name.strip() else None


def _destination_resolved(
    map_item: Mapping[str, object] | None,
    web_item: Mapping[str, object] | None,
) -> bool:
    """Return true only when sourced evidence identifies the destination."""

    map_facts = item_facts(map_item)
    if _is_usable(map_item) and not any(
        is_confirmed_absent(fact.get("value")) for fact in map_facts
    ):
        destination = usable_fact_values(map_facts).get("destination")
        if isinstance(destination, Mapping) and any(
            isinstance(destination.get(field), str)
            and bool(str(destination[field]).strip())
            for field in ("name", "adcode", "provider_record_id")
        ):
            return True
    web_facts = item_facts(web_item)
    if _is_usable(web_item) and not any(
        is_confirmed_absent(fact.get("value")) for fact in web_facts
    ):
        name = usable_fact_values(web_facts).get("destination_official_name")
        if isinstance(name, str) and name.strip():
            return True
    return False


def _day_shells(
    earliest: datetime,
    latest: datetime,
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    cursor = earliest.date()
    while cursor <= latest.date():
        values.append(
            {
                "day": len(values) + 1,
                "date": cursor.isoformat(),
                "events": [],
                "conditions": [],
            }
        )
        cursor += timedelta(days=1)
    return values


def _add_event(
    days: list[dict[str, object]],
    event: dict[str, object],
) -> None:
    raw = event.get("start_at")
    if not isinstance(raw, str):
        return
    date_value = datetime.fromisoformat(raw).date().isoformat()
    day = next((item for item in days if item["date"] == date_value), None)
    if day is not None:
        day["events"].append(event)


def _bounded_time(
    earliest: datetime,
    latest: datetime,
    day_offset: int,
    clock: time,
) -> datetime:
    candidate = datetime.combine(
        earliest.date() + timedelta(days=day_offset),
        clock,
    )
    if candidate < earliest:
        return earliest
    if candidate >= latest:
        return latest - timedelta(minutes=1)
    return candidate


def _rail_time(
    events: Sequence[Mapping[str, object]],
    event_id: str,
    field: str,
) -> datetime | None:
    for event in events:
        if event.get("event_id") == event_id:
            raw = event.get(field)
            return datetime.fromisoformat(raw) if isinstance(raw, str) else None
    return None


def _wall_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError(f"{field} must be local wall time")
    return parsed


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value



_USABLE_STATUSES = frozenset({"sourced", "estimated"})


def _is_usable(evidence: Mapping[str, object] | None) -> bool:
    """该证据是否携带单一可用值（evidence-axes.md §1）。

    ``sourced`` 与 ``estimated`` 都携带；``missing`` 没有值；``conflicting``
    有多个互斥的值，取任何一个都是替用户做裁决。P3b 之前这七处直接与
    ``"sourced"`` 比较，那是三态时期「有值」的唯一说法。
    """

    return (
        evidence is not None
        and str(evidence.get("status")) in _USABLE_STATUSES
    )

def _blocker(
    blocker_id: str,
    domain: str,
    *,
    reason: object = None,
    severity: str = "conditional",
    fact_id: str | None = None,
) -> dict[str, object]:
    suggested_actions = {
        "railway": ["重新查询铁路", "手动填写车次"],
        "map": ["查询高德公交或路线"],
        "web": ["搜索景点、开放时间或住宿片区", "用户补充住宿基地"],
    }
    return {
        "blocker_id": blocker_id,
        "domain": domain,
        "severity": severity,
        # 裁决 8.2 / evidence-axes.md §5.5：结论层不复述证据状态，改为引用。
        # 消费方顺着 fact_id 读该事实的 token，得知是「没结论」还是「打架」。
        **({"fact_id": fact_id} if fact_id else {}),
        "reason": reason,
        "suggested_actions": suggested_actions.get(
            domain,
            ["补充有效证据"],
        ),
    }


def _unique_blockers(
    blockers: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for blocker in blockers:
        blocker_id = str(blocker.get("blocker_id"))
        if blocker_id in seen:
            continue
        seen.add(blocker_id)
        result.append(deepcopy(dict(blocker)))
    return result


__all__ = ["PlanningInputCompiler"]
