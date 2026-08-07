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
from pathlib import Path
from threading import RLock
import time
from typing import Any

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

#: 可直接作为 ``submit_trip_evidence(..., evidence=...)`` 参数回喂的完整示例。
#: ``value`` 的嵌套层、action_id 与来源都在同一个对象里；missing 视图不再只
#: 公布一段需要宿主自行猜包装方式的 JSON 字符串（I12 / D20）。
RAILWAY_MANUAL_EXAMPLE: dict[str, object] = {
    "action_id": "railway",
    "value": {
        "outbound": {
            "train_code": "G100",
            "departure_at": "2026-08-11T09:00",
            "arrival_at": "2026-08-11T12:00",
            "origin_station": "<出发站全称>",
            "destination_station": "<到达站全称>",
        },
        "return": {
            "train_code": "G101",
            "departure_at": "2026-08-14T18:00",
            "arrival_at": "2026-08-14T21:00",
            "origin_station": "<到达站全称>",
            "destination_station": "<出发站全称>",
        },
    },
    "sources": [
        {
            "provider": "中国铁路12306",
            "retrieved_at": "2026-08-05T13:30:00+08:00",
        }
    ],
}


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
#: 并发：`_LOCK` 锁保护，锁对象表的全部读写都在锁内。
_RUN_LOCKS: dict[str, RLock] = {}

#: 并发：`_LOCK` 只保护两个模块级字典本身；每个 `_LoopState` 的字段以及对应
#: 的两个落盘文件由 `_run_lock(run_id)` 保护。
#:
#: 这是一份**跨调用共享的可变状态**——动作循环的内存缓存，键是 run_id。写它的
#: 有两类线程：工具调用线程（同步推进）与后台动作循环线程。两者都必须先取
#: `_LOCK`，且**不得在持锁期间做网络 I/O**（那会把前台调用一起拖住，正是
#: I13 要防的）。取数据、放锁、再采集，采完重新取锁写回。
#:
#: 落盘那一份（`action-loop.json`）与本表的关系见 persistence-v2.md §13.1：
#: 权威在 `run.json`，本表是它的内存视图，缺失时可重建。
#: 并发：`_run_lock(run_id)` 锁保护每个值的字段读写，`_LOCK` 保护表本身。
_STATES: dict[str, _LoopState] = {}


def _run_lock(run_id: str) -> RLock:
    """同一 run 串行提交状态；不同 run 互不阻塞，也不把网络 I/O 锁进去。"""

    with _LOCK:
        return _RUN_LOCKS.setdefault(run_id, RLock())

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

    with _run_lock(run_id):
        run = store.get_run(run_id)
        if run.status is not RunStatus.CONFIRMED:
            raise TravelAgentError("run must be confirmed before action execution")
        store.start(run_id)
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
        with _LOCK:
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

    with _run_lock(run_id):
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


def resume_missing_action_loop(
    run_id: str,
    *,
    store: InMemoryAgentStore | None = None,
) -> dict[str, object]:
    """恢复 ``store.start`` 后、动作循环首次落盘前崩溃的 DIRECT_PLAN。"""

    store = store if store is not None else default_agent_store()
    with _run_lock(run_id):
        run = store.get_run(run_id)
        if run.status is not RunStatus.RUNNING:
            raise TravelAgentError("run is not executing actions")
        loaded = _load_loop_state(run_id, store)
        if loaded is not None:
            with _LOCK:
                _STATES[run_id] = loaded
            return get_next_actions(run_id, store=store)
        state = _LoopState(
            fallback_result=(
                recovery_safe(deepcopy(dict(run.result)))
                if isinstance(run.result, Mapping)
                else None
            )
        )
        with _LOCK:
            _STATES[run_id] = state
        _persist_loop_state(run_id, state, store)
        store.append_event(
            run_id,
            event_type="planning.actions.recovered",
            status="running",
            message="服务重启后已恢复未落盘的动作循环。",
            details={"tool": "destination_context"},
        )
        return get_next_actions(run_id, store=store)


#: 并发：`_LOCK` 保护，全部读写都在锁内。
#:
#: 「这个 run 的哪些动作**此刻正在飞**」。键是 run_id，值是 action_id 集合。
#:
#: 第五次实测的死锁需要两个条件同时成立：超时误判（已由 `ACTION_STALL_SECONDS`
#: 修掉），以及**重发不去重**。只修前者不够——真有一次动作慢过阈值时，旧的还在
#: 飞、新的又发出去，两份结果互相覆盖，而循环永远看不到「已经有人在做了」。
#:
#: 记在内存而不落盘是对的：进程一死，在飞的动作也随之消失，重启后本就该重发。
#: 落盘反而会留下一个永远清不掉的「假在飞」。
_IN_FLIGHT: dict[str, set[str]] = {}

#: 同一个动作连续超时多少次就熔断。
#:
#: 与 WORKER_LOST 同族：失败要说出来，不静默转圈。到达上限就落
#: `{DOMAIN}_ACTION_FAILED`，宿主拿到明确结论与下一步，而不是看着它转到天荒地老。
MAX_CONSECUTIVE_TIMEOUTS = 3

#: 并发：`_LOCK` 保护，全部读写都在锁内。
#: 每个 (run_id, action_id) 连续超时了几次。成功一次就清零。
_TIMEOUT_STRIKES: dict[tuple[str, str], int] = {}


#: 一个动作多久没进展算「卡住」。**这是看门狗阈值的唯一出处**——判定用它、
#: 报文也用它。
#:
#: 与 `max_wait_seconds`（本次调用还能花多久）是**两个不同的数**，此前被同一个
#: `min()` 合并，于是 MCP 传进来的 5 秒调用预算把看门狗一起缩成了 5 秒，而报文
#: 里写死的 30 纹丝不动——宿主看到「超过30秒没有新进展」发生在第 5 秒
#: （第五次实测，2026-08-04）。
#:
#: 预算用完只说明「这次没等到」，动作还在飞；只有真的超过本阈值才是卡住。
ACTION_STALL_SECONDS = 30.0


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
                    timeout=remaining,
                )
                for future in completed:
                    # 「已经有人在做」不是错误，是进度：另一条路径正在跑同一个
                    # 动作，本次不必也不能再发一遍。把它当异常抛出去，宿主看到的
                    # 就是硬错误（疲劳测试首跑 20 轮里 4 轮死在这儿）。
                    try:
                        future.result()
                    except ActionAlreadyInFlight:
                        continue
                if any(
                    str(batch[futures.index(future)].get("action_id"))
                    != "planner"
                    for future in completed
                ):
                    executed.discard(("planner", "initial"))
                if pending:
                    pending_ids = [
                        str(batch[futures.index(future)]["action_id"])
                        for future in pending
                    ]
                    # 停滞判定归**入口**所有（`execute_registered_action`
                    # 内的看门狗），这里只管本次调用的预算。两处都判会重复
                    # 记熔断次数、并对已经阻塞的 run 再 block 一次
                    # （实测：TravelAgentError("run is not running")）。
                    return _budget_exhausted(
                        run_id,
                        pending_ids,
                        max_wait_seconds,
                        store=store,
                    )
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
                timeout=remaining,
            )
            if pending:
                # 同上：停滞归入口判，这里只判预算。
                return _budget_exhausted(
                    run_id,
                    [action_id],
                    max_wait_seconds,
                    store=store,
                )
            try:
                next(iter(completed)).result()
            except ActionAlreadyInFlight:
                # 同上：在飞不是失败，下一轮轮询会看到它的结果。
                return _budget_exhausted(
                    run_id,
                    [action_id],
                    max_wait_seconds,
                    store=store,
                )
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
    with _run_lock(run_id):
        return _get_next_actions_unlocked(run_id, store=store)


def pending_action_schemas(actions: object) -> list[dict[str, object]]:
    """Project executable/manual actions into the one published evidence schema.

    Both the blocked action snapshot and ``read_trip(view="missing")`` call this
    function.  Keeping the record wrapper (action_id/value/sources), field scope,
    and examples in one projection prevents a read-model copy from drifting away
    from the parser contract again (D2/D5).
    """

    if not isinstance(actions, list):
        return []
    seen: set[str] = set()
    schemas: list[dict[str, object]] = []
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        action_id = str(action.get("action_id") or "")
        if not action_id or action_id in seen:
            continue
        seen.add(action_id)
        submit_action_id = str(
            action.get("submit_action_id", action.get("action_id")) or ""
        )
        gate_schema = _evidence_gate_schema(submit_action_id)
        required_fields = list(action.get("required_fields") or [])
        optional_fields = list(action.get("optional_fields") or [])
        example = action.get("example")
        if gate_schema is not None:
            # registered_tool / codex_web_research 也会成为宿主可回喂的证据门，
            # 不能因为动作构造器没重复写说明书就投影出空 schema。域级提交门
            # 是唯一兜底表；手工动作可在其上收窄字段，但不得把说明书清空。
            if not required_fields:
                required_fields = list(gate_schema["required_fields"])
            if not optional_fields:
                optional_fields = list(gate_schema["optional_fields"])
            if not example:
                example = gate_schema["example"]
        schemas.append(
            {
                "action_id": action_id,
                "submit_action_id": submit_action_id,
                "title": action.get("title"),
                "required_fields": required_fields,
                "optional_fields": optional_fields,
                **(
                    {
                        # required/optional 都是 example.value 内部的业务路径；
                        # 外层 action_id/value/sources 由完整 example 直接示形。
                        "field_scope": "example.value",
                        "example": deepcopy(example),
                    }
                    if example
                    else {}
                ),
            }
        )
    return schemas


def _pending_evidence_schemas(
    run_id: str,
    run: object,
    store: InMemoryAgentStore,
) -> list[dict[str, object]]:
    """阻塞态下「还缺哪些证据、各自什么形状」。

    复用**同一套**动作构造函数（`_registered_action` / `_manual_railway_action`
    / `_plan_followup_actions`），不另写一份清单——写第二份就等着它和门不一致
    （D2/D5）。这里只是把它们在阻塞态也拿出来，而不是重新定义一遍。
    """

    try:
        state = _load_loop_state(run_id, store)
    except TravelAgentError:
        return []
    if state is None:
        return []
    intent = getattr(run, "intent", None)
    if intent is None:
        return []
    actions: list[Mapping[str, object]] = []
    for action_id in _DOMAINS:
        if state.action_status.get(action_id) in {"waiting", "blocked", "failed"}:
            try:
                actions.append(_registered_action(action_id, intent, state))
            except Exception:  # noqa: BLE001
                continue
    if state.action_status.get("railway") in {"blocked", "failed"}:
        actions.append(_manual_railway_action(intent))
    try:
        actions.extend(_plan_followup_actions(intent, state))
    except Exception:  # noqa: BLE001
        pass
    return pending_action_schemas(actions)


def _get_next_actions_unlocked(
    run_id: str,
    *,
    store: InMemoryAgentStore,
) -> dict[str, object]:

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
            # 阻塞态**照样要说清还缺什么**。
            #
            # `actions` 保持为空是对的：阻塞时没有可以立刻派发的动作，那是行为
            # 契约，调用方靠它判断「能不能推」。但「现在推不动」与「还缺哪些
            # 证据、各自什么形状」是两个问题，此前只答了前一个——于是 run 报
            # USER_INPUT_REQUIRED，却一个字段名都给不出来（疲劳测试首跑撞出，
            # 也是第六次实测那条抱怨没修干净的那一半）。
            #
            # 分成两个键而不是把它们塞进 `actions`：两者语义不同，合一个键就会
            # 让「有 actions」不再等价于「能推」。
            pending_actions=_pending_evidence_schemas(run_id, run, store),
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

    # 在飞去重：同一个动作已经有人在跑，就不再发第二个。**这一步必须在任何
    # 状态变更之前**——第五次实测的死锁正是「旧的还在飞、新的又发出去」。
    if not _claim_in_flight(run_id, action_id):
        raise ActionAlreadyInFlight(
            f"{action_id} 已在执行中，本次不重复派发"
        )

    def _run_and_release() -> dict[str, object]:
        # **在飞登记只在真正跑完时才释放**，不随外层超时返回而释放：外层等不到
        # 不代表活干完了，提前放会让下一次派发和它撞车。
        try:
            return _execute_registered_action_claimed(
                run_id,
                action_id,
                store=store,
                evidence_broker=evidence_broker,
            )
        finally:
            _release_in_flight(run_id, action_id)

    # 看门狗与熔断下沉到这里——**动作执行的唯一入口**。
    #
    # 上一轮核对表的欠账：降级链原本只活在 `run_until_blocked` 里，于是
    # `execute_trip(action_id=X)` 与 `retry_action(X)` 这两条直呼路径既没有
    # 看门狗也没有熔断（第七次实测「重试两次无效」的结构性成因）。放在入口处，
    # 四条路径全部自动继承，不必各自记得包一层。
    executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix=f"action-{action_id}",
    )
    try:
        future = executor.submit(_run_and_release)
        completed, pending = wait((future,), timeout=ACTION_STALL_SECONDS)
        if pending:
            # 超过停滞阈值：记一次熔断计数并如实落状态。动作**不取消**——
            # 它还在飞，迟到的结果照样会被收下（第五轮的「迟到结果回收」）。
            _timeout_actions(run_id, [action_id], store=store)
            return get_next_actions(run_id, store=store)
        return next(iter(completed)).result()
    finally:
        executor.shutdown(wait=False)


def _execute_registered_action_claimed(
    run_id: str,
    action_id: str,
    *,
    store: InMemoryAgentStore,
    evidence_broker: EvidenceBroker,
) -> dict[str, object]:
    """真正执行。调用方必须已经通过 `_claim_in_flight` 占位。"""

    run_lock = _run_lock(run_id)
    with run_lock:
        run = store.get_run(run_id)
        if (
            run.status is RunStatus.COMPLETED
            and action_id in {"railway", "map", "planner"}
        ):
            run = store.resume(run_id)
        if run.status is not RunStatus.RUNNING:
            raise TravelAgentError("run is not executing actions")
        live_state = _state(run_id, store)
        if action_id not in _TOOL_REGISTRY:
            raise TravelAgentError("action is not a registered runtime tool")
        is_refresh = live_state.action_status[action_id] in {
            "completed",
            "failed",
        }
        if live_state.action_status[action_id] != "waiting" and not is_refresh:
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
        live_state.action_status[action_id] = "running"
        _persist_loop_state(run_id, live_state, store)
        store.append_event(
            run_id,
            event_type="tool.started",
            status="started",
            message=f"{_TOOL_REGISTRY[action_id]['title']}开始执行。",
            details={"tool": action_id},
        )
        # handler 可能做网络 I/O，绝不带锁。给它不可共享的快照，避免另一域
        # 同时提交结果时改动 handler 正在读取的 dict。
        state = deepcopy(live_state)
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
        with run_lock:
            live_state = _state(run_id, store)
            live_state.action_status[action_id] = "blocked"
            _persist_loop_state(run_id, live_state, store)
        raise
    except Exception as error:
        with run_lock:
            live_state = _state(run_id, store)
            live_state.action_status[action_id] = "blocked"
            _persist_loop_state(run_id, live_state, store)
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
        with run_lock:
            live_state = _state(run_id, store)
            result = deepcopy(dict(outcome))
            live_state.result = result
            live_state.action_status[action_id] = "completed"
            # 成功一次就清零——「连续」超时才该熔断，累计的不算。
            _clear_timeout_strikes(run_id, action_id)
            # §13.1 的写入顺序：run.json 先落权威，action-loop.json 后落。
            # 反过来会开出一个恢复不了的中断窗口——action-loop 说 planner 已完成，
            # run.json 里却还没有 result，重启后状态自相矛盾。
            store.record_result(run_id, result)
            _persist_loop_state(run_id, live_state, store)
            planner_evidence = _loop_evidence(live_state, run.intent)
            displayable = _result_is_displayable(result, planner_evidence)
            if displayable:
                store.persist_plan_version(run_id, result)
            store.append_event(
                run_id,
                event_type="tool.completed",
                status="completed",
                message=(
                    "计划版本已通过证据门并安装。"
                    if displayable
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
            if displayable:
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
    with _run_lock(run_id):
        return _submit_evidence_unlocked(run_id, evidence, store=store)


def _submit_evidence_unlocked(
    run_id: str,
    evidence: EvidenceItem | Mapping[str, object],
    *,
    store: InMemoryAgentStore,
) -> dict[str, object]:
    """收下一条证据。

    **BLOCKED 的 run 仍收自己在飞动作的迟到结果**（第五次实测）：看门狗判超时
    会把 run 打成 BLOCKED，而那次采集其实还在跑；26 秒后它带着一份完全合法的
    证据回来，此前会被这道门以「run is not accepting evidence」挡掉、直接丢弃。
    下一轮于是只能重查——这正是死循环的最后一环。

    「超时」的意思是**这次没等到**，不是**结果作废**。所以放行条件收得很窄：
    只有仍登记在 `_IN_FLIGHT` 里的那个动作（也就是我们自己派出去、还没回来的
    那一次）才准在 BLOCKED 态下交货。宿主的手工提交不受影响——它不在飞，
    仍然按原规则要求 run 处于 RUNNING。
    """

    raw = evidence.to_dict() if isinstance(evidence, EvidenceItem) else dict(evidence)
    action_id = raw.pop("action_id", None)
    if not isinstance(action_id, str) or action_id not in _ACTION_ORDER:
        raise TravelAgentError("evidence action_id is invalid")
    run = store.get_run(run_id)
    if run.status is not RunStatus.RUNNING and not (
        run.status is RunStatus.BLOCKED
        and action_id in in_flight_actions(run_id)
    ):
        raise TravelAgentError("run is not accepting evidence")
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
    } and action_id not in in_flight_actions(run_id):
        # 第二道门，与上面那道同因（第五次实测）：看门狗判超时会把动作状态
        # 从 waiting 翻成 blocked，于是那次采集真正回来时被这里挡掉、结果丢弃。
        # 仍在飞的动作是我们自己派出去、还没回来的那一次，它的结果必须收下——
        # 「超时」是这次没等到，不是结果作废。
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
        if action_id == "map":
            # I12 第三个域。此前 map 没有门，形状不合的提交会静默通过、
            # 死在编译器里（宿主第三次实测的班车证据就是这么丢的）。
            _validate_map_value(usable_fact_values(merged.facts))
        state.evidence[item.domain] = merged
        state.last_sourced_evidence[item.domain] = merged
        state.action_status[action_id] = "completed"
        if action_id != "planner":
            state.action_status["planner"] = "waiting"
            state.result = None
        _persist_loop_state(run_id, state, store)
        submitted_values = usable_fact_values(item.facts)
        if submitted_values:
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
        else:
            # accepted/stored 是记录级事实，sourced 是字段级结论。旧实现只看
            # item.status，于是一个 0-fact 记录也会对外宣布 sourced（D22）。
            store.append_event(
                run_id,
                event_type="tool.completed",
                status="completed",
                message=f"{_action_title(action_id)}未解析出字段级事实。",
                details={
                    "tool": action_id,
                    "support": "unknown",
                    "parsed_facts_count": 0,
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
    enriched = deepcopy(dict(value))
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
        "example": deepcopy(RAILWAY_MANUAL_EXAMPLE),
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
                # 「乘什么、在哪换、走多远」——采集器一直在采（公交路线规划2.0
                # 的 segments[].bus.buslines[]），此前在**这一步**被丢掉：
                # 归一化只留了时长/距离/票价，于是行程里只剩一个时长估算。
                # 这不是数据源缺口，是归一化把已有的东西扔了。
                #
                # services 保持采集顺序。换乘点由相邻两段推出：前一段的
                # alight_at 就是后一段 board_at 的换乘站。不在这里另算一个
                # transfer 列表——那会变成第二份可以和 services 不一致的数据
                # （D19）。
                "services": _normalized_services(selected.get("services")),
                # 「先走 840 米到某站，坐 9 站，再走 100 米」——顺序信息只有
                # legs 说得出，services 只是它的乘车子集。
                "legs": _normalized_legs(selected.get("legs")),
                "walking_distance_meters": _nonnegative_int(
                    selected.get("walking_distance_meters")
                ),
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


#: 一段公交线路在事件 detail 里被展示的字段。运营时刻可能缺（高德不总是返回），
#: 缺就是 ``None``——不编，也不因此丢掉整条线路。
_SERVICE_FIELDS = (
    "service",
    "board_at",
    "alight_at",
    "operating_start",
    "operating_end",
)


def _normalized_services(value: object) -> list[dict[str, object]]:
    """把采集器的 ``services`` 归一化成可展示的线路段。

    只收**线路身份齐全**的段：线路名、上车站、下车站三者缺一，这一段就说不出
    「乘什么、在哪上、在哪下」，留着只会在界面上显示一个空行。运营时刻另算，
    缺了不影响这一段可用。
    """

    if not isinstance(value, list):
        return []
    services: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        identity = {
            key: item.get(key)
            for key in ("service", "board_at", "alight_at")
        }
        if any(
            not isinstance(text, str) or not text.strip()
            for text in identity.values()
        ):
            continue
        services.append({key: item.get(key) for key in _SERVICE_FIELDS})
    return services


def _normalized_legs(value: object) -> list[dict[str, object]]:
    """按原顺序保留「走一段 / 坐一段」。

    只收说得出话的段：步行段要有距离，乘车段要有线路身份。缺了的段留着只会在
    界面上显示一个空行。
    """

    if not isinstance(value, list):
        return []
    legs: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        mode = item.get("mode")
        if mode == "walk":
            distance = _nonnegative_int(item.get("distance_meters"))
            if distance is None:
                continue
            legs.append(
                {
                    "mode": "walk",
                    "distance_meters": distance,
                    "duration_seconds": _nonnegative_int(
                        item.get("duration_seconds")
                    ),
                }
            )
        elif mode == "ride":
            if not all(
                isinstance(item.get(key), str) and str(item.get(key)).strip()
                for key in ("service", "board_at", "alight_at")
            ):
                continue
            legs.append(
                {
                    "mode": "ride",
                    **{key: item.get(key) for key in _SERVICE_FIELDS},
                    "ride_duration_seconds": _nonnegative_int(
                        item.get("ride_duration_seconds")
                    ),
                    "stop_count": _nonnegative_int(item.get("stop_count")),
                }
            )
    return legs


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


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
                    # 声明与消费同一张表（D2）。此前这里只写 hotel_area.name，
                    # 宿主照着填必被 _validate_web_value 拦下。
                    "required_fields": [
                        *WEB_REQUIRED_FIELDS,
                        WEB_ACCOMMODATION_FIELD,
                    ],
                    "example": deepcopy(WEB_EXAMPLE),
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
                    f"local_transit[].{field}"
                    for field in MAP_SEGMENT_REQUIRED_FIELDS
                ],
                "optional_fields": [
                    f"local_transit[].{field}"
                    for field in MAP_SEGMENT_OPTIONAL_FIELDS
                ],
                "example": deepcopy(MAP_SEGMENT_EXAMPLE),
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


#: 一段当地交通被规划器消费所必需的键。与 `local_transit_manual` 声明的
#: `required_fields` 是**同一张表**（D2）——那边由这里派生，不另抄一份。
MAP_SEGMENT_REQUIRED_FIELDS = ("from", "to", "duration_seconds")

#: 可选的线路级信息。给了就进事件 detail（「乘什么、在哪上下、多少钱」），
#: 不给不影响这一段可用。宿主第三次实测提交的正是这一组，此前无处安放。
MAP_SEGMENT_OPTIONAL_FIELDS = (
    "services",
    "fare",
    "walking_distance_meters",
    "headway_minutes",
    "first_departure",
    "last_departure",
)

#: 报错与 missing 视图共用的「最近合法形状」。这是完整提交记录，不是
#: 序列化后的 value 片段；调用方可以把它原样传给 evidence 参数。
MAP_SEGMENT_EXAMPLE: dict[str, object] = {
    "action_id": "map",
    "value": {
        "local_transit": [
            {
                "from": "<起点>",
                "to": "<终点>",
                "duration_seconds": 1800,
                "services": [
                    {
                        "service": "<线路名>",
                        "board_at": "<上车站>",
                        "alight_at": "<下车站>",
                    }
                ],
                "fare": {"status": "sourced", "amount_cny": 15.0},
                "headway_minutes": 25,
                "first_departure": "06:30",
            }
        ]
    },
    "sources": [
        {
            "provider": "<出处>",
            "retrieved_at": "2026-08-05T13:30:00+08:00",
        }
    ],
}


def _example_text(example: Mapping[str, object]) -> str:
    return json.dumps(example, ensure_ascii=False, separators=(",", ":"))


def _validate_map_value(value: object) -> None:
    """当地交通证据的提交门：**校验通过 = 规划器消费必成功**（I12）。

    此前 map 域**根本没有门**。宿主第三次实测提交了一份「线路」形状的班车证据
    （line / board_at / alight_at / fare，没有 from/to/duration_seconds），
    提交被静默接受、事件流写下「取得有效证据」，然后编译器产出 0 个事件加一个
    `MAP_INPUT_UNAVAILABLE`——需求仍然缺，动作被重新派发，宿主眼中就是
    「反复被拒」，却始终拿不到一句说明缺什么。

    这正是 I12 当初为 railway 立下的形状，只是当时只落了 railway 一个域。

    与 railway 那道门一样，吃的是 `usable_fact_values(item.facts)`——**与规划器
    同一个视图**。在提交时的原始 mapping 上校验会放行投影后缺键的证据。
    """

    if not isinstance(value, Mapping):
        raise TravelAgentError("map evidence value must be an object")
    routes = value.get("local_transit")
    if routes is None:
        # 只报了目的地识别、没带当地交通的 map 证据是合法的——采集器就这么产。
        return
    if not isinstance(routes, list) or not routes:
        raise TravelAgentError(
            "local_transit 必须是非空数组；"
            f"最近的合法形状：{_example_text(MAP_SEGMENT_EXAMPLE)}"
        )
    problems: list[str] = []
    for index, route in enumerate(routes):
        if not isinstance(route, Mapping):
            problems.append(f"local_transit[{index}] 不是对象")
            continue
        absent = [
            field
            for field in MAP_SEGMENT_REQUIRED_FIELDS
            if route.get(field) in (None, "")
        ]
        if absent:
            problems.append(
                f"local_transit[{index}] 缺 " + "、".join(absent)
            )
            continue
        duration = route.get("duration_seconds")
        if (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration <= 0
        ):
            problems.append(
                f"local_transit[{index}].duration_seconds 必须是正整数秒，"
                f"收到 {duration!r}"
            )
    if problems:
        raise TravelAgentError(
            "；".join(problems)
            + f"。每一段都要能回答「从哪到哪、要多久」——"
            f"线路名、上下车站、票价是可选的补充。"
            f"最近的合法形状：{_example_text(MAP_SEGMENT_EXAMPLE)}"
        )


#: web 证据被消费所必需的键。**与派发动作声明的 required_fields 是同一张表**
#: （D2）——那边由这里派生。此前两边各写各的：`accommodation_base_manual` 声明
#: 只要 `hotel_area.name`，而这道门要 `destination_official_name` +
#: `verified_facts`，宿主照着声明填必被拒，且报错不说全套要什么。
WEB_REQUIRED_FIELDS = ("destination_official_name", "verified_facts")

#: 景点列表进入规划器的最小形状。只有 ``name`` 没有稳定 id 时，编译器会
#: 如实跳过该项；这正是第九次宿主实测 accepted=true 但 attraction_count=0
#: 的消费层差异。
WEB_ATTRACTION_REQUIRED_FIELDS = (
    "attractions[].attraction_id",
    "attractions[].name",
)

#: 补住宿片区时**额外**要的。它是 `accommodation_base` 这个需求的专属要件，
#: 不是每份 web 证据都得有。
WEB_ACCOMMODATION_FIELD = "hotel_area.name"

WEB_EXAMPLE: dict[str, object] = {
    "action_id": "web",
    "value": {
        "destination_official_name": "<行政区全称>",
        "verified_facts": [
            {
                "claim": "<一句可核对的事实>",
                "source_url": "<出处链接>",
            }
        ],
        "attractions": [
            {
                "attraction_id": "<稳定景点ID>",
                "name": "<景点名称>",
                "route_query_name": "<地图检索名称>",
                "visit_minutes": 120,
            }
        ],
        "hotel_area": {"name": "<住宿片区名>"},
    },
    "sources": [
        {
            "provider": "<出处>",
            "retrieved_at": "2026-08-05T13:30:00+08:00",
        }
    ],
}


def _evidence_gate_schema(action_id: str) -> dict[str, object] | None:
    """Return the sole published, directly replayable schema for a gate.

    ``_DOMAINS`` is the submission-gate inventory.  This function deliberately
    has one branch for every member, so a new gate cannot silently inherit an
    empty pending action: the scanning meta-test feeds every projected example
    back through the real parser.
    """

    if action_id == "railway":
        return {
            "required_fields": RAILWAY_MANUAL_REQUIRED_FIELDS,
            "optional_fields": RAILWAY_MANUAL_OPTIONAL_FIELDS,
            "example": RAILWAY_MANUAL_EXAMPLE,
        }
    if action_id == "web":
        return {
            # web 的统一研究动作同时承担目的地、景点与住宿三个展示 gate；
            # example 必须让三者都能增长，而不只是通过通用 web 校验。
            "required_fields": (
                *WEB_REQUIRED_FIELDS,
                *WEB_ATTRACTION_REQUIRED_FIELDS,
                WEB_ACCOMMODATION_FIELD,
            ),
            "optional_fields": (),
            "example": WEB_EXAMPLE,
        }
    if action_id == "map":
        return {
            "required_fields": tuple(
                f"local_transit[].{field}"
                for field in MAP_SEGMENT_REQUIRED_FIELDS
            ),
            "optional_fields": tuple(
                f"local_transit[].{field}"
                for field in MAP_SEGMENT_OPTIONAL_FIELDS
            ),
            "example": MAP_SEGMENT_EXAMPLE,
        }
    return None


def _validate_web_value(value: object) -> None:
    """web 证据的提交门：**校验通过 = 消费必成功**（I12）。

    一次点名**全部**缺失项并给出示例。此前一次只报一个键、且不给形状，宿主
    补一个再试一次、再被另一个键拦下——第四次实测「调试数据结构字段匹配问题」
    两轮试错就是这么来的。
    """

    if not isinstance(value, Mapping):
        raise TravelAgentError(
            "web evidence value must be an object。形状："
            f"{_example_text(WEB_EXAMPLE)}"
        )
    absent: list[str] = []
    official_name = value.get("destination_official_name")
    if not isinstance(official_name, str) or not official_name.strip():
        absent.append("destination_official_name（目的地行政区全称）")
    facts = value.get("verified_facts")
    if (
        not isinstance(facts, list)
        or not facts
        or any(not isinstance(item, Mapping) for item in facts)
    ):
        absent.append("verified_facts（非空数组，每项一条可核对的事实）")
    if absent:
        raise TravelAgentError(
            "web 证据缺：" + "、".join(absent)
            + f"。景点、住宿片区这些都放在 verified_facts 里或与之并列，"
            "但上面两项是每份 web 证据都要有的。形状："
            f"{_example_text(WEB_EXAMPLE)}"
        )


def _block_run(
    run_id: str,
    domain: str,
    *,
    store: InMemoryAgentStore,
    stalled: bool = False,
) -> None:
    with _run_lock(run_id):
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


class ActionAlreadyInFlight(TravelAgentError):
    """这个动作已经在飞了，本次不重复派发。

    单独一个类型而不是复用 `TravelAgentError`：调用方要能分辨「这次没派出去是
    因为已经有人在做」（正常，等着即可）与「派发失败了」（异常）。
    """


def _claim_in_flight(run_id: str, action_id: str) -> bool:
    """把动作登记为在飞。已经在飞就返回 False，调用方不该重复派发。"""

    with _LOCK:
        flying = _IN_FLIGHT.setdefault(run_id, set())
        if action_id in flying:
            return False
        flying.add(action_id)
        return True


def _release_in_flight(run_id: str, action_id: str) -> None:
    with _LOCK:
        flying = _IN_FLIGHT.get(run_id)
        if flying is None:
            return
        flying.discard(action_id)
        if not flying:
            _IN_FLIGHT.pop(run_id, None)


def in_flight_actions(run_id: str) -> frozenset[str]:
    """这个 run 此刻有哪些动作在飞。供调用方避开重复派发。"""

    with _LOCK:
        return frozenset(_IN_FLIGHT.get(run_id, ()))


def _record_timeout_strike(run_id: str, action_id: str) -> int:
    with _LOCK:
        key = (run_id, action_id)
        _TIMEOUT_STRIKES[key] = _TIMEOUT_STRIKES.get(key, 0) + 1
        return _TIMEOUT_STRIKES[key]


def _clear_timeout_strikes(run_id: str, action_id: str) -> None:
    with _LOCK:
        _TIMEOUT_STRIKES.pop((run_id, action_id), None)


def _budget_exhausted(
    run_id: str,
    pending_ids: Sequence[str],
    budget_seconds: float,
    *,
    store: InMemoryAgentStore,
) -> dict[str, object]:
    """预算用完：如实说「还在飞」，不动 run 状态、不取消在飞的动作。

    与 `_timeout_actions` 的区别就是本轮事故的全部要害——那个把动作打成
    ``blocked`` 并阻塞 run，这个什么都不改，只告诉调用方过会儿再来。
    """

    snapshot = get_next_actions(run_id, store=store)
    return {
        **snapshot,
        "status": "NEED_USER_INPUT",
        "reason": "time_budget_exhausted",
        "in_flight": list(pending_ids),
        "elapsed_seconds": float(budget_seconds),
    }


def _timeout_actions(
    run_id: str,
    action_ids: list[str],
    *,
    store: InMemoryAgentStore,
) -> None:
    """Close actions that made no observable progress for ACTION_STALL_SECONDS."""

    with _run_lock(run_id):
        state = _state(run_id, store)
        tripped: list[str] = []
        for action_id in action_ids:
            strikes = _record_timeout_strike(run_id, action_id)
            if action_id in state.action_status:
                # 熔断之后标 failed 而不是 blocked：failed 才会在动作快照里带出
                # requery 与手工提交两条出路，blocked 只是「再等等」。
                state.action_status[action_id] = (
                    "failed" if strikes >= MAX_CONSECUTIVE_TIMEOUTS else "blocked"
                )
            if strikes >= MAX_CONSECUTIVE_TIMEOUTS:
                tripped.append(action_id)
            store.append_event(
                run_id,
                event_type="tool.timeout",
                status="failed",
                message=(
                    f"{_action_title(action_id)}超过 "
                    f"{ACTION_STALL_SECONDS:g} 秒没有新进展。"
                ),
                details={
                    "tool": action_id,
                    # 与判定用的是同一个常量。此前这里是写死的 30，而真正生效
                    # 的是 min(30, remaining)——数字都在，就是对不上。
                    "timeout_seconds": ACTION_STALL_SECONDS,
                    "consecutive_timeouts": strikes,
                    "max_consecutive_timeouts": MAX_CONSECUTIVE_TIMEOUTS,
                },
            )
        _persist_loop_state(run_id, state, store)
        # 熔断：连续超时到上限就说出「这个域失败了」，不再无限转圈。与
        # WORKER_LOST 同族——失败要有明确结论和下一步，不是静默重试到天荒地老。
        _block_run(
            run_id,
            action_ids[0],
            store=store,
            stalled=not tripped,
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
    with _run_lock(run_id):
        with _LOCK:
            state = _STATES.get(run_id)
        if state is None:
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
            with _LOCK:
                _STATES[run_id] = state
            _persist_loop_state(run_id, state, store)
        return tuple(written)


def _persist_loop_state(
    run_id: str,
    state: _LoopState,
    store: InMemoryAgentStore,
) -> None:
    with _run_lock(run_id):
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


def action_loop_started(
    run_id: str,
    *,
    store: InMemoryAgentStore | None = None,
) -> bool:
    """这个 run 有没有动作循环可推。

    候选比较阶段的 run 是 RUNNING 但**还没有动作循环**——循环要等选定候选之后
    才建。调用方需要在「推循环」之前问这一句，而不是靠捕获
    ``action loop was not started`` 来猜（D10：捕获式判断会把「文件真的丢了」
    一并吞掉）。
    """

    store = store if store is not None else default_agent_store()
    with _run_lock(run_id):
        with _LOCK:
            if _STATES.get(run_id) is not None:
                return True
        return _load_loop_state(run_id, store) is not None


def _load_loop_state(
    run_id: str,
    store: InMemoryAgentStore,
) -> _LoopState | None:
    run_directory = store.run_directory(run_id)
    if run_directory is None:
        return None
    action_path = run_directory / "action-loop.json"
    evidence_path = run_directory / "evidence" / "current.json"
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
    "action_loop_started",
    "ACTION_STALL_SECONDS",
    "get_next_actions",
    "pending_action_schemas",
    "restart_action_loop_for_intent",
    "resume_missing_action_loop",
    "run_until_blocked",
    "start_action_loop",
    "record_refetched_evidence",
    "submit_evidence",
]
