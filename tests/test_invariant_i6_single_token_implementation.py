"""I6: 展示 token 只能由单一实现产生。

契约：docs/contracts/invariants.md I6
预期转绿：P3
"""

from __future__ import annotations

import json
from pathlib import Path
import re
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

UI_TOKEN_LITERALS: tuple[str, ...] = (
    "verified",
    "sourced_stale",
    "sourced_undated",
    "estimated",
    "estimated_stale",
    "estimated_undated",
    "conflicting",
    "unknown",
)
_TOKEN_ALTERNATION = "|".join(
    re.escape(token)
    for token in sorted(UI_TOKEN_LITERALS, key=len, reverse=True)
)
_QUOTED_TOKEN = rf'(?:"(?:{_TOKEN_ALTERNATION})"|\'(?:{_TOKEN_ALTERNATION})\')'
_TOKEN_CONDITIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "comparison",
        re.compile(
            rf'(?:{_QUOTED_TOKEN}\s*(?:===|!==|==|!=)|'
            rf'(?:===|!==|==|!=)\s*{_QUOTED_TOKEN})'
        ),
    ),
    ("switch-case", re.compile(rf'\bcase\s+{_QUOTED_TOKEN}\s*:')),
    (
        "membership",
        re.compile(rf'\.(?:includes|has)\s*\([^)]*{_QUOTED_TOKEN}'),
    ),
    (
        "literal-list-membership",
        re.compile(
            rf'\[[^\]]*{_QUOTED_TOKEN}[^\]]*\]'
            rf'\s*\.(?:includes|has)\s*\('
        ),
    ),
    (
        "literal-set-membership",
        re.compile(
            rf'new\s+Set\s*\(\s*\[[^\]]*{_QUOTED_TOKEN}[^\]]*\]'
            rf'\s*\)\s*\.has\s*\('
        ),
    ),
)

# 呈现层唯一允许含 token 词表字面量的形状：徽章的 CSS 样式选择器。
# 它只决定颜色，不参与 support/freshness 或 token 判定。
BADGE_STYLE_SELECTOR = re.compile(
    rf'\.token\[data-token=(?P<quote>["\'])'
    rf'(?P<token>{_TOKEN_ALTERNATION})(?P=quote)\]'
)


def _mcp_app_frontend_sources() -> list[tuple[str, str]]:
    """Return inline scripts and local JS referenced by MCP App templates."""

    sources: list[tuple[str, str]] = []
    root = REPO_ROOT / "src" / "trip_decider"
    for template in sorted(root.glob("mcp_app*.html")):
        text = template.read_text(encoding="utf-8")
        relative = template.relative_to(REPO_ROOT).as_posix()
        for index, script in enumerate(
            re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", text, re.S),
            start=1,
        ):
            sources.append((f"{relative}#inline-script-{index}", script))
        for raw_source in re.findall(
            r'<script[^>]+src=["\']([^"\']+)["\'][^>]*>',
            text,
            re.S,
        ):
            if "://" in raw_source or raw_source.startswith("//"):
                continue
            path = (template.parent / raw_source).resolve()
            try:
                path.relative_to(REPO_ROOT.resolve())
            except ValueError:
                continue
            if path.is_file():
                sources.append(
                    (
                        path.relative_to(REPO_ROOT).as_posix(),
                        path.read_text(encoding="utf-8"),
                    )
                )
    return sources


def _token_condition_hits() -> list[tuple[str, int, str, str]]:
    hits: list[tuple[str, int, str, str]] = []
    for path, source in _mcp_app_frontend_sources():
        for kind, pattern in _TOKEN_CONDITIONS:
            for match in pattern.finditer(source):
                line = source.count("\n", 0, match.start()) + 1
                snippet = source.splitlines()[line - 1].strip()
                hits.append((path, line, kind, snippet))
    return hits


def _non_badge_style_literal_hits() -> list[tuple[str, str]]:
    """Every presentation token literal must be one badge-style selector."""

    hits: list[tuple[str, str]] = []
    root = REPO_ROOT / "src" / "trip_decider"
    quoted_token = re.compile(rf'["\'](?:{_TOKEN_ALTERNATION})["\']')
    for path, source in _mcp_app_frontend_sources():
        for literal in quoted_token.finditer(source):
            line = source.count("\n", 0, literal.start()) + 1
            hits.append((path, source.splitlines()[line - 1].strip()))
    for template in sorted(root.glob("mcp_app*.html")):
        text = template.read_text(encoding="utf-8")
        relative = template.relative_to(REPO_ROOT).as_posix()
        for style in re.findall(r"<style(?:\s[^>]*)?>(.*?)</style>", text, re.S):
            for selectors, declarations in re.findall(
                r"([^{}]+)\{([^{}]*)\}",
                style,
            ):
                if quoted_token.search(declarations):
                    hits.append((relative, declarations.strip()))
                for literal in quoted_token.finditer(selectors):
                    containing_selector = selectors[
                        selectors.rfind(",", 0, literal.start()) + 1:
                        selectors.find(",", literal.end())
                        if selectors.find(",", literal.end()) >= 0
                        else len(selectors)
                    ]
                    if BADGE_STYLE_SELECTOR.search(containing_selector) is None:
                        hits.append((relative, containing_selector.strip()))
        outside_resources = re.sub(
            r"<(?:style|script)(?:\s[^>]*)?>.*?</(?:style|script)>",
            "",
            text,
            flags=re.S,
        )
        for literal in quoted_token.finditer(outside_resources):
            line = outside_resources.count("\n", 0, literal.start()) + 1
            hits.append(
                (relative, outside_resources.splitlines()[line - 1].strip())
            )
    return hits


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

    def test_i6_mcp_app_token_conditionals_are_zero(self) -> None:
        """呈现资源只透传 token；不得按词表分支或重新定级。"""

        hits = _token_condition_hits()
        formatted = [
            f"{path}:{line} [{kind}] {snippet}"
            for path, line, kind, snippet in hits
        ]
        self.assertEqual(
            [],
            hits,
            "MCP App 模板或其前端资源出现 token 词表条件判定；"
            "呈现层只许透传，样式映射不在脚本里分支：\n  "
            + "\n  ".join(formatted),
        )

    def test_i6_rendering_literal_exemption_is_badge_style_only(self) -> None:
        """CSS 中的 token 字面量只允许出现在徽章样式选择器。"""

        hits = _non_badge_style_literal_hits()
        self.assertEqual(
            [],
            hits,
            "呈现模板中的 token 字面量超出 badge_style 单点豁免：\n  "
            + "\n  ".join(f"{path}: {snippet}" for path, snippet in hits),
        )


if __name__ == "__main__":
    unittest.main()
