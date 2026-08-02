"""全仓唯一的证据构造入口。

`docs/contracts/persistence-v2.md` §10 的原则：

> 测试 fixture 一律按**生产端实际落盘形状**构造，不按「读取层当时读什么」构造。

P3a 三次撞到这个问题：fixture 缺 `status`、缺 `retrieved_at`、把证据传成
`evidence=` 关键字而非 `result.context.evidence`。生产侧三者都正确，是 fixture
落后于现实。P4-a 清点确认全仓有 **59 处手工证据构造、9 种不同键集合**
（清单见 `docs/contracts/p4a-fixture-shapes.md`）。

测试只声明「我要一条什么 support 的什么域证据」，形状由本模块负责。
**P4-b 把落盘改成 facts 形状时，只改这一处。**
"""

from __future__ import annotations

from typing import Any

from trip_decider.travel_agent import EvidenceItem, EvidenceStatus

_ATTRACTION_NAMES = ("景点甲", "景点乙", "景点丙", "景点丁")


def _attraction_names(count: int) -> tuple[str, ...]:
    """景点名。规划器按名字把路线段接到景点上，命名必须与路线段一致。"""

    return _ATTRACTION_NAMES[:count]


DEFAULT_RETRIEVED_AT = "2026-08-02T18:00:00+08:00"

# 生产端每条证据都带的键。EvidenceItem.to_dict()（travel_agent.py）恒写它们，
# 因此 fixture 少任何一个都是在模拟一个生产端不会产生的形状。
REQUIRED_KEYS = frozenset(
    {
        "evidence_id",
        "domain",
        "status",
        "value",
        "sources",
        "missing_reason",
        "conflict_details",
    }
)

SUPPORT_STATES = ("sourced", "estimated", "conflicting", "unknown", "confirmed_absent")


def railway_value(*, retrieved_at: str = DEFAULT_RETRIEVED_AT) -> dict[str, Any]:
    """12306 跨城铁路证据的生产端形状。"""

    return {
        "domain": "railway",
        "origin": "甲站",
        "destination": "乙站",
        "outbound": {
            "train_code": "G100",
            "origin_station": "甲站",
            "destination_station": "乙站",
            "departure_at": "2026-08-04T13:00",
            "arrival_at": "2026-08-04T16:00",
            "duration_seconds": 10800,
            "second_class_fare_cny_per_person": 200.0,
            "second_class_availability": "available",
        },
        "return": {
            "train_code": "G101",
            "origin_station": "乙站",
            "destination_station": "甲站",
            "departure_at": "2026-08-07T18:00",
            "arrival_at": "2026-08-07T21:00",
            "duration_seconds": 10800,
            "second_class_fare_cny_per_person": 200.0,
            "second_class_availability": "available",
        },
        "snapshot": {
            "acquisition": "live_fetch",
            "retrieved_at": retrieved_at,
            "attempted_at": retrieved_at,
            "availability_semantics": "current_at_retrieval_only",
        },
        "roundtrip_fare_cny": 800.0,
        "roundtrip_duration_seconds": 21600,
        "retrieved_at": retrieved_at,
    }


def map_value(
    *,
    retrieved_at: str = DEFAULT_RETRIEVED_AT,
    attraction_count: int = 1,
) -> dict[str, Any]:
    """高德行政区与路线证据的生产端形状。"""

    return {
        "destination": {"name": "乙地", "adcode": "999999"},
        "retrieved_at": retrieved_at,
        "local_transit": [
            # 车站到住宿片区这一段是规划器接续跨城铁路与当地行程的必需输入。
            {
                "route_id": "route-station-base",
                "from": "乙站",
                "to": "住宿片区",
                "duration_seconds": 1800,
                "distance_meters": 12000,
                "fare": {"status": "unknown", "amount_cny": None},
            },
            *[
                {
                    "route_id": f"route-base-{name}",
                    "from": "住宿片区",
                    "to": name,
                    "duration_seconds": 1200,
                    "distance_meters": 6000,
                    "fare": {"status": "unknown", "amount_cny": None},
                }
                for name in _attraction_names(attraction_count)
            ],
        ],
        "map_points": [
            {"name": name, "longitude": 117.8 + i / 100, "latitude": 29.2}
            for i, name in enumerate(_attraction_names(attraction_count), start=1)
        ],
    }


def web_value(
    *,
    retrieved_at: str = DEFAULT_RETRIEVED_AT,
    attraction_count: int = 3,
) -> dict[str, Any]:
    """目的地画像证据的生产端形状。"""

    return {
        "destination_official_name": "乙地",
        "retrieved_at": retrieved_at,
        "verified_facts": [
            {"field": "official_administrative_name", "value": "乙地"},
        ],
        "attractions": [
            {
                "attraction_id": f"spot-{index}",
                "name": name,
                "visit_minutes": 90,
                "opening_hours": {"status": "unknown"},
                "ticket": {"status": "unknown"},
            }
            for index, name in enumerate(_attraction_names(attraction_count), start=1)
        ],
        "hotel_area": {
            "name": "住宿片区",
            "longitude": 117.86,
            "latitude": 29.25,
        },
        "route_sequence": ["住宿片区", *_attraction_names(attraction_count)],
        "route_segments": [
            ["住宿片区", name] for name in _attraction_names(attraction_count)
        ],
    }


_VALUE_BY_DOMAIN = {
    "railway": railway_value,
    "map": map_value,
    "web": web_value,
}


def evidence(
    domain: str,
    state: str = "sourced",
    *,
    retrieved_at: str = DEFAULT_RETRIEVED_AT,
    missing_reason: str = "collector_error",
    conflict_detail: str = "来源A与来源B不一致",
    **value_overrides: Any,
) -> EvidenceItem:
    """按目标 support 态构造一条证据。

    ``state`` ∈ :data:`SUPPORT_STATES`。返回的对象经 ``to_dict()`` 后与生产端
    落盘形状一致——这是本模块存在的全部理由。
    """

    if state not in SUPPORT_STATES:
        raise ValueError(f"unsupported evidence state: {state!r}")
    builder = _VALUE_BY_DOMAIN[domain]
    sources = (
        {"provider": f"controlled-{domain}", "retrieved_at": retrieved_at},
    )

    if state == "unknown":
        return EvidenceItem(
            evidence_id=f"{domain}-missing",
            domain=domain,
            status=EvidenceStatus.MISSING,
            value=None,
            missing_reason=missing_reason,
        )
    if state == "conflicting":
        return EvidenceItem(
            evidence_id=f"{domain}-conflicting",
            domain=domain,
            status=EvidenceStatus.CONFLICTING,
            value=builder(retrieved_at=retrieved_at, **value_overrides),
            sources=sources,
            conflict_details=(conflict_detail,),
        )
    if state == "confirmed_absent":
        return EvidenceItem(
            evidence_id=f"{domain}-absent",
            domain=domain,
            status=EvidenceStatus.SOURCED,
            value={
                "kind": "confirmed_absent",
                "scope": {
                    "origin": "甲站",
                    "destination": "乙站",
                    "window": "2026-08-04~2026-08-07",
                },
                "retrieved_at": retrieved_at,
            },
            sources=sources,
        )
    status = (
        EvidenceStatus.ESTIMATED if state == "estimated" else EvidenceStatus.SOURCED
    )
    return EvidenceItem(
        evidence_id=f"{domain}-{state}",
        domain=domain,
        status=status,
        value=builder(retrieved_at=retrieved_at, **value_overrides),
        sources=sources,
    )


def evidence_dict(domain: str, state: str = "sourced", **kwargs: Any) -> dict[str, Any]:
    """同 :func:`evidence`，但返回落盘形状的 dict。"""

    return evidence(domain, state, **kwargs).to_dict()


def all_domains(state: str = "sourced", **kwargs: Any) -> dict[str, EvidenceItem]:
    """三个域各一条，同一 support 态。"""

    return {d: evidence(d, state, **kwargs) for d in ("railway", "map", "web")}
