"""City-neutral itinerary events, pace constraints, and evaluation."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta


EVENT_TYPES = frozenset(
    {"transit", "attraction", "meal", "hotel", "buffer", "rest"}
)

PLANNER_DEFAULTS: dict[str, object] = {
    "breakfast_minutes": 30,
    "lunch_window_start": "11:30",
    "lunch_window_end": "13:30",
    "lunch_minutes": 60,
    "dinner_window_start": "17:30",
    "dinner_window_end": "20:00",
    "dinner_minutes": 60,
    "arrival_buffer_minutes": 30,
    "rail_wait_minutes": 45,
    "hotel_luggage_minutes": 30,
    "hotel_checkin_minutes": 30,
    "hotel_checkout_minutes": 30,
    "inter_event_buffer_minutes": 10,
    "midday_rest_minutes": 30,
}

PACE_PROFILES: dict[str, dict[str, object]] = {
    "relaxed": {
        "max_attractions_per_day": 1,
        "earliest_departure": "08:00",
        "latest_return": "19:00",
        "lunch_minutes": 75,
        "dinner_minutes": 75,
        "inter_event_buffer_minutes": 20,
        "arrival_buffer_minutes": 45,
        "rail_wait_minutes": 60,
        "midday_rest_minutes": 45,
        "max_daily_active_minutes": 650,
        "max_continuous_attraction_minutes": 90,
        "max_transfers_per_day": 1,
        "default_night_activity": False,
        "drop_low_priority": True,
        "physical_level": "low",
        "early_start": False,
        "night_activity": False,
        "transport_tolerance": "low",
        "depth_preference": "deep",
    },
    "standard": {
        "max_attractions_per_day": 2,
        "earliest_departure": "07:15",
        "latest_return": "20:30",
        "lunch_minutes": 60,
        "dinner_minutes": 60,
        "inter_event_buffer_minutes": 10,
        "arrival_buffer_minutes": 30,
        "rail_wait_minutes": 45,
        "midday_rest_minutes": 30,
        "max_daily_active_minutes": 720,
        "max_continuous_attraction_minutes": 120,
        "max_transfers_per_day": 2,
        "default_night_activity": True,
        "drop_low_priority": True,
        "physical_level": "moderate",
        "early_start": True,
        "night_activity": True,
        "transport_tolerance": "moderate",
        "depth_preference": "balanced",
    },
    "intensive": {
        "max_attractions_per_day": 3,
        "earliest_departure": "06:30",
        "latest_return": "22:00",
        "lunch_minutes": 60,
        "dinner_minutes": 60,
        "inter_event_buffer_minutes": 10,
        "arrival_buffer_minutes": 30,
        "rail_wait_minutes": 45,
        "midday_rest_minutes": 30,
        "max_daily_active_minutes": 840,
        "max_continuous_attraction_minutes": 180,
        "max_transfers_per_day": 3,
        "default_night_activity": True,
        "drop_low_priority": False,
        "physical_level": "high",
        "early_start": True,
        "night_activity": True,
        "transport_tolerance": "high",
        "depth_preference": "highlights",
    },
}

PACE_OVERRIDE_FIELDS = frozenset(
    {
        "max_attractions_per_day",
        "earliest_departure",
        "latest_return",
        "max_daily_active_minutes",
        "max_continuous_attraction_minutes",
        "max_transfers_per_day",
        "default_night_activity",
        "drop_low_priority",
    }
)

_DURATION_DEFAULT_KEYS = {
    key for key in PLANNER_DEFAULTS if key.endswith("_minutes")
}
_TIME_DEFAULT_KEYS = {
    key
    for key in PLANNER_DEFAULTS
    if key.endswith("_start") or key.endswith("_end")
}


def resolve_planner_defaults(
    supplied: Mapping[str, object] | None,
    *,
    profile_values: Mapping[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    overrides = {} if supplied is None else dict(supplied)
    unknown = sorted(set(overrides) - set(PLANNER_DEFAULTS))
    if unknown:
        raise ValueError(
            "unknown planner default fields: " + ", ".join(unknown)
        )
    values = dict(PLANNER_DEFAULTS)
    if profile_values is not None:
        values.update(
            {
                key: profile_values[key]
                for key in PLANNER_DEFAULTS
                if key in profile_values
            }
        )
    values.update(overrides)
    for key in _DURATION_DEFAULT_KEYS:
        value = values[key]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 5 <= value <= 240
        ):
            raise ValueError(f"{key} must be an integer from 5 to 240")
    for key in _TIME_DEFAULT_KEYS:
        value = values[key]
        if not isinstance(value, str):
            raise ValueError(f"{key} must use HH:MM")
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            raise ValueError(f"{key} must use HH:MM") from None
    if values["lunch_window_start"] >= values["lunch_window_end"]:
        raise ValueError("lunch window start must precede end")
    if values["dinner_window_start"] >= values["dinner_window_end"]:
        raise ValueError("dinner window start must precede end")
    contract = {
        key: {
            "value": value,
            "origin": (
                "user_supplied" if key in overrides else "planner_default"
            ),
            "support": "estimated",
            "editable": True,
        }
        for key, value in values.items()
    }
    return values, contract


def resolve_pace_settings(
    *,
    pace: str,
    physical_level: str | None,
    early_start: bool | None,
    night_activity: bool | None,
    transport_tolerance: str | None,
    depth_preference: str | None,
    overrides: Mapping[str, object] | None,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    if pace not in {"relaxed", "standard", "intensive", "custom"}:
        raise ValueError(
            "pace must be relaxed, standard, intensive, or custom"
        )
    base_name = "standard" if pace == "custom" else pace
    values = dict(PACE_PROFILES[base_name])
    explicit: dict[str, object] = {}
    independent = {
        "physical_level": physical_level,
        "early_start": early_start,
        "night_activity": night_activity,
        "transport_tolerance": transport_tolerance,
        "depth_preference": depth_preference,
    }
    for key, value in independent.items():
        if value is not None:
            explicit[key] = value
            values[key] = value
    raw_overrides = {} if overrides is None else dict(overrides)
    unknown = sorted(set(raw_overrides) - PACE_OVERRIDE_FIELDS)
    if unknown:
        raise ValueError(
            "unknown pace override fields: " + ", ".join(unknown)
        )
    explicit.update(raw_overrides)
    values.update(raw_overrides)
    if values["physical_level"] not in {"low", "moderate", "high"}:
        raise ValueError("physical_level must be low, moderate, or high")
    if values["transport_tolerance"] not in {"low", "moderate", "high"}:
        raise ValueError(
            "transport_tolerance must be low, moderate, or high"
        )
    if values["depth_preference"] not in {
        "highlights",
        "balanced",
        "deep",
    }:
        raise ValueError(
            "depth_preference must be highlights, balanced, or deep"
        )
    if not isinstance(values["early_start"], bool):
        raise ValueError("early_start must be a boolean")
    if not isinstance(values["night_activity"], bool):
        raise ValueError("night_activity must be a boolean")
    for key in ("default_night_activity", "drop_low_priority"):
        if not isinstance(values[key], bool):
            raise ValueError(f"{key} must be a boolean")
    for key in ("earliest_departure", "latest_return"):
        value = values[key]
        if not isinstance(value, str):
            raise ValueError(f"{key} must use HH:MM")
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            raise ValueError(f"{key} must use HH:MM") from None
    if values["earliest_departure"] >= values["latest_return"]:
        raise ValueError("earliest departure must precede latest return")
    numeric_bounds = {
        "max_attractions_per_day": (1, 6),
        "max_daily_active_minutes": (240, 960),
        "max_continuous_attraction_minutes": (45, 240),
        "max_transfers_per_day": (0, 6),
    }
    for key, (minimum, maximum) in numeric_bounds.items():
        value = values[key]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not minimum <= value <= maximum
        ):
            raise ValueError(
                f"{key} must be an integer from {minimum} to {maximum}"
            )
    transfer_caps = {"low": 1, "moderate": 2, "high": 3}
    values["max_transfers_per_day"] = min(
        int(values["max_transfers_per_day"]),
        transfer_caps[str(values["transport_tolerance"])],
    )
    physical_caps = {"low": 90, "moderate": 120, "high": 180}
    values["max_continuous_attraction_minutes"] = min(
        int(values["max_continuous_attraction_minutes"]),
        physical_caps[str(values["physical_level"])],
    )
    if not bool(values["early_start"]):
        values["earliest_departure"] = max(
            str(values["earliest_departure"]), "08:00"
        )
    values["default_night_activity"] = (
        bool(values["default_night_activity"])
        and bool(values["night_activity"])
    )
    values["pace"] = pace
    contract = {
        key: {
            "value": value,
            "origin": (
                "user_supplied"
                if key in explicit
                else "pace_profile_default"
            ),
            "editable": True,
        }
        for key, value in values.items()
    }
    return values, contract


def at_date_time(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}")


def make_event(
    *,
    event_id: str,
    event_type: str,
    name: str,
    start_at: datetime | None,
    end_at: datetime | None = None,
    minutes: int | None = None,
    why: str,
    value_origin: str,
    adjustable: Sequence[str] = (),
    branch: str | None = None,
    condition: str | None = None,
    conflicts: Sequence[str] = (),
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unsupported event type: {event_type}")
    if minutes is not None:
        if end_at is not None or start_at is None:
            raise ValueError("minutes requires start_at and excludes end_at")
        end_at = start_at + timedelta(minutes=minutes)
    result: dict[str, object] = {
        "event_id": event_id,
        "type": event_type,
        "name": name,
        "start_at": (
            start_at.isoformat(timespec="minutes")
            if start_at is not None
            else None
        ),
        "end_at": (
            end_at.isoformat(timespec="minutes")
            if end_at is not None
            else None
        ),
        "value_origin": value_origin,
        "why": why,
        "adjustable": list(adjustable),
        "conflicts": list(conflicts),
    }
    if branch is not None:
        result["branch"] = branch
    if condition is not None:
        result["condition"] = condition
    if extra is not None:
        result.update(extra)
    return result


def make_duration_event(
    *,
    event_id: str,
    event_type: str,
    name: str,
    start_at: datetime,
    minutes: int,
    why: str,
    adjustable: Sequence[str],
    branch: str | None = None,
    condition: str | None = None,
    conflicts: Sequence[str] = (),
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return make_event(
        event_id=event_id,
        event_type=event_type,
        name=name,
        start_at=start_at,
        minutes=minutes,
        why=why,
        value_origin="planner_default",
        adjustable=adjustable,
        branch=branch,
        condition=condition,
        conflicts=conflicts,
        extra=extra,
    )


def event_end(value: Mapping[str, object]) -> datetime:
    raw = value.get("end_at")
    if not isinstance(raw, str):
        raise RuntimeError("event end is unavailable")
    return datetime.fromisoformat(raw)


def index_segments(
    transport: Mapping[str, object],
) -> dict[tuple[str, str], dict[str, object]]:
    values = transport.get("segments")
    if not isinstance(values, Sequence):
        raise RuntimeError("public transport segments are unavailable")
    result: dict[tuple[str, str], dict[str, object]] = {}
    for value in values:
        if not isinstance(value, dict):
            raise RuntimeError("public transport segment is invalid")
        result[(str(value["from"]), str(value["to"]))] = value
    return result


def make_transit_event(
    *,
    event_id: str,
    route: Mapping[str, object],
    policy: Mapping[str, object],
    start_at: datetime,
    branch: str | None = None,
    condition: str | None = None,
    why: str = (
        "公共交通优先；道路方式仅在公共交通不可用时比较"
    ),
    backup_rule: str = "仅在公共交通不可用时再比较道路方式",
) -> dict[str, object]:
    origin = str(route["from"])
    destination = str(route["to"])
    primary = route.get("primary")
    if not isinstance(primary, Mapping):
        return make_event(
            event_id=event_id,
            event_type="transit",
            name=f"{origin}→{destination}",
            start_at=start_at,
            why="已先查询公共交通，但没有取得可排程结果",
            value_origin="unknown",
            adjustable=("start_at", "transport_choice"),
            branch=branch,
            condition=condition,
            conflicts=("公共交通时长不可用",),
            extra={
                "from": origin,
                "to": destination,
                "transport_mode": "public_transit",
                "status": "UNKNOWN",
                "fare": {"status": "unknown", "amount_cny": None},
                "board_at": None,
                "alight_at": None,
                "service": None,
                "operating": None,
                "backup": route.get("alternatives", []),
                "reason": route.get("reason"),
            },
        )
    services = primary.get("services")
    first_service = (
        services[0]
        if isinstance(services, list)
        and services
        and isinstance(services[0], Mapping)
        else {}
    )
    return make_event(
        event_id=event_id,
        event_type="transit",
        name=str(policy["published_service"]),
        start_at=start_at,
        end_at=start_at
        + timedelta(seconds=int(primary["duration_seconds"])),
        why=why,
        value_origin="api_estimate_and_sourced_service",
        adjustable=("start_at", "transport_choice"),
        branch=branch,
        condition=condition,
        extra={
            "from": origin,
            "to": destination,
            "transport_mode": "public_transit",
            "status": "estimated",
            "duration_seconds": primary["duration_seconds"],
            "distance_meters": primary["distance_meters"],
            "walking_distance_meters": primary[
                "walking_distance_meters"
            ],
            "transfer_count": (
                max(0, len(services) - 1)
                if isinstance(services, list)
                else None
            ),
            "fare": policy["fare"],
            "board_at": first_service.get("board_at") or origin,
            "alight_at": first_service.get("alight_at") or destination,
            "service": policy["published_service"],
            "operating": policy["operating"],
            "source": [primary["source"], policy["source"]],
            "backup": {
                "status": "not_queried_because_public_transit_available",
                "rule": backup_rule,
                "taxi_fare_cny": None,
                "charter_fare_cny": None,
                "self_drive_cost_cny": None,
            },
        },
    )


#: ``make_rail_event`` 逐个**直取**的车次字段——缺任何一个都会 KeyError。
#:
#: 它是「一个方向排得出车次事件」的充要字段集，三个地方共用同一份：
#:
#: * 提交门（``agent_actions._validate_railway_value``）按它拦；
#: * 手工填写动作的 ``required_fields`` 按它派生；
#: * 编译器（``planning_input_compiler._compile_railway``）按它判定该方向
#:   是否排得出事件，排不出就退回 ``RAILWAY_{}_MISSING``。
#:
#: 常量存在的理由是宿主实测的 P0：声明说要 ``outbound``/``return``/``fare``/
#: ``source``，消费按 ``origin_station`` 取值，四个键全给了照样 KeyError。
#: 两张表不是一张，就会有「过了门死在屋里」（D2）。
#:
#: ``.get()`` 取的字段**不进这里**（票价、余票）：它们缺席是被容忍的，
#: 写进必填集会把可容忍的缺失升级成硬拒绝。
#: 新增直取字段而不同步本常量会让
#: ``test_invariant_i12_validated_evidence_never_crashes_planner`` 转红。
RAIL_EVENT_REQUIRED_TRAIN_FIELDS: tuple[str, ...] = (
    "train_code",
    "departure_at",
    "arrival_at",
    "origin_station",
    "destination_station",
)


def make_rail_event(
    *,
    event_id: str,
    train: Mapping[str, object],
    name_prefix: str,
    fact_refs: Sequence[str] = (),
) -> dict[str, object]:
    # 时刻可靠性不再写死在事件上。事件只说自己出自哪些 fact，读取层拿
    # fact_refs 按读取时刻算 token——同一份计划，明天读和今天读该给出不同的
    # 可靠性结论，冻在盘上的标签做不到这件事。
    why = "行程时刻出自12306采集快照；可靠性由读取时按证据新鲜度判定"
    return make_event(
        event_id=event_id,
        event_type="transit",
        name=f"{name_prefix} {train['train_code']}",
        start_at=datetime.fromisoformat(str(train["departure_at"])),
        end_at=datetime.fromisoformat(str(train["arrival_at"])),
        why=why,
        # value_origin 走 derivation 轴（evidence-axes.md §2.1），与新鲜度
        # 无关：12306 的时刻表无论采集于何时都是官方报数。旧代码把 UNKNOWN
        # 快照降级成 value_origin="unknown"，那是拿 freshness 去改 support。
        value_origin="official_report",
        adjustable=("train_choice",),
        extra={
            "from": train["origin_station"],
            "to": train["destination_station"],
            "transport_mode": "high_speed_rail",
            "fare": {
                "amount_cny": train.get("second_class_fare_cny_per_person"),
            },
            "source": "中国铁路12306",
            "fact_refs": list(fact_refs),
        },
    )


def make_attraction_event(
    *,
    event_id: str,
    attraction: Mapping[str, object],
    start_at: datetime,
    end_at: datetime,
    phase: str,
    why: str,
    branch: str | None = None,
) -> dict[str, object]:
    return make_event(
        event_id=event_id,
        event_type="attraction",
        name=f"{attraction['name']}·{phase}",
        start_at=start_at,
        end_at=end_at,
        why=why,
        value_origin="rule_derived",
        adjustable=("start_at", "duration_minutes"),
        branch=branch,
        extra={
            "attraction_id": attraction["id"],
            "planning_allocation_minutes": int(
                (end_at - start_at).total_seconds() // 60
            ),
            "features": attraction["features"],
            "suitable_for": attraction["suitable_for"],
            "scheduling_traits": attraction["scheduling_traits"],
            "opening_hours": attraction["opening_hours"],
            "ticket": attraction["ticket"],
        },
    )


def make_meal_event(
    *,
    event_id: str,
    meal_kind: str,
    start_at: datetime,
    minutes: int,
    location: str,
    why: str,
    branch: str | None = None,
    condition: str | None = None,
    overlaps_event_id: str | None = None,
    conflicts: Sequence[str] = (),
) -> dict[str, object]:
    extra: dict[str, object] = {
        "meal_kind": meal_kind,
        "location": location,
        "cost": {"status": "unknown", "amount_cny": None},
    }
    if overlaps_event_id is not None:
        extra["overlaps_event_id"] = overlaps_event_id
    return make_duration_event(
        event_id=event_id,
        event_type="meal",
        name={"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐"}[
            meal_kind
        ],
        start_at=start_at,
        minutes=minutes,
        why=why,
        adjustable=(
            "start_at",
            "duration_minutes",
            "daily_meal_budget",
        ),
        branch=branch,
        condition=condition,
        conflicts=conflicts,
        extra=extra,
    )


def schedule_change(
    action: str,
    *,
    attraction: str,
    reason: str,
    from_day: int | None = None,
    to_day: int | None = None,
) -> dict[str, object]:
    if action not in {"moved_day", "removed", "retained_unscheduled"}:
        raise ValueError("unsupported schedule change action")
    result: dict[str, object] = {
        "action": action,
        "attraction": attraction,
        "reason": reason,
    }
    if action == "moved_day":
        if from_day is None or to_day is None:
            raise ValueError("moved_day requires from_day and to_day")
        result.update({"from_day": from_day, "to_day": to_day})
    return result


def conditional_conflict(
    conflict_id: str,
    message: str,
    *,
    severity: str = "conditional",
) -> dict[str, str]:
    return {
        "conflict_id": conflict_id,
        "severity": severity,
        "message": message,
    }


def evaluate_pace(
    *,
    days: Sequence[Mapping[str, object]],
    settings: Mapping[str, object],
) -> dict[str, object]:
    evaluations: list[dict[str, object]] = []
    all_changes: list[dict[str, object]] = []
    for day in days:
        selected_branch = day.get("selected_branch")
        raw_events = day.get("events")
        if not isinstance(raw_events, Sequence):
            raise RuntimeError("day events are unavailable")
        events = [
            event
            for event in raw_events
            if isinstance(event, Mapping)
            and (
                event.get("branch") is None
                or event.get("branch") == selected_branch
            )
        ]
        attraction_ids = {
            str(event["attraction_id"])
            for event in events
            if event.get("type") == "attraction"
            and event.get("attraction_id") is not None
        }
        active_minutes = 0
        continuous_attraction = 0
        transfers_in_day = 0
        local_transit_starts: list[datetime] = []
        local_transit_ends: list[datetime] = []
        unknown_local_transit_end = False
        for event in events:
            start_raw = event.get("start_at")
            end_raw = event.get("end_at")
            start = (
                datetime.fromisoformat(start_raw)
                if isinstance(start_raw, str)
                else None
            )
            end = (
                datetime.fromisoformat(end_raw)
                if isinstance(end_raw, str)
                else None
            )
            duration = (
                int((end - start).total_seconds() // 60)
                if start is not None and end is not None
                else None
            )
            if (
                duration is not None
                and event.get("type") != "rest"
                and event.get("transport_mode") != "high_speed_rail"
                and event.get("overlaps_event_id") is None
            ):
                active_minutes += duration
            if event.get("type") == "attraction" and duration is not None:
                continuous_attraction = max(
                    continuous_attraction, duration
                )
            if event.get("type") == "transit":
                transfer_count = event.get("transfer_count")
                if isinstance(transfer_count, int):
                    transfers_in_day += transfer_count
                if (
                    event.get("transport_mode") != "high_speed_rail"
                    and start is not None
                ):
                    local_transit_starts.append(start)
                if (
                    event.get("transport_mode") != "high_speed_rail"
                    and end is not None
                ):
                    local_transit_ends.append(end)
                if (
                    event.get("transport_mode") != "high_speed_rail"
                    and start is not None
                    and end is None
                ):
                    unknown_local_transit_end = True
        violations: list[str] = []
        conditions: list[str] = []
        if len(attraction_ids) > int(settings["max_attractions_per_day"]):
            violations.append("max_attractions_per_day")
        if active_minutes > int(settings["max_daily_active_minutes"]):
            violations.append("max_daily_active_minutes")
        if continuous_attraction > int(
            settings["max_continuous_attraction_minutes"]
        ):
            violations.append("max_continuous_attraction_minutes")
        if transfers_in_day > int(settings["max_transfers_per_day"]):
            violations.append("max_transfers_per_day")
        if local_transit_starts:
            earliest = min(local_transit_starts).strftime("%H:%M")
            if earliest < str(settings["earliest_departure"]):
                violations.append("earliest_departure")
        else:
            earliest = None
        if local_transit_ends:
            latest = max(local_transit_ends).strftime("%H:%M")
            if latest > str(settings["latest_return"]):
                violations.append("latest_return")
        else:
            latest = None
        if unknown_local_transit_end:
            conditions.append("latest_return_unverified")
        day_status = (
            "CONFLICT"
            if violations
            else "CONDITIONAL"
            if conditions
            else "PASS"
        )
        evaluations.append(
            {
                "day": day["day"],
                "attraction_count": len(attraction_ids),
                "active_minutes": active_minutes,
                "max_continuous_attraction_minutes": (
                    continuous_attraction
                ),
                "transfers_in_day": transfers_in_day,
                "earliest_local_departure": earliest,
                "latest_local_return": latest,
                "violations": violations,
                "conditions": conditions,
                "status": day_status,
            }
        )
        raw_changes = day.get("pace_decisions", [])
        if isinstance(raw_changes, Sequence):
            all_changes.extend(
                dict(change)
                for change in raw_changes
                if isinstance(change, Mapping)
            )
    return {
        "scope": (
            "destination-day minutes exclude intercity rail, overnight rest, "
            "and meals explicitly overlapping rail"
        ),
        "days": evaluations,
        "changes": all_changes,
        "status": (
            "CONFLICT"
            if any(value["status"] == "CONFLICT" for value in evaluations)
            else "CONDITIONAL"
            if any(
                value["status"] == "CONDITIONAL" for value in evaluations
            )
            else "PASS"
        ),
    }


def _selected_events(
    days: Sequence[Mapping[str, object]],
) -> list[tuple[int, int, Mapping[str, object]]]:
    selected: list[tuple[int, int, Mapping[str, object]]] = []
    for day in days:
        raw_events = day.get("events")
        if not isinstance(raw_events, Sequence):
            raise ValueError("day events must be an array")
        selected_branch = day.get("selected_branch")
        for index, event in enumerate(raw_events):
            if not isinstance(event, Mapping):
                raise ValueError("event must be an object")
            if (
                event.get("branch") is not None
                and event.get("branch") != selected_branch
            ):
                continue
            selected.append((int(day["day"]), index, event))
    return selected


def _event_duration_minutes(event: Mapping[str, object]) -> int | None:
    start = event.get("start_at")
    end = event.get("end_at")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    return int(
        (
            datetime.fromisoformat(end) - datetime.fromisoformat(start)
        ).total_seconds()
        // 60
    )


def _event_attraction_id(event: Mapping[str, object]) -> str | None:
    value = event.get("attraction_id")
    return str(value) if isinstance(value, str) and value else None


def _event_removal_attraction_id(
    event: Mapping[str, object],
) -> str | None:
    direct = _event_attraction_id(event)
    if direct is not None:
        return direct
    related = event.get("remove_with_attraction_id")
    return (
        str(related)
        if isinstance(related, str) and related
        else None
    )


def replan_itinerary(
    *,
    previous_days: Sequence[Mapping[str, object]],
    candidate_days: Sequence[Mapping[str, object]],
    settings: Mapping[str, object],
    edits: Mapping[str, object],
) -> dict[str, object]:
    """Apply explicit edits to a regenerated candidate with minimal change."""

    allowed_edit_fields = {
        "must_visit",
        "removed_attraction_ids",
        "forced_days",
        "event_duration_minutes",
        "locked_event_ids",
        "day_start_times",
    }
    unknown = sorted(set(edits) - allowed_edit_fields)
    if unknown:
        raise ValueError("unknown replan edits: " + ", ".join(unknown))

    def string_set(field: str) -> set[str]:
        raw = edits.get(field, [])
        if (
            not isinstance(raw, Sequence)
            or isinstance(raw, (str, bytes))
            or any(not isinstance(value, str) or not value for value in raw)
        ):
            raise ValueError(f"{field} must be an array of non-empty text")
        return set(raw)

    must_visit = string_set("must_visit")
    removed = string_set("removed_attraction_ids")
    locked = string_set("locked_event_ids")
    raw_forced = edits.get("forced_days", {})
    raw_durations = edits.get("event_duration_minutes", {})
    raw_day_starts = edits.get("day_start_times", {})
    if not isinstance(raw_forced, Mapping):
        raise ValueError("forced_days must be an object")
    if not isinstance(raw_durations, Mapping):
        raise ValueError("event_duration_minutes must be an object")
    if not isinstance(raw_day_starts, Mapping):
        raise ValueError("day_start_times must be an object")
    forced_days: dict[str, int] = {}
    for attraction_id, day_number in raw_forced.items():
        if (
            not isinstance(attraction_id, str)
            or not attraction_id
            or not isinstance(day_number, int)
            or isinstance(day_number, bool)
            or day_number < 1
        ):
            raise ValueError("forced_days contains an invalid entry")
        forced_days[attraction_id] = day_number
    duration_edits: dict[str, int] = {}
    for event_id, minutes in raw_durations.items():
        if (
            not isinstance(event_id, str)
            or not event_id
            or not isinstance(minutes, int)
            or isinstance(minutes, bool)
            or not 15 <= minutes <= 720
        ):
            raise ValueError(
                "event_duration_minutes must map event IDs to 15..720"
            )
        duration_edits[event_id] = minutes
    day_start_times: dict[int, str] = {}
    for day_number, clock in raw_day_starts.items():
        if (
            not isinstance(day_number, str)
            or not day_number.isdigit()
            or int(day_number) < 1
            or not isinstance(clock, str)
        ):
            raise ValueError("day_start_times contains an invalid entry")
        try:
            datetime.strptime(clock, "%H:%M")
        except ValueError:
            raise ValueError(
                "day_start_times values must use HH:MM"
            ) from None
        day_start_times[int(day_number)] = clock

    candidate_evaluation = evaluate_pace(
        days=candidate_days,
        settings=settings,
    )
    candidate_violations = {
        int(day["day"]): set(day["violations"])
        for day in candidate_evaluation["days"]
    }
    days = deepcopy(list(candidate_days))
    previous_positions = {
        str(event["event_id"]): (day, index, deepcopy(dict(event)))
        for day, index, event in _selected_events(previous_days)
    }
    conflicts: list[dict[str, object]] = []
    explicit_changes: list[dict[str, object]] = []
    retained_unscheduled: list[dict[str, object]] = []
    event_change_reasons: dict[str, str] = {}
    attraction_change_reasons: dict[str, str] = {}
    attempts: list[dict[str, object]] = []

    def shift_day_payload(
        day: dict[str, object],
        *,
        from_date: str,
        to_date: str,
    ) -> None:
        delta = (
            datetime.fromisoformat(to_date)
            - datetime.fromisoformat(from_date)
        )
        for event in day["events"]:
            for field in ("start_at", "end_at"):
                value = event.get(field)
                if isinstance(value, str):
                    event[field] = (
                        datetime.fromisoformat(value) + delta
                    ).isoformat(timespec="minutes")

    def trim_rest_boundaries(
        trial_days: list[dict[str, object]],
    ) -> list[str]:
        reasons: list[str] = []
        ordered = sorted(trial_days, key=lambda value: int(value["day"]))
        for current, following in zip(ordered, ordered[1:]):
            following_starts = [
                datetime.fromisoformat(str(event["start_at"]))
                for _, _, event in _selected_events([following])
                if isinstance(event.get("start_at"), str)
            ]
            if not following_starts:
                continue
            boundary = min(following_starts)
            for _, _, event in _selected_events([current]):
                if event.get("type") != "rest":
                    continue
                end_value = event.get("end_at")
                if not isinstance(end_value, str):
                    continue
                end_at = datetime.fromisoformat(end_value)
                if end_at <= boundary:
                    continue
                event_id = str(event["event_id"])
                if event_id in locked:
                    reasons.append(
                        f"{event_id}锁定且跨日休息与次日时间轴重叠"
                    )
                    continue
                event["end_at"] = boundary.isoformat(timespec="minutes")
                event_change_reasons[event_id] = (
                    "为满足用户强制换天，收拢跨日休息边界。"
                )
        return reasons

    def day_overlap_reasons(
        trial_days: Sequence[Mapping[str, object]],
        day_numbers: set[int],
    ) -> list[str]:
        reasons: list[str] = []
        for day in trial_days:
            if int(day["day"]) not in day_numbers:
                continue
            events = [
                event
                for _, _, event in _selected_events([day])
                if isinstance(event.get("start_at"), str)
                and isinstance(event.get("end_at"), str)
            ]
            events.sort(key=lambda event: str(event["start_at"]))
            for left, right in zip(events, events[1:]):
                if (
                    right.get("overlaps_event_id")
                    == left.get("event_id")
                    or left.get("overlaps_event_id")
                    == right.get("event_id")
                ):
                    continue
                if datetime.fromisoformat(
                    str(right["start_at"])
                ) < datetime.fromisoformat(str(left["end_at"])):
                    reasons.append(
                        f"Day {day['day']}时间重叠："
                        f"{left['event_id']} / {right['event_id']}"
                    )
        return reasons

    def try_swap_destination_days(
        *,
        source_day_number: int,
        target_day_number: int,
        attraction_id: str,
    ) -> tuple[list[dict[str, object]] | None, list[str]]:
        trial_days = deepcopy(days)
        source = next(
            day
            for day in trial_days
            if int(day["day"]) == source_day_number
        )
        target = next(
            day
            for day in trial_days
            if int(day["day"]) == target_day_number
        )
        affected_event_ids = {
            str(event["event_id"])
            for _, _, event in _selected_events([source, target])
        }
        locked_in_swap = sorted(affected_event_ids & locked)
        if locked_in_swap:
            return None, [
                "交换日程会移动锁定事件：" + "、".join(locked_in_swap)
            ]
        if any(
            event.get("transport_mode") == "high_speed_rail"
            for _, _, event in _selected_events([source, target])
        ):
            return None, ["交换候选包含跨城铁路事件"]
        source_date = str(source["date"])
        target_date = str(target["date"])
        payload_fields = {
            "events",
            "title",
            "conditions",
            "pace_decisions",
            "selected_branch",
        }
        source_payload = {
            field: deepcopy(source[field])
            for field in payload_fields
            if field in source
        }
        target_payload = {
            field: deepcopy(target[field])
            for field in payload_fields
            if field in target
        }
        for field in payload_fields:
            source.pop(field, None)
            target.pop(field, None)
        source.update(target_payload)
        target.update(source_payload)
        shift_day_payload(
            source,
            from_date=target_date,
            to_date=source_date,
        )
        shift_day_payload(
            target,
            from_date=source_date,
            to_date=target_date,
        )
        boundary_reasons = trim_rest_boundaries(trial_days)
        trial_evaluation = evaluate_pace(
            days=trial_days,
            settings=settings,
        )
        evaluation_reasons = [
            (
                f"Day {value['day']}违反"
                + "、".join(value["violations"])
            )
            for value in trial_evaluation["days"]
            if int(value["day"]) in {
                source_day_number,
                target_day_number,
            }
            and value["violations"]
        ]
        overlap_reasons = day_overlap_reasons(
            trial_days,
            {source_day_number, target_day_number},
        )
        forced_days_after = {
            day_number
            for day_number, _, event in _selected_events(trial_days)
            if _event_attraction_id(event) == attraction_id
        }
        if forced_days_after != {target_day_number}:
            evaluation_reasons.append(
                "交换后用户指定地点未唯一落在目标日"
            )
        reasons = [
            *boundary_reasons,
            *evaluation_reasons,
            *overlap_reasons,
        ]
        return (None, reasons) if reasons else (trial_days, [])

    for event_id in sorted(locked):
        previous = previous_positions.get(event_id)
        if previous is None:
            conflicts.append(
                {
                    "type": "locked_event_missing",
                    "event_id": event_id,
                    "message": "锁定事件不在旧计划中，不能猜测其内容。",
                }
            )
            continue
        old_day, old_index, old_event = previous
        for day in days:
            day["events"] = [
                event
                for event in day["events"]
                if event.get("event_id") != event_id
            ]
        target = next(
            (day for day in days if int(day["day"]) == old_day),
            None,
        )
        if target is None:
            conflicts.append(
                {
                    "type": "locked_day_missing",
                    "event_id": event_id,
                    "message": "锁定事件原日期不存在，不能移动该事件。",
                }
            )
            continue
        insertion = min(old_index, len(target["events"]))
        target["events"].insert(insertion, old_event)

    for day_number, clock in sorted(day_start_times.items()):
        target = next(
            (day for day in days if int(day["day"]) == day_number),
            None,
        )
        if target is None:
            conflicts.append(
                {
                    "type": "day_start_day_missing",
                    "day": day_number,
                    "message": "用户指定的日期不存在。",
                }
            )
            continue
        movable = [
            event
            for _, _, event in _selected_events([target])
            if isinstance(event.get("start_at"), str)
            and (
                event.get("type") == "attraction"
                or (
                    event.get("type") == "transit"
                    and not str(event.get("event_id", "")).startswith(
                        "rail-"
                    )
                )
            )
        ]
        if not movable:
            conflicts.append(
                {
                    "type": "day_start_activity_missing",
                    "day": day_number,
                    "message": "该日没有可调整的当地出发事件。",
                }
            )
            continue
        earliest_movable = min(
            datetime.fromisoformat(str(event["start_at"]))
            for event in movable
        )
        requested = at_date_time(str(target["date"]), clock)
        if earliest_movable >= requested:
            continue
        delta = requested - earliest_movable
        affected = [
            event
            for _, _, event in _selected_events([target])
            if isinstance(event.get("start_at"), str)
            and datetime.fromisoformat(str(event["start_at"]))
            >= earliest_movable
            and (
                event.get("type") == "attraction"
                or (
                    event.get("type") == "transit"
                    and not str(event.get("event_id", "")).startswith(
                        "rail-"
                    )
                )
                or (
                    event.get("type") == "buffer"
                    and (
                        isinstance(
                            event.get("remove_with_attraction_id"),
                            str,
                        )
                        or str(event.get("event_id", "")).startswith(
                            "activity-buffer-"
                        )
                    )
                )
            )
        ]
        locked_affected = [
            str(event["event_id"])
            for event in affected
            if str(event["event_id"]) in locked
        ]
        if locked_affected:
            conflicts.append(
                {
                    "type": "day_start_hits_locked_event",
                    "day": day_number,
                    "event_ids": locked_affected,
                    "message": (
                        "新的出发时间会移动已锁定事件；"
                        "锁定优先，因此未应用该修改。"
                    ),
                }
            )
            continue
        for event in affected:
            for field in ("start_at", "end_at"):
                raw = event.get(field)
                if isinstance(raw, str):
                    event[field] = (
                        datetime.fromisoformat(raw) + delta
                    ).isoformat(timespec="minutes")
            event_change_reasons[str(event["event_id"])] = (
                f"用户要求Day {day_number}在{clock}以后出发；"
                "为保持相对顺序，受影响的当地交通、景点和缓冲顺延。"
            )
        shifted_intervals = [
            (
                datetime.fromisoformat(str(event["start_at"])),
                datetime.fromisoformat(str(event["end_at"])),
            )
            for event in affected
            if isinstance(event.get("start_at"), str)
            and isinstance(event.get("end_at"), str)
        ]
        meals = [
            event
            for _, _, event in _selected_events([target])
            if event.get("type") == "meal"
            and isinstance(event.get("start_at"), str)
            and isinstance(event.get("end_at"), str)
        ]
        for meal in meals:
            meal_start = datetime.fromisoformat(str(meal["start_at"]))
            meal_end = datetime.fromisoformat(str(meal["end_at"]))
            duration = meal_end - meal_start
            while True:
                overlapping = [
                    interval
                    for interval in shifted_intervals
                    if interval[0] < meal_end and interval[1] > meal_start
                ]
                if not overlapping:
                    break
                if str(meal["event_id"]) in locked:
                    conflicts.append(
                        {
                            "type": "day_start_hits_locked_meal",
                            "day": day_number,
                            "event_id": str(meal["event_id"]),
                            "message": (
                                "顺延后的活动与已锁定餐食重叠；"
                                "餐食未移动，需要用户调整活动或解除锁定。"
                            ),
                        }
                    )
                    break
                meal_start = max(interval[1] for interval in overlapping)
                meal_end = meal_start + duration
            if str(meal["event_id"]) in locked:
                continue
            original_start = datetime.fromisoformat(str(meal["start_at"]))
            if meal_start != original_start:
                meal["start_at"] = meal_start.isoformat(timespec="minutes")
                meal["end_at"] = meal_end.isoformat(timespec="minutes")
                event_change_reasons[str(meal["event_id"])] = (
                    f"Day {day_number}出发时间调整后与活动重叠；"
                    "餐食按原时长顺延到首个可用时段。"
                )
                if (
                    meal.get("meal_kind") == "lunch"
                    and meal_end
                    > at_date_time(
                        str(target["date"]),
                        str(PLANNER_DEFAULTS["lunch_window_end"]),
                    )
                ):
                    conflicts.append(
                        {
                            "type": "lunch_window_exceeded",
                            "day": day_number,
                            "event_id": str(meal["event_id"]),
                            "message": (
                                f"Day {day_number}推迟出发后，午餐需延至"
                                f"{meal_start.strftime('%H:%M')}–"
                                f"{meal_end.strftime('%H:%M')}，超过默认午餐"
                                f"窗口{PLANNER_DEFAULTS['lunch_window_end']}；"
                                "可缩短景点、缩短午餐或接受较晚午餐。"
                            ),
                        }
                    )
        explicit_changes.append(
            {
                "action": "moved_time",
                "day": day_number,
                "from": earliest_movable.strftime("%H:%M"),
                "to": clock,
                "reason": (
                    f"用户要求Day {day_number}在{clock}以后出发；"
                    "只顺延受影响的当地交通、景点和相邻缓冲。"
                ),
            }
        )

    previous_attraction_events: dict[str, list[str]] = {}
    for _, _, event in _selected_events(previous_days):
        attraction_id = _event_attraction_id(event)
        if attraction_id is not None:
            previous_attraction_events.setdefault(attraction_id, []).append(
                str(event["event_id"])
            )

    for attraction_id in sorted(removed):
        event_ids = previous_attraction_events.get(attraction_id, [])
        if attraction_id in must_visit:
            conflicts.append(
                {
                    "type": "must_visit_removed",
                    "attraction_id": attraction_id,
                    "message": "同一地点同时被标记为must_visit和删除。",
                }
            )
            continue
        if any(event_id in locked for event_id in event_ids):
            conflicts.append(
                {
                    "type": "locked_event_removed",
                    "attraction_id": attraction_id,
                    "message": "地点包含锁定事件，不能删除。",
                }
            )
            continue
        removed_count = 0
        for day in days:
            selected_branch = day.get("selected_branch")
            matching_events = [
                event
                for event in day["events"]
                if (
                    _event_removal_attraction_id(event)
                    == attraction_id
                    and (
                        event.get("branch") is None
                        or event.get("branch") == selected_branch
                    )
                )
            ]
            starts = [
                datetime.fromisoformat(str(event["start_at"]))
                for event in matching_events
                if isinstance(event.get("start_at"), str)
            ]
            ends = [
                datetime.fromisoformat(str(event["end_at"]))
                for event in matching_events
                if isinstance(event.get("end_at"), str)
            ]
            before = len(day["events"])
            day["events"] = [
                event
                for event in day["events"]
                if _event_removal_attraction_id(event) != attraction_id
            ]
            removed_count += before - len(day["events"])
            if starts and ends:
                removed_start = min(starts)
                removed_end = max(ends)
                shift = removed_end - removed_start
                remaining_events = day["events"]
                for event_index, event in enumerate(remaining_events):
                    start_value = event.get("start_at")
                    if (
                        event.get("branch") is not None
                        and event.get("branch") != selected_branch
                    ) or not isinstance(start_value, str):
                        continue
                    start_at = datetime.fromisoformat(start_value)
                    if start_at < removed_end:
                        continue
                    if event.get("type") in {"meal", "hotel", "rest"}:
                        break
                    event_id = str(event["event_id"])
                    if event_id in locked:
                        conflicts.append(
                            {
                                "type": "removal_hits_locked_event",
                                "attraction_id": attraction_id,
                                "locked_event_id": event_id,
                                "message": (
                                    "删除地点需要提前后续事件，"
                                    "但后续事件已锁定。"
                                ),
                            }
                        )
                        break
                    next_selected = next(
                        (
                            candidate
                            for candidate in remaining_events[
                                event_index + 1 :
                            ]
                            if (
                                candidate.get("branch") is None
                                or candidate.get("branch")
                                == selected_branch
                            )
                        ),
                        None,
                    )
                    if (
                        event.get("type") == "buffer"
                        and next_selected is not None
                        and next_selected.get("type")
                        in {"meal", "hotel", "rest"}
                    ):
                        free_start = start_at - shift
                        if free_start < start_at:
                            free_event = make_event(
                                event_id=(
                                    f"free-after-{attraction_id}-"
                                    f"day-{day['day']}"
                                ),
                                event_type="rest",
                                name="自由活动 / 可用时间",
                                start_at=free_start,
                                end_at=start_at,
                                why=(
                                    "用户删除地点后释放时间；"
                                    "未自动填入其他景点。"
                                ),
                                value_origin="rule_derived",
                                adjustable=(
                                    "start_at",
                                    "end_at",
                                    "activity_choice",
                                ),
                                branch=(
                                    str(event["branch"])
                                    if event.get("branch") is not None
                                    else None
                                ),
                                extra={
                                    "free_time": True,
                                    "released_by_attraction_id": (
                                        attraction_id
                                    ),
                                },
                            )
                            remaining_events.insert(
                                event_index,
                                free_event,
                            )
                            event_change_reasons[
                                str(free_event["event_id"])
                            ] = (
                                "用户删除地点后，将释放的时间显式"
                                "保留为自由活动。"
                            )
                        break
                    event["start_at"] = (
                        start_at - shift
                    ).isoformat(timespec="minutes")
                    end_value = event.get("end_at")
                    if isinstance(end_value, str):
                        end_at = datetime.fromisoformat(end_value)
                        if (
                            event.get("type") != "buffer"
                            or next_selected is None
                            or next_selected.get("type")
                            not in {"meal", "hotel", "rest"}
                        ) and end_at.date() == start_at.date():
                            event["end_at"] = (
                                end_at - shift
                            ).isoformat(timespec="minutes")
                    event_change_reasons[event_id] = (
                        "用户删除前序地点后，提前同日后续事件以消除空档。"
                    )
        if removed_count:
            explicit_changes.append(
                schedule_change(
                    "removed",
                    attraction=attraction_id,
                    reason=(
                        "用户明确删除；保持其余事件日期和相对顺序，"
                        "仅压缩由删除产生的空档。"
                    ),
                )
            )

    for attraction_id, target_day_number in sorted(forced_days.items()):
        matching: list[tuple[int, Mapping[str, object]]] = []
        for day_number, _, event in _selected_events(days):
            if _event_attraction_id(event) == attraction_id:
                matching.append((day_number, event))
        if not matching:
            conflicts.append(
                {
                    "type": "forced_attraction_missing",
                    "attraction_id": attraction_id,
                    "message": "指定换天的地点不在当前候选计划中。",
                }
            )
            continue
        if all(day == target_day_number for day, _ in matching):
            continue
        if any(str(event["event_id"]) in locked for _, event in matching):
            conflicts.append(
                {
                    "type": "locked_event_move",
                    "attraction_id": attraction_id,
                    "message": "地点包含锁定事件，不能换天。",
                }
            )
            continue
        target_day = next(
            (
                day
                for day in days
                if int(day["day"]) == target_day_number
            ),
            None,
        )
        if target_day is None:
            conflicts.append(
                {
                    "type": "forced_day_missing",
                    "attraction_id": attraction_id,
                    "message": "用户指定的目标日期不存在。",
                }
            )
            continue
        source_day = matching[0][0]
        durations = [
            _event_duration_minutes(event) for _, event in matching
        ]
        required_minutes = sum(
            duration for duration in durations if duration is not None
        ) + int(settings["inter_event_buffer_minutes"])
        target_evaluation = next(
            value
            for value in evaluate_pace(
                days=days,
                settings=settings,
            )["days"]
            if int(value["day"]) == target_day_number
        )
        target_ids = {
            _event_attraction_id(event)
            for _, _, event in _selected_events([target_day])
            if _event_attraction_id(event) is not None
        }
        capacity_reasons: list[str] = []
        if len(target_ids) + 1 > int(
            settings["max_attractions_per_day"]
        ):
            capacity_reasons.append("目标日景点数量上限")
        if int(target_evaluation["active_minutes"]) + required_minutes > int(
            settings["max_daily_active_minutes"]
        ):
            capacity_reasons.append("目标日总活动时长上限")
        if any(
            duration is None
            or duration
            > int(settings["max_continuous_attraction_minutes"])
            for duration in durations
        ):
            capacity_reasons.append("连续游玩上限")
        attempts.append(
            {
                "strategy": "direct_move",
                "attraction_id": attraction_id,
                "from_day": source_day,
                "to_day": target_day_number,
                "status": (
                    "failed" if capacity_reasons else "accepted"
                ),
                "reasons": list(capacity_reasons),
            }
        )
        if capacity_reasons:
            swapped_days, swap_reasons = try_swap_destination_days(
                source_day_number=source_day,
                target_day_number=target_day_number,
                attraction_id=attraction_id,
            )
            attempts.append(
                {
                    "strategy": "swap_unlocked_destination_days",
                    "attraction_id": attraction_id,
                    "from_day": source_day,
                    "to_day": target_day_number,
                    "status": (
                        "accepted"
                        if swapped_days is not None
                        else "failed"
                    ),
                    "reasons": swap_reasons,
                }
            )
            if swapped_days is not None:
                old_event_days = {
                    str(event["event_id"]): day_number
                    for day_number, _, event in _selected_events(days)
                }
                days = swapped_days
                for day_number, _, event in _selected_events(days):
                    event_id = str(event["event_id"])
                    if old_event_days.get(event_id) != day_number:
                        event_change_reasons[event_id] = (
                            "为满足用户强制换天，交换两个未锁定"
                            "当地日程块。"
                        )
                all_candidate_ids = {
                    _event_attraction_id(event)
                    for _, _, event in _selected_events(candidate_days)
                    if _event_attraction_id(event) is not None
                }
                old_attraction_days = {
                    candidate_id: {
                        day_number
                        for day_number, _, event in _selected_events(
                            candidate_days
                        )
                        if _event_attraction_id(event) == candidate_id
                    }
                    for candidate_id in all_candidate_ids
                }
                for day_number, _, event in _selected_events(days):
                    candidate_id = _event_attraction_id(event)
                    if (
                        candidate_id is not None
                        and day_number
                        not in old_attraction_days.get(
                            candidate_id,
                            set(),
                        )
                    ):
                        attraction_change_reasons[candidate_id] = (
                            "为满足用户强制换天，交换两个未锁定"
                            "当地日程块。"
                        )
                explicit_changes.append(
                    schedule_change(
                        "moved_day",
                        attraction=attraction_id,
                        from_day=source_day,
                        to_day=target_day_number,
                        reason=(
                            "直接移入目标日超限；交换两个未锁定"
                            "当地日程块后满足用户硬约束。"
                        ),
                    )
                )
                attempts.extend(
                    [
                        {
                            "strategy": "delete_low_priority",
                            "status": "not_needed",
                            "reasons": [
                                "交换未锁定日程块已找到可行候选"
                            ],
                        },
                        {
                            "strategy": "shorten_adjustable_activity",
                            "status": "not_needed",
                            "reasons": [
                                "未在已有可行候选上继续损失游玩时长"
                            ],
                        },
                    ]
                )
                continue
            deletion_candidates = sorted(
                target_ids - must_visit
            )
            attempts.append(
                {
                    "strategy": "delete_low_priority",
                    "status": "failed",
                    "candidates": deletion_candidates,
                    "reasons": (
                        ["目标日没有可删除的非必去景点"]
                        if not deletion_candidates
                        else [
                            "删除目标日景点后仍缺少用户指定地点"
                            "在目标日的可复用交通上下文"
                        ]
                    ),
                }
            )
            adjustable_minutes = sum(
                max(0, int(duration or 0) - 15)
                for duration in durations
            )
            attempts.append(
                {
                    "strategy": "shorten_adjustable_activity",
                    "status": "failed",
                    "available_reduction_minutes": adjustable_minutes,
                    "reasons": [
                        "缩短游玩时长不能补齐目标日交通上下文"
                    ],
                }
            )
        for day in days:
            day["events"] = [
                event
                for event in day["events"]
                if _event_attraction_id(event) != attraction_id
            ]
        if capacity_reasons:
            reason = (
                f"用户指定Day {target_day_number}，但"
                + "、".join(capacity_reasons)
                + "不足；未退回原日期。"
            )
            retained_unscheduled.append(
                {
                    "attraction_id": attraction_id,
                    "requested_day": target_day_number,
                    "reason": reason,
                }
            )
            explicit_changes.append(
                schedule_change(
                    "retained_unscheduled",
                    attraction=attraction_id,
                    reason=reason,
                )
            )
            conflicts.append(
                {
                    "type": "forced_day_capacity",
                    "attraction_id": attraction_id,
                    "message": reason,
                }
            )
            continue

        target_events = target_day["events"]
        attraction_indices = [
            index
            for index, event in enumerate(target_events)
            if event.get("type") == "attraction"
        ]
        insertion = (
            attraction_indices[-1] + 1 if attraction_indices else 0
        )
        anchor = (
            datetime.fromisoformat(
                str(target_events[insertion - 1]["end_at"])
            )
            + timedelta(
                minutes=int(settings["inter_event_buffer_minutes"])
            )
            if insertion > 0
            and isinstance(target_events[insertion - 1].get("end_at"), str)
            else at_date_time(
                str(target_day["date"]),
                str(settings["earliest_departure"]),
            )
        )
        moved_events: list[dict[str, object]] = []
        for _, event in matching:
            duration = _event_duration_minutes(event)
            if duration is None:
                raise ValueError("movable attraction requires duration")
            moved = deepcopy(dict(event))
            moved["start_at"] = anchor.isoformat(timespec="minutes")
            anchor += timedelta(minutes=duration)
            moved["end_at"] = anchor.isoformat(timespec="minutes")
            moved_events.append(moved)
            anchor += timedelta(
                minutes=int(settings["inter_event_buffer_minutes"])
            )
        target_events[insertion:insertion] = moved_events
        for moved in moved_events:
            event_change_reasons[str(moved["event_id"])] = (
                "用户明确指定目标日期。"
            )
        explicit_changes.append(
            schedule_change(
                "moved_day",
                attraction=attraction_id,
                from_day=source_day,
                to_day=target_day_number,
                reason="用户明确指定目标日期；其余事件顺序保持不变。",
            )
        )
        attraction_change_reasons[attraction_id] = (
            "用户明确指定目标日期。"
        )

    for event_id, minutes in sorted(duration_edits.items()):
        located = next(
            (
                (day_number, index, event)
                for day_number, index, event in _selected_events(days)
                if event.get("event_id") == event_id
            ),
            None,
        )
        if located is None:
            conflicts.append(
                {
                    "type": "duration_event_missing",
                    "event_id": event_id,
                    "message": "要修改时长的景点事件不存在。",
                }
            )
            continue
        day_number, event_index, match = located
        if event_id in locked:
            conflicts.append(
                {
                    "type": "locked_event_duration",
                    "event_id": event_id,
                    "message": "锁定事件不能修改游玩时长。",
                }
            )
            continue
        if match.get("type") != "attraction":
            raise ValueError("duration edits only support attraction events")
        start = match.get("start_at")
        if not isinstance(start, str):
            raise ValueError("attraction start time is unavailable")
        old_duration = _event_duration_minutes(match)
        if old_duration is None:
            raise ValueError("attraction duration is unavailable")
        match["end_at"] = (
            datetime.fromisoformat(start) + timedelta(minutes=minutes)
        ).isoformat(timespec="minutes")
        match["planning_allocation_minutes"] = minutes
        event_change_reasons[event_id] = "用户修改该景点游玩时长。"
        delta = minutes - old_duration
        if delta:
            day = next(
                value for value in days if int(value["day"]) == day_number
            )
            selected_branch = day.get("selected_branch")
            for later in day["events"][event_index + 1 :]:
                if (
                    later.get("branch") is not None
                    and later.get("branch") != selected_branch
                ):
                    continue
                later_id = str(later["event_id"])
                if later_id in locked:
                    conflicts.append(
                        {
                            "type": "duration_hits_locked_event",
                            "event_id": event_id,
                            "locked_event_id": later_id,
                            "message": (
                                "修改后的游玩时长会推移后续锁定事件；"
                                "锁定事件保持不动。"
                            ),
                        }
                    )
                    break
                for field in ("start_at", "end_at"):
                    value = later.get(field)
                    if isinstance(value, str):
                        later[field] = (
                            datetime.fromisoformat(value)
                            + timedelta(minutes=delta)
                        ).isoformat(timespec="minutes")
                event_change_reasons[later_id] = (
                    "为容纳用户修改后的景点时长，顺延同日后续事件。"
                )

    present_attractions = {
        _event_attraction_id(event)
        for _, _, event in _selected_events(days)
        if _event_attraction_id(event) is not None
    }
    for attraction_id in sorted(must_visit - present_attractions):
        conflicts.append(
            {
                "type": "must_visit_unscheduled",
                "attraction_id": attraction_id,
                "message": "must_visit地点未能进入当前时间轴。",
            }
        )

    evaluation = evaluate_pace(days=days, settings=settings)
    for day in evaluation["days"]:
        new_violations = sorted(
            set(day["violations"])
            - candidate_violations.get(int(day["day"]), set())
        )
        if new_violations:
            conflicts.append(
                {
                    "type": "pace_constraint_violation",
                    "day": day["day"],
                    "constraints": new_violations,
                    "message": "该日超过当前节奏硬限制。",
                }
            )

    def overlap_pairs(
        values: Sequence[Mapping[str, object]],
    ) -> set[tuple[int, str, str]]:
        pairs: set[tuple[int, str, str]] = set()
        for day in values:
            selected = [
                event
                for _, _, event in _selected_events([day])
                if isinstance(event.get("start_at"), str)
                and isinstance(event.get("end_at"), str)
            ]
            selected.sort(key=lambda event: str(event["start_at"]))
            for left, right in zip(selected, selected[1:]):
                if (
                    right.get("overlaps_event_id")
                    == left.get("event_id")
                    or left.get("overlaps_event_id")
                    == right.get("event_id")
                ):
                    continue
                if datetime.fromisoformat(
                    str(right["start_at"])
                ) < datetime.fromisoformat(str(left["end_at"])):
                    pairs.add(
                        (
                            int(day["day"]),
                            str(left["event_id"]),
                            str(right["event_id"]),
                        )
                    )
        return pairs

    new_overlap_pairs = sorted(
        overlap_pairs(days) - overlap_pairs(candidate_days)
    )
    for day_number, left_id, right_id in new_overlap_pairs:
        conflicts.append(
            {
                "type": "timeline_overlap",
                "day": day_number,
                "event_ids": [left_id, right_id],
                "message": (
                    "锁定或时长修改后产生时间重叠；"
                    "系统未静默移动锁定事件。"
                ),
            }
        )

    new_positions = {
        str(event["event_id"]): (day, index, dict(event))
        for day, index, event in _selected_events(days)
    }
    unchanged: list[str] = []
    moved_events: list[dict[str, object]] = []
    removed_events: list[dict[str, object]] = []
    added_events: list[dict[str, object]] = []
    for event_id, (
        old_day,
        _old_index,
        old_event,
    ) in previous_positions.items():
        current = new_positions.get(event_id)
        if current is None:
            attraction_id = _event_removal_attraction_id(old_event)
            removed_events.append(
                {
                    "event_id": event_id,
                    "event_type": old_event.get("type"),
                    "name": old_event.get("name"),
                    "transport_mode": old_event.get("transport_mode"),
                    "attraction_id": old_event.get("attraction_id"),
                    "from_day": old_day,
                    "reason": (
                        "用户明确删除该地点。"
                        if attraction_id in removed
                        else "新约束模板未保留该事件。"
                    ),
                }
            )
            continue
        new_day, _new_index, new_event = current
        if (
            old_day == new_day
            and old_event == new_event
        ):
            unchanged.append(event_id)
        elif (
            old_day != new_day
            or old_event.get("start_at") != new_event.get("start_at")
            or old_event.get("end_at") != new_event.get("end_at")
        ):
            moved_events.append(
                {
                    "event_id": event_id,
                    "event_type": old_event.get("type"),
                    "name": old_event.get("name"),
                    "transport_mode": old_event.get("transport_mode"),
                    "attraction_id": old_event.get("attraction_id"),
                    "from_day": old_day,
                    "to_day": new_day,
                    "from": {
                        "start_at": old_event.get("start_at"),
                        "end_at": old_event.get("end_at"),
                    },
                    "to": {
                        "start_at": new_event.get("start_at"),
                        "end_at": new_event.get("end_at"),
                    },
                    "reason": event_change_reasons.get(
                        event_id,
                        "用户修改pace或时间窗后重新应用通用节奏模板。",
                    ),
                }
            )
    for event_id, (day_number, _index, event) in new_positions.items():
        if event_id in previous_positions:
            continue
        added_events.append(
            {
                "event_id": event_id,
                "event_type": event.get("type"),
                "name": event.get("name"),
                "transport_mode": event.get("transport_mode"),
                "attraction_id": event.get("attraction_id"),
                "to_day": day_number,
                "start_at": event.get("start_at"),
                "end_at": event.get("end_at"),
                "reason": event_change_reasons.get(
                    event_id,
                    "新约束产生的必要日程块。",
                ),
            }
        )

    locked_preserved = [
        event_id
        for event_id in sorted(locked)
        if event_id in previous_positions
        and event_id in new_positions
        and previous_positions[event_id][0]
        == new_positions[event_id][0]
        and previous_positions[event_id][2]
        == new_positions[event_id][2]
    ]
    previous_attraction_days: dict[str, set[int]] = {}
    new_attraction_days: dict[str, set[int]] = {}
    attraction_labels: dict[str, str] = {}
    for day_number, _, event in _selected_events(previous_days):
        attraction_id = _event_attraction_id(event)
        if attraction_id is not None:
            previous_attraction_days.setdefault(attraction_id, set()).add(
                day_number
            )
            attraction_labels.setdefault(
                attraction_id,
                str(event.get("name", attraction_id)).split("·", 1)[0],
            )
    for day_number, _, event in _selected_events(days):
        attraction_id = _event_attraction_id(event)
        if attraction_id is not None:
            new_attraction_days.setdefault(attraction_id, set()).add(
                day_number
            )
            attraction_labels.setdefault(
                attraction_id,
                str(event.get("name", attraction_id)).split("·", 1)[0],
            )
    pace_reason_by_label = {
        str(change["attraction"]): str(change["reason"])
        for change in candidate_evaluation["changes"]
        if isinstance(change, Mapping)
        and isinstance(change.get("attraction"), str)
        and isinstance(change.get("reason"), str)
    }
    retained_ids = {
        str(value["attraction_id"]) for value in retained_unscheduled
    }
    attraction_changes: list[dict[str, object]] = []
    for attraction_id in sorted(
        set(previous_attraction_days) | set(new_attraction_days)
    ):
        old_days = sorted(previous_attraction_days.get(attraction_id, set()))
        new_days = sorted(new_attraction_days.get(attraction_id, set()))
        label = attraction_labels.get(attraction_id, attraction_id)
        if attraction_id in retained_ids:
            retained_value = next(
                value
                for value in retained_unscheduled
                if value["attraction_id"] == attraction_id
            )
            attraction_changes.append(
                {
                    "action": "retained_unscheduled",
                    "attraction_id": attraction_id,
                    "label": label,
                    "from_days": old_days,
                    "to_days": [],
                    "reason": retained_value["reason"],
                }
            )
        elif old_days and not new_days:
            attraction_changes.append(
                {
                    "action": "removed",
                    "attraction_id": attraction_id,
                    "label": label,
                    "from_days": old_days,
                    "to_days": [],
                    "reason": (
                        "用户明确删除该地点。"
                        if attraction_id in removed
                        else pace_reason_by_label.get(
                            label,
                            "新pace或时间窗模板未再安排该地点。",
                        )
                    ),
                }
            )
        elif old_days != new_days:
            attraction_changes.append(
                {
                    "action": "moved_day",
                    "attraction_id": attraction_id,
                    "label": label,
                    "from_days": old_days,
                    "to_days": new_days,
                    "reason": attraction_change_reasons.get(
                        attraction_id,
                        pace_reason_by_label.get(
                            label,
                            "用户修改pace、日期或时间窗后重新分配日期。",
                        ),
                    ),
                }
            )
        else:
            attraction_changes.append(
                {
                    "action": "unchanged",
                    "attraction_id": attraction_id,
                    "label": label,
                    "from_days": old_days,
                    "to_days": new_days,
                    "reason": "日期保持不变。",
                }
            )
    suggestions: list[str] = []
    if conflicts:
        suggestions.extend(
            [
                "延长一天或放宽最晚返回时间",
                "减少must_visit或取消一个低优先级景点",
                "缩短未锁定景点游玩时长",
            ]
        )
        if forced_days:
            suggestions.append("取消强制换天，或选择容量更充足的日期")
        if locked:
            suggestions.append("解除冲突事件的锁定，或恢复原pace")
    hard_conflict_types = {
        "must_visit_removed",
        "must_visit_unscheduled",
        "forced_day_capacity",
        "locked_event_move",
        "locked_event_removed",
        "removal_hits_locked_event",
        "duration_hits_locked_event",
        "pace_constraint_violation",
        "timeline_overlap",
    }
    decision_conflict_types = {
        "must_visit_removed",
        "locked_event_move",
        "locked_event_removed",
        "removal_hits_locked_event",
        "duration_hits_locked_event",
        "timeline_overlap",
    }
    hard_conflicts = [
        conflict
        for conflict in conflicts
        if conflict["type"] in hard_conflict_types
    ]
    has_partial_plan = bool(_selected_events(days))
    if hard_conflicts:
        if not has_partial_plan:
            status = "NO_PLAN_FOUND"
        elif any(
            conflict["type"] in decision_conflict_types
            for conflict in hard_conflicts
        ):
            status = "NEEDS_USER_DECISION"
        else:
            status = "PARTIAL_PLAN_WITH_CONFLICTS"
    elif conflicts or evaluation["status"] != "PASS":
        status = "CONDITIONAL"
    else:
        status = "PLANNED"
    return {
        "status": status,
        "priority_order": [
            "locked_events",
            "new_user_hard_constraints",
            "must_visit",
            "feasibility",
            "minimal_change",
            "soft_preferences",
        ],
        "days": days,
        "pace_evaluation": evaluation,
        "candidate_pace_evaluation": candidate_evaluation,
        "changes": explicit_changes,
        "attempts": attempts,
        "retained_unscheduled": retained_unscheduled,
        "conflicts": conflicts,
        "suggestions": suggestions,
        "diff": {
            "unchanged_event_ids": unchanged,
            "moved_events": moved_events,
            "removed_events": removed_events,
            "added_events": added_events,
            "locked_preserved_event_ids": locked_preserved,
            "attraction_changes": attraction_changes,
        },
    }


def plan_destination_context(
    context: Mapping[str, object],
) -> dict[str, object]:
    """Create a conservative plan shell from dynamic context evidence.

    This function never supplies city facts. A later planning capability may
    schedule activities only when the context contains the required sourced
    values.
    """

    context_id = context.get("context_id")
    intent = context.get("intent")
    evidence = context.get("evidence")
    missing = context.get("missing_domains", [])
    conflicting = context.get("conflicting_domains", [])
    if (
        not isinstance(context_id, str)
        or not context_id
        or not isinstance(intent, Mapping)
        or not isinstance(evidence, list)
        or any(not isinstance(item, Mapping) for item in evidence)
        or not isinstance(missing, list)
        or not isinstance(conflicting, list)
    ):
        raise ValueError("invalid DestinationContext payload")
    status = (
        "NEEDS_USER_DECISION"
        if conflicting
        else "CONTEXT_INCOMPLETE"
        if missing
        else "CONTEXT_READY"
    )
    return {
        "plan_id": f"plan-{context_id}",
        "context_id": context_id,
        "status": status,
        "publishable": False,
        "days": [],
        "evidence_refs": [
            str(item["evidence_id"])
            for item in evidence
            if isinstance(item.get("evidence_id"), str)
        ],
        "missing": list(missing),
        "conflicting": list(conflicting),
        "constraints": {
            "earliest_departure_at": intent.get(
                "earliest_departure_at"
            ),
            "latest_return_at": intent.get("latest_return_at"),
            "travelers": intent.get("travelers"),
            "total_budget_cny": intent.get("total_budget_cny"),
            "pace": intent.get("pace"),
        },
        "capability_boundary": (
            "No activity is scheduled until its required map, transport, "
            "and operational evidence exists in DestinationContext."
        ),
    }


def validate_destination_plan(
    context: Mapping[str, object],
    plan: Mapping[str, object],
) -> dict[str, object]:
    """Validate context linkage and evidence provenance."""

    # 两种 context 都要吃：**采集时**的完整 context（证据内联），与**落盘后**
    # 的 context（证据已收敛进 evidence/current.json，只留 evidence_refs，
    # persistence-v2.md §2.1.1）。本函数只用证据的 id 集合做引用解析核对，
    # 因此两种形状给的是同一个信息——收敛不改变它的判定。
    evidence = context.get("evidence")
    refs_only = context.get("evidence_refs")
    if isinstance(evidence, list):
        available = {
            str(item["evidence_id"])
            for item in evidence
            if isinstance(item, Mapping)
            and isinstance(item.get("evidence_id"), str)
        }
    elif isinstance(refs_only, list):
        evidence = []
        available = {
            str(item) for item in refs_only if isinstance(item, str)
        }
    else:
        raise ValueError(
            "context must carry either evidence or evidence_refs"
        )
    refs = plan.get("evidence_refs")
    problems: list[dict[str, object]] = []
    if plan.get("context_id") != context.get("context_id"):
        problems.append({"code": "CONTEXT_ID_MISMATCH"})
    if (
        not isinstance(refs, list)
        or any(not isinstance(item, str) for item in refs)
    ):
        problems.append({"code": "INVALID_EVIDENCE_REFS"})
    else:
        unresolved = sorted(set(refs) - available)
        if unresolved:
            problems.append(
                {
                    "code": "UNRESOLVED_EVIDENCE_REFS",
                    "refs": unresolved,
                }
            )
    catalog_claims = [
        item
        for item in evidence
        if isinstance(item, Mapping)
        and item.get("domain") == "destination_catalog"
    ]
    if catalog_claims:
        problems.append({"code": "CATALOG_USED_AS_FACT_EVIDENCE"})
    return {
        "valid": not problems,
        "problems": problems,
        "checked_context_id": context.get("context_id"),
    }


def _trimmed(context: Mapping[str, object]) -> dict[str, object]:
    """重排产出的 context 同样不内联证据（persistence-v2.md §2.1.1）。

    本模块在 ``travel_agent`` **下方**（后者 import 前者），不能反向 import；
    规则只有三行，复制一次比倒转依赖方向划算。两处必须同形——
    ``travel_agent.trimmed_context`` 是权威，分叉由
    ``tests/test_context_trimming_is_one_shape`` 守着（D5）。
    """

    trimmed = deepcopy(dict(context))
    evidence = trimmed.pop("evidence", None)
    trimmed.setdefault(
        "evidence_refs",
        [
            str(item["evidence_id"])
            for item in (evidence if isinstance(evidence, list) else [])
            if isinstance(item, Mapping)
            and isinstance(item.get("evidence_id"), str)
        ],
    )
    return trimmed


def revise_destination_plan(
    previous_result: Mapping[str, object],
    *,
    planner_edits: Mapping[str, object],
    pace: str | None,
) -> dict[str, object]:
    """Revise a generic plan without reacquiring evidence."""

    context = previous_result.get("context")
    previous_plan = previous_result.get("plan")
    if not isinstance(context, Mapping) or not isinstance(
        previous_plan,
        Mapping,
    ):
        raise ValueError("previous result lacks context or plan")
    previous_days = previous_plan.get("days")
    if not isinstance(previous_days, list):
        raise ValueError("previous plan days must be an array")
    if not previous_days:
        result = deepcopy(dict(previous_plan))
        result["revision"] = {
            "status": "NO_SCHEDULED_EVENTS",
            "applied_edits": deepcopy(dict(planner_edits)),
            "network_calls": 0,
            "diff": {
                "unchanged_event_ids": [],
                "moved_events": [],
                "removed_events": [],
                "added_events": [],
                "locked_preserved_event_ids": [],
                "attraction_changes": [],
            },
        }
        return {
            "context": _trimmed(context),
            "plan": result,
            "validation": validate_destination_plan(context, result),
            "pipeline": [
                "revise",
                "validate",
            ],
        }
    constraints = previous_plan.get("constraints")
    if constraints is not None and not isinstance(constraints, Mapping):
        raise ValueError("previous plan constraints must be an object")
    selected_pace = pace or str(
        (constraints or {}).get("pace") or "standard"
    )
    settings, _ = resolve_pace_settings(
        pace=selected_pace,
        physical_level=None,
        early_start=None,
        night_activity=None,
        transport_tolerance=None,
        depth_preference=None,
        overrides=None,
    )
    replanned = replan_itinerary(
        previous_days=previous_days,
        candidate_days=previous_days,
        settings=settings,
        edits=planner_edits,
    )
    result = deepcopy(dict(previous_plan))
    result["days"] = replanned["days"]
    result["status"] = replanned["status"]
    result["revision"] = {
        **replanned,
        "network_calls": 0,
    }
    return {
        "context": _trimmed(context),
        "plan": result,
        "validation": validate_destination_plan(context, result),
        "pipeline": ["revise", "validate"],
    }


__all__ = [
    "EVENT_TYPES",
    "PACE_PROFILES",
    "PLANNER_DEFAULTS",
    "RAIL_EVENT_REQUIRED_TRAIN_FIELDS",
    "at_date_time",
    "conditional_conflict",
    "evaluate_pace",
    "event_end",
    "index_segments",
    "make_attraction_event",
    "make_duration_event",
    "make_event",
    "make_meal_event",
    "make_rail_event",
    "make_transit_event",
    "plan_destination_context",
    "resolve_pace_settings",
    "resolve_planner_defaults",
    "replan_itinerary",
    "revise_destination_plan",
    "schedule_change",
    "validate_destination_plan",
]
