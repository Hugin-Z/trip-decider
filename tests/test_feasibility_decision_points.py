"""§3.1 判定点清单必须与代码一致（PLAN.md §12 P5 闸门第 3 条）。

闸门原话：「`freshness-policy.md` §3.1 的可行性判定点清单与代码实际一致——
存在一个测试断言清单完备（新增判定点会导致该测试失败）」。本文件是那个测试。

**为什么这条闸门必须有**：§3.1 的清单是 §3.2 机械核对程序的输入——判断一个
data_type 是不是 `feasibility_critical`，靠的是「它的字段有没有进入某个判定点的
输入闭包」。清单漏一个判定点，§3.2 就会把一个真 critical 的类型判成非 critical，
于是它超窗后不重查、不阻断，陈旧数据静默支撑一个「可行」结论——那正是本产品
的靶心（`freshness-policy.md` §3.4）。

**上一版清单的实测下场**（写这条测试的直接理由）：16 个行号写进契约，一次重构
之后**无一命中**，处数也从 17 变成 18，而没有任何东西会响。行号是最先过期的
那种数字（D1）。现在清单以「函数名 + blocker_id」为键，行号降为参考。

**选型：AST 扫描**（三种路数的取舍见 `invariant_support.scan_decision_points`
的 docstring）。一句话：判定点是 18 处 `_blocker(...)` **调用**，装饰器挂不上
调用；而「逐个调用点记得注册」正是这条守卫要防的失误——D20 要的是让不小心
无从发生，不是要求更小心。
"""

from __future__ import annotations

import unittest

from tests.invariant_support import (
    parse_decision_point_registry,
    scan_decision_points,
)


class FeasibilityDecisionPointsCase(unittest.TestCase):
    def test_contract_registry_equals_the_code(self) -> None:
        """双向相等：多出是死登记，缺少是漏判。"""

        registry = parse_decision_point_registry()
        code = scan_decision_points()

        self.assertEqual(
            sorted(code - registry),
            [],
            "代码里有 §3.1.1 没登记的可行性判定点。"
            "漏登记会让 §3.2 把真 critical 的 data_type 判成非 critical，"
            "陈旧数据于是静默支撑「可行」结论——补进 §3.1.1 的表",
        )
        self.assertEqual(
            sorted(registry - code),
            [],
            "§3.1.1 登记了代码里不存在的判定点。"
            "死登记会让下一个人以为某条路径受保护——从表里删掉，"
            "或者说明它为什么该存在",
        )

    def test_the_registry_is_not_empty(self) -> None:
        """前置条件：解析器真的解析到了东西。

        没有这一条，一个把小节标题改坏、导致解析恒返回空集的改动会让上面那条
        用例**双向全绿**——空集是空集的子集。守卫的哑火方式往往不是断言写错，
        是输入悄悄变空（D6）。
        """

        registry = parse_decision_point_registry()
        self.assertGreaterEqual(
            len(registry),
            15,
            "§3.1.1 的表没解析出足够的行——小节标题或表格式被改动了，"
            "本文件的另一条用例会因此变成恒真",
        )

    def test_both_non_blocker_outputs_are_registered(self) -> None:
        """判定点 1、2 不是 blocker，容易在只想着 blocker 时被漏掉。

        §3.1 的三类里有两类不是 `_blocker(...)` 调用，而是对
        `feasibility_status` / `planning_state` 的赋值。它们与 blocker 同表登记
        （分两张表就会有人只改一张，D5），这一条钉住它们确实在表里。
        """

        registry = parse_decision_point_registry()
        self.assertIn(("_coarse_option", "feasibility_status"), registry)
        self.assertIn(("compile", "planning_state"), registry)


if __name__ == "__main__":
    unittest.main()
