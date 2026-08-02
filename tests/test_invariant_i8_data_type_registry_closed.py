"""I8: 每个 data_type 必须在策略表中登记，且登记必须闭合。

契约：docs/contracts/invariants.md I8
预期转绿：P1（本阶段）

策略表指 docs/contracts/freshness-policy.md §2.2 的权威登记表，不是
evidence_broker.py 的 FRESHNESS_POLICIES 字典——后者是待迁移的现状。
"""

from __future__ import annotations

import unittest

from tests.invariant_support import parse_policy_registry, scan_produced_data_types

_VALID_PHASES = frozenset({"P1", "P2", "P3", "P4", "P5"})


class DataTypeRegistryClosedCase(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = parse_policy_registry()
        self.assertTrue(
            self.registry,
            "无法从 freshness-policy.md §2.2 解析出登记表——"
            "表格格式可能已偏离 I8 判定方法要求的形态",
        )
        self.produced = scan_produced_data_types(known=frozenset(self.registry))

    def test_i8_rule_1_every_producer_is_registered(self) -> None:
        unregistered = sorted(set(self.produced) - set(self.registry))
        self.assertEqual(
            [],
            unregistered,
            f"以下 data_type 在 src/ 中被产出但未登记：{unregistered}",
        )

    def test_i8_rule_2_every_active_entry_has_a_producer(self) -> None:
        orphaned = sorted(
            name
            for name, policy in self.registry.items()
            if policy["status"] == "active" and name not in self.produced
        )
        self.assertEqual(
            [],
            orphaned,
            f"以下登记为 active 的 data_type 在 src/ 中没有生产者：{orphaned}。"
            "它们的策略配置从未被执行过，因此取值从未被验证过。",
        )

    def test_i8_rule_3_planned_entries_carry_a_target_phase(self) -> None:
        problems = sorted(
            name
            for name, policy in self.registry.items()
            if policy["status"] == "planned"
            and policy["planned_for"] not in _VALID_PHASES
        )
        self.assertEqual(
            [],
            problems,
            f"以下 planned 项没有合法的 planned_for：{problems}。"
            "没有目标阶段，planned 会退化成永久豁免的垃圾桶——"
            "那正是 I8 反向规则要防的事（freshness-policy.md §2.1.1）。",
        )

    def test_i8_rule_4_reserved_entries_have_no_producer(self) -> None:
        misfiled = sorted(
            name
            for name, policy in self.registry.items()
            if policy["status"] == "reserved" and name in self.produced
        )
        self.assertEqual(
            [],
            misfiled,
            f"以下登记为 reserved 的 data_type 已经有生产者：{misfiled}，"
            "它们应当是 active",
        )

    def test_i8_registry_invariants_on_the_policy_values(self) -> None:
        problems: list[str] = []
        for name, policy in sorted(self.registry.items()):
            tolerance = int(policy["tolerance_seconds"])
            max_reuse = int(policy["max_reuse_seconds"])
            if tolerance > max_reuse:
                problems.append(
                    f"{name}: tolerance_seconds({tolerance}) > "
                    f"max_reuse_seconds({max_reuse})"
                )
            if not policy["stale_allowed"] and (tolerance or max_reuse):
                problems.append(
                    f"{name}: stale_allowed=False 时两个窗口必须同为 0，"
                    f"实为 {tolerance}/{max_reuse}"
                )
        self.assertEqual(
            [],
            problems,
            "登记表违反 freshness-policy.md §2 的取值约束：\n  "
            + "\n  ".join(problems),
        )

    def test_i8_seat_availability_is_absent_from_the_registry(self) -> None:
        """裁决 2：余票属订票域，PLAN.md v4 §2 明确不做。"""

        self.assertNotIn(
            "seat_availability",
            self.registry,
            "seat_availability 仍在登记表中，与裁决 2 及 PLAN.md v4 §2 "
            "的产品边界冲突",
        )


if __name__ == "__main__":
    unittest.main()
