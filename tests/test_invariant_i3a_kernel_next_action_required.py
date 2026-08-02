"""I3a（内核范围）：next_action 的双向约束与域校验。

契约：docs/contracts/invariants.md I3a
阶段：P2 转绿。读取层范围的 I3a 见
tests/test_invariant_i3a_next_action_required.py，登记为 P3a。

双向约束是必要的：只要求「非 verified 时必须有」而不要求「verified 时必须
没有」，UI 就无法用它的存在与否做渲染分支。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from trip_decider.evidence_core import (
    ACTORS,
    FRESHNESS_VALUES,
    EvidenceCoreError,
    FactInput,
    FreshnessPolicy,
    NEXT_ACTION_KINDS,
    REASON_CODES,
    SUPPORT_VALUES,
    SourceRef,
    TOKEN_VALUES,
    build_next_action,
    combine_token,
    evaluate_fact,
    validate_next_action,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
TOLERANCE = 21600

CRITICAL = FreshnessPolicy(
    data_type="railway_schedule_fare",
    tolerance_seconds=TOLERANCE,
    feasibility_critical=True,
    on_stale="auto_refetch",
)
NON_CRITICAL = FreshnessPolicy(
    data_type="poi_coordinate",
    tolerance_seconds=2592000,
    feasibility_critical=False,
    on_stale="flag_for_confirmation",
)

REQUIRED_FIELDS = (
    "kind",
    "field_ref",
    "data_type",
    "reason_code",
    "actor",
    "blocking",
    "detail",
)

# 见 test_invariant_i2_kernel_token_matches_support.py 中的同名常量：undated
# 必须用「有值但不可用」的时间戳构造，不能用缺失的时间戳。
_RETRIEVED_AT = {
    "fresh": (NOW - timedelta(seconds=TOLERANCE - 60)).isoformat(),
    "stale": (NOW - timedelta(seconds=TOLERANCE + 60)).isoformat(),
    "undated": "2026-08-02T12:00:00",
}


def _fact_for(support: str, freshness: str, data_type: str) -> FactInput:
    sources = (SourceRef("provider", retrieved_at=_RETRIEVED_AT[freshness]),)
    base: dict[str, object] = {
        "fact_id": f"fact-{support}-{freshness}",
        "data_type": data_type,
        "sources": sources,
        "value": {"departure_at": "2026-08-04T13:00"},
        "field_name": None,
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
        base["reason"] = "no_source_found"
    return FactInput(**base)  # type: ignore[arg-type]


class KernelNextActionRequiredCase(unittest.TestCase):
    def test_i3a_verified_facts_carry_no_next_action(self) -> None:
        verdict = evaluate_fact(_fact_for("sourced", "fresh", CRITICAL.data_type), CRITICAL, now=NOW)
        self.assertEqual("verified", verdict.token)
        self.assertIsNone(
            verdict.next_action, "有把握的事实不产生噪声（§5.1）"
        )

    def test_i3a_every_non_verified_token_carries_a_complete_next_action(
        self,
    ) -> None:
        for support in sorted(SUPPORT_VALUES):
            for freshness in sorted(FRESHNESS_VALUES):
                token = combine_token(support, freshness)
                if token == "verified":
                    continue
                with self.subTest(support=support, freshness=freshness):
                    verdict = evaluate_fact(
                        _fact_for(support, freshness, CRITICAL.data_type),
                        CRITICAL,
                        now=NOW,
                    )
                    action = verdict.next_action
                    self.assertIsNotNone(action, f"{token} 必须携带 next_action")
                    assert action is not None
                    for name in REQUIRED_FIELDS:
                        self.assertIn(name, action)
                    self.assertIn(action["kind"], NEXT_ACTION_KINDS)
                    self.assertIn(action["reason_code"], REASON_CODES)
                    self.assertIn(action["actor"], ACTORS)
                    self.assertIsInstance(action["blocking"], bool)
                    self.assertTrue(str(action["detail"]).strip())

    def test_i3a_validator_enforces_both_directions(self) -> None:
        action = build_next_action(
            token="unknown",
            field_ref="fact-x",
            data_type="railway_schedule_fare",
            support="unknown",
            freshness="fresh",
            feasibility_critical=True,
            reason="no_source_found",
        )
        validate_next_action(action, token="unknown")

        with self.assertRaises(EvidenceCoreError):
            validate_next_action(action, token="verified")
        with self.assertRaises(EvidenceCoreError):
            validate_next_action(None, token="unknown")
        validate_next_action(None, token="verified")

    def test_i3a_every_enum_field_is_domain_checked(self) -> None:
        base = build_next_action(
            token="sourced_stale",
            field_ref="fact-x",
            data_type="railway_schedule_fare",
            support="sourced",
            freshness="stale",
            feasibility_critical=True,
        )
        assert base is not None
        corruptions = {
            "kind": "please_retry",
            "reason_code": "because_i_said_so",
            "actor": "robot",
            "blocking": "yes",
            "detail": "",
            "field_ref": "   ",
            "data_type": "",
        }
        for name, bad_value in corruptions.items():
            with self.subTest(field=name):
                corrupted = dict(base)
                corrupted[name] = bad_value
                with self.assertRaises(EvidenceCoreError):
                    validate_next_action(corrupted, token="sourced_stale")

        for name in REQUIRED_FIELDS:
            with self.subTest(missing=name):
                incomplete = {k: v for k, v in base.items() if k != name}
                with self.assertRaises(EvidenceCoreError):
                    validate_next_action(incomplete, token="sourced_stale")

    def test_i3a_user_choice_requires_non_empty_options(self) -> None:
        verdict = evaluate_fact(
            _fact_for("conflicting", "fresh", CRITICAL.data_type),
            CRITICAL,
            now=NOW,
        )
        action = verdict.next_action
        assert action is not None
        self.assertEqual("user_choice", action["kind"])
        self.assertTrue(action["options"], "conflicting 必须给出可裁决的候选")
        for option in action["options"]:
            self.assertTrue(str(option["option_id"]).strip())
            self.assertTrue(str(option["label"]).strip())

        for bad in ([], "not-a-list", None):
            with self.subTest(options=bad):
                corrupted = dict(action)
                corrupted["options"] = bad
                with self.assertRaises(EvidenceCoreError):
                    validate_next_action(corrupted, token="conflicting")

    def test_i3a_options_and_retry_after_at_are_kind_scoped(self) -> None:
        stale = build_next_action(
            token="sourced_stale",
            field_ref="fact-x",
            data_type="railway_schedule_fare",
            support="sourced",
            freshness="stale",
            feasibility_critical=True,
            retry_after_at="2026-08-02T13:00:00+08:00",
        )
        assert stale is not None
        self.assertEqual("auto_refetch", stale["kind"])
        validate_next_action(stale, token="sourced_stale")

        with_options = dict(stale)
        with_options["options"] = [{"option_id": "a", "label": "A"}]
        with self.assertRaises(EvidenceCoreError):
            validate_next_action(with_options, token="sourced_stale")

        naive_retry = dict(stale)
        naive_retry["retry_after_at"] = "2026-08-02T13:00:00"
        with self.assertRaises(EvidenceCoreError):
            validate_next_action(naive_retry, token="sourced_stale")

    def test_i3a_blocking_follows_feasibility_critical(self) -> None:
        critical = evaluate_fact(
            _fact_for("unknown", "fresh", CRITICAL.data_type), CRITICAL, now=NOW
        )
        ordinary = evaluate_fact(
            _fact_for("unknown", "fresh", NON_CRITICAL.data_type),
            NON_CRITICAL,
            now=NOW,
        )
        assert critical.next_action is not None
        assert ordinary.next_action is not None
        self.assertTrue(critical.next_action["blocking"])
        self.assertFalse(ordinary.next_action["blocking"])

    def test_i3a_reason_code_prefers_the_freshness_side(self) -> None:
        """§5.2 末段：两轴同时非理想时取 freshness 侧的值。"""

        verdict = evaluate_fact(
            _fact_for("estimated", "stale", CRITICAL.data_type), CRITICAL, now=NOW
        )
        assert verdict.next_action is not None
        self.assertEqual(
            "beyond_tolerance_window",
            verdict.next_action["reason_code"],
            "support 侧（estimated）本身不需要行动，行动由超窗驱动",
        )

    def test_i3a_holds_for_every_token_in_the_vocabulary(self) -> None:
        """穷举 8 个 token，逐个核对双向约束。"""

        covered: set[str] = set()
        for support in sorted(SUPPORT_VALUES):
            for freshness in sorted(FRESHNESS_VALUES):
                token = combine_token(support, freshness)
                covered.add(token)
                verdict = evaluate_fact(
                    _fact_for(support, freshness, CRITICAL.data_type),
                    CRITICAL,
                    now=NOW,
                )
                validate_next_action(verdict.next_action, token=verdict.token)
        self.assertEqual(TOKEN_VALUES, covered)


if __name__ == "__main__":
    unittest.main()
