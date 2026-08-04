"""I13：单次 MCP 工具调用的墙钟时间有上界，且循环必须能到达检查点。

事故（Claude Desktop MCP 第二次实测，2026-08-04）：宿主主动选用、intent 一次
填对、零试错——然后卡死 4 分钟，超时放弃回退 web search。

归因最反直觉的一点：**没有任何一次调用是慢的**。每次 `advance_trip_task` 都在
10 秒内老实返回，只是永远返回 `checkpoint=RUNNING`。坏的是总时长无界——没有
任何一次调用能让宿主离终点更近。

所以本文件守两件事，缺一不可：

1. 单次调用不超 `MCP_CALL_BUDGET_SECONDS`（慢采集不是豁免理由）；
2. 循环算出「要外部补证据」之后必须落到宿主认得的检查点，不得无限 RUNNING。

见 `docs/contracts/invariants.md` I13。
"""

from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from typing import Any
import unittest
from unittest import mock

from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.mcp_adapter import (
    MCP_CALL_BUDGET_SECONDS,
    TripMCPAdapter,
    TripMCPError,
)
from trip_decider.travel_agent import InMemoryAgentStore
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService

from tests.invariant_support import noop_collector

#: 假采集器一次睡多久。比同步推进预算（5 秒）大得多，也比宿主超时线小，
#: 这样「预算没生效」会明确表现为超标而不是把测试挂死。
_SLOW_COLLECT_SECONDS = 25.0

#: 用例结束时置位，让还在睡的假采集器立刻醒来退出。
#:
#: 不这么做的话，本用例会往后续用例里漏一批睡满 25 秒的守护线程——它们醒来后
#: 还会去写自己那个 run。实测这批线程真的让 `test_user_supply_railway_end_to_end`
#: 与 `test_product_web` 间歇性失败过一次；单跑都绿、连跑才红，正是最难查的那
#: 种。测试自己制造不确定性，比它守的东西还坏。
_RELEASE_SLOW_COLLECTORS = threading.Event()

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


def slow_collector(*args: Any, **kwargs: Any) -> dict[str, object]:
    """一个「网络很慢」的采集器。

    用 `Event.wait` 而不是 `time.sleep`：用例期间它一样是阻塞的（事件没置位，
    等满 25 秒），用例结束置位后它立刻醒来退出，不把线程漏给后面的用例。
    """

    _RELEASE_SLOW_COLLECTORS.wait(timeout=_SLOW_COLLECT_SECONDS)
    raise AssertionError("慢采集器不该跑完——预算生效的话早就返回了")


class BoundedMCPCallCase(unittest.TestCase):
    def setUp(self) -> None:
        _RELEASE_SLOW_COLLECTORS.clear()
        self.addCleanup(_RELEASE_SLOW_COLLECTORS.set)
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        root = Path(self._temporary.name) / "sessions"
        self.store = InMemoryAgentStore(root)
        self.application = TripApplicationService(
            store=self.store,
            evidence_broker=EvidenceBroker(root.parent / "cache"),
            railway_collector=slow_collector,
            map_collector=slow_collector,
            web_collector=slow_collector,
        )
        self.query = TripQueryService(
            store=self.store,
            application_service=self.application,
        )
        self.adapter = TripMCPAdapter(self.application, self.query)

    def _elapsed(self, label: str, operation) -> float:
        started = time.monotonic()
        try:
            operation()
        except TripMCPError:
            pass  # 业务性拒绝也算返回了——本不变式只管时间
        elapsed = time.monotonic() - started
        self.assertLess(
            elapsed,
            MCP_CALL_BUDGET_SECONDS,
            f"{label} 用了 {elapsed:.1f} 秒，超过 I13 上界 "
            f"{MCP_CALL_BUDGET_SECONDS} 秒——宿主会当成服务器挂了",
        )
        return elapsed

    def test_every_registered_tool_has_a_budget_probe(self) -> None:
        """**扫描式**：新注册的工具自动进入 I13 的范围。

        第四次实测（2026-08-04）`verify_itinerary` 首次被真宿主调用即 4 分钟
        无响应——而 I13 当时是绿的。归因是**清单式守卫**：下面那份 calls 列表
        是按写它那天的工具册手抄的，`verify_itinerary` 在同一轮新增却没进去。

        与 next_call 守卫上一轮踩的是同一个坑：按清单核对的守卫，总会漏掉清单
        之后新增的东西。这里不再手抄——从真实注册的工具册取名单，缺探针就红。
        新增工具时你可以选择怎么探它，但**不能选择不探**（D20）。
        """

        import asyncio

        from trip_decider.mcp_server import build_mcp_server

        server = build_mcp_server(self.adapter)
        registered = {tool.name for tool in asyncio.run(server.list_tools())}
        probed = {label.split("(")[0] for label, _ in self._budget_probes()}

        self.assertEqual(
            set(),
            registered - probed,
            f"以下工具已注册但没有 I13 探针：{sorted(registered - probed)}。"
            "在 _budget_probes 里补一条——这正是 verify_itinerary 漏掉的方式",
        )
        self.assertEqual(
            set(),
            probed - registered,
            f"以下探针指向已不存在的工具：{sorted(probed - registered)}",
        )

    def _budget_probes(self) -> list[tuple[str, Any]]:
        """工具名 → 一次会真的走到底的调用。

        探针本身是数据，但**缺哪个会被上面的扫描抓到**——这就是它与旧清单的
        全部区别。
        """

        run_id = getattr(self, "_probe_run_id", None)
        if run_id is None:
            run_id = str(
                self.adapter.create_trip_task(dict(_INTENT))["run"]["run_id"]
            )
            self.adapter.confirm_trip_intent(run_id)
            self._probe_run_id = run_id
        # 只停自己起的这一个。`mock.patch.stopall` 会把别处起的补丁一并停掉，
        # 那是跨用例的隐蔽干扰。
        patch = mock.patch(
            "trip_decider.mcp_adapter.verify_checkable_incrementally",
            lambda checkable, **kwargs: None,
        )
        patch.start()
        self.addCleanup(patch.stop)
        return [
            *self._core_probes(run_id),
            # 实采注入成不动的假货：本用例量的是**工具调用本身**多久返回，
            # 不该顺带去打 12306（那会让用例依赖网络，还会漏线程给后续用例）。
            ("verify_itinerary", lambda: self.adapter.verify_itinerary(
                [{"train_code": "G1", "origin_station": "甲站",
                  "destination_station": "乙站",
                  "departure_at": "2026-08-11T08:00"}])),
            ("read_verification", lambda: self.adapter.read_verification(
                "verify-does-not-exist")),
        ]

    def test_every_tool_returns_within_budget_under_a_slow_collector(
        self,
    ) -> None:
        """采集器慢到 25 秒，每个工具仍必须在上界内返回。"""

        for label, operation in self._budget_probes():
            with self.subTest(tool=label):
                self._elapsed(label, operation)

    def _core_probes(self, run_id: str) -> list[tuple[str, Any]]:
        calls = [
            ("create_trip_task", lambda: self.adapter.create_trip_task(
                dict(_INTENT))),
            ("confirm_trip_intent", lambda: self.adapter.confirm_trip_intent(
                run_id)),
            ("advance_trip_task", lambda: self.adapter.advance_trip_task(
                run_id, wait_seconds=1)),
            ("read_trip", lambda: self.adapter.read_trip(run_id)),
            ("read_trip(missing)", lambda: self.adapter.read_trip(
                run_id, view="missing")),
            ("show_trip_candidates", lambda: self.adapter
                .render_trip_candidates(run_id)),
            ("show_trip_plan", lambda: self.adapter.render_trip_plan(run_id)),
            ("select_trip_candidate", lambda: self.adapter
                .select_trip_candidate(run_id, "nope")),
            ("submit_trip_evidence", lambda: self.adapter.submit_trip_evidence(
                run_id, {"action_id": "railway", "status": "missing",
                         "missing_reason": "测试"})),
            ("revise_trip_plan", lambda: self.adapter.revise_trip_plan(
                run_id, {"pace": "relaxed"})),
            ("audit_trip_plan", lambda: self.adapter.audit_trip_plan(
                content="测试攻略")),
        ]
        return calls


class TerminatesWithoutABackgroundThreadCase(unittest.TestCase):
    """没有后台线程兜底时，同步支自己必须能走到检查点。

    这是事故的**精确形状**。`select_candidate` 有意不 spawn（两个客户端都会紧接着
    显式驱动一次），所以「比较完选一个」之后推进动作循环的**只有** `execute_trip`
    的同步支。而同步支算出 `NEED_USER_INPUT` 之后把结论丢了，run 于是永远
    RUNNING。

    用「`_spawn` 置空」来建模这个条件：这样唯一能救场的就是同步支落状态。
    把 `execute_trip` 里那一行 `settle_action_loop` 去掉，本用例必红——
    这是它与上面那些用例的关键差别，那些用例有后台线程兜底，去掉修复照样绿。
    """

    def setUp(self) -> None:
        _RELEASE_SLOW_COLLECTORS.clear()
        self.addCleanup(_RELEASE_SLOW_COLLECTORS.set)
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        root = Path(self._temporary.name) / "sessions"

        class NoBackgroundApplication(TripApplicationService):
            @staticmethod
            def _spawn(*, target: Any, args: Any, name: str) -> None:
                del target, args, name

        self.store = InMemoryAgentStore(root)
        self.application = NoBackgroundApplication(
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
        self.adapter.confirm_trip_intent(self.run_id)

    def _advance_until_checkpoint(self) -> tuple[list[str], dict[str, object]]:
        checkpoints: list[str] = []
        response: dict[str, object] = {}
        for _ in range(8):
            response = self.adapter.advance_trip_task(
                self.run_id,
                wait_seconds=1,
            )
            checkpoints.append(str(response["checkpoint"]))
            if checkpoints[-1] != "RUNNING":
                break
        return checkpoints, response

    def test_advance_reaches_a_checkpoint_instead_of_looping_forever(
        self,
    ) -> None:
        """事故里每次调用都规矩地返回 RUNNING，永不终止。

        只测单次耗时的守卫会对这种形状全绿放行——所以这里测的是「会不会前进」。
        """

        checkpoints, _ = self._advance_until_checkpoint()

        self.assertNotEqual(
            ["RUNNING"] * len(checkpoints),
            checkpoints,
            "连调 8 次全是 RUNNING——这正是宿主卡死 4 分钟的形状："
            "每次都按时返回，但永远不前进",
        )

    def test_the_reached_checkpoint_tells_the_host_what_to_do(self) -> None:
        """到了检查点还得说得出下一步，否则宿主照样只能猜。"""

        _, response = self._advance_until_checkpoint()

        self.assertNotEqual("RUNNING", str(response.get("checkpoint")))
        next_call = response.get("next_call")
        self.assertIsInstance(next_call, dict)
        assert isinstance(next_call, dict)
        self.assertTrue(
            next_call.get("options"),
            f"检查点 {response.get('checkpoint')} 没给出任何可调入口",
        )


class SingleSettlementEntrypointCase(unittest.TestCase):
    """只许有一个地方把动作循环的结论落成 run 状态。

    事故的形状就是同一个结论有两处实现、只有一处生效（D19）。这条守卫防止它
    再长回来：新增一处 `store.block(` 就必须登记。
    """

    #: 允许调用 `store.block(` 的函数。改这张表**必须**同时说明为什么新的
    #: 那一处不会与 `settle_action_loop` 得出不同结论。
    ALLOWED = frozenset(
        {
            # 唯一的「动作循环走不动了，需要外部补证据」落状态入口。
            "settle_action_loop",
            # 后台线程的异常兜底：线程里抛出来的异常不能让 run 静默留在
            # RUNNING。落的是 ACTION_LOOP_FAILED / INTERNAL_ERROR，
            # 与 settle_action_loop 的 CODEX_ACTION_REQUIRED 不是同一件事。
            "_run_action_loop_background",
            # 候选比较**失败**，落 GUIDED_COMPARISON_UNAVAILABLE。这是比较
            # 阶段的事，此时动作循环还没开始，不可能与 settle_action_loop
            # 抢同一个结论。
            "_candidate_comparison_background",
        }
    )

    def test_block_is_called_only_from_registered_functions(self) -> None:
        source = Path("src/trip_decider/trip_application.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)

        offenders: list[str] = []
        for function in ast.walk(tree):
            if not isinstance(
                function, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            if function.name in self.ALLOWED:
                continue
            for node in ast.walk(function):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "block"
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "store"
                ):
                    offenders.append(f"{function.name}:{node.lineno}")

        self.assertEqual(
            [],
            sorted(offenders),
            "以下函数直接调了 store.block(，绕过唯一落状态入口 "
            f"settle_action_loop：{sorted(offenders)}。"
            "两处实现只有一处生效，正是宿主卡死 4 分钟的成因",
        )


if __name__ == "__main__":
    unittest.main()
