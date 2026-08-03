"""读时同步重采：解析步的守卫（freshness-policy.md §5.1/§5.2）。

**这条解析步存在的全部理由是原子性。** 判定「算不算 stale」早就收敛到
`project_domain` 一处，但那个漏斗不是**动手**的位置：它的调用方拿同一份证据
mapping 做的事远不止取 token——编译器取完 token 之后用同一个对象建全部车次、
票价与 fact_refs。在 `project_domain` 内部重采会让 token 反映新数据而下游字段
全是旧的，计划一边宣称 verified 一边用过期车次拼出来。**那比不重查更坏。**

所以本文件的核心不是「重采会发生」，是「重采之后 token 与值同源」。
只断言 token 翻转的用例会放过半新半旧——那正是要防的东西。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import unittest

from trip_decider.evidence_core import token_freshness, token_support
from trip_decider.evidence_projection import (
    REFETCH_THROTTLE_SECONDS,
    needs_refetch,
    project_domain,
    resolve_stale_evidence,
    usable_fact_values,
    item_facts,
)
from trip_decider.planning_input_compiler import plan_verdict_from_result

from tests.test_planning_input_compiler import (
    READ_AT,
    _intent,
    _map,
    _railway,
    _web,
)

STALE_AT = READ_AT + timedelta(hours=7)


def _context() -> dict:
    return {
        "context_id": "refetch",
        "intent": _intent("乙地").to_dict(),
        "evidence": [
            {
                "evidence_id": "user",
                "domain": "user_input",
                "status": "sourced",
                "value": _intent("乙地").to_dict(),
                "sources": [{"source_type": "user_supplied"}],
            },
            _railway().to_dict(),
            _map("乙地").to_dict(),
            _web("乙地").to_dict(),
        ],
    }


def _result() -> dict:
    return {
        "context": _context(),
        "plan": {"artifact_kind": "PlanVersion"},
    }


def _fresh_railway(*, departure: str, retrieved_at: str) -> dict:
    """一份「刚采到」的铁路证据，去程发车时刻可控——下游是否同步看它。

    从 ``EvidenceItem`` 改而不是从 ``to_dict()`` 的产物改：落盘形状的 ``value``
    已经是 facts 数组，直接 ``value["outbound"]`` 拿不到东西（这正是
    ``_stale_railway_evidence`` 注释里记着的那个坑）。
    """

    base = _railway()
    value = deepcopy(base.value)
    value["outbound"]["departure_at"] = departure
    value["snapshot"]["retrieved_at"] = retrieved_at
    value["snapshot"]["attempted_at"] = retrieved_at
    return replace(
        base,
        value=value,
        sources=(
            {"provider": "official-rail", "retrieved_at": retrieved_at},
        ),
    ).to_dict()


def _railway_of(context: dict) -> dict:
    return next(
        item
        for item in context["evidence"]
        if item["domain"] == "railway"
    )


class RefetchTriggerCase(unittest.TestCase):
    """触发条件：stale ∧ critical ∧ on_stale == auto_refetch。"""

    def test_fresh_evidence_does_not_trigger(self) -> None:
        item = _railway().to_dict()
        self.assertFalse(needs_refetch(item, "railway", now=READ_AT))

    def test_stale_critical_auto_refetch_triggers(self) -> None:
        item = _railway().to_dict()
        self.assertTrue(needs_refetch(item, "railway", now=STALE_AT))

    def test_non_critical_domain_never_triggers(self) -> None:
        """web 域是 destination_profile：非 critical、档位 flag_for_confirmation。

        它过期照样过期，只是不重查——档位的意义就在这里，不是所有陈旧都要打
        数据源。
        """

        item = _web("乙地").to_dict()
        self.assertFalse(
            needs_refetch(item, "web", now=READ_AT + timedelta(days=30))
        )

    def test_a_recent_failed_attempt_throttles(self) -> None:
        """节流阀：刚失败过就不再打。

        节流状态存在**已持久化的** ``refresh_failure.attempted_at`` 上。
        ``next_action.retry_after_at`` 是读取时算出来的、不落盘，拿它做节流等于
        没有节流——它的角色是把截止时刻报出去，不是存它。
        """

        item = _railway().to_dict()
        attempted = (STALE_AT - timedelta(seconds=30)).isoformat()
        item["value"]["refresh_failure"] = {
            "missing_reason": "rail_http",
            "attempted_at": attempted,
        }
        self.assertFalse(needs_refetch(item, "railway", now=STALE_AT))

        # 窗口过去之后恢复重试——节流是延期不是永久豁免（D9 的同一条道理）
        beyond = STALE_AT + timedelta(seconds=REFETCH_THROTTLE_SECONDS + 1)
        self.assertTrue(needs_refetch(item, "railway", now=beyond))

    def test_a_failure_without_a_timestamp_does_not_throttle_forever(
        self,
    ) -> None:
        """没有 attempted_at 就放行一次。

        算不出截止时刻时，放行至多多打一次——那一次会写下正经的 attempted_at，
        之后正常节流。反过来「无时间戳即永久节流」会让这条证据再也不重查，
        比多打一次糟得多。
        """

        item = _railway().to_dict()
        item["value"]["refresh_failure"] = {"missing_reason": "rail_http"}
        self.assertTrue(needs_refetch(item, "railway", now=STALE_AT))


class RefetchAtomicityCase(unittest.TestCase):
    """同一次读取内，token 的依据与 fact_values 的依据必须是同一份实例。"""

    def test_successful_refetch_moves_token_and_values_together(self) -> None:
        """D6 必成分支 + 原子性，一条用例同时钉。

        **只断言 token 翻回 verified 是不够的**——那正是半新半旧会通过的断言。
        这里同时断言下游业务字段换成了新值，两者必须一起动。
        """

        fresh_departure = "2026-08-04T15:30"
        fresh_at = STALE_AT.isoformat()

        def refetcher(domain, item):
            self.assertEqual("railway", domain)
            return _fresh_railway(
                departure=fresh_departure,
                retrieved_at=fresh_at,
            )

        context = _context()
        before = _railway_of(context)
        self.assertEqual(
            "2026-08-04T13:00",
            usable_fact_values(item_facts(before))["outbound"]["departure_at"],
        )
        self.assertEqual(
            "stale",
            token_freshness(
                project_domain({"railway": before}, "railway", now=STALE_AT).token
            ),
        )

        resolved = resolve_stale_evidence(
            {"railway": before},
            now=STALE_AT,
            refetcher=refetcher,
        )
        self.assertEqual(("railway",), resolved.refetched)

        after = resolved.items["railway"]
        verdict = project_domain({"railway": after}, "railway", now=STALE_AT)
        # 半新半旧即败：两条断言必须同时成立
        self.assertEqual("verified", verdict.token, "token 没翻回 verified")
        self.assertEqual(
            fresh_departure,
            usable_fact_values(item_facts(after))["outbound"]["departure_at"],
            "token 翻新了但下游业务字段还是旧值——半新半旧，"
            "正是这条解析步要防的东西",
        )

    def test_the_compiled_plan_sees_the_refetched_values(self) -> None:
        """装载点一（run.result 容器）的端到端原子性。

        编译器取完 token 之后用**同一个对象**建车次事件。这条钉住替换发生在
        compile 之前：计划里的发车时刻必须是重采回来的那个。
        """

        fresh_departure = "2026-08-04T15:30"

        def refetcher(domain, item):
            return _fresh_railway(
                departure=fresh_departure,
                retrieved_at=STALE_AT.isoformat(),
            )

        stale_verdict = plan_verdict_from_result(_result(), now=STALE_AT)
        fresh_verdict = plan_verdict_from_result(
            _result(),
            now=STALE_AT,
            refetcher=refetcher,
        )
        self.assertNotEqual(
            stale_verdict.planning_state,
            fresh_verdict.planning_state,
            "重采没有改变计划准入结论——解析步没接上，或没接在 compile 之前",
        )
        stale_ids = {
            str(item.get("blocker_id"))
            for item in stale_verdict.blockers
        }
        fresh_ids = {
            str(item.get("blocker_id"))
            for item in fresh_verdict.blockers
        }
        self.assertIn("RAILWAY_INPUT_UNAVAILABLE", stale_ids)
        self.assertNotIn(
            "RAILWAY_INPUT_UNAVAILABLE",
            fresh_ids,
            "重采成功之后铁路输入仍被判为不可用",
        )


class RefetchFailureCase(unittest.TestCase):
    """D6 必败分支：降级发生，且**读取不被阻塞**。"""

    def test_a_failing_refetcher_degrades_without_blocking_the_read(
        self,
    ) -> None:
        calls: list[str] = []

        def refetcher(domain, item):
            calls.append(domain)
            raise RuntimeError("rail_http 503")

        context = _context()
        resolved = resolve_stale_evidence(
            {"railway": _railway_of(context)},
            now=STALE_AT,
            refetcher=refetcher,
        )
        self.assertEqual(["railway"], calls, "重采根本没被调用")
        self.assertEqual((), resolved.refetched)
        self.assertEqual(("railway",), resolved.failed)
        # 降级 = 保持原样按 stale 投影，不是抹成 unknown、更不是抛出去
        after = resolved.items["railway"]
        verdict = project_domain({"railway": after}, "railway", now=STALE_AT)
        self.assertEqual("sourced", token_support(verdict.token))
        self.assertEqual("stale", token_freshness(verdict.token))
        self.assertIsNotNone(
            verdict.next_action,
            "降级后 next_action 缺席——用户看不到「正在重查」这件事",
        )

    def test_a_failing_refetch_still_produces_a_plan_verdict(self) -> None:
        """读取不阻塞的可执行形式：失败照样出结论。"""

        def refetcher(domain, item):
            raise RuntimeError("rail_http 503")

        verdict = plan_verdict_from_result(
            _result(),
            now=STALE_AT,
            refetcher=refetcher,
        )
        self.assertIsNotNone(
            verdict.planning_state,
            "重采失败把读取带崩了——预算与失败都必须降级，不得阻塞读取",
        )

    def test_a_programming_error_in_the_refetcher_is_not_swallowed(
        self,
    ) -> None:
        """D12：重采路径里的 NameError 不是「数据源不可用」。

        宽捕获会把它记成一次业务降级，于是归因去查数据源，而故障在代码里。
        """

        def refetcher(domain, item):
            raise NameError("undefined_helper")

        with self.assertRaises(NameError):
            resolve_stale_evidence(
                {"railway": _railway_of(_context())},
                now=STALE_AT,
                refetcher=refetcher,
            )


class RefetchBudgetCase(unittest.TestCase):
    def test_an_exhausted_budget_skips_without_blocking(self) -> None:
        """预算耗尽的域保持原样，照常按 stale 投影。"""

        ticks = iter([0.0, 99.0, 99.0, 99.0])

        def refetcher(domain, item):  # pragma: no cover - 不该被调用
            raise AssertionError("预算已耗尽却仍发起了重采")

        resolved = resolve_stale_evidence(
            {"railway": _railway_of(_context())},
            now=STALE_AT,
            refetcher=refetcher,
            budget_seconds=8.0,
            monotonic=lambda: next(ticks),
        )
        self.assertEqual((), resolved.refetched)
        self.assertEqual(("railway",), resolved.skipped_over_budget)
        self.assertIn("railway", resolved.items)


class BlockingAsymmetryCase(unittest.TestCase):
    """已知不对称（evidence-axes.md §5.2.1），推迟三轮后落地。

    契约注记：`estimated + stale + critical` **不阻断**，
    `sourced + stale + critical`（`on_stale == auto_refetch`）**阻断**——
    支持程度更弱的一侧反而更宽松。

    理由（裁决补注）：**承诺过的失效比从未承诺的模糊更需要拦。** `sourced` 对
    用户做过「这个值是准的」这一承诺，承诺失效后继续推进，就是替用户维持一个
    已经不成立的前提；`estimated` 从没做过那个承诺，拦死它只会让一条本来能走、
    只是需要说清前提的路径永久走不通。

    auto_refetch 落地后这条不对称成为**可观测行为**：序 4 会触发重采，序 3 不会。
    """

    def _fact(self, support: str):
        from trip_decider.evidence_core import FactInput, SourceRef

        return FactInput(
            fact_id="fact_rail_outbound_departure_at",
            data_type="railway_schedule_fare",
            value={"departure_at": "2026-08-04T13:00"},
            # §2.1 的六值分两组：DERIVATIONS_SOURCED / DERIVATIONS_ESTIMATED。
            derivation=(
                "direct_observation"
                if support == "sourced"
                else "api_estimate"
            ),
            sources=(
                SourceRef(
                    provider="official-rail",
                    retrieved_at=(READ_AT - timedelta(hours=8)).isoformat(),
                ),
            ),
        )

    def _verdict(self, support: str):
        from trip_decider.evidence_core import evaluate_fact
        from trip_decider.evidence_projection import READ_POLICIES

        return evaluate_fact(
            self._fact(support),
            READ_POLICIES["railway_schedule_fare"],
            now=READ_AT,
        )

    def test_sourced_stale_critical_blocks(self) -> None:
        verdict = self._verdict("sourced")
        self.assertEqual("stale", token_freshness(verdict.token))
        self.assertTrue(
            verdict.next_action["blocking"],
            "sourced 超窗未阻断——承诺过的精确值失效了却照常推进",
        )

    def test_estimated_stale_critical_does_not_block_but_conditions(
        self,
    ) -> None:
        verdict = self._verdict("estimated")
        self.assertEqual("stale", token_freshness(verdict.token))
        self.assertFalse(
            verdict.next_action["blocking"],
            "estimated 被阻断了——没有任何重查能让它变精确，"
            "拦住它等于永久拦死一条本来可用的路径",
        )
        self.assertTrue(
            verdict.requires_conditional,
            "estimated 不阻断就必须要求 conditional，"
            "否则它会变成一条不带前提说明的「可行」结论（裁决 5）",
        )

    def test_only_the_blocking_side_is_refetched(self) -> None:
        """不对称的行为侧：重采只发生在 sourced 那一支。

        `estimated` 从来就不精确，没有任何重查能让它变精确——对它发起重采是
        白打一次数据源。
        """

        item = _railway().to_dict()
        self.assertTrue(needs_refetch(item, "railway", now=STALE_AT))

        estimated = deepcopy(item)
        estimated["status"] = "estimated"
        verdict = project_domain(
            {"railway": estimated},
            "railway",
            now=STALE_AT,
        )
        self.assertEqual(
            "estimated",
            token_support(verdict.token),
            "前置条件不满足：夹具没有构造出 estimated support",
        )
        self.assertFalse(
            verdict.next_action["blocking"],
            "estimated + stale + critical 阻断了，与契约注记矛盾",
        )


if __name__ == "__main__":
    unittest.main()
