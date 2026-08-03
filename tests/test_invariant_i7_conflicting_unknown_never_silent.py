"""I7: conflicting 与 unknown 不得静默进入硬约束判定。

契约：docs/contracts/invariants.md I7
预期转绿：P5

覆盖判定点 1（候选 feasibility_status，guided_discovery.py:520-536）。
含裁决 5 的扩展分支：estimated 可以参与判定，但必须至少产生一个 conditional。
"""

from __future__ import annotations

from datetime import datetime, timezone
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

_UNCONDITIONAL = frozenset({"FEASIBLE", "PLAN_READY"})


def _intent() -> TravelIntent:
    return TravelIntent.from_mapping(
        {
            "task_mode": "GUIDED_DISCOVERY",
            "origin": "甲地",
            "destination_anchor": "某区域",
            "earliest_departure_at": "2026-08-04T12:00:00",
            "latest_return_at": "2026-08-07T22:00:00",
            "travelers": 2,
            "total_budget_cny": 6000,
        }
    )


def _compare(collector: object) -> dict[str, object]:
    broker = EvidenceBroker(
        clock=lambda: datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    )
    with patch(
        "trip_decider.guided_discovery.guided_region_seeds",
        return_value=_SEEDS,
    ):
        return build_guided_comparison(
            _intent(),
            railway_collector=collector,
            run_id="invariant-i7",
            evidence_broker=broker,
            clock=lambda: datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
        )


def _railway_status(option: dict[str, object]) -> str:
    statuses = option["evidence_statuses"]
    entry = next(item for item in statuses if item["domain"] == "railway")
    return str(entry["token"])


class ConflictingUnknownNeverSilentCase(unittest.TestCase):
    def test_i7_conflicting_evidence_stays_conflicting(self) -> None:
        def conflicting(_intent: TravelIntent) -> EvidenceItem:
            return EvidenceItem(
                evidence_id="conflicting-railway",
                domain="railway",
                status=EvidenceStatus.CONFLICTING,
                value={"retrieved_at": "2026-08-02T09:00:00+08:00"},
                conflict_details=("两个来源给出不同的到达时刻",),
            )

        option = _compare(conflicting)["options"][0]

        self.assertNotIn(
            str(option["feasibility_status"]),
            _UNCONDITIONAL,
            "conflicting 输入产出了无条件可行结论",
        )
        self.assertEqual(
            "conflicting",
            _railway_status(option),
            "conflicting 证据被折叠为另一个展示态"
            "（guided_discovery.py:595-599 的 else 分支把 CONFLICTING "
            "映射为 MISSING），第 3 条不成立",
        )

    def test_i7_conflict_details_survive_to_the_caller(self) -> None:
        def conflicting(_intent: TravelIntent) -> EvidenceItem:
            return EvidenceItem(
                evidence_id="conflicting-railway",
                domain="railway",
                status=EvidenceStatus.CONFLICTING,
                value={"retrieved_at": "2026-08-02T09:00:00+08:00"},
                conflict_details=("两个来源给出不同的到达时刻",),
            )

        option = _compare(conflicting)["options"][0]
        serialized = repr(option)
        self.assertIn(
            "两个来源给出不同的到达时刻",
            serialized,
            "conflict_details 未出现在对外返回值中"
            "（guided_discovery.py:548-590 的返回体没有该字段），"
            "用户无从知道两个来源在哪一点上打架",
        )

    def test_i7_unknown_evidence_stays_unknown(self) -> None:
        def missing(_intent: TravelIntent) -> EvidenceItem:
            return EvidenceItem(
                evidence_id="missing-railway",
                domain="railway",
                status=EvidenceStatus.MISSING,
                value=None,
                missing_reason="collector_error",
            )

        option = _compare(missing)["options"][0]

        self.assertNotIn(
            str(option["feasibility_status"]),
            _UNCONDITIONAL,
            "unknown 输入产出了无条件可行结论",
        )
        self.assertEqual(
            "unknown",
            _railway_status(option),
            "unknown 证据的展示态不是 unknown",
        )

    def test_i7_estimated_input_produces_at_least_one_conditional(self) -> None:
        """裁决 5 的扩展分支：estimated 可参与判定，但必须携带 conditional。

        直接用例，不靠 hasattr 间接推断——构造一条 estimated 铁路证据，跑完
        判定点 1，断言结论可行**且**结论上挂着一条条件说明。
        """

        def estimated(_intent: TravelIntent) -> EvidenceItem:
            return EvidenceItem(
                evidence_id="estimated-railway",
                domain="railway",
                status=EvidenceStatus.ESTIMATED,
                value={
                    "retrieved_at": "2026-08-02T18:00:00+08:00",
                    "roundtrip_duration_seconds": 21600,
                    "roundtrip_fare_cny": 800.0,
                    "snapshot": {
                        "acquisition": "live_fetch",
                        "retrieved_at": "2026-08-02T18:00:00+08:00",
                    },
                },
                sources=(
                    {
                        "provider": "controlled-rail",
                        "retrieved_at": "2026-08-02T18:00:00+08:00",
                    },
                ),
            )

        option = _compare(estimated)["options"][0]

        self.assertEqual(
            "estimated",
            _railway_status(option),
            "estimated 证据没有以 estimated 呈现",
        )
        self.assertEqual(
            "CONDITIONALLY_FEASIBLE",
            str(option["feasibility_status"]),
            "裁决 5：estimated 可以参与判定，不应被拦成 UNKNOWN",
        )
        self.assertTrue(
            option.get("conditions"),
            "裁决 5：estimated 输入必须至少产生一个 conditional，"
            "否则推算值会被当作确定值使用",
        )


if __name__ == "__main__":
    unittest.main()
