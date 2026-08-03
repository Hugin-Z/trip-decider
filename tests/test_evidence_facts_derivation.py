"""写入侧转换器：v1-in-memory → 字段级 facts（persistence-v2.md §1.3）。

采集器返回的是业务字段平铺的 mapping；EvidenceItem.facts 靠这条推导把它
转成 facts 再落盘。双读拆除后它**不消失**——消失的只是「读落盘时可能需要推导」
那个分支（见 evidence_projection.item_facts）。

覆盖 `p4a-fixture-shapes.md` §0 清点出的 9 种键集合各至少一例，外加 §3.1
标注的唯一有损项（availability 抹除）——那一条是字段级 support 存在的理由，
必须推导出 support=unknown 的 fact。
"""

from __future__ import annotations

import unittest

from trip_decider.evidence_core import (
    derive_facts,
    fact_id,
    normalized_retrieved_at,
)
from trip_decider.travel_agent import EvidenceItem, EvidenceStatus

STAMP = "2026-08-02T18:00:00+08:00"


def _by_field(facts) -> dict[str, dict]:
    return {str(f["field"]): dict(f) for f in facts}


class LossyCaseCase(unittest.TestCase):
    """§3.1 的唯一有损项：availability 抹除。"""

    def test_unknown_sentinel_becomes_a_field_level_unknown(self) -> None:
        facts = derive_facts(
            {
                "outbound": {
                    "train_code": "G100",
                    "departure_at": "2026-08-04T13:00",
                    "second_class_availability": "UNKNOWN",
                },
                "roundtrip_fare_cny": 800.0,
            },
            "railway-live-query",
            "railway",
            item_support="sourced",
            data_type="railway_schedule_fare",
            retrieved_at=STAMP,
        )
        by = _by_field(facts)
        # 同一条证据里，时刻可靠而余票未知——v1 的 item 级 support 表达不了。
        self.assertEqual("sourced", by["outbound.departure_at"]["support"])
        self.assertEqual("sourced", by["roundtrip_fare_cny"]["support"])
        self.assertEqual(
            "unknown", by["outbound.second_class_availability"]["support"]
        )
        self.assertIsNone(
            by["outbound.second_class_availability"]["value"],
            "不可知的字段不得保留旧值",
        )
        self.assertIn("reason", by["outbound.second_class_availability"])

    def test_none_leaf_is_unknown_too(self) -> None:
        facts = derive_facts(
            {"hotel_area": {"name": "住宿片区", "nightly_price_cny": None}},
            "web-live-profile",
            "web",
            item_support="sourced",
        )
        by = _by_field(facts)
        self.assertEqual("sourced", by["hotel_area.name"]["support"])
        self.assertEqual("unknown", by["hotel_area.nightly_price_cny"]["support"])

    def test_support_is_only_ever_lowered(self) -> None:
        """item 级为 unknown 时，任何叶子都不得升回去。"""

        facts = derive_facts(
            {"outbound": {"train_code": "G100"}},
            "railway-missing",
            "railway",
            item_support="unknown",
            reason="collector_error",
        )
        self.assertEqual({"unknown"}, {str(f["support"]) for f in facts})


class KeySetCoverageCase(unittest.TestCase):
    """p4a-fixture-shapes.md §0 的 9 种键集合。"""

    def _item(self, **overrides) -> EvidenceItem:
        base = {
            "evidence_id": "e1",
            "domain": "railway",
            "status": EvidenceStatus.SOURCED,
            "value": {"outbound": {"train_code": "G100"}},
            "sources": ({"provider": "p", "retrieved_at": STAMP},),
        }
        base.update(overrides)
        return EvidenceItem(**base)

    def test_1_full_seven_keys(self) -> None:
        item = self._item(missing_reason=None, conflict_details=())
        self.assertTrue(item.facts)

    def test_2_no_missing_reason(self) -> None:
        self.assertTrue(self._item().facts)

    def test_3_no_sources_with_missing_reason(self) -> None:
        item = self._item(
            status=EvidenceStatus.MISSING,
            value=None,
            sources=(),
            missing_reason="collector_error",
        )
        facts = item.facts
        self.assertEqual(1, len(facts))
        self.assertEqual("unknown", facts[0]["support"])
        self.assertEqual("collector_error", facts[0]["reason"])

    def test_4_conflicting_carries_details(self) -> None:
        item = self._item(
            status=EvidenceStatus.CONFLICTING,
            conflict_details=("来源A与来源B不一致",),
        )
        for fact in item.facts:
            self.assertEqual("conflicting", fact["support"])
            self.assertIn("conflict_details", fact)

    def test_5_estimated_propagates(self) -> None:
        item = self._item(status=EvidenceStatus.ESTIMATED)
        self.assertEqual({"estimated"}, {str(f["support"]) for f in item.facts})

    def test_6_confirmed_absent_stays_one_fact(self) -> None:
        """确认的否定是整体结论，不拆字段（evidence-axes.md §2.2.1）。"""

        item = self._item(
            value={
                "kind": "confirmed_absent",
                "scope": {"origin": "甲站", "window": "8-4~8-7"},
            }
        )
        facts = item.facts
        self.assertEqual(1, len(facts))
        self.assertEqual("confirmed_absent", facts[0]["value"]["kind"])
        self.assertEqual("sourced", facts[0]["support"])

    def test_7_nested_lists_expand_per_index(self) -> None:
        """两条路线是两个独立事实，可以有不同 support。"""

        item = self._item(
            domain="map",
            value={
                "local_transit": [
                    {"route_id": "r1", "duration_seconds": 1200},
                    {"route_id": "r2", "duration_seconds": None},
                ]
            },
        )
        by = _by_field(item.facts)
        self.assertEqual(
            "sourced", by["local_transit[0].duration_seconds"]["support"]
        )
        self.assertEqual(
            "unknown", by["local_transit[1].duration_seconds"]["support"]
        )

    def test_8_empty_value_yields_no_facts(self) -> None:
        self.assertEqual((), self._item(value={}).facts)

    def test_9_persisted_facts_are_read_directly(self) -> None:
        """落盘已带 facts 时直读，不再推导——这是双读的另一半。"""

        persisted = {
            "facts": [
                {
                    "fact_id": "e1#custom",
                    "field": "custom",
                    "value": 42,
                    "support": "estimated",
                }
            ]
        }
        item = self._item(value=persisted)
        facts = item.facts
        self.assertEqual(1, len(facts))
        self.assertEqual("e1#custom", facts[0]["fact_id"])
        self.assertEqual("estimated", facts[0]["support"])


class DerivationDetailCase(unittest.TestCase):
    def test_fact_id_follows_the_single_rule(self) -> None:
        facts = derive_facts(
            {"outbound": {"train_code": "G100"}}, "rail-1", "railway"
        )
        self.assertEqual(
            fact_id("rail-1", "outbound.train_code"), facts[0]["fact_id"]
        )

    def test_metadata_keys_never_become_facts(self) -> None:
        """取证元数据与展示态不是事实。"""

        facts = derive_facts(
            {
                "train_code": "G100",
                "snapshot": {"acquisition": "cache_fallback", "retrieved_at": STAMP},
                "schedule_status": "STALE",
                "support": "sourced",  # item 级元数据，不该成为 fact
                "refresh_failure": {"missing_reason": "rail_http"},
                "network_attempts": 3,
                "source": {"provider": "p"},
            },
            "e1",
            "railway",
        )
        self.assertEqual(["train_code"], [str(f["field"]) for f in facts])

    def test_retrieved_at_normalization_order(self) -> None:
        """§1.3.1：snapshot > freshness > value > source。"""

        self.assertEqual(
            "A",
            normalized_retrieved_at(
                {
                    "snapshot": {"retrieved_at": "A"},
                    "freshness": {"retrieved_at": "B"},
                    "retrieved_at": "C",
                },
                "D",
            ),
        )
        self.assertEqual(
            "B",
            normalized_retrieved_at(
                {"freshness": {"retrieved_at": "B"}, "retrieved_at": "C"}, "D"
            ),
        )
        self.assertEqual("C", normalized_retrieved_at({"retrieved_at": "C"}, "D"))
        self.assertEqual("D", normalized_retrieved_at({}, "D"))
        self.assertIsNone(normalized_retrieved_at({}, None))

    def test_every_fact_carries_the_required_shape(self) -> None:
        facts = derive_facts(
            {"a": 1, "b": {"c": 2}},
            "e1",
            "railway",
            data_type="railway_schedule_fare",
            retrieved_at=STAMP,
        )
        for fact in facts:
            for key in (
                "fact_id",
                "field",
                "value",
                "support",
                "data_type",
                "retrieved_at",
            ):
                self.assertIn(key, fact)
            self.assertEqual(STAMP, fact["retrieved_at"])


if __name__ == "__main__":
    unittest.main()
