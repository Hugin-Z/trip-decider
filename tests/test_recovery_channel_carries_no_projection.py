"""恢复数据不得携带读取层投影（I1/I5 的通道守卫）。

P4-b3 修好的通道：guided 比较结果是读取层投影，它落在 ``run.result``，而
``start_action_loop`` 整份 deepcopy 成 ``fallback_result`` 写进 action-loop.json，
于是 ``token: "verified"`` 被冻进了盘。

本文件守的是**已断的通道不复通**。它必须让一次 fallback 真实发生——只断言
``recovery_safe`` 这个纯函数是不够的，那证明不了它接在了写盘路径上。
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider import agent_actions
from trip_decider.evidence_core import recovery_safe

from tests.characterization_support import CHAR_NOW
from tests.invariant_support import drive_offline_run

# recovery_safe 剥掉的键。与 evidence_core._PROJECTION_KEYS 对应，此处写成
# 字面量：守卫不该跟着被守对象一起漂移。
PROJECTION_KEYS = (
    "token",
    "next_action",
    "display_status",
    "displayable",
    "planning_state",
)


def _paths_carrying(node: object, keys: tuple[str, ...], path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys:
                found.append(f"{path}/{key}")
            found.extend(_paths_carrying(value, keys, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_paths_carrying(value, keys, f"{path}[{index}]"))
    return found


class RecoveryChannelCase(unittest.TestCase):
    """驱动一次真实 run，检查它写下的 action-loop.json。"""

    @classmethod
    def setUpClass(cls) -> None:
        agent_actions.set_read_clock(lambda: CHAR_NOW)
        cls._temporary = TemporaryDirectory()
        try:
            application, _query, run_id = drive_offline_run(
                Path(cls._temporary.name) / "sessions"
            )
            directory = application.store.run_directory(run_id)
            assert directory is not None
            cls.action_loop = json.loads(
                (directory / "action-loop.json").read_text(encoding="utf-8")
            )
        finally:
            agent_actions.reset_read_clock()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_the_fallback_actually_happened(self) -> None:
        """前置条件：没有 fallback，后面两条断言就是空跑。"""

        fallback = self.action_loop.get("fallback_result")
        self.assertIsInstance(
            fallback,
            dict,
            "这次 run 没有产生 fallback_result，通道守卫等于没跑",
        )
        self.assertTrue(fallback, "fallback_result 是空的，同样守不住什么")

    def test_fallback_carries_no_projection_keys(self) -> None:
        """通道守卫本体。"""

        leaked = _paths_carrying(
            self.action_loop["fallback_result"], PROJECTION_KEYS
        )
        self.assertEqual(
            [],
            leaked,
            "读取层投影回流到了恢复数据里：\n  " + "\n  ".join(leaked),
        )

    def test_the_projection_was_there_to_strip(self) -> None:
        """阴性对照：证明剥离确实发生了，而不是上游本来就没产。

        没有这一条，前一条会在「比较结果压根没进 fallback」时假绿。
        """

        options = self.action_loop["fallback_result"].get("options")
        self.assertIsInstance(
            options,
            list,
            "fallback 里没有 options——比较结果没进来，剥离无从谈起",
        )
        assert isinstance(options, list)
        self.assertTrue(options)
        self.assertTrue(
            any("evidence_statuses" in option for option in options),
            "options 里没有 evidence_statuses，说明结构在别处就被丢了，"
            "不是被 recovery_safe 剥的",
        )
        # 结构留下了，投影没留下——这正是「存引用、读时重算」的形状。
        for option in options:
            for node in option.get("evidence_statuses", []):
                self.assertIn("domain", node, "证据节点连域都没了，剥过头了")
                self.assertNotIn("token", node)

    def test_recovery_safe_keeps_facts_and_structure(self) -> None:
        """纯函数层：只剥投影，不动事实与引用。"""

        cleaned = recovery_safe(
            {
                "token": "verified",
                "domain": "railway",
                "fact_refs": ["rail-1#outbound.train_code"],
                "nested": [{"next_action": {"kind": "auto_refetch"}, "value": 42}],
            }
        )
        self.assertEqual(
            {
                "domain": "railway",
                "fact_refs": ["rail-1#outbound.train_code"],
                "nested": [{"value": 42}],
            },
            cleaned,
        )


if __name__ == "__main__":
    unittest.main()
