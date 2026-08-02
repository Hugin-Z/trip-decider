"""证据内核的单元测试与硬边界核对。

契约：docs/contracts/evidence-axes.md
阶段闸门：PLAN.md v4 §12 的 P2
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from trip_decider.evidence_core import (
    ACTORS,
    CONFIRMED_ABSENT_KIND,
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    FRESHNESS_UNDATED,
    FRESHNESS_VALUES,
    EvidenceCoreError,
    FactInput,
    FreshnessPolicy,
    NEXT_ACTION_KINDS,
    REASON_CODES,
    SUPPORT_VALUES,
    SourceRef,
    SupportVerdict,
    TOKEN_VALUES,
    aggregate_freshness,
    aggregate_support,
    combine_token,
    classify_support,
    compute_freshness,
    confirmed_absent,
    evaluate_fact,
    is_confirmed_absent,
    parse_timestamp,
    resolve_freshness,
    token_freshness,
    token_support,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
KERNEL_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "trip_decider"
    / "evidence_core.py"
)
POLICY = FreshnessPolicy(
    data_type="railway_schedule_fare",
    tolerance_seconds=21600,
    feasibility_critical=True,
    on_stale="auto_refetch",
)


def _at(**delta: float) -> str:
    return (NOW - timedelta(**delta)).isoformat()


def _fact(**overrides: object) -> FactInput:
    base: dict[str, object] = {
        "fact_id": "fact-under-test",
        "data_type": "railway_schedule_fare",
    }
    base.update(overrides)
    return FactInput(**base)  # type: ignore[arg-type]


def _sourced(**overrides: object) -> FactInput:
    base: dict[str, object] = {
        "value": {"departure_at": "2026-08-04T13:00"},
        "derivation": "direct_observation",
        "sources": (SourceRef("中国铁路12306", retrieved_at=_at(hours=1)),),
    }
    base.update(overrides)
    return _fact(**base)


class HardBoundaryCase(unittest.TestCase):
    """P2 闸门 1、2：零 I/O、不 import 产品模块。"""

    def setUp(self) -> None:
        self.tree = ast.parse(KERNEL_PATH.read_text(encoding="utf-8"))

    def test_kernel_imports_only_the_standard_library(self) -> None:
        stdlib_roots = {"collections", "dataclasses", "datetime", "types", "typing"}
        imported: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.level:
                    self.fail(f"内核使用了相对 import：{node.module}")
                imported.add(node.module.split(".")[0])
        forbidden = sorted(imported - stdlib_roots - {"__future__"})
        self.assertEqual(
            [],
            forbidden,
            f"内核 import 了非标准库模块：{forbidden}。"
            "依赖方向必须单向——产品依赖内核，内核不依赖产品。",
        )

    def test_kernel_performs_no_io(self) -> None:
        banned_names = {"open", "input", "print"}
        banned_attributes = {
            "now",
            "today",
            "utcnow",
            "read_text",
            "write_text",
            "read_bytes",
            "write_bytes",
            "urlopen",
            "monotonic",
            "time",
        }
        hits: list[str] = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if isinstance(target, ast.Name) and target.id in banned_names:
                hits.append(f"{target.id}() @ line {node.lineno}")
            elif (
                isinstance(target, ast.Attribute)
                and target.attr in banned_attributes
            ):
                hits.append(f".{target.attr}() @ line {node.lineno}")
        self.assertEqual(
            [],
            hits,
            f"内核出现了 I/O 或读时钟调用：{hits}。"
            "now 必须由调用方注入。",
        )


class SupportClassificationCase(unittest.TestCase):
    """§2.2 的五序判定。"""

    def test_s1_unknown_when_no_conclusion(self) -> None:
        for label, fact in (
            ("value 缺失", _fact(value=None, reason="collector_timeout")),
            (
                "字段不在 value 中",
                _fact(
                    value={"other": 1},
                    field_name="departure_at",
                    derivation="direct_observation",
                    sources=(SourceRef("p", retrieved_at=_at(hours=1)),),
                ),
            ),
        ):
            with self.subTest(label):
                self.assertEqual("unknown", classify_support(fact).support)

    def test_s2_conflicting_outranks_estimated(self) -> None:
        """来源分歧时即使一方是推算值，结果仍是 conflicting。"""

        verdict = classify_support(
            _fact(
                value={"departure_at": "14:00"},
                derivation="api_estimate",
                sources=(SourceRef("p", retrieved_at=_at(hours=1)),),
                conflict_details=("来源A说14:00", "来源B说15:10"),
                conflict_source_refs=("source-a", "source-b"),
            )
        )
        self.assertEqual("conflicting", verdict.support)
        self.assertEqual("sources_disagree", verdict.reason)

    def test_s2_conflicting_requires_two_source_refs(self) -> None:
        with self.assertRaises(EvidenceCoreError):
            classify_support(
                _fact(
                    value={"x": 1},
                    conflict_details=("分歧",),
                    conflict_source_refs=("only-one",),
                )
            )

    def test_s3_estimated_covers_every_derivation_variant(self) -> None:
        for derivation in ("api_estimate", "model_estimate", "rule_derived"):
            with self.subTest(derivation=derivation):
                verdict = classify_support(
                    _fact(
                        value={"duration_seconds": 1800},
                        derivation=derivation,
                        sources=(SourceRef("p", retrieved_at=_at(hours=1)),),
                    )
                )
                self.assertEqual("estimated", verdict.support)

    def test_s4_sourced_requires_complete_sources(self) -> None:
        without_retrieved_at = _sourced(sources=(SourceRef("provider"),))
        self.assertEqual(
            "unknown",
            classify_support(without_retrieved_at).support,
            "缺 retrieved_at 的来源不满足序 4，应落到序 5 兜底",
        )
        self.assertEqual("sourced", classify_support(_sourced()).support)

    def test_s5_fallback_reports_classification_failed(self) -> None:
        verdict = classify_support(_fact(value={"x": 1}, derivation=None))
        self.assertEqual("unknown", verdict.support)
        self.assertEqual("classification_failed", verdict.reason)


class ConfirmedAbsentCase(unittest.TestCase):
    """§2.2.1 / §2.2.2：来源明确给出的负结果。"""

    def test_confirmed_absent_requires_a_non_empty_scope(self) -> None:
        for bad in ({}, None, "no trains"):
            with self.subTest(scope=bad):
                with self.assertRaises(EvidenceCoreError):
                    confirmed_absent(bad)  # type: ignore[arg-type]

    def test_confirmed_absent_is_mechanically_distinguishable(self) -> None:
        absent = confirmed_absent({"origin": "甲站", "window": "2026-08-04"})
        self.assertTrue(is_confirmed_absent(absent))
        for present in ({"kind": "other"}, {"departure_at": "13:00"}, None, 0, []):
            with self.subTest(value=present):
                self.assertFalse(is_confirmed_absent(present))

    def test_confirmed_absent_is_sourced_not_unknown(self) -> None:
        """P1 意外发现 1：确认的否定是结论，不是不确定。"""

        verdict = classify_support(
            _sourced(
                value=confirmed_absent(
                    {"origin": "甲站", "destination": "乙站", "window": "8-4~8-7"}
                ),
                derivation="official_report",
            )
        )
        self.assertEqual("sourced", verdict.support)
        self.assertTrue(verdict.confirmed_absent)

    def test_confirmed_absent_fresh_renders_as_verified_without_action(
        self,
    ) -> None:
        verdict = evaluate_fact(
            _sourced(
                value=confirmed_absent({"window": "8-4~8-7"}),
                derivation="official_report",
            ),
            POLICY,
            now=NOW,
        )
        self.assertEqual("verified", verdict.token)
        self.assertTrue(verdict.confirmed_absent)
        self.assertIsNone(
            verdict.next_action,
            "「确认没有直达车」不需要证据行动指引；改换乘或改日期是规划决策",
        )

    def test_confirmed_absent_propagates_through_aggregation(self) -> None:
        aggregate = aggregate_support(
            [
                SupportVerdict("sourced", "s4", confirmed_absent=True),
                SupportVerdict("sourced", "s4"),
            ],
            derivation_occurred=False,
            input_fact_ids=("a", "b"),
        )
        self.assertEqual("sourced", aggregate.support)
        self.assertTrue(
            aggregate.confirmed_absent,
            "§2.2.2：任一输入 confirmed_absent 则派生事实吸收该标志",
        )
        self.assertEqual(("a", "b"), aggregate.input_fact_ids)


class FreshnessCase(unittest.TestCase):
    """§3.2。"""

    def test_boundary_is_inclusive(self) -> None:
        exactly_at_window = compute_freshness(
            _at(seconds=21600), now=NOW, tolerance_seconds=21600
        )
        one_second_past = compute_freshness(
            _at(seconds=21601), now=NOW, tolerance_seconds=21600
        )
        self.assertEqual(FRESHNESS_FRESH, exactly_at_window)
        self.assertEqual(FRESHNESS_STALE, one_second_past)

    def test_future_timestamps_are_undated_not_fresh(self) -> None:
        future = (NOW + timedelta(hours=1)).isoformat()
        self.assertEqual(
            FRESHNESS_UNDATED,
            compute_freshness(future, now=NOW, tolerance_seconds=21600),
            "未来时间戳是数据错误，不得被当作最新",
        )

    def test_naive_and_unparsable_timestamps_are_undated(self) -> None:
        for value in ("2026-08-02T12:00:00", "", None, "not-a-date", 12345):
            with self.subTest(value=value):
                self.assertEqual(
                    FRESHNESS_UNDATED,
                    compute_freshness(value, now=NOW, tolerance_seconds=21600),
                )

    def test_zero_tolerance_makes_everything_but_now_stale(self) -> None:
        self.assertEqual(
            FRESHNESS_STALE,
            compute_freshness(_at(seconds=1), now=NOW, tolerance_seconds=0),
        )

    def test_now_must_be_timezone_aware(self) -> None:
        with self.assertRaises(EvidenceCoreError):
            compute_freshness(
                _at(hours=1),
                now=datetime(2026, 8, 2, 12, 0),
                tolerance_seconds=0,
            )

    def test_parse_timestamp_accepts_zulu_suffix(self) -> None:
        self.assertIsNotNone(parse_timestamp("2026-08-02T12:00:00Z"))
        self.assertIsNone(parse_timestamp("2026-08-02T12:00:00"))

    def test_aggregate_freshness_takes_the_worst(self) -> None:
        self.assertEqual(
            FRESHNESS_UNDATED,
            aggregate_freshness([FRESHNESS_FRESH, FRESHNESS_UNDATED, FRESHNESS_STALE]),
        )
        self.assertEqual(
            FRESHNESS_STALE, aggregate_freshness([FRESHNESS_FRESH, FRESHNESS_STALE])
        )
        self.assertEqual(
            FRESHNESS_FRESH, aggregate_freshness([FRESHNESS_FRESH, FRESHNESS_FRESH])
        )


class TokenAlgebraCase(unittest.TestCase):
    """§4.1 / §4.3。"""

    def test_every_axis_pair_maps_to_a_token(self) -> None:
        produced = {
            combine_token(support, freshness)
            for support in SUPPORT_VALUES
            for freshness in FRESHNESS_VALUES
        }
        self.assertEqual(TOKEN_VALUES, produced)
        self.assertEqual(8, len(TOKEN_VALUES))

    def test_decomposition_recovers_the_support_component(self) -> None:
        for support in SUPPORT_VALUES:
            for freshness in FRESHNESS_VALUES:
                with self.subTest(support=support, freshness=freshness):
                    token = combine_token(support, freshness)
                    self.assertEqual(support, token_support(token))

    def test_conflicting_and_unknown_absorb_freshness(self) -> None:
        for support in ("conflicting", "unknown"):
            tokens = {
                combine_token(support, freshness)
                for freshness in FRESHNESS_VALUES
            }
            self.assertEqual(1, len(tokens))
            self.assertIsNone(token_freshness(tokens.pop()))

    def test_freshness_never_upgrades_support(self) -> None:
        """estimated 无论多新鲜都不会变成 verified。"""

        for freshness in FRESHNESS_VALUES:
            self.assertNotEqual(
                "verified", combine_token("estimated", freshness)
            )

    def test_unsupported_values_are_rejected(self) -> None:
        for support, freshness in (("verified", "fresh"), ("sourced", "current")):
            with self.subTest(support=support, freshness=freshness):
                with self.assertRaises(EvidenceCoreError):
                    combine_token(support, freshness)
        with self.assertRaises(EvidenceCoreError):
            token_support("LIVE")


class AggregationCase(unittest.TestCase):
    """§2.4 的四分支。"""

    def _aggregate(self, supports: list[str], *, derived: bool) -> str:
        return aggregate_support(
            [SupportVerdict(value, "x") for value in supports],
            derivation_occurred=derived,
        ).support

    def test_branch_1_conflicting_wins_over_unknown(self) -> None:
        self.assertEqual(
            "conflicting",
            self._aggregate(["sourced", "unknown", "conflicting"], derived=False),
        )

    def test_branch_2_unknown_wins_over_estimated(self) -> None:
        self.assertEqual(
            "unknown",
            self._aggregate(["sourced", "estimated", "unknown"], derived=False),
        )

    def test_branch_3_estimated_from_derivation_or_input(self) -> None:
        self.assertEqual(
            "estimated", self._aggregate(["sourced", "estimated"], derived=False)
        )
        self.assertEqual(
            "estimated",
            self._aggregate(["sourced", "sourced"], derived=True),
            "roundtrip_duration_seconds 案例：两个 sourced 相加判 estimated，"
            "偏严是有意的（evidence-axes.md §2.4）",
        )

    def test_branch_4_all_sourced_without_derivation(self) -> None:
        self.assertEqual(
            "sourced", self._aggregate(["sourced", "sourced"], derived=False)
        )

    def test_aggregation_requires_at_least_one_input(self) -> None:
        with self.assertRaises(EvidenceCoreError):
            aggregate_support([], derivation_occurred=False)

    def test_aggregation_accepts_bare_support_strings(self) -> None:
        self.assertEqual(
            "sourced",
            aggregate_support(["sourced"], derivation_occurred=False).support,
        )
        with self.assertRaises(EvidenceCoreError):
            aggregate_support(["LIVE"], derivation_occurred=False)


class VocabularyCase(unittest.TestCase):
    """取值域与契约的对应。"""

    def test_reason_codes_match_the_contract(self) -> None:
        self.assertEqual(
            15,
            len(REASON_CODES),
            "P0 的 10 个 + P2 新增 4 个 + P3b 前置修正的 refresh_failed",
        )
        self.assertIn("refresh_failed", REASON_CODES)
        for added in (
            "cancelled_by_user",
            "input_precondition_unmet",
            "internal_contract_violation",
            "source_rejected_by_policy",
        ):
            self.assertIn(added, REASON_CODES)

    def test_enumerations_have_the_contracted_sizes(self) -> None:
        self.assertEqual(4, len(SUPPORT_VALUES))
        self.assertEqual(3, len(FRESHNESS_VALUES))
        self.assertEqual(5, len(NEXT_ACTION_KINDS))
        self.assertEqual(3, len(ACTORS))
        self.assertEqual("confirmed_absent", CONFIRMED_ABSENT_KIND)

    def test_evaluate_fact_rejects_a_mismatched_policy(self) -> None:
        with self.assertRaises(EvidenceCoreError):
            evaluate_fact(
                _sourced(),
                FreshnessPolicy("poi_coordinate", 100, False),
                now=NOW,
            )


class RefreshFailureCase(unittest.TestCase):
    """§3.4：刷新失败封顶。

    这条规则守的是 I2 抓不到的那类问题——缓存降级值的 support 声明是对的
    （确实来自 12306），错的是把它当 fresh。I2 只核对 token 与声明的一致性，
    因此这里必须有独立单测。见 invariants.md I2 的「边界」小节。
    """

    def test_fresh_window_plus_refresh_failure_is_capped_to_stale(self) -> None:
        verdict = resolve_freshness(
            _at(hours=1), now=NOW, tolerance_seconds=21600, refresh_failed=True
        )
        self.assertEqual(FRESHNESS_STALE, verdict.value)
        self.assertTrue(verdict.capped_by_refresh_failure)

    def test_missing_attempted_at_still_caps(self) -> None:
        """两处写入方不带时间戳；顺序由结构保证，不能因此放行。"""

        self.assertEqual(
            FRESHNESS_STALE,
            compute_freshness(
                _at(hours=1),
                now=NOW,
                tolerance_seconds=21600,
                refresh_failed=True,
            ),
        )

    def test_failure_not_later_than_collection_does_not_cap(self) -> None:
        """记录早于采集说明它属于本次采集本身，不是后续刷新。"""

        verdict = resolve_freshness(
            _at(hours=1),
            now=NOW,
            tolerance_seconds=21600,
            refresh_failed_at=_at(hours=2),
        )
        self.assertEqual(FRESHNESS_FRESH, verdict.value)
        self.assertFalse(verdict.capped_by_refresh_failure)

    def test_cap_never_upgrades_an_already_stale_value(self) -> None:
        verdict = resolve_freshness(
            _at(hours=9), now=NOW, tolerance_seconds=21600, refresh_failed=True
        )
        self.assertEqual(FRESHNESS_STALE, verdict.value)

    def test_cap_leaves_undated_alone(self) -> None:
        verdict = resolve_freshness(
            "not-a-date", now=NOW, tolerance_seconds=21600, refresh_failed=True
        )
        self.assertEqual(FRESHNESS_UNDATED, verdict.value)

    def test_capped_facts_report_refresh_failed_not_beyond_window(self) -> None:
        """两种 stale 的行动指引不同，reason_code 必须能区分。"""

        capped = evaluate_fact(
            FactInput(
                fact_id="f",
                data_type="railway_schedule_fare",
                value={"x": 1},
                derivation="direct_observation",
                sources=(SourceRef("12306", retrieved_at=_at(hours=1)),),
                refresh_failed=True,
            ),
            POLICY,
            now=NOW,
        )
        aged = evaluate_fact(
            FactInput(
                fact_id="f",
                data_type="railway_schedule_fare",
                value={"x": 1},
                derivation="direct_observation",
                sources=(SourceRef("12306", retrieved_at=_at(hours=9)),),
            ),
            POLICY,
            now=NOW,
        )
        self.assertEqual("sourced_stale", capped.token)
        self.assertEqual("sourced_stale", aged.token)
        assert capped.next_action is not None and aged.next_action is not None
        self.assertEqual("refresh_failed", capped.next_action["reason_code"])
        self.assertEqual(
            "beyond_tolerance_window", aged.next_action["reason_code"]
        )
        self.assertNotEqual(
            capped.next_action["detail"], aged.next_action["detail"]
        )


if __name__ == "__main__":
    unittest.main()
