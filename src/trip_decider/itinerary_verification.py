"""核实模式 v0：逐条核验别处排好的行程断言。

**为什么要有它**：第二次宿主实测里，宿主在 trip-decider 卡住后回退去 web search，
自己排了一份行程——车次、时刻、票价一应俱全，**全程没有一句话说得出出处**。
那份行程可能对，也可能不对，用户没有办法知道是哪一种。核实模式就是把「哪条是真
查到的、哪条对不上、哪条查无实据」这件事本身做成能力。

**v0 的范围**（已裁决）：

* 只核 railway 域——车次存在性 / 时刻 / 票价；
* 入参是**结构化断言列表**，半结构化文本解析放 v1；
* 无状态单次服务，不建 run；
* 计数式总评，计数不加权。

**三档而不是两档**：`sourced`（查到且对得上）/ `conflicting`（查到但对不上）/
`unknown`（没查到）。`unknown` **不是**「假」——12306 查不到某趟车可能是因为
日期超出预售期、站名写法不同、或者网络故障，这些都不等于那趟车不存在。把
「查无实据」说成「错」是这个工具最容易犯也最不该犯的错。

**不做的事**：不排行程、不改行程、不给建议行程。它只回答「你手上这份，哪些
站得住」。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import time

from trip_decider.evidence_broker import FRESHNESS_POLICIES
from trip_decider.evidence_core import (
    FRESHNESS_FRESH,
    SUPPORT_CONFLICTING,
    SUPPORT_SOURCED,
    SUPPORT_UNKNOWN,
    combine_token,
    resolve_freshness,
)
from trip_decider.intercity_rail import _RailClient, _RailFailure, _Train

#: 一条铁路断言必须有的字段。少任何一个都没法核——不是「核不出」而是
#: 「不知道要核什么」，所以在入口就拒，并说清缺哪个。
RAILWAY_ASSERTION_REQUIRED_FIELDS = (
    "train_code",
    "origin_station",
    "destination_station",
    "departure_at",
)

#: 可选字段：给了就核，不给就不核。不给不算缺陷。
RAILWAY_ASSERTION_OPTIONAL_FIELDS = ("arrival_at", "price_cny")

#: 票价对比的容差（元）。12306 的二等座票价按席别浮动，同一趟车不同日期也可能
#: 差几块。超出这个范围才算冲突——否则会把正常浮动报成「行程有错」。
_PRICE_TOLERANCE_CNY = Decimal("0.5")

#: 时刻对比的容差（分钟）。0 表示必须完全一致：时刻表是精确数据，差一分钟就是
#: 抄错了或看的是别的车次，没有「差不多」的余地。
_TIME_TOLERANCE_MINUTES = 0


@dataclass(frozen=True)
class VerifiedFinding:
    """一条断言的核验结论。"""

    index: int
    verdict: str
    claim: dict[str, object]
    observed: dict[str, object] | None
    mismatches: tuple[dict[str, object], ...]
    reason: str | None
    retrieved_at: str | None
    suggested_action: str | None

    def token(self, *, now: datetime | None = None) -> str:
        """这条结论的展示 token，按**真实**采集时刻算。

        R2：核验路径**不得抬升**证据状态。一条 6 小时前采到的时刻表，在别处
        读是 ``sourced_stale``，从核验里读出来也必须是 ``sourced_stale``——
        「刚核过」指的是刚做过比对，不是数据刚采到。

        计算走 `evidence_core` 的同一套实现，不在这里另写一份判定（D19）。
        """

        return verification_token(
            self.verdict,
            self.retrieved_at,
            now=now,
        )

    def to_dict(self, *, now: datetime | None = None) -> dict[str, object]:
        return {
            "index": self.index,
            "verdict": self.verdict,
            "claim": dict(self.claim),
            "observed": dict(self.observed) if self.observed else None,
            "mismatches": [dict(item) for item in self.mismatches],
            "reason": self.reason,
            "retrieved_at": self.retrieved_at,
            "token": self.token(now=now),
            "suggested_action": self.suggested_action,
        }


#: 核验读的是哪个 data_type 的容差。与规划链路读同一张策略表——**容差只有一份**，
#: 核验不能自带一个更宽松的（那就是变相抬升新鲜度）。
RAILWAY_DATA_TYPE = "railway_schedule_fare"

#: verdict → support 分量。三档判定与两轴模型的对应关系，只此一处。
_VERDICT_SUPPORT = {
    "sourced": SUPPORT_SOURCED,
    "conflicting": SUPPORT_CONFLICTING,
    "unknown": SUPPORT_UNKNOWN,
}


def verification_token(
    verdict: str,
    retrieved_at: object,
    *,
    now: datetime | None = None,
) -> str:
    """按读取时刻重算核验 token，避免登记处缓存把新鲜度冻住。"""

    support = _VERDICT_SUPPORT[verdict]
    if support in {SUPPORT_CONFLICTING, SUPPORT_UNKNOWN}:
        # 这两个吸收 freshness——查不到/对不上，谈不上新不新鲜。
        return combine_token(support, FRESHNESS_FRESH)
    freshness = resolve_freshness(
        retrieved_at,
        now=now or datetime.now().astimezone(),
        tolerance_seconds=FRESHNESS_POLICIES[
            RAILWAY_DATA_TYPE
        ].stale_ttl_seconds,
    )
    return combine_token(support, freshness.value)


def verify_railway_assertions(
    assertions: Sequence[Mapping[str, object]],
    *,
    client_factory=_RailClient,
    now=None,
) -> dict[str, object]:
    """逐条核验铁路断言。

    每条断言各自独立：一条查不到不影响其余各条。整份查询共用一个 12306 会话，
    因为会话初始化本身就要好几秒，每条都重来会把响应时间推过 I13 的上界。
    """

    if not isinstance(assertions, Sequence) or isinstance(assertions, (str, bytes)):
        raise ValueError("assertions must be a list")
    claims = list(assertions)
    if not claims:
        raise ValueError("assertions must not be empty")

    started = time.monotonic()
    findings: list[VerifiedFinding] = []

    # 先把形状不合格的挑出来。它们不消耗网络，也不该因为网络失败而变成 unknown
    # ——「你没告诉我车次号」和「我查不到这趟车」是两回事。
    checkable: list[tuple[int, Mapping[str, object]]] = []
    for index, claim in enumerate(claims, start=1):
        problem = _shape_problem(claim)
        if problem is None:
            checkable.append((index, claim))
            continue
        findings.append(
            VerifiedFinding(
                index=index,
                verdict="unknown",
                claim=_claim_view(claim),
                observed=None,
                mismatches=(),
                reason=problem,
                retrieved_at=None,
                suggested_action=(
                    "补齐这条断言的必填字段后重新提交："
                    + "、".join(RAILWAY_ASSERTION_REQUIRED_FIELDS)
                ),
            )
        )

    if checkable:
        findings.extend(
            _verify_against_live_rail(
                checkable,
                client_factory=client_factory,
            )
        )

    findings.sort(key=lambda item: item.index)
    return {
        "artifact_kind": "ItineraryVerification",
        "domain": "railway",
        "findings": [finding.to_dict() for finding in findings],
        "summary": summarize(findings),
        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        "scope_note": (
            "v0 只核铁路域（车次存在性、时刻、票价）。住宿、门票、当地交通"
            "未核验——没有核验不等于没有问题。"
        ),
    }


def split_by_shape(
    assertions: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[tuple[int, Mapping[str, object]]]]:
    """把「一眼就知道不合格的」与「要实采才知道的」分开。

    形状问题**不消耗网络**，所以可以在工具调用的同一次往返里就回给宿主
    （`verification_registry` 的「首批可秒回」）。它们也不该因为网络失败而变成
    unknown——「你没告诉我车次号」和「我查不到这趟车」是两回事。
    """

    immediate: list[dict[str, object]] = []
    checkable: list[tuple[int, Mapping[str, object]]] = []
    for index, claim in enumerate(assertions, start=1):
        problem = _shape_problem(claim)
        if problem is None:
            checkable.append((index, claim))
            continue
        immediate.append(
            VerifiedFinding(
                index=index,
                verdict="unknown",
                claim=_claim_view(claim),
                observed=None,
                mismatches=(),
                reason=problem,
                retrieved_at=None,
                suggested_action=(
                    "补齐这条断言的必填字段后重新提交："
                    + "、".join(RAILWAY_ASSERTION_REQUIRED_FIELDS)
                ),
            ).to_dict()
        )
    return immediate, checkable


def verify_checkable_incrementally(
    checkable: Sequence[tuple[int, Mapping[str, object]]],
    *,
    report: Callable[[Mapping[str, object]], None],
    client_factory=_RailClient,
) -> None:
    """逐条实采并**逐条上报**，供后台线程调用。

    逐条而不是攒齐再交：宿主轮询时能看到进度，也能在部分结果上先做判断。
    一条查不到不影响其余各条——这一点与同步版一致。
    """

    for finding in _iter_verify_against_live_rail(
        list(checkable),
        client_factory=client_factory,
    ):
        report(finding.to_dict())


def summarize_dicts(findings: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """按已落成 dict 的结论算总评。

    与 `summarize` 是同一套计数，入参形态不同：分批核验在登记处只留 dict。
    计数规则不在这里重写一遍——转回 verdict 列表交给同一个实现（D19）。
    """

    counts = {"sourced": 0, "conflicting": 0, "unknown": 0}
    flagged: list[int] = []
    for finding in findings:
        verdict = str(finding.get("verdict"))
        if verdict not in counts:
            continue
        counts[verdict] += 1
        if verdict in {"conflicting", "unknown"}:
            flagged.append(int(finding.get("index") or 0))
    flagged.sort()
    total = sum(counts.values())
    sentence = (
        f"{total} 条断言："
        f"{counts['sourced']} 条有据、"
        f"{counts['conflicting']} 条冲突、"
        f"{counts['unknown']} 条查无实据"
    )
    if flagged:
        sentence += (
            "，建议出发前确认第 "
            + "、".join(str(index) for index in flagged)
            + " 条"
        )
    return {
        "total": total,
        "sourced": counts["sourced"],
        "conflicting": counts["conflicting"],
        "unknown": counts["unknown"],
        "needs_confirmation": flagged,
        "sentence": sentence,
    }


def summarize(findings: Sequence[VerifiedFinding]) -> dict[str, object]:
    """计数式总评。**计数不加权**（已裁决）。

    不加权是有意的：一条票价差 3 块和一条车次根本不存在，孰轻孰重取决于用户
    在乎什么，不该由工具替他定。工具只把数报准，把该确认的条目点名。
    """

    counts = {"sourced": 0, "conflicting": 0, "unknown": 0}
    for finding in findings:
        counts[finding.verdict] += 1
    flagged = sorted(
        finding.index
        for finding in findings
        if finding.verdict in {"conflicting", "unknown"}
    )
    total = len(findings)
    sentence = (
        f"{total} 条断言："
        f"{counts['sourced']} 条有据、"
        f"{counts['conflicting']} 条冲突、"
        f"{counts['unknown']} 条查无实据"
    )
    if flagged:
        sentence += (
            "，建议出发前确认第 "
            + "、".join(str(index) for index in flagged)
            + " 条"
        )
    return {
        "total": total,
        "sourced": counts["sourced"],
        "conflicting": counts["conflicting"],
        "unknown": counts["unknown"],
        "needs_confirmation": flagged,
        "sentence": sentence,
    }


def _shape_problem(claim: object) -> str | None:
    if not isinstance(claim, Mapping):
        return "assertion_not_an_object"
    absent = [
        field
        for field in RAILWAY_ASSERTION_REQUIRED_FIELDS
        if not str(claim.get(field, "")).strip()
    ]
    if absent:
        return "missing_fields:" + ",".join(absent)
    try:
        _wall_time(str(claim["departure_at"]))
    except ValueError:
        return "departure_at_not_local_iso"
    arrival = claim.get("arrival_at")
    if arrival is not None and str(arrival).strip():
        try:
            _wall_time(str(arrival))
        except ValueError:
            return "arrival_at_not_local_iso"
    price = claim.get("price_cny")
    if price is not None and not _is_number(price):
        return "price_cny_not_a_number"
    return None


def _verify_against_live_rail(
    checkable: Sequence[tuple[int, Mapping[str, object]]],
    *,
    client_factory,
) -> list[VerifiedFinding]:
    return list(
        _iter_verify_against_live_rail(
            checkable,
            client_factory=client_factory,
        )
    )


def _iter_verify_against_live_rail(
    checkable: Sequence[tuple[int, Mapping[str, object]]],
    *,
    client_factory,
):
    """逐条产出结论；同步入口仅负责把这个迭代器收集成列表。"""

    client = client_factory()
    try:
        try:
            client.initialize_web_session()
            name_to_code, code_to_name = client.station_codes()
        except (_RailFailure, OSError, ValueError) as error:
            # 会话建不起来，全部条目都是 unknown——**不是 conflicting**。
            # 逐条 yield 同样重要：即使失败结论很多，宿主也能看到进度。
            for index, claim in checkable:
                yield VerifiedFinding(
                    index=index,
                    verdict="unknown",
                    claim=_claim_view(claim),
                    observed=None,
                    mismatches=(),
                    reason=f"rail_session_unavailable:{type(error).__name__}",
                    retrieved_at=None,
                    suggested_action="12306 连不上，稍后重试本次核验",
                )
            return

        # 值是 (车次列表, 那一次的采集时刻)——时刻与数据同生共死（R2）。
        schedule_cache: dict[
            tuple[str, str, date], tuple[list[_Train], str]
        ] = {}
        for index, claim in checkable:
            yield _verify_one(
                index,
                claim,
                client=client,
                name_to_code=name_to_code,
                code_to_name=code_to_name,
                schedule_cache=schedule_cache,
            )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except (OSError, ValueError):
                # 结果已经采到；关闭会话失败不应把整份核验改判成失败。
                pass


def _verify_one(
    index: int,
    claim: Mapping[str, object],
    *,
    client,
    name_to_code: Mapping[str, str],
    code_to_name: Mapping[str, str],
    schedule_cache: dict[tuple[str, str, date], tuple[list[_Train], str]],
) -> VerifiedFinding:
    origin = str(claim["origin_station"]).strip()
    destination = str(claim["destination_station"]).strip()
    departure = _wall_time(str(claim["departure_at"]))

    unknown_stations = [
        name for name in (origin, destination) if name not in name_to_code
    ]
    if unknown_stations:
        return VerifiedFinding(
            index=index,
            verdict="unknown",
            claim=_claim_view(claim),
            observed=None,
            mismatches=(),
            reason="station_name_not_recognized:" + ",".join(unknown_stations),
            # 一个字节都没取到，就不能盖一个采集时刻（R2）。
            retrieved_at=None,
            suggested_action=(
                "12306 用的是车站全称（如「上海虹桥」而不是「上海」）。"
                "换成全称后重新提交这一条"
            ),
        )

    key = (
        name_to_code[origin],
        name_to_code[destination],
        departure.date(),
    )
    if key not in schedule_cache:
        try:
            fetched = client.query_direct(
                travel_date=departure.date(),
                origin_code=key[0],
                destination_code=key[1],
                station_names=dict(code_to_name),
            )
        except (_RailFailure, OSError, ValueError) as error:
            return VerifiedFinding(
                index=index,
                verdict="unknown",
                claim=_claim_view(claim),
                observed=None,
                mismatches=(),
                reason=f"schedule_query_failed:{type(error).__name__}",
                retrieved_at=None,
                suggested_action="这一段没查成，稍后重试",
            )
        # 采集时刻在**取到之后**记，并与数据一起存。多条断言共用一次查询时，
        # 后来的那些必须报**那一次**的时刻，不能各自盖一个「现在」（R2）。
        schedule_cache[key] = (
            fetched,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        )

    trains, retrieved_at = schedule_cache[key]
    wanted = str(claim["train_code"]).strip().upper()
    candidates = [
        train for train in trains if train.train_code.upper() == wanted
    ]
    # 同一个车次号可能在一次查询里出现多条。2026-08-04 实测（用例见
    # tests/test_itinerary_verification.py DuplicateTrainCodeCase）：按市名查，
    # 12306 会把该市各始发站的车一并返回，同一车次号出现两次——始发站不同、
    # 发车时刻不同、二等座票价也差 10 元。直接取第一条会拿另一条腿的时刻和票价
    # 去对断言，报出一个并不存在的冲突。
    if len(candidates) > 1:
        exact = [
            train
            for train in candidates
            if train.origin_station == origin
            and train.destination_station == destination
        ]
        candidates = exact or candidates
    if len(candidates) > 1:
        on_time = [
            train
            for train in candidates
            if _minutes_apart(train.departure_at, departure)
            <= _TIME_TOLERANCE_MINUTES
        ]
        if len(on_time) == 1:
            candidates = on_time
    if len(candidates) > 1:
        # 还是分不清就**不猜**。列出各条腿让人自己指定始发站——猜错会报出一个
        # 假冲突，那比说「你得说清是哪一趟」坏得多。
        return VerifiedFinding(
            index=index,
            verdict="unknown",
            claim=_claim_view(claim),
            observed={
                "ambiguous_legs": [
                    {
                        "origin_station": train.origin_station,
                        "destination_station": train.destination_station,
                        "departure_at": train.departure_at.isoformat(
                            timespec="minutes"
                        ),
                        "arrival_at": train.arrival_at.isoformat(
                            timespec="minutes"
                        ),
                    }
                    for train in candidates
                ]
            },
            mismatches=(),
            reason="multiple_legs_share_this_train_code",
            retrieved_at=retrieved_at,
            suggested_action=(
                f"{wanted} 在这条线路上有多条腿（始发站不同）。"
                "请把 origin_station 写成具体的始发站全称后重新提交这一条"
            ),
        )
    match = candidates[0] if candidates else None
    if match is None:
        return VerifiedFinding(
            index=index,
            verdict="unknown",
            claim=_claim_view(claim),
            observed={
                "same_route_train_codes": sorted(
                    train.train_code for train in trains
                )[:12],
                "same_route_train_count": len(trains),
            },
            retrieved_at=retrieved_at,
            mismatches=(),
            reason="train_not_found_on_this_route_and_date",
            suggested_action=(
                "这一天这条线路上没查到该车次。可能是车次号写错、日期不对，"
                "或超出 12306 预售期——请人工到 12306 确认"
            ),
        )

    mismatches: list[dict[str, object]] = []
    observed: dict[str, object] = {
        "train_code": match.train_code,
        "origin_station": match.origin_station,
        "destination_station": match.destination_station,
        "departure_at": match.departure_at.isoformat(timespec="minutes"),
        "arrival_at": match.arrival_at.isoformat(timespec="minutes"),
    }
    if _minutes_apart(match.departure_at, departure) > _TIME_TOLERANCE_MINUTES:
        mismatches.append(
            {
                "field": "departure_at",
                "claimed": departure.isoformat(timespec="minutes"),
                "observed": match.departure_at.isoformat(timespec="minutes"),
            }
        )
    arrival_claim = claim.get("arrival_at")
    if arrival_claim is not None and str(arrival_claim).strip():
        arrival = _wall_time(str(arrival_claim))
        if _minutes_apart(match.arrival_at, arrival) > _TIME_TOLERANCE_MINUTES:
            mismatches.append(
                {
                    "field": "arrival_at",
                    "claimed": arrival.isoformat(timespec="minutes"),
                    "observed": match.arrival_at.isoformat(timespec="minutes"),
                }
            )

    price_claim = claim.get("price_cny")
    if price_claim is not None and _is_number(price_claim):
        try:
            observed_price = client.second_class_price(
                train=match,
                travel_date=departure.date(),
            )
        except (_RailFailure, OSError, ValueError):
            observed["price_cny"] = None
            observed["price_note"] = "价格未查到，本条只核了车次与时刻"
        else:
            observed["price_cny"] = float(observed_price)
            if abs(Decimal(str(price_claim)) - observed_price) > _PRICE_TOLERANCE_CNY:
                mismatches.append(
                    {
                        "field": "price_cny",
                        "claimed": float(price_claim),
                        "observed": float(observed_price),
                        "note": "二等座实时票价",
                    }
                )

    if mismatches:
        return VerifiedFinding(
            index=index,
            verdict="conflicting",
            claim=_claim_view(claim),
            observed=observed,
            mismatches=tuple(mismatches),
            reason=None,
            retrieved_at=retrieved_at,
            suggested_action="按实查值更正这一条",
        )
    return VerifiedFinding(
        index=index,
        verdict="sourced",
        claim=_claim_view(claim),
        observed=observed,
        mismatches=(),
        reason=None,
        retrieved_at=retrieved_at,
        suggested_action=None,
    )


def _claim_view(claim: object) -> dict[str, object]:
    if not isinstance(claim, Mapping):
        return {"raw": repr(claim)[:200]}
    return {
        key: claim.get(key)
        for key in (
            *RAILWAY_ASSERTION_REQUIRED_FIELDS,
            *RAILWAY_ASSERTION_OPTIONAL_FIELDS,
        )
        if key in claim
    }


def _wall_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is not None:
        raise ValueError("assertion times must be local ISO without offset")
    return parsed


def _minutes_apart(left: datetime, right: datetime) -> float:
    return abs((left - right).total_seconds()) / 60.0


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(
        value, bool
    )


__all__ = [
    "RAILWAY_ASSERTION_REQUIRED_FIELDS",
    "RAILWAY_ASSERTION_OPTIONAL_FIELDS",
    "VerifiedFinding",
    "verification_token",
    "summarize",
    "verify_railway_assertions",
    "split_by_shape",
    "verify_checkable_incrementally",
    "summarize_dicts",
]
