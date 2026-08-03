"""两处 context 裁剪必须产出同一形状。

A 收敛（`persistence-v2.md` §2.1.1）之后有两个实现：

* `travel_agent.trimmed_context`——**权威**，`run.json` 与 `plan-NNNN.json`
  两条写入路径共用；
* `itinerary_planner._trimmed`——重排路径用。`itinerary_planner` 在
  `travel_agent` **下方**（后者 import 前者），不能反向 import，规则只有三行，
  复制一次比倒转依赖方向划算。

**但复制就是两份并列的名单，早晚有人只改一份（D5）。** 这里没法像别处那样
「合并成一份、旧名保留为派生视图」——依赖方向不允许。退而求其次：用一条断言
把「两份必须同形」变成机械可核对的，改了一份而不改另一份即红。

判据是**输出相等**，不是源码相似：实现可以各写各的，产出不许分叉。
"""

from __future__ import annotations

import unittest

from trip_decider.itinerary_planner import _trimmed
from trip_decider.travel_agent import trimmed_context


def _context(**extra) -> dict:
    return {
        "context_id": "ctx-1",
        "intent": {"origin": "甲站", "destination_anchor": "乙地"},
        "evidence": [
            {"evidence_id": "railway-live-query", "domain": "railway"},
            {"evidence_id": "web-official-query", "domain": "web"},
            {"evidence_id": "map-live-query", "domain": "map"},
        ],
        "built_at": "2026-07-30T11:00:00+08:00",
        **extra,
    }


class ContextTrimmingCase(unittest.TestCase):
    def test_both_implementations_agree(self) -> None:
        self.assertEqual(trimmed_context(_context()), _trimmed(_context()))

    def test_the_inline_evidence_is_gone(self) -> None:
        """收敛的目的：文件里**根本没有可回落的证据副本**。

        留一份内联副本，「读取层不得回落到旧值」就退化成一句自律，而自律
        不可核对（D20 的同一条道理，也是 R2 由形状保证的原因）。
        """

        for trim in (trimmed_context, _trimmed):
            with self.subTest(implementation=trim.__name__):
                result = trim(_context())
                self.assertNotIn("evidence", result)
                self.assertEqual(
                    [
                        "railway-live-query",
                        "web-official-query",
                        "map-live-query",
                    ],
                    result["evidence_refs"],
                )

    def test_everything_else_is_preserved(self) -> None:
        """只摘证据，别的原样——裁剪不是重建。"""

        for trim in (trimmed_context, _trimmed):
            with self.subTest(implementation=trim.__name__):
                result = trim(_context(hard_constraint_conflicts=["x"]))
                self.assertEqual("ctx-1", result["context_id"])
                self.assertEqual("2026-07-30T11:00:00+08:00", result["built_at"])
                self.assertEqual(["x"], result["hard_constraint_conflicts"])

    def test_a_context_without_evidence_still_gets_refs(self) -> None:
        """已裁剪过的 context 再裁剪一次不出事。

        重排链路会把上一版的 context 再传一遍，二次裁剪必须幂等——否则
        `evidence_refs` 会被清空，而清空表现出来是「计划突然指不到任何证据」。
        """

        once = trimmed_context(_context())
        twice = trimmed_context(once)
        self.assertEqual(once["evidence_refs"], twice["evidence_refs"])
        self.assertEqual(once, twice)

        once_b = _trimmed(_context())
        self.assertEqual(once_b["evidence_refs"], _trimmed(once_b)["evidence_refs"])


if __name__ == "__main__":
    unittest.main()
