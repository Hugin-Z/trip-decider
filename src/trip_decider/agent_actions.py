"""Action-driven orchestration for a Codex-hosted trip run.

Registered runtime tools execute inside the local product.  Destination POI
and lodging candidates come from the live provider collector; unresolved
opening hours, ticket prices, and lodging prices remain explicit missing data.
No collector result is marked complete unless it is sourced evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
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
from trip_decider.evidence_projection import usable_fact_values
from trip_decider.evidence_broker import (
    default_evidence_broker,
    EvidenceBroker,
    evidence_collected_at,
    query_for_intent_domain,
)
from trip_decider.itinerary_planner import (
    plan_destination_context,
    validate_destination_plan,
)
from trip_decider.evidence_core import aggregate_support
from trip_decider.intercity_rail import rail_snapshot_metadata
from trip_decider.planning_input_compiler import PlanningInputCompiler
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
    RunStatus,
    TravelAgentError,
    TravelIntent,
    atomic_runtime_json as _atomic_runtime_json,
    build_destination_context,
)


_DOMAINS = ("railway", "web", "map")
_ACTION_ORDER = ("railway", "web", "map", "planner")


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
        return {
            "action_status": dict(self.action_status),
            "result": deepcopy(self.result),
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
                deepcopy(dict(run.result))
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
                "evidence_status": "sourced",
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
        if _result_is_displayable(state.result):
            return _snapshot(run_id, "READY", [], result=state.result)
        if _result_planning_state(state.result) == "BLOCKED":
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
        _persist_loop_state(run_id, state, store)
        if _result_is_displayable(result):
            store.persist_plan_version(run_id, result)
        store.append_event(
            run_id,
            event_type="tool.completed",
            status="completed",
            message=(
                "计划版本已通过证据门并安装。"
                if _result_is_displayable(result)
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
        if _result_is_displayable(result):
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
            _validate_web_value(merged.value)
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
                "evidence_status": "sourced",
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
                "evidence_status": "sourced",
                "snapshot_status": "STALE",
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
            "evidence_status": item.status.value,
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
    web_value = web_evidence.value if web_evidence is not None else None
    official_name = (
        web_value.get("destination_official_name")
        if isinstance(web_value, Mapping)
        else None
    )
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
        and isinstance(district_evidence.value, Mapping)
        and isinstance(
            district_evidence.value.get("local_transit"),
            list,
        )
        and district_evidence.value["local_transit"]
    ):
        return district_evidence
    if (
        not district_evidence.status.is_usable
        or not _web_route_inputs(state.evidence.get("web"))
    ):
        return district_evidence
    value = district_evidence.value
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
        route["evidence_status"] = "LIVE"
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
    user = EvidenceItem(
        evidence_id="confirmed-travel-intent",
        domain="user_input",
        status=EvidenceStatus.SOURCED,
        value=intent.to_dict(),
        sources=(
            {
                "source_type": "user_supplied",
                "locator": "confirmed_travel_intent",
            },
        ),
    )
    context = build_destination_context(
        intent,
        (user, *(state.evidence[domain] for domain in _DOMAINS)),
    )
    compiled = PlanningInputCompiler().compile(context, now=_READ_CLOCK())
    planning_draft = plan_destination_context(context.to_dict())
    planning_draft = {
        **planning_draft,
        "artifact_kind": "PlanningDraft",
        "planning_state": compiled["planning_state"],
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
        "displayable": compiled["displayable"],
        "display_status": compiled["display_status"],
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
        "planning_state": compiled["planning_state"],
        "task_mode": intent.task_mode.value,
        "context": context.to_dict(),
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
        value = web_evidence.value if web_evidence is not None else None
        arguments = {
            "destination": (
                value.get("destination_official_name")
                if isinstance(value, Mapping)
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
        "required_fields": [
            "outbound",
            "return",
            "fare",
            "source",
        ],
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
    value = deepcopy(dict(previous.value))
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
        "STALE",
        retrieved_at=retrieved_at,
        attempted_at=attempted_at,
    )
    for direction in ("outbound", "return"):
        train = value.get(direction)
        if isinstance(train, Mapping):
            normalized_train = deepcopy(dict(train))
            normalized_train["schedule_status"] = "STALE"
            normalized_train["fare_status"] = "STALE"
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
    value = deepcopy(dict(previous.value))
    value["freshness"] = {
        "status": "STALE",
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
            normalized_route["evidence_status"] = "STALE"
            normalized_route["schedule_status"] = "STALE"
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
            freshness = evidence.value.get("freshness")
            if not (
                isinstance(freshness, Mapping)
                and freshness.get("status") == "STALE"
            ):
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
    freshness = map_item.value.get("freshness")
    stale = (
        isinstance(freshness, Mapping)
        and freshness.get("status") == "STALE"
    )
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


def _result_is_displayable(
    result: Mapping[str, object] | None,
) -> bool:
    if not isinstance(result, Mapping):
        return False
    plan = result.get("plan")
    return (
        result.get("planning_state") in {"PARTIAL_READY", "PLAN_READY"}
        and isinstance(plan, Mapping)
        and plan.get("artifact_kind") == "PlanVersion"
        and plan.get("planning_state") == result.get("planning_state")
        and plan.get("displayable") is True
    )


def _result_planning_state(
    result: Mapping[str, object] | None,
) -> str | None:
    if not isinstance(result, Mapping):
        return None
    value = result.get("planning_state")
    return str(value) if isinstance(value, str) else None


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
            else f"{domain.upper()}_EVIDENCE_BLOCKED"
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
    raw_result = action.get("result")
    if raw_result is not None and not isinstance(raw_result, Mapping):
        raise TravelAgentError(
            "persisted action loop has invalid result"
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
    "submit_evidence",
]
