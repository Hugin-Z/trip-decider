"""编程错误不得穿业务失败的外衣。

背景是一次真实事故：一处 `except Exception` 把 `NameError` 包装成
「真实证据不足」。同一句叙述覆盖了「采集器没拿到数据」和「这段代码有 bug」，
两者在可观测层面无法区分——日志说证据不足，于是归因去查采集器和数据源，
而故障在代码里。浪费了一整轮。

宽捕获 + 专属失败叙述 = 任何 bug 都穿它的外衣。本文件是那条纪律的守卫：
**注入 NameError，断言对外叙述不是业务失败话术。**

两个落点各有各的处置，因为处境不同：

* `agent_actions.execute_registered_action` 是同步调用 → **重抛**，栈留得住；
* `trip_application._run_action_loop_background` 在后台线程 → 重抛只会让线程
  静默死掉，所以走**如实记类型**：错误码自报 `INTERNAL_ERROR`、
  `error_detail` 记 `NameError`，并把栈打进日志。P5 轮 2 把类型名从码里
  挪进 `error_detail`——码要保持有限可查表，类型信息一条不丢（两段式收敛）。

每条用例都配一条正向对照：业务失败必须**保留**原叙述。只证明「编程错误会
响」是不够的——那可能是把所有失败都改成了同一句话。
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from trip_decider.agent_actions import (
    action_loop_started,
    execute_registered_action,
    start_action_loop,
)
from trip_decider.travel_agent import (
    InMemoryAgentStore,
    RunStatus,
    TravelAgentError,
    confirm_intent,
    create_run,
)

from tests.invariant_support import (
    NoBackgroundApplication as _NoBackgroundService,
    noop_collector,
    offline_intent,
)

#: 业务失败话术的**片段**，按子串匹配。
#:
#: 此前这里是三个整词，断言写成 ``assertNotIn(run.error_code, _BUSINESS_NARRATIVE)``
#: ——那是**恒真**的：实际错误码是 ``RAILWAY_EVIDENCE_BLOCKED`` 之类的带域全名，
#: 与 ``"EVIDENCE_BLOCKED"`` 从不相等，所以这条守卫对它点名要防的那个值也不会响
#: （D6：没响过的绿是没有信息的）。改成子串匹配，并在 P5 轮 2 的词表收敛后同步
#: 片段：``*_EVIDENCE_BLOCKED`` → ``*_ACTION_FAILED``，
#: ``WEB_EVIDENCE_REQUIRED`` → ``CODEX_ACTION_REQUIRED``。
_BUSINESS_NARRATIVE = (
    "ACTION_FAILED",
    "ACTION_REQUIRED",
    "INPUT_REQUIRED",
    "ACTION_STALLED",
)


def _wears_business_costume(code: str) -> list[str]:
    return [item for item in _BUSINESS_NARRATIVE if item in code]


def _started_run(store: InMemoryAgentStore) -> str:
    run = create_run(offline_intent(), store=store)
    confirm_intent(run.run_id, store=store)
    start_action_loop(run.run_id, store=store)
    return run.run_id


class ProgrammingErrorsCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.store = InMemoryAgentStore(
            runtime_root=Path(self._temporary.name) / "sessions"
        )

    def test_name_error_in_a_collector_is_reraised(self) -> None:
        """负向验证：注入 NameError，同步路径必须原样抛出。"""

        run_id = _started_run(self.store)

        def exploding_collector(*_args, **_kwargs):
            raise NameError("undefined_helper")

        with patch(
            "trip_decider.agent_actions.collect_railway_evidence",
            exploding_collector,
        ):
            with self.assertRaises(NameError):
                execute_registered_action(
                    run_id,
                    "railway",
                    store=self.store,
                )

        # 关键在「对外叙述里没有业务失败」：run 没有被判成证据受阻，
        # 也没有落下一个 *_ACTION_FAILED 错误码去误导归因。
        run = self.store.get_run(run_id)
        self.assertIsNot(
            run.status,
            RunStatus.BLOCKED,
            "NameError 把 run 判成了业务阻塞，归因会被引向采集器",
        )
        self.assertEqual(
            [],
            _wears_business_costume(str(run.error_code or "")),
            f"NameError 被翻译成了业务失败话术：{run.error_code!r}",
        )

    def test_business_failure_keeps_its_narrative(self) -> None:
        """正向对照：业务失败仍走原路，叙述不变。

        没有这一条，上面那条可能是「把所有失败都改成重抛」换来的绿。
        """

        run_id = _started_run(self.store)

        def failing_collector(*_args, **_kwargs):
            raise TravelAgentError("rail_http")

        with patch(
            "trip_decider.agent_actions.collect_railway_evidence",
            failing_collector,
        ):
            execute_registered_action(run_id, "railway", store=self.store)

        run = self.store.get_run(run_id)
        self.assertIs(
            run.status,
            RunStatus.BLOCKED,
            "业务失败不再阻塞 run——原叙述被改坏了",
        )
        self.assertEqual(
            "RAILWAY_ACTION_FAILED",
            run.error_code,
            "业务失败的叙述被改了，正向对照失效",
        )

    def test_the_same_action_cannot_be_claimed_by_two_threads(self) -> None:
        """第二个调用应收到稳定的状态错误，而不是争抢同一个临时文件。"""

        run_id = _started_run(self.store)
        collector_entered = threading.Event()
        release_collector = threading.Event()
        self.addCleanup(release_collector.set)
        first_errors: list[BaseException] = []

        def gated_collector(intent):
            collector_entered.set()
            release_collector.wait(timeout=5.0)
            return noop_collector(intent)

        def execute_first() -> None:
            try:
                execute_registered_action(run_id, "railway", store=self.store)
            except BaseException as error:  # 测试线程必须把异常交回主线程
                first_errors.append(error)

        with patch(
            "trip_decider.agent_actions.collect_railway_evidence",
            gated_collector,
        ):
            thread = threading.Thread(target=execute_first, daemon=True)
            thread.start()
            self.assertTrue(collector_entered.wait(timeout=5.0))
            with self.assertRaisesRegex(TravelAgentError, "not waiting"):
                execute_registered_action(run_id, "railway", store=self.store)
            release_collector.set()
            thread.join(timeout=5.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual([], first_errors)
        run = self.store.get_run(run_id)
        started = [
            event
            for event in self.store.events_after(run.session_id, 0)
            if event.event_type == "tool.started"
            and event.details.get("tool") == "railway"
        ]
        self.assertEqual(1, len(started))


class BackgroundThreadNarrativeCase(unittest.TestCase):
    """后台线程那个落点——本文件此前**只测了同步落点**。

    模块 docstring 从一开始就写着「两个落点各有各的处置」，但用例全部打在
    ``execute_registered_action`` 上，``_run_action_loop_background`` 一条都没有。
    P5 轮 2 改那半边（型名从码里挪进 ``error_detail``）时做 D6 负向验证才发现：
    往后台分支注入故障，本文件全绿——它对自己声称覆盖的一半是瞎的。

    这正是 D9 说的那种零覆盖路径：套件绿了很久，靠逐条查验才发现它没被执行过。
    """

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.store = InMemoryAgentStore(
            runtime_root=Path(self._temporary.name) / "sessions"
        )
        self.service = _NoBackgroundService(store=self.store)

    def _running_run(self) -> str:
        created = self.service.create_trip(offline_intent())
        self.service.confirm_trip(created.run_id)
        # 必须真的进 RUNNING：那个 except 分支只在 RUNNING 时才落 block，
        # 停在 CONFIRMED 上驱动后台会得到一个 error_code 恒为 None 的假绿。
        self.service.execute_trip(created.run_id)
        self.assertIs(
            self.store.get_run(created.run_id).status,
            RunStatus.RUNNING,
        )
        return created.run_id

    def _drive_background(self, error: BaseException) -> None:
        def exploding(*_args, **_kwargs):
            raise error

        with patch(
            "trip_decider.trip_application.run_until_blocked",
            exploding,
        ):
            self.service._run_action_loop_background(self._run_id)

    def test_programming_error_reports_internal_error_with_the_type(
        self,
    ) -> None:
        """D12 的「如实记类型」：码说这是我们的 bug，类型名进 error_detail。"""

        self._run_id = self._running_run()
        self._drive_background(NameError("undefined_helper"))

        run = self.store.get_run(self._run_id)
        self.assertEqual("INTERNAL_ERROR", run.error_code)
        self.assertEqual("NameError", run.error_detail)
        self.assertEqual(
            [],
            _wears_business_costume(str(run.error_code or "")),
            f"NameError 被翻译成了业务失败话术：{run.error_code!r}",
        )

    def test_business_failure_keeps_the_business_code(self) -> None:
        """正向对照：业务失败不许被一起吞进 INTERNAL_ERROR。"""

        self._run_id = self._running_run()
        self._drive_background(TravelAgentError("loop_http"))

        run = self.store.get_run(self._run_id)
        self.assertEqual("ACTION_LOOP_FAILED", run.error_code)
        self.assertEqual("TravelAgentError", run.error_detail)

    def test_direct_plan_recovers_if_start_crashed_before_loop_persisted(self) -> None:
        intent = offline_intent()
        intent["task_mode"] = "DIRECT_PLAN"
        created = self.service.create_trip(intent)
        self.service.confirm_trip(created.run_id)
        # 模拟 start_action_loop 在 store.start 后、首次落盘前进程退出。
        self.store.start(created.run_id)

        outcome = self.service.execute_trip(created.run_id)

        self.assertTrue(outcome.accepted)
        self.assertTrue(action_loop_started(created.run_id, store=self.store))
        self.assertEqual("ACTIONS_AVAILABLE", outcome.action_loop["status"])


if __name__ == "__main__":
    unittest.main()
