"""P3b 重分类的构造点核对。

表征 fixture 直接注入证据，不经过采集侧构造点（见
`docs/contracts/p3b-characterization-log.md` 批次 3）。这三处由本文件单独守。

对象：`docs/contracts/support-reclassification.md` §1 的 R1 / R2 / R3。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.invariant_support import controlled_web, offline_intent
from trip_decider.agent_actions import _LoopState, _map_handler, _merged_support
from trip_decider.travel_agent import EvidenceItem, EvidenceStatus, TravelIntent


class MergedSupportCase(unittest.TestCase):
    """R3：合并结果的 support 按 evidence-axes.md §2.4 聚合。"""

    def test_two_sourced_stay_sourced(self) -> None:
        self.assertIs(
            EvidenceStatus.SOURCED,
            _merged_support(EvidenceStatus.SOURCED, EvidenceStatus.SOURCED),
        )

    def test_any_estimated_drags_the_merge_down(self) -> None:
        """行政区（sourced）与路线时长（estimated）合并后整体为 estimated。

        这是重分类影响面最大的一跳：合并结果会向下游全部消费方传播。
        """

        for pair in (
            (EvidenceStatus.SOURCED, EvidenceStatus.ESTIMATED),
            (EvidenceStatus.ESTIMATED, EvidenceStatus.SOURCED),
            (EvidenceStatus.ESTIMATED, EvidenceStatus.ESTIMATED),
        ):
            with self.subTest(pair=[item.value for item in pair]):
                self.assertIs(EvidenceStatus.ESTIMATED, _merged_support(*pair))


class EnumExtensionCase(unittest.TestCase):
    def test_is_usable_covers_exactly_the_value_carrying_states(self) -> None:
        self.assertTrue(EvidenceStatus.SOURCED.is_usable)
        self.assertTrue(EvidenceStatus.ESTIMATED.is_usable)
        # missing 没有值；conflicting 有多个互斥的值，取任何一个都是替用户裁决。
        self.assertFalse(EvidenceStatus.MISSING.is_usable)
        self.assertFalse(EvidenceStatus.CONFLICTING.is_usable)

    def test_persisted_value_round_trips(self) -> None:
        self.assertEqual("estimated", EvidenceStatus.ESTIMATED.value)
        self.assertIs(
            EvidenceStatus.ESTIMATED, EvidenceStatus("estimated")
        )


class ReclassifiedConstructionPointsCase(unittest.TestCase):
    """R1 / R2：高德路径规划时长的两处构造点必须产出 ESTIMATED。"""

    def test_map_route_construction_points_are_marked_estimated(self) -> None:
        import inspect

        from trip_decider import agent_actions

        source = inspect.getsource(agent_actions._map_handler)
        self.assertIn(
            "EvidenceStatus.ESTIMATED",
            source,
            "R1/R2：_map_handler 产出的地图证据含高德路径规划时长，"
            "按 evidence-axes.md §2.2 应为 estimated",
        )
        self.assertNotIn(
            "status=EvidenceStatus.SOURCED",
            source,
            "R1/R2 已重分类，不应再有 sourced 构造",
        )

    def test_map_route_with_no_normalized_segments_keeps_base_evidence(
        self,
    ) -> None:
        """路线接口返回空列表时也应该产出可读证据，不应访问未赋值局部变量。"""

        map_evidence = EvidenceItem(
            evidence_id="controlled-map-empty-routes",
            domain="map",
            status=EvidenceStatus.SOURCED,
            value={
                "destination": {"name": "乙地", "adcode": "330100"},
                "retrieved_at": "2026-08-01T09:00:00+08:00",
            },
            sources=(
                {
                    "provider": "controlled-map",
                    "retrieved_at": "2026-08-01T09:00:00+08:00",
                },
            ),
        )
        state = _LoopState(
            evidence={"web": controlled_web(), "map": map_evidence}
        )
        route_result = {
            "status": "NO_ROUTE",
            "segments": [],
            "place_resolutions": {},
            "retrieved_at": "2026-08-01T09:01:00+08:00",
            "source": {"provider": "controlled-route"},
        }

        with patch(
            "trip_decider.agent_actions.estimate_live_public_transport_segments",
            return_value=route_result,
        ):
            result = _map_handler(
                TravelIntent.from_mapping(offline_intent()),
                state,
            )

        self.assertEqual(EvidenceStatus.ESTIMATED, result.status)
        self.assertEqual([], result.value["local_transit"])
        self.assertEqual("NO_ROUTE", result.value["local_transit_outcome"])


if __name__ == "__main__":
    unittest.main()
