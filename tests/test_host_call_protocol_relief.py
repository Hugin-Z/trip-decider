"""调用协议减负：消除宿主实测里反复试错的三处。

事故（Claude Desktop MCP，2026-08-03）：宿主被迫调用时，确认需求 / 提交证据
反复试错十余次。归因出三处，各给最小改动——本轮只消除试错，不重设计协议。

1. **必填参数语义不明** → `submit_trip_evidence` 的 `evidence` 是无 schema 的
   自由 dict，内核要六个键，其中三个宿主根本不该被问：`domain` 恒等于
   `action_id`（问两遍是纯重复）、`evidence_id` 要宿主凭空发明、`status` 有
   value 就是 sourced。现在都派生/自动生成。`sources` **不补**——来源是证据
   之所以成立的理由，代填就是伪造。
2. **多步序列不可发现** → 每个 checkpoint 与每条错误都带 `next_call`，
   说明该调哪个工具、缺哪个字段。宿主试错的一半花在猜下一步上。
3. **同一信息重复提交** → 重复确认幂等。此前第二次 `confirm_trip_intent`
   抛「run is not awaiting confirmation」，而宿主重复确认的典型原因恰恰是
   上一次没看懂返回体。

配套：`docs/contracts/host-call-protocol.md`。
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.mcp_adapter import TripMCPAdapter, TripMCPError
from trip_decider.travel_agent import InMemoryAgentStore
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService

from tests.evidence_factory import railway_value
from tests.invariant_support import noop_collector


class _NoBackgroundApplication(TripApplicationService):
    @staticmethod
    def _spawn(*, target: object, args: object, name: str) -> None:
        del target, args, name


_INTENT = {
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


class HostCallProtocolCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        root = Path(self._temporary.name) / "sessions"
        self.store = InMemoryAgentStore(root)
        self.application = _NoBackgroundApplication(
            store=self.store,
            evidence_broker=EvidenceBroker(root.parent / "cache"),
            railway_collector=noop_collector,
            map_collector=noop_collector,
            web_collector=noop_collector,
        )
        self.query = TripQueryService(
            store=self.store,
            application_service=self.application,
        )
        self.adapter = TripMCPAdapter(self.application, self.query)
        self.run_id = str(
            self.adapter.create_trip_task(dict(_INTENT))["run"]["run_id"]
        )

    def _started(self) -> None:
        self.adapter.confirm_trip_intent(self.run_id)
        self.application.execute_trip(self.run_id)

    # -- 减负 1：宿主只填自己知道的东西 -----------------------------------

    def _minimal_railway(self) -> dict[str, object]:
        produced = railway_value()
        return {
            "action_id": "railway",
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

    def test_evidence_needs_only_action_id_value_and_sources(self) -> None:
        """不填 domain / evidence_id / status 也能提交成功。"""

        self._started()

        response = self.adapter.submit_trip_evidence(
            self.run_id,
            self._minimal_railway(),
        )

        self.assertIsNotNone(response["action_loop"])
        evidence = self.application.current_run_evidence(self.run_id)
        self.assertIn("railway", evidence)

    def test_generated_evidence_id_is_present_and_domain_scoped(self) -> None:
        self._started()
        self.adapter.submit_trip_evidence(self.run_id, self._minimal_railway())

        stored = self.application.current_run_evidence(self.run_id)["railway"]
        evidence_id = str(stored["evidence_id"])

        self.assertTrue(evidence_id, "没有生成 evidence_id")
        self.assertTrue(
            evidence_id.startswith("railway-"),
            f"生成的 id 认不出属于哪个域：{evidence_id}",
        )

    def test_explicit_domain_that_contradicts_action_id_is_rejected(
        self,
    ) -> None:
        """domain 可以不填；填了就不许和 action_id 打架。"""

        self._started()
        submission = self._minimal_railway()
        submission["domain"] = "web"

        with self.assertRaises(TripMCPError) as caught:
            self.adapter.submit_trip_evidence(self.run_id, submission)

        message = str(caught.exception)
        self.assertIn("domain", message)
        self.assertIn("action_id", message)
        self.assertIn("可以不填", message)

    def test_missing_sources_is_refused_and_says_why(self) -> None:
        """来源不代填。报错要说清这是有意为之，否则宿主会以为是格式问题。"""

        self._started()
        submission = self._minimal_railway()
        submission.pop("sources")

        with self.assertRaises(TripMCPError) as caught:
            self.adapter.submit_trip_evidence(self.run_id, submission)

        message = str(caught.exception)
        self.assertIn("sources", message)
        self.assertIn("下一步", message)

    def test_missing_action_id_names_the_valid_values(self) -> None:
        self._started()

        with self.assertRaises(TripMCPError) as caught:
            self.adapter.submit_trip_evidence(self.run_id, {"value": {}})

        message = str(caught.exception)
        for domain in ("railway", "web", "map"):
            self.assertIn(domain, message)

    # -- 减负 2：下一步不用猜 ---------------------------------------------

    def test_every_checkpoint_carries_a_next_call(self) -> None:
        checkpoint = self.adapter.advance_trip_task(
            self.run_id,
            wait_seconds=0,
        )

        self.assertIn("next_call", checkpoint)
        next_call = checkpoint["next_call"]
        self.assertIsInstance(next_call, dict)
        assert isinstance(next_call, dict)
        self.assertTrue(
            next_call.get("options"),
            f"检查点 {checkpoint['checkpoint']} 没给出任何可调入口",
        )
        for option in next_call["options"]:
            self.assertTrue(
                option.get("entrypoint"),
                f"下一步没点名工具：{option}",
            )

    def test_awaiting_confirmation_points_at_confirm(self) -> None:
        checkpoint = self.adapter.advance_trip_task(
            self.run_id,
            wait_seconds=0,
        )

        self.assertEqual(
            "NEED_INTENT_CONFIRMATION",
            checkpoint["checkpoint"],
        )
        self.assertEqual(
            "confirm_trip_intent",
            checkpoint["next_call"]["options"][0]["entrypoint"],
        )

    def test_blocked_run_next_call_passes_through_its_own_recovery(
        self,
    ) -> None:
        """阻塞态用 run 自己算出的 recovery，不用按检查点名给的粗建议（D19）。"""

        self._started()
        self.store.block(
            self.run_id,
            {"action_loop_status": "BLOCKED", "blocked_domains": ["planner"]},
            "PLANNER_ACTION_FAILED",
        )

        checkpoint = self.adapter.advance_trip_task(
            self.run_id,
            wait_seconds=0,
        )
        next_call = checkpoint["next_call"]

        self.assertEqual("PLANNER_ACTION_FAILED", next_call["reason"])
        self.assertIn(
            "submit_trip_evidence",
            {
                str(option.get("entrypoint"))
                for option in next_call["options"]
            },
        )

    def test_errors_carry_a_next_call_in_their_message(self) -> None:
        with self.assertRaises(TripMCPError) as caught:
            self.adapter.submit_trip_evidence(self.run_id, {"value": {}})

        self.assertIn("下一步", str(caught.exception))
        self.assertIsNotNone(caught.exception.next_call)

    # -- 减负 3：重复确认幂等 ---------------------------------------------

    def test_confirming_twice_is_idempotent(self) -> None:
        first = self.adapter.confirm_trip_intent(self.run_id)
        second = self.adapter.confirm_trip_intent(self.run_id)

        self.assertEqual(
            first["run"]["status"],
            second["run"]["status"],
            "第二次确认返回了不同的状态",
        )

    def test_confirming_after_execution_still_does_not_raise(self) -> None:
        """宿主看不懂返回体时会保守地再确认一次，那不该像出错。"""

        self._started()

        response = self.adapter.confirm_trip_intent(self.run_id)

        self.assertEqual(self.run_id, response["run"]["run_id"])

    def test_changing_the_intent_after_confirmation_is_not_swallowed(
        self,
    ) -> None:
        """带 intent 的重复调用是「改条件」，改不了必须说，不能静默吞掉。"""

        self.adapter.confirm_trip_intent(self.run_id)
        changed = {**_INTENT, "travelers": 4}

        with self.assertRaises(TripMCPError):
            self.adapter.confirm_trip_intent(self.run_id, changed)


if __name__ == "__main__":
    unittest.main()
