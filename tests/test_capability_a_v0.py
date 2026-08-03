"""能力 A v0：候选池预筛与可达性准入。

目标一句话（作业单）：「从武汉出发、想找个山里安静的地方待两天」进去，出来
2–3 个可达、相关、各自 Plan-backed 的候选，**不再是乌鲁木齐**。

本文件守两段：预筛（缩池，不排序）与可达性（准入门槛 + 唯一排序判据）。
真实数据那一段由 `scripts/smoke_action_loop.py` 验。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider.destination_pool import (
    MAX_PREFILTERED,
    load_destination_pool,
    prefilter_pool,
)
from trip_decider.reachability import (
    PLAYABLE_FRACTION,
    assess_reachability,
    net_playable_seconds,
)

from tests.test_planning_input_compiler import READ_AT, _railway

WINDOW = 48 * 3600


class DestinationPoolCase(unittest.TestCase):
    def test_the_shipped_pool_loads(self) -> None:
        pool = load_destination_pool()
        self.assertGreaterEqual(len(pool), 20, "样例种子目录没加载到")
        self.assertTrue(all(entry.get("name") for entry in pool))

    def test_a_missing_pool_is_empty_not_an_error(self) -> None:
        """没有种子目录的部署应当如实报「无可行候选」，不是崩在读取上。"""

        with TemporaryDirectory() as temporary:
            missing = Path(temporary) / "nope.json"
            self.assertEqual([], load_destination_pool(missing))

    def test_prefilter_caps_the_pool(self) -> None:
        pool = load_destination_pool()
        selected = prefilter_pool(pool, themes=["自然风光"], trip_days=2.0)
        self.assertLessEqual(len(selected), MAX_PREFILTERED)
        self.assertTrue(selected, "预筛把池子清空了")

    def test_suggested_days_orders_but_never_rejects(self) -> None:
        """`suggested_days` 是排序偏好，**不是准入门槛**。

        裁决 1 的准入集是「车次 + 净可玩时长 + 锚点 POI」，不含它。第一版把它
        做成硬过滤，实测把目标用例打成零候选——种子目录里 12 个山岳类目的地
        全部自述 `min >= 2.5`，「山里待两天」于是一个都不剩。真正该拦下
        「两天去不了」的是实查车程算出的净可玩时长。
        """

        pool = load_destination_pool()
        two_days = prefilter_pool(pool, themes=["自然风光"], trip_days=2.0)
        self.assertTrue(
            two_days,
            "两天的行程窗被预筛清空了——suggested_days 又变回硬门槛了",
        )
        # 更装得下的排前面
        shortfalls = [
            max(0.0, float((entry.get("suggested_days") or {}).get("min", 0)) - 2.0)
            for entry in two_days
        ]
        self.assertEqual(
            sorted(shortfalls),
            shortfalls,
            "预筛没有把「更装得下的」排在前面",
        )

    def test_an_unmatched_theme_vocabulary_does_not_empty_the_pool(self) -> None:
        """主题命中**只排序不排除**——第二次犯同一个错才发现的。

        把它做成硬条件时 `themes=["自然风光"]` 直接清空池子：种子目录说
        「山水」，用户说「自然风光」，两个词互不包含。用户词表与种子词表粒度
        不同，拿它做准入门槛等于要求用户猜中种子的用词。

        裁决 1 的准入集里那条是「≥1 个**匹配主题的锚点 POI**」，是对真实 POI
        检索结果的要求（web 域实采验证），不是对种子自述字符串的要求。
        """

        pool = load_destination_pool()
        for themes in (["自然风光"], ["主题完全不存在的词"], []):
            with self.subTest(themes=themes):
                selected = prefilter_pool(pool, themes=themes, trip_days=3.0)
                self.assertTrue(
                    selected,
                    "主题对不上就把池子清空了——它又变回硬门槛了",
                )
                self.assertLessEqual(len(selected), MAX_PREFILTERED)

    def test_theme_hits_still_order_the_pool(self) -> None:
        """不排除不等于不起作用：命中的必须排在没命中的前面。"""

        entries = [
            {"name": "无关地", "themes": ["都市"], "suggested_days": {"min": 1.0}},
            {"name": "命中地", "themes": ["山水"], "suggested_days": {"min": 1.0}},
        ]
        selected = prefilter_pool(entries, themes=["山水"], trip_days=3.0)
        self.assertEqual(
            ["命中地", "无关地"],
            [entry["name"] for entry in selected],
        )

    def test_the_prefilter_reads_only_declared_attributes(self) -> None:
        """判据只用种子对自己声明的属性，不依赖任何外部数据。

        这一条防的是「预筛偷偷开始查网络」——那会让它失去存在意义
        （`capability-a-design.md` §6.1：预筛比它要省的东西还贵就没必要）。
        """

        entries = [
            {"name": "甲地", "themes": ["山水"], "suggested_days": {"min": 2.0}},
            {"name": "乙地", "themes": ["都市"], "suggested_days": {"min": 1.0}},
        ]
        selected = prefilter_pool(entries, themes=["山水"], trip_days=2.0)
        self.assertEqual(
            ["甲地", "乙地"],
            [entry["name"] for entry in selected],
            "命中的应排前面，但两条都该留下——预筛不排除",
        )


class ReachabilityCase(unittest.TestCase):
    def _item(self) -> dict:
        return _railway().to_dict()

    def test_a_sourced_round_trip_is_admitted(self) -> None:
        result = assess_reachability(
            self._item(),
            window_seconds=WINDOW,
            now=READ_AT,
        )
        self.assertTrue(result.admitted, f"未准入：{result.reason}")
        self.assertIsNone(result.reason)
        self.assertGreater(result.net_playable_seconds, 0)

    def test_a_destination_without_rail_evidence_is_filtered(self) -> None:
        """**过滤，不是降权**（裁决落点 1），且原因可查。

        上一轮的死路里，被推荐的城市查不到车次却照样成为候选，动作循环因此
        震荡不收敛。原因可查是另一半：没有 reason 的过滤，归因只能靠猜。
        """

        result = assess_reachability(
            None,
            window_seconds=WINDOW,
            now=READ_AT,
        )
        self.assertFalse(result.admitted)
        self.assertEqual("railway_not_collected", result.reason)

    def test_unsourced_rail_evidence_is_filtered_with_its_support(self) -> None:
        """判据用现有 token 表达，不引第二套（I6 不破）。"""

        missing = {
            "evidence_id": "railway-live-query",
            "domain": "railway",
            "status": "missing",
            "value": None,
            "sources": [],
            "missing_reason": "exact_station_identity_not_found",
        }
        result = assess_reachability(
            missing,
            window_seconds=WINDOW,
            now=READ_AT,
        )
        self.assertFalse(result.admitted)
        self.assertEqual("railway_support_unknown", result.reason)

    def test_too_much_time_on_the_train_is_filtered(self) -> None:
        """净可玩时长不足 → 不准入。这一条才是「两天去不了大理」的判据。"""

        window = 6 * 3600  # 六小时的行程窗，往返各三小时就一点不剩
        result = assess_reachability(
            self._item(),
            window_seconds=window,
            now=READ_AT,
        )
        self.assertFalse(result.admitted)
        self.assertEqual("net_playable_below_threshold", result.reason)
        self.assertIsNotNone(
            result.net_playable_seconds,
            "被阈值拦下时也要报出算出来的净可玩时长，否则无从判断差多少",
        )

    def test_the_threshold_is_the_documented_fraction(self) -> None:
        """阈值＝行程窗的 50%（裁决 5），且它确实参与判定。

        没有这一条，把 fraction 改成 0 也会全绿——那样阈值就是个摆设。
        """

        self.assertEqual(0.5, PLAYABLE_FRACTION)
        window = 8 * 3600
        item = self._item()
        lenient = assess_reachability(
            item,
            window_seconds=window,
            now=READ_AT,
            fraction=0.0,
        )
        strict = assess_reachability(
            item,
            window_seconds=window,
            now=READ_AT,
            fraction=0.9,
        )
        self.assertTrue(lenient.admitted)
        self.assertFalse(strict.admitted)

    def test_a_roundtrip_only_shape_is_understood(self) -> None:
        """只带 `roundtrip_duration_seconds` 的证据也要认。

        那是本产品既有的字段——采集器与候选卡都用它。第一版只认逐段的
        outbound/return，把这种证据判成「结构不全」：判据照着一个测试夹具的
        形状写，而不是照着管线真正携带的形状。
        """

        from trip_decider.travel_agent import EvidenceItem, EvidenceStatus

        item = EvidenceItem(
            evidence_id="estimated-railway",
            domain="railway",
            status=EvidenceStatus.ESTIMATED,
            value={
                "retrieved_at": "2026-07-30T10:44:00+08:00",
                "roundtrip_duration_seconds": 21600,
                "roundtrip_fare_cny": 800.0,
                "snapshot": {
                    "acquisition": "live_fetch",
                    "retrieved_at": "2026-07-30T10:44:00+08:00",
                },
            },
            sources=(
                {
                    "provider": "controlled-rail",
                    "retrieved_at": "2026-07-30T10:44:00+08:00",
                },
            ),
        ).to_dict()
        result = assess_reachability(
            item,
            window_seconds=WINDOW,
            now=READ_AT,
        )
        self.assertTrue(result.admitted, f"未准入：{result.reason}")

    def test_estimated_support_is_admitted(self) -> None:
        """裁决 5：estimated **可以**参与判定，不得被拦死。

        重查不会让推算值变精确，拦掉它等于永久拦死一条本来可用的路径
        （`evidence-axes.md` §5.2.1 的已知不对称，同一个道理）。
        """

        from trip_decider.reachability import ADMISSIBLE_SUPPORT

        self.assertIn("estimated", ADMISSIBLE_SUPPORT)
        self.assertIn("sourced", ADMISSIBLE_SUPPORT)
        self.assertNotIn("unknown", ADMISSIBLE_SUPPORT)
        self.assertNotIn("conflicting", ADMISSIBLE_SUPPORT)

    def test_net_playable_never_goes_negative(self) -> None:
        self.assertEqual(
            0,
            net_playable_seconds(
                window_seconds=3600,
                outbound_seconds=7200,
                return_seconds=7200,
            ),
        )


if __name__ == "__main__":
    unittest.main()
