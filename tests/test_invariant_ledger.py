"""预期失败登记的元测试。

P1 到 P5 期间不变式测试套件长期为红。若不管住这一点，红色会变成常态，
从而失去信息量——回归和「悄悄修好但没人记录」都会被淹没。

本元测试断言：**实际失败集合 == 登记集合**。

* 多出失败（登记外的测试红了）→ 回归，失败。
* 少了失败（登记内的测试绿了）→ 有人修好了却没更新登记，同样失败，
  因为下一个人无法据此判断进度。
* 出现 error（导入错误、环境问题）→ 零容忍，直接失败。登记只接受
  断言失败；无法构造场景的阻塞项必须以 assertXxx 表达，不得让异常逃逸。

登记文件：tests/invariant_ledger.json
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = Path(__file__).with_name("invariant_ledger.json")
INVARIANT_PATTERN = "test_invariant_i*.py"

_PHASE_ORDER = ("P0", "P1", "P2", "P3a", "P3b", "P4", "P5")
_VALID_PHASES = frozenset(_PHASE_ORDER)
_REQUIRED_FIELDS = ("test_id", "invariant", "expected_green_at", "failing_assertion")
_EXEMPTION_FIELDS = (
    "invariant",
    "scope",
    "reason",
    "expires_at_phase",
    "tracked_in",
)


def _load_ledger() -> dict[str, object]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def _run_invariant_suite() -> unittest.TestResult:
    """Run every I1-I9 test in-process and return the raw result."""

    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(REPO_ROOT / "tests"),
        pattern=INVARIANT_PATTERN,
        top_level_dir=str(REPO_ROOT),
    )
    if loader.errors:
        raise AssertionError(
            "不变式测试模块无法加载：\n  " + "\n  ".join(loader.errors)
        )
    result = unittest.TestResult()
    suite.run(result)
    return result


class InvariantLedgerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = _load_ledger()
        cls.result = _run_invariant_suite()

    # -- 登记文件自身的形态 ------------------------------------------------

    def test_ledger_entries_are_well_formed(self) -> None:
        entries = self.ledger.get("entries")
        self.assertIsInstance(entries, list, "登记文件缺少 entries 数组")
        assert isinstance(entries, list)

        problems: list[str] = []
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                problems.append(f"entries[{index}] 不是对象")
                continue
            for field in _REQUIRED_FIELDS:
                if not entry.get(field):
                    problems.append(f"entries[{index}] 缺少 {field}")
            phase = entry.get("expected_green_at")
            if phase not in _VALID_PHASES:
                problems.append(
                    f"entries[{index}] expected_green_at={phase!r} 不是 P1-P5"
                )
            test_id = entry.get("test_id")
            if isinstance(test_id, str):
                if test_id in seen:
                    problems.append(f"entries[{index}] test_id 重复：{test_id}")
                seen.add(test_id)
        self.assertEqual([], problems, "登记文件格式问题：\n  " + "\n  ".join(problems))

    # -- 核心：实际失败集合 == 登记集合 -------------------------------------

    def test_no_invariant_test_raises_an_error(self) -> None:
        """error 零容忍：登记只接受断言失败。"""

        errors = sorted(
            f"{test.id()}\n{traceback.strip().splitlines()[-1]}"
            for test, traceback in self.result.errors
        )
        self.assertEqual(
            [],
            errors,
            "不变式测试出现了 error 而非断言失败。error 通常是导入或环境"
            "问题，说明测试没有真正执行到断言：\n  " + "\n  ".join(errors),
        )

    def test_actual_failures_match_the_ledger(self) -> None:
        registered = sorted(
            str(entry["test_id"])
            for entry in self.ledger["entries"]
            if isinstance(entry, dict)
        )
        actual = sorted(test.id() for test, _traceback in self.result.failures)

        unregistered = sorted(set(actual) - set(registered))
        recovered = sorted(set(registered) - set(actual))

        message_parts: list[str] = []
        if unregistered:
            message_parts.append(
                "以下测试失败但不在登记中——这是回归，或是新写的测试忘了登记：\n  "
                + "\n  ".join(unregistered)
            )
        if recovered:
            message_parts.append(
                "以下测试在登记中但已经通过——请从 invariant_ledger.json 移除，"
                "并在对应阶段闸门记录它转绿了：\n  " + "\n  ".join(recovered)
            )
        self.assertEqual(
            registered,
            actual,
            "\n\n".join(message_parts) if message_parts else "",
        )

    # -- 豁免类目（与预期失败区分开）--------------------------------------

    def test_exemptions_are_well_formed_and_dated(self) -> None:
        """豁免必须有到期阶段，且不得已经过期。

        豁免与预期失败是两回事：``entries`` 说「整条测试允许失败」，
        ``exemptions`` 说「某条不变式在某个受限子范围内允许不成立，而承载它
        的测试整体仍需通过」。没有到期阶段的豁免会变成永久豁免，那正是这个
        类目要防的东西。
        """

        exemptions = self.ledger.get("exemptions")
        self.assertIsInstance(
            exemptions, list, "登记文件缺少 exemptions 数组（可以为空）"
        )
        assert isinstance(exemptions, list)

        current = str(self.ledger.get("current_phase", ""))
        self.assertIn(
            current, _VALID_PHASES, f"current_phase={current!r} 不是合法阶段"
        )
        current_index = _PHASE_ORDER.index(current)

        problems: list[str] = []
        for index, exemption in enumerate(exemptions):
            if not isinstance(exemption, dict):
                problems.append(f"exemptions[{index}] 不是对象")
                continue
            for name in _EXEMPTION_FIELDS:
                if not exemption.get(name):
                    problems.append(f"exemptions[{index}] 缺少 {name}")
            phase = exemption.get("expires_at_phase")
            if phase not in _VALID_PHASES:
                problems.append(
                    f"exemptions[{index}] expires_at_phase={phase!r} 不是合法阶段"
                )
                continue
            if _PHASE_ORDER.index(str(phase)) <= current_index:
                problems.append(
                    f"exemptions[{index}] 已于 {phase} 到期，"
                    f"当前阶段是 {current}——豁免必须清零或延期并说明理由"
                )
            tracked = REPO_ROOT / str(exemption.get("tracked_in", "")).split("#")[0].split(" ")[0]
            if not tracked.exists():
                problems.append(
                    f"exemptions[{index}] tracked_in 指向的文件不存在：{tracked}"
                )
        self.assertEqual(
            [], problems, "豁免登记问题：\n  " + "\n  ".join(problems)
        )

    def test_declared_red_set_matches_the_entries(self) -> None:
        """``still_red_invariants`` 必须与 entries 完全一致。

        这个字段是「哪些不变式还红着」的显式声明。它与 entries 分开存放，是
        为了让转绿成为一次需要动手改声明的动作——否则某条不变式的最后一个用例
        被删掉时，登记会静悄悄地变空而没人发现。
        """

        declared = set(self.ledger.get("still_red_invariants", []))
        covered = {
            str(entry["invariant"])
            for entry in self.ledger["entries"]
            if isinstance(entry, dict)
        }
        self.assertEqual(
            sorted(declared),
            sorted(covered),
            "still_red_invariants 与 entries 不一致："
            f"只在声明里的 {sorted(declared - covered)}，"
            f"只在登记里的 {sorted(covered - declared)}",
        )
        self.assertEqual(
            [],
            sorted(declared & set(self.ledger.get("green_invariants", []))),
            "同一条不变式不能既在 still_red_invariants 又在 green_invariants",
        )


if __name__ == "__main__":
    unittest.main()
