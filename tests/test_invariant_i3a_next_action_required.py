"""I3a: 每个非 verified 的事实必须携带 next_action，verified 必须不带。

契约：docs/contracts/invariants.md I3a
预期转绿：P2（内核范围）
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.invariant_support import drive_offline_run

_NEXT_ACTION_REQUIRED_FIELDS = (
    "kind",
    "field_ref",
    "data_type",
    "reason_code",
    "actor",
    "blocking",
    "detail",
)
_NEXT_ACTION_KINDS = frozenset(
    {
        "auto_refetch",
        "user_confirm",
        "user_choice",
        "user_supply",
        "accept_as_is",
    }
)


class NextActionRequiredCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        _application, self.query, self.run_id = drive_offline_run(
            Path(self._temporary.name) / "sessions"
        )

    def _evidence_nodes(self) -> list[dict[str, object]]:
        presentation = self.query.trip(self.run_id)["presentation"]
        nodes = presentation.get("evidence_statuses")
        self.assertIsInstance(
            nodes,
            list,
            "前置条件不满足：presentation 中没有 evidence_statuses",
        )
        assert isinstance(nodes, list)
        self.assertTrue(nodes, "前置条件不满足：evidence_statuses 为空")
        return [node for node in nodes if isinstance(node, dict)]

    def test_i3a_every_evidence_node_carries_a_token(self) -> None:
        missing = [
            node.get("domain")
            for node in self._evidence_nodes()
            if "token" not in node
        ]
        self.assertEqual(
            [],
            missing,
            "以下证据节点没有 token 字段，因此无法判定是否该带 next_action："
            f"{missing}。当前节点携带的是 status（LIVE/STALE/MISSING），"
            "见 trip_read_model.py:889-922",
        )

    def test_i3a_non_verified_nodes_carry_a_complete_next_action(self) -> None:
        problems: list[str] = []
        for node in self._evidence_nodes():
            domain = node.get("domain")
            token = node.get("token")
            action = node.get("next_action")
            if token == "verified":
                if action is not None:
                    problems.append(f"{domain}: verified 却携带了 next_action")
                continue
            if not isinstance(action, dict):
                problems.append(
                    f"{domain}: token={token!r} 非 verified，但没有 next_action"
                )
                continue
            for field in _NEXT_ACTION_REQUIRED_FIELDS:
                if field not in action:
                    problems.append(f"{domain}: next_action 缺少 {field}")
            if action.get("kind") not in _NEXT_ACTION_KINDS:
                problems.append(
                    f"{domain}: next_action.kind={action.get('kind')!r} 不在取值域内"
                )
        self.assertEqual(
            [],
            problems,
            "next_action 契约未满足（docs/contracts/evidence-axes.md §5）：\n  "
            + "\n  ".join(problems),
        )

    def test_i3a_candidate_view_evidence_carries_next_action(self) -> None:
        """候选比较视图同样受 I3a 约束，不因它是另一条读取入口而豁免。"""

        candidates = self.query.candidates(self.run_id)["candidates"]
        self.assertTrue(candidates, "前置条件不满足：候选列表为空")
        option = candidates[0]
        nodes = option.get("evidence_statuses")
        self.assertIsInstance(
            nodes,
            list,
            "候选卡没有 evidence_statuses，无法核对 I3a",
        )
        assert isinstance(nodes, list)

        problems: list[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            domain = node.get("domain")
            if "token" not in node:
                problems.append(f"{domain}: 没有 token")
                continue
            if node["token"] != "verified" and "next_action" not in node:
                problems.append(
                    f"{domain}: token={node['token']!r} 非 verified，"
                    "但没有 next_action"
                )
        self.assertEqual(
            [],
            problems,
            "候选卡的证据节点不满足 I3a（guided_discovery.py:575-584 产出的"
            "元组只有 domain/status/collected_at/from_cache/timed_out）：\n  "
            + "\n  ".join(problems),
        )


if __name__ == "__main__":
    unittest.main()
