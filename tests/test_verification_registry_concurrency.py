"""R1：核验登记处的并发竞态——半更新态不得可观测。

**外部审计（Codex release gate）判为 HIGH，阻断级。**

**竞态的精确形状**：修复前，后台线程分**两次**取锁——一次追加结论、一次转终态。
两次之间读者拿得到锁，于是能观察到

    status = "RUNNING"  而  pending = 0

「没有待办、却还在跑」。宿主的轮询循环无论按哪个字段写都会错：按 `pending > 0`
写会提前收工、把部分结果当成最终结论；按 `status` 写会对着一个已经跑完的任务
继续轮询。**两个字段各自都是「对的」，错的是它们能被看到不一致。**

**修法**：后台线程一个字段都不碰，只往 `inbox` 投递；持锁的工具线程独占地把
消息应用到条目上。追加结论与转终态因此发生在同一个临界区里，中间态不可观测。

**本文件先证明钩子抓得住这个竞态**（用一个复刻旧纪律的模型），再断言真实登记处
在同样的钩子下不出现半更新态。没有第一步，第二步的绿是没有信息的（D6）。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import threading
import time
import unittest

from trip_decider.verification_registry import VerificationRegistry


class _Scheduler:
    """把线程切换钉在我们要的那个点上，不靠运气撞。

    竞态测试最坏的写法是「跑一万次看会不会挂」——它既慢又不可靠，红了也说不清
    是哪个交错。这里用一个闸门显式制造那一个交错。
    """

    def __init__(self) -> None:
        self.reader_may_go = threading.Event()
        self.writer_may_finish = threading.Event()

    def pause_writer_before_terminal(self) -> None:
        """后台线程走到「已投完全部结论、尚未转终态」时停在这里。"""

        self.reader_may_go.set()
        self.writer_may_finish.wait(timeout=5.0)


class _LegacyRegistry:
    """复刻**修复前**的纪律：后台线程两次取锁，各写各的。

    这不是死代码，是竞态的可执行说明。有了它，下面那条「真实登记处没有半更新态」
    才有对照——否则无从判断是修好了还是钩子根本没生效。
    """

    def __init__(self, scheduler: _Scheduler) -> None:
        self._lock = threading.RLock()
        self.collected: list[dict[str, object]] = []
        self.status = "RUNNING"
        self.total = 2
        self._scheduler = scheduler

    def worker(self) -> None:
        for index in (1, 2):
            with self._lock:  # 第一次取锁：追加结论
                self.collected.append({"index": index})
        self._scheduler.pause_writer_before_terminal()
        with self._lock:  # 第二次取锁：转终态
            self.status = "COMPLETE"

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "status": self.status,
                "pending": max(0, self.total - len(self.collected)),
            }


class TheHookCanCatchTheRaceCase(unittest.TestCase):
    """先证明钩子抓得住（D6）。这一条**必须**在旧纪律下红/复现。"""

    def test_legacy_discipline_exposes_a_half_updated_snapshot(self) -> None:
        scheduler = _Scheduler()
        legacy = _LegacyRegistry(scheduler)
        thread = threading.Thread(target=legacy.worker, daemon=True)
        thread.start()

        self.assertTrue(
            scheduler.reader_may_go.wait(timeout=5.0),
            "后台线程没走到闸门，钩子没生效",
        )
        observed = legacy.snapshot()
        scheduler.writer_may_finish.set()
        thread.join(timeout=5.0)

        # 这就是宿主会看到的自相矛盾的一幕。
        self.assertEqual("RUNNING", observed["status"])
        self.assertEqual(0, observed["pending"])


class RealRegistryHasNoObservableMiddleStateCase(unittest.TestCase):
    """同样的钩子打在真实登记处上，半更新态不得出现。"""

    def _run_with_gate(self) -> list[dict[str, object]]:
        scheduler = _Scheduler()
        registry = VerificationRegistry()
        observed: list[dict[str, object]] = []

        def collect(report: Callable[[Mapping[str, object]], None]) -> None:
            report({"index": 1, "verdict": "sourced"})
            report({"index": 2, "verdict": "sourced"})
            # 全部结论已投递、终态消息尚未投递——旧纪律下的危险窗口。
            scheduler.pause_writer_before_terminal()

        started = registry.start_background(
            total=2,
            immediate=[],
            collect=collect,
        )
        self.assertTrue(
            scheduler.reader_may_go.wait(timeout=5.0),
            "后台线程没走到闸门，钩子没生效",
        )
        observed.append(started)
        # 在危险窗口里反复读
        for _ in range(5):
            snapshot = registry.read(str(started["verify_id"]))
            assert snapshot is not None
            observed.append(snapshot)
        scheduler.writer_may_finish.set()
        # 放行之后要给后台线程真正投出终态消息的时间。轮询之间不等的话，
        # 二十次全落在同一个瞬间——那测的是「读得快不快」，不是「转不转终态」。
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            snapshot = registry.read(str(started["verify_id"]))
            assert snapshot is not None
            observed.append(snapshot)
            if snapshot["status"] in {"COMPLETE", "FAILED"}:
                break
            time.sleep(0.01)
        return observed

    def test_no_snapshot_says_running_with_nothing_pending(self) -> None:
        offenders = [
            snapshot
            for snapshot in self._run_with_gate()
            if snapshot["status"] == "RUNNING" and snapshot["pending"] == 0
        ]

        self.assertEqual(
            [],
            offenders,
            "读到了「没有待办却还在跑」的半更新态——宿主的轮询循环会据此提前收工",
        )

    def test_checked_never_exceeds_total(self) -> None:
        offenders = [
            snapshot
            for snapshot in self._run_with_gate()
            if int(snapshot["checked"]) > int(snapshot["total"])
        ]

        self.assertEqual([], offenders, f"计数越界：{offenders}")

    def test_the_run_still_reaches_a_terminal_state(self) -> None:
        """修竞态不能把活修死。"""

        self.assertEqual("COMPLETE", self._run_with_gate()[-1]["status"])


class BackgroundThreadTouchesOnlyTheInboxCase(unittest.TestCase):
    """单写者纪律：后台线程只碰 inbox，其余字段归持锁的工具线程。"""

    def test_findings_are_invisible_until_a_locked_read_drains_them(
        self,
    ) -> None:
        registry = VerificationRegistry(spawn=lambda worker, name: worker())
        captured: list[object] = []

        def collect(report: Callable[[Mapping[str, object]], None]) -> None:
            report({"index": 1, "verdict": "sourced"})
            captured.append(True)

        started = registry.start_background(
            total=1, immediate=[], collect=collect
        )

        self.assertTrue(captured, "collect 没被调用")
        # 同步 spawn：start_background 末尾那次 read 已经排空并落定。
        self.assertEqual("COMPLETE", started["status"])
        self.assertEqual(1, started["checked"])

    def test_concurrent_readers_and_writer_stay_consistent(self) -> None:
        """压一压：多读者 + 后台推进，计数与状态始终自洽。"""

        registry = VerificationRegistry()
        release = threading.Event()
        self.addCleanup(release.set)

        def collect(report: Callable[[Mapping[str, object]], None]) -> None:
            for index in range(1, 21):
                report({"index": index, "verdict": "sourced"})
            release.wait(timeout=5.0)

        started = registry.start_background(
            total=20, immediate=[], collect=collect
        )
        verify_id = str(started["verify_id"])
        problems: list[str] = []

        def poll() -> None:
            for _ in range(200):
                snapshot = registry.read(verify_id)
                if snapshot is None:
                    problems.append("条目在跑着的时候消失了")
                    return
                checked = int(snapshot["checked"])
                pending = int(snapshot["pending"])
                if checked + pending != int(snapshot["total"]):
                    problems.append(f"计数不自洽：{snapshot}")
                if snapshot["status"] == "RUNNING" and pending == 0:
                    problems.append(f"半更新态：{snapshot}")

        readers = [threading.Thread(target=poll) for _ in range(4)]
        for reader in readers:
            reader.start()
        for reader in readers:
            reader.join(timeout=10.0)
        release.set()

        self.assertEqual([], problems)


if __name__ == "__main__":
    unittest.main()
