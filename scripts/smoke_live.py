"""全链路真实数据冒烟：武汉 → 婺源，12306 + 高德实采。

**这不是测试，是验收工具。** 套件用受控证据与夹具，证明的是「逻辑对」；本脚本
用真实数据跑一遍产品路径，证明的是「功能在」。P0 至今这两件事一直没被分开验过，
第一次跑就撞出高德解析器的 7 个 dataclass 装饰器全丢（`c7cbd50`）。

用法（需要 AMAP_WEB_SERVICE_KEY 环境变量，且网络可达 12306 与高德）：

    ./.venv/Scripts/python.exe scripts/smoke_live.py

每一步打印「预期看到什么」与实测值。任何一步的实测与预期不符即为失败，如实
打印后继续往下走——冒烟的价值在于一次跑完拿到完整问题列表，不是第一处就停。
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trip_decider.destination_runtime import (  # noqa: E402
    collect_map_evidence,
    collect_railway_evidence,
)
from trip_decider.dynamic_discovery import (  # noqa: E402
    collect_live_destination_profile,
)
from trip_decider.evidence_projection import (  # noqa: E402
    project_domain,
    verdict_payload,
)
from trip_decider.planning_input_compiler import (  # noqa: E402
    PlanningInputCompiler,
)
from trip_decider.travel_agent import TravelIntent  # noqa: E402


ORIGIN = "武汉"
DESTINATION = "婺源"

_FAILURES: list[str] = []


def step(number: str, what: str, expected: str) -> None:
    print(f"\n=== 步骤 {number}：{what}")
    print(f"    预期：{expected}")


def ok(detail: str) -> None:
    print(f"    [通过] {detail}")


def bad(detail: str) -> None:
    print(f"    [失败] {detail}")
    _FAILURES.append(detail)


def _intent() -> TravelIntent:
    """真实近期日期：从今天起第 11 天出发，玩两晚。

    不写死日期——12306 只放售一段时间窗内的车次，写死的日期几个月后必然查不到，
    那时冒烟会以为是代码坏了（D11 的同一条道理：夹具里的死时间戳与 now 的关系
    是活的）。
    """

    start = datetime.now(timezone.utc) + timedelta(days=11)
    end = start + timedelta(days=2)
    return TravelIntent.from_mapping(
        {
            "task_mode": "DIRECT_PLAN",
            "origin": ORIGIN,
            "destination_anchor": DESTINATION,
            "destination_expression": f"想去{DESTINATION}",
            "earliest_departure_at": start.strftime("%Y-%m-%dT08:00"),
            "latest_return_at": end.strftime("%Y-%m-%dT20:00"),
            "travelers": 2,
            "total_budget_cny": 4000,
            "themes": ["自然风光"],
        }
    )


def main() -> int:
    print("trip-decider 全链路真实数据冒烟")
    print(f"仓库：{REPO_ROOT}")
    if not os.environ.get("AMAP_WEB_SERVICE_KEY"):
        print("\n[停] AMAP_WEB_SERVICE_KEY 未设置，高德相关步骤无法进行。")
        return 2

    intent = _intent()
    print(f"意图：{ORIGIN} → {DESTINATION}")
    print(
        f"行程窗：{intent.earliest_departure_at} .. {intent.latest_return_at}"
    )

    evidence: dict[str, object] = {}

    step("1", "12306 实采跨城往返", "SOURCED，去返程各有车次、时刻与二等座票价")
    rail = collect_railway_evidence(intent)
    if rail.status.is_usable and isinstance(rail.value, dict):
        out = rail.value.get("outbound") or {}
        back = rail.value.get("return") or {}
        ok(
            f"去程 {out.get('train_code')} "
            f"{out.get('departure_at')}→{out.get('arrival_at')} "
            f"¥{out.get('second_class_fare_cny_per_person')}"
        )
        ok(
            f"返程 {back.get('train_code')} "
            f"{back.get('departure_at')}→{back.get('arrival_at')} "
            f"¥{back.get('second_class_fare_cny_per_person')}"
        )
        evidence["railway"] = rail.to_dict()
    else:
        bad(f"铁路证据不可用：{rail.missing_reason}")

    step("2", "高德实采目的地行政区", "SOURCED，解析出 name/adcode/level")
    map_item = collect_map_evidence(intent)
    if map_item.status.is_usable and isinstance(map_item.value, dict):
        ok(f"destination={map_item.value.get('destination')}")
        evidence["map"] = map_item.to_dict()
    else:
        bad(f"地图证据不可用：{map_item.missing_reason}")

    step("3", "高德实采景点与住宿候选", "SOURCED，attractions 与 hotel_candidates 非空")
    try:
        web = collect_live_destination_profile(intent)
    except Exception as error:  # noqa: BLE001 - 冒烟要如实记异常类型
        bad(f"web 采集抛出 {type(error).__name__}: {error}")
        web = None
    if web is not None and web.status.is_usable and isinstance(web.value, dict):
        attractions = web.value.get("attractions") or []
        hotels = web.value.get("hotel_candidates") or []
        ok(f"景点 {len(attractions)} 个，住宿候选 {len(hotels)} 个")
        if not attractions:
            bad("景点为空——编译器会因此判 WEB_INPUT_UNAVAILABLE")
        evidence["web"] = web.to_dict()
    elif web is not None:
        bad(f"web 证据不可用：{web.missing_reason}")

    step(
        "4",
        "读取时刻定级（两轴 token）",
        "刚采到的证据应为 verified；非 verified 必须带 next_action",
    )
    # 读取时刻必须取在**采集之后**。第一版把 now 取在采集之前，于是
    # now - retrieved_at < 0，三个域全判 undated（§3.2 的未来时间戳规则）——
    # 那是脚本的时序错，不是产品缺陷。真实读取永远发生在采集之后。
    now = datetime.now(timezone.utc)
    for domain in ("railway", "map", "web"):
        item = evidence.get(domain)
        if not isinstance(item, dict):
            bad(f"{domain}: 没有证据可定级")
            continue
        payload = verdict_payload(
            project_domain({domain: item}, domain, now=now)
        )
        token = payload["token"]
        has_action = "next_action" in payload
        if token == "verified" and not has_action:
            ok(f"{domain}: {token}")
        elif token != "verified" and has_action:
            ok(f"{domain}: {token}（带 next_action，符合 I3a 双向约束）")
        else:
            bad(f"{domain}: token={token} 与 next_action 存在性不符 I3a")

    step("5", "编译计划", "产出 days/事件，planning_state 非空")
    context = {
        "context_id": "smoke",
        "intent": intent.to_dict(),
        "evidence": [
            {
                "evidence_id": "confirmed-travel-intent",
                "domain": "user_input",
                "status": "sourced",
                "value": intent.to_dict(),
                "sources": [{"source_type": "user_supplied"}],
            },
            *[item for item in evidence.values() if isinstance(item, dict)],
        ],
    }
    try:
        compiled = PlanningInputCompiler().compile(context, now=now)
    except Exception as error:  # noqa: BLE001
        bad(f"编译抛出 {type(error).__name__}: {error}")
        compiled = None
    if compiled is not None:
        state = compiled.get("planning_state")
        events = sum(len(day["events"]) for day in compiled["days"])
        ok(f"planning_state={state}，共 {events} 个事件")
        blockers = [
            str(item.get("blocker_id"))
            for item in compiled.get("conditional_blockers", [])
        ]
        print(f"    blockers：{blockers or '（无）'}")
        rail_events = compiled.get("cross_city_rail_events") or []
        if len(rail_events) == 2:
            ok("跨城往返两段都排上了")
        else:
            bad(f"跨城车次事件 {len(rail_events)} 段，预期 2 段")

    print("\n" + "=" * 60)
    if _FAILURES:
        print(f"冒烟完成，{len(_FAILURES)} 处不符预期：")
        for item in _FAILURES:
            print(f"  - {item}")
        return 1
    print("冒烟完成，全部步骤符合预期。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
