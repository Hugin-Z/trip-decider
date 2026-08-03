"""可达性：Plan-backed 候选的准入门槛与唯一排序判据（能力 A v0）。

裁决 1 把「粗粒度可行方案」定义为三件事：**往返车次（实查）+ 净可玩时长 ≥ 阈值
+ ≥1 个匹配主题的锚点 POI**。前两件在本模块，第三件在预筛（主题命中）与
web 采集（锚点 POI）。

**门槛是过滤不是降权**（裁决落点 1）：车次查不到的目的地**不进候选集**。
上一轮的实证是这条纪律的由来——候选生成器提出了铁路采集器解析不出车站身份的
城市（乌鲁木齐），动作循环因此在 ACTIONS_AVAILABLE / NEED_USER_INPUT 之间震荡
八轮不收敛。那不是排得不好，是违反产品定义（`capability-a-design.md` §1.3）。

**判据用现有 token 表达，不引第二套**：railway 域 token 的 support 必须落在
``ADMISSIBLE_SUPPORT``。I6 的「实现数 = 1」因此不被破坏。

**被拦下不等于消失**：调用方必须把不准入的目的地放进显式退回区，携带原样
token + ``reason`` + ``next_action``（`invariants.md` I7 第 4 条）。过滤与
「不静默」的共同敌人是信息消失——候选集里悄悄少一个地方，比候选卡上显示错
更难发现，因为没有东西可看。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from trip_decider.evidence_core import token_support
from trip_decider.evidence_projection import project_domain

__all__ = [
    "ADMISSIBLE_SUPPORT",
    "PLAYABLE_FRACTION",
    "Reachability",
    "assess_reachability",
    "net_playable_seconds",
]

#: 净可玩时长阈值＝行程窗总时长的这个比例（裁决 5）。
#:
#: **标记为可调，待真实数据复核。** 50% 是提案值，没有实测支撑：它说的是
#: 「一半时间花在路上就不值得去」，听起来合理，但合理不等于对。真实出行记录
#: （`PLAN.md` §9.4）积累之后按实际体感复核——那时才有证据支持一个数字。
PLAYABLE_FRACTION = 0.5

#: 可以进候选集的 support。
#:
#: `sourced` 是实采到的车次；`estimated` 是有车次但时长为推算——裁决 5 允许它
#: 参与判定并要求携带 conditional。`unknown`（没查到）与 `conflicting`（来源
#: 打架）都无法支撑「这趟能不能成行」，进退回区（I7 第 4 条）。
ADMISSIBLE_SUPPORT = frozenset({"sourced", "estimated"})


@dataclass(frozen=True)
class Reachability:
    """一个目的地的可达性判定。

    ``admitted`` 是准入结论；``reason`` 在不准入时说明**为什么**——上一轮的
    死路里，被过滤掉的目的地没有任何可查的原因，归因只能靠猜。
    """

    admitted: bool
    reason: str | None
    net_playable_seconds: int | None
    outbound_seconds: int | None
    return_seconds: int | None

    def as_payload(self) -> dict[str, object]:
        """候选卡上的可达性分项（三分项之一，裁决 6）。"""

        return {
            "admitted": self.admitted,
            "reason": self.reason,
            "net_playable_seconds": self.net_playable_seconds,
            "outbound_seconds": self.outbound_seconds,
            "return_seconds": self.return_seconds,
        }


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value > 0 else None


def _leg_seconds(value: object) -> int | None:
    if not isinstance(value, Mapping):
        return None
    duration = value.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, int):
        return None
    return duration if duration > 0 else None


def net_playable_seconds(
    *,
    window_seconds: int,
    outbound_seconds: int,
    return_seconds: int,
) -> int:
    """行程窗减去往返车程后剩下的时间。

    v0 只减车程，不减首末段接驳与缓冲——那两项要等目的地内交通实查才知道，
    而候选阶段还没走到那一步。**这让判定偏乐观**，记在这里：v1 接入当地交通
    之后应当把它们减掉，那时同一个阈值会更严。
    """

    return max(0, window_seconds - outbound_seconds - return_seconds)


def assess_reachability(
    railway_item: Mapping[str, object] | None,
    *,
    window_seconds: int,
    now: datetime,
    fraction: float = PLAYABLE_FRACTION,
) -> Reachability:
    """判定一个目的地是否够格进候选集。

    三种不准入，各有可查的原因：车次没查到（``railway_not_collected`` /
    ``railway_support_*``）、车程未知（``railway_duration_unavailable``）、
    净可玩时长不足（``net_playable_below_threshold``）。
    """

    if railway_item is None:
        return Reachability(False, "railway_not_collected", None, None, None)

    verdict = project_domain({"railway": railway_item}, "railway", now=now)
    support = token_support(verdict.token)
    if support not in ADMISSIBLE_SUPPORT:
        # 门槛用现有 token 表达（裁决落点 1），**但只拦 unknown 与 conflicting**。
        #
        # `estimated` 不拦：裁决 5 明确「estimated 可以参与可行性判定，但不得
        # 产出无条件可行结论」——它有车次，只是时长是推算的，重查也不会让它
        # 变精确。拦掉它等于永久拦死一条本来可用的路径（`evidence-axes.md`
        # §5.2.1 记的那条已知不对称，正是同一个道理）。
        #
        # 第一版把判据写成 `!= "sourced"`，连 estimated 一起拦了，与裁决 5
        # 直接矛盾；I7 的 estimated 用例当场变成 IndexError。
        return Reachability(
            False,
            f"railway_support_{support}",
            None,
            None,
            None,
        )

    from trip_decider.evidence_projection import item_facts, usable_fact_values

    usable = usable_fact_values(item_facts(railway_item))
    outbound = _leg_seconds(usable.get("outbound"))
    inbound = _leg_seconds(usable.get("return"))
    # 往返总时长优先读 `roundtrip_duration_seconds`——**那是本产品既有的字段**，
    # 采集器（`intercity_rail.py:601`）与候选卡（`guided_discovery.py:644`）
    # 都用它。第一版只认逐段的 outbound/return，于是把只带往返总时长的证据
    # 判成「结构不全」：我照着一个测试夹具的形状写判据，而不是照着管线真正
    # 携带的形状（D13 的反面——内部寻址方式必须跟着既有对外形状走）。
    roundtrip = _positive_int(usable.get("roundtrip_duration_seconds"))
    if outbound is not None and inbound is not None:
        total = outbound + inbound
    elif roundtrip is not None:
        total = roundtrip
    else:
        return Reachability(
            False,
            "railway_duration_unavailable",
            None,
            outbound,
            inbound,
        )

    playable = max(0, window_seconds - total)
    if playable < int(window_seconds * fraction):
        return Reachability(
            False,
            "net_playable_below_threshold",
            playable,
            outbound,
            inbound,
        )
    return Reachability(True, None, playable, outbound, inbound)
