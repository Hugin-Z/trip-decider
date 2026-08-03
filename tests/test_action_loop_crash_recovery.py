"""§13.1 的验收用例：`run.json` 已写、`action-loop.json` 未写，仍可恢复。

去重把 `action-loop.json` 的 `result` 删了（实测 78,102 字节，与 `run.json`
的同名字段逐字节相同）。副本的问题不是占地方，是**两份可以不一致**——谁是
权威没写下来，两边就都不是。裁决把权威钉在 `run.json`，代价是崩溃恢复语义
变了：以前两份独立、任一可单独重建，现在 `action-loop.json` 依赖 `run.json`。

语义变了就必须有用例钉住新语义，否则「可恢复」只是一句自称。本文件模拟写入
顺序之间的那个中断窗口：`run.json` 已落、`action-loop.json` 还没落。

配套的负向验证在 `test_recovery_needs_the_authoritative_run_json`——
先证明这个用例真的在考恢复，而不是在考「文件反正都在」。
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider.agent_actions import (
    _STATES,
    _load_loop_state,
    reset_read_clock,
    set_read_clock,
)
from trip_decider.travel_agent import TravelAgentError

from tests.characterization_support import CHAR_NOW
from tests.invariant_support import drive_offline_run


class ActionLoopCrashRecoveryCase(unittest.TestCase):
    def setUp(self) -> None:
        set_read_clock(lambda: CHAR_NOW)
        self.addCleanup(reset_read_clock)
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        application, _query, self.run_id = drive_offline_run(
            Path(self._temporary.name) / "sessions"
        )
        self.store = application.store
        directory = self.store.run_directory(self.run_id)
        assert directory is not None
        self.directory = directory
        # 内存态会掩盖磁盘恢复——清掉，强制走 _load_loop_state。
        _STATES.pop(self.run_id, None)
        self.addCleanup(_STATES.pop, self.run_id, None)

    def _action_loop(self) -> dict[str, object]:
        return json.loads(
            (self.directory / "action-loop.json").read_text(encoding="utf-8")
        )

    def test_action_loop_no_longer_duplicates_the_run_result(self) -> None:
        """去重本身：副本没了，且留下了指向权威的说明。"""

        action_loop = self._action_loop()
        self.assertNotIn(
            "result",
            action_loop,
            "action-loop.json 仍在存 result 副本，去重没有生效",
        )
        self.assertEqual("run.json#result", action_loop.get("result_source"))
        run = json.loads(
            (self.directory / "run.json").read_text(encoding="utf-8")
        )
        self.assertIsInstance(
            run.get("result"),
            dict,
            "run.json 里没有 result——权威侧是空的，去重就成了丢数据",
        )

    def test_recovers_when_action_loop_was_never_written(self) -> None:
        """中断窗口：run.json 已落、action-loop.json 未落。"""

        expected = self.store.get_run(self.run_id).result
        (self.directory / "action-loop.json").unlink()

        state = _load_loop_state(self.run_id, self.store)

        self.assertIsNotNone(state, "action-loop.json 缺失时恢复直接放弃了")
        assert state is not None
        self.assertEqual(
            expected,
            state.result,
            "恢复出来的 result 与 run.json 的权威副本不一致",
        )
        self.assertEqual(
            "completed",
            state.action_status["planner"],
            "run.json 里已有计划，planner 却没被重建成 completed",
        )
        self.assertTrue(
            state.evidence,
            "证据没有从 evidence/current.json 重建出来",
        )

    def test_recovery_needs_the_authoritative_run_json(self) -> None:
        """负向验证：把权威侧的 result 抽走，恢复必须如实说没有。

        没有这一条，上面那条用例可能只是在考「文件反正都在」——它得证明
        自己真的是从 run.json 取的 result，而不是从别处捡到的。

        注意抹除必须打在**权威本体**上：``get_run()`` 返回的是 deepcopy，
        改它等于什么都没改，用例会带着一个空操作显示为绿。这条负向验证第一次
        跑就是这么假绿的——它自己先证明了自己在裸奔。
        """

        (self.directory / "action-loop.json").unlink()
        self.store._runs[self.run_id].result = None

        state = _load_loop_state(self.run_id, self.store)

        assert state is not None
        self.assertIsNone(
            state.result,
            "run.json 已无 result，恢复却凭空拿出一个——说明它另有来源",
        )
        self.assertEqual(
            "waiting",
            state.action_status["planner"],
            "没有权威 result 却把 planner 判为已完成",
        )

    def test_missing_evidence_is_still_an_error(self) -> None:
        """恢复不是「什么都能忍」：证据侧缺失仍须报错，不得静默给空状态。"""

        (self.directory / "evidence" / "current.json").unlink()
        with self.assertRaises(TravelAgentError):
            _load_loop_state(self.run_id, self.store)


if __name__ == "__main__":
    unittest.main()
