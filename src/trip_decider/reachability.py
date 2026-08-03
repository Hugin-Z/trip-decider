"""可达性：Plan-backed 候选的准入门槛与唯一排序判据（能力 A v0）。

裁决 1 把「粗粒度可行方案」定义为三件事：**往返车次（实查）+ 净可玩时长 ≥ 阈值
+ ≥1 个匹配主题的锚点 POI**。前两件在本模块，第三件在预筛（主题命中）与
web 采集（锚点 POI）。

**门槛是过滤不是降权**（裁决落点 1）：车次查不到的目的地**不进候选集**。
上一轮的实证是这条纪律的由来——候选生成器提出了铁路采集器解析不出车站身份的
城市（乌鲁木齐），动作循环因此在 ACTIONS_AVAILABLE / NEED_USER_INPUT 之间震荡
八轮不收敛。那不是排得不好，是违反产品定义（`capability-a-design.md` §1.3）。

**判据用现有 token 表达，不引第二套**：railway 域的 token 其 support 必须是
``sourced``。I6 的「实现数 = 1」因此不被破坏。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from trip_decider.evidence_core import token_support
from trip_decider.evidence_projection import project_domain

__all__ = [
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

    三种不准入，各有可查的原因：车次没查到 / 车次结构不全 / 净可玩时长不足。
    """

    if railway_item is None:
        return Reachability(False, "railway_not_collected", None, None, None)

    verdict = project_domain({"railway": railway_item}, "railway", now=now)
    if token_support(verdict.token) != "sourced":
        # 门槛用现有 token 表达（裁决落点 1）：support 不是 sourced 就不进。
        # 这一支覆盖 unknown / conflicting / estimated 三种，它们的共同点是
        # 「这趟车到底有没有」这件事没有实采支撑。
        return Reachability(
            False,
            f"railway_support_{token_support(verdict.token)}",
            None,
            None,
            None,
        )

    from trip_decider.evidence_projection import item_facts, usable_fact_values

    usable = usable_fact_values(item_facts(railway_item))
    outbound = _leg_seconds(usable.get("outbound"))
    inbound = _leg_seconds(usable.get("return"))
    if outbound is None or inbound is None:
        return Reachability(
            False,
            "railway_legs_incomplete",
            None,
            outbound,
            inbound,
        )

    playable = net_playable_seconds(
        window_seconds=window_seconds,
        outbound_seconds=outbound,
        return_seconds=inbound,
    )
    if playable < int(window_seconds * fraction):
        return Reachability(
            False,
            "net_playable_below_threshold",
            playable,
            outbound,
            inbound,
        )
    return Reachability(True, None, playable, outbound, inbound)
