"""I9: 不得存在城市专属逻辑。

契约：docs/contracts/invariants.md I9
预期转绿：P5

裁决 1（2026-08-02）把 PLAN.md v3 架构红线 1 拆成两条：城市专属逻辑保留
为红线（本不变式）；中文词表 / 行政区后缀降级为非红线，因此
guided_discovery.py:715,723-736 与 travel_agent.py:55-61 不在判定范围内。
"""

from __future__ import annotations

import unittest

from tests.invariant_support import CITY_LITERAL_SEEDS, scan_literals


class NoCitySpecificLogicCase(unittest.TestCase):
    def test_i9_src_contains_no_place_name_literals(self) -> None:
        hits = scan_literals(CITY_LITERAL_SEEDS)
        by_file: dict[str, set[str]] = {}
        for path, _line, literal in hits:
            by_file.setdefault(path, set()).add(literal)
        report = sorted(
            f"{path}: {'、'.join(sorted(names))}"
            for path, names in by_file.items()
        )
        self.assertEqual(
            [],
            report,
            f"src/ 下 {len(by_file)} 个文件包含具体地名字面量，"
            "违反架构红线 1（裁决 1 拆分后仍保留的一半）：\n  "
            + "\n  ".join(report),
        )

    def test_i9_language_word_lists_are_not_in_scope(self) -> None:
        """降级部分不得被误判为违规——防止红线在后续被悄悄改回去。"""

        language_only = ("自治州", "倾向", "大概想去")
        hits = scan_literals(language_only)
        self.assertNotEqual(
            [],
            hits,
            "前置条件不满足：语言词表已从 src/ 消失，"
            "本用例失去了它要防的对象，应重新审视 I9 的判定范围",
        )
        self.assertEqual(
            [],
            [
                literal
                for literal in language_only
                if literal in CITY_LITERAL_SEEDS
            ],
            "语言词表被写进了地名字面量集合，与裁决 1 的降级冲突",
        )


if __name__ == "__main__":
    unittest.main()
