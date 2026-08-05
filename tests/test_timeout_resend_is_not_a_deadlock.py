"""超时重发不得变成死循环。

**事故**（第五次实测，2026-08-04）。宿主的归因：

> 主循环反复重发新动作、永远等不到结果。

阈值误判（看门狗 5 秒 vs 高德 26 秒）是导火索，但**病理是重发本身**：
超时 → 重发 → 旧结果无人收 → 新动作再超时。只要阈值 < 真实耗时，这个环就没有
出口。把阈值调大只是把环推远一点，环还在。

三条一起才算修好，缺一条都还会转：

1. **重发幂等**——同一动作已在飞就不再发第二个（`_IN_FLIGHT` 登记）；
2. **迟到结果回收**——超时之后才回来的结果仍然是合法证据，照样入库，
   下一轮直接用，不重查。「超时」是这次没等到，不是结果作废；
3. **熔断**——连续超时到上限就落 `{DOMAIN}_ACTION_FAILED` 说出来，
   不静默转圈（与 WORKER_LOST 同族）。

本文件用宿主的实测参数：阈值 5 秒、采集 26 秒（按 `_SCALE` 等比缩小，
测的是关系不是绝对值，见 `test_action_watchdog_threshold` 里的同款说明）。
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest import mock

from trip_decider.agent_actions import (
    ActionAlreadyInFlight,
    MAX_CONSECUTIVE_TIMEOUTS,
    execute_registered_action,
    get_next_actions,
    in_flight_actions,
    run_until_blocked,
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

from tests.evidence_factory import railway_value
from tests.invariant_support import noop_collector

#: 宿主实测是阈值 5 秒 / 采集 26 秒，比例约 1:5。这里整体缩小 10 倍。
_STALL = 0.5
_COLLECT = 2.6

_INTENT = {
    "task_mode": "DIRECT_PLAN",
    "origin": "甲地",
    "destination_anchor": "乙地",
    "destination_expression": "确定乙地",
    "earliest_departure_at": "2026-08-11T08:00",
    "latest_return_at": "2026-08-14T22:00",
    "travelers": 2,
    "total_budget_cny": 6000,
    "pace": "relaxed",
    "transport_preferences": ["rail"],
}


class _SlowRailway:
    """慢采集：`_COLLECT` 秒后返回一份**合法**证据。

    返回合法证据是关键——迟到的结果必须能被当成证据收下，
    才谈得上「不重查」。
    """

    def __init__(
        self,
        seconds: float = _COLLECT,
        release: threading.Event | None = None,
    ) -> None:
        self.seconds = seconds
        self.calls = 0
        self._lock = threading.Lock()
        #: 拆卸时用来提前叫醒的闸门。没有它，「永远等不到」的用例会让 teardown
        #: 真的等满 30 秒。
        self.release = release if release is not None else threading.Event()

    def __call__(self, intent: object) -> EvidenceItem:
        with self._lock:
            self.calls += 1
        self.release.wait(timeout=self.seconds)
        produced = railway_value()
        return EvidenceItem(
            evidence_id="railway-late",
            domain="railway",
            status=EvidenceStatus.SOURCED,
            value=produced,
            sources=(
                {
                    "provider": "中国铁路12306",
                    "retrieved_at": "2026-08-04T10:00:00+08:00",
                },
            ),
        )


class _Harness(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        # 先登记「等在飞动作退场」，再登记删目录——cleanup 是后进先出，
        # 所以这个顺序保证目录在没有线程还往里写的时候才被删掉。
        #
        # 不这么做就会有一个偶发的 teardown 竞态：慢采集所在的池线程还在
        # `_persist_loop_state`，临时目录已经被删了。全量跑（CPU 更挤）时才
        # 偶尔撞上——正是本轮出现过的那次 flake。
        self.addCleanup(self._temporary.cleanup)
        self.addCleanup(self._await_quiescence)
        #: 所有慢采集共用它：拆卸时先放行，再等在飞退场。
        self.release_collectors = threading.Event()
        self.addCleanup(self.release_collectors.set)
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

    def _slow(self, seconds: float = _COLLECT) -> "_SlowRailway":
        return _SlowRailway(seconds=seconds, release=self.release_collectors)

    def _await_quiescence(self) -> None:
        """等这个 run 的在飞动作全部退场，最多等到慢采集自然结束。"""

        deadline = time.monotonic() + 35.0
        while time.monotonic() < deadline:
            if not in_flight_actions(self.run_id):
                return
            time.sleep(0.05)

    def _stall(self):
        return mock.patch(
            "trip_decider.agent_actions.ACTION_STALL_SECONDS", _STALL
        )

    def _railway(self, collector: object):
        return mock.patch(
            "trip_decider.agent_actions.collect_railway_evidence", collector
        )


class ResendIsIdempotentCase(_Harness):
    """条件一：同一动作已在飞，不再发第二个。"""

    def test_a_second_dispatch_while_in_flight_is_refused(self) -> None:
        collector = self._slow()
        outcome: list[object] = []

        def first() -> None:
            with self._railway(collector):
                try:
                    execute_registered_action(
                        self.run_id,
                        "railway",
                        store=self.store,
                        evidence_broker=self.broker,
                    )
                except Exception as error:  # noqa: BLE001
                    outcome.append(error)

        thread = threading.Thread(target=first, daemon=True)
        thread.start()
        # 等它真的进入在飞状态
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if "railway" in in_flight_actions(self.run_id):
                break
            time.sleep(0.02)

        self.assertIn("railway", in_flight_actions(self.run_id))
        with self.assertRaises(ActionAlreadyInFlight):
            execute_registered_action(
                self.run_id,
                "railway",
                store=self.store,
                evidence_broker=self.broker,
            )
        thread.join(timeout=10.0)
        self.assertEqual(1, collector.calls, "同一动作被派发了两次")

    def test_the_registry_is_released_after_completion(self) -> None:
        """在飞登记必须释放，否则这个动作以后永远发不出去。"""

        collector = self._slow(0.05)
        with self._railway(collector):
            execute_registered_action(
                self.run_id,
                "railway",
                store=self.store,
                evidence_broker=self.broker,
            )

        self.assertEqual(frozenset(), in_flight_actions(self.run_id))

    def test_the_registry_is_released_even_when_the_action_raises(
        self,
    ) -> None:
        def explode(intent: object) -> EvidenceItem:
            raise RuntimeError("采集器炸了")

        with self._railway(explode):
            # 业务异常被转成「该域失败」的证据路径，不外泄——这是既有设计。
            # 这里要验的只有一件事：不论走哪条路，在飞登记都得释放。
            try:
                execute_registered_action(
                    self.run_id,
                    "railway",
                    store=self.store,
                    evidence_broker=self.broker,
                )
            except Exception:  # noqa: BLE001
                pass

        self.assertEqual(
            frozenset(),
            in_flight_actions(self.run_id),
            "动作抛异常后在飞登记没释放——该动作从此再也发不出去",
        )


class LateResultIsReclaimedCase(_Harness):
    """条件二：超时之后回来的结果仍然入库，下一轮直接用。"""

    def test_the_late_evidence_lands_in_the_store(self) -> None:
        collector = self._slow()
        with self._stall(), self._railway(collector):
            run_until_blocked(
                self.run_id,
                store=self.store,
                evidence_broker=self.broker,
                max_wait_seconds=_STALL + 0.3,
            )
            # 超时了；等那份慢结果自己回来
            deadline = time.monotonic() + _COLLECT + 3.0
            while time.monotonic() < deadline:
                evidence = self.application.current_run_evidence(self.run_id)
                if "railway" in evidence:
                    break
                time.sleep(0.05)

        evidence = self.application.current_run_evidence(self.run_id)
        self.assertIn(
            "railway",
            evidence,
            "超时后回来的合法证据被丢掉了——下一轮只能重查，环就是这么转起来的",
        )

    def test_the_reclaimed_evidence_keeps_its_real_retrieved_at(self) -> None:
        """迟到不改事实：retrieved_at 仍是采集器报的那个。"""

        collector = self._slow()
        with self._stall(), self._railway(collector):
            run_until_blocked(
                self.run_id,
                store=self.store,
                evidence_broker=self.broker,
                max_wait_seconds=_STALL + 0.3,
            )
            deadline = time.monotonic() + _COLLECT + 3.0
            while time.monotonic() < deadline:
                if "railway" in self.application.current_run_evidence(
                    self.run_id
                ):
                    break
                time.sleep(0.05)

        stored = self.application.current_run_evidence(self.run_id)["railway"]
        sources = stored.get("sources") or []
        self.assertTrue(sources, "迟到证据丢了来源")

    def test_the_next_round_does_not_requery(self) -> None:
        """结果已在库里，下一轮不该再打一次网络。"""

        collector = self._slow()
        with self._stall(), self._railway(collector):
            run_until_blocked(
                self.run_id,
                store=self.store,
                evidence_broker=self.broker,
                max_wait_seconds=_STALL + 0.3,
            )
            deadline = time.monotonic() + _COLLECT + 3.0
            while time.monotonic() < deadline:
                if "railway" in self.application.current_run_evidence(
                    self.run_id
                ):
                    break
                time.sleep(0.05)
            after_first = collector.calls
            snapshot = get_next_actions(self.run_id, store=self.store)

        pending = {
            str(action.get("action_id"))
            for action in snapshot.get("actions") or []
        }
        self.assertEqual(
            after_first,
            collector.calls,
            "取下一步动作时又打了一次网络",
        )
        self.assertNotIn(
            "railway",
            pending,
            "railway 已经有证据了，却还被列为待办——下一轮会重查",
        )


class CircuitBreakerCase(_Harness):
    """条件三：连续超时到上限就说出来，不无限转圈。"""

    def _time_out_once(self, collector: object) -> None:
        with self._stall(), self._railway(collector):
            try:
                run_until_blocked(
                    self.run_id,
                    store=self.store,
                    evidence_broker=self.broker,
                    max_wait_seconds=_STALL + 0.3,
                )
            except Exception:  # noqa: BLE001
                pass

    def test_the_last_strike_trips_the_breaker(self) -> None:
        """攒够 MAX_CONSECUTIVE_TIMEOUTS 次，这一次就落 FAILED 而不是 STALLED。

        用预置计数驱动而不是真超时三遍：三次真超时需要宿主在每次之间把 run
        从 BLOCKED 拉回 RUNNING（那是状态机的既有规则），那条路径由
        `test_guided_discovery_recovery` 覆盖。这里要验的是**熔断这个判断本身**。
        """

        from trip_decider.agent_actions import (
            _record_timeout_strike,
            _timeout_actions,
        )

        for _ in range(MAX_CONSECUTIVE_TIMEOUTS - 1):
            _record_timeout_strike(self.run_id, "railway")

        with self._stall():
            _timeout_actions(self.run_id, ["railway"], store=self.store)

        self.assertEqual(
            "RAILWAY_ACTION_FAILED",
            self.store.get_run(self.run_id).error_code,
            "攒够次数仍未熔断",
        )

    def test_an_early_strike_does_not_trip_the_breaker(self) -> None:
        """没攒够就不许提前熔断——那会把一次偶发慢查询说成域失败。"""

        from trip_decider.agent_actions import _timeout_actions

        with self._stall():
            _timeout_actions(self.run_id, ["railway"], store=self.store)

        self.assertEqual(
            "RAILWAY_ACTION_STALLED",
            self.store.get_run(self.run_id).error_code,
        )

    def test_a_success_clears_the_strike_count(self) -> None:
        """「连续」才算数——中间成功过一次就得清零。"""

        from trip_decider.agent_actions import (
            _clear_timeout_strikes,
            _record_timeout_strike,
            _timeout_actions,
        )

        for _ in range(MAX_CONSECUTIVE_TIMEOUTS - 1):
            _record_timeout_strike(self.run_id, "railway")
        _clear_timeout_strikes(self.run_id, "railway")  # 成功路径做的事

        with self._stall():
            _timeout_actions(self.run_id, ["railway"], store=self.store)

        self.assertEqual(
            "RAILWAY_ACTION_STALLED",
            self.store.get_run(self.run_id).error_code,
            "成功过一次之后，旧的超时次数仍被累计进熔断",
        )

    def test_in_flight_dedup_is_what_actually_stops_the_spin(self) -> None:
        """记录事实：真正掐断死循环的是在飞去重，不是熔断。

        采集一直没回来时，动作**不会**被重发，所以次数也攒不起来——
        run 停在一个如实的 STALLED 上等宿主，而不是转圈。
        """

        collector = self._slow(30.0)
        with self._stall(), self._railway(collector):
            for _ in range(4):
                try:
                    run_until_blocked(
                        self.run_id,
                        store=self.store,
                        evidence_broker=self.broker,
                        max_wait_seconds=_STALL + 0.2,
                    )
                except Exception:  # noqa: BLE001
                    pass

        self.assertEqual(
            1,
            collector.calls,
            f"采集器被重发了 {collector.calls} 次——死循环的形状还在",
        )

    def test_the_timeout_event_counts_the_strikes(self) -> None:
        """事件里要看得见「第几次」，否则熔断是个黑箱。"""

        collector = self._slow(30.0)
        self._time_out_once(collector)

        run = self.store.get_run(self.run_id)
        events = [
            dict(event.details or {})
            for event in self.store.events_after(run.session_id, 0)
            if event.event_type == "tool.timeout"
        ]
        self.assertTrue(events)
        self.assertEqual(1, events[0].get("consecutive_timeouts"))
        self.assertEqual(
            MAX_CONSECUTIVE_TIMEOUTS,
            events[0].get("max_consecutive_timeouts"),
            "事件没说上限是多少，宿主无从判断还剩几次",
        )


if __name__ == "__main__":
    unittest.main()
