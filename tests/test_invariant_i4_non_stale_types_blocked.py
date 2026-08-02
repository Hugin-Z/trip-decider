"""I4: stale_allowed=False 的 data_type 不得以缓存值参与可行性判定。

契约：docs/contracts/invariants.md I4
预期转绿：P5

按裁决 2，当前 stale_allowed=False 的只剩 hotel_price；seat_availability
已从登记表删除（属订票域）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from trip_decider.evidence_broker import EvidenceBroker, evidence_query
from trip_decider.travel_agent import EvidenceItem, EvidenceStatus

from tests.invariant_support import parse_policy_registry, scan_produced_data_types


def _non_stale_data_types() -> list[str]:
    return sorted(
        name
        for name, policy in parse_policy_registry().items()
        if not policy["stale_allowed"]
    )


class NonStaleTypesBlockedCase(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
        self.non_stale = _non_stale_data_types()
        self.assertTrue(
            self.non_stale,
            "前置条件不满足：登记表中没有 stale_allowed=False 的 data_type",
        )

    def _query(self, data_type: str) -> object:
        return evidence_query(
            provider="controlled-provider",
            origin="甲地",
            destination="乙地",
            query_parameters={"travelers": 2},
            earliest_departure_at="2026-08-04T12:00:00+08:00",
            latest_return_at="2026-08-07T22:00:00+08:00",
            data_type=data_type,
        )

    def test_i4_cache_layer_never_returns_a_non_stale_type(self) -> None:
        """第 1 条：缓存层不返回该记录。当前已成立。"""

        for data_type in self.non_stale:
            with self.subTest(data_type=data_type):
                broker = EvidenceBroker(clock=lambda: self.now)
                query = self._query(data_type)
                broker.publish(
                    run_id="seed-run",
                    query=query,
                    evidence=EvidenceItem(
                        evidence_id="seed",
                        domain="web",
                        status=EvidenceStatus.SOURCED,
                        value={"price_cny": 400},
                        sources=(
                            {
                                "provider": "controlled-provider",
                                "retrieved_at": (
                                    self.now - timedelta(minutes=1)
                                ).isoformat(),
                            },
                        ),
                    ),
                    collected_at=(self.now - timedelta(minutes=1)).isoformat(),
                )
                reused = broker.stale_after_failure(
                    run_id="fresh-run",
                    query=query,
                    live_failure=EvidenceItem(
                        evidence_id="live-failure",
                        domain="web",
                        status=EvidenceStatus.MISSING,
                        value=None,
                        missing_reason="collector_error",
                    ),
                )
                self.assertIsNone(reused)

    def test_i4_non_stale_type_reaches_feasibility_as_unknown(self) -> None:
        """第 2、3 条：读取层判 unknown 且可行性结论不得无条件可行。"""

        registry = parse_policy_registry()
        produced = scan_produced_data_types(known=frozenset(registry))
        without_producer = [
            data_type
            for data_type in self.non_stale
            if data_type not in produced
        ]
        self.assertEqual(
            [],
            without_producer,
            "阻塞于 P5：以下 stale_allowed=False 的 data_type 在 src/ 中"
            f"没有生产者，无法构造端到端场景：{without_producer}。"
            "hotel_price 的 status 为 planned（planned_for=P5，见 "
            "freshness-policy.md §2.2 注 2），生产者落地后本用例才能执行"
            "第 2、3 条断言。",
        )


if __name__ == "__main__":
    unittest.main()
