"""宿主实测 P0 之二：GUIDED_DISCOVERY 比较失败后的死锁。

事故（Claude Desktop MCP，2026-08-03）：目的地表达含糊但意图明确（方向 + 日期
预算齐全），分类落 `GUIDED_DISCOVERY`，比较代理抛 `TravelAgentError`，run 变成
BLOCKED 且**三个入口全堵**：

* `execute_trip` → 「run must be confirmed before execution」
* `select_candidate` → 「candidate comparison must complete before selection」
* `confirm_trip` → 「run is not awaiting confirmation」

宿主的绕法是在 `destination_expression` 里写「已承诺无需比较」命中
`_DIRECT_DESTINATION_MARKERS`，改走 `DIRECT_PLAN`。

**归因不是分类错误。** 用户说的是方向不是承诺，`GUIDED_DISCOVERY` 是对的；
错的是比较代理拿不到候选时把 run 留成没有出口的终局。分类照旧（第一条用例
把这一点钉住，防止有人用「改分类」来糊这个洞）。

**关闭标准**：同款输入不再需要那句咒语。第二条用例逐字使用宿主夹具里的意图，
全程不碰 `destination_expression`。

本文件不依赖网络：比较构造器与三个采集器都由测试注入。
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.travel_agent import (
    InMemoryAgentStore,
    RunStatus,
    TaskMode,
    TravelAgentError,
)
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService

from tests.invariant_support import noop_collector

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "host_mcp_smoke"
    / "guided_discovery_intent.json"
)


def host_fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class _NoBackgroundApplication(TripApplicationService):
    @staticmethod
    def _spawn(*, target: object, args: object, name: str) -> None:
        del target, args, name


class _ImmediateBackgroundApplication(TripApplicationService):
    @staticmethod
    def _spawn(*, target: object, args: object, name: str) -> None:
        del name
        target(*args)


def _failing_comparison(intent: object, **arguments: object) -> dict[str, object]:
    """真实失败点：活体候选检索解析不出区域（dynamic_discovery.py:71）。"""

    del intent, arguments
    raise TravelAgentError("guided destination region could not be resolved live")


class GuidedDiscoveryRecoveryCase(unittest.TestCase):
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
            comparison_builder=_failing_comparison,
        )
        self.query = TripQueryService(
            store=self.store,
            application_service=self.application,
        )
        self.intent = dict(host_fixture()["intent"])

    def _drive_to_failed_comparison(self) -> str:
        run = self.application.create_trip(self.intent)
        self.application.confirm_trip(run.run_id)
        self.application.execute_trip(run.run_id)
        self.application._candidate_comparison_background(
            run.run_id,
            TaskMode.GUIDED_DISCOVERY,
        )
        return run.run_id

    # -- 1. 分类照旧：这个洞不许用「改分类」来糊 ---------------------------

    def test_host_intent_still_classifies_as_guided_discovery(self) -> None:
        run = self.application.create_trip(self.intent)
        intent = self.store.get_run(run.run_id).intent
        expected = host_fixture()["expected_classification"]

        self.assertEqual(expected["task_mode"], intent.task_mode.value)
        self.assertEqual(
            expected["classification_basis"],
            intent.classification_basis,
            "分类依据变了——说方向不等于说承诺，改分类是把问题挪走不是修好",
        )

    # -- 2. 关闭标准：同款输入不再需要咒语 --------------------------------

    def test_host_input_reaches_a_direct_plan_without_the_spell(self) -> None:
        """全程不碰 destination_expression，仍能走到详细规划。"""

        run_id = self._drive_to_failed_comparison()
        spell = host_fixture()[
            "host_workaround_that_must_stop_being_necessary"
        ]["destination_expression"]
        self.assertNotIn(
            spell,
            str(self.store.get_run(run_id).intent.destination_expression),
            "前置条件不满足：意图里已经带着咒语了",
        )

        candidates = self.query.candidates(run_id)
        fallback = [
            option
            for option in candidates["candidates"]
            if option.get("comparison_status") == "not_compared"
        ]
        self.assertTrue(
            fallback,
            "比较失败后没有留下任何可推进的候选——宿主只能靠改话术绕状态机",
        )

        self.application.select_candidate(
            run_id,
            str(fallback[0]["destination_id"]),
        )

        current = self.store.get_run(run_id)
        self.assertIs(
            RunStatus.RUNNING,
            current.status,
            "选了退路之后 run 没有恢复运行",
        )
        self.assertIs(
            TaskMode.DIRECT_PLAN,
            current.intent.task_mode,
            "退路没有转成 DIRECT_PLAN，详细规划跑不起来",
        )

    # -- 3. 出路必须写在 run 上，不靠宿主猜 -------------------------------

    def test_blocked_run_declares_its_exits(self) -> None:
        run_id = self._drive_to_failed_comparison()
        result = self.store.get_run(run_id).result

        self.assertIsInstance(result, dict)
        assert isinstance(result, dict)
        recovery = result.get("recovery")
        self.assertTrue(
            recovery,
            "比较失败的 run 没有 recovery 字段：宿主只看到 "
            "GUIDED_COMPARISON_UNAVAILABLE，无从知道下一步能做什么",
        )
        self.assertIsInstance(recovery, list)
        assert isinstance(recovery, list)
        kinds = {
            str(item.get("kind"))
            for item in recovery
            if isinstance(item, dict)
        }
        self.assertIn(
            "retry_comparison",
            kinds,
            f"没有声明「重试比较」这条出路：{kinds}",
        )
        self.assertIn(
            "plan_region_anchor_directly",
            kinds,
            f"没有声明「直接规划区域锚点」这条出路：{kinds}",
        )
        for item in recovery:
            self.assertTrue(
                isinstance(item, dict) and item.get("entrypoint"),
                f"出路没有指明调用入口，宿主还是得猜：{item}",
            )

    # -- 4. 重试这条出路真的走得通 ----------------------------------------

    def test_a_blocked_comparison_can_be_retried(self) -> None:
        run_id = self._drive_to_failed_comparison()
        self.assertIs(RunStatus.BLOCKED, self.store.get_run(run_id).status)

        # 换一个能成功的比较构造器，重试必须真的重跑而不是报「未确认」。
        self.application.comparison_builder = _succeeding_comparison
        self.application.execute_trip(run_id)
        self.application._candidate_comparison_background(
            run_id,
            TaskMode.GUIDED_DISCOVERY,
        )

        candidates = self.query.candidates(run_id)
        compared = [
            option
            for option in candidates["candidates"]
            if option.get("comparison_status") != "not_compared"
        ]
        self.assertTrue(compared, "重试之后仍然没有真正比较出来的候选")

    # -- 5. 声明的出路必须**在宿主面上**真的调得通 -------------------------

    def test_declared_exits_are_callable_through_the_mcp_surface(self) -> None:
        """`recovery` 里点名的入口，必须是宿主真能调的那个入口。

        差点漏掉的一处：应用层放行了重试，但 `advance_trip_task` 把 BLOCKED 当
        终局检查点，直接回快照而不调 `execute_trip`。那样 `retry_comparison`
        就是一条声明了却调不通的出路——比不写更坏，宿主会按它试然后再次卡住
        （D14：存在性不冒充可用性）。
        """

        from trip_decider.mcp_adapter import TripMCPAdapter

        run_id = self._drive_to_failed_comparison()
        adapter = TripMCPAdapter(self.application, self.query)
        result = self.store.get_run(run_id).result
        assert isinstance(result, dict)
        by_kind = {
            str(item["kind"]): item
            for item in result["recovery"]
            if isinstance(item, dict)
        }

        # retry_comparison → advance_trip_task
        self.assertEqual(
            "advance_trip_task",
            by_kind["retry_comparison"]["entrypoint"],
        )
        self.application.comparison_builder = _succeeding_comparison
        adapter.advance_trip_task(run_id, wait_seconds=0)
        self.application._candidate_comparison_background(
            run_id,
            TaskMode.GUIDED_DISCOVERY,
        )
        self.assertTrue(
            self.query.candidates(run_id)["comparison_completed"],
            "按 recovery 点名的入口调用之后，比较仍未完成——出路是假的",
        )

    def test_declared_direct_plan_exit_is_callable_through_mcp(self) -> None:
        from trip_decider.mcp_adapter import TripMCPAdapter

        run_id = self._drive_to_failed_comparison()
        adapter = TripMCPAdapter(self.application, self.query)
        result = self.store.get_run(run_id).result
        assert isinstance(result, dict)
        exit_route = next(
            item
            for item in result["recovery"]
            if isinstance(item, dict)
            and item.get("kind") == "plan_region_anchor_directly"
        )
        self.assertEqual("select_trip_candidate", exit_route["entrypoint"])

        adapter.select_trip_candidate(
            run_id,
            str(exit_route["arguments"]["candidate_id"]),
        )

        self.assertIs(
            TaskMode.DIRECT_PLAN,
            self.store.get_run(run_id).intent.task_mode,
        )

    # -- 6. 失败的比较不许自称完成 ----------------------------------------

    def test_candidates_does_not_claim_a_failed_comparison_completed(
        self,
    ) -> None:
        run_id = self._drive_to_failed_comparison()
        candidates = self.query.candidates(run_id)

        self.assertFalse(
            candidates["comparison_completed"],
            "比较抛异常之后 candidates() 仍报 comparison_completed=True——"
            "这是一句假话，宿主据此以为候选列表是空的比较结果",
        )

    # -- 7. 后台线程不能静默消失并留下永久 RUNNING ----------------------

    def test_programming_error_blocks_with_internal_error(self) -> None:
        def broken_comparison(*_args: object, **_kwargs: object):
            raise NameError("undefined_candidate_helper")

        self.application.comparison_builder = broken_comparison
        run = self.application.create_trip(self.intent)
        self.application.confirm_trip(run.run_id)
        self.application.execute_trip(run.run_id)
        self.application._candidate_comparison_background(
            run.run_id,
            TaskMode.GUIDED_DISCOVERY,
        )

        current = self.store.get_run(run.run_id)
        self.assertIs(RunStatus.BLOCKED, current.status)
        self.assertEqual("INTERNAL_ERROR", current.error_code)
        self.assertEqual("NameError", current.error_detail)

    def test_a_restarted_service_resumes_a_lost_comparison_worker(self) -> None:
        """盘上 RUNNING、本进程却没有 worker 时，下一次轮询要补起它。"""

        run = self.application.create_trip(self.intent)
        self.application.confirm_trip(run.run_id)
        self.application.execute_trip(run.run_id)
        self.assertIs(RunStatus.RUNNING, self.store.get_run(run.run_id).status)

        restarted = _ImmediateBackgroundApplication(
            store=self.store,
            evidence_broker=self.application.evidence_broker,
            railway_collector=noop_collector,
            map_collector=noop_collector,
            web_collector=noop_collector,
            comparison_builder=_succeeding_comparison,
        )
        outcome = restarted.execute_trip(run.run_id)

        self.assertTrue(outcome.accepted)
        self.assertIs(RunStatus.COMPLETED, self.store.get_run(run.run_id).status)


def _succeeding_comparison(intent: object, **arguments: object) -> dict[str, object]:
    """重试成功那一支。形状取自 invariant_support.controlled_comparison。"""

    from tests.invariant_support import controlled_comparison

    return controlled_comparison(intent, **arguments)


if __name__ == "__main__":
    unittest.main()
