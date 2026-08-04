"""I15：跨调用可变状态必须声明并发策略。

**由 R1 逼出来**（外部审计 HIGH）。核验登记处的竞态不是「写错了一行」，是
**没有人在任何地方说过这份状态由谁写、谁读、拿什么保护**。没有声明，下一个
改它的人（包括三天后的自己）只能靠读全文猜。

**陈述**：模块级可变容器中，**在运行期真的被改过的**那些，必须在紧邻的注释里
声明并发策略，否则即红。

**为什么只盯「真的被改过的」**：判定过宽和过窄一样没用——前者让人学会忽略它。
全仓 39 个模块级容器里 37 个是词表、策略表和 `__all__`，从导入到进程结束一个
字节都不变；要求它们各写一行「并发：只读」，产出的是 37 行样板，而样板会被
连同真正要紧的那两行一起略过。

所以「只读」这件事由**扫描自己证明**（全仓搜下标赋值、`append` / `update` /
`pop` 之类的变更调用），不劳人声明。人只需要为**真共享可变状态**写一句——
本轮全仓两处。

**为什么盯模块级**：模块级的东西天然跨调用、跨线程共享，而它看起来和一个普通
常量一模一样。实例属性至少还有个 `self` 提示作用域；模块级没有。

**声明怎么写**：紧挨着的注释里出现 `并发：` 开头的一行。内容自便，但要回答
「谁写、谁读、拿什么保护」。三类常见答案：

* `并发：只读常量，导入后不再变更` —— 绝大多数（词表、策略表、`__all__`）；
* `并发：<锁名> 保护，全部读写都在锁内` —— 真共享可变状态；
* `并发：单线程，仅 <场景> 使用` —— 明确不打算支持并发。

**不接受空话**：只写「并发：安全」不算，判据要求出现「只读 / 锁 / 单线程」
之一——那是三种**不同的**保证，混着说等于没说。
"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

_SOURCE_ROOT = Path("src/trip_decider")

_MUTABLE_CALLS = frozenset({"dict", "list", "set", "defaultdict", "deque"})

#: 声明必须落在这三类保证之一上。
_POLICY_MARKERS = ("只读", "锁", "单线程")

_DECLARATION_PREFIX = "并发："

#: 会改变容器内容的写法。下标赋值另行判定（它是语句不是调用）。
_MUTATING_METHODS = frozenset(
    {
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "update",
        "setdefault",
        "add",
        "discard",
        "popitem",
        "sort",
    }
)


def _mutated_names() -> set[str]:
    """全仓里**真的被改过**的名字。

    「只读」不该由人声明——人会写错，也会在改了它之后忘了改声明。这里直接搜
    变更行为：下标赋值 / del / 变更方法调用 / 增广赋值。搜到的才要人解释。

    按**名字**搜，不做作用域分析：同名局部变量的变更会被算进来，也就是判定
    偏严。偏严的代价是多写一行声明，偏松的代价是漏掉一个竞态——选偏严。
    """

    mutated: set[str] = set()

    def record(node: ast.AST) -> None:
        base = node
        while isinstance(base, (ast.Subscript, ast.Attribute)):
            base = base.value
        if isinstance(base, ast.Name):
            mutated.add(base.id)

    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Subscript):
                        record(target)
            elif isinstance(node, ast.AugAssign):
                record(node.target)
            elif isinstance(node, ast.Delete):
                for target in node.targets:
                    record(target)
            elif isinstance(node, ast.Call) and isinstance(
                node.func, ast.Attribute
            ):
                if node.func.attr in _MUTATING_METHODS:
                    record(node.func.value)
    return mutated


def _module_level_mutables() -> list[tuple[Path, int, str]]:
    """模块级可变容器：(文件, 行号, 变量名)。"""

    found: list[tuple[Path, int, str]] = []
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(
                node.target, ast.Name
            ):
                targets = [node.target]
                value = node.value
            else:
                continue
            if value is None:
                continue
            mutable = isinstance(value, (ast.Dict, ast.List, ast.Set)) or (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in _MUTABLE_CALLS
            )
            if not mutable:
                continue
            for target in targets:
                found.append((path, node.lineno, target.id))
    return found


def _declaration_above(path: Path, lineno: int) -> str | None:
    """紧邻上方的注释块里，那一行 `并发：` 声明。

    往上扫连续的注释行（含 `#:` 文档注释）；遇到空行或代码就停——隔了别的东西
    的注释不算「紧邻」，那样的话随便哪里写一句就能骗过判定。
    """

    lines = path.read_text(encoding="utf-8").splitlines()
    index = lineno - 2  # 0-based，且跳过声明行自己
    block: list[str] = []
    while index >= 0:
        stripped = lines[index].strip()
        if not stripped.startswith("#"):
            break
        block.append(stripped.lstrip("#: ").strip())
        index -= 1
    for line in block:
        if line.startswith(_DECLARATION_PREFIX):
            return line
    return None


class ModuleLevelMutablesDeclareConcurrencyCase(unittest.TestCase):
    def test_the_scan_finds_something(self) -> None:
        """扫不到东西不是「全绿」，是判定失效。"""

        self.assertGreater(len(_module_level_mutables()), 10)

    def test_shared_mutable_state_declares_a_policy(self) -> None:
        mutated = _mutated_names()
        missing = [
            f"{path.relative_to(_SOURCE_ROOT)}:{lineno} {name}"
            for path, lineno, name in _module_level_mutables()
            if name in mutated and _declaration_above(path, lineno) is None
        ]

        self.assertEqual(
            [],
            missing,
            "以下模块级可变容器没有声明并发策略（I15）：\n  "
            + "\n  ".join(missing)
            + "\n在紧邻上方加一行注释：「并发：只读常量，导入后不再变更」/"
            "「并发：<锁名> 保护，全部读写都在锁内」/「并发：单线程，仅 X 使用」。"
            "\n或者把它收进函数作用域——跨调用共享才需要声明。",
        )

    def test_declarations_name_a_real_guarantee(self) -> None:
        """「并发：安全」这种空话不算——三种保证是不同的东西。"""

        vague: list[str] = []
        for path, lineno, name in _module_level_mutables():
            declaration = _declaration_above(path, lineno)
            if declaration is None:
                continue
            if not any(marker in declaration for marker in _POLICY_MARKERS):
                vague.append(
                    f"{path.relative_to(_SOURCE_ROOT)}:{lineno} {name}"
                    f" —— {declaration}"
                )

        self.assertEqual(
            [],
            vague,
            "以下声明没落到具体保证上（要出现「只读」「锁」「单线程」之一）：\n  "
            + "\n  ".join(vague),
        )

    def test_the_registry_state_is_declared_under_a_lock(self) -> None:
        """R1 那份状态本身要有声明——不然这条不变式没管住肇事者。

        登记处的条目表是**实例属性**不是模块级，扫描看不到它；所以这里单独
        钉一条：它的并发策略写在类文档里，且真的有锁。
        """

        from trip_decider.verification_registry import VerificationRegistry

        source = Path(
            "src/trip_decider/verification_registry.py"
        ).read_text(encoding="utf-8")

        self.assertIn("_lock", source)
        self.assertIn("单写者", source)
        registry = VerificationRegistry()
        self.assertTrue(hasattr(registry, "_lock"))


if __name__ == "__main__":
    unittest.main()
