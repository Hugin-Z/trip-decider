"""每一个对宿主的错误都必须带下一步。**扫描式，不是按清单。**

事故（Claude Desktop MCP 第三次实测，2026-08-04）：宿主在候选比较阶段调
`advance_trip_task`，收到一句光秃秃的 "action loop was not started"，没有任何
下一步提示，于是盲试了好几次别的调用。

上一轮明明已经做了 next_call 守卫——但它是**按当时那份错误清单**逐条核对的，
而这条错误是从 `agent_actions` 经 `_guard` 透传出来的新路径，不在清单里。

> 按清单核对的守卫，总会漏掉清单之后新增的东西。

所以本轮改成两层，都不依赖清单：

1. **构造强制**：`TripMCPError.__init__` 的 `next_call` 没有默认值，省略是
   `TypeError`，传空是 `ValueError`。真的无路可走要显式传 `NO_NEXT_CALL`——
   那是一个决定，会被下面的扫描看见，而不是一次遗忘（D20）。
2. **静态扫描**：AST 扫全部 `TripMCPError(...)` 构造点与 `_guard(...)` 调用点，
   逐个核对 `next_call` 实参存在且不是 `None`。新增构造点自动进入扫描范围，
   不需要有人记得更新清单。

第 3 层是运行时的：把每个工具都往错里调一遍，断言抛出来的东西带 next_call。
静态扫描证明「所有构造点都传了」，运行时证明「传的东西真的到得了宿主手上」。
"""

from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.mcp_adapter import (
    NO_NEXT_CALL,
    TripMCPAdapter,
    TripMCPError,
)
from trip_decider.travel_agent import InMemoryAgentStore
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService

from tests.invariant_support import noop_collector

_ADAPTER_SOURCE = Path("src/trip_decider/mcp_adapter.py")


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


class StaticScanCase(unittest.TestCase):
    """扫描式：新增的构造点自动进入范围，不靠谁记得更新清单。"""

    def setUp(self) -> None:
        self.tree = ast.parse(_ADAPTER_SOURCE.read_text(encoding="utf-8"))

    def _calls_named(self, *names: str) -> list[ast.Call]:
        found: list[ast.Call] = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            label = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if label in names:
                found.append(node)
        return found

    def test_every_error_construction_passes_next_call(self) -> None:
        offenders = [
            f"line {call.lineno}"
            for call in self._calls_named("TripMCPError")
            if _keyword(call, "next_call") is None
        ]

        self.assertEqual(
            [],
            offenders,
            f"以下 TripMCPError 构造点没有传 next_call：{offenders}。"
            "宿主拿到没有下一步的错误只能盲试",
        )

    def test_no_construction_passes_next_call_none(self) -> None:
        """传 None 等于没传，只是绕过了构造函数的检查。"""

        offenders = [
            f"line {call.lineno}"
            for call in self._calls_named("TripMCPError", "_guard")
            if isinstance(
                (value := _keyword(call, "next_call")),
                ast.Constant,
            )
            and value.value is None
        ]

        self.assertEqual([], offenders, f"以下调用点传了 next_call=None：{offenders}")

    def test_every_guard_call_passes_next_call(self) -> None:
        """`_guard` 是错误的**总出口**：它透传的异常都是宿主要看的。

        上一轮那条漏网的错误正是从这里出去的——`_guard` 允许 next_call 缺省，
        于是内核抛出的任何新错误都会光着身子到宿主面前。
        """

        offenders = [
            f"line {call.lineno}"
            for call in self._calls_named("_guard")
            if _keyword(call, "next_call") is None
        ]

        self.assertEqual(
            [],
            offenders,
            f"以下 _guard 调用点没有传 next_call：{offenders}。"
            "内核抛出的错误会原样透传给宿主，没有下一步",
        )

    def test_the_sentinel_is_used_deliberately_if_at_all(self) -> None:
        """`NO_NEXT_CALL` 是逃生口，用了就要看得见。

        本轮零处使用——三处原本裸奔的错误都给出了真实的下一步。这条不禁止
        使用，只要求它保持可见：数量涨了就该有人解释为什么那些错误真的无路可走。
        """

        # 只数**当作实参传出去**的那些。定义处的赋值、以及构造函数内部
        # `next_call == NO_NEXT_CALL` 的比较都不是「用了逃生口」。
        uses = [
            call.lineno
            for call in self._calls_named("TripMCPError", "_guard")
            if isinstance((value := _keyword(call, "next_call")), ast.Name)
            and value.id == "NO_NEXT_CALL"
        ]

        self.assertEqual(
            [],
            uses,
            f"NO_NEXT_CALL 被当作实参传在 {uses}——本轮登记的用量是 0。"
            "要新增就在这里写明那条错误为什么真的无路可走",
        )


class RuntimeCase(unittest.TestCase):
    """静态扫描证明「都传了」，这里证明「传的到得了宿主手上」。"""

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        root = Path(self._temporary.name) / "sessions"
        store = InMemoryAgentStore(root)
        application = TripApplicationService(
            store=store,
            evidence_broker=EvidenceBroker(root.parent / "cache"),
            railway_collector=noop_collector,
            map_collector=noop_collector,
            web_collector=noop_collector,
        )
        query = TripQueryService(store=store, application_service=application)
        self.adapter = TripMCPAdapter(application, query)

    def _misuses(self) -> list[tuple[str, object]]:
        return [
            ("create_trip_task(空 intent)",
             lambda: self.adapter.create_trip_task({})),
            ("confirm_trip_intent(不存在的 run)",
             lambda: self.adapter.confirm_trip_intent("nope")),
            ("advance_trip_task(wait_seconds 越界)",
             lambda: self.adapter.advance_trip_task("nope", wait_seconds=999)),
            ("advance_trip_task(不存在的 run)",
             lambda: self.adapter.advance_trip_task("nope", wait_seconds=0)),
            ("read_trip(非法 view)",
             lambda: self.adapter.read_trip("nope", view="不存在的视图")),
            ("read_trip(不存在的 run)",
             lambda: self.adapter.read_trip("nope")),
            ("show_trip_candidates(不存在的 run)",
             lambda: self.adapter.render_trip_candidates("nope")),
            ("show_trip_plan(不存在的 run)",
             lambda: self.adapter.render_trip_plan("nope")),
            ("select_trip_candidate(不存在的候选)",
             lambda: self.adapter.select_trip_candidate("nope", "nope")),
            ("submit_trip_evidence(缺 action_id)",
             lambda: self.adapter.submit_trip_evidence("nope", {"value": {}})),
            ("submit_trip_evidence(缺 sources)",
             lambda: self.adapter.submit_trip_evidence(
                 "nope", {"action_id": "railway", "value": {"a": 1}})),
            ("revise_trip_plan(不存在的 run)",
             lambda: self.adapter.revise_trip_plan("nope", {"pace": "relaxed"})),
            ("audit_trip_plan(两者都不给)",
             lambda: self.adapter.audit_trip_plan()),
            ("verify_itinerary(不是列表)",
             lambda: self.adapter.verify_itinerary("不是列表")),
            ("verify_itinerary(空列表)",
             lambda: self.adapter.verify_itinerary([])),
        ]

    def test_every_misuse_answers_with_a_next_step(self) -> None:
        bare: list[str] = []
        for label, operation in self._misuses():
            try:
                operation()
            except TripMCPError as error:
                if not error.next_call or error.next_call == NO_NEXT_CALL:
                    bare.append(f"{label}: {error}")
                elif "下一步" not in str(error):
                    bare.append(f"{label}: next_call 没进消息文本")
            except Exception as error:  # noqa: BLE001
                bare.append(
                    f"{label}: 抛的不是 TripMCPError 而是 "
                    f"{type(error).__name__}（宿主看到的是未包装的内部错误）"
                )

        self.assertEqual([], bare, f"以下误用没有给出可执行的下一步：{bare}")


class ConstructorCase(unittest.TestCase):
    """省略 next_call 必须在语法层面失败，而不是靠人记得。"""

    def test_omitting_next_call_is_a_type_error(self) -> None:
        with self.assertRaises(TypeError):
            TripMCPError("没有下一步")  # type: ignore[call-arg]

    def test_empty_next_call_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TripMCPError("空的下一步", next_call="   ")

    def test_sentinel_keeps_the_message_clean(self) -> None:
        error = TripMCPError("确实没有下一步", next_call=NO_NEXT_CALL)

        self.assertEqual("确实没有下一步", str(error))
        self.assertEqual(NO_NEXT_CALL, error.next_call)


if __name__ == "__main__":
    unittest.main()
