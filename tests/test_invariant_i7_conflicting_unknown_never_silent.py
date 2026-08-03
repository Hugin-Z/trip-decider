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


def _rejected_entry(result: dict) -> dict:
    """退回区的第一条。空退回区即为**信息消失**——I7 第 4 条要防的正是它。"""

    rejected = result.get("rejected_candidates")
    assert isinstance(rejected, list) and rejected, (
        "被拦下的候选没有进退回区，直接消失了——I7 第 4 条不成立"
    )
    return rejected[0]


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

        # 第 4 条（准入过滤形态）：conflicting 的铁路证据支撑不了「这趟能不能
        # 成行」，候选因此不进入选区——但**不是消失**，它进退回区。
        result = _compare(conflicting)
        entry = _rejected_entry(result)

        self.assertEqual(
            [],
            result["options"],
            "conflicting 的铁路证据不该产出可行候选",
        )
        self.assertEqual(
            "conflicting",
            str(entry["token"]),
            "conflicting 证据在退回项上被折叠成了另一个 token，第 3 条不成立",
        )
        self.assertTrue(entry.get("reason"), "退回项没有 reason")
        self.assertTrue(entry.get("next_action"), "退回项没有 next_action")

    def test_i7_conflict_details_survive_to_the_caller(self) -> None:
        def conflicting(_intent: TravelIntent) -> EvidenceItem:
            return EvidenceItem(
                evidence_id="conflicting-railway",
                domain="railway",
                status=EvidenceStatus.CONFLICTING,
                value={"retrieved_at": "2026-08-02T09:00:00+08:00"},
                conflict_details=("两个来源给出不同的到达时刻",),
            )

        # 候选被准入过滤拦下之后，conflict_details 必须在**退回区**可见——
        # 信息换了位置不算消失，换没了才算。
        result = _compare(conflicting)
        serialized = repr(result["rejected_candidates"])
        self.assertIn(
            "两个来源给出不同的到达时刻",
            serialized,
            "conflict_details 未出现在退回区，"
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

        # 第 4 条的判定方法（`invariants.md` I7）：构造一个 railway 为 unknown
        # 的候选，断言它**出现在 rejected_candidates 而不是消失**，且 token
        # 原样为 unknown。
        result = _compare(missing)
        entry = _rejected_entry(result)

        self.assertEqual(
            [],
            result["options"],
            "查不到车次的目的地进了候选集——裁决 1 的准入门槛没生效",
        )
        self.assertEqual(
            "unknown",
            str(entry["token"]),
            "unknown 证据在退回项上被折叠成了另一个 token",
        )
        self.assertTrue(entry.get("reason"), "退回项没有 reason")
        self.assertTrue(entry.get("next_action"), "退回项没有 next_action")
        self.assertTrue(
            result.get("no_feasible_candidates"),
            "全部候选被拦下时没有如实报「无可行候选」",
        )
        self.assertTrue(
            result.get("relaxation_hint"),
            "无可行候选时没有给放松建议——那会让用户无从下手",
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
