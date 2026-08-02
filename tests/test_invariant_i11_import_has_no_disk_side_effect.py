"""I11: import 不得产生磁盘副作用。

契约：docs/contracts/invariants.md I11（裁决 13.3）
阶段：P4-a 转绿

v1 在 travel_agent 的模块尾部构造 DEFAULT_AGENT_STORE，于是任何
``import trip_decider.travel_agent`` 都会 mkdir 加全量读盘（基线报告 M8）。
本轮改为显式工厂后，这条不变式守住它不再退回去。
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

# 全部产品模块。逐个 import 而不是只 import 入口，因为副作用可能藏在任何
# 一个模块的尾部。
MODULES = sorted(
    path.relative_to(SRC_ROOT).with_suffix("").as_posix().replace("/", ".")
    for path in (SRC_ROOT / "trip_decider").rglob("*.py")
    if "__pycache__" not in path.parts
)

_PROBE = textwrap.dedent(
    """
    import importlib
    import io
    import json
    import sys
    from pathlib import Path

    touched = []
    real_mkdir = Path.mkdir
    real_open = Path.open
    real_read_text = Path.read_text

    def _record(kind, path):
        text = str(path).replace("\\\\", "/")
        if "/runtime/" in text or text.endswith("/runtime"):
            touched.append(f"{kind}:{text}")

    def mkdir(self, *a, **k):
        _record("mkdir", self)
        return real_mkdir(self, *a, **k)

    def opener(self, *a, **k):
        _record("open", self)
        return real_open(self, *a, **k)

    def read_text(self, *a, **k):
        _record("read_text", self)
        return real_read_text(self, *a, **k)

    Path.mkdir = mkdir
    Path.open = opener
    Path.read_text = read_text

    for name in json.loads(sys.argv[1]):
        importlib.import_module(name)

    sys.stdout.write(json.dumps(touched))
    """
)


class ImportHasNoDiskSideEffectCase(unittest.TestCase):
    def test_i11_importing_every_module_touches_no_runtime_path(self) -> None:
        import json

        result = subprocess.run(
            [sys.executable, "-c", _PROBE, json.dumps(MODULES)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={
                "PYTHONPATH": str(SRC_ROOT),
                "PATH": "",
                "SYSTEMROOT": "C:\Windows",
            },
        )
        self.assertEqual(
            0,
            result.returncode,
            f"探针子进程失败：\n{result.stderr[-2000:]}",
        )
        touched = json.loads(result.stdout or "[]")
        self.assertEqual(
            [],
            sorted(set(touched)),
            "import 触碰了 runtime 路径。默认 store / broker / 服务必须惰性构造"
            "（travel_agent.default_agent_store 等），不得在模块尾部直接实例化。",
        )

    def test_i11_probe_covers_every_product_module(self) -> None:
        """探针必须覆盖全部模块，否则副作用可以藏在没被 import 的那个里。"""

        self.assertGreaterEqual(len(MODULES), 20)
        for entry in ("trip_decider.travel_agent", "trip_decider.mcp_server"):
            self.assertIn(entry, MODULES)


if __name__ == "__main__":
    unittest.main()
