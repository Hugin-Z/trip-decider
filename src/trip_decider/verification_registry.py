"""进行中的核验任务：立即返回可秒回的部分，实采在后台推进。

**事故**（Claude Desktop 第四次实测，2026-08-04）：`verify_itinerary` 首次被真
宿主调用即 4 分钟无响应，宿主回退 web search。归因是同步实采——一份行程的车次
断言逐条查 12306，会话初始化本身就要 8 秒，每条再加 2 秒；任何一次 12306 变慢
都会被 15 秒超时 × 2 次重试放大成 31 秒一条。

修法与 run 那条链路同构：**工具调用只负责收下活并立刻回执**，实采在后台线程
推进，宿主轮询取增量。区别是核验不建 run——它无状态、单次、不进规划，所以
另起一个轻量登记处，而不是硬塞进 run 状态机。

**为什么在内存里而不落盘**：核验是一次会话内的问答，宿主拿到结果就用掉了。
落盘会引入一整套过期清理与并发写的问题，换来的只是「进程重启后还能查到上次的
核验」——那个场景不存在（宿主重启后会重新问）。代价说清楚：进程重启则
`verify_id` 失效，`read_verification` 会明确报「这个 id 不存在」并让宿主重提，
而不是假装还在跑。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from queue import Empty, SimpleQueue
import threading
import time
from uuid import uuid4

#: 一份核验最多留多久。超过就可以被新的核验挤掉——防止长跑进程无限积累。
_RETENTION_SECONDS = 3600.0

#: 同时最多留多少份。到顶时先淘汰最旧的**已完成**的。
_MAX_ENTRIES = 32


class VerificationCapacityError(RuntimeError):
    """所有槽位都被正在运行的核验占用。"""


@dataclass
class _Verification:
    verify_id: str
    total: int
    created_at: float
    dedupe_key: str | None = None
    #: 后台失败时，只把尚未得到结论的原断言交还给宿主重试。
    retry_items: list[object] = field(default_factory=list)
    #: 形状不合格的那些——不消耗网络，第一次调用就能给出。
    immediate: list[dict[str, object]] = field(default_factory=list)
    #: 实采核出来的。**只由持锁的工具线程从 ``inbox`` 搬进来**，
    #: 后台线程不直接写它（R1）。
    collected: list[dict[str, object]] = field(default_factory=list)
    status: str = "RUNNING"
    error: str | None = None
    #: 后台线程**唯一**能碰的东西。三元组 ``(kind, payload, detail)``：
    #: ``("finding", 结论, None)`` 或 ``("done", 终态, 错误详情)``。
    inbox: SimpleQueue = field(default_factory=SimpleQueue, repr=False)

    def snapshot(self) -> dict[str, object]:
        findings = sorted(
            (*self.immediate, *self.collected),
            key=lambda item: int(item.get("index") or 0),
        )
        pending = max(0, self.total - len(findings))
        status = self.status
        # 「结论已全部到齐、后台还没宣告收工」是一个**真实存在**的瞬间：worker
        # 投完最后一条结论到投出终态消息之间，总有一段。把它报成 RUNNING 会
        # 让宿主同时看到「还在跑」和「没有待办」——两个字段各自都没说谎，
        # 但合起来自相矛盾，轮询循环按哪个字段写都会错（R1）。
        #
        # 所以给它一个准确的名字，而不是假装它不存在，也不是把 pending 报成
        # 假的非零值。不变式因此成立：**RUNNING 蕴含 pending > 0**。
        if status == "RUNNING" and pending == 0:
            status = "FINALIZING"
        result = {
            "verify_id": self.verify_id,
            "status": status,
            "total": self.total,
            "checked": len(findings),
            "pending": pending,
            "findings": deepcopy(findings),
            "error": self.error,
        }
        if self.status == "FAILED":
            checked_indices = {
                int(item.get("index") or 0) for item in findings
            }
            result["retry_assertions"] = deepcopy(
                [
                    item
                    for index, item in enumerate(self.retry_items, start=1)
                    if index not in checked_indices
                ]
            )
        return result


class VerificationRegistry:
    """核验任务的登记处。线程安全，进程内。"""

    def __init__(
        self,
        *,
        spawn: Callable[[Callable[[], None], str], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        # 不需要重入。登记处的临界区只排空消息、维护条目并复制快照；展示层的
        # freshness 重算发生在 read() 返回之后。用普通 Lock 让今后任何“持锁
        # 回调再读登记处”的改动直接暴露，而不是被 RLock 悄悄合法化（B1）。
        self._lock = threading.Lock()
        self._entries: dict[str, _Verification] = {}
        self._spawn = spawn if spawn is not None else _default_spawn
        self._clock = clock if clock is not None else time.monotonic

    def start_background(
        self,
        *,
        total: int,
        immediate: Sequence[Mapping[str, object]],
        collect: Callable[[Callable[[Mapping[str, object]], None]], None],
        dedupe_key: str | None = None,
        retry_items: Sequence[object] = (),
    ) -> dict[str, object]:
        """登记一份核验并**立刻**返回回执。

        名字里带 background 是给 I14 的静态扫描看的：它是一条**异步边界**，
        传进来的 ``collect`` 在后台线程里跑，不在本次工具调用里跑。

        ``collect`` 在后台线程里跑，每核出一条就调一次传给它的 ``report``。
        逐条上报而不是等全部跑完再交——宿主轮询时能看到进度，也能在部分结果
        上先做判断。
        """

        entry = _Verification(
            verify_id=f"verify-{uuid4()}",
            total=total,
            created_at=self._clock(),
            dedupe_key=dedupe_key,
            retry_items=deepcopy(list(retry_items)),
            immediate=[dict(item) for item in immediate],
        )
        if len(entry.immediate) >= total:
            # 全部都是形状问题，没有要采的——不必起线程。
            entry.status = "COMPLETE"
        with self._lock:
            self._prune_locked()
            if dedupe_key is not None:
                duplicate = next(
                    (
                        existing
                        for existing in self._entries.values()
                        if existing.dedupe_key == dedupe_key
                        and existing.status != "FAILED"
                    ),
                    None,
                )
                if duplicate is not None:
                    return duplicate.snapshot()
            self._evict_finished_for_capacity_locked()
            if len(self._entries) >= _MAX_ENTRIES:
                raise VerificationCapacityError(
                    f"已有 {_MAX_ENTRIES} 份核验正在运行，请稍后重试"
                )
            self._entries[entry.verify_id] = entry

        def report(finding: Mapping[str, object]) -> None:
            entry.inbox.put(("finding", dict(finding), None))

        def worker() -> None:
            try:
                collect(report)
            except Exception as error:  # noqa: BLE001
                # 后台线程里重抛只会让线程静默死掉。如实记类型，让轮询看得见。
                entry.inbox.put(
                    ("done", "FAILED", f"{type(error).__name__}: {error}")
                )
                return
            entry.inbox.put(("done", "COMPLETE", None))

        if entry.status == "RUNNING":
            self._spawn(worker, f"trip-decider-verify-{entry.verify_id}")
        snapshot = self.read(entry.verify_id)
        assert snapshot is not None
        return snapshot

    def read(self, verify_id: str) -> dict[str, object] | None:
        with self._lock:
            self._prune_locked()
            entry = self._entries.get(verify_id)
            if entry is None:
                return None
            # 排空与快照在**同一个临界区**里。分成两段的话，读者能看见
            # 「结论已到齐、状态还写着 RUNNING」这种半更新态。
            self._drain_locked(entry)
            return entry.snapshot()

    @staticmethod
    def _drain_locked(entry: _Verification) -> None:
        """把后台投递的消息应用到条目上。**只有持锁的工具线程调它。**

        后台线程一个字段都不碰，只往 ``inbox`` 投递；所有字段变更集中在这里，
        于是「追加结论」与「转终态」发生在同一个临界区里。这就是 R1 要的单写者。
        """

        while True:
            try:
                kind, payload, detail = entry.inbox.get_nowait()
            except Empty:
                return
            if kind == "finding":
                entry.collected.append(payload)
            elif kind == "done":
                entry.status = str(payload)
                entry.error = detail

    def _prune_locked(self) -> None:
        # 先排空再判断终态：没人轮询过的条目，其完成消息还压在队列里，
        # 不排空就会被当成 RUNNING 而永远淘汰不掉。
        for entry in self._entries.values():
            self._drain_locked(entry)
        now = self._clock()
        stale = [
            key
            for key, entry in self._entries.items()
            if now - entry.created_at > _RETENTION_SECONDS
        ]
        for key in stale:
            del self._entries[key]

    def _evict_finished_for_capacity_locked(self) -> None:
        if len(self._entries) < _MAX_ENTRIES:
            return
        finished = sorted(
            (
                (entry.created_at, key)
                for key, entry in self._entries.items()
                if entry.status != "RUNNING"
            ),
        )
        for _created, key in finished[: len(self._entries) - _MAX_ENTRIES + 1]:
            del self._entries[key]


def _default_spawn(worker: Callable[[], None], name: str) -> None:
    threading.Thread(target=worker, name=name, daemon=True).start()


__all__ = ["VerificationCapacityError", "VerificationRegistry"]
