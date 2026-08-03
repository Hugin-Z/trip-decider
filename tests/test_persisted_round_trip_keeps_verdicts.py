"""落盘往返后判定不分叉。

**判据：同一份落盘，写入进程与读回进程必须给出同一个判定。** 恢复路径若读到
与写入时不同的数据，两侧结论就会分叉。

**它的覆盖范围有明确上界，别当成声呐盲区的等价替代。** 负向验证做过：把
`_map_handler` 还原成 v1 式读取（那正是漏掉 `destination_official_name`、让 run
停在 BLOCKED 的原始缺陷），本场景**仍然全绿**——`drive_offline_run` 走不到那条
分支，因此抓不到它。

能抓什么、抓不到什么，写在这里免得下一个人误以为它兜住了整类问题：

* **能抓**：同一条判定链在两侧数据上分叉——落盘丢字段、重建路径断裂、
  facts 没写全。前置条件（两侧非同一对象、读回确为 v2 形状）各有一条断言守着，
  防止空跑。
* **抓不到**：只在特定动作路径上触发的 v1 残留读取。那类要靠触及该路径的用例，
  或靠声呐——而声呐只包新序列化的 value，经 JSON 往返读回的是普通 dict。

给声呐补往返覆盖的方案被否了，理由是时序：历史存量删除与双读拆除就在本批之后，
届时那个窗口连同它守护的对象一起消失。窗口期内的残留缺口是**已知敞口**，
不是已解决问题。

本场景保留为永久回归：它是第 6 批 action-loop 去重所需崩溃恢复用例的前身。
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider import agent_actions
from trip_decider.evidence_projection import business_view, project_domain
from trip_decider.planning_input_compiler import PlanningInputCompiler
from trip_decider.travel_agent import InMemoryAgentStore

from tests.characterization_support import CHAR_NOW
from tests.invariant_support import drive_offline_run


def _verdicts(context: dict) -> dict:
    """一份 context 的完整判定链结论。

    只取结论，不取中间结构——判定分叉才是要抓的东西，结构差异由别的守卫管。
    """

    compiled = PlanningInputCompiler().compile(context, now=CHAR_NOW)
    return {
        "planning_state": compiled.get("planning_state"),
        "status": compiled.get("status"),
        "displayable": compiled.get("displayable"),
        "blockers": sorted(
            str(item.get("blocker_id"))
            for item in compiled.get("conditional_blockers", [])
            if isinstance(item, dict)
        ),
        "missing_requirements": sorted(
            str(item) for item in compiled.get("missing_requirements", [])
        ),
        "rail_events": sum(
            1
            for day in compiled.get("days", [])
            for event in day.get("events", [])
            if str(event.get("event_id", "")).startswith("rail-")
        ),
        "tokens": {
            domain: project_domain(
                {
                    str(item.get("domain")): item
                    for item in context.get("evidence", [])
                    if isinstance(item, dict)
                },
                domain,
                now=CHAR_NOW,
            ).token
            for domain in ("railway", "map", "web")
        },
    }


class PersistedRoundTripCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        agent_actions.set_read_clock(lambda: CHAR_NOW)
        cls._temporary = TemporaryDirectory()
        try:
            root = Path(cls._temporary.name) / "sessions"
            application, _query, run_id = drive_offline_run(root)
            directory = application.store.run_directory(run_id)
            assert directory is not None

            run = json.loads(
                (directory / "run.json").read_text(encoding="utf-8")
            )
            cls.context = run["result"]["context"]

            # 读回：新 store 从同一份盘上重建，模拟进程重启。
            agent_actions._STATES.pop(run_id, None)
            restored_store = InMemoryAgentStore(root)
            restored = restored_store.get_run(run_id)
            assert isinstance(restored.result, dict)
            cls.restored_context = restored.result["context"]
            cls.run_id = run_id
        finally:
            agent_actions.reset_read_clock()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_the_round_trip_actually_happened(self) -> None:
        """前置条件：两侧不是同一个对象，否则比较毫无意义。"""

        self.assertIsNot(self.context, self.restored_context)
        self.assertTrue(self.context.get("evidence"))
        self.assertTrue(self.restored_context.get("evidence"))

    def test_persisted_shape_is_v2(self) -> None:
        """前置条件：读回的确实是 v2 形状，否则守的是旧世界。"""

        for item in self.restored_context["evidence"]:
            value = item.get("value")
            if isinstance(value, dict) and item.get("domain") != "user_input":
                self.assertIn(
                    "facts",
                    value,
                    f"{item.get('domain')} 域的落盘 value 不是 v2 形状",
                )

    def test_verdicts_do_not_fork_across_the_round_trip(self) -> None:
        """本体：写入侧与读回侧必须给出同一个判定。

        分叉即意味着恢复路径上有人读到了不同的数据——多半是残留的 v1 式读取
        静默拿到了 None。
        """

        self.assertEqual(
            _verdicts(self.context),
            _verdicts(self.restored_context),
            "落盘往返后判定分叉：恢复路径读到的数据与写入时不同",
        )

    def test_business_view_survives_the_round_trip(self) -> None:
        """业务字段本身也要挺过往返——判定相同但字段丢失是可能的。"""

        for item in self.restored_context["evidence"]:
            if item.get("domain") not in {"railway", "map", "web"}:
                continue
            view = business_view(item)
            self.assertTrue(
                view,
                f"{item.get('domain')} 域读回后业务视图为空——"
                "facts 没落盘，或重建路径断了",
            )


if __name__ == "__main__":
    unittest.main()
