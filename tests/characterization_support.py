"""P3b 迁移守卫：29 闸门改造的表征测试脚手架。

`docs/contracts/p3b-gate-inventory.md` §6 指出：I7 只守 29 处中的 2 处，其余
27 处没有直接的不变式守卫。既有回归的 fixture 是按旧行为写的，它守不住
「改造后行为符合清单预期」这件事。

本模块提供一个固定证据 fixture，跑完整规划链路，把三个可行性判定点的输出
规范化成一份快照。改造前后各跑一次，diff 出来的每一条都必须能在清单的
「预期影响」列里找到对应；找不到的就是事故。

**这不是不变式，是一次性的迁移守卫。** P3b 结束后可降级为普通回归 fixture。

判定点（`docs/contracts/freshness-policy.md` §3.1）：
  判定点 1  候选 feasibility_status   guided_discovery.py:520-536
  判定点 2  计划 planning_state       planning_input_compiler.py:216-227
  判定点 3  conditional_blockers      planning_input_compiler.py 的 17 处 _blocker
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.guided_discovery import build_guided_comparison
from trip_decider.planning_input_compiler import PlanningInputCompiler
from trip_decider.travel_agent import (
    EvidenceItem,
    EvidenceStatus,
    TravelIntent,
)

from tests.evidence_factory import evidence as factory_evidence

BASELINE_PATH = Path(__file__).with_name("characterization_baseline.json")

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
FRESH_AT = "2026-08-02T18:00:00+08:00"  # = 10:00 UTC，各 data_type 均在窗内

_SEEDS = [
    {
        "id": "destination-one",
        "name": "目的地一",
        "region_label": "某区域",
        "planning_city": "目的地一",
        "rail_gateway": "目的地一",
        "themes": [],
        "intensity": "standard",
    }
]


def intent() -> TravelIntent:
    return TravelIntent.from_mapping(
        {
            "task_mode": "DIRECT_PLAN",
            "origin": "甲地",
            "destination_anchor": "乙地",
            "earliest_departure_at": "2026-08-04T12:00:00",
            "latest_return_at": "2026-08-07T22:00:00",
            "travelers": 2,
            "total_budget_cny": 6000,
            "pace": "relaxed",
            "transport_preferences": ["rail"],
        }
    )


# ---------------------------------------------------------------------------
# 证据构造：四态 + confirmed_absent
# ---------------------------------------------------------------------------


# 证据构造统一走 tests/evidence_factory（persistence-v2.md §10）。本模块此前
# 自带一份 railway/map/web 的形状定义，与 invariant_support 里的那份是两套——
# 正是 P4-a 清点出的 9 种键集合中的两种。


def _estimated_status():
    """枚举扩展前 ESTIMATED 不存在；保留以兼容表征基线的历史语义。"""

    return getattr(EvidenceStatus, "ESTIMATED", None)


def evidence(domain: str, state: str, *, retrieved_at: str = FRESH_AT):
    """委托给共享工厂。返回 None 表示该 state 在当前枚举下不可构造。"""

    if state == "estimated" and _estimated_status() is None:
        return None
    return factory_evidence(domain, state, retrieved_at=retrieved_at)


# ---------------------------------------------------------------------------
# 场景表：每条覆盖一组闸门
# ---------------------------------------------------------------------------

SCENARIOS: tuple[tuple[str, dict[str, str]], ...] = (
    ("all_sourced", {"railway": "sourced", "map": "sourced", "web": "sourced"}),
    ("railway_unknown", {"railway": "unknown", "map": "sourced", "web": "sourced"}),
    (
        "railway_conflicting",
        {"railway": "conflicting", "map": "sourced", "web": "sourced"},
    ),
    (
        "railway_confirmed_absent",
        {"railway": "confirmed_absent", "map": "sourced", "web": "sourced"},
    ),
    ("map_unknown", {"railway": "sourced", "map": "unknown", "web": "sourced"}),
    (
        "map_conflicting",
        {"railway": "sourced", "map": "conflicting", "web": "sourced"},
    ),
    ("web_unknown", {"railway": "sourced", "map": "sourced", "web": "unknown"}),
    ("all_unknown", {"railway": "unknown", "map": "unknown", "web": "unknown"}),
    # estimated 场景：枚举扩展前不可构造，快照里记为 not_constructible
    ("railway_estimated", {"railway": "estimated", "map": "sourced", "web": "sourced"}),
    ("map_estimated", {"railway": "sourced", "map": "estimated", "web": "sourced"}),
    (
        "all_estimated",
        {"railway": "estimated", "map": "estimated", "web": "estimated"},
    ),
)


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------


def _guided_snapshot(items: dict[str, EvidenceItem]) -> dict[str, Any]:
    """判定点 1：候选 feasibility_status 与候选卡的证据状态。"""

    broker = EvidenceBroker(clock=lambda: NOW)

    def collector(_intent: TravelIntent) -> EvidenceItem:
        return items["railway"]

    try:
        with patch(
            "trip_decider.guided_discovery.guided_region_seeds",
            return_value=_SEEDS,
        ):
            result = build_guided_comparison(
                intent(),
                railway_collector=collector,
                run_id="characterization",
                evidence_broker=broker,
                clock=lambda: NOW,
            )
    except Exception as error:  # noqa: BLE001 - 表征测试要记录异常本身
        return {"error": f"{type(error).__name__}: {error}"}

    option = result["options"][0]
    return {
        "feasibility_status": option.get("feasibility_status"),
        "coarse_plan_status": option.get("coarse_plan_status"),
        "roundtrip_transport_status": (
            option.get("roundtrip_transport", {}).get("token")
            or option.get("roundtrip_transport", {}).get("status")
        ),
        "playable_time_seconds": option.get("playable_time_seconds"),
        "evidence_statuses": [
            {
                key: item.get(key)
                for key in ("domain", "status", "token", "conflict_details")
                if key in item
            }
            for item in option.get("evidence_statuses", [])
        ],
        "has_next_action": [
            item.get("domain")
            for item in option.get("evidence_statuses", [])
            if item.get("next_action")
        ],
        "conflict_details_visible": "来源A与来源B不一致" in repr(option),
        "evidence_missing_count": len(option.get("evidence_missing", [])),
        "conditions": list(option.get("conditions", [])),
    }


def _planning_snapshot(items: dict[str, EvidenceItem]) -> dict[str, Any]:
    """判定点 2 与 3：planning_state 与 conditional_blockers。"""

    context = {
        "context_id": "characterization",
        "intent": intent().to_dict(),
        "evidence": [
            EvidenceItem(
                evidence_id="user",
                domain="user_input",
                status=EvidenceStatus.SOURCED,
                value=intent().to_dict(),
                sources=({"source_type": "user_supplied"},),
            ).to_dict(),
            *[item.to_dict() for item in items.values()],
        ],
        "built_at": FRESH_AT,
    }
    try:
        compiled = PlanningInputCompiler().compile(context)
    except Exception as error:  # noqa: BLE001
        return {"error": f"{type(error).__name__}: {error}"}

    return {
        "planning_state": compiled.get("planning_state"),
        "status": compiled.get("status"),
        "displayable": compiled.get("displayable"),
        "blockers": sorted(
            str(item.get("blocker_id"))
            for item in compiled.get("conditional_blockers", [])
            if isinstance(item, Mapping)
        ),
        "blocker_fact_refs": sorted(
            str(item.get("fact_id"))
            for item in compiled.get("conditional_blockers", [])
            if isinstance(item, Mapping) and item.get("fact_id")
        ),
        "missing_requirements": sorted(
            str(
                item.get("reason") or item.get("domain") or item
                if isinstance(item, Mapping)
                else item
            )
            for item in compiled.get("missing_requirements", [])
        ),
        "rail_event_count": len(compiled.get("cross_city_rail_events", [])),
        "attraction_event_count": len(compiled.get("attraction_events", [])),
        "local_transit_event_count": len(compiled.get("local_transit_events", [])),
        "map_point_count": len(compiled.get("map_points", [])),
        "destination_resolved": (
            compiled.get("display_requirements", {}).get("destination_resolved")
        ),
    }


def capture() -> dict[str, Any]:
    """跑全部场景，返回规范化快照。"""

    snapshot: dict[str, Any] = {}
    for label, states in SCENARIOS:
        items: dict[str, EvidenceItem] = {}
        skipped = False
        for domain, state in states.items():
            item = evidence(domain, state)
            if item is None:
                skipped = True
                break
            items[domain] = item
        if skipped:
            snapshot[label] = {"not_constructible": "EvidenceStatus 无 ESTIMATED"}
            continue
        snapshot[label] = {
            "decision_point_1_guided": _guided_snapshot(items),
            "decision_point_2_3_planning": _planning_snapshot(items),
        }
    return snapshot


def load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def save_baseline(snapshot: dict[str, Any]) -> None:
    BASELINE_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def diff(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """逐路径比对，返回人类可读的差异行。"""

    lines: list[str] = []

    def walk(path: str, left: Any, right: Any) -> None:
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            for key in sorted(set(left) | set(right)):
                walk(f"{path}/{key}", left.get(key), right.get(key))
            return
        if left != right:
            lines.append(f"{path}\n    改造前: {left!r}\n    改造后: {right!r}")

    walk("", before, after)
    return lines


if __name__ == "__main__":  # 手工重新采基线用
    save_baseline(capture())
    print(f"baseline written to {BASELINE_PATH}")
