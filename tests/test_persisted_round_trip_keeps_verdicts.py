"""落盘往返后判定不分叉。

**判据：同一份落盘，写入进程与读回进程必须给出同一个判定。** 恢复路径若读到
与写入时不同的数据，两侧结论就会分叉。

**往返的对象是容器 B（`evidence/current.json`）**——2026-08-03 随 A 收敛改。
此前两侧取的都是 `run.result["context"]["evidence"]`（容器 A）：一侧是
`json.loads` 的裸解析，另一侧是 store 反序列化后的同一份文件。A 删除之后那两侧
会**同时变空**，比较随即恒真——一条守卫最糟的死法不是断言写错，是它守的对象
没了而它自己不知道（本文件因此在 A 收敛清单里被单独列为「需要判断的那一条」）。

改后守的是**真实持久化路径**：证据经 `evidence/current.json` 写出、由重启后的
store 读回，两侧判定必须相同。这比原来更接近它一直声称要守的东西——
「恢复路径读到的数据与写入时不同」说的本来就是证据，而证据的权威容器是 B。

**它的覆盖范围有明确上界，别当成声呐盲区的等价替代。** 负向验证做过：把
`_map_handler` 还原成 v1 式读取（那正是漏掉 `destination_official_name`、让 run
停在 BLOCKED 的原始缺陷），本场景**仍然全绿**——`drive_offline_run` 走不到那条
分支，因此抓不到它。

能抓什么、抓不到什么：

* **能抓**：同一条判定链在两侧数据上分叉——落盘丢字段、重建路径断裂、
  facts 没写全。前置条件（两侧非同一对象、读回确为 v2 形状、破坏落盘会改变
  判定）各有一条断言守着，防止空跑。
* **抓不到**：只在特定动作路径上触发的 v1 残留读取。那类要靠触及该路径的用例。

本场景保留为永久回归：它是第 6 批 action-loop 去重所需崩溃恢复用例的前身。
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider import agent_actions
from trip_decider.evidence_projection import business_view, project_domain
from trip_decider.planning_input_compiler import PlanningInputCompiler
from trip_decider.travel_agent import (
    InMemoryAgentStore,
    TravelIntent,
    user_input_evidence,
)

from tests.characterization_support import CHAR_NOW
from tests.invariant_support import drive_offline_run


def _context_of(intent: dict, evidence: dict) -> dict:
    """按读取层的规则组装编译输入：intent + 容器 B + 重建的 user_input。

    与 `trip_query._compile_evidence` / `agent_actions._loop_evidence` 同一套
    规则。`user_input` 不在 B 里——它是 intent 的投影不是采集证据。
    """

    items = [deepcopy(dict(item)) for item in evidence.values()]
    items.append(user_input_evidence(TravelIntent.from_mapping(intent)).to_dict())
    return {
        "context_id": "round-trip",
        "intent": deepcopy(intent),
        "evidence": items,
    }


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


def _evidence_from_disk(directory: Path) -> dict:
    """裸解析 `evidence/current.json`——不经 store，代表「刚写出去的那一份」。"""

    document = json.loads(
        (directory / "evidence" / "current.json").read_text(encoding="utf-8")
    )
    current = document.get("current")
    return {
        str(item["domain"]): item
        for item in (current if isinstance(current, list) else [])
        if isinstance(item, dict) and isinstance(item.get("domain"), str)
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
            cls.directory = directory
            cls.run_id = run_id

            run = json.loads(
                (directory / "run.json").read_text(encoding="utf-8")
            )
            cls.intent = run["intent"]
            # 写入侧：盘上那份 evidence/current.json 的裸解析
            cls.written = _evidence_from_disk(directory)

            # 读回侧：新 store 从同一份盘上重建，模拟进程重启
            agent_actions._STATES.pop(run_id, None)
            restored_store = InMemoryAgentStore(root)
            restored_app = type(application)(store=restored_store)
            cls.restored = dict(restored_app.current_run_evidence(run_id))
        finally:
            agent_actions.reset_read_clock()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_the_round_trip_actually_happened(self) -> None:
        """前置条件：两侧不是同一个对象，且都非空，否则比较毫无意义。"""

        self.assertIsNot(self.written, self.restored)
        self.assertTrue(self.written, "写入侧证据为空——容器 B 没落盘")
        self.assertTrue(self.restored, "读回侧证据为空——恢复路径断了")
        self.assertEqual(
            sorted(self.written),
            sorted(self.restored),
            "两侧的域集合不同",
        )

    def test_persisted_shape_is_v2(self) -> None:
        """前置条件：读回的确实是 v2 形状，否则守的是旧世界。"""

        for domain, item in self.restored.items():
            value = item.get("value")
            if isinstance(value, dict):
                self.assertIn(
                    "facts",
                    value,
                    f"{domain} 域的落盘 value 不是 v2 形状",
                )

    def test_verdicts_do_not_fork_across_the_round_trip(self) -> None:
        """本体：写入侧与读回侧必须给出同一个判定。

        分叉即意味着恢复路径上有人读到了不同的数据——多半是残留的 v1 式读取
        静默拿到了 None。
        """

        self.assertEqual(
            _verdicts(_context_of(self.intent, self.written)),
            _verdicts(_context_of(self.intent, self.restored)),
            "落盘往返后判定分叉：恢复路径读到的数据与写入时不同",
        )

    def test_corrupting_the_persisted_evidence_changes_the_verdict(
        self,
    ) -> None:
        """**恒真检查**：破坏落盘的证据，判定必须跟着变。

        没有这一条，上面那条相等断言在「两侧同时退化成空」时会全绿——A 收敛前
        本文件守的对象正是那样一份即将消失的容器（D6：没响过的绿是没有信息的）。
        """

        broken = deepcopy(self.restored)
        railway = broken.get("railway")
        self.assertIsNotNone(railway, "夹具里没有铁路证据，本检查无从进行")
        railway["status"] = "missing"
        railway["value"] = None
        railway["sources"] = []
        railway["missing_reason"] = "rail_http"

        self.assertNotEqual(
            _verdicts(_context_of(self.intent, self.restored)),
            _verdicts(_context_of(self.intent, broken)),
            "破坏了落盘证据而判定没变——这条守卫是恒真的，守不住任何东西",
        )

    def test_business_view_survives_the_round_trip(self) -> None:
        """业务字段本身也要挺过往返——判定相同但字段丢失是可能的。"""

        for domain, item in self.restored.items():
            if domain not in {"railway", "map", "web"}:
                continue
            view = business_view(item)
            self.assertTrue(
                view,
                f"{domain} 域读回后业务视图为空——facts 没落盘，或重建路径断了",
            )


if __name__ == "__main__":
    unittest.main()
