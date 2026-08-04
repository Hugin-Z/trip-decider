"""进程入口对 durable runtime 的独占占用。

`InMemoryAgentStore` 的并发保证是线程级，不是跨进程事务。两个 MCP/Web 进程指向
同一个 sessions 目录时，各自持有一份内存快照并会覆盖同名临时文件；与其静默
损坏或永久轮询旧状态，不如让第二个进程立即给出可操作的错误。
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO


class RuntimeOwnershipError(RuntimeError):
    """另一个 trip-decider 进程正在使用同一 runtime。"""


class RuntimeOwner:
    """持有 sessions 目录中的单字节系统锁，直到进程入口退出。"""

    def __init__(self, runtime_root: Path | str) -> None:
        self.runtime_root = Path(runtime_root).resolve()
        self._handle: BinaryIO | None = None

    def __enter__(self) -> "RuntimeOwner":
        self.acquire()
        return self

    def __exit__(self, *_error: object) -> None:
        self.release()

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        path = self.runtime_root / ".trip-decider.owner.lock"
        handle = path.open("a+b")
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            _lock(handle)
        except OSError as error:
            handle.close()
            raise RuntimeOwnershipError(
                f"runtime 已被另一个进程占用：{self.runtime_root}。"
                "关闭重复的 trip-decider 进程、为它配置不同的 "
                "TRIP_DECIDER_RUNTIME_ROOT，或用 mcp_server --with-web "
                "在同一进程同时提供 MCP 与网页。"
            ) from error
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            _unlock(handle)
        finally:
            handle.close()


def _lock(handle: BinaryIO) -> None:
    handle.seek(0)
    if __import__("os").name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if __import__("os").name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = ["RuntimeOwner", "RuntimeOwnershipError"]
