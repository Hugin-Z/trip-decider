"""I1: 持久化文件中不得出现展示状态字段。

契约：docs/contracts/invariants.md I1
预期转绿：P4
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.invariant_support import (
    ALLOWED_KEYS,
    FORBIDDEN_KEYS,
    FORBIDDEN_VALUES,
    REPO_ROOT,
    drive_offline_run,
    iter_json_documents,
    walk_scalars,
)


class PersistedDisplayStatusCase(unittest.TestCase):
    """I1 检查新写入的 run 目录，不检查仓库中已有的历史 run。"""

    def test_i1_fresh_run_output_has_no_display_status_fields(self) -> None:
        with TemporaryDirectory() as temporary:
            sessions_root = Path(temporary) / "sessions"
            application, _query, run_id = drive_offline_run(sessions_root)
            run_directory = application.store.run_directory(run_id)
            self.assertIsNotNone(run_directory)
            assert run_directory is not None
            self.assertTrue(
                (run_directory / "plan-version.json").is_file(),
                "前置条件不满足：本次 run 没有产出 plan-version.json，"
                "I1 的扫描对象不完整",
            )

            hits: list[str] = []
            for path, document in iter_json_documents(run_directory):
                relative = (
                    f"{run_directory.name}/"
                    f"{path.relative_to(run_directory).as_posix()}"
                )
                for pointer, key, value in walk_scalars(document):
                    if key in ALLOWED_KEYS:
                        continue
                    if key in FORBIDDEN_KEYS:
                        hits.append(
                            f"{relative}{pointer} 键名 {key!r} 属于禁用键名集合"
                        )
                    elif isinstance(value, str) and value in FORBIDDEN_VALUES:
                        hits.append(
                            f"{relative}{pointer} 取值 {value!r} 属于禁用取值集合"
                        )

        self.assertEqual(
            [],
            sorted(set(hits)),
            f"落盘产物中出现了 {len(set(hits))} 处展示状态字段（去重后）",
        )

    def test_i1_scanner_does_not_touch_the_repository_runtime(self) -> None:
        """扫描器必须自建 runtime_root，不得读写仓库的 runtime/sessions。"""

        repository_runtime = REPO_ROOT / "runtime" / "sessions"
        before = (
            sorted(p.name for p in repository_runtime.iterdir())
            if repository_runtime.is_dir()
            else []
        )
        with TemporaryDirectory() as temporary:
            sessions_root = Path(temporary) / "sessions"
            drive_offline_run(sessions_root)
            self.assertTrue(sessions_root.is_dir())
        after = (
            sorted(p.name for p in repository_runtime.iterdir())
            if repository_runtime.is_dir()
            else []
        )
        self.assertEqual(before, after, "I1 的驱动污染了仓库 runtime/sessions")


if __name__ == "__main__":
    unittest.main()
