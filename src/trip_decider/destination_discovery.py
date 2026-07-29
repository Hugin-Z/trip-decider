"""Rank preliminary destination seeds without claiming feasibility."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path


_CATALOG_PATH = Path(__file__).with_name("destination_catalog.json")
_ALLOWED_PACES = {"轻松", "适中", "紧凑"}
_ALLOWED_TRANSPORT = {"高铁", "自驾", "飞机"}
_INTENSITY_FIT = {
    "轻松": {"轻松": 15.0, "适中": 8.0, "偏高": 2.0},
    "适中": {"轻松": 11.0, "适中": 15.0, "偏高": 8.0},
    "紧凑": {"轻松": 8.0, "适中": 13.0, "偏高": 15.0},
}


class DiscoveryInputError(ValueError):
    """Raised when a discovery request is structurally invalid."""


def load_destination_catalog() -> dict[str, object]:
    document = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("destination catalog must be an object")
    if document.get("scope") != "candidate_seed_library":
        raise RuntimeError("destination catalog must be a seed library")
    if (
        document.get("catalog_status")
        != "CANDIDATE_SEEDS_NOT_FEASIBILITY_VERIFIED"
    ):
        raise RuntimeError("destination catalog status is invalid")
    destinations = document.get("destinations")
    if not isinstance(destinations, list) or not 20 <= len(destinations) <= 30:
        raise RuntimeError("destination catalog must contain 20 to 30 entries")
    ids: set[str] = set()
    required = {
        "id",
        "name",
        "region_label",
        "province",
        "planning_city",
        "planning_adcode",
        "gateway_label",
        "themes",
        "suggested_days",
        "intensity",
        "access_modes",
        "season_months",
        "season_note",
        "summary",
        "confidence",
        "missing_fields",
    }
    for destination in destinations:
        if not isinstance(destination, dict):
            raise RuntimeError("destination entry must be an object")
        if set(destination) != required:
            raise RuntimeError("destination entry fields do not match contract")
        destination_id = destination["id"]
        if not isinstance(destination_id, str) or destination_id in ids:
            raise RuntimeError("destination ids must be unique strings")
        ids.add(destination_id)
        suggested = destination["suggested_days"]
        if (
            not isinstance(suggested, dict)
            or set(suggested) != {"min", "max"}
            or not isinstance(suggested["min"], (int, float))
            or not isinstance(suggested["max"], (int, float))
            or suggested["min"] <= 0
            or suggested["max"] < suggested["min"]
        ):
            raise RuntimeError("invalid suggested day range")
        if destination["intensity"] not in {"轻松", "适中", "偏高"}:
            raise RuntimeError("invalid destination intensity")
    policy = document.get("estimation_policy")
    if not isinstance(policy, dict):
        raise RuntimeError("catalog estimation policy is required")
    if policy.get("intercity_time") != "pending_external_source":
        raise RuntimeError("intercity time must remain pending")
    if policy.get("budget") != "pending_external_source":
        raise RuntimeError("budget must remain pending")
    return document


def _as_nonempty_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiscoveryInputError(f"{field} must be a non-empty string")
    return value.strip()


def normalize_discovery_request(
    request: Mapping[str, object],
) -> dict[str, object]:
    origin = _as_nonempty_text(request.get("origin"), "origin")
    start_text = _as_nonempty_text(
        request.get("approximate_start_date"),
        "approximate_start_date",
    )
    try:
        start_date = date.fromisoformat(start_text)
    except ValueError:
        raise DiscoveryInputError(
            "approximate_start_date must use YYYY-MM-DD"
        ) from None
    days = request.get("days")
    budget = request.get("total_budget")
    travelers = request.get("travelers")
    if (
        not isinstance(days, (int, float))
        or isinstance(days, bool)
        or not 0.5 <= float(days) <= 30
    ):
        raise DiscoveryInputError("days must be between 0.5 and 30")
    if (
        not isinstance(budget, (int, float))
        or isinstance(budget, bool)
        or float(budget) < 0
    ):
        raise DiscoveryInputError("total_budget must be non-negative")
    if (
        not isinstance(travelers, int)
        or isinstance(travelers, bool)
        or not 1 <= travelers <= 20
    ):
        raise DiscoveryInputError("travelers must be between 1 and 20")
    themes_value = request.get("themes")
    if not isinstance(themes_value, Sequence) or isinstance(
        themes_value, (str, bytes)
    ):
        raise DiscoveryInputError("themes must be an array")
    themes = tuple(
        dict.fromkeys(
            _as_nonempty_text(theme, "theme") for theme in themes_value
        )
    )
    if not themes:
        raise DiscoveryInputError("at least one theme is required")
    pace = _as_nonempty_text(request.get("pace"), "pace")
    if pace not in _ALLOWED_PACES:
        raise DiscoveryInputError("unsupported pace")
    transport_value = request.get("transport_preferences")
    if not isinstance(transport_value, Sequence) or isinstance(
        transport_value, (str, bytes)
    ):
        raise DiscoveryInputError("transport_preferences must be an array")
    transport = tuple(
        dict.fromkeys(
            _as_nonempty_text(item, "transport preference")
            for item in transport_value
        )
    )
    if not transport or any(item not in _ALLOWED_TRANSPORT for item in transport):
        raise DiscoveryInputError("unsupported transport preference")
    return {
        "origin": origin,
        "approximate_start_date": start_date.isoformat(),
        "days": float(days),
        "total_budget": float(budget),
        "travelers": travelers,
        "themes": list(themes),
        "pace": pace,
        "transport_preferences": list(transport),
    }


def _day_score(days: float, minimum: float, maximum: float) -> float:
    if minimum <= days <= maximum:
        return 20.0
    distance = minimum - days if days < minimum else days - maximum
    return max(0.0, 20.0 - distance * 8.0)


def _candidate_card(
    destination: Mapping[str, object],
    request: Mapping[str, object],
    catalog_index: int,
) -> dict[str, object]:
    requested_themes = set(request["themes"])
    destination_themes = set(destination["themes"])
    matched_themes = [
        theme for theme in request["themes"] if theme in destination_themes
    ]
    theme_score = 55.0 * len(matched_themes) / len(requested_themes)
    day_range = destination["suggested_days"]
    days_score = _day_score(
        float(request["days"]),
        float(day_range["min"]),
        float(day_range["max"]),
    )
    intensity_score = _INTENSITY_FIT[str(request["pace"])][
        str(destination["intensity"])
    ]
    matching_transport = [
        mode
        for mode in request["transport_preferences"]
        if mode in destination["access_modes"]
    ]
    transport_score = 10.0 if matching_transport else 0.0
    start_month = date.fromisoformat(
        str(request["approximate_start_date"])
    ).month
    season_fit = start_month in destination["season_months"]
    season_score = 10.0 if season_fit else 3.0
    score = round(
        theme_score
        + days_score
        + intensity_score
        + transport_score
        + season_score,
        2,
    )
    reasons: list[str] = []
    if matched_themes:
        reasons.append("匹配主题：" + "、".join(matched_themes))
    if days_score == 20.0:
        reasons.append("建议天数与本次时长匹配")
    elif days_score:
        reasons.append("天数接近建议范围，需压缩或留白")
    if matching_transport:
        reasons.append("目录支持偏好交通：" + "、".join(matching_transport))
    reasons.append(
        "季节目录：" + ("适配" if season_fit else "需进一步复核")
    )
    return {
        "destination_id": destination["id"],
        "name": destination["name"],
        "region_label": destination["region_label"],
        "province": destination["province"],
        "summary": destination["summary"],
        "score": score,
        "catalog_order": catalog_index,
        "match_reasons": reasons,
        "suggested_days": dict(day_range),
        "intercity_time": {
            "status": "待接数据源",
            "value": None,
            "required_source": "铁路/航空/公路班次与时刻数据",
        },
        "budget_range": {
            "status": "待接数据源",
            "currency": "CNY",
            "value": None,
            "required_source": "实时跨城交通、住宿与门票价格",
        },
        "feasibility_status": "UNKNOWN",
        "recommended_gateway": None,
        "roundtrip_transport_duration_seconds": None,
        "roundtrip_transport_cost_cny": None,
        "feasibility_conditions": [
            "尚未执行真实跨城交通验证。"
        ],
        "feasibility_risks": [],
        "themes": list(destination["themes"]),
        "intensity": destination["intensity"],
        "season_fit": "适配" if season_fit else "需复核",
        "season_note": destination["season_note"],
        "confidence": destination["confidence"],
        "missing_fields": list(destination["missing_fields"]),
    }


def rank_destination_candidates(
    raw_request: Mapping[str, object],
    *,
    limit: int = 5,
    feasibility_assessments: (
        Mapping[str, Mapping[str, object]] | None
    ) = None,
) -> dict[str, object]:
    if not 3 <= limit <= 5:
        raise DiscoveryInputError("candidate limit must be 3 to 5")
    request = normalize_discovery_request(raw_request)
    catalog = load_destination_catalog()
    cards = [
        _candidate_card(destination, request, index)
        for index, destination in enumerate(catalog["destinations"])
    ]
    assessments = feasibility_assessments or {}
    allowed_statuses = {
        "FEASIBLE",
        "CONDITIONALLY_FEASIBLE",
        "INFEASIBLE",
        "UNKNOWN",
    }
    for card in cards:
        assessment = assessments.get(str(card["destination_id"]))
        if assessment is None:
            continue
        status = assessment.get("status")
        if status not in allowed_statuses:
            raise DiscoveryInputError("invalid feasibility status")
        card["feasibility_status"] = status
        card["recommended_gateway"] = assessment.get(
            "recommended_gateway"
        )
        selected_gateway = next(
            (
                gateway
                for gateway in assessment.get("gateways", [])
                if isinstance(gateway, Mapping)
                and gateway.get("gateway")
                == assessment.get("recommended_gateway")
            ),
            None,
        )
        if isinstance(selected_gateway, Mapping):
            card["rail_snapshot"] = selected_gateway.get(
                "snapshot",
                {
                    "status": "UNKNOWN",
                    "retrieved_at": None,
                    "display": "UNKNOWN · 未取得可用铁路快照",
                },
            )
            duration = selected_gateway.get(
                "roundtrip_transport_duration_seconds"
            )
            cost = selected_gateway.get(
                "roundtrip_transport_cost_cny"
            )
            card["roundtrip_transport_duration_seconds"] = duration
            card["roundtrip_transport_cost_cny"] = cost
            card["intercity_time"] = {
                "status": (
                    "已取得真实快照"
                    if duration is not None
                    else "真实数据不完整"
                ),
                "value": duration,
                "unit": "seconds",
                "required_source": None,
            }
            card["budget_range"] = {
                "status": (
                    "仅已知交通"
                    if cost is not None
                    else "真实数据不完整"
                ),
                "currency": "CNY",
                "value": cost,
                "required_source": "住宿、餐饮、门票和当地游玩交通",
            }
        card["feasibility_conditions"] = list(
            assessment.get("conditions", [])
        )
        card["feasibility_risks"] = list(
            assessment.get("risks", [])
        )
        card["match_reasons"].insert(
            0,
            "真实跨城交通状态：" + str(status),
        )
        card["missing_fields"] = [
            field
            for field in card["missing_fields"]
            if field
            not in {"跨城实时班次", "跨城交通时长", "实时票价"}
        ]
    status_priority = {
        "FEASIBLE": 0,
        "CONDITIONALLY_FEASIBLE": 1,
        "UNKNOWN": 2,
        "INFEASIBLE": 3,
    }
    cards.sort(
        key=lambda item: (
            status_priority[str(item["feasibility_status"])],
            (
                float(item["roundtrip_transport_duration_seconds"])
                if item["roundtrip_transport_duration_seconds"] is not None
                else float("inf")
            ),
            (
                float(item["roundtrip_transport_cost_cny"])
                if item["roundtrip_transport_cost_cny"] is not None
                else float("inf")
            ),
            -float(item["score"]),
            item["catalog_order"],
        )
    )
    for card in cards:
        card.pop("catalog_order")
    evaluated_statuses = {
        str(card["feasibility_status"])
        for card in cards
        if str(card["destination_id"]) in assessments
    }
    return {
        "stage": "discover",
        "candidate_status": (
            next(iter(evaluated_statuses))
            if len(evaluated_statuses) == 1
            else "PRELIMINARY_NOT_FEASIBILITY_VERIFIED"
        ),
        "feasibility_status": (
            next(iter(evaluated_statuses))
            if len(evaluated_statuses) == 1
            else "UNKNOWN"
        ),
        "request": request,
        "preliminary_candidates": cards[:limit],
        "ranking_basis": [
            "真实跨城可达性状态",
            "真实往返交通时间占用",
            "已知往返交通费用",
            "主题重合",
            "建议天数接近度",
            "节奏与体力强度",
            "目录支持的交通偏好",
            "季节目录适配",
        ],
        "not_ranked": (
            ["住宿价格", "门票价格"]
            if assessments
            else [
                "实时跨城交通时长",
                "实时交通价格",
                "住宿价格",
                "门票价格",
            ]
        ),
        "catalog_version": catalog["catalog_version"],
        "disclaimer": (
            "仅带真实交通状态的候选完成了跨城可达性验证；总预算仍"
            "缺住宿、餐饮、门票和当地交通，因此条件可行不等于完整"
            "行程已经可发布。"
        ),
    }


def destination_detail(
    destination_id: str,
    raw_request: Mapping[str, object],
) -> dict[str, object]:
    request = normalize_discovery_request(raw_request)
    catalog = load_destination_catalog()
    destination = next(
        (
            item
            for item in catalog["destinations"]
            if item["id"] == destination_id
        ),
        None,
    )
    if destination is None:
        raise DiscoveryInputError("unknown destination_id")
    return {
        "stage": "plan",
        "request": request,
        "destination": {
            **dict(destination),
            "catalog_role": "preliminary_candidate_index_only",
        },
        "plan_status": "DESTINATION_CONTEXT_DATA_PENDING",
        "modules": {
            "intercity": {
                "title": "出发地 → 目的地 → 返程",
                "gateway": "待动态证据解析",
                "outbound": "待接数据源",
                "arrival_time": "待接数据源",
                "return_time": "待接数据源",
                "return_trip": "待接数据源",
                "required_source": "铁路12306/航班/公路班次与实时票价",
            },
            "stay": {
                "title": "住宿区域与酒店通勤",
                "area": "待接数据源",
                "hotel_to_first_stop": "待接数据源",
                "last_stop_to_hotel": "待接数据源",
                "required_source": "住宿区域、酒店坐标、房价与可订状态",
            },
            "local_route": {
                "title": "当地地点解析与路线",
                "engine": "trip_decider.simple_live",
                "status": "已连接，等待用户填写当地必去地点",
                "supports": [
                    "高德行政区查询",
                    "POI精确匹配与歧义保留",
                    "walking/driving 路线",
                    "每日时间轴",
                ],
                "limitations": [
                    "多候选不会自动选第一项",
                    "营业时间、排队、门票尚未核实",
                ],
            },
            "timeline": {
                "title": "每日时间轴",
                "days": request["days"],
                "status": "等待跨城抵达/返程时间和当地必去地点",
            },
            "budget": {
                "title": "预算拆分",
                "user_total_budget": request["total_budget"],
                "travelers": request["travelers"],
                "transport": "待接数据源",
                "stay": "待接数据源",
                "tickets": "待接数据源",
                "local_transport": "待接数据源",
            },
            "map": {
                "title": "地图与路线",
                "status": "等待当地地点解析与路线结果",
                "complex_map": False,
            },
            "alternatives": {
                "title": "雨天 / 时间不足备选",
                "rain_plan": "待接数据源",
                "short_time_plan": "待接数据源",
                "required_source": "天气预报、景点开放状态与室内地点数据",
            },
        },
        "missing_real_sources": [
            "跨城铁路/航班/公路时刻与票价",
            "住宿区域、酒店坐标、价格与可订状态",
            "景点开放时间、门票与临时关闭",
            "天气预报与雨天可用性",
        ],
    }
