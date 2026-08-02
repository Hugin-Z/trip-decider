"""I3b: UI 必须渲染 next_action.detail（弱形式，裁决 4）。

契约：docs/contracts/invariants.md I3b
预期转绿：P3

弱形式的已知覆盖缺口：能抓住「字段被完全忽略」，抓不住「引用了但渲染在
不可见位置」。裁决 4 已接受该缺口——requirements.lock 44 行内无任何 DOM
实现，为一条不变式引入浏览器驱动不划算。
"""

from __future__ import annotations

import unittest

from tests.invariant_support import MCP_APP_HTML, WEB_APP_JS


class UIRendersNextActionCase(unittest.TestCase):
    def _assert_renders(self, label: str, source: str) -> list[str]:
        problems: list[str] = []
        if "next_action" not in source:
            problems.append(f"{label}: 完全没有引用 next_action")
            return problems
        if "detail" not in source:
            problems.append(f"{label}: 引用了 next_action 但没有引用 detail")
        return problems

    def test_i3b_mcp_app_renders_next_action_detail(self) -> None:
        source = MCP_APP_HTML.read_text(encoding="utf-8")
        self.assertEqual(
            [],
            self._assert_renders("mcp_app_workspace_v1.html", source),
            "MCP App 不渲染 next_action。当前候选卡（:212-268）只渲染 "
            "evidence_missing 的中文自由文本列表，evidence_statuses 与 "
            "next_action 均未被引用。",
        )

    def test_i3b_standalone_web_renders_next_action_detail(self) -> None:
        source = WEB_APP_JS.read_text(encoding="utf-8")
        self.assertEqual(
            [],
            self._assert_renders("web/app.js", source),
            "Standalone Web 不渲染 next_action。app.js:1099 只遍历 "
            "presentation.evidence_statuses 并读取其 status。",
        )


if __name__ == "__main__":
    unittest.main()
