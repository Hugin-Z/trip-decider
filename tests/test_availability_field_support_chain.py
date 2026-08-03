"""余票哨兵的三段链路：写哨兵 → 推导 → 消费。

`p4b-baseline-flip-preview.md` §3 要求的端到端断言。这条链路在表征上**看不见**
——前后余票都是字面量 `"UNKNOWN"`，值相同，判定结果也相同。兜底路径已经在工作，
但兜底工作和被测试是两回事：链路哪天断了，没有任何东西会红。

关键的一条是 `test_3_consumer_...` 里的最后半句：**同一条证据的车次时刻仍为
sourced**。那是字段级 support 对 item 级做到了什么的证明——item 级只能整条说
「这份铁路证据可靠」或「不可靠」，说不出「时刻可靠而余票未知」。
"""

from __future__ import annotations

import unittest

from trip_decider.agent_actions import _stale_railway_evidence
from trip_decider.evidence_projection import usable_fact_values
from trip_decider.travel_agent import EvidenceItem, EvidenceStatus

COLLECTED_AT = "2026-08-01T09:00:00+08:00"
SENTINEL = "UNKNOWN"


def _fresh_railway() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="railway-live-query",
        domain="railway",
        status=EvidenceStatus.SOURCED,
        value={
            "snapshot": {"acquisition": "live_fetch", "retrieved_at": COLLECTED_AT},
            "outbound": {
                "train_code": "G100",
                "departure_at": "2026-08-04T13:00",
                "arrival_at": "2026-08-04T16:00",
                "origin_station": "甲站",
                "destination_station": "乙站",
                "second_class_fare_cny_per_person": 400.0,
                "second_class_availability": "充足",
            },
        },
        sources=({"provider": "controlled-rail", "retrieved_at": COLLECTED_AT},),
    )


def _refresh_failure() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="railway-refresh-failed",
        domain="railway",
        status=EvidenceStatus.MISSING,
        value={"attempted_at": "2026-08-02T09:00:00+08:00"},
        missing_reason="rail_http",
    )


class AvailabilityChainCase(unittest.TestCase):
    def setUp(self) -> None:
        self.stale = _stale_railway_evidence(_fresh_railway(), _refresh_failure())

    def test_1_writer_blanks_availability_with_the_sentinel(self) -> None:
        """第一段：刷新失败时，写入侧把余票抹成字面量 UNKNOWN。"""

        outbound = self.stale.value["outbound"]
        self.assertEqual(SENTINEL, outbound["second_class_availability"])
        # 抹掉的只有余票。时刻与票价原样留下——它们没有过期到不可用，
        # 只是采集时刻变旧了，那是另一根轴的事。
        self.assertEqual("G100", outbound["train_code"])
        self.assertEqual(400.0, outbound["second_class_fare_cny_per_person"])

    def test_2_derivation_turns_the_sentinel_into_field_level_unknown(self) -> None:
        """第二段：推导把该叶子降为 support=unknown，并丢弃旧值。"""

        by_field = {
            str(fact["field"]): fact for fact in self.stale.facts
        }
        availability = by_field["outbound.second_class_availability"]
        self.assertEqual("unknown", str(availability["support"]))
        self.assertIsNone(
            availability["value"],
            "不可知的字段不得保留旧值——留着就等于宣称它仍然成立",
        )

    def test_3_consumer_loses_availability_but_keeps_the_schedule(self) -> None:
        """第三段：消费端拿不到余票，但车次时刻仍是 sourced。

        最后半句是这条链路存在的全部理由。
        """

        usable = usable_fact_values(self.stale.facts)
        outbound = usable["outbound"]

        self.assertNotIn(
            "second_class_availability",
            outbound,
            "support 不可用的字段不该出现在可用值里",
        )

        by_field = {str(fact["field"]): fact for fact in self.stale.facts}
        self.assertEqual(
            "sourced",
            str(by_field["outbound.train_code"]["support"]),
            "同一条证据的车次时刻必须仍为 sourced——"
            "item 级 support 说不出「时刻可靠而余票未知」，"
            "字段级说得出，这就是它存在的理由",
        )
        self.assertEqual("G100", outbound["train_code"])
        self.assertEqual(400.0, outbound["second_class_fare_cny_per_person"])

    def test_item_level_alone_cannot_express_this(self) -> None:
        """对照组：item 级 support 整条仍是 sourced。

        没有这一条，前三条可以在「整条降级为 unknown」的实现下也通过——
        那种实现同样让余票消失，但会连车次时刻一起废掉。
        """

        self.assertIs(EvidenceStatus.SOURCED, self.stale.status)
        supports = {str(fact["support"]) for fact in self.stale.facts}
        self.assertEqual(
            {"sourced", "unknown"},
            supports,
            "同一条证据内必须同时存在两种 support，否则字段级没有生效",
        )


if __name__ == "__main__":
    unittest.main()
