"""候选池：种子目录的运行时加载与预筛（能力 A v0）。

**本模块不含任何地名。** 种子数据住在 `src/` 之外，运行时按路径加载——
I9 禁止的是 `src/` 下出现具体地名字面量，不是禁止产品使用地名数据
（`invariants.md` I9、`capability-a-design.md` §6 裁决 7）。

预筛的判据是 catalog **对自己声明的属性**（主题、建议天数），不是本模块对世界
的断言。裁决 4 原文是「粗距离预筛」，实测种子池没有坐标、取坐标 28 条要 330 秒
且 1/3 解析不到——判据因此换成自述属性，目的（砍到 ≤10 再实查车次）不变
（`capability-a-design.md` §6.1）。

**预筛只缩池，不进排序。** 排序只按可达性，见 `guided_discovery`。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
import os
from pathlib import Path

__all__ = [
    "DEFAULT_POOL_ENV",
    "MAX_PREFILTERED",
    "PoolEntry",
    "load_destination_pool",
    "prefilter_pool",
]

#: 种子目录的路径来自环境变量；未设置时回落到仓库自带的样例数据。
#: 用户可以整份替换它——这是裁决 7 的「用户可替换的配置，不是内置」。
DEFAULT_POOL_ENV = "TRIP_DECIDER_DESTINATION_POOL"

#: 预筛后进入实查的上限（裁决 4）。每个都要打一次 12306，上限直接决定
#: 一次候选生成的耗时下界。
MAX_PREFILTERED = 10


def _default_pool_path() -> Path:
    # 仓库根 / examples——本文件在 src/trip_decider/ 下，上溯三级。
    return (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "destination_catalog.json"
    )


class PoolEntry(dict):
    """种子目录里的一条。就是原始 mapping，不做投影。

    刻意不定义字段：它是**用户可替换的数据**，本模块只依赖两个键
    （``themes`` 与 ``suggested_days``）做预筛，其余原样传给下游。
    多定义一个字段就多一条对用户数据的约束。
    """


def load_destination_pool(path: str | os.PathLike[str] | None = None) -> list[PoolEntry]:
    """加载种子目录。缺失或不可解析时返回空池，不抛。

    空池不是异常：没有种子目录的部署应当如实报「无可行候选」，而不是崩在
    读取上——那会把一个配置问题表现成一次运行失败。
    """

    target = Path(path) if path is not None else None
    if target is None:
        configured = os.environ.get(DEFAULT_POOL_ENV)
        target = Path(configured) if configured else _default_pool_path()
    try:
        document = json.loads(Path(target).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    entries = (
        document.get("destinations")
        if isinstance(document, Mapping)
        else document
    )
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return []
    return [
        PoolEntry(deepcopy(dict(entry)))
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("name")
    ]


def _theme_hits(entry: Mapping[str, object], themes: Sequence[str]) -> list[str]:
    """命中的主题**逐条列出**，不打分。

    判据是子串双向包含：种子的主题词与用户的主题词粒度不同
    （「山水」vs「自然风光」），要求相等会让绝大多数正确匹配落空。
    """

    declared = [
        str(item)
        for item in (entry.get("themes") or ())
        if isinstance(item, str)
    ]
    hits: list[str] = []
    for wanted in themes:
        needle = str(wanted).strip()
        if not needle:
            continue
        for item in declared:
            if needle in item or item in needle:
                hits.append(item)
                break
    return hits


def _window_shortfall(entry: Mapping[str, object], trip_days: float) -> float:
    """种子自述的建议天数比行程窗多出多少天。0 表示装得下。

    **这是排序偏好，不是准入门槛。** 准入门槛由裁决 1 定死：往返车次（实查）+
    净可玩时长 ≥ 阈值 + ≥1 个匹配主题的锚点 POI——``suggested_days`` 不在其中。

    第一版把它做成硬过滤，实测直接把目标用例打成零候选：种子目录里 12 个山岳
    类目的地全部自述 ``min >= 2.5``，「山里待两天」于是一个候选都不剩。那是我
    在执行修正里自己加的门，超出了裁决 1 的准入集。真正该拦下「两天去不了」的
    是**实查车程算出的净可玩时长**，不是种子对自己的建议——建议是给人看的，
    不是可行性判据。
    """

    suggested = entry.get("suggested_days")
    if not isinstance(suggested, Mapping):
        return 0.0
    minimum = suggested.get("min")
    if not isinstance(minimum, (int, float)):
        return 0.0
    return max(0.0, float(minimum) - trip_days)


def prefilter_pool(
    entries: Sequence[Mapping[str, object]],
    *,
    themes: Sequence[str],
    trip_days: float,
    limit: int = MAX_PREFILTERED,
) -> list[PoolEntry]:
    """按 catalog 自述属性把池子砍到 ``limit`` 条。

    **这一步只缩池，不设门槛。** 准入门槛只有裁决 1 那三条（往返车次实查、
    净可玩时长、锚点 POI），全部在本模块之外验证。这里的两个判据（主题命中数、
    建议天数）**只决定谁进实查**，既不排除任何种子，也不进最终排序——排序只按
    实查得到的可达性（裁决 6）。

    分开是有意的：预筛用的是种子的**自述**，排序用的是对现实的**实测**。
    把自述混进排序，就等于让未经核实的标签影响结论。

    返回顺序是**稳定的**，但那只是为了让同一输入产出同一批候选，不是排名。
    """

    scored: list[tuple[int, float, int, PoolEntry]] = []
    for index, entry in enumerate(entries):
        hits = _theme_hits(entry, themes)
        # **主题命中同样只排序、不排除。** 第二次犯同一个错才发现：把它做成
        # 硬条件时，`themes=["自然风光"]` 直接清空池子——种子目录说「山水」，
        # 用户说「自然风光」，两个词互不包含。用户词表与种子词表**粒度不同**，
        # 拿它做准入门槛等于要求用户猜中种子的用词。
        #
        # 裁决 1 的准入集里那条是「≥1 个**匹配主题的锚点 POI**」——那是对
        # 真实 POI 检索结果的要求，由 web 域实采验证，不是对种子自述字符串的
        # 要求。相关性的真正把关在那里，不在这里。
        scored.append(
            (
                -len(hits),
                _window_shortfall(entry, trip_days),
                index,
                PoolEntry(entry),
            )
        )
    # 命中多的优先，其次是「按自述天数更装得下的」优先。两者都只决定**谁进
    # 实查**，不决定最终排名——排名只看实查得到的可达性（裁决 6）。
    scored.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in scored[:limit]]
