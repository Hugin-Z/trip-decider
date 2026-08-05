"""进度不许穿错误的衣服。

**同一个毛病犯了三轮**，每次换一件外衣：

| 轮次 | 泄漏出来的内部状态 | 宿主看到的 |
|---|---|---|
| 三 | 候选比较阶段还没建动作循环 | `action loop was not started` 异常 |
| 六 | 证据已入库、只是返回体没写 accepted | `accepted: false` 且无理由 |
| 七 | 同一动作还在飞，本次不重复派发 | `ActionAlreadyInFlight` 异常 |

三次都不是「功能坏了」，是**协调状态以失败的形式对外说话**。宿主没法分辨
「还没好」和「坏了」，于是重试、盲试、止损。

所以立成形状而不是靠记性：

1. **错误码词表与内部状态词表不得相交**——一个词既是进度又是失败，在形状上
   不可能（本文件第一组）；
2. 协调类异常不得逃到宿主面前（第二组，跑真实路径）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest import mock

from trip_decider.agent_actions import (
    ACTION_STALL_SECONDS,
    ActionAlreadyInFlight,
    execute_registered_action,
    start_action_loop,
)
from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.mcp_adapter import TripMCPAdapter, TripMCPError
from trip_decider.travel_agent import (
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
    RUN_ERROR_CODES,
)
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService

from tests.invariant_support import noop_collector

#: 内部协调状态的词表。这些是「进度」，不是「结果」。
#:
#: 动作级取自 `_LoopState.action_status` 的取值域；快照级取自
#: `_snapshot(...)` 与各处 `action_loop["status"]` 实际写出去的词。
_COORDINATION_WORDS = frozenset(
    {
        # 动作级
        "waiting",
        "running",
        "completed",
        "blocked",
        "failed",
        # 快照 / action_loop 级
        "ACTIONS_AVAILABLE",
        "NEED_USER_INPUT",
        "READY",
        "COMPARING",
        "CANDIDATE_COMPARISON_RUNNING",
        "ACTION_IN_FLIGHT",
        "WORKER_LOST",
        "RUNNING",
        "FINALIZING",
        "COMPLETE",
    }
)

_INTENT = {
    "task_mode": "DIRECT_PLAN",
    "origin": "甲地",
    "destination_anchor": "乙地",
    "destination_expression": "确定乙地",
    "earliest_departure_at": "2026-08-12T08:00",
    "latest_return_at": "2026-08-15T22:00",
    "travelers": 2,
    "total_budget_cny": 6000,
    "pace": "relaxed",
    "transport_preferences": ["rail"],
}


class ErrorCodesAndProgressWordsAreDisjointCase(unittest.TestCase):
    """一个词不能既是进度又是失败。"""

    def test_no_run_error_code_is_a_coordination_word(self) -> None:
        overlap = sorted(
            code for code in RUN_ERROR_CODES if code in _COORDINATION_WORDS
        )

        self.assertEqual(
            [],
            overlap,
            f"以下词同时是错误码和内部协调状态：{overlap}。"
            "宿主无从判断它是「还没好」还是「坏了」",
        )

    def test_no_coordination_word_looks_like_a_terminal_failure(self) -> None:
        """协调词不得带失败后缀——那会让读的人当成终局。"""

        offenders = sorted(
            word
            for word in _COORDINATION_WORDS
            if word.endswith("_FAILED") or word.endswith("_ERROR")
        )

        self.assertEqual([], offenders, f"协调词长得像失败：{offenders}")

    def test_the_error_vocabulary_is_still_closed(self) -> None:
        """词表非空且封闭——空表会让上面两条恒真。"""

        self.assertGreater(len(RUN_ERROR_CODES), 5)
        self.assertGreater(len(_COORDINATION_WORDS), 5)


class NoCoordinationExceptionEscapesCase(unittest.TestCase):
    """协调类异常不得到达宿主面前。跑真实路径，不看代码。"""

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.collector_release = threading.Event()
        self.addCleanup(self._temporary.cleanup)
        self.addCleanup(self._await_quiescence)
        self.addCleanup(self.collector_release.set)
        root = Path(self._temporary.name) / "sessions"
        self.store = InMemoryAgentStore(root)
        self.broker = EvidenceBroker(root.parent / "cache")

        class _NoBackground(TripApplicationService):
            @staticmethod
            def _spawn(*, target: object, args: object, name: str) -> None:
                del target, args, name

        self.application = _NoBackground(
            store=self.store,
            evidence_broker=self.broker,
            railway_collector=noop_collector,
            map_collector=noop_collector,
            web_collector=noop_collector,
        )
        self.query = TripQueryService(
            store=self.store, application_service=self.application
        )
        self.adapter = TripMCPAdapter(self.application, self.query)
        self.run_id = self.application.create_trip(dict(_INTENT)).run_id
        self.application.confirm_trip(self.run_id)
        start_action_loop(self.run_id, store=self.store)

    def _await_quiescence(self) -> None:
        from trip_decider.agent_actions import in_flight_actions

        deadline = time.monotonic() + 35.0
        while time.monotonic() < deadline:
            if not in_flight_actions(self.run_id):
                return
            time.sleep(0.05)

    def _slow_collector(self, intent: object) -> EvidenceItem:
        self.collector_release.wait(timeout=30.0)
        return EvidenceItem(
            evidence_id="railway-slow",
            domain="railway",
            status=EvidenceStatus.MISSING,
            value=None,
            missing_reason="slow",
        )

    def test_advancing_while_an_action_is_in_flight_is_not_an_error(
        self,
    ) -> None:
        """第七次实测的形状：补完证据接着 advance，那一域还在飞。"""

        with mock.patch(
            "trip_decider.agent_actions.collect_railway_evidence",
            self._slow_collector,
        ):
            worker = threading.Thread(
                target=lambda: execute_registered_action(
                    self.run_id,
                    "railway",
                    store=self.store,
                    evidence_broker=self.broker,
                ),
                daemon=True,
            )
            worker.start()
            from trip_decider.agent_actions import in_flight_actions

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if "railway" in in_flight_actions(self.run_id):
                    break
                time.sleep(0.02)

            # 宿主此刻推进：不许收到异常
            try:
                view = self.adapter.advance_trip_task(
                    self.run_id, wait_seconds=0
                )
            except ActionAlreadyInFlight as error:  # pragma: no cover
                self.fail(f"协调状态以异常形式泄漏给宿主：{error}")
            except TripMCPError as error:
                if "已在执行中" in str(error):
                    self.fail(f"协调状态穿了错误的衣服：{error}")
                raise

        self.assertIn("checkpoint", view)

    def test_a_direct_retry_while_in_flight_reports_progress(self) -> None:
        """直呼路径同样：回报「在飞」，不是抛错。"""

        with mock.patch(
            "trip_decider.agent_actions.collect_railway_evidence",
            self._slow_collector,
        ):
            worker = threading.Thread(
                target=lambda: execute_registered_action(
                    self.run_id,
                    "railway",
                    store=self.store,
                    evidence_broker=self.broker,
                ),
                daemon=True,
            )
            worker.start()
            from trip_decider.agent_actions import in_flight_actions

            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if "railway" in in_flight_actions(self.run_id):
                    break
                time.sleep(0.02)

            outcome = self.application.execute_trip(
                self.run_id, action_id="railway"
            )

        loop = outcome.action_loop or {}
        self.assertEqual("ACTION_IN_FLIGHT", loop.get("status"))
        self.assertIn("railway", loop.get("in_flight") or [])


if __name__ == "__main__":
    unittest.main()
