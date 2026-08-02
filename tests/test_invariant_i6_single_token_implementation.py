"""I6: 展示 token 只能由单一实现产生。

契约：docs/contracts/invariants.md I6
预期转绿：P3
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from tests.invariant_support import (
    REPO_ROOT,
    SCANNED_TOKEN_LITERALS,
    scan_literals,
)

# 唯一的 token 产生实现。evidence_projection 只是适配器——它把持久化形状翻译
# 成内核输入再翻译回来，自己不含任何 token 字面量。
TOKEN_IMPLEMENTATION_WHITELIST: frozenset[str] = frozenset(
    {"src/trip_decider/evidence_core.py"}
)

# 前端资源允许出现 token 字面量用于样式与文案映射，但不得出现由 support 或
# freshness 推导 token 的逻辑。该区分靠白名单显式声明，不靠扫描器判断。
RENDERING_WHITELIST: frozenset[str] = frozenset(
    {
        "src/trip_decider/mcp_app_workspace_v1.html",
        "src/trip_decider/web/app.js",
        "src/trip_decider/web/styles.css",
    }
)

LEDGER_PATH = Path(__file__).with_name("invariant_ledger.json")


def _exempt_paths() -> dict[str, str]:
    """读取 ledger 中 I6 的豁免范围。

    豁免是数据不是代码：它登记在 invariant_ledger.json 里、带到期阶段、由元
    测试核对未过期。测试消费它，不自己定义它。
    """

    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    exempt: dict[str, str] = {}
    for entry in ledger.get("exemptions", []):
        if not isinstance(entry, dict) or entry.get("invariant") != "I6":
            continue
        for path in entry.get("paths", []):
            exempt[str(path)] = str(entry.get("expires_at_phase", "?"))
    return exempt


class SingleTokenImplementationCase(unittest.TestCase):
    def setUp(self) -> None:
        self.exempt = _exempt_paths()
        self.hits = [
            hit
            for hit in scan_literals(SCANNED_TOKEN_LITERALS, quoted_only=True)
            if hit[0] not in RENDERING_WHITELIST
            and hit[0] not in TOKEN_IMPLEMENTATION_WHITELIST
        ]

    def test_i6_token_literals_live_in_exactly_one_module(self) -> None:
        offending = [hit for hit in self.hits if hit[0] not in self.exempt]
        files = sorted({path for path, _line, _literal in offending})
        self.assertEqual(
            [],
            files,
            f"展示 token 字面量出现在白名单与豁免之外的 {len(files)} 个模块中，"
            f"共 {len(offending)} 处。docs/contracts/invariants.md I6 要求"
            "实现数 = 1。命中模块：\n  " + "\n  ".join(files),
        )

    def test_i6_exemptions_are_still_needed(self) -> None:
        """豁免不得虚挂：登记了却已经没有命中的，必须从 ledger 移除。

        没有这一条，豁免会在模块清理干净之后继续留着，下一个人无从判断它是
        真的还需要，还是忘了删。
        """

        hit_paths = {path for path, _line, _literal in self.hits}
        stale = sorted(set(self.exempt) - hit_paths)
        self.assertEqual(
            [],
            stale,
            "以下路径在 I6 豁免中登记，但已经没有 token 字面量了，"
            f"请从 invariant_ledger.json 移除：{stale}",
        )

    def test_i6_known_parallel_implementations_are_gone(self) -> None:
        """基线报告 §3.3 点名的读取层映射实现必须消失。

        豁免只覆盖写入侧（落盘产物的生产者，P4 清理）；读取层没有豁免。
        """

        read_layer = {
            "src/trip_decider/trip_read_model.py": "snapshot_status / 域状态推导",
        }
        surviving = sorted(
            f"{path}（{label}）"
            for path, label in read_layer.items()
            if any(hit[0] == path for hit in self.hits)
        )
        self.assertEqual(
            [],
            surviving,
            "以下读取层映射实现仍在产出展示态字面量：\n  " + "\n  ".join(surviving),
        )


if __name__ == "__main__":
    unittest.main()
