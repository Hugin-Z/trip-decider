"""同一份证据、同一个 now，两个读取面不得给出不同结论。

**这是「四入口收敛、不分叉」裁决（2026-08-03）的可执行形式。**

背景：`plan_readiness`（读取层）与 `get_next_actions`（动作循环）都要回答
「这份计划当前够不够格呈现」，此前**各 compile 一次、各判一次**
`PARTIAL_READY/PLAN_READY`。两份并列的实现读同一份 context、判同一件事，却没有
任何东西保证它们给同一个答案。

为什么这算严重：它与「结论和数据不同步」同族，只是错位换了位置——不是结论比
数据旧，而是**同一时刻的两次读取彼此不一致**。用户在计划页看到「可呈现」、在
动作页看到「还缺东西」，两个都是系统说的。I5 / R2 防的是前者，这条防后者。

收敛后两边都走 `planning_input_compiler.plan_verdict_from_result`。本文件钉住
这个收敛：**不是断言两个函数长得像，是断言它们的输出相等**——实现可以变，
相等不许变。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import trip_decider.agent_actions as agent_actions
from trip_decider.agent_actions import (
    execute_registered_action,
    set_read_clock,
    reset_read_clock,
    start_action_loop,
    submit_evidence,
)
from trip_decider.planning_input_compiler import (
    INSTALLABLE_STATES,
    plan_verdict_from_result,
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


class ReadEntrancesAgreeCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.store = InMemoryAgentStore(
            runtime_root=Path(self._temporary.name) / "sessions"
        )
        self.application = TripApplicationService(store=self.store)
        self.query = TripQueryService(
            store=self.store,
            application_service=self.application,
            clock=lambda: READ_AT,
        )
        previous = set_read_clock(lambda: READ_AT)
        self.addCleanup(lambda: set_read_clock(previous))
        self.addCleanup(reset_read_clock)

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

    def test_plan_readiness_and_next_actions_agree_on_planning_state(
        self,
    ) -> None:
        run_id = self._ready_run()

        readiness = self.query.plan_readiness(run_id, now=READ_AT)
        loop_result = self.application.next_actions(run_id).get("result")
        loop_state = agent_actions.recomputed_planning_state(
            loop_result,
            self.application.current_run_evidence(run_id),
        )

        self.assertIsNotNone(
            readiness["planning_state"],
            "前置条件不满足：plan_readiness 没算出 planning_state，"
            "本用例会退化成 None == None 的假绿",
        )
        self.assertEqual(
            readiness["planning_state"],
            loop_state,
            "同一 run、同一 now，两个读取面的 planning_state 分叉了——"
            "四入口收敛裁决被破坏",
        )
        self.assertEqual(
            readiness["usable_now"],
            loop_state in INSTALLABLE_STATES,
            "「当前可用」的判据在两边不一致",
        )

    def test_they_still_agree_after_the_tolerance_window(self) -> None:
        """跨过容忍窗再比一次。

        只在窗内比不够：两边**都**用同一个 now 去 compile 才叫收敛，而窗内窗外
        恰恰是 planning_state 会变的地方（P4-b2 翻面证过：同一份 PlanVersion
        新鲜时 PLAN_READY，过窗后 PARTIAL_READY 带 conditional）。若某一边把
        now 钉死了，只有跨窗这一比才看得出来。
        """

        run_id = self._ready_run()
        stale_at = READ_AT + timedelta(hours=7)
        previous = set_read_clock(lambda: stale_at)
        self.addCleanup(lambda: set_read_clock(previous))

        readiness = self.query.plan_readiness(run_id, now=stale_at)
        loop_result = self.application.next_actions(run_id).get("result")
        loop_state = agent_actions.recomputed_planning_state(
            loop_result,
            self.application.current_run_evidence(run_id),
        )

        self.assertEqual(readiness["planning_state"], loop_state)

    def test_the_window_actually_changes_the_verdict(self) -> None:
        """前置条件：窗内窗外确实给出不同结论。

        没有这一条，上面那条跨窗用例可能只是把同一个结论比了两遍——那样它
        证明不了任何关于 now 的事（D6：没响过的绿是没有信息的）。
        """

        run_id = self._ready_run()
        result = self.application.next_actions(run_id).get("result")
        evidence = self.application.current_run_evidence(run_id)

        fresh = plan_verdict_from_result(
            result,
            now=READ_AT,
            evidence=evidence,
        )
        stale = plan_verdict_from_result(
            result,
            now=READ_AT + timedelta(hours=7),
            evidence=evidence,
        )
        self.assertNotEqual(
            (fresh.planning_state, len(fresh.blockers)),
            (stale.planning_state, len(stale.blockers)),
            "跨越容忍窗后判定没有任何变化——夹具的时间关系没钉住，"
            "跨窗用例因此失去意义（D11）",
        )


class SameEvidenceSourceCase(unittest.TestCase):
    """守卫 4：两个读取面读的是**同一份**证据（D19 根治的可执行断言）。

    上面几条断言的是「两面结论相等」。那还不够——两份内容恰好相同的副本也能
    让结论相等，而 A/B 副本此前正是靠「都从同一个 state.evidence 写出」保持相同，
    那是运气不是保证（读时重采的写回就是第一条只更新其中一份的路径）。

    A 收敛之后，`run.result["context"]` 不再是证据来源，两面都从容器 B 取。
    本用例改动**只有 B 会看到**的那一份，然后断言两面**一起**跟着变——
    副本若还在，改 B 不影响读 A 的那一面，用例即响。
    """

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.store = InMemoryAgentStore(
            runtime_root=Path(self._temporary.name) / "sessions"
        )
        self.application = TripApplicationService(store=self.store)
        self.query = TripQueryService(
            store=self.store,
            application_service=self.application,
            clock=lambda: READ_AT,
        )
        previous = set_read_clock(lambda: READ_AT)
        self.addCleanup(lambda: set_read_clock(previous))
        self.addCleanup(reset_read_clock)

    def test_mutating_container_b_moves_both_entrances(self) -> None:
        run_id = ReadEntrancesAgreeCase._ready_run(self)

        before_readiness = self.query.plan_readiness(run_id, now=READ_AT)
        before_loop = agent_actions.recomputed_planning_state(
            self.application.next_actions(run_id).get("result"),
            self.application.current_run_evidence(run_id),
        )
        self.assertEqual(before_readiness["planning_state"], before_loop)

        # 只动 B：把铁路证据换成 missing。A（若还存在）不受影响。
        broken = {
            "evidence_id": "railway-live-query",
            "domain": "railway",
            "status": "missing",
            "value": None,
            "sources": [],
            "missing_reason": "rail_http",
        }
        self.application.record_refetched_evidence(
            run_id,
            [("railway", broken)],
        )

        after_readiness = self.query.plan_readiness(run_id, now=READ_AT)
        after_loop_result = self.application.next_actions(run_id).get("result")
        after_loop = agent_actions.recomputed_planning_state(
            after_loop_result,
            self.application.current_run_evidence(run_id),
        )

        self.assertNotEqual(
            before_readiness["planning_state"],
            after_readiness["planning_state"],
            "改了容器 B 而 plan_readiness 的结论没变——它还在读别的地方",
        )
        self.assertEqual(
            after_readiness["planning_state"],
            after_loop,
            "改了容器 B 之后两个读取面分叉了——副本仍在",
        )


if __name__ == "__main__":
    unittest.main()
