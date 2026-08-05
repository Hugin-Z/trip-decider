"""降级链在动作执行的**唯一入口**上，四条派发路径自动继承。

**上一轮核对表的欠账**（第七次实测归因）：超时→重试→熔断→ACTION_FAILED
这条链原本只活在 `run_until_blocked` 内部，于是

| 派发路径 | 看门狗 | 熔断 |
|---|---|---|
| `execute_trip(action_id=None)` → run_until_blocked | 有 | 有 |
| `execute_trip(action_id=X)` → 直呼 | **无** | **无** |
| `retry_action(X)` → 直呼 | **无** | **无** |
| `_run_action_loop_background` → run_until_blocked | 有 | 有 |

两条直呼路径完全裸奔——慢采集在那里可以跑到天荒地老，熔断一次也数不到。
这正是「重试两次无效」的结构性成因：宿主按 recovery 去 retry，而 retry 那条路
根本没有降级链。

**修法不是给两条路各包一层**（那就是三份实现，早晚有人只改一份），而是把链
下沉到 `execute_registered_action`——所有派发最终都从这里过。

本文件按核对表逐条复核，并做 D6：直呼路径注入慢采集，熔断必须接住。
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest import mock

from trip_decider.agent_actions import (
    ACTION_STALL_SECONDS,
    MAX_CONSECUTIVE_TIMEOUTS,
    _record_timeout_strike,
    execute_registered_action,
    start_action_loop,
)
from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.travel_agent import (
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
    RunStatus,
)
from trip_decider.trip_application import TripApplicationService

from tests.invariant_support import noop_collector

#: 缩放阈值。测的是「链接没接上」，与绝对秒数无关。
_STALL = 0.4

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


class _NeverReturns:
    """永远等不到的采集器，可提前放行以便拆卸。"""

    def __init__(self) -> None:
        self.calls = 0
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, intent: object) -> EvidenceItem:
        with self._lock:
            self.calls += 1
        self.release.wait(timeout=30.0)
        return EvidenceItem(
            evidence_id="railway-slow",
            domain="railway",
            status=EvidenceStatus.MISSING,
            value=None,
            missing_reason="slow",
        )


class _Harness(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.collector = _NeverReturns()
        # cleanup 是后进先出，所以注册顺序 = 执行顺序的倒序：
        # 先放行慢采集 → 等在飞动作真正退场 → 最后才删目录。
        # 不这么排就会撞上 teardown 竞态：worker 还在 _persist_loop_state，
        # 临时目录已经没了。
        self.addCleanup(self._temporary.cleanup)
        self.addCleanup(self._await_quiescence)
        self.addCleanup(self.collector.release.set)
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

    def _patched(self):
        return (
            mock.patch(
                "trip_decider.agent_actions.ACTION_STALL_SECONDS", _STALL
            ),
            mock.patch(
                "trip_decider.agent_actions.collect_railway_evidence",
                self.collector,
            ),
        )

    def _timeout_events(self) -> list[dict[str, object]]:
        run = self.store.get_run(self.run_id)
        return [
            dict(event.details or {})
            for event in self.store.events_after(run.session_id, 0)
            if event.event_type == "tool.timeout"
        ]


class DirectDispatchInheritsTheChainCase(_Harness):
    """D6：直呼路径注入慢采集，看门狗与熔断必须接住。"""

    def test_a_direct_call_times_out_instead_of_hanging(self) -> None:
        """`execute_registered_action` 直呼——此前这条路没有任何上界。"""

        stall, railway = self._patched()
        started = time.monotonic()
        with stall, railway:
            execute_registered_action(
                self.run_id,
                "railway",
                store=self.store,
                evidence_broker=self.broker,
            )
        elapsed = time.monotonic() - started

        self.assertLess(
            elapsed,
            _STALL + 3.0,
            f"直呼路径没有上界，等了 {elapsed:.1f}s",
        )
        self.assertTrue(
            self._timeout_events(),
            "直呼路径超时了却没有 tool.timeout 事件——看门狗没接住",
        )

    def test_the_direct_path_feeds_the_breaker(self) -> None:
        """超时要计入熔断计数，否则连续超时永远攒不够。"""

        stall, railway = self._patched()
        with stall, railway:
            execute_registered_action(
                self.run_id,
                "railway",
                store=self.store,
                evidence_broker=self.broker,
            )

        events = self._timeout_events()
        self.assertTrue(events)
        self.assertEqual(1, events[0].get("consecutive_timeouts"))

    def test_the_breaker_trips_on_the_direct_path(self) -> None:
        """攒够次数，直呼路径也要落 {DOMAIN}_ACTION_FAILED。"""

        for _ in range(MAX_CONSECUTIVE_TIMEOUTS - 1):
            _record_timeout_strike(self.run_id, "railway")

        stall, railway = self._patched()
        with stall, railway:
            execute_registered_action(
                self.run_id,
                "railway",
                store=self.store,
                evidence_broker=self.broker,
            )

        self.assertEqual(
            "RAILWAY_ACTION_FAILED",
            self.store.get_run(self.run_id).error_code,
            "直呼路径攒够超时次数却没熔断",
        )

    def test_retry_action_inherits_the_same_chain(self) -> None:
        """`retry_action` 是宿主按 recovery 走的那条路，必须同样有上界。"""

        self.store.block(
            self.run_id,
            {"action_loop_status": "BLOCKED", "blocked_domains": ["railway"]},
            "RAILWAY_ACTION_STALLED",
        )
        stall, railway = self._patched()
        started = time.monotonic()
        with stall, railway:
            try:
                self.application.retry_action(self.run_id, "railway")
            except Exception:  # noqa: BLE001
                pass
        elapsed = time.monotonic() - started

        self.assertLess(
            elapsed,
            _STALL + 5.0,
            f"retry_action 没有上界，等了 {elapsed:.1f}s——"
            "宿主按 recovery 重试，结果重试本身挂住了",
        )

    def test_the_slow_collector_is_not_cancelled(self) -> None:
        """超时不取消在飞的采集：它的结果仍是合法证据（第五轮的裁决）。"""

        stall, railway = self._patched()
        with stall, railway:
            execute_registered_action(
                self.run_id,
                "railway",
                store=self.store,
                evidence_broker=self.broker,
            )
            self.assertEqual(
                1,
                self.collector.calls,
                "采集器没被调用，或被重复调用",
            )


class ShippedThresholdIsInheritedCase(unittest.TestCase):
    """出厂阈值只有一处，入口与报文共用它。"""

    def test_the_entry_point_uses_the_single_threshold(self) -> None:
        import inspect

        from trip_decider import agent_actions

        source = inspect.getsource(agent_actions.execute_registered_action)
        self.assertIn(
            "ACTION_STALL_SECONDS",
            source,
            "入口没有引用统一阈值常量——又要出现第二个数字",
        )


if __name__ == "__main__":
    unittest.main()
