"""A12 回归：A 收敛之后，重排链路仍然完整走通。

链路：`revise_destination_plan` → `validate_destination_plan` → 新 PlanVersion
→ `plan_readiness.usable_now`。

**为什么这条必须单独钉**：A 收敛动了重排路径上的两个东西——

* 写入侧：重排产出的 `context` 不再内联证据，只留 `evidence_refs`；
* 读取侧：`validate_destination_plan` 原本从内联证据取 `evidence_id` 集合来
  核对 `plan.evidence_refs` 是否都解析得到，现在改从 `evidence_refs` 取。

两处若不同步，症状是**重排产出一个 `UNRESOLVED_EVIDENCE_REFS` 的无效计划**，
而重排本身不报错——validation 的 `valid: False` 会被当成「这次改不动」，
查起来完全看不出根因是收敛漏了一半。

`PLAN.md` §9.3 的 A12 判据是「至少发生 1 次真实的约束修改重排，且新
PlanVersion 可用」。本用例是它的离线可执行形式：真实出行那次验的是判断质量，
这里验的是链路通不通。
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider import agent_actions
from trip_decider.itinerary_planner import validate_destination_plan
from trip_decider.travel_agent import trimmed_context

from tests.characterization_support import CHAR_NOW
from tests.invariant_support import drive_offline_run


class RevisionChainCase(unittest.TestCase):
    def setUp(self) -> None:
        agent_actions.set_read_clock(lambda: CHAR_NOW)
        self.addCleanup(agent_actions.reset_read_clock)
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        root = Path(self._temporary.name) / "sessions"
        self.application, self.query, self.run_id = drive_offline_run(root)

    def test_the_installed_plan_is_usable_before_revising(self) -> None:
        """前置条件：重排之前得先有一个可用的计划。

        没有这一条，下面那条可能在「本来就没装上计划」的情况下全绿。
        """

        readiness = self.query.plan_readiness(self.run_id, now=CHAR_NOW)
        self.assertTrue(readiness["written"], "没有已写入的 PlanVersion")
        self.assertTrue(
            readiness["usable_now"],
            f"初始计划就不可用：{readiness}",
        )

    def test_trimmed_context_still_validates_its_evidence_refs(self) -> None:
        """收敛的核心风险点：裁剪后的 context 仍能核对引用。

        `validate_destination_plan` 现在从 `evidence_refs` 取 id 集合。若它没跟着
        改，裁剪后的 context 会让每一个 `plan.evidence_refs` 都解析不到。
        """

        run = self.application.store.get_run(self.run_id)
        context = run.result["context"]
        self.assertNotIn(
            "evidence",
            context,
            "A 未收敛：result 的 context 仍内联证据",
        )
        self.assertTrue(
            context.get("evidence_refs"),
            "裁剪后 evidence_refs 为空——引用全部指不到",
        )

        plan = run.result.get("plan") or {}
        report = validate_destination_plan(context, plan)
        self.assertEqual(
            [],
            report["problems"],
            f"裁剪后的 context 核对不过：{report['problems']}",
        )
        self.assertTrue(report["valid"])

    def test_an_unresolvable_ref_is_still_caught(self) -> None:
        """恒真检查：核对必须还会失败。

        上一条断言「核对通过」，而一个永远通过的核对器同样能让它绿。这里塞一个
        指不到的引用，`UNRESOLVED_EVIDENCE_REFS` 必须冒出来（D6）。
        """

        run = self.application.store.get_run(self.run_id)
        context = run.result["context"]
        plan = dict(run.result.get("plan") or {})
        plan["evidence_refs"] = [
            *(plan.get("evidence_refs") or []),
            "evidence-that-does-not-exist",
        ]

        report = validate_destination_plan(context, plan)
        self.assertIn(
            "UNRESOLVED_EVIDENCE_REFS",
            [str(item.get("code")) for item in report["problems"]],
            "塞了一个指不到的引用却核对通过——核对器是恒真的",
        )

    def test_revising_produces_a_new_usable_plan_version(self) -> None:
        """本体：改一处约束 → 新版本 → 仍然可用。"""

        before = self.query.plan_readiness(self.run_id, now=CHAR_NOW)
        before_version = before["plan_version"]

        # 真实的约束修改：把节奏放慢——A12 说的「一次真实的约束修改重排」
        self.application.revise_trip(
            self.run_id,
            revision={"pace": "relaxed", "user_message": "第二天别排那么满"},
        )

        after = self.query.plan_readiness(self.run_id, now=CHAR_NOW)
        self.assertNotEqual(
            before_version,
            after["plan_version"],
            "重排没有产生新版本",
        )
        self.assertTrue(
            after["usable_now"],
            f"新版本不可用——重排链路在收敛后断了：{after}",
        )

    def test_the_revised_context_is_also_trimmed(self) -> None:
        """重排产出的 context 同样不内联证据。

        写入点有三个，重排占两个。只收敛 planner 那一个，重排一次就把内联证据
        写回去了——收敛会被悄悄撤销，而没有任何东西会报错。
        """

        self.application.revise_trip(
            self.run_id,
            revision={"pace": "relaxed"},
        )
        run = self.application.store.get_run(self.run_id)
        context = run.result["context"]
        self.assertNotIn(
            "evidence",
            context,
            "重排把内联证据写回去了——A 收敛被悄悄撤销",
        )
        self.assertEqual(
            trimmed_context(context),
            context,
            "重排产出的 context 与权威裁剪规则不同形",
        )


if __name__ == "__main__":
    unittest.main()
