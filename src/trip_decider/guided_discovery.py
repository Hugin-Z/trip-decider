"""Region-scoped destination comparison using existing evidence collectors."""

from __future__ import annotations

from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import time
from typing import Protocol
from uuid import uuid4

from trip_decider.evidence_core import (
    FRESHNESS_STALE,
    SUPPORT_ESTIMATED,
    SUPPORT_SOURCED,
    is_confirmed_absent,
    normalized_retrieved_at,
    token_freshness,
)
from trip_decider.evidence_projection import project_domain
from trip_decider.dynamic_discovery import dynamic_destination_seeds
from trip_decider.evidence_broker import (
    default_evidence_broker,
    EvidenceBroker,
    evidence_collected_at,
    query_for_intent_domain,
)
from trip_decider.travel_agent import (
    EvidenceItem,
    EvidenceStatus,
    TaskMode,
    TravelAgentError,
    TravelIntent,
)


class EvidenceCollector(Protocol):
    def __call__(self, intent: TravelIntent) -> EvidenceItem:
        ...


ProgressCallback = Callable[
    [str, str, Mapping[str, object] | None],
    None,
]
CancelCheck = Callable[[], bool]


_DEFAULT_TIMEOUTS = {
    "railway": 15.0,
    "map": 15.0,
    "web": 10.0,
}


@dataclass(frozen=True)
class _EvidenceCheck:
    evidence: EvidenceItem
    # 展示 token（evidence-axes.md §4.1 的 8 值），由内核算出。字段名保留
    # display_status 以免波及未改造的调用方，取值域已换。
    display_status: str
    collected_at: str | None
    from_cache: bool
    timed_out: bool = False
    next_action: Mapping[str, object] | None = None


def guided_region_seeds(
    intent: TravelIntent,
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    """Return two or three live candidates for this discovery run."""

    if intent.task_mode not in {
        TaskMode.OPEN_DISCOVERY,
        TaskMode.GUIDED_DISCOVERY,
    }:
        raise TravelAgentError(
            "destination seeds require a discovery mode"
        )
    if (
        intent.task_mode is TaskMode.GUIDED_DISCOVERY
        and not intent.destination_anchor
    ):
        raise TravelAgentError(
            "guided discovery requires a destination region"
        )
    if limit not in {2, 3}:
        raise TravelAgentError("guided candidate limit must be 2 or 3")
    return dynamic_destination_seeds(intent, limit=limit)


def preferred_direct_destination(intent: TravelIntent) -> str | None:
    """Return the strongest explicit regional seed without claiming feasibility."""

    try:
        seeds = guided_region_seeds(intent, limit=3)
    except TravelAgentError:
        return None
    name = seeds[0].get("name")
    return str(name) if isinstance(name, str) and name else None


def build_guided_comparison(
    intent: TravelIntent,
    *,
    railway_collector: EvidenceCollector,
    map_collector: EvidenceCollector | None = None,
    web_collector: EvidenceCollector | None = None,
    timeouts: Mapping[str, float] | None = None,
    run_id: str | None = None,
    evidence_broker: EvidenceBroker | None = None,
    initial_evidence: Mapping[
        str,
        Mapping[str, EvidenceItem],
    ]
    | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Check regional options concurrently and stream each completed card."""
    read_at = (clock or (lambda: datetime.now(timezone.utc)))()
    if evidence_broker is None:
        evidence_broker = default_evidence_broker()

    active_run_id = run_id or f"ephemeral-guided-{uuid4()}"
    seeds = guided_region_seeds(intent, limit=3)
    if progress is not None:
        progress(
            "comparison_started",
            intent.destination_anchor or "",
            {"candidate_count": len(seeds)},
        )
    collectors: dict[str, EvidenceCollector | None] = {
        "railway": railway_collector,
        "map": map_collector,
        "web": web_collector,
    }
    configured_timeouts = dict(_DEFAULT_TIMEOUTS)
    if timeouts is not None:
        for domain, value in timeouts.items():
            if (
                domain not in configured_timeouts
                or not isinstance(value, (int, float))
                or isinstance(value, bool)
                or float(value) <= 0
            ):
                raise TravelAgentError("invalid guided collector timeout")
            configured_timeouts[domain] = float(value)
    checks: dict[str, dict[str, _EvidenceCheck]] = {
        str(seed["id"]): {} for seed in seeds
    }
    gateways = {
        str(seed["id"]): _station_seed(seed) for seed in seeds
    }
    seed_by_id = {str(seed["id"]): seed for seed in seeds}
    options_by_id: dict[str, dict[str, object]] = {}
    emitted: set[str] = set()
    executor = ThreadPoolExecutor(
        max_workers=max(1, len(seeds) * len(collectors)),
        thread_name_prefix="guided-evidence",
    )
    pending: dict[
        Future[EvidenceItem],
        tuple[str, str, float],
    ] = {}

    for seed in seeds:
        name = str(seed["name"])
        seed_id = str(seed["id"])
        gateway = gateways[seed_id]
        if progress is not None:
            progress(
                "candidate_started",
                name,
                {
                    "destination_id": seed_id,
                    "candidate_count": len(seeds),
                },
            )
        railway_intent = replace(
            intent,
            task_mode=TaskMode.DIRECT_PLAN,
            destination_anchor=gateway,
            destination_expression=None,
            classification_basis="guided_coarse_check",
        )
        destination_intent = replace(
            intent,
            task_mode=TaskMode.DIRECT_PLAN,
            destination_anchor=name,
            destination_expression=None,
            classification_basis="dynamic_candidate_check",
        )
        for domain, collector in collectors.items():
            candidate_intent = (
                railway_intent if domain == "railway" else destination_intent
            )
            supplied = (
                initial_evidence.get(seed_id, {}).get(domain)
                if initial_evidence is not None
                else None
            )
            if (
                isinstance(supplied, EvidenceItem)
                and supplied.domain == domain
                and supplied.status.is_usable
            ):
                check = replace(
                    _check_from_evidence(supplied),
                    from_cache=True,
                )
                checks[seed_id][domain] = check
                if progress is not None:
                    progress(
                        "domain_completed",
                        name,
                        {
                            "destination_id": seed_id,
                            "domain": domain,
                            "evidence_status": check.display_status,
                            "from_cache": True,
                            "collected_at": check.collected_at,
                        },
                    )
                continue
            if collector is None:
                checks[seed_id][domain] = _missing_check(
                    domain,
                    "collector_not_configured",
                    now=read_at,
                )
                continue
            if progress is not None:
                progress(
                    "domain_started",
                    name,
                    {
                        "destination_id": seed_id,
                        "domain": domain,
                    },
                )
            future = executor.submit(collector, candidate_intent)
            pending[future] = (
                seed_id,
                domain,
                time.monotonic() + configured_timeouts[domain],
            )

    def emit_ready_options() -> None:
        for seed_id, seed_checks in checks.items():
            if seed_id in emitted or len(seed_checks) != len(collectors):
                continue
            seed = seed_by_id[seed_id]
            option = _coarse_option(
                intent,
                seed,
                gateways[seed_id],
                seed_checks,
            )
            options_by_id[seed_id] = option
            emitted.add(seed_id)
            if progress is not None:
                progress(
                    "candidate_completed",
                    str(seed["name"]),
                    {
                        "destination_id": seed_id,
                        "feasibility_status": option[
                            "feasibility_status"
                        ],
                        "option": option,
                    },
                )

    emit_ready_options()
    try:
        while pending:
            if should_cancel is not None and should_cancel():
                for future, (seed_id, domain, _deadline) in list(
                    pending.items()
                ):
                    checks[seed_id][domain] = _missing_check(
                        domain,
                        "cancelled_by_user",
                        now=read_at,
                    )
                    future.cancel()
                    del pending[future]
                emit_ready_options()
                break
            completed, _ = wait(
                tuple(pending),
                timeout=0.05,
                return_when=FIRST_COMPLETED,
            )
            for future in completed:
                seed_id, domain, _deadline = pending.pop(future)
                seed = seed_by_id[seed_id]
                try:
                    evidence = future.result()
                    if not isinstance(evidence, EvidenceItem):
                        raise TravelAgentError(
                            "guided collector returned invalid evidence"
                        )
                    if evidence.domain != domain:
                        raise TravelAgentError(
                            "guided collector returned wrong evidence domain"
                        )
                    candidate_intent = replace(
                        intent,
                        task_mode=TaskMode.DIRECT_PLAN,
                        destination_anchor=(
                            gateways[seed_id]
                            if domain == "railway"
                            else str(seed_by_id[seed_id]["name"])
                        ),
                        destination_expression=None,
                    )
                    query = query_for_intent_domain(
                        candidate_intent,
                        domain,
                    )
                    if evidence.status.is_usable:
                        collected_at = evidence_collected_at(evidence)
                        if collected_at is not None:
                            try:
                                evidence_broker.publish(
                                    run_id=active_run_id,
                                    query=query,
                                    evidence=evidence,
                                    collected_at=collected_at,
                                )
                            except TravelAgentError:
                                if progress is not None:
                                    progress(
                                        "cache_rejected",
                                        str(seed_by_id[seed_id]["name"]),
                                        {
                                            "destination_id": seed_id,
                                            "domain": domain,
                                        },
                                    )
                    else:
                        stale = evidence_broker.stale_after_failure(
                            run_id=active_run_id,
                            query=query,
                            live_failure=evidence,
                        )
                        if stale is not None:
                            evidence = stale
                    check = _check_from_evidence(evidence, now=read_at)
                    checks[seed_id][domain] = replace(
                        check,
                        from_cache=_is_stale(check.display_status),
                    )
                except Exception as error:
                    failure = _missing_check(
                        domain,
                        "collector_error:" + type(error).__name__,
                        now=read_at,
                    )
                    candidate_intent = replace(
                        intent,
                        task_mode=TaskMode.DIRECT_PLAN,
                        destination_anchor=(
                            gateways[seed_id]
                            if domain == "railway"
                            else str(seed_by_id[seed_id]["name"])
                        ),
                        destination_expression=None,
                    )
                    stale = evidence_broker.stale_after_failure(
                        run_id=active_run_id,
                        query=query_for_intent_domain(
                            candidate_intent,
                            domain,
                        ),
                        live_failure=failure.evidence,
                    )
                    checks[seed_id][domain] = (
                        replace(
                            _check_from_evidence(stale, now=read_at),
                            from_cache=True,
                        )
                        if stale is not None
                        else failure
                    )
                check = checks[seed_id][domain]
                if progress is not None:
                    progress(
                        "domain_completed",
                        str(seed["name"]),
                        {
                            "destination_id": seed_id,
                            "domain": domain,
                            "evidence_status": check.display_status,
                            "from_cache": check.from_cache,
                            "collected_at": check.collected_at,
                        },
                    )
            now = time.monotonic()
            for future, (seed_id, domain, deadline) in list(
                pending.items()
            ):
                if now < deadline:
                    continue
                future.cancel()
                del pending[future]
                checks[seed_id][domain] = _missing_check(
                    domain,
                    "collector_timeout",
                    timed_out=True,
                    now=read_at,
                )
                candidate_intent = replace(
                    intent,
                    task_mode=TaskMode.DIRECT_PLAN,
                    destination_anchor=(
                        gateways[seed_id]
                        if domain == "railway"
                        else str(seed_by_id[seed_id]["name"])
                    ),
                    destination_expression=None,
                )
                stale = evidence_broker.stale_after_failure(
                    run_id=active_run_id,
                    query=query_for_intent_domain(
                        candidate_intent,
                        domain,
                    ),
                    live_failure=checks[seed_id][domain].evidence,
                )
                if stale is not None:
                    checks[seed_id][domain] = replace(
                        _check_from_evidence(stale, now=read_at),
                        from_cache=True,
                        timed_out=True,
                    )
                if progress is not None:
                    progress(
                        "domain_timeout",
                        str(seed_by_id[seed_id]["name"]),
                        {
                            "destination_id": seed_id,
                            "domain": domain,
                            "timeout_seconds": configured_timeouts[domain],
                            "evidence_status": "MISSING",
                        },
                    )
            emit_ready_options()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    options = [
        options_by_id[str(seed["id"])]
        for seed in seeds
        if str(seed["id"]) in options_by_id
    ]
    reusable_evidence = {
        seed_id: {
            domain: check.evidence.to_dict()
            for domain, check in sorted(seed_checks.items())
        }
        for seed_id, seed_checks in sorted(checks.items())
        if len(seed_checks) == len(collectors)
    }
    return {
        "stage": (
            "open_discovery"
            if intent.task_mode is TaskMode.OPEN_DISCOVERY
            else "guided_discovery"
        ),
        "task_mode": intent.task_mode.value,
        "region_anchor": intent.destination_anchor,
        "expected_option_count": len(seeds),
        "option_count": len(options),
        "cancelled": (
            bool(should_cancel is not None and should_cancel())
        ),
        "options": options,
        "reusable_evidence": reusable_evidence,
        "selection_required": True,
        "detailed_plan_created": False,
        "conditions": [
            "每个方案均分别执行铁路、地图和网页粗检；单项超时"
            "保持MISSING，不阻塞其他方案。",
            "条件可行只表示值得继续核验，不等于详细行程已经可发布。",
        ],
    }


def _coarse_option(
    intent: TravelIntent,
    seed: Mapping[str, object],
    gateway: str,
    checks: Mapping[str, _EvidenceCheck],
) -> dict[str, object]:
    rail_check = checks["railway"]
    evidence = rail_check.evidence
    rail = _usable_fact_values(evidence)
    duration = _nonnegative_number(
        rail.get("roundtrip_duration_seconds")
    )
    known_cost = _nonnegative_number(
        rail.get("roundtrip_fare_cny")
    )
    available = _available_seconds(intent)
    playable = (
        max(0.0, available - duration)
        if duration is not None
        else None
    )
    budget_margin = (
        float(intent.total_budget_cny) - known_cost
        if known_cost is not None
        and intent.total_budget_cny is not None
        else None
    )
    # 判定点 1（p3b-gate-inventory.md §3.3，丙型）。四分支：
    #   confirmed_absent -> 已核实没有直达车，是一个确定的可行性结论
    #   sourced/estimated -> 可参与判定；estimated 必须携带 conditional（裁决 5）
    #   unknown/conflicting -> 结论未知，原因必须可见（I7）
    rail_absent = any(
        is_confirmed_absent(fact.get("value")) for fact in evidence.facts
    )
    rail_usable = (
        evidence.status.is_usable
        and not rail_absent
        and duration is not None
        and known_cost is not None
    )
    rail_sourced = rail_usable
    conditionally_feasible = (
        rail_usable
        and playable is not None
        and playable > 0
        and budget_margin is not None
        and budget_margin >= 0
    )
    if rail_absent:
        feasibility_status = "INFEASIBLE_NO_TRANSPORT"
    elif conditionally_feasible:
        feasibility_status = "CONDITIONALLY_FEASIBLE"
    else:
        feasibility_status = "UNKNOWN"
    # 裁决 5：estimated 可以参与判定，但结论必须携带一个 conditional。
    rail_conditions: list[str] = []
    if conditionally_feasible and evidence.status is EvidenceStatus.ESTIMATED:
        rail_conditions.append(
            "往返交通时长为推算值，实际耗时可能不同"
        )
    missing = [
        "当地交通难度",
        "住宿价格与可用性",
        "完整餐饮与当地交通预算",
    ]
    if not rail_sourced:
        missing.insert(0, "可用的往返铁路时刻与票价")
    if checks["map"].display_status == "MISSING":
        missing.append("目的地地图核验")
    if checks["web"].display_status == "MISSING":
        missing.append("景点开放时间和门票网页核验")
    return {
        "destination_id": seed["id"],
        "destination_anchor": seed["name"],
        "name": seed["name"],
        "region_label": seed["region_label"],
        "gateway_checked": gateway,
        "feasibility_status": feasibility_status,
        "coarse_plan_status": feasibility_status,
        "roundtrip_transport": {
            "token": rail_check.display_status,
            "duration_seconds": duration,
            "known_cost_cny": known_cost,
            "outbound": _train_summary(rail.get("outbound")),
            "return": _train_summary(rail.get("return")),
            "retrieved_at": rail_check.collected_at,
            "missing_reason": evidence.missing_reason,
            "from_cache": rail_check.from_cache,
            "timed_out": rail_check.timed_out,
        },
        "playable_time_seconds": playable,
        "local_transport_difficulty": {
            "status": "MISSING",
            "value": None,
        },
        "themes": list(seed.get("themes", [])),
        "physical_intensity": seed.get("intensity"),
        "budget_headroom_after_known_transport_cny": budget_margin,
        "evidence_statuses": [
            {
                "domain": domain,
                "token": checks[domain].display_status,
                "collected_at": checks[domain].collected_at,
                "from_cache": checks[domain].from_cache,
                "timed_out": checks[domain].timed_out,
                # conflict_details 此前被整条丢弃（基线报告 M1）。分歧的具体
                # 内容是用户裁决的唯一依据，必须原样透出。
                **(
                    {
                        "conflict_details": list(
                            checks[domain].evidence.conflict_details
                        )
                    }
                    if checks[domain].evidence.conflict_details
                    else {}
                ),
                **(
                    {"next_action": dict(checks[domain].next_action)}
                    if checks[domain].next_action is not None
                    else {}
                ),
            }
            for domain in ("railway", "map", "web")
        ],
        "evidence_missing": missing,
        "conditions": rail_conditions,
        "candidate_source_notice": (
            "候选来自本次高德POI实时检索；可行性只使用"
            "本次铁路、地图和补充事实证据。"
        ),
    }


def _check_from_evidence(
    evidence: EvidenceItem,
    *,
    now: datetime | None = None,
) -> _EvidenceCheck:
    """把一条证据定级为候选卡上的展示 token。

    定级全部委托给 ``evidence_core``（经 ``evidence_projection``）——本函数
    自己不再产出任何展示态字面量。旧实现把 ``CONFLICTING`` 折叠进 ``MISSING``
    并丢弃 ``conflict_details``（基线报告 M1，I7 第 3 条），现在四态原样保留。
    """

    verdict = project_domain(
        {evidence.domain: evidence.to_dict()},
        evidence.domain,
        now=now if now is not None else datetime.now(timezone.utc),
    )
    return _EvidenceCheck(
        evidence=evidence,
        display_status=verdict.token,
        collected_at=_evidence_collected_at(evidence),
        from_cache=False,
        next_action=(
            dict(verdict.next_action)
            if verdict.next_action is not None
            else None
        ),
    )


def _missing_check(
    domain: str,
    reason: str,
    *,
    timed_out: bool = False,
    now: datetime | None = None,
) -> _EvidenceCheck:
    item = EvidenceItem(
        evidence_id=f"guided-{domain}-missing",
        domain=domain,
        status=EvidenceStatus.MISSING,
        value=None,
        missing_reason=reason,
    )
    check = _check_from_evidence(item, now=now)
    return replace(check, timed_out=timed_out)


_USABLE_SUPPORT = frozenset({SUPPORT_SOURCED, SUPPORT_ESTIMATED})


def _is_stale(token: str) -> bool:
    """陈旧与否由读取时刻决定。

    旧实现读 ``value["freshness"]["status"]``——那是采集时冻结的判断，同一份
    落盘无论何时读都给同一个答案，正是 I5 要禁的东西。token 出自
    ``project_domain(now=...)``，换一个 now 就能换一个结论。
    """

    return token_freshness(token) == FRESHNESS_STALE


def _usable_fact_values(evidence: EvidenceItem) -> dict[str, object]:
    """字段级可用值：support 不可用的字段根本不出现。

    item 级 support 说不出"时刻可靠而余票未知"，字段级说得出
    （persistence-v2.md §1.3）。
    """

    return {
        str(fact["field"]): fact["value"]
        for fact in evidence.facts
        if str(fact.get("support")) in _USABLE_SUPPORT
        and fact.get("value") is not None
    }


def _evidence_collected_at(evidence: EvidenceItem) -> str:
    source_stamp = next(
        (
            str(source["retrieved_at"])
            for source in evidence.sources
            if isinstance(source.get("retrieved_at"), str)
            and source["retrieved_at"]
        ),
        None,
    )
    return normalized_retrieved_at(evidence.value, source_stamp) or _now_iso()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(
        timespec="seconds"
    )


def _train_summary(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        key: value.get(key)
        for key in (
            "train_code",
            "departure_at",
            "arrival_at",
            "duration_seconds",
        )
    }


def _available_seconds(intent: TravelIntent) -> float:
    if not intent.earliest_departure_at or not intent.latest_return_at:
        return 0.0
    earliest = datetime.fromisoformat(intent.earliest_departure_at)
    latest = datetime.fromisoformat(intent.latest_return_at)
    return max(0.0, (latest - earliest).total_seconds())


def _nonnegative_number(value: object) -> float | None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or float(value) < 0
    ):
        return None
    return float(value)


def _station_seed(destination: Mapping[str, object]) -> str:
    live_gateway = destination.get("rail_gateway")
    if isinstance(live_gateway, str) and live_gateway.strip():
        return live_gateway.strip()
    planning_city = str(destination.get("planning_city", "")).strip()
    for suffix in ("自治州", "地区", "市", "县", "区"):
        if planning_city.endswith(suffix) and len(planning_city) > len(suffix):
            return planning_city[: -len(suffix)]
    return planning_city or str(destination["name"])


def _normalized_region_text(value: str) -> str:
    result = value
    for token in (
        "大概想去",
        "考虑",
        "倾向",
        "优先",
        "那块",
        "一带",
        "附近",
        "区域",
        "地区",
        " ",
        "、",
        "/",
    ):
        result = result.replace(token, "")
    return result


def _region_match_score(
    anchor: str,
    destination: Mapping[str, object],
) -> int:
    name = str(destination.get("name", ""))
    if name and name in anchor:
        return 100
    planning = _station_seed(destination)
    if len(planning) >= 2 and planning in anchor:
        return 80
    gateway = str(destination.get("gateway_label", ""))
    gateway_parts = [
        item.strip()
        for item in gateway.replace("／", "/").split("/")
        if item.strip()
    ]
    if any(len(item) >= 2 and item in anchor for item in gateway_parts):
        return 70
    province = str(destination.get("province", ""))
    if province and province in anchor:
        return 20
    return 0


__all__ = [
    "build_guided_comparison",
    "guided_region_seeds",
    "preferred_direct_destination",
]
