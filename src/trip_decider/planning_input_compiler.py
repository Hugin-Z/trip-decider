"""City-neutral compilation from DestinationContext to itinerary inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, time, timedelta

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


class PlanningInputCompiler:
    """Compile evidence-backed inputs for the existing itinerary planner."""

    def compile(
        self,
        context: DestinationContext | Mapping[str, object],
    ) -> dict[str, object]:
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
        _record_evidence_blockers(evidence, blockers)

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
        display_requirements = {
            "cross_city_transport": bool(rail_events),
            "attraction": bool(events_by_type["attraction"]),
            "local_transit": bool(local_transit_events),
            "accommodation_base": hotel_area is not None,
        }
        displayable = all(display_requirements.values())
        status = (
            "PARTIAL_PLAN_WITH_BLOCKERS"
            if unique_blockers
            else "CONDITIONALLY_FEASIBLE"
        )
        return {
            "status": status,
            "displayable": displayable,
            "display_status": (
                "DISPLAYABLE_CONDITIONAL_ITINERARY"
                if displayable
                else "SUPPLEMENTING_DATA"
            ),
            "display_requirements": display_requirements,
            "days": days,
            "cross_city_rail_events": rail_events,
            "attraction_events": events_by_type["attraction"],
            "local_transit_events": local_transit_events,
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
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
    blockers: list[dict[str, object]],
) -> None:
    if evidence is None or evidence.get("status") != "sourced":
        return
    value = evidence.get("value")
    if not isinstance(value, Mapping):
        blockers.append(_blocker("RAILWAY_EVIDENCE_MISSING", "railway"))
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
            snapshot=snapshot,
        )
        event["second_class_availability"] = (
            "UNKNOWN"
            if snapshot_status in {"STALE", "UNKNOWN"}
            else train.get("second_class_availability", "UNKNOWN")
        )
        event["schedule_status"] = snapshot_status
        if snapshot_status == "STALE":
            event["fare"] = {
                **deepcopy(dict(event["fare"])),
                "status": "stale",
            }
        event["evidence_dependencies"] = [evidence_id]
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
            timing_status="estimated",
            value_origin="api_estimate",
            adjustable=("start_at", "transport_choice"),
            extra={
                "from": route.get("from"),
                "to": route.get("to"),
                "duration_seconds": duration,
                "distance_meters": route.get("distance_meters"),
                "fare": deepcopy(
                    route.get(
                        "fare",
                        {"status": "unknown", "amount_cny": None},
                    )
                ),
                "evidence_dependencies": [evidence_id],
            },
        )
        _add_event(days, event)
        events_by_type["transit"].append(event)
        dependencies["transit"].append(evidence_id)


def _compile_attractions(
    map_item: Mapping[str, object] | None,
    web_item: Mapping[str, object] | None,
    *,
    earliest: datetime,
    latest: datetime,
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
    blockers: list[dict[str, object]],
) -> None:
    candidates: list[tuple[Mapping[str, object], str]] = []
    seen: set[str] = set()
    for evidence in (map_item, web_item):
        if evidence is None or evidence.get("status") != "sourced":
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
        event["evidence_dependencies"] = [evidence_id]
        _add_event(days, event)
        events_by_type["attraction"].append(event)
        dependencies["attraction"].append(evidence_id)


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

    for day_index, day in enumerate(days):
        date_value = datetime.fromisoformat(str(day["date"])).date()
        lunch_at = datetime.combine(date_value, time(12, 0))
        if earliest <= lunch_at < latest:
            meal = make_meal_event(
                event_id=f"meal-lunch-{day_index + 1}",
                meal_kind="lunch",
                start_at=lunch_at,
                minutes=int(defaults["lunch_minutes"]),
                location=hotel_area,
                why="使用可编辑的Planner午餐默认约束",
            )
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
                    timing_status="estimated",
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

    arrival = _rail_time(events_by_type["transit"], "rail-outbound", "end_at")
    if arrival is not None:
        buffer_event = make_duration_event(
            event_id="arrival-buffer",
            event_type="buffer",
            name="抵达后缓冲",
            start_at=arrival,
            minutes=int(defaults["arrival_buffer_minutes"]),
            why="使用可编辑的Planner到站缓冲默认约束",
            adjustable=("duration_minutes",),
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
            timing_status="estimated",
            value_origin="planner_default",
            adjustable=("duration_minutes",),
            extra={
                "evidence_dependencies": [
                    "railway-live-query",
                    user_dependency,
                ]
            },
        )
        _add_event(days, wait)
        events_by_type["buffer"].append(wait)
        dependencies["buffer"].extend(wait["evidence_dependencies"])


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
    if evidence is None or evidence.get("status") != "sourced":
        return []
    value = evidence.get("value")
    raw = value.get(key) if isinstance(value, Mapping) else None
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _hotel_area(evidence: Mapping[str, object] | None) -> str | None:
    if evidence is None or evidence.get("status") != "sourced":
        return None
    value = evidence.get("value")
    hotel = value.get("hotel_area") if isinstance(value, Mapping) else None
    name = hotel.get("name") if isinstance(hotel, Mapping) else None
    return name.strip() if isinstance(name, str) and name.strip() else None


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


def _blocker(
    blocker_id: str,
    domain: str,
    *,
    reason: object = None,
    severity: str = "conditional",
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
