"""Action-driven orchestration for a Codex-hosted trip run.

Registered runtime tools execute inside the local product.  Web research stays
an explicit Codex action and enters the run only through ``submit_evidence``.
No collector result is marked complete unless it is sourced evidence.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from trip_decider.destination_runtime import (
    collect_map_evidence,
    collect_railway_evidence,
)
from trip_decider.itinerary_planner import (
    plan_destination_context,
    validate_destination_plan,
)
from trip_decider.intercity_rail import rail_snapshot_metadata
from trip_decider.planning_input_compiler import PlanningInputCompiler
from trip_decider.simple_live import (
    _LiveFailure,
    estimate_live_public_transport_segments,
)
from trip_decider.travel_agent import (
    DEFAULT_AGENT_STORE,
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
    RunStatus,
    TravelAgentError,
    TravelIntent,
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

    def to_dict(self) -> dict[str, object]:
        return {
            "action_status": dict(self.action_status),
            "result": deepcopy(self.result),
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


def start_action_loop(
    run_id: str,
    *,
    store: InMemoryAgentStore = DEFAULT_AGENT_STORE,
) -> dict[str, object]:
    """Move a confirmed run into its action-driven execution state."""

    run = store.get_run(run_id)
    if run.status is not RunStatus.CONFIRMED:
        raise TravelAgentError("run must be confirmed before action execution")
    store.start(run_id)
    with _LOCK:
        state = _LoopState()
        _STATES[run_id] = state
        _persist_loop_state(run_id, state, store)
    return get_next_actions(run_id, store=store)


def run_until_blocked(
    run_id: str,
    *,
    store: InMemoryAgentStore = DEFAULT_AGENT_STORE,
) -> dict[str, object]:
    """Execute local registered tools and pause at external evidence actions.

    A failed railway refresh is deliberately not retried here: the returned
    actions expose both explicit re-query and manual train entry.  This keeps
    retry authority with the caller and prevents an implicit retry loop.
    """

    executed: set[tuple[str, str]] = set()
    for _ in range(16):
        snapshot = get_next_actions(run_id, store=store)
        if snapshot["status"] in {"READY", "BLOCKED"}:
            return snapshot
        actions = snapshot.get("actions")
        if not isinstance(actions, list):
            raise TravelAgentError("action snapshot omitted actions")
        executable = next(
            (
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
            ),
            None,
        )
        if executable is None:
            return {
                **snapshot,
                "status": "NEED_USER_INPUT",
                "paused_at": [
                    str(action.get("action_type"))
                    for action in actions
                    if isinstance(action, Mapping)
                ],
            }
        action_id = str(executable["action_id"])
        mode = str(executable.get("mode", "initial"))
        executed.add((action_id, mode))
        execute_registered_action(run_id, action_id, store=store)
    raise TravelAgentError("run-until-blocked exceeded its action bound")


def get_next_actions(
    run_id: str,
    *,
    store: InMemoryAgentStore = DEFAULT_AGENT_STORE,
) -> dict[str, object]:
    """Return the next honest state and executable actions for Codex."""

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
        return _snapshot(
            run_id,
            "NEED_USER_INPUT",
            _plan_followup_actions(run.intent, state),
            reason="displayable_itinerary_requirements_missing",
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
        and "web" in state.evidence
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
    store: InMemoryAgentStore = DEFAULT_AGENT_STORE,
) -> dict[str, object]:
    """Execute one registered 12306, AMap, or Planner action."""

    run = store.get_run(run_id)
    if (
        run.status is RunStatus.COMPLETED
        and action_id in {"railway", "map"}
    ):
        run = store.resume(run_id)
    if run.status is not RunStatus.RUNNING:
        raise TravelAgentError("run is not executing actions")
    state = _state(run_id, store)
    if action_id not in _TOOL_REGISTRY:
        raise TravelAgentError("action is not a registered runtime tool")
    is_refresh = (
        action_id in {"railway", "map"}
        and state.action_status[action_id] in {"completed", "failed"}
    )
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
        _persist_plan_version(run_id, result, store)
        store.append_event(
            run_id,
            event_type="tool.completed",
            status="completed",
            message="Planner完成并通过证据边界校验。",
            details={"tool": "planner"},
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
    store: InMemoryAgentStore = DEFAULT_AGENT_STORE,
) -> dict[str, object]:
    """Validate and attach one action-owned evidence item."""

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
    if item.status is EvidenceStatus.SOURCED:
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


def _map_handler(
    intent: TravelIntent,
    state: _LoopState,
) -> EvidenceItem:
    web_value = state.evidence["web"].value
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
    district_evidence = collect_map_evidence(
        replace(intent, destination_anchor=selected_name)
    )
    if (
        district_evidence.status is EvidenceStatus.SOURCED
        and isinstance(district_evidence.value, Mapping)
        and isinstance(
            district_evidence.value.get("local_transit"),
            list,
        )
        and district_evidence.value["local_transit"]
    ):
        return district_evidence
    if (
        district_evidence.status is not EvidenceStatus.SOURCED
        or not _web_route_inputs(state.evidence.get("web"))
    ):
        return district_evidence
    value = district_evidence.value
    destination = (
        value.get("destination")
        if isinstance(value, Mapping)
        else None
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
    segments = [
        (place_names[index], place_names[index + 1])
        for index in range(len(place_names) - 1)
    ]
    try:
        route_result = estimate_live_public_transport_segments(
            city=selected_name,
            city_adcode=city_adcode,
            place_names=place_names,
            segments=segments,
        )
    except _LiveFailure as error:
        enriched = deepcopy(dict(value))
        enriched["local_transit_result_status"] = "FAILED"
        enriched["local_transit_input_signature"] = route_signature
        enriched["local_transit_refresh_failure"] = {
            "stage": error.stage,
            "python_exception_type": error.python_exception_type,
        }
        return EvidenceItem(
            evidence_id=district_evidence.evidence_id,
            domain="map",
            status=EvidenceStatus.SOURCED,
            value=enriched,
            sources=district_evidence.sources,
        )
    local_transit = _normalize_local_transit(route_result)
    enriched = deepcopy(dict(value))
    enriched["local_transit"] = local_transit
    enriched["local_transit_result_status"] = route_result.get("status")
    enriched["local_transit_input_signature"] = route_signature
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
        status=EvidenceStatus.SOURCED,
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
    compiled = PlanningInputCompiler().compile(context)
    plan = plan_destination_context(context.to_dict())
    plan = {
        **plan,
        "status": compiled["status"],
        "days": compiled["days"],
        "planning_input": {
            key: deepcopy(compiled[key])
            for key in (
                "cross_city_rail_events",
                "attraction_events",
                "local_transit_events",
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
        "accommodation_notice": (
            "具体酒店未选择，当前使用住宿片区或交通枢纽；"
            "首末段交通待细化。"
            if compiled["display_requirements"]["accommodation_base"]
            else None
        ),
    }
    validation = validate_destination_plan(context.to_dict(), plan)
    if validation.get("valid") is not True:
        raise TravelAgentError("planner output failed context validation")
    days = plan.get("days")
    if not isinstance(days, list) or not days:
        raise TravelAgentError(
            "planner did not produce a non-empty itinerary"
        )
    return {
        "action_loop_status": (
            "READY"
            if compiled["displayable"]
            else "NEED_USER_INPUT"
        ),
        "task_mode": intent.task_mode.value,
        "context": context.to_dict(),
        "plan": deepcopy(dict(plan)),
        "validation": deepcopy(dict(validation)),
        "pipeline": [
            "parse_intent",
            "collect_evidence",
            "build_destination_context",
            "plan",
            "validate",
        ],
    }


_TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "railway": {
        "title": "中国铁路12306查询",
        "handler": _railway_handler,
    },
    "map": {
        "title": "高德目的地核验",
        "handler": _map_handler,
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
        value = state.evidence["web"].value
        arguments = {
            "destination": (
                value.get("destination_official_name")
                if isinstance(value, Mapping)
                else None
            )
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
        previous.status is not EvidenceStatus.SOURCED
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
        previous.status is not EvidenceStatus.SOURCED
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
    return EvidenceItem(
        evidence_id=previous.evidence_id,
        domain=previous.domain,
        status=EvidenceStatus.SOURCED,
        value=value,
        sources=previous.sources,
    )


def _merge_sourced_evidence(
    previous: EvidenceItem,
    current: EvidenceItem,
) -> EvidenceItem:
    if (
        previous.status is not EvidenceStatus.SOURCED
        or current.status is not EvidenceStatus.SOURCED
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
    return EvidenceItem(
        evidence_id=current.evidence_id,
        domain=current.domain,
        status=EvidenceStatus.SOURCED,
        value=_merge_values(previous.value, current.value),
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


def _web_route_inputs(
    evidence: EvidenceItem | None,
) -> tuple[str, list[str]] | None:
    if (
        evidence is None
        or evidence.status is not EvidenceStatus.SOURCED
        or not isinstance(evidence.value, Mapping)
    ):
        return None
    hotel = evidence.value.get("hotel_area")
    base = hotel.get("name") if isinstance(hotel, Mapping) else None
    attractions = evidence.value.get("attractions")
    if (
        not isinstance(base, str)
        or not base.strip()
        or not isinstance(attractions, list)
    ):
        return None
    names = [
        str(item["name"]).strip()
        for item in attractions
        if isinstance(item, Mapping)
        and isinstance(item.get("name"), str)
        and str(item["name"]).strip()
    ]
    unique_names = list(dict.fromkeys(names))
    return (
        (base.strip(), unique_names)
        if unique_names and base.strip() not in unique_names
        else None
    )


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
            "questions": [
                "官方行政区全称是什么？",
                "至少一个景点及其开放时间可由哪些一手来源支持？",
                "可作为粗计划基地的住宿片区或交通枢纽是什么？",
            ],
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
        or evidence.status is not EvidenceStatus.SOURCED
        or not isinstance(evidence.value, Mapping)
    ):
        return True
    routes = evidence.value.get("local_transit")
    return not isinstance(routes, list) or not routes


def _can_collect_local_transit(state: _LoopState) -> bool:
    map_item = state.evidence.get("map")
    if (
        map_item is None
        or map_item.status is not EvidenceStatus.SOURCED
        or not isinstance(map_item.value, Mapping)
    ):
        return False
    route_inputs = _web_route_inputs(state.evidence.get("web"))
    if route_inputs is None:
        return False
    base, attractions = route_inputs
    expected_signature = [base, *attractions]
    if (
        "local_transit_result_status" in map_item.value
        and map_item.value.get("local_transit_input_signature")
        == expected_signature
    ):
        return False
    destination = map_item.value.get("destination")
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
    return isinstance(plan, Mapping) and plan.get("displayable") is True


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
    plan = result.get("plan")
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
    plan = result.get("plan")
    raw = plan.get("conditional_blockers") if isinstance(plan, Mapping) else []
    return deepcopy(raw) if isinstance(raw, list) else []


def _plan_followup_actions(
    intent: TravelIntent,
    state: _LoopState,
) -> list[dict[str, object]]:
    missing = set(_missing_display_requirements(state.result))
    actions: list[dict[str, object]] = []
    if "cross_city_transport" in missing:
        actions.extend(
            (
                _registered_action(intent=intent, action_id="railway", mode="requery"),
                _manual_railway_action(intent),
            )
        )
    if "attraction" in missing:
        actions.append(
            {
                **_web_action(intent),
                "mode": "attractions_and_opening_hours",
            }
        )
    if "accommodation_base" in missing:
        actions.extend(
            (
                {
                    **_web_action(intent),
                    "mode": "accommodation_area",
                },
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
        "local_transit" in missing
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
    elif "local_transit" in missing:
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
) -> None:
    state = _state(run_id, store)
    item = state.evidence.get(domain)
    store.block(
        run_id,
        {
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
        },
        f"{domain.upper()}_EVIDENCE_BLOCKED",
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
    store: InMemoryAgentStore = DEFAULT_AGENT_STORE,
) -> _LoopState:
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
        run_directory / "evidence.json",
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
    evidence_path = run_directory / "evidence.json"
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


def _persist_plan_version(
    run_id: str,
    result: Mapping[str, object],
    store: InMemoryAgentStore,
) -> None:
    run_directory = store.run_directory(run_id)
    if run_directory is None:
        return
    versions = run_directory / "plans"
    versions.mkdir(parents=True, exist_ok=True)
    existing = sorted(versions.glob("plan-*.json"))
    version = len(existing) + 1
    plan = result.get("plan")
    if not isinstance(plan, Mapping):
        raise TravelAgentError("planner result omitted plan")
    payload = {
        "run_id": run_id,
        "plan_version": version,
        "plan": deepcopy(dict(plan)),
    }
    _atomic_runtime_json(
        versions / f"plan-{version:04d}.json",
        payload,
    )
    _atomic_runtime_json(
        run_directory / "plan-version.json",
        payload,
    )


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


def _atomic_runtime_json(
    path: Path,
    value: Mapping[str, object],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


__all__ = [
    "execute_registered_action",
    "get_next_actions",
    "run_until_blocked",
    "start_action_loop",
    "submit_evidence",
]
