"""读取层适配器：把持久化的证据形状投影为内核输入，再取回 token。

分工边界：

* ``evidence_core`` 是纯代数——它只认识 ``FactInput`` / ``FreshnessPolicy``，
  不知道 ``EvidenceItem`` 长什么样，也不知道本产品有哪些 domain。
* 本模块知道产品的持久化形状，负责把它翻译成内核输入，并把内核的判定翻译
  回读模型需要的字段。它**不自己算 token**——所有定级都委托给内核，因此
  ``invariants.md`` I6 的「实现数 = 1」不因本模块存在而被破坏。

P3a 边界：本模块只读不写。持久化内容逐字节不变，重分类不生效
（``support-reclassification.md`` §1 的 3 处高德时长在本阶段仍按 ``sourced``
投影，已在 ``tests/invariant_ledger.json`` 登记为豁免，P3b 到期）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import re
from datetime import datetime
from types import MappingProxyType
from typing import Any

from trip_decider.evidence_core import (
    FactInput,
    FactVerdict,
    FreshnessPolicy,
    SUPPORT_ESTIMATED,
    SUPPORT_SOURCED,
    SourceRef,
    derive_facts,
    evaluate_fact,
    collection_metadata,
    normalized_retrieved_at,
    support_from_legacy_name,
    token_support,
)

__all__ = [
    "DOMAIN_DATA_TYPES",
    "item_facts",
    "item_retrieved_at",
    "business_view",
    "usable_fact_values",
    "INTERNAL_CONTRACT_VIOLATION_EVENT",
    "READ_POLICIES",
    "internal_contract_violation_event",
    "is_supported",
    "project_domain",
    "reason_code_for",
    "verdict_payload",
]


# ---------------------------------------------------------------------------
# 策略表（docs/contracts/freshness-policy.md §2.2 的运行时镜像）
# ---------------------------------------------------------------------------
#
# 契约文件是权威，本表是它的手工镜像——内核要求策略由调用方注入，而读契约
# markdown 是 I/O，不能放在产品路径里。两者的一致性由
# tests/test_evidence_projection.py 机械核对，漂移会红。

READ_POLICIES: Mapping[str, FreshnessPolicy] = MappingProxyType(
    {
        "hotel_price": FreshnessPolicy(
            "hotel_price", 0, True, "block", stale_allowed=False
        ),
        "railway_schedule_fare": FreshnessPolicy(
            "railway_schedule_fare", 21600, True, "auto_refetch"
        ),
        "route_duration": FreshnessPolicy(
            "route_duration", 21600, True, "auto_refetch"
        ),
        "poi_coordinate": FreshnessPolicy(
            "poi_coordinate", 2592000, False, "flag_for_confirmation"
        ),
        "destination_profile": FreshnessPolicy(
            "destination_profile", 86400, False, "flag_for_confirmation"
        ),
        "opening_hours": FreshnessPolicy(
            "opening_hours", 86400, True, "auto_refetch"
        ),
        "ticket_price": FreshnessPolicy(
            "ticket_price", 86400, False, "flag_for_confirmation"
        ),
    }
)

# domain -> data_type。镜像 evidence_broker.query_for_intent_domain
# (evidence_broker.py:285-336) 的选择：map 域在解析过路线时是 route_duration，
# 否则是 poi_coordinate。
DOMAIN_DATA_TYPES: Mapping[str, str] = MappingProxyType(
    {
        "railway": "railway_schedule_fare",
        "web": "destination_profile",
        "map": "poi_coordinate",
    }
)

INTERNAL_CONTRACT_VIOLATION_EVENT = "evidence.internal_contract_violation"


# ---------------------------------------------------------------------------
# missing_reason -> reason_code（docs/contracts/reason-code-inventory.md §1、§4）
# ---------------------------------------------------------------------------

_REASON_CODE_BY_LITERAL: Mapping[str, str] = MappingProxyType(
    {
        # §1.1 collector_not_configured
        "collector_not_configured": "collector_not_configured",
        "amap_web_service_key_not_configured": "collector_not_configured",
        "credential": "collector_not_configured",
        # §1.2 collector_timeout
        "collector_timeout": "collector_timeout",
        # §1.3 collector_error
        "live_search_failed": "collector_error",
        "rail_http": "collector_error",
        "rail_transport": "collector_error",
        "rail_session_initialize": "collector_error",
        "rail_session_parse": "collector_error",
        "rail_station_parse": "collector_error",
        "rail_schedule_parse": "collector_error",
        "rail_price_parse": "collector_error",
        "rail_response_window": "collector_error",
        "district_parse": "collector_error",
        "poi_parse": "collector_error",
        "poi_location_parse": "collector_error",
        "route_transit_parse": "collector_error",
        "poi_projection": "collector_error",
        "output_install": "collector_error",
        "output_prepare": "collector_error",
        "plan_build": "collector_error",
        # §1.4 no_source_found
        "live_destination_profile_unavailable": "no_source_found",
        "no_live_attraction_candidates": "no_source_found",
        "exact_station_identity_not_found": "no_source_found",
        "exact_destination_district_not_found": "no_source_found",
        "railway_data_unavailable": "no_source_found",
        "map_data_unavailable": "no_source_found",
        "not_collected": "no_source_found",
        "district_resolution": "no_source_found",
        "poi_selection": "no_source_found",
        "transfer_place_resolution": "no_source_found",
        # §4.1 cancelled_by_user
        "cancelled_by_user": "cancelled_by_user",
        # §4.2 input_precondition_unmet
        "destination_anchor_not_supplied": "input_precondition_unmet",
        # §4.3 internal_contract_violation
        "input_validation": "internal_contract_violation",
        "map_point_input_validation": "internal_contract_violation",
        "route_matrix_input_validation": "internal_contract_violation",
        "public_route_matrix_input_validation": "internal_contract_violation",
        "public_route_points_input_validation": "internal_contract_violation",
        "transfer_input_validation": "internal_contract_violation",
        "route_input": "internal_contract_violation",
        # §4.4 source_rejected_by_policy
        "district_observation_policy": "source_rejected_by_policy",
        "poi_observation_policy": "source_rejected_by_policy",
    }
)

# travel_agent.py:1723 产出 "{domain}_collector_not_configured"；域信息由
# field_ref 承载，不进 reason_code（reason-code-inventory.md §1.1）。
_DOMAIN_PREFIXED_SUFFIXES = ("_collector_not_configured",)


def reason_code_for(missing_reason: object) -> str:
    """把持久化的 missing_reason 翻译成契约 reason_code。

    未登记的字面量归 ``collector_error`` 而非静默丢弃——归错比丢掉好，前者
    在 detail 里仍能看到原文，后者查不出来。
    """

    if not isinstance(missing_reason, str) or not missing_reason.strip():
        return "no_source_found"
    raw = missing_reason.strip()
    if raw in _REASON_CODE_BY_LITERAL:
        return _REASON_CODE_BY_LITERAL[raw]
    # guided_discovery.py:358 的 "collector_error:<ExceptionType>"
    head = raw.split(":", 1)[0]
    if head in _REASON_CODE_BY_LITERAL:
        return _REASON_CODE_BY_LITERAL[head]
    for suffix in _DOMAIN_PREFIXED_SUFFIXES:
        if raw.endswith(suffix):
            return _REASON_CODE_BY_LITERAL[suffix.lstrip("_")]
    return "collector_error"


def internal_contract_violation_event(
    *,
    domain: str,
    field_ref: str,
    raw_reason: str,
    data_type: str,
) -> dict[str, Any]:
    """构造排查通道的事件载荷（evidence-axes.md §2.3）。

    只构造不写入：写入必须发生在采集时。读取路径写事件会让两次读取产生不同
    的事件数，直接违反 I5 的「结构逐字节稳定」。
    """

    return {
        "event_type": INTERNAL_CONTRACT_VIOLATION_EVENT,
        "domain": domain,
        "field_ref": field_ref,
        "raw_reason": raw_reason,
        "data_type": data_type,
    }


# ---------------------------------------------------------------------------
# 投影
# ---------------------------------------------------------------------------


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _data_type_for(domain: str, facts: Iterable[Mapping[str, Any]]) -> str:
    """判据从裸 value 的 ``local_transit`` 键换成 facts 的字段前缀。"""

    if domain == "map" and any(
        str(fact.get("field", "")).startswith("local_transit")
        for fact in facts
    ):
        return "route_duration"
    return DOMAIN_DATA_TYPES.get(domain, "destination_profile")


def _retrieved_at(item: Mapping[str, object]) -> str | None:
    """按持久化形状的优先级取采集时刻：snapshot > value > sources 最大值。"""

    value = _mapping(item.get("value"))
    snapshot = _mapping(value.get("snapshot"))
    if isinstance(snapshot.get("retrieved_at"), str):
        return str(snapshot["retrieved_at"])
    freshness = _mapping(value.get("freshness"))
    if isinstance(freshness.get("retrieved_at"), str):
        return str(freshness["retrieved_at"])
    if isinstance(value.get("retrieved_at"), str):
        return str(value["retrieved_at"])
    sources = item.get("sources")
    stamps = [
        str(source["retrieved_at"])
        for source in (sources if isinstance(sources, Sequence) else ())
        if isinstance(source, Mapping)
        and isinstance(source.get("retrieved_at"), str)
    ]
    return max(stamps) if stamps else None


# 刷新失败在落盘里有四种形状，都是「采集时刻的事实」而不是展示态：
#   evidence_broker.py:377      value.refresh_failure = {missing_reason}
#   agent_actions.py:1186       value.refresh_failure = {missing_reason, attempted_at}
#   agent_actions.py:1215       value.refresh_failure = {missing_reason}
#   agent_actions.py:905        value.local_transit_refresh_failure = {stage, ...}
_REFRESH_FAILURE_KEYS = ("refresh_failure", "local_transit_refresh_failure")


def _refresh_failure(value: Mapping[str, object]) -> tuple[bool, str | None]:
    """返回 ``(是否存在刷新失败, 失败时刻或 None)``。

    两处形状不带时间戳。缺时间戳仍算存在——一条挂在该值上的刷新失败记录必然
    发生在该值采集之后，顺序是结构性保证的（``evidence-axes.md`` §3.4）。
    """

    for key in _REFRESH_FAILURE_KEYS:
        record = value.get(key)
        if isinstance(record, Mapping) and record:
            attempted = record.get("attempted_at")
            return True, attempted if isinstance(attempted, str) else None
        if isinstance(record, str) and record.strip():
            return True, None
    # 刻意不看 snapshot.attempted_at：intercity_rail.py:484 在每次采集**开始**
    # 时就写它，因此正常成功采集里它必然早于 retrieved_at。把它当刷新失败信号
    # 会在每一次正常采集上误报。只有显式的 refresh_failure 记录才算数。
    return False, None


def _sources(item: Mapping[str, object], retrieved_at: str | None) -> tuple[SourceRef, ...]:
    raw = item.get("sources")
    refs: list[SourceRef] = []
    for source in raw if isinstance(raw, Sequence) else ():
        if not isinstance(source, Mapping):
            continue
        provider = (
            source.get("provider")
            or source.get("publisher")
            or source.get("source_type")
            or "unknown-provider"
        )
        refs.append(
            SourceRef(
                provider=str(provider),
                retrieved_at=(
                    str(source["retrieved_at"])
                    if isinstance(source.get("retrieved_at"), str)
                    else retrieved_at
                ),
            )
        )
    return tuple(refs)


def _fact_from_item(
    item: Mapping[str, object],
    *,
    domain: str,
    fact_id: str,
) -> FactInput:
    """把一条持久化证据翻译成内核输入。

    P3a 不做重分类：``EvidenceStatus.SOURCED`` 一律映射到
    ``direct_observation``，包括高德路径规划时长——那 3 处在
    ``support-reclassification.md`` §1 列为 P3b 的工作，在本阶段是登记豁免项。
    """

    value = _mapping(item.get("value"))
    data_type = _data_type_for(domain, item_facts(item))
    retrieved_at = _retrieved_at(item)
    refresh_failed, refresh_failed_at = _refresh_failure(value)
    status = str(item.get("status") or "").lower()
    conflict_details = tuple(
        str(detail)
        for detail in (item.get("conflict_details") or ())
        if isinstance(detail, str)
    )

    if status == "conflicting" and conflict_details:
        return FactInput(
            fact_id=fact_id,
            data_type=data_type,
            value=dict(value) or {"domain": domain},
            derivation="direct_observation",
            sources=_sources(item, retrieved_at) or (
                SourceRef("unknown-provider", retrieved_at=retrieved_at),
            ),
            conflict_details=conflict_details,
            conflict_source_refs=tuple(
                f"{fact_id}#source-{index}"
                for index in range(max(2, len(conflict_details)))
            ),
            retrieved_at=retrieved_at,
            refresh_failed=refresh_failed,
            refresh_failed_at=refresh_failed_at,
        )

    if status == "estimated" and value:
        # P3b：持久化枚举加入 estimated 后，读取层必须认它。P3a 时该分支不存在
        # ——那时枚举里没有这个值，所有非 sourced 都落到兜底的 unknown。
        return FactInput(
            fact_id=fact_id,
            data_type=data_type,
            value=dict(value),
            derivation="api_estimate",
            sources=_sources(item, retrieved_at)
            or (SourceRef("unknown-provider", retrieved_at=retrieved_at),),
            retrieved_at=retrieved_at,
            refresh_failed=refresh_failed,
            refresh_failed_at=refresh_failed_at,
        )

    if status == "sourced" and value:
        return FactInput(
            fact_id=fact_id,
            data_type=data_type,
            value=dict(value),
            derivation="direct_observation",
            sources=_sources(item, retrieved_at)
            or (SourceRef("unknown-provider", retrieved_at=retrieved_at),),
            retrieved_at=retrieved_at,
            refresh_failed=refresh_failed,
            refresh_failed_at=refresh_failed_at,
        )

    return FactInput(
        fact_id=fact_id,
        data_type=data_type,
        value=None,
        reason=reason_code_for(item.get("missing_reason")),
        retrieved_at=retrieved_at,
    )


def project_domain(
    evidence: Mapping[str, Mapping[str, object]],
    domain: str,
    *,
    now: datetime,
    fact_id: str | None = None,
    absent_reason: str = "no_source_found",
) -> FactVerdict:
    """投影一个证据域，返回内核判定。域缺席时产出 unknown。"""

    reference = fact_id or f"evidence.{domain}"
    item = evidence.get(domain)
    if not isinstance(item, Mapping):
        fact = FactInput(
            fact_id=reference,
            data_type=DOMAIN_DATA_TYPES.get(domain, "destination_profile"),
            value=None,
            reason=absent_reason,
        )
    else:
        fact = _fact_from_item(item, domain=domain, fact_id=reference)
    return evaluate_fact(fact, READ_POLICIES[fact.data_type], now=now)


def is_supported(verdict: FactVerdict) -> bool:
    """该域是否有可用支撑——取代旧代码里的「已采到 或 已过期」二值判断。

    语义等价的写法是「support 轴为 sourced」：旧的两个可用态合起来正是
    「有来源且可回读」，与新鲜与否无关。
    """

    return token_support(verdict.token) == "sourced"


def verdict_payload(verdict: FactVerdict) -> dict[str, Any]:
    """内核判定 → 对外返回值的两个字段。

    ``next_action`` 在 token 为 ``verified`` 时缺席（§5.1 双向约束），UI 因此
    可以用它的存在与否做渲染分支。
    """

    payload: dict[str, Any] = {"token": verdict.token}
    if verdict.next_action is not None:
        payload["next_action"] = dict(verdict.next_action)
    return payload


# ---------------------------------------------------------------------------
# 字段级读取（persistence-v2.md §1.3）
#
# `EvidenceItem.facts` 服务对象形态的调用方；下面两个函数服务 dict 形态的
# ——读取层拿到的大多是已落盘的 mapping，没有对象可用。两条路走同一个
# `derive_facts`，不允许出现第二套推导。

USABLE_SUPPORT = frozenset({SUPPORT_SOURCED, SUPPORT_ESTIMATED})


def item_facts(item: Any) -> tuple[Mapping[str, Any], ...]:
    """落盘证据 mapping → 字段级 facts。

    与 `EvidenceItem.facts` 同样是双读：已带 facts 键就直读，否则从 v1 的裸
    value 推导。P4-b3 生产端切换后，走的是前一条分支。
    """

    if not isinstance(item, Mapping):
        return ()
    value = item.get("value")
    if isinstance(value, Mapping) and isinstance(
        value.get("facts"), (list, tuple)
    ):
        return tuple(
            fact for fact in value["facts"] if isinstance(fact, Mapping)
        )
    status = item.get("status")
    support = (
        support_from_legacy_name(status)
        if isinstance(status, str)
        else SUPPORT_SOURCED
    )
    domain = str(item.get("domain") or "")
    conflict_details = item.get("conflict_details")
    return derive_facts(
        value,
        str(item.get("evidence_id") or domain),
        domain,
        item_support=support,
        data_type=DOMAIN_DATA_TYPES.get(domain, ""),
        retrieved_at=item_retrieved_at(item),
        reason=(
            str(item["missing_reason"])
            if isinstance(item.get("missing_reason"), str)
            else None
        ),
        conflict_details=(
            tuple(str(entry) for entry in conflict_details)
            if isinstance(conflict_details, (list, tuple))
            else ()
        ),
    )


def item_retrieved_at(item: Any) -> str | None:
    """采集时刻，按 persistence-v2.md §1.3.1 的归一顺序取。

    source 级是回落项：多个来源时取最晚的一个，因为整条证据不会比它最新的
    那次采集更旧。
    """

    if not isinstance(item, Mapping):
        return None
    sources = item.get("sources")
    stamps = [
        str(source["retrieved_at"])
        for source in (sources if isinstance(sources, (list, tuple)) else ())
        if isinstance(source, Mapping)
        and isinstance(source.get("retrieved_at"), str)
        and source["retrieved_at"]
    ]
    return normalized_retrieved_at(
        item.get("value"),
        max(stamps) if stamps else None,
    )


_PATH_STEP = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def usable_fact_values(
    facts: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """字段级可用值，**按原嵌套形状重建**。

    support 不可用的字段根本不出现——item 级 support 说不出"时刻可靠而余票
    未知"，字段级说得出。调用方因此不需要自己判断：拿不到的字段就是不该用
    的字段。

    重建而非返回扁平点号键，是因为消费端读的是 ``value["local_transit"][0]``
    这样的结构。扁平化只是 facts 的内部表示，不是对外形状。
    """

    root: dict[str, Any] = {}
    for fact in facts:
        if str(fact.get("support")) not in USABLE_SUPPORT:
            continue
        value = fact.get("value")
        if value is None:
            continue
        steps = [
            key if key else int(index)
            for key, index in _PATH_STEP.findall(str(fact.get("field", "")))
        ]
        if not steps:
            continue
        _plant(root, steps, value)
    return root


def _plant(root: dict[str, Any], steps: list[Any], value: Any) -> None:
    """把一个叶子按路径种回去，沿途缺什么建什么。

    下标可能跳号——中间那条路线整条 unknown 时它就不会出现——所以列表按
    需补 ``None`` 占位，保持其余下标不移位。
    """

    cursor: Any = root
    for step, nxt in zip(steps, steps[1:]):
        child = [] if isinstance(nxt, int) else {}
        if isinstance(step, int):
            while len(cursor) <= step:
                cursor.append(None)
            if not isinstance(cursor[step], (dict, list)):
                cursor[step] = child
            cursor = cursor[step]
        else:
            if not isinstance(cursor.get(step), (dict, list)):
                cursor[step] = child
            cursor = cursor[step]
    last = steps[-1]
    if isinstance(last, int):
        while len(cursor) <= last:
            cursor.append(None)
        cursor[last] = value
    else:
        cursor[last] = value


def business_view(item: Any) -> dict[str, Any]:
    """落盘证据 → 「业务字段 + 采集元数据」的平面视图。

    重建出的业务字段与保留下来的元数据可能落在**同一个键**上——``snapshot``
    既装着车次（事实）又装着采集时刻（元数据）。扁平 ``{**a, **b}`` 会让一边
    整个盖掉另一边；这里按键深合并，元数据叶子胜出。

    两种形态都收：落盘 dict 走 ``item_facts``，``EvidenceItem`` 走它的 ``.facts``。
    """

    if isinstance(item, Mapping):
        facts = item_facts(item)
        value = item.get("value")
    else:
        facts = getattr(item, "facts", ())
        value = getattr(item, "value", None)
    view = usable_fact_values(facts)
    for key, meta in collection_metadata(value).items():
        current = view.get(key)
        if isinstance(meta, Mapping) and isinstance(current, Mapping):
            view[key] = {**current, **meta}
        else:
            view[key] = meta
    return view
