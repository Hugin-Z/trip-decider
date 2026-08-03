"""表征守卫：当前快照必须逐字段等于基线文件。

**这是本仓的哑火检测器之一。** 在它落地之前，表征核对没有任何自动兜底——
套件里没有一条断言「快照 == 基线」，而 `python -m tests.characterization_support`
是直接覆盖写盘。少了这一条，重刷就从「确认」退回成「信任」：谁都可能在没看过
差异的情况下把基线洗掉，而基线是判断其他改动有没有踩坏东西的唯一工具。

三层守卫的分工（`engineering-discipline.md` D7）：

* **表征**（本文件）守**判定结果**——同一份输入，结论字段有没有变；
* 单测守**数据形状**；
* 不变式守**契约性质**。

哪层缺位，哪层负责的那类变化就会静默。timing_status 退役那次表征零响，正是
因为那类变化归单测管而不归表征管——不是表征失灵，是找错了层。

**改结论字段时它必然响，这是设计。** 处置按 D8 三步：结论变没变 → 变的什么
性质 → 归到哪条裁决；逐条对上之后才允许
`python -m tests.characterization_support --save` 重刷。表外的即停。
"""

from __future__ import annotations

import unittest

from tests.characterization_support import BASELINE_PATH, check, diff_paths


class CharacterizationBaselineCase(unittest.TestCase):
    def test_current_snapshot_equals_baseline(self) -> None:
        mismatches = check()
        paths = sorted(set(diff_paths(mismatches)))
        self.assertEqual(
            [],
            mismatches,
            f"表征快照与基线有 {len(mismatches)} 条差异，涉及 "
            f"{len(paths)} 个字段路径：\n  "
            + "\n  ".join(paths)
            + f"\n\n基线文件：{BASELINE_PATH}"
            "\n逐条对本轮裁决表核对：表内的确认后跑 "
            "`python -m tests.characterization_support --save` 重刷；"
            "表外的即停——那是改坏了，不是该重刷的理由。",
        )


if __name__ == "__main__":
    unittest.main()
