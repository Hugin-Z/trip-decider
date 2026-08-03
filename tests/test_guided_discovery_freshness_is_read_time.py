"""guided_discovery 这条路径上，freshness 是 now 的函数（I5）。

针对性断言，配合 P4-b2 第一批迁移：`_coarse_option` 之前从
`value["freshness"]["status"]` 读陈旧与否——那是采集时冻结的判断，同一份
落盘无论何时读都给同一个答案。迁移后 token 出自 `project_domain(now=...)`。

判据是机械的：**同一份落盘、两个 now，结论必须能不同**。如果这个测试变绿
到"两个 now 给同一答案"，说明 freshness 又被写死了。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.guided_discovery import build_guided_comparison
from trip_decider.travel_agent import (
    EvidenceItem,
    EvidenceStatus,
    TravelIntent,
)

_SEEDS = [
    {
        "id": "destination-one",
        "name": "目的地一",
        "region_label": "某区域",
        "planning_city": "目的地一",
        "rail_gateway": "目的地一",
        "themes": [],
        "intensity": "standard",
    }
]

# 落盘时刻固定。两次读取分别在它之后 1 小时与 30 天。
COLLECTED_AT = "2026-08-02T10:00:00+00:00"
READ_FRESH = datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc)
READ_STALE = READ_FRESH + timedelta(days=30)


def _intent() -> TravelIntent:
    return TravelIntent.from_mapping(
        {
            "task_mode": "GUIDED_DISCOVERY",
            "origin": "甲地",
            "destination_anchor": "某区域",
            "earliest_departure_at": "2026-09-04T12:00:00",
            "latest_return_at": "2026-09-07T22:00:00",
            "travelers": 2,
            "total_budget_cny": 6000,
        }
    )


def _sourced_railway(_intent: TravelIntent) -> EvidenceItem:
    """一份固定的落盘证据。两次读取拿到的是同一个对象形状。"""

    return EvidenceItem(
        evidence_id="railway-fixed",
        domain="railway",
        status=EvidenceStatus.SOURCED,
        value={
            "roundtrip_duration_seconds": 21600,
            "roundtrip_fare_cny": 800.0,
            "snapshot": {"acquisition": "live_fetch", "retrieved_at": COLLECTED_AT},
        },
        sources=({"provider": "controlled-rail", "retrieved_at": COLLECTED_AT},),
    )


def _read_at(now: datetime) -> dict[str, object]:
    broker = EvidenceBroker(clock=lambda: now)
    with patch(
        "trip_decider.guided_discovery.guided_region_seeds",
        return_value=_SEEDS,
    ):
        return build_guided_comparison(
            _intent(),
            railway_collector=_sourced_railway,
            run_id="i5-read-time",
            evidence_broker=broker,
            clock=lambda: now,
        )


def _railway_entry(comparison: dict[str, object]) -> dict[str, object]:
    option = comparison["options"][0]
    return next(
        entry
        for entry in option["evidence_statuses"]
        if entry["domain"] == "railway"
    )


class FreshnessIsReadTimeCase(unittest.TestCase):
    def test_same_bytes_two_clocks_two_verdicts(self) -> None:
        fresh = _railway_entry(_read_at(READ_FRESH))
        stale = _railway_entry(_read_at(READ_STALE))

        self.assertEqual(
            "verified",
            str(fresh["token"]),
            "采集后 1 小时读取，token 应为 verified",
        )
        self.assertEqual(
            "sourced_stale",
            str(stale["token"]),
            "采集后 30 天读取，token 应为 sourced_stale；"
            "若仍是 verified，说明 freshness 又变回了写盘时冻结的判断（I5）",
        )
        self.assertNotEqual(
            str(fresh["token"]),
            str(stale["token"]),
            "同一份落盘、两个 now 给出同一个 freshness 结论——I5 被破坏",
        )

    def test_from_cache_follows_the_read_clock(self) -> None:
        """`from_cache` 是同一个判断的另一个出口，必须同步。"""

        self.assertIs(False, bool(_railway_entry(_read_at(READ_FRESH))["from_cache"]))
        self.assertIs(True, bool(_railway_entry(_read_at(READ_STALE))["from_cache"]))

    def test_collected_at_does_not_move_with_the_read_clock(self) -> None:
        """对照组：采集时刻是写盘属性，不能跟着 now 走。

        没有这一条，上面两条可以靠"把两个字段都接到 now"作弊通过。
        """

        fresh = _railway_entry(_read_at(READ_FRESH))
        stale = _railway_entry(_read_at(READ_STALE))
        self.assertEqual(COLLECTED_AT, str(fresh["collected_at"]))
        self.assertEqual(str(fresh["collected_at"]), str(stale["collected_at"]))


if __name__ == "__main__":
    unittest.main()
