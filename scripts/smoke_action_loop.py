"""动作循环全链路真实数据冒烟：GUIDED_DISCOVERY → 候选 → 选择 → PlanVersion → 重排。

与 `smoke_live.py` 的分工：那个直调采集器，验的是「采集器与编译器能吃真实数据」；
**本脚本走动作循环本体**，验的是「产品的那条链路真的能跑通」。上一轮的冒烟绕过了
`_map_handler`，`local_transit` 因此为空、计划停在 COLLECTING_EVIDENCE——这次由
动作循环真实产出。

这条链路从 P0 至今**真实数据零覆盖**，而套件全绿。上一轮第一个真实调用就撞出
高德解析器死了 15 天（`c7cbd50` 丢了 7 个 dataclass 装饰器），所以这里每一段都
打印实测值，任何一段不符预期都如实记录并继续——一次跑完拿到完整问题列表，
比第一处就停有用。

用法：

    ./.venv/Scripts/python.exe scripts/smoke_action_loop.py

需要 AMAP_WEB_SERVICE_KEY 与网络。运行数据落在临时目录，不污染 runtime/。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trip_decider.travel_agent import (  # noqa: E402
    InMemoryAgentStore,
    TravelIntent,
)
from trip_decider.trip_application import TripApplicationService  # noqa: E402
from trip_decider.trip_query import TripQueryService  # noqa: E402


_FAILURES: list[str] = []
_NOTES: list[str] = []


def step(number: str, what: str, expected: str) -> None:
    print(f"\n=== {number}. {what}")
    print(f"    预期：{expected}")


def ok(detail: str) -> None:
    print(f"    [通过] {detail}")


def bad(detail: str) -> None:
    print(f"    [失败] {detail}")
    _FAILURES.append(detail)


def note(detail: str) -> None:
    print(f"    [记录] {detail}")
    _NOTES.append(detail)


def _intent() -> dict:
    """真实近期日期，不写死——12306 只放售一段时间窗内的车次（D11）。"""

    start = datetime.now(timezone.utc) + timedelta(days=11)
    end = start + timedelta(days=2)
    return {
        "task_mode": "GUIDED_DISCOVERY",
        "origin": "武汉",
        "destination_expression": "想找个山里安静的地方待两天",
        "earliest_departure_at": start.strftime("%Y-%m-%dT08:00"),
        "latest_return_at": end.strftime("%Y-%m-%dT20:00"),
        "travelers": 2,
        "total_budget_cny": 4000,
        "themes": ["自然风光"],
        # confirm_intent 要求这两项齐备（intent_missing_required_fields）
        "pace": "relaxed",
        "transport_preferences": ["high_speed_rail"],
    }


def _evidence_snapshot(query: TripQueryService, run_id: str) -> None:
    """A10 取证格式：每次读取存一份 evidence_statuses。

    顺带验证记录流程本身可操作——A10 要求「每条 verified token 均未被现实证伪」，
    前提是拿得到一份可核对的 token 清单。
    """

    try:
        trip = query.trip(run_id)
    except Exception as error:  # noqa: BLE001
        note(f"读取快照失败：{type(error).__name__}: {error}")
        return
    presentation = trip.get("presentation") or {}
    statuses = presentation.get("evidence_statuses")
    if statuses is None:
        # 形状可能随版本不同，退而记录 presentation 的键，便于下一轮定位
        note(f"presentation 无 evidence_statuses，键：{sorted(presentation)[:12]}")
        return
    print(f"    证据快照：{json.dumps(statuses, ensure_ascii=False)[:400]}")


def main() -> int:
    print("trip-decider 动作循环全链路真实数据冒烟")
    if not os.environ.get("AMAP_WEB_SERVICE_KEY"):
        print("\n[停] AMAP_WEB_SERVICE_KEY 未设置。")
        return 2

    temporary = TemporaryDirectory()
    store = InMemoryAgentStore(runtime_root=Path(temporary.name) / "sessions")
    application = TripApplicationService(store=store)
    query = TripQueryService(store=store, application_service=application)

    intent = _intent()
    print(f"意图：{intent['origin']} → {intent['destination_expression']}")
    print(f"行程窗：{intent['earliest_departure_at']} .. {intent['latest_return_at']}")

    step("1", "创建任务并确认意图", "run 进入 CONFIRMED")
    created = application.create_trip(intent)
    run_id = created.run_id
    application.confirm_trip(run_id)
    status = store.get_run(run_id).status
    ok(f"run_id={run_id} status={status.value}")

    step("2", "执行引导式发现（真实采集）", "产出候选，stage=guided_discovery")
    try:
        application.execute_trip(run_id)
    except Exception as error:  # noqa: BLE001
        bad(f"execute_trip 抛出 {type(error).__name__}: {error}")
    # 引导式发现在**后台线程**里跑，execute_trip 只负责派工就返回。
    # 不等就读候选，必然报「comparison is not available」——那是时序，不是缺陷。
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        run = store.get_run(run_id)
        if run.status.value != "RUNNING" or run.result:
            break
        time.sleep(2)
    run = store.get_run(run_id)
    waited = int(240 - (deadline - time.monotonic()))
    print(
        f"    等待 {waited}s 后 run.status={run.status.value} "
        f"error_code={run.error_code}"
    )
    if run.error_code:
        bad(f"运行以 {run.error_code} 停止（detail={run.error_detail}）")

    step("3", "读取候选", "≥1 个候选，每个带 evidence_statuses")
    options: list = []
    try:
        payload = query.candidates(run_id)
        options = payload.get("candidates") or []
        ok(f"候选 {len(options)} 个，stage={payload.get('stage')}")
        for option in options[:3]:
            print(
                f"      - {option.get('destination_id')} "
                f"feasibility={option.get('feasibility_status')} "
                f"playable={option.get('playable_time_seconds')}"
            )
    except Exception as error:  # noqa: BLE001
        bad(f"读取候选失败：{type(error).__name__}: {error}")

    if not options:
        print("\n候选为空，后续步骤无法进行。")
        return _finish()

    step("4", "选定第一个候选", "同一 run 继续，进入详细规划")
    destination_id = str(options[0].get("destination_id"))
    try:
        application.select_candidate(run_id, destination_id)
        ok(f"已选 {destination_id}，status={store.get_run(run_id).status.value}")
    except Exception as error:  # noqa: BLE001
        bad(f"select_candidate 失败：{type(error).__name__}: {error}")
        return _finish()

    step(
        "5",
        "推进动作循环至计划产出（含 _map_handler 真实产出 local_transit）",
        "planner 完成，PlanVersion 安装，local_transit 非空",
    )
    for attempt in range(1, 9):
        snapshot = application.next_actions(run_id)
        status = str(snapshot.get("status"))
        actions = snapshot.get("actions") or []
        print(f"    第 {attempt} 轮：status={status} 待执行 {len(actions)} 个")
        if status == "READY":
            ok("动作循环报告 READY")
            break
        executable = [
            str(action.get("action_id"))
            for action in actions
            if action.get("action_type") == "registered_tool"
        ]
        if not executable:
            note(f"无可自动执行的动作，剩余：{[a.get('action_id') for a in actions]}")
            break
        for action_id in executable:
            try:
                application.retry_action(run_id, action_id)
            except Exception as error:  # noqa: BLE001
                bad(f"执行 {action_id} 失败：{type(error).__name__}: {error}")
    _evidence_snapshot(query, run_id)

    step("6", "计划可用性与一次修改重排", "usable_now 为真；重排后产生新版本")
    readiness = query.plan_readiness(run_id)
    print(f"    readiness={readiness}")
    if readiness.get("written"):
        ok(f"已写入版本 {readiness.get('plan_version')}")
    else:
        bad("没有已写入的 PlanVersion——链路未走到计划安装")
    if readiness.get("usable_now"):
        ok(f"当前可用，planning_state={readiness.get('planning_state')}")
    else:
        note(
            f"当前不可用：planning_state={readiness.get('planning_state')}，"
            f"blockers={[b.get('blocker_id') for b in readiness.get('blockers', [])]}"
        )

    if readiness.get("written"):
        before = readiness.get("plan_version")
        try:
            application.revise_trip(
                run_id,
                {"note": "第二天别排那么满"},
            )
            after = query.plan_readiness(run_id).get("plan_version")
            if after != before:
                ok(f"重排产生新版本：{before} → {after}")
            else:
                note(f"重排后版本号未变（仍为 {after}）")
        except Exception as error:  # noqa: BLE001
            bad(f"revise_trip 失败：{type(error).__name__}: {error}")

    return _finish()


def _finish() -> int:
    print("\n" + "=" * 60)
    if _NOTES:
        print(f"记录 {len(_NOTES)} 条（降级可用，不挡链路）：")
        for item in _NOTES:
            print(f"  - {item}")
    if _FAILURES:
        print(f"\n死路 {len(_FAILURES)} 条：")
        for item in _FAILURES:
            print(f"  - {item}")
        return 1
    print("\n动作循环链路跑通，无死路。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
