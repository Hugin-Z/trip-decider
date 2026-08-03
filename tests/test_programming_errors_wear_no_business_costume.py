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
  静默死掉，所以走**如实记类型**：错误码自报 `INTERNAL_ERROR_NAMEERROR`，
  并把栈打进日志。

每条用例都配一条正向对照：业务失败必须**保留**原叙述。只证明「编程错误会
响」是不够的——那可能是把所有失败都改成了同一句话。
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trip_decider.agent_actions import (
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

from tests.invariant_support import offline_intent

_BUSINESS_NARRATIVE = ("EVIDENCE_BLOCKED", "EVIDENCE_REQUIRED", "ACTION_STALLED")


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
        # 也没有落下一个 *_EVIDENCE_BLOCKED 错误码去误导归因。
        run = self.store.get_run(run_id)
        self.assertIsNot(
            run.status,
            RunStatus.BLOCKED,
            "NameError 把 run 判成了业务阻塞，归因会被引向采集器",
        )
        self.assertNotIn(
            str(run.error_code or ""),
            _BUSINESS_NARRATIVE,
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
            "RAILWAY_EVIDENCE_BLOCKED",
            run.error_code,
            "业务失败的叙述被改了，正向对照失效",
        )


if __name__ == "__main__":
    unittest.main()
