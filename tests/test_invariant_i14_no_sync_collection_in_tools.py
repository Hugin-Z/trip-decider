"""I14：MCP 工具处理函数内不得出现同步网络实采。

**事故**（Claude Desktop 第四次实测，2026-08-04）：`verify_itinerary` 首次被真
宿主调用即 4 分钟无响应，宿主回退 web search。同步实采堵死了这次调用。

**为什么要一条结构约束，而不是继续靠 I13 的计时**：

I13 是**行为**判定——「这次调用有没有超时」。它需要一个能触发实采的场景、一个
能把实采变慢的注入点，还需要有人记得给新工具写探针（第四次实测就是漏了探针）。
本轮已把 I13 改成扫描式，但它仍然只在**跑得到那条分支**时才看得见问题。

I14 是**结构**判定——「这段代码里有没有同步实采」。不需要触发、不需要注入、
不需要跑到。两条一起才够：I13 抓「跑起来慢」，I14 抓「结构上就会慢」。

**判定方法**：从每个 MCP 工具处理函数出发，在 `src/trip_decider/` 内做名字级
调用闭包遍历，命中网络原语即红。

**这个判定的已知局限**（写在这里而不是假装没有）：按**函数名**匹配，不做别名
与动态分派分析。所以它可能漏掉「先把采集器赋给变量再调」这类写法，也可能误报
同名的无关函数。它抓的是「直接或经几层调用摸到网络」这一最常见形状——第四次
事故正是这个形状。漏掉的那些由 I13 的计时兜底。
"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

_SOURCE_ROOT = Path("src/trip_decider")
_SERVER = _SOURCE_ROOT / "mcp_server.py"

#: 网络原语。摸到任何一个就算「同步实采」。
#:
#: 前两个是真正发请求的地方；`_RailClient` 是 12306 会话（构造即握手）；
#: 后面几个是各采集器的公开入口——它们最终都落到前面那些上，但列出来能让报错
#: 直接指向「你调的是哪个采集器」而不是一个底层函数名。
_NETWORK_PRIMITIVES = frozenset(
    {
        "urlopen",
        "_http_get",
        "_RailClient",
        "collect_railway_evidence",
        "collect_map_evidence",
        "collect_live_destination_profile",
        "estimate_live_public_transport_segments",
        "search_live_destination_candidates",
        "_transit_route_value",
        "_route_value",
        "verify_railway_assertions",
    }
)

#: **异步边界**：传进这些函数的东西在别的线程里跑，不算本次调用的同步实采。
#: 扫描遇到它们时**不跟进实参子树**。
#:
#: 名字都带 background / spawn 不是巧合——异步边界必须在调用点一望即知，
#: 否则读代码的人和扫描器都分不清「这行会等」和「这行不会等」。
_ASYNC_DISPATCH = frozenset(
    {"start_background", "_spawn", "_spawn_action_loop"}
)

#: 已知会摸到网络、但**有意保留**的入口，连同理由。
#:
#: 这不是豁免清单而是**登记簿**：每一条都要说清为什么这次调用不会把宿主拖死，
#: 并且**理由本身要另有用例钉住**——只写一句话的豁免等于没有豁免。
_REGISTERED_EXPOSURES: dict[str, str] = {
    "__read_time_refetch__": (
        "读取期重采（trip_query._refetcher_for → live_refetcher）确实是同步实采，"
        "但 MCP 这条路上它被构造期开关关掉了（TripQueryService(live_refetch=False)，"
        "trip_services.build_trip_services 不传这个参数）。只有 product_web 会打开。"
        "静态扫描看不见运行期开关，所以在这里登记；"
        "开关真的是关的这件事由 ReadTimeRefetchIsOffForMCPCase 钉住。"
    ),
}

#: 上面那条豁免覆盖的调用链末端。命中这些的路径按已登记处理。
_REFETCH_TRAIL = ("_refetcher_for", "live_refetcher")


def _tool_handlers() -> dict[str, ast.FunctionDef]:
    """从 `mcp_server.py` 取出所有被 `@server.tool(...)` 装饰的处理函数。

    按装饰器取，不按命名约定——命名约定会漏掉改了名的，而装饰器就是「它是不是
    一个对外工具」的唯一真实判据。
    """

    tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
    handlers: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            func = call.func if call is not None else decorator
            if isinstance(func, ast.Attribute) and func.attr == "tool":
                handlers[node.name] = node
    return handlers


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


#: 这些名字在代码库里到处都是，按名字连边只会连出假路径
#: （实测：`TripMCPError → __init__ → VerificationRegistry → collect → _http_get`
#: 整条都是假的——`collect` 是个形参名，`start` 撞上了三个无关方法）。
#: 跳过它们会**漏**掉真的经由它们的路径，这是本判定已知且接受的代价，
#: 由 I13 的计时兜底。
_TOO_GENERIC = frozenset(
    {"__init__", "start", "collect", "read", "run", "get", "close", "report"}
)


def _definitions() -> tuple[dict[str, list[ast.AST]], dict[int, set[str]]]:
    """名字 → 定义节点，外加「每个定义所在模块导入了哪些名字」。

    只按名字连边会连出大量假路径；这里额外记下每个模块的导入名，让 `ast.Name`
    形式的调用**只在本模块定义或本模块导入过**时才连边。属性调用
    （`self.x.foo()`）拿不到模块信息，退回按名字连——但跳过 `_TOO_GENERIC`。
    """

    table: dict[str, list[ast.AST]] = {}
    visible: dict[int, set[str]] = {}
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        local: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local.add(node.name)
            elif isinstance(node, ast.ImportFrom):
                local.update(alias.asname or alias.name for alias in node.names)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                table.setdefault(node.name, []).append(node)
                visible[id(node)] = local
    return table, visible


def _outgoing(node: ast.AST, visible: set[str]) -> list[str]:
    """这个定义体里，值得跟进去的调用名。

    **提到网络原语就算数，不限于调用它。** `verify_railway_assertions` 的网络
    入口是形参默认值 `client_factory=_RailClient`——真正的调用写成
    `client_factory(...)`，按调用名根本看不见。把采集器当值传来传去和直接调它
    是同一件事，所以对原语只看「有没有提到」。这一条是本文件的自检用例逼出来
    的：改之前扫描连已知的采集入口都看不出摸网络。
    """

    skip: set[int] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            label = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else None
            )
            if label in _ASYNC_DISPATCH:
                for argument in (*child.args, *(k.value for k in child.keywords)):
                    for inner in ast.walk(argument):
                        skip.add(id(inner))

    names: list[str] = []
    for child in ast.walk(node):
        if id(child) in skip:
            continue
        if isinstance(child, ast.Name) and child.id in _NETWORK_PRIMITIVES:
            names.append(child.id)
            continue
        if isinstance(child, ast.Attribute) and child.attr in _NETWORK_PRIMITIVES:
            names.append(child.attr)
            continue
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            # 普通调用：必须是本模块可见的名字，否则是形参/局部变量
            if func.id in visible:
                names.append(func.id)
        elif isinstance(func, ast.Attribute) and func.attr not in _TOO_GENERIC:
            names.append(func.attr)
    return names


def _reaches_network(
    start: ast.AST,
    table: dict[str, list[ast.AST]],
    visible: dict[int, set[str]],
    *,
    start_visible: set[str] | None = None,
) -> list[str]:
    """从 start 出发做调用闭包 BFS，返回第一条摸到网络原语的路径。"""

    seen: set[str] = set()
    queue: list[tuple[ast.AST, set[str], list[str]]] = [
        (start, start_visible if start_visible is not None else set(), [])
    ]
    while queue:
        node, scope, path = queue.pop(0)
        for name in _outgoing(node, scope):
            if name in _NETWORK_PRIMITIVES:
                return [*path, name]
            if name in seen or name not in table:
                continue
            seen.add(name)
            for definition in table[name]:
                queue.append(
                    (definition, visible.get(id(definition), set()), [*path, name])
                )
    return []


class NoSynchronousCollectionInToolsCase(unittest.TestCase):
    def setUp(self) -> None:
        self.handlers = _tool_handlers()
        self.table, self.visible = _definitions()
        server_imports = set()
        tree = ast.parse(_SERVER.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                server_imports.update(
                    alias.asname or alias.name for alias in node.names
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                server_imports.add(node.name)
        self.server_scope = server_imports

    def test_the_scan_actually_found_the_tools(self) -> None:
        """扫描本身要能被证伪：找不到工具就不是「全绿」而是「没在看」。"""

        self.assertGreaterEqual(
            len(self.handlers),
            10,
            f"只扫到 {len(self.handlers)} 个工具处理函数，装饰器识别可能失效了",
        )

    def test_the_scan_can_see_network_primitives_at_all(self) -> None:
        """反向自检：明知会摸到网络的函数，扫描必须报出来。

        没有这一条，上面的「全绿」可能只是因为扫描根本什么都看不见。
        """

        collector = self.table.get("verify_railway_assertions")
        self.assertTrue(collector, "取不到已知的采集入口，扫描表构建失败")
        reached = _reaches_network(
            collector[0],
            self.table,
            self.visible,
            start_visible=self.visible.get(id(collector[0]), set()),
        )
        self.assertTrue(
            reached,
            "扫描连 verify_railway_assertions 都看不出摸网络——判定失效",
        )

    def test_no_tool_handler_reaches_a_network_primitive(self) -> None:
        offenders: dict[str, str] = {}
        for name, handler in sorted(self.handlers.items()):
            path = _reaches_network(
                handler,
                self.table,
                self.visible,
                start_visible=self.server_scope,
            )
            if not path:
                continue
            if any(step in _REFETCH_TRAIL for step in path):
                continue
            offenders[name] = " → ".join(path)

        self.assertEqual(
            {},
            offenders,
            "以下 MCP 工具的调用闭包里有同步网络实采（I14）：\n"
            + "\n".join(f"  {tool}: {trail}" for tool, trail in offenders.items())
            + "\n把实采挪到后台线程，工具只收活并立刻回执。",
        )

    def test_registered_exposures_each_carry_a_reason(self) -> None:
        blank = [
            tool
            for tool, reason in _REGISTERED_EXPOSURES.items()
            if not reason.strip()
        ]
        self.assertEqual([], blank, f"以下登记的例外没写理由：{blank}")


if __name__ == "__main__":
    unittest.main()


class ReadTimeRefetchIsOffForMCPCase(unittest.TestCase):
    """钉住上面那条豁免的理由。

    `_REGISTERED_EXPOSURES["__read_time_refetch__"]` 说「MCP 这条路上重采开关是
    关的」。只写一句话的豁免等于没有豁免——这里把那句话变成可核对的。
    """

    def test_the_shared_runtime_builds_query_without_live_refetch(self) -> None:
        from tempfile import TemporaryDirectory

        from trip_decider.trip_services import build_trip_services

        with TemporaryDirectory() as temporary:
            services = build_trip_services(Path(temporary) / "sessions")

        self.assertFalse(
            services.query._live_refetch,
            "MCP 共用的运行时打开了读取期重采——I14 的豁免理由不再成立，"
            "要么关掉它，要么把重采异步化",
        )

    def test_the_refetcher_is_none_when_the_switch_is_off(self) -> None:
        """开关关着时真的取不到重采器，而不是只是「默认参数写着 False」。"""

        from tempfile import TemporaryDirectory

        from trip_decider.trip_services import build_trip_services

        with TemporaryDirectory() as temporary:
            services = build_trip_services(Path(temporary) / "sessions")
            run_id = services.application.create_trip(
                {
                    "task_mode": "DIRECT_PLAN",
                    "origin": "甲地",
                    "destination_anchor": "乙地",
                    "destination_expression": "确定乙地",
                    "earliest_departure_at": "2026-08-11T08:00",
                    "latest_return_at": "2026-08-14T22:00",
                    "travelers": 2,
                    "total_budget_cny": 6000,
                    "pace": "relaxed",
                    "transport_preferences": ["rail"],
                }
            ).run_id

            self.assertIsNone(services.query._refetcher_for(run_id))
