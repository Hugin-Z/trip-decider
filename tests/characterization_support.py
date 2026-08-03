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

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
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

FRESH_AT = "2026-08-02T18:00:00+08:00"  # = 10:00 UTC
# 表征的读取时刻。与 FRESH_AT 的关系是契约：**恰好晚 1 小时**，因此全部
# data_type 都在各自的容差窗内（最短的是 hotel_price 的 0 秒容差，它靠
# stale_allowed=False 单独处理，不受此常量影响）。
#
# 读取时刻必须是钉死的输入。P4-b2 之前表征靠墙钟，而夹具时间戳是写死的
# 今天——两者的差值每天在变，改造后基线会自行翻面。要造陈旧场景就加第二个
# 常量，不要动 FRESH_AT。
CHAR_NOW = datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc)  # = 19:00+08:00
# FRESH_AT 后 7 小时：超出铁路 6 小时容差，用于翻面路径的正向用例。
STALE_NOW = datetime(2026, 8, 2, 17, 0, tzinfo=timezone.utc)  # = 次日 01:00+08:00
NOW = CHAR_NOW  # 兼容既有引用；同一个时刻只许有一份定义

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


def _guided_snapshot(
    items: dict[str, EvidenceItem],
    *,
    now: datetime = CHAR_NOW,
) -> dict[str, Any]:
    """判定点 1：候选 feasibility_status 与候选卡的证据状态。"""

    broker = EvidenceBroker(clock=lambda: now)

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
                clock=lambda: now,
            )
    except Exception as error:  # noqa: BLE001 - 表征测试要记录异常本身
        return {"error": f"{type(error).__name__}: {error}"}

    # 准入过滤（能力 A v0）之后，「候选被拦下」也是一种判定结果——它必须进
    # 表征，否则「本来有候选、后来一个都不剩」这类变化不会响。退回区是 I7
    # 第 4 条要求的可见位置，同样进快照。
    rejected = [
        {
            "name": entry.get("name"),
            "token": entry.get("token"),
            "reason": entry.get("reason"),
            "next_action_kind": (entry.get("next_action") or {}).get("kind"),
        }
        for entry in result.get("rejected_candidates", [])
    ]
    if not result["options"]:
        return {
            "admitted_count": 0,
            "rejected": rejected,
            "no_feasible_candidates": result.get("no_feasible_candidates"),
            "relaxation_hint": result.get("relaxation_hint"),
            "conflict_details_visible": "来源A与来源B不一致" in repr(result),
        }
    option = result["options"][0]
    return {
        "admitted_count": len(result["options"]),
        "rejected": rejected,
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


def _planning_snapshot(
    items: dict[str, EvidenceItem],
    *,
    now: datetime = CHAR_NOW,
) -> dict[str, Any]:
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
        compiled = PlanningInputCompiler().compile(context, now=now)
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
        # 两个引用键各有含义（persistence-v2.md §7.4）：evidence_refs 指整个
        # 证据项，fact_refs 指具体字段。快照分开记——合成一列会让「引用降级成
        # 域级」这类变化看不出来。
        "blocker_evidence_refs": sorted(
            reference
            for item in compiled.get("conditional_blockers", [])
            if isinstance(item, Mapping)
            for reference in item.get("evidence_refs", [])
        ),
        "blocker_fact_refs": sorted(
            reference
            for item in compiled.get("conditional_blockers", [])
            if isinstance(item, Mapping)
            for reference in item.get("fact_refs", [])
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


def _full_run_snapshot(*, now: datetime = CHAR_NOW) -> dict[str, Any]:
    """完整 run 直到计划安装——**哑火检测器**。

    P4-a 的 fixture 收编把动作循环掐断了：run 停在 RUNNING，
    ``plan-version.json`` 与 ``plans/`` 根本没写出来，而套件全绿、无异常。
    后果是 I1 的落盘测量少了 227 处命中却没人发现（差点当成截肢的成果）。

    其余场景都只驱动 ``build_guided_comparison`` 与 ``PlanningInputCompiler``，
    走不到动作循环，因此抓不到那类断裂。这一条驱动到计划真正落盘为止。
    """

    from tempfile import TemporaryDirectory

    from trip_decider.agent_actions import reset_read_clock, set_read_clock
    from tests.invariant_support import drive_offline_run

    set_read_clock(lambda: now)
    try:
        return _full_run_body(now)
    finally:
        reset_read_clock()


def _full_run_body(now: datetime) -> dict[str, Any]:
    from tempfile import TemporaryDirectory

    from tests.invariant_support import drive_offline_run

    with TemporaryDirectory() as temporary:
        try:
            application, _query, run_id = drive_offline_run(
                Path(temporary) / "sessions"
            )
        except Exception as error:  # noqa: BLE001 - 表征测试要记录异常本身
            return {"error": f"{type(error).__name__}: {error}"}
        directory = application.store.run_directory(run_id)
        if directory is None:
            return {"error": "run_directory is None"}
        plan_version_path = directory / "plan-version.json"
        installed = (
            json.loads(plan_version_path.read_text(encoding="utf-8"))
            if plan_version_path.is_file()
            else None
        )
        return {
            "run_status": application.store.get_run(run_id).status.value,
            "plan_version_written": plan_version_path.is_file(),
            "plan_version_number": (
                installed.get("plan_version")
                if isinstance(installed, dict)
                else None
            ),
            "plans_directory_count": len(
                sorted((directory / "plans").glob("plan-*.json"))
            ),
            "files": sorted(
                path.relative_to(directory).as_posix()
                for path in directory.rglob("*")
                if path.is_file()
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
            "stale_read_planning": _planning_snapshot(items, now=STALE_NOW),
        }
    # 完整 run 只跑一次——它驱动真实动作循环，比其余场景重得多。
    snapshot["full_run_until_plan_installed"] = _full_run_snapshot()
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


def diff_paths(lines: Sequence[str]) -> list[str]:
    """从 diff 行里抽出路径，供「变化只该落在哪几个字段上」这类断言使用。

    逐条肉眼看差异会漏；断言**路径集合**能抓住「还有别的字段也动了」这一类，
    那正是改名批次里最容易被当成噪音放过去的信号。
    """

    return [str(line).splitlines()[0] for line in lines]


def check() -> list[str]:
    """当前快照与基线文件的差异。空列表即零 diff。"""

    return diff(load_baseline(), capture())


def _main(argv: Sequence[str]) -> int:
    """核对优先。裸跑**不写盘**——重刷必须显式带 ``--save``。

    此前这里是 ``save_baseline(capture())`` 一行，裸跑即覆盖。那让重刷从
    「确认」退回成「信任」：谁都可能在没看过差异的情况下把基线洗掉，而基线
    是判断其他改动有没有踩坏东西的唯一工具。
    """

    mismatches = check()
    if not mismatches:
        print("表征零 diff。基线与当前快照一致，无需重刷。")
        return 0

    print(f"表征差异 {len(mismatches)} 条：\n")
    for item in mismatches:
        print(item)
    print("\n受影响的字段路径：")
    for path in sorted(set(diff_paths(mismatches))):
        print(f"  {path}")

    if "--save" not in argv:
        print(
            "\n未重刷。确认以上每一条都在本轮裁决表内之后，"
            "再跑 `python -m tests.characterization_support --save`。"
            "\n表外的差异即停——那是改坏了，不是该重刷的理由。"
        )
        return 1

    save_baseline(capture())
    print(f"\n已重刷基线：{BASELINE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
