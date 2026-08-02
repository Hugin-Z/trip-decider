"""I2（内核范围）：token 与两轴精确对应。

契约：docs/contracts/invariants.md I2
阶段：P2 转绿。读取层范围的 I2 见
tests/test_invariant_i2_token_matches_support.py，登记为 P3a。

I2 的断言形式是**精确相等**而非「不高于」的偏序比较：
``token_support(token) == 聚合后的 support`` 且
``token_freshness(token) == 按 now 算出的 freshness``。
精确相等是更强的条件，且不需要定义一个有争议的全序。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from trip_decider.evidence_core import (
    FRESHNESS_VALUES,
    FactInput,
    FreshnessPolicy,
    SUPPORT_VALUES,
    SourceRef,
    SupportVerdict,
    aggregate_freshness,
    aggregate_support,
    combine_token,
    compute_freshness,
    confirmed_absent,
    evaluate_fact,
    token_freshness,
    token_support,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
TOLERANCE = 21600  # railway_schedule_fare, freshness-policy.md §2.2

POLICY = FreshnessPolicy(
    data_type="railway_schedule_fare",
    tolerance_seconds=TOLERANCE,
    feasibility_critical=True,
    on_stale="auto_refetch",
)

# docs/contracts/evidence-axes.md §4.1 的 8 token 表，在测试里独立写一遍。
# 若内核改了映射而这张表没改，测试会红——这正是要防的。
EXPECTED_TOKENS = {
    ("sourced", "fresh"): "verified",
    ("sourced", "stale"): "sourced_stale",
    ("sourced", "undated"): "sourced_undated",
    ("estimated", "fresh"): "estimated",
    ("estimated", "stale"): "estimated_stale",
    ("estimated", "undated"): "estimated_undated",
    ("conflicting", "fresh"): "conflicting",
    ("conflicting", "stale"): "conflicting",
    ("conflicting", "undated"): "conflicting",
    ("unknown", "fresh"): "unknown",
    ("unknown", "stale"): "unknown",
    ("unknown", "undated"): "unknown",
}

# undated 用的是「有值但不可用」的时间戳（无时区），不是缺失的时间戳。
# 缺失会让 §2.2 序 4 不成立而落到序 5 兜底，产出 unknown 而非 sourced_undated
# ——见 evidence-axes.md §4.1 的可达性说明。
_RETRIEVED_AT = {
    "fresh": (NOW - timedelta(seconds=TOLERANCE - 60)).isoformat(),
    "stale": (NOW - timedelta(seconds=TOLERANCE + 60)).isoformat(),
    "undated": "2026-08-02T12:00:00",
}


def _fact_for(support: str, freshness: str) -> FactInput:
    """构造一个目标 (support, freshness) 的事实。

    构造只使用 §2.1 的判定输入；token 不作为输入出现，必须由内核算出。
    """

    retrieved_at = _RETRIEVED_AT[freshness]
    sources = (SourceRef("中国铁路12306", retrieved_at=retrieved_at),)
    base: dict[str, object] = {
        "fact_id": f"fact-{support}-{freshness}",
        "data_type": "railway_schedule_fare",
        "sources": sources,
        "value": {"departure_at": "2026-08-04T13:00"},
    }
    if support == "sourced":
        base["derivation"] = "direct_observation"
    elif support == "estimated":
        base["derivation"] = "api_estimate"
    elif support == "conflicting":
        base["derivation"] = "direct_observation"
        base["conflict_details"] = ("来源A说13:00", "来源B说13:40")
        base["conflict_source_refs"] = ("source-a", "source-b")
    else:
        base["value"] = None
        base["reason"] = "collector_error"
    return FactInput(**base)  # type: ignore[arg-type]


class KernelTokenMatchesSupportCase(unittest.TestCase):
    def test_i2_every_axis_combination_maps_to_the_contracted_token(
        self,
    ) -> None:
        """12 种组合逐个核对 §4.1 表。"""

        for (support, freshness), expected in sorted(EXPECTED_TOKENS.items()):
            with self.subTest(support=support, freshness=freshness):
                self.assertEqual(expected, combine_token(support, freshness))

    def test_i2_end_to_end_evaluation_matches_both_components(self) -> None:
        """从判定输入出发走完整门面，再分解回两轴，必须精确相等。"""

        for (support, freshness), expected in sorted(EXPECTED_TOKENS.items()):
            with self.subTest(support=support, freshness=freshness):
                verdict = evaluate_fact(_fact_for(support, freshness), POLICY, now=NOW)
                self.assertEqual(support, verdict.support)
                self.assertEqual(freshness, verdict.freshness)
                self.assertEqual(expected, verdict.token)
                self.assertEqual(support, token_support(verdict.token))
                decomposed = token_freshness(verdict.token)
                if decomposed is not None:
                    self.assertEqual(freshness, decomposed)

    def test_i2_unusable_evidence_is_never_displayed_as_available(self) -> None:
        """基线报告 §3.4 的缺陷方向：采集失败不得比缺席更乐观。"""

        failed = evaluate_fact(_fact_for("unknown", "fresh"), POLICY, now=NOW)
        self.assertEqual("unknown", failed.token)
        self.assertNotEqual("verified", failed.token)

    def test_i2_aggregated_facts_match_their_aggregated_axes(self) -> None:
        """派生事实：聚合后的两轴与 token 必须精确相等。"""

        cases = [
            (["sourced", "sourced"], False, "sourced"),
            (["sourced", "sourced"], True, "estimated"),
            (["sourced", "estimated"], False, "estimated"),
            (["sourced", "unknown"], False, "unknown"),
            (["sourced", "conflicting", "unknown"], False, "conflicting"),
        ]
        for supports, derived, expected_support in cases:
            for freshnesses, expected_freshness in (
                (["fresh", "fresh"], "fresh"),
                (["fresh", "stale"], "stale"),
                (["fresh", "undated"], "undated"),
            ):
                with self.subTest(supports=supports, derived=derived):
                    aggregate = aggregate_support(
                        [SupportVerdict(value, "x") for value in supports],
                        derivation_occurred=derived,
                    )
                    freshness = aggregate_freshness(freshnesses)
                    token = combine_token(aggregate.support, freshness)
                    self.assertEqual(expected_support, aggregate.support)
                    self.assertEqual(expected_freshness, freshness)
                    self.assertEqual(aggregate.support, token_support(token))

    def test_i2_confirmed_absent_is_verified_not_unknown(self) -> None:
        """确认的否定是结论。P1 意外发现 1 的修正。"""

        fact = FactInput(
            fact_id="fact-no-direct-train",
            data_type="railway_schedule_fare",
            value=confirmed_absent(
                {
                    "origin": "甲站",
                    "destination": "乙站",
                    "window": "2026-08-04~2026-08-07",
                }
            ),
            derivation="official_report",
            sources=(
                SourceRef("中国铁路12306", retrieved_at=_RETRIEVED_AT["fresh"]),
            ),
        )
        verdict = evaluate_fact(fact, POLICY, now=NOW)
        self.assertEqual("sourced", verdict.support)
        self.assertEqual("verified", verdict.token)
        self.assertTrue(verdict.confirmed_absent)

    def test_i2_freshness_is_a_function_of_the_injected_now(self) -> None:
        """同一份证据在两个读取时刻产出不同 freshness——I5 的内核前提。"""

        retrieved_at = (NOW - timedelta(seconds=TOLERANCE - 60)).isoformat()
        early = compute_freshness(
            retrieved_at, now=NOW, tolerance_seconds=TOLERANCE
        )
        later = compute_freshness(
            retrieved_at,
            now=NOW + timedelta(seconds=120),
            tolerance_seconds=TOLERANCE,
        )
        self.assertEqual("fresh", early)
        self.assertEqual("stale", later)

    def test_i2_token_vocabulary_is_closed(self) -> None:
        produced = {
            combine_token(support, freshness)
            for support in SUPPORT_VALUES
            for freshness in FRESHNESS_VALUES
        }
        self.assertEqual(set(EXPECTED_TOKENS.values()), produced)


if __name__ == "__main__":
    unittest.main()
