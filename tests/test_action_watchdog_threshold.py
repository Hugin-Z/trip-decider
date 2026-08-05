"""看门狗：声明的阈值必须就是判定用的阈值,超时不得变成死循环。

**事故**(Claude Desktop 第五次实测,2026-08-04)。宿主给出的归因精确到可以
直接照着查:

> 看门狗写着超过 30 秒但 ~5 秒触发(01:15:02→01:15:07),高德后台 26 秒正常
> 完成(tool.timed 25875ms),主循环反复重发新动作、永远等不到结果。

**归因:比较对象错,外加同一个数字写死了三处。**

    mcp_adapter._SYNCHRONOUS_DRIVE_BUDGET_SECONDS = 5.0
      → execute_trip(drive_budget_seconds=5.0)
        → run_until_blocked(max_wait_seconds=5.0)
          → remaining ≈ 5.0
            → wait(futures, timeout=min(30.0, remaining))   ← 真正等 5 秒
              → _timeout_actions() 报「超过30秒」、timeout_seconds: 30

`remaining` 是**整个循环这一次调用还能花多久**(I13 的调用上界),不是
**这个动作多久算卡住**。两个概念被同一个 `min()` 合并了,于是:调用预算一到,
就把一个跑得好好的动作宣判为超时。

这是上一轮「4 分钟卡死」修复引入的回归:那一轮为了把 MCP 单次调用压进 I13 的
上界,给同步推进传了 5 秒预算——顺带把每个动作的看门狗从 30 秒缩成了 5 秒,
而报文里的 30 是写死的,没跟着变。

**两个数必须分开**:
* 调用预算用完 → 「这次没等到,回头再来」,run 继续跑,不怪任何动作;
* 动作真的超过停滞阈值 → 才是超时。
"""

from __future__ import annotations

from pathlib import Path
import threading
import time
import unittest

from trip_decider.agent_actions import (
    ACTION_STALL_SECONDS,
    run_until_blocked,
    start_action_loop,
)
from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.travel_agent import (
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
)
from trip_decider.trip_application import TripApplicationService

from tests.invariant_support import noop_collector

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


class _SlowCollector:
    """按指定秒数「采集」的假采集器,可查调用次数。"""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, intent: object) -> EvidenceItem:
        with self._lock:
            self.calls += 1
        time.sleep(self.seconds)
        return EvidenceItem(
            evidence_id="railway-slow",
            domain="railway",
            status=EvidenceStatus.MISSING,
            value=None,
            missing_reason="slow-probe",
        )


class _Harness(unittest.TestCase):
    def setUp(self) -> None:
        from tempfile import TemporaryDirectory

        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
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

    def _timeout_events(self) -> list[dict[str, object]]:
        run = self.store.get_run(self.run_id)
        return [
            dict(event.details or {})
            for event in self.store.events_after(run.session_id, 0)
            if event.event_type == "tool.timeout"
        ]


#: 行为用例把阈值缩小到这个值再测。
#:
#: 要验的性质是**关系**——「低于阈值不判超时、高于阈值判超时、报出来的数就是
#: 判定用的数」——它与阈值的绝对大小无关。按真实的 30 秒跑一遍要 86 秒，
#: 把整套测试的耗时翻一倍多；缩到 2 秒测同一个关系只要几秒。
#:
#: 出厂值本身由 `ShippedThresholdCase` 单独钉住，所以缩放不会放跑「有人把 30
#: 改成 5」这类漂移。
_SCALED = 2.0


def _scaled_threshold():
    from unittest import mock

    return mock.patch(
        "trip_decider.agent_actions.ACTION_STALL_SECONDS", _SCALED
    )


class ShippedThresholdCase(unittest.TestCase):
    """出厂阈值本身。行为用例是缩放跑的，这一条守住真实数字。"""

    def test_the_shipped_threshold_is_thirty_seconds(self) -> None:
        self.assertEqual(30.0, ACTION_STALL_SECONDS)

    def test_the_stall_threshold_exceeds_the_mcp_drive_budget(self) -> None:
        """看门狗必须**宽于**单次调用预算，否则预算一到就误判。

        这正是事故的形状：预算 5 秒、看门狗名义 30 秒，但被 min() 合并成 5 秒。
        两者一旦反过来（或相等），误判就会回来。
        """

        from trip_decider.mcp_adapter import (
            _SYNCHRONOUS_DRIVE_BUDGET_SECONDS,
        )

        self.assertGreater(
            ACTION_STALL_SECONDS,
            _SYNCHRONOUS_DRIVE_BUDGET_SECONDS,
            "看门狗阈值不宽于调用预算——预算用完就会被当成动作超时",
        )


class DeclaredThresholdIsTheEnforcedThresholdCase(_Harness):
    """声明的阈值就要是判定用的阈值——这是本轮事故的核心。"""

    def test_a_collect_under_the_threshold_is_not_a_timeout(self) -> None:
        """宿主实测的形状：高德 26 秒正常完成，不该被判超时。

        缩放后等价于「25 秒 < 30 秒阈值」。
        """

        collector = _SlowCollector(_SCALED * 0.5)
        with _scaled_threshold(), _patch_railway(collector):
            run_until_blocked(
                self.run_id,
                store=self.store,
                evidence_broker=self.broker,
                max_wait_seconds=_SCALED + 5.0,
            )

        self.assertEqual(
            [],
            self._timeout_events(),
            "低于阈值的采集被判成了超时",
        )

    def test_a_collect_over_the_threshold_does_time_out(self) -> None:
        """收紧不能收成永不超时——超过阈值必须响。"""

        collector = _SlowCollector(_SCALED + 3.0)
        with _scaled_threshold(), _patch_railway(collector):
            run_until_blocked(
                self.run_id,
                store=self.store,
                evidence_broker=self.broker,
                max_wait_seconds=_SCALED + 8.0,
            )

        self.assertTrue(self._timeout_events(), "超过阈值却没有触发超时")

    def test_the_reported_number_is_the_enforced_number(self) -> None:
        """报文里的秒数必须来自同一个常量，不能是另写的字面量。

        事故里三个 30 各写各的（min() 里一个、消息里一个、details 里一个），
        真正生效的却是第四个数（remaining）。缩放之后立刻看得出来：判定按 2 秒
        走，报文若还印着 30 就是没同源。
        """

        collector = _SlowCollector(_SCALED + 3.0)
        with _scaled_threshold(), _patch_railway(collector):
            run_until_blocked(
                self.run_id,
                store=self.store,
                evidence_broker=self.broker,
                max_wait_seconds=_SCALED + 8.0,
            )

        for details in self._timeout_events():
            self.assertEqual(
                _SCALED,
                details.get("timeout_seconds"),
                "报出来的阈值与实际判定用的不是同一个数",
            )


class BudgetExhaustionIsNotAnActionFailureCase(_Harness):
    """调用预算用完 ≠ 这个动作坏了。

    这是事故的另一半:MCP 给同步推进 5 秒预算,预算一到就把动作宣判超时。
    正确行为是「这次没等到,回头再来」——动作还在飞,run 继续。
    """

    def test_a_short_budget_does_not_blame_the_action(self) -> None:
        collector = _SlowCollector(3.0)
        with _patch_railway(collector):
            snapshot = run_until_blocked(
                self.run_id,
                store=self.store,
                evidence_broker=self.broker,
                max_wait_seconds=0.5,  # 预算远小于采集耗时
            )

        self.assertEqual(
            [],
            self._timeout_events(),
            "调用预算用完被当成了动作超时——那正是 5 秒误判的成因",
        )
        self.assertEqual("NEED_USER_INPUT", snapshot.get("status"))

    def test_the_run_is_not_blocked_by_budget_exhaustion(self) -> None:
        """预算用完不许把 run 打成阻塞——它只是还没跑完。"""

        collector = _SlowCollector(3.0)
        with _patch_railway(collector):
            run_until_blocked(
                self.run_id,
                store=self.store,
                evidence_broker=self.broker,
                max_wait_seconds=0.5,
            )

        run = self.store.get_run(self.run_id)
        self.assertNotEqual(
            "RAILWAY_ACTION_STALLED",
            run.error_code,
            "预算用完把 run 打成了 STALLED",
        )


def _patch_railway(collector: object):
    from unittest import mock

    return mock.patch(
        "trip_decider.agent_actions.collect_railway_evidence",
        collector,
    )


if __name__ == "__main__":
    unittest.main()
