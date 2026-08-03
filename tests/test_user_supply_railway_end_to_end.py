"""宿主实测 P0 之一：user_supply 铁路证据的端到端链路。

事故（Claude Desktop MCP，2026-08-03）：宿主按 `railway_manual` 动作声明的
`required_fields`（`outbound` / `return` / `fare` / `source`）手工提交铁路证据，
四层校验全过，事件流写下「12306 查询取得有效证据」，随后 Planner 消费时
`KeyError: 'origin_station'`，run 落 `PLANNER_ACTION_FAILED` 且不再派发动作。

归因是 D2 的变体：**声明的表和消费的表不是同一张**。声明说要四个键，消费
（`itinerary_planner.make_rail_event`）按 `train_code` / `departure_at` /
`arrival_at` / `origin_station` / `destination_station` 逐个直取。宿主把声明
要的都给了，仍然过不了消费。

夹具是宿主的真实提交形状，脱敏后存放于
`fixtures/host_mcp_smoke/user_supply_railway.json`——**不补键**，缺席本身是证据。

本文件不依赖网络：三个采集器都由测试注入。
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider.agent_actions import (
    RAILWAY_MANUAL_OPTIONAL_FIELDS,
    RAILWAY_MANUAL_REQUIRED_FIELDS,
    execute_registered_action,
    get_next_actions,
    submit_evidence,
)
from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.itinerary_planner import RAIL_EVENT_REQUIRED_TRAIN_FIELDS
from trip_decider.travel_agent import (
    EvidenceItem,
    InMemoryAgentStore,
    RunStatus,
    TravelAgentError,
)
from trip_decider.trip_application import TripApplicationService

from tests.evidence_factory import railway_value
from tests.invariant_support import controlled_map, controlled_web, noop_collector

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "host_mcp_smoke"
    / "user_supply_railway.json"
)


def host_fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class _NoBackgroundApplication(TripApplicationService):
    """所有阶段跑在调用线程上，测试保持确定。"""

    @staticmethod
    def _spawn(*, target: object, args: object, name: str) -> None:
        del target, args, name


DIRECT_INTENT = {
    "task_mode": "DIRECT_PLAN",
    "origin": "甲地",
    "destination_anchor": "乙地",
    "destination_expression": "确定乙地",
    "earliest_departure_at": "2026-08-04T12:00",
    "latest_return_at": "2026-08-07T22:00",
    "travelers": 2,
    "total_budget_cny": 6000,
    "pace": "relaxed",
    "transport_preferences": ["rail"],
    "themes": ["自然"],
}


def complete_manual_submission() -> dict[str, object]:
    """一条**消费得动**的手工提交：按真实消费需求给全。"""

    produced = railway_value()
    return {
        "action_id": "railway",
        "evidence_id": "railway-user-supply",
        "domain": "railway",
        "status": "sourced",
        "value": {
            "outbound": dict(produced["outbound"]),
            "return": dict(produced["return"]),
        },
        "sources": [
            {
                "provider": "中国铁路12306",
                "retrieved_at": "2026-08-03T10:20:00+08:00",
            }
        ],
    }


class UserSupplyRailwayCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        root = Path(self._temporary.name) / "sessions"
        self.store = InMemoryAgentStore(root)
        self.application = _NoBackgroundApplication(
            store=self.store,
            evidence_broker=EvidenceBroker(root.parent / "evidence-cache"),
            railway_collector=noop_collector,
            map_collector=noop_collector,
            web_collector=noop_collector,
        )
        run = self.application.create_trip(DIRECT_INTENT)
        self.run_id = run.run_id
        self.application.confirm_trip(self.run_id)
        self.application.execute_trip(self.run_id)

    # -- 其余两个域，让 planner 真的跑得到铁路那一段 ----------------------

    def _supply_other_domains(self) -> None:
        submit_evidence(
            self.run_id,
            {**controlled_web().to_dict(), "action_id": "web"},
            store=self.store,
        )
        submit_evidence(
            self.run_id,
            {**controlled_map().to_dict(), "action_id": "map"},
            store=self.store,
        )

    def _manual_action(self) -> dict[str, object]:
        """采集失败后动作循环给出的手工填写动作。"""

        self.store.get_run(self.run_id)
        snapshot = get_next_actions(self.run_id, store=self.store)
        manual = [
            action
            for action in snapshot["actions"]
            if action.get("action_id") == "railway_manual"
        ]
        if manual:
            return manual[0]
        # 采集器返回 missing 时铁路动作转 failed，重新取一次快照即含手工动作。
        execute_registered_action(self.run_id, "railway", store=self.store)
        snapshot = get_next_actions(self.run_id, store=self.store)
        manual = [
            action
            for action in snapshot["actions"]
            if action.get("action_id") == "railway_manual"
        ]
        self.assertTrue(manual, "采集失败后没有派发 railway_manual 动作")
        return manual[0]

    # -- 1. 声明与消费同一张表（D2）---------------------------------------

    def test_declared_required_fields_are_exactly_what_the_planner_indexes(
        self,
    ) -> None:
        """动作声明的必填项必须覆盖消费端逐个直取的键。

        事故原句：声明 `outbound`/`return`/`fare`/`source`，消费按
        `origin_station` 取值。四个键全给了照样崩——因为两张表不是一张。
        """

        action = self._manual_action()
        declared = set(action.get("required_fields") or ())
        expected = {
            f"{direction}.{field}"
            for direction in ("outbound", "return")
            for field in RAIL_EVENT_REQUIRED_TRAIN_FIELDS
        }
        self.assertLessEqual(
            expected,
            declared,
            "消费端直取的键没有出现在动作声明里——宿主照声明填就会撞 KeyError。"
            f"缺的是：{sorted(expected - declared)}",
        )

    def test_optional_fields_are_declared_as_optional_not_required(self) -> None:
        """`.get()` 取的字段是可选项，不能混进必填项冒充硬要求。"""

        action = self._manual_action()
        optional = set(action.get("optional_fields") or ())
        required = set(action.get("required_fields") or ())
        self.assertTrue(
            optional,
            "手工动作没有声明可选项——票价/余票缺席是被容忍的，宿主该知道",
        )
        self.assertEqual(
            set(),
            optional & required,
            f"同一个字段既必填又可选：{sorted(optional & required)}",
        )

    # -- 2. 宿主原样提交必须在门口被拦下，并指明缺什么 ---------------------

    def test_host_submission_is_rejected_at_the_door(self) -> None:
        """宿主实测的那份提交：拦在门口，不许进屋再死。"""

        submission = host_fixture()["submission"]
        with self.assertRaises(TravelAgentError) as caught:
            submit_evidence(self.run_id, dict(submission), store=self.store)
        message = str(caught.exception)
        for missing in ("origin_station", "destination_station"):
            self.assertIn(
                missing,
                message,
                f"报错没有指明缺失的键 {missing!r}，宿主无从修正：{message}",
            )

    def test_rejected_submission_leaves_the_run_usable(self) -> None:
        """门口拦下不等于把 run 拍死：拒绝之后仍能提交修正版。"""

        submission = host_fixture()["submission"]
        with self.assertRaises(TravelAgentError):
            submit_evidence(self.run_id, dict(submission), store=self.store)

        self.assertIs(
            RunStatus.RUNNING,
            self.store.get_run(self.run_id).status,
            "一次被拒的提交把 run 打成了非 RUNNING——那就是新的死锁",
        )
        submit_evidence(
            self.run_id,
            complete_manual_submission(),
            store=self.store,
        )
        self._supply_other_domains()
        snapshot = execute_registered_action(
            self.run_id,
            "planner",
            store=self.store,
        )
        self.assertNotEqual(
            "BLOCKED",
            snapshot["status"],
            "修正后的提交仍然规划不出来",
        )

    # -- 3. 补齐消费需求的提交必须一路走通 --------------------------------

    def test_complete_manual_submission_reaches_a_plan(self) -> None:
        submit_evidence(
            self.run_id,
            complete_manual_submission(),
            store=self.store,
        )
        self._supply_other_domains()
        snapshot = execute_registered_action(
            self.run_id,
            "planner",
            store=self.store,
        )

        self.assertNotEqual("BLOCKED", snapshot["status"])
        self.assertIsNot(
            RunStatus.BLOCKED,
            self.store.get_run(self.run_id).status,
            "补齐消费需求后 run 仍然 BLOCKED",
        )

    # -- 4. 可恢复性：PLANNER_ACTION_FAILED 之后不许死锁 -------------------

    def test_a_planner_failed_run_recovers_on_corrected_resubmission(
        self,
    ) -> None:
        """宿主那个「救不回来」必须有出路。

        直接把 run 打成 `PLANNER_ACTION_FAILED`（不依赖崩溃本身还在），
        然后按修正后的证据重新提交，要求 run 能继续走到计划。
        """

        submit_evidence(
            self.run_id,
            complete_manual_submission(),
            store=self.store,
        )
        self._supply_other_domains()
        self.store.block(
            self.run_id,
            {"action_loop_status": "BLOCKED", "blocked_domains": ["planner"]},
            "PLANNER_ACTION_FAILED",
        )
        self.assertIs(RunStatus.BLOCKED, self.store.get_run(self.run_id).status)

        outcome = self.application.submit_run_evidence(
            self.run_id,
            complete_manual_submission(),
        )

        self.assertIsNotNone(outcome.action_loop)
        self.assertIs(
            RunStatus.RUNNING,
            self.store.get_run(self.run_id).status,
            "PLANNER_ACTION_FAILED 之后重新提交修正证据，run 没有恢复——死锁",
        )

    def test_blocked_run_states_how_to_recover(self) -> None:
        """死路必须自带出路说明，不能只留一个错误码。"""

        self.store.block(
            self.run_id,
            {"action_loop_status": "BLOCKED", "blocked_domains": ["planner"]},
            "PLANNER_ACTION_FAILED",
        )
        snapshot = get_next_actions(self.run_id, store=self.store)

        self.assertEqual("BLOCKED", snapshot["status"])
        self.assertTrue(
            snapshot.get("recovery"),
            "BLOCKED 快照没有 recovery 字段：宿主只看到 PLANNER_ACTION_FAILED，"
            "无从知道重新提交证据就能继续",
        )


class RailwayManualFieldListsCase(unittest.TestCase):
    """必填/可选清单本身的形态——不需要跑 run。"""

    def test_required_list_is_derived_from_the_consumption_constant(self) -> None:
        expected = tuple(
            f"{direction}.{field}"
            for direction in ("outbound", "return")
            for field in RAIL_EVENT_REQUIRED_TRAIN_FIELDS
        )
        self.assertEqual(
            expected,
            tuple(RAILWAY_MANUAL_REQUIRED_FIELDS),
            "必填清单不是从消费端常量派生的——两张表又会各改各的（D2）",
        )

    def test_optional_list_does_not_overlap_the_required_list(self) -> None:
        self.assertEqual(
            set(),
            set(RAILWAY_MANUAL_OPTIONAL_FIELDS) & set(RAILWAY_MANUAL_REQUIRED_FIELDS),
        )


if __name__ == "__main__":
    unittest.main()
