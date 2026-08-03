"""工具描述必须让宿主「认得出什么时候该用」并「照着填就对」。

事故（Claude Desktop MCP，2026-08-03）两条：

* 宿主在**明确 DIRECT_PLAN 场景**下没有选用 trip-decider——它自己 web search
  排了行程，全程无出处断言。描述里没有任何一句说明本服务与「自己检索」的差别，
  宿主自然没有理由选它。
* 被迫调用时反复试错十余次。描述里没有一个参数示例，宿主只能靠试。

本文件守的是**描述里那几样东西还在**，不是文风。三条判据都能机械核对：

1. 服务级描述要说清差异（实时查询的数据源 + 证据状态），否则宿主认不出场景；
2. 每个工具描述要有触发钩子（「什么时候用」一类的小节）；
3. 收结构化对象参数的工具要给示例——曾经试错 ≥2 次的参数全在这几个工具上。

判据是**下限不是风格**：长度门槛与小节标记都定得很松，只拦「退回一句英文
单行」这一种退化。文案好不好这里不判，也判不了。
"""

from __future__ import annotations

import asyncio
import unittest

from trip_decider.mcp_adapter import TripMCPAdapter
from trip_decider.mcp_server import build_mcp_server
from trip_decider.travel_agent import InMemoryAgentStore
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService

#: 收结构化对象参数的工具。宿主试错清单里的参数全落在这几个上。
_TOOLS_NEEDING_AN_EXAMPLE = frozenset(
    {
        "create_trip_task",
        "submit_trip_evidence",
        "revise_trip_plan",
    }
)

#: 服务级描述必须点到的差异要素。少任何一个，宿主就少一条匹配场景的钩子。
_DIFFERENTIATORS = ("12306", "高德", "证据状态")

_TRIGGER_MARKERS = ("什么时候", "适用", "用它")

_MIN_DESCRIPTION_CHARS = 60


def _build_server():
    store = InMemoryAgentStore()
    application = TripApplicationService(store=store)
    query = TripQueryService(store=store, application_service=application)
    return build_mcp_server(TripMCPAdapter(application, query))


class ToolDescriptionsCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server = _build_server()
        cls.tools = asyncio.run(server.list_tools())
        cls.descriptions = {
            tool.name: (tool.description or "") for tool in cls.tools
        }

    def test_every_tool_has_a_description(self) -> None:
        empty = sorted(
            name for name, text in self.descriptions.items() if not text.strip()
        )
        self.assertEqual([], empty, f"以下工具没有描述：{empty}")

    def test_descriptions_are_more_than_a_one_liner(self) -> None:
        """一句英文单行正是宿主没选用它的那个状态。"""

        terse = sorted(
            f"{name}（{len(text)} 字）"
            for name, text in self.descriptions.items()
            if len(text) < _MIN_DESCRIPTION_CHARS
        )
        self.assertEqual(
            [],
            terse,
            "以下工具描述短到只能是一句概括，给不出触发场景或参数示例："
            f"{terse}",
        )

    def test_every_tool_states_when_to_use_it(self) -> None:
        missing = sorted(
            name
            for name, text in self.descriptions.items()
            if not any(marker in text for marker in _TRIGGER_MARKERS)
        )
        self.assertEqual(
            [],
            missing,
            "以下工具描述没有触发钩子（「什么时候用」一类），"
            f"宿主无从判断该不该调它：{missing}",
        )

    def test_structured_parameter_tools_carry_an_example(self) -> None:
        missing = sorted(
            name
            for name in _TOOLS_NEEDING_AN_EXAMPLE
            if '{"' not in self.descriptions.get(name, "")
        )
        self.assertEqual(
            [],
            missing,
            "以下工具收结构化对象参数却没给示例值——宿主只能靠试："
            f"{missing}",
        )

    def test_evidence_tool_warns_against_inventing_facts(self) -> None:
        """本服务的全部价值在于事实追得到出处，这条必须写在最容易违反的地方。"""

        text = self.descriptions["submit_trip_evidence"]
        self.assertIn("sources", text)
        self.assertTrue(
            "不要编" in text or "不得编" in text,
            "提交证据的工具没有明写「不要编造」——那正是宿主最可能做的事",
        )

    def test_server_description_sells_the_difference(self) -> None:
        server = _build_server()
        blurb = f"{server.description or ''}\n{server.instructions or ''}"

        missing = [
            token for token in _DIFFERENTIATORS if token not in blurb
        ]
        self.assertEqual(
            [],
            missing,
            "服务级描述没点到与「自己检索」的差别要素"
            f"（{missing}）——宿主认不出什么时候该用它",
        )


if __name__ == "__main__":
    unittest.main()
