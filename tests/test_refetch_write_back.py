"""重采写回：跨读取生效，且节流真的工作（freshness-policy.md §5.2.2）。

裁决：**读取层不落盘，写回由应用层执行。** 读取层写盘会破两条——模块契约上它
只读；I5 要求两次读取的结构逐字节稳定，而读取产生写入会让第二次读取看到不同
的文件内容。

写回不是新开的通道：它走动作循环一直在用的
``state.evidence[domain]`` + ``_persist_loop_state``。

**为什么这两条守卫缺一不可**：

* 不写回 → 每次读取都重采一遍。上一轮的实现就停在这里，读完即弃；
* 失败不写回 ``refresh_failure.attempted_at`` → 节流没有状态可读，**永远空转**，
  一个挂掉的数据源会被每次页面刷新反复捶打。
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trip_decider.agent_actions import (
    execute_registered_action,
    start_action_loop,
    submit_evidence,
)
from trip_decider.evidence_projection import (
    REFETCH_THROTTLE_SECONDS,
    needs_refetch,
)
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService
from trip_decider.travel_agent import (
    InMemoryAgentStore,
    confirm_intent,
    create_run,
)

from tests.test_planning_input_compiler import (
    READ_AT,
    _intent,
    _map,
    _railway,
    _web,
)
from tests.test_read_time_refetch import STALE_AT, _fresh_railway


class RefetchWriteBackCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.store = InMemoryAgentStore(
            runtime_root=Path(self._temporary.name) / "sessions"
        )
        self.application = TripApplicationService(store=self.store)
        self.calls: list[str] = []

    def _query(self, refetcher) -> TripQueryService:
        return TripQueryService(
            store=self.store,
            application_service=self.application,
            clock=lambda: STALE_AT,
            refetcher=refetcher,
        )

    def _ready_run(self) -> str:
        run = create_run(_intent("乙地"), store=self.store)
        confirm_intent(run.run_id, store=self.store)
        start_action_loop(run.run_id, store=self.store)
        with patch(
            "trip_decider.agent_actions.collect_railway_evidence",
            return_value=_railway(),
        ):
            execute_registered_action(run.run_id, "railway", store=self.store)
        submit_evidence(
            run.run_id,
            {**_web("乙地").to_dict(), "action_id": "web"},
            store=self.store,
        )
        with patch(
            "trip_decider.agent_actions.collect_map_evidence",
            return_value=_map("乙地"),
        ):
            execute_registered_action(run.run_id, "map", store=self.store)
        execute_registered_action(run.run_id, "planner", store=self.store)
        return run.run_id

    def _stored_railway(self, run_id: str):
        return self.application.current_run_evidence(run_id)["railway"]

    def test_a_successful_refetch_survives_to_the_next_read(self) -> None:
        """第一次读触发重采并落盘；第二次读直接拿新值，**不再重采**。

        不落盘的话第二次读会再打一次数据源——那正是上一轮停在的地方。
        """

        run_id = self._ready_run()

        def refetcher(domain, item):
            self.calls.append(domain)
            return _fresh_railway(
                departure="2026-08-04T15:30",
                retrieved_at=STALE_AT.isoformat(),
            )

        query = self._query(refetcher)

        query.trip(run_id)
        self.assertEqual(["railway"], self.calls, "第一次读没有触发重采")

        # 落盘了吗——从 store 重新读一遍，不是看内存
        stored = self._stored_railway(run_id)
        self.assertFalse(
            needs_refetch(stored, "railway", now=STALE_AT),
            "重采结果没有落盘：盘上那份仍然是陈旧的，"
            "下次读取会再打一次数据源",
        )

        query.trip(run_id)
        self.assertEqual(
            ["railway"],
            self.calls,
            "第二次读又重采了一次——写回没有生效，每次读取都在打数据源",
        )

    def test_a_failed_refetch_writes_the_attempt_and_throttles(self) -> None:
        """失败也要写回，否则节流永远空转。

        节流状态是 ``refresh_failure.attempted_at``，只有落盘之后下一次读取
        才读得到它。
        """

        run_id = self._ready_run()

        def refetcher(domain, item):
            self.calls.append(domain)
            raise RuntimeError("rail_http 503")

        query = self._query(refetcher)

        query.trip(run_id)
        self.assertEqual(["railway"], self.calls)

        stored = self._stored_railway(run_id)
        failure = stored["value"].get("refresh_failure")
        self.assertIsInstance(
            failure,
            dict,
            "重采失败没有落下 refresh_failure——节流没有状态可读，"
            "挂掉的数据源会被每次刷新反复捶打",
        )
        self.assertIn("attempted_at", failure)

        # 窗内第二次读：不该再打
        throttled = self._query(refetcher)
        throttled._clock = lambda: STALE_AT + timedelta(seconds=30)
        throttled.trip(run_id)
        self.assertEqual(
            ["railway"],
            self.calls,
            "节流没有生效：失败后窗内又重采了一次",
        )

        # 窗外恢复重试——节流是延期不是永久豁免
        beyond = STALE_AT + timedelta(seconds=REFETCH_THROTTLE_SECONDS + 60)
        later = self._query(refetcher)
        later._clock = lambda: beyond
        later.trip(run_id)
        self.assertEqual(
            ["railway", "railway"],
            self.calls,
            "节流窗过去之后没有恢复重试——那不是节流，是永久放弃",
        )

    def test_the_read_layer_itself_writes_nothing(self) -> None:
        """读取层保持纯读：不注入 refetcher 时，读取不产生任何写入。

        这一条钉住「写入只发生在有重采时」——否则读取层就悄悄变成了写入方，
        I5 的「两次读取结构逐字节稳定」也就没了。
        """

        run_id = self._ready_run()
        before = self._stored_railway(run_id)

        query = self._query(None)
        query.trip(run_id)
        query.trip(run_id)

        self.assertEqual(
            before,
            self._stored_railway(run_id),
            "没有重采却发生了写入——读取层的只读契约被破坏",
        )


if __name__ == "__main__":
    unittest.main()
