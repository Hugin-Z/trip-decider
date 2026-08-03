"""Action-driven orchestration for a Codex-hosted trip run.

Registered runtime tools execute inside the local product.  Destination POI
and lodging candidates come from the live provider collector; unresolved
opening hours, ticket prices, and lodging prices remain explicit missing data.
No collector result is marked complete unless it is sourced evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import RLock
import time
from typing import Any
from uuid import uuid4

from trip_decider.destination_runtime import (
    collect_map_evidence,
    collect_railway_evidence,
)
from trip_decider.dynamic_discovery import collect_live_destination_profile
from trip_decider.evidence_core import (
    FRESHNESS_STALE,
    recovery_safe,
    token_freshness,
)
from trip_decider.evidence_projection import (
    business_view,
    project_domain,
    usable_fact_values,
)
from trip_decider.evidence_broker import (
    default_evidence_broker,
    EvidenceBroker,
    evidence_collected_at,
    query_for_intent_domain,
)
from trip_decider.itinerary_planner import (
    RAIL_EVENT_REQUIRED_TRAIN_FIELDS,
    plan_destination_context,
    validate_destination_plan,
)
from trip_decider.evidence_core import aggregate_support
from trip_decider.intercity_rail import rail_snapshot_metadata
from trip_decider.planning_input_compiler import (
    PlanningInputCompiler,
    plan_verdict_from_result,
)
from trip_decider.simple_live import (
    _LiveFailure,
    estimate_public_transport_from_points,
    estimate_live_public_transport_segments,
)
from trip_decider.travel_agent import (
    default_agent_store,
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
    NON_BUSINESS_ERRORS,
    RunStatus,
    TaskMode,
    TravelAgentError,
    TravelIntent,
    atomic_runtime_json as _atomic_runtime_json,
    build_destination_context,
    trimmed_context,
    user_input_evidence,
)


_DOMAINS = ("railway", "web", "map")
_ACTION_ORDER = ("railway", "web", "map", "planner")

#: 铁路证据里「一个方向」的两个方向名。规划器按这两个键找车次。
_RAIL_DIRECTIONS = ("outbound", "return")

#: 手工填写车次动作的必填项，**从消费端常量派生**，不手写。
#:
#: 宿主实测的 P0 就出在这里手写过一份：声明 ``outbound``/``return``/``fare``/
#: ``source``，而消费端按 ``origin_station`` 等五个键直取。宿主照声明填满四个
#: 键，四层校验全过，Planner 随即 KeyError（D2：声明点与消费点必须同一张表
#: 核对后一起改；D20：能由数据形状保证的，不留给代码自律）。
RAILWAY_MANUAL_REQUIRED_FIELDS: tuple[str, ...] = tuple(
    f"{direction}.{field}"
    for direction in _RAIL_DIRECTIONS
    for field in RAIL_EVENT_REQUIRED_TRAIN_FIELDS
)

#: 消费端用 ``.get()`` 取的字段：缺席被容忍，落到「未知」而不是拒绝提交。
#: 与必填项分开声明，宿主才知道哪些值得补、哪些不补也能出方案。
RAILWAY_MANUAL_OPTIONAL_FIELDS: tuple[str, ...] = tuple(
    f"{direction}.{field}"
    for direction in _RAIL_DIRECTIONS
    for field in ("second_class_fare_cny_per_person", "second_class_availability")
)


@dataclass
class _LoopState:
    evidence: dict[str, EvidenceItem] = field(default_factory=dict)
    last_sourced_evidence: dict[str, EvidenceItem] = field(
        default_factory=dict
    )
    action_status: dict[str, str] = field(
        default_factory=lambda: {
            action_id: "waiting" for action_id in _ACTION_ORDER
        }
    )
    result: dict[str, object] | None = None
    fallback_result: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        """action-loop.json 的内容。**不含 ``result``**——见 §13.1 的去重裁决。

        ``result`` 曾经在这里逐字节重复 ``run.json`` 的同名字段（实测 78,102
        字节，两边 ``==`` 为真）。它是同一份数据的第二个副本，而副本的问题不
        是占地方，是**两份可以不一致**：谁是权威没有写下来，两边就都不是。

        裁决把权威钉在 ``run.json``：``run.json`` 先落，``action-loop.json``
        后落，恢复时以 ``run.json`` 为准。这里只留调度状态。

        ``fallback_result`` **留下**——它不是重复。它是动作循环启动那一刻的
        ``run.result`` 快照（比较阶段的候选卡，实测 1,270 字节），而
        ``run.result`` 之后会被详细规划结果覆盖。从当前的 ``run.json`` 重建
        不出它来。
        """

        return {
            "action_status": dict(self.action_status),
            # 权威在 run.json。写明白，免得下一个人以为这里少了个字段。
            "result_source": "run.json#result",
            "fallback_result": deepcopy(self.fallback_result),
        }

    def evidence_dict(self, run_id: str) -> dict[str, object]:
        return {
            "run_id": run_id,
            "current": [
                self.evidence[domain].to_dict()
                for domain in sorted(self.evidence)
            ],
            "last_sourced": [
                self.last_sourced_evidence[domain].to_dict()
                for domain in sorted(self.last_sourced_evidence)
            ],
        }


_LOCK = RLock()
_STATES: dict[str, _LoopState] = {}

# 读取时刻的注入点。产品默认是墙钟——判定"这份证据现在还新鲜吗"本来就该问
# 现在几点。表征需要它固定，否则同一份夹具隔天读会得到不同的 freshness，
# 基线会在没有代码改动的情况下自行翻面。
#
# 走模块级而非穿参：_LoopState 与 drive_offline_run 之间隔着应用服务，
# 穿参要改产品 API 来迁就测试。参照 reset_default_agent_store() 的先例。
_READ_CLOCK: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def set_read_clock(clock: Callable[[], datetime]) -> Callable[[], datetime]:
    """注入读取时刻，返回原时钟供调用方还原。仅供测试。"""

    global _READ_CLOCK
    previous = _READ_CLOCK
    _READ_CLOCK = clock
    return previous


def reset_read_clock() -> None:
    global _READ_CLOCK
    _READ_CLOCK = lambda: datetime.now(timezone.utc)


def start_action_loop(
    run_id: str,
    *,
    initial_evidence: Mapping[str, EvidenceItem] | None = None,
    store: InMemoryAgentStore | None = None,
) -> dict[str, object]:
    """Move a confirmed run into its action-driven execution state."""
    store = store if store is not None else default_agent_store()

    run = store.get_run(run_id)
    if run.status is not RunStatus.CONFIRMED:
        raise TravelAgentError("run must be confirmed before action execution")
    store.start(run_id)
    with _LOCK:
        state = _LoopState(
            fallback_result=(
                recovery_safe(deepcopy(dict(run.result)))
                if isinstance(run.result, Mapping)
                else None
            )
        )
        reused: list[str] = []
        unavailable: list[str] = []
        for domain, item in sorted((initial_evidence or {}).items()):
            if domain not in _DOMAINS or item.domain != domain:
                raise TravelAgentError(
                    "initial evidence domain does not match its key"
                )
            state.evidence[domain] = item
            if item.status.is_usable:
                state.last_sourced_evidence[domain] = item
                state.action_status[domain] = "completed"
                reused.append(domain)
            elif (
                domain == "web"
                and item.missing_reason
                in {
                    "collector_not_configured",
                    "web_search_collector_not_configured",
                }
            ):
                state.evidence.pop(domain, None)
                state.action_status[domain] = "waiting"
            else:
                state.action_status[domain] = "waiting"
                unavailable.append(domain)
        _STATES[run_id] = state
        _persist_loop_state(run_id, state, store)
    store.append_event(
        run_id,
        event_type="planning.actions.initialized",
        status="running",
        message="已复用比较证据，只补充详细规划缺失项。",
        details={
            "tool": "destination_context",
            "total_actions": len(_ACTION_ORDER),
            "completed_actions": reused,
            "unavailable_actions": unavailable,
            "pending_actions": [
                action_id
                for action_id in _ACTION_ORDER
                if state.action_status[action_id] == "waiting"
            ],
        },
    )
    for domain in reused:
        store.append_event(
            run_id,
            event_type="planning.evidence.reused",
            status="completed",
            message=f"{_action_title(domain)}沿用区域比较阶段证据。",
            details={
                "tool": domain,
                "support": "sourced",
            },
        )
    return get_next_actions(run_id, store=store)


def restart_action_loop_for_intent(
    run_id: str,
    intent: TravelIntent | Mapping[str, object],
    *,
    store: InMemoryAgentStore | None = None,
) -> dict[str, object]:
    """Start a same-run revision while reusing still-applicable evidence."""
    store = store if store is not None else default_agent_store()

    previous = store.get_run(run_id)
    contract = (
        intent
        if isinstance(intent, TravelIntent)
        else TravelIntent.from_mapping(intent)
    )
    state = _state(run_id, store)
    reusable = dict(state.evidence)
    previous_intent = previous.intent
    if contract.destination_anchor != previous_intent.destination_anchor:
        reusable.clear()
    else:
        rail_inputs = (
            "origin",
            "earliest_departure_at",
            "latest_return_at",
            "transport_preferences",
        )
        if any(
            getattr(contract, field_name)
            != getattr(previous_intent, field_name)
            for field_name in rail_inputs
        ):
            reusable.pop("railway", None)
    store.prepare_revision(run_id, intent=contract)
    return start_action_loop(
        run_id,
        initial_evidence=reusable,
        store=store,
    )


def run_until_blocked(
    run_id: str,
    *,
    store: InMemoryAgentStore | None = None,
    evidence_broker: EvidenceBroker | None = None,
    max_wait_seconds: float = 30.0,
) -> dict[str, object]:
    """Execute local registered tools and pause at external evidence actions.

    A failed railway refresh is deliberately not retried here: the returned
    actions expose both explicit re-query and manual train entry.  This keeps
    retry authority with the caller and prevents an implicit retry loop.
    """
    evidence_broker = (
        evidence_broker
        if evidence_broker is not None
        else default_evidence_broker()
    )
    store = store if store is not None else default_agent_store()

    if (
        not isinstance(max_wait_seconds, (int, float))
        or isinstance(max_wait_seconds, bool)
        or float(max_wait_seconds) <= 0
    ):
        raise TravelAgentError("max_wait_seconds must be positive")
    started = time.monotonic()
    executed: set[tuple[str, str]] = set()
    for _ in range(16):
        remaining = float(max_wait_seconds) - (
            time.monotonic() - started
        )
        if remaining <= 0:
            snapshot = get_next_actions(run_id, store=store)
            return {
                **snapshot,
                "status": "NEED_USER_INPUT",
                "reason": "time_budget_exhausted",
                "elapsed_seconds": float(max_wait_seconds),
            }
        snapshot = get_next_actions(run_id, store=store)
        if snapshot["status"] in {"READY", "BLOCKED"}:
            return snapshot
        actions = snapshot.get("actions")
        if not isinstance(actions, list):
            raise TravelAgentError("action snapshot omitted actions")
        executable = [
            action
            for action in actions
            if isinstance(action, Mapping)
            and action.get("action_type") == "registered_tool"
            and action.get("mode") != "requery"
            and (
                str(action.get("action_id")),
                str(action.get("mode", "initial")),
            )
            not in executed
        ]
        if not executable:
            return {
                **snapshot,
                "status": "NEED_USER_INPUT",
                "paused_at": [
                    str(action.get("action_type"))
                    for action in actions
                    if isinstance(action, Mapping)
                ],
            }
        batch = [
            action
            for action in executable
            if action.get("action_id") in {"railway", "web", "map"}
            and action.get("mode", "initial") == "initial"
        ]
        if len(batch) > 1:
            for action in batch:
                executed.add(
                    (
                        str(action["action_id"]),
                        str(action.get("mode", "initial")),
                    )
                )
            executor = ThreadPoolExecutor(
                max_workers=len(batch),
                thread_name_prefix="detail-missing-actions",
            )
            try:
                futures = [
                    executor.submit(
                        execute_registered_action,
                        run_id,
                        str(action["action_id"]),
                        store=store,
                        evidence_broker=evidence_broker,
                    )
                    for action in batch
                ]
                completed, pending = wait(
                    futures,
                    timeout=min(30.0, remaining),
                )
                for future in completed:
                    future.result()
                if any(
                    str(batch[futures.index(future)].get("action_id"))
                    != "planner"
                    for future in completed
                ):
                    executed.discard(("planner", "initial"))
                if pending:
                    for future in pending:
                        future.cancel()
                    pending_ids = [
                        str(batch[futures.index(future)]["action_id"])
                        for future in pending
                    ]
                    _timeout_actions(
                        run_id,
                        pending_ids,
                        store=store,
                    )
                    return get_next_actions(run_id, store=store)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
            continue
        action = executable[0]
        action_id = str(action["action_id"])
        mode = str(action.get("mode", "initial"))
        executed.add((action_id, mode))
        executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="detail-action-budget",
        )
        try:
            future = executor.submit(
                execute_registered_action,
                run_id,
                action_id,
                store=store,
                evidence_broker=evidence_broker,
            )
            completed, pending = wait(
                (future,),
                timeout=min(30.0, remaining),
            )
            if pending:
                future.cancel()
                _timeout_actions(
                    run_id,
                    [action_id],
                    store=store,
                )
                return get_next_actions(run_id, store=store)
            next(iter(completed)).result()
            if action_id != "planner":
                executed.discard(("planner", "initial"))
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    raise TravelAgentError("run-until-blocked exceeded its action bound")


def get_next_actions(
    run_id: str,
    *,
    store: InMemoryAgentStore | None = None,
) -> dict[str, object]:
    """Return the next honest state and executable actions for Codex."""
    store = store if store is not None else default_agent_store()

    run = store.get_run(run_id)
    if run.status is RunStatus.AWAITING_CONFIRMATION:
        return _snapshot(
            run_id,
            "NEED_USER_INPUT",
            [],
            missing_fields=list(run.intent.blocking_missing_fields),
        )
    if run.status is RunStatus.CONFIRMED:
        return _snapshot(
            run_id,
            "NEED_USER_INPUT",
            [],
            reason="run_not_started",
        )
    if run.status is RunStatus.COMPLETED:
        return _snapshot(
            run_id,
            "READY",
            [],
            result=run.result,
        )
    if run.status is RunStatus.BLOCKED:
        result = run.result if isinstance(run.result, Mapping) else {}
        return _snapshot(
            run_id,
            "BLOCKED",
            [],
            blocked_domains=list(
                _mapping_list(result, "blocked_domains")
            ),
            reason=run.error_code,
            recovery=_blocked_recovery(run, result),
        )
    if run.status is RunStatus.FAILED:
        return _snapshot(
            run_id,
            "BLOCKED",
            [],
            reason="runtime_failure",
        )
    if run.status is not RunStatus.RUNNING:
        raise TravelAgentError("run has an unsupported lifecycle state")

    state = _state(run_id, store)
    if state.action_status["planner"] == "completed":
        loop_evidence = _loop_evidence(state, run.intent)
        if _result_is_displayable(state.result, loop_evidence):
            return _snapshot(run_id, "READY", [], result=state.result)
        # 读时重算，不读盘上的副本。此前这里是
        # `_result_planning_state(state.result)`，读 `result["planning_state"]`
        # ——那个键在 P4 已从落盘契约删除（I1 禁用键），于是这一支**恒不成立**：
        # 硬约束冲突的 run 拿不到 BLOCKED 快照，只会落到下面那句
        # 「缺展示要件」，叙述与真实原因无关。删掉读盘的那个 helper，接上
        # 与 _result_is_displayable 同一个读时结论。
        if recomputed_planning_state(state.result, loop_evidence) == "BLOCKED":
            return _snapshot(
                run_id,
                "BLOCKED",
                [],
                reason="unresolved_hard_constraint_conflict",
                result=state.result,
                missing_requirements=_missing_display_requirements(
                    state.result
                ),
                blockers=_result_blockers(state.result),
            )
        return _snapshot(
            run_id,
            "NEED_USER_INPUT",
            _plan_followup_actions(run.intent, state),
            reason="displayable_itinerary_requirements_missing",
            result=state.result,
            missing_requirements=_missing_display_requirements(state.result),
            blockers=_result_blockers(state.result),
        )
    actions: list[dict[str, object]] = []
    if state.action_status["railway"] == "waiting":
        actions.append(_registered_action("railway", run.intent))
    elif state.action_status["railway"] == "failed":
        actions.extend(
            (
                _registered_action(
                    "railway",
                    run.intent,
                    mode="requery",
                ),
                _manual_railway_action(run.intent),
            )
        )
    if state.action_status["web"] == "waiting":
        actions.append(_web_action(run.intent))
    map_action: dict[str, object] | None = None
    if (
        state.action_status["map"] == "waiting"
        and (
            "web" in state.evidence
            or (
                "map" in state.evidence
                and not state.evidence["map"].status.is_usable
            )
        )
    ):
        map_action = _registered_action("map", run.intent, state)
        actions.append(map_action)
    elif (
        state.action_status["map"] == "completed"
        and _needs_local_transit(state)
        and _can_collect_local_transit(state)
    ):
        map_action = _registered_action(
            "map",
            run.intent,
            state,
            mode="local_transit",
        )
        actions.append(map_action)
    if (
        state.action_status["planner"] == "waiting"
        and all(domain in state.evidence for domain in _DOMAINS)
        and map_action is None
    ):
        actions.append(_registered_action("planner", run.intent))
    if actions:
        return _snapshot(run_id, "ACTIONS_AVAILABLE", actions)
    return _snapshot(run_id, "BLOCKED", [], reason="no_progress_action")


def execute_registered_action(
    run_id: str,
    action_id: str,
    *,
    store: InMemoryAgentStore | None = None,
    evidence_broker: EvidenceBroker | None = None,
) -> dict[str, object]:
    """Execute one registered 12306, AMap, or Planner action."""
    evidence_broker = (
        evidence_broker
        if evidence_broker is not None
        else default_evidence_broker()
    )
    store = store if store is not None else default_agent_store()

    run = store.get_run(run_id)
    if (
        run.status is RunStatus.COMPLETED
        and action_id in {"railway", "map", "planner"}
    ):
        run = store.resume(run_id)
    if run.status is not RunStatus.RUNNING:
        raise TravelAgentError("run is not executing actions")
    state = _state(run_id, store)
    if action_id not in _TOOL_REGISTRY:
        raise TravelAgentError("action is not a registered runtime tool")
    is_refresh = state.action_status[action_id] in {"completed", "failed"}
    if state.action_status[action_id] != "waiting" and not is_refresh:
        raise TravelAgentError("action is not waiting")
    if not is_refresh:
        available = {
            action["action_id"] for action in get_next_actions(
                run_id,
                store=store,
            )["actions"]
        }
        if action_id not in available:
            raise TravelAgentError("action prerequisites are not satisfied")
    state.action_status[action_id] = "running"
    _persist_loop_state(run_id, state, store)
    store.append_event(
        run_id,
        event_type="tool.started",
        status="started",
        message=f"{_TOOL_REGISTRY[action_id]['title']}开始执行。",
        details={"tool": action_id},
    )
    action_started = time.monotonic()
    try:
        outcome = _TOOL_REGISTRY[action_id]["handler"](
            run.intent,
            state,
        )
    except NON_BUSINESS_ERRORS:
        # 编程错误不穿业务外衣。走下面那条路会把它变成
        # 「{域}_ACTION_FAILED」+「该域缺证据」，那句叙述与事故原因毫无
        # 关系，只会把归因引向采集器和数据源。这里是同步调用，重抛能让它
        # 原样浮到调用方，栈也留得住。
        state.action_status[action_id] = "blocked"
        _persist_loop_state(run_id, state, store)
        raise
    except Exception as error:
        state.action_status[action_id] = "blocked"
        _persist_loop_state(run_id, state, store)
        store.append_event(
            run_id,
            event_type="tool.failed",
            status="failed",
            message=f"{_TOOL_REGISTRY[action_id]['title']}执行失败。",
            details={
                "tool": action_id,
                "error_type": type(error).__name__,
                "duration_ms": round(
                    (time.monotonic() - action_started) * 1000,
                    3,
                ),
            },
        )
        _block_run(run_id, action_id, store=store)
        return get_next_actions(run_id, store=store)

    if action_id == "planner":
        if not isinstance(outcome, Mapping):
            raise TravelAgentError("planner action returned a non-object")
        result = deepcopy(dict(outcome))
        state.result = result
        state.action_status[action_id] = "completed"
        # §13.1 的写入顺序：run.json 先落权威，action-loop.json 后落。
        # 反过来会开出一个恢复不了的中断窗口——action-loop 说 planner 已完成，
        # run.json 里却还没有 result，重启后状态自相矛盾。
        store.record_result(run_id, result)
        _persist_loop_state(run_id, state, store)
        planner_evidence = _loop_evidence(state, run.intent)
        if _result_is_displayable(result, planner_evidence):
            store.persist_plan_version(run_id, result)
        store.append_event(
            run_id,
            event_type="tool.completed",
            status="completed",
            message=(
                "计划版本已通过证据门并安装。"
                if _result_is_displayable(result, planner_evidence)
                else "规划草稿已生成，仍在补充最低真实证据。"
            ),
            details={
                "tool": "planner",
                "duration_ms": round(
                    (time.monotonic() - action_started) * 1000,
                    3,
                ),
            },
        )
        if _result_is_displayable(result, planner_evidence):
            store.complete(run_id, result)
        else:
            store.append_event(
                run_id,
                event_type="plan.supplementing",
                status="waiting",
                message="尚未满足可展示行程最低条件，继续补充真实数据。",
                details={
                    "missing_requirements": (
                        _missing_display_requirements(result)
                    ),
                },
            )
        return get_next_actions(run_id, store=store)

    if not isinstance(outcome, EvidenceItem):
        raise TravelAgentError("evidence action returned an invalid value")
    query = _broker_query(run.intent, action_id, state)
    usable_live = _is_usable_action_evidence(action_id, query.data_type, outcome)
    if usable_live:
        collected_at = evidence_collected_at(outcome)
        if collected_at is not None:
            try:
                evidence_broker.publish(
                    run_id=run_id,
                    query=query,
                    evidence=outcome,
                    collected_at=collected_at,
                )
            except TravelAgentError:
                store.append_event(
                    run_id,
                    event_type="evidence.cache_rejected",
                    status="completed",
                    message="本次证据可使用，但不满足跨任务缓存条件。",
                    details={"tool": action_id},
                )
    elif action_id in state.last_sourced_evidence:
        previous = state.last_sourced_evidence[action_id]
        outcome = (
            _stale_railway_evidence(previous, outcome)
            if action_id == "railway"
            else _stale_generic_evidence(previous, outcome)
        )
    else:
        stale = evidence_broker.stale_after_failure(
            run_id=run_id,
            query=query,
            live_failure=outcome,
        )
        if stale is not None:
            outcome = stale
    store.append_event(
        run_id,
        event_type="tool.timed",
        status="completed",
        message="一项数据查询完成计时。",
        details={
            "tool": action_id,
            "duration_ms": round(
                (time.monotonic() - action_started) * 1000,
                3,
            ),
        },
    )
    return submit_evidence(
        run_id,
        {
            **outcome.to_dict(),
            "action_id": action_id,
        },
        store=store,
    )


def submit_evidence(
    run_id: str,
    evidence: EvidenceItem | Mapping[str, object],
    *,
    store: InMemoryAgentStore | None = None,
) -> dict[str, object]:
    """Validate and attach one action-owned evidence item."""
    store = store if store is not None else default_agent_store()

    run = store.get_run(run_id)
    if run.status is not RunStatus.RUNNING:
        raise TravelAgentError("run is not accepting evidence")
    raw = evidence.to_dict() if isinstance(evidence, EvidenceItem) else dict(evidence)
    action_id = raw.pop("action_id", None)
    if not isinstance(action_id, str) or action_id not in _ACTION_ORDER:
        raise TravelAgentError("evidence action_id is invalid")
    if action_id == "planner":
        raise TravelAgentError("planner does not accept evidence submission")
    item = (
        evidence
        if isinstance(evidence, EvidenceItem)
        else EvidenceItem.from_mapping(raw)
    )
    if item.domain != action_id:
        raise TravelAgentError("evidence domain does not match its action")
    state = _state(run_id, store)
    if state.action_status[action_id] not in {
        "waiting",
        "running",
        "failed",
        "completed",
    }:
        raise TravelAgentError("evidence action is not accepting a result")
    if action_id == "web" and state.action_status[action_id] == "waiting":
        state.action_status[action_id] = "running"
        store.append_event(
            run_id,
            event_type="tool.started",
            status="started",
            message="Codex开始执行网页事实核验。",
            details={"tool": "web"},
        )
    if item.status.is_usable:
        previous = state.last_sourced_evidence.get(item.domain)
        merged = (
            _merge_sourced_evidence(previous, item)
            if action_id in {"web", "map"} and previous is not None
            else item
        )
        if action_id == "web":
            # 校验吃重建后的业务字段视图：落盘是 facts 数组。
            _validate_web_value(usable_fact_values(merged.facts))
        if action_id == "railway":
            # 同上，且必须在**投影之后**校验——见 _validate_railway_value。
            _validate_railway_value(usable_fact_values(merged.facts))
        state.evidence[item.domain] = merged
        state.last_sourced_evidence[item.domain] = merged
        state.action_status[action_id] = "completed"
        if action_id != "planner":
            state.action_status["planner"] = "waiting"
            state.result = None
        _persist_loop_state(run_id, state, store)
        store.append_event(
            run_id,
            event_type="tool.completed",
            status="completed",
            message=f"{_action_title(action_id)}取得有效证据。",
            details={
                "tool": action_id,
                "support": "sourced",
            },
        )
        return get_next_actions(run_id, store=store)

    if action_id in state.last_sourced_evidence:
        previous = state.last_sourced_evidence[action_id]
        degraded = (
            _stale_railway_evidence(previous, item)
            if action_id == "railway"
            else _stale_generic_evidence(previous, item)
        )
        state.evidence[action_id] = degraded
        state.action_status[action_id] = "completed"
        state.action_status["planner"] = "waiting"
        state.result = None
        _persist_loop_state(run_id, state, store)
        store.append_event(
            run_id,
            event_type="tool.degraded",
            status="completed",
            message=(
                f"{_action_title(action_id)}重新查询失败；"
                "保留最近成功证据并降级为STALE。"
            ),
            details={
                "tool": action_id,
                "support": "sourced",
                "availability": (
                    "UNKNOWN" if action_id == "railway" else None
                ),
                "refresh_failure": item.missing_reason,
            },
        )
        return get_next_actions(run_id, store=store)

    state.evidence[item.domain] = item
    state.action_status[action_id] = "blocked"
    store.append_event(
        run_id,
        event_type="tool.failed",
        status="failed",
        message=f"{_action_title(action_id)}未取得有效证据。",
        details={
            "tool": action_id,
            "support": item.status.support,
        },
    )
    state.action_status[action_id] = "failed"
    state.action_status["planner"] = "waiting"
    state.result = None
    _persist_loop_state(run_id, state, store)
    return get_next_actions(run_id, store=store)


def _railway_handler(
    intent: TravelIntent,
    state: _LoopState,
) -> EvidenceItem:
    del state
    return collect_railway_evidence(intent)


def _web_handler(
    intent: TravelIntent,
    state: _LoopState,
) -> EvidenceItem:
    del state
    return collect_live_destination_profile(intent)


def _map_handler(
    intent: TravelIntent,
    state: _LoopState,
) -> EvidenceItem:
    web_evidence = state.evidence.get("web")
    web_value = (
        usable_fact_values(web_evidence.facts)
        if web_evidence is not None
        else {}
    )
    official_name = web_value.get("destination_official_name")
    selected_name = (
        official_name.strip()
        if isinstance(official_name, str) and official_name.strip()
        else intent.destination_anchor
    )
    if not selected_name:
        raise TravelAgentError("map action lacks a destination anchor")
    existing_map = state.evidence.get("map")
    district_evidence = (
        existing_map
        if (
            existing_map is not None
            and existing_map.status.is_usable
        )
        else collect_map_evidence(
            replace(intent, destination_anchor=selected_name)
        )
    )
    if (
        district_evidence.status.is_usable
        and bool(district_evidence.facts)
        and isinstance(
            usable_fact_values(district_evidence.facts).get("local_transit"),
            list,
        )
        and usable_fact_values(district_evidence.facts)["local_transit"]
    ):
        return district_evidence
    if (
        not district_evidence.status.is_usable
        or not _web_route_inputs(state.evidence.get("web"))
    ):
        return district_evidence
    value = usable_fact_values(district_evidence.facts)
    destination = (
        value.get("destination")
        if isinstance(value, Mapping)
        else None
    )
    route_city = (
        str(destination.get("name")).strip()
        if isinstance(destination, Mapping)
        and isinstance(destination.get("name"), str)
        and str(destination.get("name")).strip()
        else selected_name
    )
    city_adcode = (
        destination.get("adcode")
        if isinstance(destination, Mapping)
        else None
    )
    route_inputs = _web_route_inputs(state.evidence.get("web"))
    if (
        not isinstance(city_adcode, str)
        or not city_adcode.isdigit()
        or route_inputs is None
    ):
        return district_evidence
    base, attractions = route_inputs
    place_names = [base, *attractions]
    route_signature = list(place_names)
    segments = _web_route_segments(
        state.evidence.get("web"),
        place_names,
    )
    try:
        route_points = _web_route_points(
            state.evidence.get("web"),
            place_names,
        )
        route_result = (
            estimate_public_transport_from_points(
                city_adcode=city_adcode,
                place_points=route_points,
                segments=segments,
            )
            if route_points is not None
            else estimate_live_public_transport_segments(
                city=route_city,
                city_adcode=city_adcode,
                place_names=place_names,
                segments=segments,
            )
        )
    except _LiveFailure as error:
        enriched = deepcopy(dict(value))
        enriched["local_transit_outcome"] = "FAILED"
        enriched["local_transit_input_signature"] = route_signature
        enriched["local_transit_refresh_failure"] = {
            "stage": error.stage,
            "python_exception_type": error.python_exception_type,
        }
        return EvidenceItem(
            evidence_id=district_evidence.evidence_id,
            domain="map",
            # 高德路径规划返回的行程时长是服务端推算量，不是直接读出
            # （evidence-axes.md §2.2）。support-reclassification.md §1 的 R2。
            status=EvidenceStatus.ESTIMATED,
            value=enriched,
            sources=district_evidence.sources,
        )
    local_transit = _normalize_local_transit(route_result)
    resolutions = route_result.get("place_resolutions")
    retrieved_at = route_result.get("retrieved_at")
    for route in local_transit:
        if isinstance(resolutions, Mapping):
            origin = resolutions.get(route.get("from"))
            destination_point = resolutions.get(route.get("to"))
            if isinstance(origin, Mapping):
                route["from_location"] = deepcopy(origin.get("location"))
            if isinstance(destination_point, Mapping):
                route["to_location"] = deepcopy(
                    destination_point.get("location")
                )
        route["retrieved_at"] = retrieved_at
        enriched = deepcopy(dict(value))
    enriched["local_transit"] = local_transit
    enriched["local_transit_outcome"] = route_result.get("status")
    enriched["local_transit_input_signature"] = route_signature
    enriched["local_transit_place_resolutions"] = deepcopy(
        route_result.get("place_resolutions", {})
    )
    if isinstance(route_result.get("timings_ms"), Mapping):
        enriched["timings_ms"] = deepcopy(
            dict(route_result["timings_ms"])
        )
    route_source = route_result.get("source")
    sources = list(district_evidence.sources)
    if isinstance(route_source, Mapping):
        sources.append(
            {
                **deepcopy(dict(route_source)),
                "retrieved_at": route_result.get("retrieved_at"),
            }
        )
    return EvidenceItem(
        evidence_id=district_evidence.evidence_id,
        domain="map",
        # 同 R2：value 里的 local_transit[].duration_seconds 全部来自高德
        # 路径规划。support-reclassification.md §1 的 R1。
        status=EvidenceStatus.ESTIMATED,
        value=enriched,
        sources=tuple(sources),
    )


def _planner_handler(
    intent: TravelIntent,
    state: _LoopState,
) -> Mapping[str, object]:
    # 单一出处：读取层要按同样规则重建它（persistence-v2.md §2.1.1），
    # 两处各造一份就会在 evidence_id 上分叉，引用随即解析不到（D5）。
    user = user_input_evidence(intent)
    context = build_destination_context(
        intent,
        (user, *(state.evidence[domain] for domain in _DOMAINS)),
    )
    compiled = PlanningInputCompiler().compile(context, now=_READ_CLOCK())
    planning_draft = plan_destination_context(context.to_dict())
    planning_draft = {
        **planning_draft,
        "artifact_kind": "PlanningDraft",
        "status": compiled["status"],
        "days": compiled["days"],
        "planning_input": {
            key: deepcopy(compiled[key])
            for key in (
                "cross_city_rail_events",
                "attraction_events",
                "local_transit_events",
                "map_points",
                "meal_events",
                "hotel_events",
                "buffer_events",
                "rest_events",
                "evidence_dependencies",
                "planner_defaults",
                "pace_contract",
            )
        },
        "conditional_blockers": deepcopy(
            compiled["conditional_blockers"]
        ),
        "display_requirements": deepcopy(
            compiled["display_requirements"]
        ),
        "missing_requirements": deepcopy(
            compiled["missing_requirements"]
        ),
        "accommodation_notice": (
            "具体酒店未选择，当前使用住宿片区或交通枢纽；"
            "首末段交通待细化。"
            if compiled["display_requirements"]["accommodation_base"]
            else None
        ),
    }
    validation = validate_destination_plan(
        context.to_dict(),
        planning_draft,
    )
    if validation.get("valid") is not True:
        raise TravelAgentError("planner output failed context validation")
    days = planning_draft.get("days")
    if not isinstance(days, list) or not days:
        raise TravelAgentError(
            "planner did not produce a non-empty itinerary"
        )
    installable = compiled["planning_state"] in {
        "PARTIAL_READY",
        "PLAN_READY",
    }
    result: dict[str, object] = {
        "action_loop_status": (
            "READY" if installable else compiled["planning_state"]
        ),
        "task_mode": intent.task_mode.value,
        # A 收敛：result 的 context 不再内联证据，只留引用
        # （persistence-v2.md §2.1.1）。证据的权威容器是
        # evidence/current.json，留内联副本就是 D19 的那个问题。
        "context": trimmed_context(context.to_dict()),
        "planning_draft": deepcopy(dict(planning_draft)),
        "validation": deepcopy(dict(validation)),
        "pipeline": [
            "parse_intent",
            "collect_evidence",
            "build_destination_context",
            "plan",
            "validate",
        ],
    }
    if installable:
        result["plan"] = {
            **deepcopy(dict(planning_draft)),
            "artifact_kind": "PlanVersion",
        }
    return result


_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "railway": {
        "title": "中国铁路12306查询",
        "handler": _railway_handler,
    },
    "map": {
        "title": "高德目的地核验",
        "handler": _map_handler,
    },
    "web": {
        "title": "目的地景点与住宿候选查询",
        "handler": _web_handler,
    },
    "planner": {
        "title": "通用Planner",
        "handler": _planner_handler,
    },
}


def _registered_action(
    action_id: str,
    intent: TravelIntent,
    state: _LoopState | None = None,
    *,
    mode: str = "initial",
) -> dict[str, object]:
    arguments: dict[str, object] = {}
    if action_id == "railway":
        arguments = {
            "origin": intent.origin,
            "destination": intent.destination_anchor,
            "earliest_departure_at": intent.earliest_departure_at,
            "latest_return_at": intent.latest_return_at,
        }
    elif action_id == "map" and state is not None:
        web_evidence = state.evidence.get("web")
        arguments = {
            "destination": (
                usable_fact_values(web_evidence.facts).get(
                    "destination_official_name"
                )
                if web_evidence is not None
                else None
            )
        }
    elif action_id == "web":
        arguments = {
            "destination": intent.destination_anchor,
            "themes": list(intent.themes),
        }
    return {
        "action_id": action_id,
        "action_type": "registered_tool",
        "tool": action_id,
        "title": _action_title(action_id),
        "mode": mode,
        "arguments": arguments,
    }


def _manual_railway_action(
    intent: TravelIntent,
) -> dict[str, object]:
    return {
        "action_id": "railway_manual",
        "action_type": "user_input",
        "tool": "railway",
        "title": "手动填写车次",
        "submit_action_id": "railway",
        "arguments": {
            "origin": intent.origin,
            "destination": intent.destination_anchor,
            "earliest_departure_at": intent.earliest_departure_at,
            "latest_return_at": intent.latest_return_at,
        },
        # 必填/可选都从消费端常量派生。旧版在这里手写了四个键
        # （outbound/return/fare/source），与消费端各说各话——宿主照着填满
        # 仍然 KeyError（D2）。
        "required_fields": list(RAILWAY_MANUAL_REQUIRED_FIELDS),
        "optional_fields": list(RAILWAY_MANUAL_OPTIONAL_FIELDS),
    }


def _stale_railway_evidence(
    previous: EvidenceItem,
    failed_refresh: EvidenceItem,
) -> EvidenceItem:
    if (
        not previous.status.is_usable
        or not isinstance(previous.value, Mapping)
    ):
        raise TravelAgentError(
            "railway fallback requires prior sourced evidence"
        )
    # 从重建视图出发，不从落盘形状——v2 的 value 是 facts 数组，直接
    # .get("outbound") 会静默拿到 None，余票抹除就悄悄失效了。
    value = business_view(previous)
    old_snapshot = value.get("snapshot")
    if not isinstance(old_snapshot, Mapping):
        raise TravelAgentError(
            "prior railway evidence omitted snapshot metadata"
        )
    retrieved_at = old_snapshot.get("retrieved_at")
    if not isinstance(retrieved_at, str) or not retrieved_at:
        raise TravelAgentError(
            "prior railway snapshot omitted retrieval time"
        )
    attempted_at = None
    if isinstance(failed_refresh.value, Mapping):
        raw_attempted = failed_refresh.value.get("attempted_at")
        if isinstance(raw_attempted, str):
            attempted_at = raw_attempted
    value["snapshot"] = rail_snapshot_metadata(
        "cache_fallback",
        retrieved_at=retrieved_at,
        attempted_at=attempted_at,
    )
    for direction in ("outbound", "return"):
        train = value.get(direction)
        if isinstance(train, Mapping):
            normalized_train = deepcopy(dict(train))
            # schedule_status / fare_status 不再写：它们落盘时按 _status
            # 后缀被剪掉，是写了没人读的死字段。余票哨兵留着——它有真作用，
            # 经推导变成字段级 unknown（见三段链路测试）。
            normalized_train["second_class_availability"] = "UNKNOWN"
            value[direction] = normalized_train
    value["refresh_failure"] = {
        "missing_reason": failed_refresh.missing_reason,
        "attempted_at": attempted_at,
    }
    return EvidenceItem(
        evidence_id=previous.evidence_id,
        domain="railway",
        status=EvidenceStatus.SOURCED,
        value=value,
        sources=previous.sources,
    )


def _stale_generic_evidence(
    previous: EvidenceItem,
    failed_refresh: EvidenceItem,
) -> EvidenceItem:
    if (
        not previous.status.is_usable
        or not isinstance(previous.value, Mapping)
    ):
        raise TravelAgentError(
            "evidence fallback requires prior sourced evidence"
        )
    value = business_view(previous)
    # 只留采集时刻。旧代码还把陈旧判定写进 status——freshness 是读取时刻的函数，
    # 冻进盘里就是 I5 违反，而 freshness 键本身在 I1 的禁用集里。
    value["freshness"] = {
        "retrieved_at": _latest_retrieved_at(previous.sources),
    }
    value["refresh_failure"] = {
        "missing_reason": failed_refresh.missing_reason,
    }
    routes = value.get("local_transit")
    if isinstance(routes, list):
        stale_routes: list[object] = []
        for route in routes:
            if not isinstance(route, Mapping):
                stale_routes.append(deepcopy(route))
                continue
            normalized_route = deepcopy(dict(route))
            if "fare" in normalized_route:
                normalized_route["fare"] = {
                    "status": "unknown",
                    "amount_cny": None,
                }
            stale_routes.append(normalized_route)
        value["local_transit"] = stale_routes
    hotels = value.get("hotel_candidates")
    if isinstance(hotels, list):
        sanitized_hotels: list[object] = []
        for hotel in hotels:
            if not isinstance(hotel, Mapping):
                sanitized_hotels.append(deepcopy(hotel))
                continue
            sanitized = deepcopy(dict(hotel))
            for key in tuple(sanitized):
                if "price" in str(key).lower():
                    sanitized[key] = None
            sanitized["price_status"] = "UNKNOWN"
            sanitized_hotels.append(sanitized)
        value["hotel_candidates"] = sanitized_hotels
        value["hotel_price_status"] = "UNKNOWN"
    return EvidenceItem(
        evidence_id=previous.evidence_id,
        domain=previous.domain,
        status=EvidenceStatus.SOURCED,
        value=value,
        sources=previous.sources,
    )



def _merged_support(*statuses: EvidenceStatus) -> EvidenceStatus:
    """合并两条可用证据时的 support 聚合（evidence-axes.md §2.4）。

    调用方已保证输入都是 ``is_usable``，因此这里只需要处理 sourced 与
    estimated 两支：任一 estimated 则结果 estimated。
    """

    aggregate = aggregate_support(
        [status.value for status in statuses],
        derivation_occurred=False,
    )
    return EvidenceStatus(aggregate.support)

def _merge_sourced_evidence(
    previous: EvidenceItem,
    current: EvidenceItem,
) -> EvidenceItem:
    if (
        not previous.status.is_usable
        or not current.status.is_usable
        or previous.domain != current.domain
    ):
        raise TravelAgentError("only sourced evidence in one domain can merge")
    if not isinstance(previous.value, Mapping) or not isinstance(
        current.value,
        Mapping,
    ):
        return current
    sources: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for source in (*previous.sources, *current.sources):
        key = json.dumps(
            source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if key not in seen:
            seen.add(key)
            sources.append(deepcopy(dict(source)))
    merged_value = _merge_values(previous.value, current.value)
    if current.domain == "map" and isinstance(merged_value, Mapping):
        merged_map = deepcopy(dict(merged_value))
        for field_name in (
            "local_transit",
            "local_transit_input_signature",
            "local_transit_outcome",
        ):
            if field_name in current.value:
                merged_map[field_name] = deepcopy(
                    current.value[field_name]
                )
        if (
            current.value.get("local_transit_outcome")
            in {"AVAILABLE", "PARTIAL"}
            and "local_transit_refresh_failure" not in current.value
        ):
            merged_map.pop("local_transit_refresh_failure", None)
        merged_value = merged_map
    return EvidenceItem(
        evidence_id=current.evidence_id,
        domain=current.domain,
        # 合并结果的 support 按 evidence-axes.md §2.4 聚合：任一输入为
        # estimated 则结果 estimated。这是 29 处闸门里唯一引入聚合规则的点
        # （p3b-gate-inventory.md §1.9）。
        status=_merged_support(previous.status, current.status),
        value=merged_value,
        sources=tuple(sources),
    )


def _merge_values(previous: object, current: object) -> object:
    if isinstance(previous, Mapping) and isinstance(current, Mapping):
        merged = deepcopy(dict(previous))
        for key, value in current.items():
            merged[str(key)] = (
                _merge_values(merged[key], value)
                if key in merged
                else deepcopy(value)
            )
        return merged
    if isinstance(previous, list) and isinstance(current, list):
        merged_list = deepcopy(previous)
        identity_key = next(
            (
                key
                for key in (
                    "attraction_id",
                    "route_id",
                    "field",
                    "source_id",
                )
                if any(
                    isinstance(item, Mapping) and key in item
                    for item in current
                )
            ),
            None,
        )
        if identity_key is not None:
            for item in current:
                if not isinstance(item, Mapping) or identity_key not in item:
                    continue
                match_index = next(
                    (
                        index
                        for index, previous_item in enumerate(merged_list)
                        if isinstance(previous_item, Mapping)
                        and previous_item.get(identity_key)
                        == item.get(identity_key)
                    ),
                    None,
                )
                if match_index is not None:
                    merged_list[match_index] = _merge_values(
                        merged_list[match_index],
                        item,
                    )
            current = [
                item
                for item in current
                if not (
                    isinstance(item, Mapping)
                    and identity_key in item
                    and any(
                        isinstance(previous_item, Mapping)
                        and previous_item.get(identity_key)
                        == item.get(identity_key)
                        for previous_item in previous
                    )
                )
            ]
        seen = {
            json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for item in merged_list
        }
        for item in current:
            key = json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if key not in seen:
                seen.add(key)
                merged_list.append(deepcopy(item))
        return merged_list
    return deepcopy(current)


def _latest_retrieved_at(
    sources: tuple[Mapping[str, object], ...],
) -> str | None:
    values = [
        str(source["retrieved_at"])
        for source in sources
        if isinstance(source.get("retrieved_at"), str)
    ]
    return max(values) if values else None


def _broker_query(
    intent: TravelIntent,
    action_id: str,
    state: _LoopState,
):
    return query_for_intent_domain(
        intent,
        action_id,
        route_inputs=(
            _web_route_inputs(state.evidence.get("web"))
            if action_id == "map"
            else None
        ),
    )


def _is_usable_action_evidence(
    action_id: str,
    data_type: str,
    evidence: EvidenceItem,
) -> bool:
    if not evidence.status.is_usable:
        return False
    if action_id != "map" or data_type != "route_duration":
        return True
    # 采集结果走 .value：它是采集元数据，本来就不在 facts 里
    # （persistence-v2.md §1.4.1）。
    value = evidence.value
    if not isinstance(value, Mapping):
        return False
    if value.get("local_transit_outcome") not in {"AVAILABLE", "PARTIAL"}:
        return False
    # 路线本身走 facts：字段级 support 不可用的路线不算采到了。旧代码只数
    # 列表长度，一条 support 全 unknown 的路线也会让本域被判为可用。
    routes = usable_fact_values(evidence.facts).get("local_transit")
    return isinstance(routes, list) and bool(routes)


def _web_route_inputs(
    evidence: EvidenceItem | None,
) -> tuple[str, list[str]] | None:
    if (
        evidence is None
        or not evidence.status.is_usable
    ):
        return None
    web_value = usable_fact_values(evidence.facts)
    hotel = web_value.get("hotel_area")
    base = (
        hotel.get("route_query_name", hotel.get("name"))
        if isinstance(hotel, Mapping)
        else None
    )
    attractions = web_value.get("attractions")
    if (
        not isinstance(base, str)
        or not base.strip()
        or not isinstance(attractions, list)
    ):
        return None
    names = [
        str(item.get("route_query_name", item["name"])).strip()
        for item in attractions
        if isinstance(item, Mapping)
        and isinstance(item.get("name"), str)
        and str(item["name"]).strip()
        and isinstance(item.get("route_query_name", item["name"]), str)
        and str(item.get("route_query_name", item["name"])).strip()
    ]
    unique_names = list(dict.fromkeys(names))
    explicit_sequence = web_value.get("route_sequence")
    if isinstance(explicit_sequence, list):
        sequence = [
            str(value).strip()
            for value in explicit_sequence
            if isinstance(value, str) and value.strip()
        ]
        expected = [base.strip(), *unique_names]
        if (
            len(sequence) == len(expected)
            and sequence[0] == base.strip()
            and set(sequence) == set(expected)
        ):
            return sequence[0], sequence[1:]
    return (
        (base.strip(), unique_names)
        if unique_names and base.strip() not in unique_names
        else None
    )


def _web_route_points(
    evidence: EvidenceItem | None,
    place_names: list[str],
) -> dict[str, Mapping[str, object]] | None:
    if (
        evidence is None
        or not evidence.status.is_usable
    ):
        return None
    web_value = usable_fact_values(evidence.facts)
    values: dict[str, Mapping[str, object]] = {}
    hotel = web_value.get("hotel_area")
    if isinstance(hotel, Mapping):
        name = hotel.get("route_query_name", hotel.get("name"))
        location = hotel.get("location")
        if isinstance(name, str) and isinstance(location, Mapping):
            values[name.strip()] = location
    attractions = web_value.get("attractions")
    if isinstance(attractions, list):
        for item in attractions:
            if not isinstance(item, Mapping):
                continue
            name = item.get("route_query_name", item.get("name"))
            location = item.get("location")
            if isinstance(name, str) and isinstance(location, Mapping):
                values[name.strip()] = location
    return (
        {name: values[name] for name in place_names}
        if all(name in values for name in place_names)
        else None
    )


def _web_route_segments(
    evidence: EvidenceItem | None,
    place_names: list[str],
) -> list[tuple[str, str]]:
    if (
        evidence is not None
        and evidence.status.is_usable
    ):
        raw_segments = usable_fact_values(evidence.facts).get("route_segments")
        if isinstance(raw_segments, list):
            result = [
                (str(item[0]).strip(), str(item[1]).strip())
                for item in raw_segments
                if isinstance(item, list)
                and len(item) == 2
                and all(isinstance(value, str) and value.strip() for value in item)
                and item[0] in place_names
                and item[1] in place_names
                and item[0] != item[1]
            ]
            if result:
                return result
    return list(zip(place_names, place_names[1:]))


def _normalize_local_transit(
    value: Mapping[str, object],
) -> list[dict[str, object]]:
    raw_segments = value.get("segments")
    if not isinstance(raw_segments, list):
        return []
    normalized: list[dict[str, object]] = []
    for index, segment in enumerate(raw_segments, start=1):
        if not isinstance(segment, Mapping):
            continue
        options: list[Mapping[str, object]] = []
        primary = segment.get("primary")
        if isinstance(primary, Mapping):
            options.append(primary)
        alternatives = segment.get("alternatives")
        if isinstance(alternatives, list):
            options.extend(
                item for item in alternatives if isinstance(item, Mapping)
            )
        selected = next(
            (
                option
                for option in options
                if isinstance(option.get("duration_seconds"), int)
                and not isinstance(option.get("duration_seconds"), bool)
                and int(option["duration_seconds"]) > 0
            ),
            None,
        )
        if selected is None:
            continue
        fare = selected.get("fare_cny", selected.get("cost_cny"))
        normalized.append(
            {
                "route_id": f"amap-local-{index}",
                "from": segment.get("from"),
                "to": segment.get("to"),
                "mode": selected.get("mode"),
                "duration_seconds": selected["duration_seconds"],
                "distance_meters": selected.get("distance_meters"),
                "polyline": deepcopy(selected.get("polyline")),
                "route_source": selected.get("source"),
                "fare": {
                    "status": (
                        "estimated" if isinstance(fare, (int, float)) else "unknown"
                    ),
                    "amount_cny": (
                        float(fare)
                        if isinstance(fare, (int, float))
                        and not isinstance(fare, bool)
                        else None
                    ),
                },
            }
        )
    return normalized


def _web_action(intent: TravelIntent) -> dict[str, object]:
    return {
        "action_id": "web",
        "action_type": "codex_web_research",
        "tool": "web",
        "title": "核验目的地公开事实",
        "query": {
            "destination": intent.destination_anchor,
            "parallel_tasks": [
                {
                    "task": "景点资料与住宿片区",
                    "required_for_first_plan": True,
                    "questions": [
                        "官方行政区全称是什么？",
                        "至少三个景点的名称和特色可由哪些一手来源支持？",
                        "可作为粗计划基地的住宿片区或交通枢纽是什么？",
                    ],
                },
                {
                    "task": "开放时间",
                    "required_for_first_plan": False,
                    "questions": ["各景点开放时间是否有一手来源？"],
                },
                {
                    "task": "门票",
                    "required_for_first_plan": False,
                    "questions": ["各景点门票是否有一手来源？"],
                },
            ],
            "per_source_timeout_seconds": 10,
            "max_sources_per_task": 3,
            "submit_core_evidence_immediately": True,
        },
        "required_evidence": {
            "domain": "web",
            "status": "sourced",
            "value_fields": ["destination_official_name", "verified_facts"],
            "sources_required": True,
        },
    }


def _read_token(evidence: EvidenceItem) -> str:
    """该域在**读取时刻**的 token。

    取代 ``value["freshness"]["status"]``——那是采集时冻结的判断，同一份落盘
    无论何时读都给同一个答案（I5）。读取时刻走 ``_READ_CLOCK``，产品默认墙钟。
    """

    return project_domain(
        {evidence.domain: evidence.to_dict()},
        evidence.domain,
        now=_READ_CLOCK(),
    ).token


def _needs_local_transit(state: _LoopState) -> bool:
    evidence = state.evidence.get("map")
    if (
        evidence is None
        or not evidence.status.is_usable
        or not isinstance(evidence.value, Mapping)
    ):
        return True
    # 路线走 facts：support 不可用的路线不算已采到，否则一条全 unknown 的
    # 路线会让本域被判为「不需要再采」。
    routes = usable_fact_values(evidence.facts).get("local_transit")
    route_inputs = _web_route_inputs(state.evidence.get("web"))
    if route_inputs is not None:
        base, attractions = route_inputs
        expected_signature = [base, *attractions]
        observed_signature = evidence.value.get(
            "local_transit_input_signature"
        )
        if (
            not isinstance(observed_signature, list)
            or len(observed_signature) != len(expected_signature)
            or set(observed_signature) != set(expected_signature)
        ):
            return True
        if evidence.value.get("local_transit_outcome") == "FAILED":
            # The exact route request already consumed its automatic retry.
            # Keep the failure explicit and let Planner return a partial plan;
            # only an explicit user re-query may run the same parameters again.
            if token_freshness(_read_token(evidence)) != FRESHNESS_STALE:
                return False
    return not isinstance(routes, list) or not routes


def _can_collect_local_transit(state: _LoopState) -> bool:
    map_item = state.evidence.get("map")
    if (
        map_item is None
        or not map_item.status.is_usable
        or not isinstance(map_item.value, Mapping)
    ):
        return False
    route_inputs = _web_route_inputs(state.evidence.get("web"))
    if route_inputs is None:
        return False
    base, attractions = route_inputs
    expected_signature = [base, *attractions]
    stale = token_freshness(_read_token(map_item)) == FRESHNESS_STALE
    if (
        "local_transit_outcome" in map_item.value
        and map_item.value.get("local_transit_input_signature")
        == expected_signature
        and not stale
    ):
        return False
    destination = usable_fact_values(map_item.facts).get("destination")
    adcode = (
        destination.get("adcode")
        if isinstance(destination, Mapping)
        else None
    )
    return (
        isinstance(adcode, str)
        and adcode.isdigit()
    )


def _loop_evidence(state: "_LoopState", intent: TravelIntent) -> dict:
    """编译输入的证据：容器 B（内存态即 ``state.evidence``）+ 重建的 user_input。

    A（``result["context"]["evidence"]``）已收敛，不再是证据来源
    （`persistence-v2.md` §2.1.1）。这里用的是 B 的**内存那一份**——它与盘上
    的 `evidence/current.json` 由 `_persist_loop_state` 同步写出，是同一份。
    """

    evidence = {
        domain: item.to_dict() for domain, item in state.evidence.items()
    }
    evidence["user_input"] = user_input_evidence(intent).to_dict()
    return evidence


def recomputed_planning_state(
    result: Mapping[str, object] | None,
    evidence: Mapping[str, Mapping[str, object]] | None = None,
) -> str | None:
    """按**读取时刻**重算 planning_state，不读盘上的副本。

    它会随 now 变——P4-b2 翻面证过：同一份 PlanVersion，新鲜时 PLAN_READY，
    过了容差窗就变 PARTIAL_READY 带 3 条 conditional。会随 now 变的值写在盘
    上就是 I5 的定义式违反，因此写入侧已停止落盘它。

    判定本身不是新建的——读取层一直有这个能力（`p4b-plan-readiness-sample.json`
    就是它的产物），这里只是把已存在的判定接上。

    **本函数不再自己碰证据 mapping**（2026-08-03 裁决：四入口收敛，不分叉）。
    它此前自己 compile 一次，而 ``trip_query.plan_readiness`` 又 compile 一次
    ——两份并列的实现读同一份 context、判同一件事，却没有任何东西保证它们
    给同一个答案。现在两边都走
    ``planning_input_compiler.plan_verdict_from_result``。
    """

    return plan_verdict_from_result(
        result,
        now=_READ_CLOCK(),
        evidence=evidence,
    ).planning_state


def _result_is_displayable(
    result: Mapping[str, object] | None,
    evidence: Mapping[str, Mapping[str, object]] | None = None,
) -> bool:
    """写入侧只验结构完整，「够不够格显示」是读取时的问题
    （persistence-v2.md §6.2）。

    两半各管各（`e579b28` 拆的那两个词）：``plan.artifact_kind`` 是**已写入**
    的结构判据，``usable_now`` 是**当前可用**的读取时刻结论。
    """

    if not isinstance(result, Mapping):
        return False
    plan = result.get("plan")
    if not (isinstance(plan, Mapping) and plan.get("artifact_kind") == "PlanVersion"):
        return False
    return plan_verdict_from_result(
        result,
        now=_READ_CLOCK(),
        evidence=evidence,
    ).usable_now


def _missing_display_requirements(
    result: Mapping[str, object] | None,
) -> list[str]:
    if not isinstance(result, Mapping):
        return [
            "cross_city_transport",
            "attraction",
            "local_transit",
            "accommodation_base",
        ]
    plan = result.get("planning_draft")
    if not isinstance(plan, Mapping):
        plan = result.get("plan")
    missing = plan.get("missing_requirements") if isinstance(plan, Mapping) else None
    if isinstance(missing, list):
        return [str(name) for name in missing]
    requirements = (
        plan.get("display_requirements")
        if isinstance(plan, Mapping)
        else None
    )
    if not isinstance(requirements, Mapping):
        return []
    return [
        str(name)
        for name, present in requirements.items()
        if present is not True
    ]


def _result_blockers(
    result: Mapping[str, object] | None,
) -> list[object]:
    if not isinstance(result, Mapping):
        return []
    plan = result.get("planning_draft")
    if not isinstance(plan, Mapping):
        plan = result.get("plan")
    raw = plan.get("conditional_blockers") if isinstance(plan, Mapping) else []
    return deepcopy(raw) if isinstance(raw, list) else []


def _plan_followup_actions(
    intent: TravelIntent,
    state: _LoopState,
) -> list[dict[str, object]]:
    missing = set(_missing_display_requirements(state.result))
    actions: list[dict[str, object]] = []
    if missing & {
        "cross_city_transport",
        "outbound_transport",
        "return_transport",
    }:
        actions.extend(
            (
                _registered_action(intent=intent, action_id="railway", mode="requery"),
                _manual_railway_action(intent),
            )
        )
    if missing & {
        "destination_resolved",
        "attraction",
        "accommodation_base",
    }:
        actions.append(_web_action(intent))
    if "accommodation_base" in missing:
        actions.extend(
            (
                {
                    "action_id": "accommodation_base_manual",
                    "action_type": "user_input",
                    "tool": "web",
                    "title": "手动填写住宿片区或交通枢纽",
                    "submit_action_id": "web",
                    "required_fields": ["hotel_area.name"],
                },
            )
        )
    if (
        missing & {"local_transit", "attraction_transit_coverage"}
        and _can_collect_local_transit(state)
    ):
        actions.append(
            _registered_action(
                "map",
                intent,
                state,
                mode="local_transit",
            )
        )
    elif missing & {"local_transit", "attraction_transit_coverage"}:
        actions.append(
            {
                "action_id": "local_transit_manual",
                "action_type": "user_input",
                "tool": "map",
                "title": "补充至少一段当地交通",
                "submit_action_id": "map",
                "required_fields": [
                    "local_transit[].from",
                    "local_transit[].to",
                    "local_transit[].duration_seconds",
                ],
            }
        )
    return actions


def _validate_railway_value(value: Mapping[str, object]) -> None:
    """铁路证据的提交门：**校验通过 = Planner 消费必成功**（I12）。

    校验吃的是 ``usable_fact_values(item.facts)``——**与规划器读的是同一个
    视图**，不是落盘形状也不是提交时的原始 mapping。这一点是本函数的全部要害：
    字段级投影会把 support 不可用的字段整个丢掉，只有在投影之后才看得见规划器
    实际拿得到什么。在原始 mapping 上校验会放行一份「投影后缺键」的证据，门就
    又比消费松了。

    放行三类，各有理由：

    * **两个方向都缺席** —— 已有的 ``RAILWAY_INPUT_UNAVAILABLE`` /
      ``RAILWAY_{}_MISSING`` 判定点负责，是规划结论不是提交错误；
    * **单个方向整体缺席** —— 同上，该方向排不出事件，另一个方向照排；
    * **已核实无直达**（``confirmed_absent``）—— 确定结论，本来就没有车次。

    拦一类：**方向在场但排不出事件**。这类过了门只会死在屋里，且报错位置
    （``make_rail_event`` 的 KeyError）与病因（提交少了键）隔着整条链路。
    报错逐个点名缺哪个方向的哪个键——宿主实测时拿到的是
    ``PLANNER_ACTION_FAILED``，从那句话推不回来该补什么。
    """

    if value.get("kind") == "confirmed_absent":
        return
    problems: list[str] = []
    for direction in _RAIL_DIRECTIONS:
        train = value.get(direction)
        if train is None:
            continue
        if not isinstance(train, Mapping):
            problems.append(f"{direction} 不是对象")
            continue
        missing = [
            field
            for field in RAIL_EVENT_REQUIRED_TRAIN_FIELDS
            if train.get(field) is None
        ]
        if missing:
            problems.append(
                f"{direction} 缺少 "
                + "、".join(f"{direction}.{field}" for field in missing)
            )
    if problems:
        raise TravelAgentError(
            "railway evidence cannot be scheduled: "
            + "；".join(problems)
            + "。必填项："
            + "、".join(RAILWAY_MANUAL_REQUIRED_FIELDS)
        )


def _validate_web_value(value: object) -> None:
    if not isinstance(value, Mapping):
        raise TravelAgentError("web evidence value must be an object")
    official_name = value.get("destination_official_name")
    facts = value.get("verified_facts")
    if not isinstance(official_name, str) or not official_name.strip():
        raise TravelAgentError(
            "web evidence requires destination_official_name"
        )
    if (
        not isinstance(facts, list)
        or not facts
        or any(not isinstance(item, Mapping) for item in facts)
    ):
        raise TravelAgentError("web evidence requires verified_facts")


def _block_run(
    run_id: str,
    domain: str,
    *,
    store: InMemoryAgentStore,
    stalled: bool = False,
) -> None:
    state = _state(run_id, store)
    item = state.evidence.get(domain)
    retained = (
        deepcopy(state.fallback_result)
        if isinstance(state.fallback_result, Mapping)
        else None
    )
    blocked_result = retained or {
        "action_loop_status": "BLOCKED",
        "blocked_domains": [domain],
        "context": {
            "missing_domains": (
                [domain]
                if item is None or item.status is EvidenceStatus.MISSING
                else []
            ),
            "conflicting_domains": (
                [domain]
                if item is not None
                and item.status is EvidenceStatus.CONFLICTING
                else []
            ),
        },
    }
    store.block(
        run_id,
        blocked_result,
        (
            f"{domain.upper()}_ACTION_STALLED"
            if stalled
            else f"{domain.upper()}_ACTION_FAILED"
        ),
    )


def _timeout_actions(
    run_id: str,
    action_ids: list[str],
    *,
    store: InMemoryAgentStore,
) -> None:
    """Close actions that made no observable progress for 30 seconds."""

    state = _state(run_id, store)
    for action_id in action_ids:
        if action_id in state.action_status:
            state.action_status[action_id] = "blocked"
        store.append_event(
            run_id,
            event_type="tool.timeout",
            status="failed",
            message=f"{_action_title(action_id)}超过30秒没有新进展。",
            details={
                "tool": action_id,
                "timeout_seconds": 30,
            },
        )
    _persist_loop_state(run_id, state, store)
    _block_run(
        run_id,
        action_ids[0],
        store=store,
        stalled=True,
    )


def _blocked_recovery(
    run: object,
    result: Mapping[str, object],
) -> list[dict[str, object]]:
    """BLOCKED 快照上的出路清单。**空列表也是答案**——但要是真的没有出路。

    宿主实测（2026-08-03）两个 P0 共用同一个体验症状：run 停了，只给一个错误码
    （``PLANNER_ACTION_FAILED`` / ``GUIDED_COMPARISON_UNAVAILABLE``），没有任何
    地方写着「接下来能做什么」。宿主于是靠试——试到的那条是改写
    ``destination_expression`` 绕状态机。

    出路是**代码里真有的迁移**，不是安慰话：每条都点名入口函数，与实现里的
    状态守卫一一对应。写不出入口的就不写（D14：存在性不冒充可用性）。
    """

    declared = result.get("recovery")
    if isinstance(declared, list) and declared:
        # 比较失败那一支自己写好了出路（_failed_comparison_result），原样透传，
        # 不在这里重述——两份会各改各的（D19）。
        return [dict(item) for item in declared if isinstance(item, Mapping)]

    intent = getattr(run, "intent", None)
    task_mode = getattr(intent, "task_mode", None)
    if task_mode is not TaskMode.DIRECT_PLAN:
        return []
    # DIRECT_PLAN 的阻塞有两条真出路，都在 trip_application 里：
    # submit_run_evidence 与 execute_trip 各自在 BLOCKED 时调
    # restart_action_loop_for_intent。
    blocked = list(_mapping_list(result, "blocked_domains"))
    return [
        {
            "kind": "resubmit_evidence",
            "entrypoint": "submit_trip_evidence",
            "arguments": {"run_id": "<本 run>"},
            "detail": (
                "重新提交修正后的证据，动作循环会就地重启并继续。"
                + (f"当前受阻的域：{'、'.join(blocked)}。" if blocked else "")
            ),
        },
        {
            "kind": "restart_action_loop",
            "entrypoint": "advance_trip_task",
            "arguments": {"run_id": "<本 run>"},
            "detail": "不改证据，直接让动作循环重跑一轮。",
        },
    ]


def _snapshot(
    run_id: str,
    status: str,
    actions: list[dict[str, object]],
    **extra: object,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "status": status,
        "actions": deepcopy(actions),
        **deepcopy(extra),
    }


def _state(
    run_id: str,
    store: InMemoryAgentStore | None = None,
) -> _LoopState:
    store = store if store is not None else default_agent_store()
    with _LOCK:
        state = _STATES.get(run_id)
        if state is None:
            state = _load_loop_state(run_id, store)
            if state is None:
                raise TravelAgentError(
                    "action loop was not started"
                ) from None
            _STATES[run_id] = state
        return state


def _action_title(action_id: str) -> str:
    return {
        "railway": "中国铁路12306查询",
        "web": "网页事实核验",
        "map": "高德目的地核验",
        "planner": "通用Planner",
    }[action_id]


def _mapping_list(value: Mapping[str, object], key: str) -> list[object]:
    raw = value.get(key, [])
    return list(raw) if isinstance(raw, list) else []


def record_refetched_evidence(
    run_id: str,
    items: Sequence[tuple[str, Mapping[str, object]]],
    *,
    store: InMemoryAgentStore | None = None,
) -> tuple[str, ...]:
    """把读时重采的产出写回**既有**证据通道（`freshness-policy.md` §5.2.2）。

    这不是新开的写入通道：它走的就是动作循环一直在用的那条
    ``state.evidence[domain]`` + ``_persist_loop_state``。读取层只负责给出
    「重采到了什么、该写回哪些」，写盘由应用层协调——读取层写盘会破它自己的
    只读契约，也会让两次读取产生不同的文件内容（I5）。

    返回真正写回的域。运行不在可写状态时**静默跳过**：读取路径不该因为
    「这个 run 已经结束了」而报错，那会把一次普通的页面刷新变成异常。
    """

    store = store if store is not None else default_agent_store()
    if not items:
        return ()
    state = _load_loop_state(run_id, store)
    if state is None:
        return ()
    written: list[str] = []
    for domain, item in items:
        if domain not in state.evidence:
            continue
        try:
            state.evidence[domain] = EvidenceItem.from_mapping(dict(item))
        except TravelAgentError:
            # 重采回来的形状不合契约时不写回，也不让读取崩——本次读取照常
            # 用内存里的那份，下次读取会重试。
            continue
        written.append(domain)
    if written:
        _persist_loop_state(run_id, state, store)
    return tuple(written)


def _persist_loop_state(
    run_id: str,
    state: _LoopState,
    store: InMemoryAgentStore,
) -> None:
    run_directory = store.run_directory(run_id)
    if run_directory is None:
        return
    _atomic_runtime_json(
        run_directory / "action-loop.json",
        state.to_dict(),
    )
    _atomic_runtime_json(
        run_directory / "evidence" / "current.json",
        state.evidence_dict(run_id),
    )


def _load_loop_state(
    run_id: str,
    store: InMemoryAgentStore,
) -> _LoopState | None:
    run_directory = store.run_directory(run_id)
    if run_directory is None:
        return None
    action_path = run_directory / "action-loop.json"
    evidence_path = run_directory / "evidence" / "current.json"
    legacy_evidence_path = run_directory / "evidence.json"
    if not evidence_path.exists() and legacy_evidence_path.is_file():
        evidence_path = legacy_evidence_path
    if not action_path.exists() and not evidence_path.exists():
        return None
    if not action_path.is_file() and evidence_path.is_file():
        # §13.1 的中断窗口：run.json 先落、action-loop.json 后落，两次写之间
        # 崩溃就留下这个状态。裁决要求「action-loop.json 缺失或落后时，从
        # run.json 重建」——权威在 run.json，这里据它把调度状态重算出来，
        # 而不是把这次崩溃当成不可恢复。
        return _rebuild_loop_state(run_id, store, evidence_path)
    if not action_path.is_file() or not evidence_path.is_file():
        raise TravelAgentError(
            "persisted action loop omitted state or evidence"
        )
    action = _runtime_json_object(action_path)
    evidence = _runtime_json_object(evidence_path)
    raw_status = action.get("action_status")
    if not isinstance(raw_status, Mapping):
        raise TravelAgentError(
            "persisted action loop has invalid action_status"
        )
    statuses: dict[str, str] = {}
    for action_id in _ACTION_ORDER:
        value = raw_status.get(action_id)
        if value not in {
            "waiting",
            "running",
            "completed",
            "failed",
            "blocked",
        }:
            raise TravelAgentError(
                "persisted action loop has invalid action state"
            )
        statuses[action_id] = (
            "waiting" if value == "running" else str(value)
        )
    current = _evidence_items(evidence.get("current"), "current")
    last_sourced = _evidence_items(
        evidence.get("last_sourced"),
        "last_sourced",
    )
    # result 的权威是 run.json（§13.1）。action-loop.json 里不再有副本，
    # 恢复时从 run.json 取——「action-loop.json 缺失或落后时，从 run.json
    # 重建」在这里落地。旧文件里若还残留 result，忽略它：权威只有一个，
    # 读两个来源、挑一个用，等于把「哪份对」的问题留给运行时掷骰子。
    raw_result = store.get_run(run_id).result
    if raw_result is not None and not isinstance(raw_result, Mapping):
        raise TravelAgentError(
            "persisted run has invalid result"
        )
    raw_fallback = action.get("fallback_result")
    if raw_fallback is not None and not isinstance(
        raw_fallback,
        Mapping,
    ):
        raise TravelAgentError(
            "persisted action loop has invalid fallback_result"
        )
    return _LoopState(
        evidence={item.domain: item for item in current},
        last_sourced_evidence={
            item.domain: item for item in last_sourced
        },
        action_status=statuses,
        result=(
            deepcopy(dict(raw_result))
            if isinstance(raw_result, Mapping)
            else None
        ),
        fallback_result=(
            deepcopy(dict(raw_fallback))
            if isinstance(raw_fallback, Mapping)
            else None
        ),
    )


def _rebuild_loop_state(
    run_id: str,
    store: InMemoryAgentStore,
    evidence_path: Path,
) -> _LoopState:
    """从 ``run.json`` + ``evidence/current.json`` 重建动作循环状态。

    只在 ``action-loop.json`` 缺失时走这里（§13.1 的恢复条款）。重建的是
    **调度状态**：哪些域已经拿到可用证据、planner 跑没跑完。这些都能从权威
    数据推出来，不需要 action-loop.json 那份副本。

    ``fallback_result`` 重建不出来——它是动作循环启动那一刻的 ``run.result``
    快照，而 ``run.result`` 已被覆盖。这里如实留 ``None``，不拿当前的
    ``run.result`` 冒充它：那会把详细规划结果当成比较阶段的候选卡，是一次
    静默的张冠李戴。
    """

    evidence = _runtime_json_object(evidence_path)
    current = _evidence_items(evidence.get("current"), "current")
    last_sourced = _evidence_items(
        evidence.get("last_sourced"),
        "last_sourced",
    )
    result = store.get_run(run_id).result
    statuses = {action_id: "waiting" for action_id in _ACTION_ORDER}
    for item in current:
        if item.domain in statuses and item.status.is_usable:
            statuses[item.domain] = "completed"
    if isinstance(result, Mapping) and result.get("plan") is not None:
        statuses["planner"] = "completed"
    return _LoopState(
        evidence={item.domain: item for item in current},
        last_sourced_evidence={
            item.domain: item for item in last_sourced
        },
        action_status=statuses,
        result=(
            deepcopy(dict(result))
            if isinstance(result, Mapping)
            else None
        ),
        fallback_result=None,
    )


def _evidence_items(
    value: object,
    field: str,
) -> list[EvidenceItem]:
    if not isinstance(value, list) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise TravelAgentError(
            f"persisted evidence {field} must be an array"
        )
    return [
        EvidenceItem.from_mapping(item)
        for item in value
        if isinstance(item, Mapping)
    ]


def _runtime_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TravelAgentError(
            f"persisted action file is unreadable: {path.name}"
        ) from error
    if not isinstance(value, dict):
        raise TravelAgentError(
            f"persisted action file is not an object: {path.name}"
        )
    return value


__all__ = [
    "execute_registered_action",
    "get_next_actions",
    "restart_action_loop_for_intent",
    "run_until_blocked",
    "start_action_loop",
    "record_refetched_evidence",
    "submit_evidence",
]
