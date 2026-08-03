"""Host-neutral application service for trip-decider run orchestration.

The service owns application use cases and their lifecycle transitions.  It
does not know about HTTP paths, status codes, SSE framing, HTML, or browser
state.  REST and future transports must call this service instead of wiring
the run store, evidence broker, and planners independently.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path
import re
import threading
from typing import Any

from trip_decider.agent_actions import (
    execute_registered_action,
    get_next_actions,
    restart_action_loop_for_intent,
    run_until_blocked,
    start_action_loop,
    submit_evidence,
)
from trip_decider.destination_runtime import (
    collect_map_evidence,
    collect_railway_evidence,
    revise_destination_result,
)
from trip_decider.dynamic_discovery import collect_live_destination_profile
from trip_decider.evidence_core import recovery_safe
from trip_decider.evidence_broker import (
    default_evidence_broker,
    EvidenceBroker,
)
from trip_decider.guided_discovery import build_guided_comparison
from trip_decider.evidence_projection import business_view
from trip_decider.travel_agent import (
    default_agent_store,
    AgentRun,
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
    NON_BUSINESS_ERRORS,
    Revision,
    RunStatus,
    TaskMode,
    TravelAgentError,
    TravelIntent,
    confirm_intent,
    continue_run_with_intent,
    create_run,
    atomic_runtime_json as _atomic_json,
    revise_run,
)

_LOGGER = logging.getLogger(__name__)



class TripApplicationError(ValueError):
    """A caller supplied an invalid application command."""


@dataclass(frozen=True)
class ApplicationOutcome:
    """Transport-neutral result of a command."""

    run_id: str
    accepted: bool = False
    action_loop: Mapping[str, object] | None = None
    audit_execution: Mapping[str, object] | None = None


EvidenceCollector = Callable[[TravelIntent], EvidenceItem]
ComparisonBuilder = Callable[..., dict[str, object]]
RevisionExecutor = Callable[..., Mapping[str, object]]


class TripApplicationService:
    """Coordinate one authoritative run/evidence/plan runtime."""

    def __init__(
        self,
        *,
        store: InMemoryAgentStore | None = None,
        evidence_broker: EvidenceBroker | None = None,
        railway_collector: EvidenceCollector = collect_railway_evidence,
        map_collector: EvidenceCollector = collect_map_evidence,
        web_collector: EvidenceCollector = collect_live_destination_profile,
        comparison_builder: ComparisonBuilder = build_guided_comparison,
        revision_executor: RevisionExecutor = revise_destination_result,
    ) -> None:
        store = store if store is not None else default_agent_store()
        self.store = store
        self.evidence_broker = (
            evidence_broker
            if evidence_broker is not None
            else default_evidence_broker()
        )
        self.railway_collector = railway_collector
        self.map_collector = map_collector
        self.web_collector = web_collector
        self.comparison_builder = comparison_builder
        self.revision_executor = revision_executor
        self._cancellations: dict[str, threading.Event] = {}
        self._cancellations_lock = threading.RLock()

    def create_trip(
        self,
        intent: TravelIntent | Mapping[str, object],
    ) -> AgentRun:
        return create_run(intent, store=self.store)

    def confirm_trip(
        self,
        run_id: str,
        intent: TravelIntent | Mapping[str, object] | None = None,
    ) -> AgentRun:
        return confirm_intent(run_id, intent, store=self.store)

    def next_actions(self, run_id: str) -> dict[str, object]:
        return get_next_actions(run_id, store=self.store)

    def execute_trip(
        self,
        run_id: str,
        *,
        action_id: str | None = None,
    ) -> ApplicationOutcome:
        """Execute or resume the mode-specific application workflow."""

        run = self.store.get_run(run_id)
        if run.status is RunStatus.RUNNING:
            action_state = (
                execute_registered_action(
                    run_id,
                    action_id,
                    store=self.store,
                    evidence_broker=self.evidence_broker,
                )
                if action_id is not None
                else run_until_blocked(
                    run_id,
                    store=self.store,
                    evidence_broker=self.evidence_broker,
                )
            )
            return ApplicationOutcome(
                run_id,
                action_loop=action_state,
            )
        if (
            run.status in {RunStatus.COMPLETED, RunStatus.BLOCKED}
            and run.intent.task_mode is TaskMode.DIRECT_PLAN
            and isinstance(run.result, Mapping)
        ):
            action_state = restart_action_loop_for_intent(
                run_id,
                run.intent,
                store=self.store,
            )
            self._spawn_action_loop(run_id, purpose="continue")
            return ApplicationOutcome(
                run_id,
                accepted=True,
                action_loop=action_state,
            )
        if run.status is not RunStatus.CONFIRMED:
            raise TripApplicationError(
                "run must be confirmed before execution"
            )
        if run.intent.blocking_missing_fields:
            raise TripApplicationError("旅行条件不完整，不能执行。")
        if run.intent.task_mode is TaskMode.PLAN_AUDIT:
            raise TripApplicationError(
                "PLAN_AUDIT must use the audit command with plan or content"
            )
        handlers = {
            TaskMode.OPEN_DISCOVERY: self.execute_open_discovery,
            TaskMode.GUIDED_DISCOVERY: self.execute_guided_discovery,
            TaskMode.DIRECT_PLAN: self.execute_direct_plan,
        }
        return handlers[run.intent.task_mode](run_id)

    def select_candidate(
        self,
        run_id: str,
        destination_id: str,
    ) -> ApplicationOutcome:
        destination_id = _required_text(
            destination_id,
            "destination_id",
        )
        previous = self.store.get_run(run_id)
        result = previous.result
        options = (
            result.get("options")
            if isinstance(result, Mapping)
            and result.get("stage")
            in {"open_discovery", "guided_discovery"}
            else None
        )
        if (
            previous.status is not RunStatus.COMPLETED
            or not isinstance(options, list)
        ):
            raise TripApplicationError(
                "candidate comparison must complete before selection"
            )
        selected = next(
            (
                option
                for option in options
                if isinstance(option, Mapping)
                and option.get("destination_id") == destination_id
            ),
            None,
        )
        if not isinstance(selected, Mapping):
            raise TripApplicationError(
                "destination_id is not in this comparison"
            )
        destination = selected.get("destination_anchor")
        if not isinstance(destination, str) or not destination:
            raise TripApplicationError(
                "selected option omitted destination_anchor"
            )
        intent_value = previous.intent.to_dict()
        intent_value.update(
            {
                "task_mode": TaskMode.DIRECT_PLAN.value,
                "destination_anchor": destination,
                "destination_expression": f"确定{destination}",
                "classification_basis": "guided_option_selected",
            }
        )
        continue_run_with_intent(
            run_id,
            intent_value,
            store=self.store,
        )
        action_state = start_action_loop(
            run_id,
            initial_evidence=self.guided_evidence_for_selection(
                run_id,
                destination_id,
            ),
            store=self.store,
        )
        return ApplicationOutcome(
            run_id,
            accepted=True,
            action_loop=action_state,
        )

    def retry_action(
        self,
        run_id: str,
        action_id: str,
    ) -> ApplicationOutcome:
        if action_id not in {"railway", "map", "web", "planner"}:
            raise TripApplicationError("action is not retryable")
        previous = self.store.get_run(run_id)
        if previous.intent.task_mode is not TaskMode.DIRECT_PLAN:
            raise TripApplicationError(
                "only DIRECT_PLAN tool actions can be retried"
            )
        if previous.status in {
            RunStatus.COMPLETED,
            RunStatus.BLOCKED,
            RunStatus.FAILED,
        }:
            restart_action_loop_for_intent(
                run_id,
                previous.intent,
                store=self.store,
            )
        action_state = execute_registered_action(
            run_id,
            action_id,
            store=self.store,
            evidence_broker=self.evidence_broker,
        )
        return ApplicationOutcome(run_id, action_loop=action_state)

    def submit_run_evidence(
        self,
        run_id: str,
        evidence: EvidenceItem | Mapping[str, object],
    ) -> ApplicationOutcome:
        previous = self.store.get_run(run_id)
        if (
            previous.status is RunStatus.BLOCKED
            and previous.intent.task_mode is TaskMode.DIRECT_PLAN
        ):
            restart_action_loop_for_intent(
                run_id,
                previous.intent,
                store=self.store,
            )
        action_state = submit_evidence(
            run_id,
            evidence,
            store=self.store,
        )
        return ApplicationOutcome(run_id, action_loop=action_state)

    def select_hotel(
        self,
        run_id: str,
        hotel_id: str,
    ) -> ApplicationOutcome:
        hotel_id = _required_text(hotel_id, "hotel_id")
        previous = self.store.get_run(run_id)
        evidence = self.current_run_evidence(run_id)
        web = evidence.get("web")
        # 不是透传：下面要读 hotel_candidates 这个业务字段。v2 的落盘
        # value 是 facts 数组，直读会静默拿到 None，然后报"没有可选住宿"。
        value = business_view(web) if isinstance(web, Mapping) else None
        if not value:
            raise TripApplicationError("当前没有可选住宿候选。")
        hotels = value.get("hotel_candidates")
        selected = (
            next(
                (
                    item
                    for item in hotels
                    if isinstance(item, Mapping)
                    and item.get("hotel_id") == hotel_id
                ),
                None,
            )
            if isinstance(hotels, list)
            else None
        )
        if not isinstance(selected, Mapping):
            raise TripApplicationError("住宿候选不属于当前run。")
        location = selected.get("location")
        value["hotel_area"] = {
            "name": selected.get("name"),
            "route_query_name": selected.get("name"),
            "kind": "selected_hotel",
            "temporary_base": False,
            "specific_hotel_selected": True,
            "location": deepcopy(location),
            "longitude": (
                location.get("longitude")
                if isinstance(location, Mapping)
                else None
            ),
            "latitude": (
                location.get("latitude")
                if isinstance(location, Mapping)
                else None
            ),
            "coordinate_system": "GCJ-02",
            "price": deepcopy(selected.get("price")),
            "source": selected.get("source"),
        }
        attractions = value.get("attractions")
        value["route_sequence"] = [
            str(selected.get("name")),
            *[
                str(item.get("route_query_name") or item.get("name"))
                for item in (
                    attractions if isinstance(attractions, list) else []
                )[:3]
                if isinstance(item, Mapping)
                and isinstance(
                    item.get("route_query_name") or item.get("name"),
                    str,
                )
            ],
        ]
        restart_action_loop_for_intent(
            run_id,
            previous.intent,
            store=self.store,
        )
        action_state = submit_evidence(
            run_id,
            {
                "action_id": "web",
                "evidence_id": str(web.get("evidence_id")),
                "domain": "web",
                "status": "sourced",
                "value": value,
                "sources": deepcopy(web.get("sources", [])),
            },
            store=self.store,
        )
        self._spawn_action_loop(run_id, purpose="hotel")
        return ApplicationOutcome(
            run_id,
            accepted=True,
            action_loop=action_state,
        )

    def revise_trip(
        self,
        run_id: str,
        *,
        revision: Revision | Mapping[str, object] | None = None,
        intent: TravelIntent | Mapping[str, object] | None = None,
    ) -> ApplicationOutcome:
        previous = self.store.get_run(run_id)
        if intent is None:
            if revision is None:
                raise TripApplicationError("revision is required")
            contract = (
                revision
                if isinstance(revision, Revision)
                else Revision.from_mapping(revision)
            )
            revised = revise_run(
                run_id,
                contract,
                executor=self.revision_executor,
                store=self.store,
            )
            return ApplicationOutcome(revised.run_id)
        corrected = (
            intent
            if isinstance(intent, TravelIntent)
            else TravelIntent.from_mapping(intent)
        )
        changed_fields = {
            field_name
            for field_name, value in corrected.to_dict().items()
            if value != previous.intent.to_dict().get(field_name)
        }
        if not changed_fields or changed_fields <= {"pace"}:
            contract = Revision(
                pace=(
                    corrected.pace
                    if corrected.pace != previous.intent.pace
                    else None
                ),
                user_message=(
                    "用户再次确认旅行条件，条件未改变。"
                    if not changed_fields
                    else "用户修改旅行节奏。"
                ),
            )
            revised = revise_run(
                run_id,
                contract,
                executor=self.revision_executor,
                intent=corrected,
                store=self.store,
            )
            return ApplicationOutcome(revised.run_id)
        action_state = restart_action_loop_for_intent(
            run_id,
            corrected,
            store=self.store,
        )
        self._spawn_action_loop(run_id, purpose="revision")
        return ApplicationOutcome(
            run_id,
            accepted=True,
            action_loop=action_state,
        )

    def audit_trip(
        self,
        run_id: str,
        *,
        plan: Mapping[str, object] | None = None,
        content: str | None = None,
    ) -> ApplicationOutcome:
        run = self.store.get_run(run_id)
        if run.intent.task_mode is not TaskMode.PLAN_AUDIT:
            raise TripApplicationError(
                "audit command only accepts PLAN_AUDIT runs"
            )
        if run.status is not RunStatus.CONFIRMED:
            raise TripApplicationError("audit run must be confirmed")
        if plan is not None and content is None:
            audit = _audit_plan_document(plan)
        elif content is not None and plan is None:
            audit = _audit_guide_content(content)
        else:
            raise TripApplicationError(
                "audit requires exactly one of plan or content"
            )
        self.store.start(run_id)
        self.store.append_event(
            run_id,
            event_type="audit.completed",
            status="completed",
            message="已有计划审计完成。",
            details={"planner_invoked": False},
        )
        self.store.complete(
            run_id,
            {
                "stage": "plan_audit",
                "task_mode": TaskMode.PLAN_AUDIT.value,
                "audit": audit,
                "planner_invoked": False,
            },
        )
        return ApplicationOutcome(
            run_id,
            audit_execution={
                "status": "AUDIT_COMPLETED",
                "planner_invoked": False,
            },
        )

    def persist_guided_evidence(
        self,
        run_id: str,
        value: Mapping[str, object],
    ) -> None:
        run_directory = self.store.run_directory(run_id)
        if run_directory is None:
            raise TripApplicationError(
                "guided evidence persistence is unavailable"
            )
        path = run_directory / "evidence" / "guided-comparison.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_json(
            path,
            {"version": 1, "destinations": dict(value)},
        )

    def guided_evidence_for_selection(
        self,
        run_id: str,
        destination_id: str,
    ) -> dict[str, EvidenceItem]:
        path = self._guided_evidence_read_path(run_id)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise TripApplicationError(
                "guided comparison evidence is unavailable"
            ) from error
        destinations = (
            document.get("destinations")
            if isinstance(document, Mapping)
            else None
        )
        selected = (
            destinations.get(destination_id)
            if isinstance(destinations, Mapping)
            else None
        )
        if not isinstance(selected, Mapping):
            raise TripApplicationError(
                "selected destination evidence is unavailable"
            )
        evidence: dict[str, EvidenceItem] = {}
        for domain, raw_item in selected.items():
            if domain not in {"railway", "map", "web"}:
                continue
            if not isinstance(raw_item, Mapping):
                raise TripApplicationError(
                    "guided comparison evidence is invalid"
                )
            evidence[domain] = EvidenceItem.from_mapping(raw_item)
        return evidence

    def current_run_evidence(
        self,
        run_id: str,
    ) -> dict[str, Mapping[str, object]]:
        run_directory = self.store.run_directory(run_id)
        if run_directory is None:
            return {}
        path = run_directory / "evidence" / "current.json"
        legacy = run_directory / "evidence.json"
        if not path.is_file() and legacy.is_file():
            path = legacy
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        current = (
            document.get("current")
            if isinstance(document, Mapping)
            else None
        )
        if not isinstance(current, list):
            return {}
        return {
            str(item["domain"]): item
            for item in current
            if isinstance(item, Mapping)
            and isinstance(item.get("domain"), str)
        }

    def execute_open_discovery(
        self,
        run_id: str,
    ) -> ApplicationOutcome:
        return self._start_candidate_comparison(
            run_id,
            TaskMode.OPEN_DISCOVERY,
        )

    def execute_guided_discovery(
        self,
        run_id: str,
    ) -> ApplicationOutcome:
        return self._start_candidate_comparison(
            run_id,
            TaskMode.GUIDED_DISCOVERY,
        )

    def execute_direct_plan(
        self,
        run_id: str,
    ) -> ApplicationOutcome:
        run = self.store.get_run(run_id)
        if run.intent.task_mode is not TaskMode.DIRECT_PLAN:
            raise TripApplicationError(
                "DIRECT_PLAN handler received another task mode"
            )
        action_state = start_action_loop(run_id, store=self.store)
        self._spawn_action_loop(run_id, purpose="actions")
        return ApplicationOutcome(
            run_id,
            accepted=True,
            action_loop=action_state,
        )

    def _start_candidate_comparison(
        self,
        run_id: str,
        mode: TaskMode,
    ) -> ApplicationOutcome:
        run = self.store.get_run(run_id)
        if run.intent.task_mode is not mode:
            raise TripApplicationError(
                f"{mode.value} handler received another task mode"
            )
        self.store.start(run_id)
        with self._cancellations_lock:
            self._cancellations[run_id] = threading.Event()
        self._spawn(
            target=self._candidate_comparison_background,
            args=(run_id, mode),
            name=f"trip-decider-{mode.value.lower()}-{run_id}",
        )
        return ApplicationOutcome(
            run_id,
            accepted=True,
            action_loop={
                "run_id": run_id,
                "status": "CANDIDATE_COMPARISON_RUNNING",
                "task_mode": mode.value,
                "pipeline": [
                    "candidate_generation",
                    "coarse_feasibility",
                    "candidate_comparison",
                    "user_selection",
                ],
            },
        )

    def _candidate_comparison_background(
        self,
        run_id: str,
        expected_mode: TaskMode,
    ) -> None:
        event_prefix = (
            "open"
            if expected_mode is TaskMode.OPEN_DISCOVERY
            else "guided"
        )

        def progress(
            status: str,
            destination: str,
            details: Mapping[str, object] | None,
        ) -> None:
            event_type = {
                "comparison_started": f"{event_prefix}.comparison.started",
                "candidate_started": f"{event_prefix}.candidate.started",
                "domain_started": f"{event_prefix}.domain.started",
                "domain_completed": f"{event_prefix}.domain.completed",
                "domain_timeout": f"{event_prefix}.domain.timeout",
                "candidate_completed": f"{event_prefix}.candidate.completed",
            }.get(status, f"{event_prefix}.progress")
            message = {
                "comparison_started": "开始并行比较倾向区域内的方案。",
                "candidate_started": "候选方案进入并行核验。",
                "domain_started": "开始核验一项真实数据。",
                "domain_completed": "一项真实数据核验完成。",
                "domain_timeout": "一项真实数据超时，继续其他核验。",
                "candidate_completed": "一个候选方案已可展示。",
            }.get(status, "区域方案比较有新进展。")
            self.store.append_event(
                run_id,
                event_type=event_type,
                status=(
                    "completed"
                    if status
                    in {
                        "domain_completed",
                        "domain_timeout",
                        "candidate_completed",
                    }
                    else "started"
                ),
                message=message,
                details={
                    "tool": (
                        str(details.get("domain"))
                        if isinstance(details, Mapping)
                        and details.get("domain")
                        in {"railway", "map", "web"}
                        else "destination_context"
                    ),
                    "destination_label": destination,
                    # TODO(P4-c): 事件流在兼任候选卡视图的数据源
                    # （trip_query.candidates 在 run.result 非比较阶段时从
                    # 事件流重建），因此这里剥掉 token / next_action 会断掉
                    # 那条读取路径。要断这条通道，得先让 candidates() 按
                    # 引用重算——那是安装语义重建的同一件事。
                    **dict(recovery_safe(details or {})),
                },
            )

        try:
            run = self.store.get_run(run_id)
            if run.intent.task_mode is not expected_mode:
                raise TravelAgentError(
                    f"{expected_mode.value} comparison received another mode"
                )
            with self._cancellations_lock:
                cancellation = self._cancellations.get(run_id)
            result = self.comparison_builder(
                run.intent,
                railway_collector=self.railway_collector,
                map_collector=self.map_collector,
                web_collector=self.web_collector,
                run_id=run_id,
                evidence_broker=self.evidence_broker,
                initial_evidence=None,
                progress=progress,
                should_cancel=(
                    cancellation.is_set
                    if cancellation is not None
                    else None
                ),
            )
            reusable_evidence = result.pop("reusable_evidence", {})
            if not isinstance(reusable_evidence, Mapping):
                raise TravelAgentError(
                    "guided comparison omitted reusable evidence"
                )
            self.persist_guided_evidence(run_id, reusable_evidence)
            self.store.append_event(
                run_id,
                event_type=f"{event_prefix}.comparison.completed",
                status="completed",
                message="区域方案均已完成粗粒度可行性检查。",
                details={
                    "tool": "validator",
                    "option_count": result["option_count"],
                },
            )
            self.store.complete(run_id, result)
        except NON_BUSINESS_ERRORS:
            # 编程错误不穿业务外衣。这个 except 曾把一个 NameError 报成
            # 「真实证据不足」——同一个叙述覆盖了「采集器没拿到数据」和
            # 「这段代码有 bug」，两者在可观测层面无法区分，归因因此走了
            # 一整轮弯路。业务失败保留原叙述，编程错误原样抛出。
            raise
        except Exception as error:
            current = self.store.get_run(run_id)
            if current.status is RunStatus.RUNNING:
                self.store.block(
                    run_id,
                    {
                        "stage": (
                            "open_discovery"
                            if expected_mode is TaskMode.OPEN_DISCOVERY
                            else "guided_discovery"
                        ),
                        "task_mode": current.intent.task_mode.value,
                        "options": [],
                        "selection_required": True,
                        "blockers": [
                            {
                                "code": "GUIDED_COMPARISON_UNAVAILABLE",
                                "reason": type(error).__name__,
                            }
                        ],
                    },
                    "GUIDED_COMPARISON_UNAVAILABLE",
                )
        finally:
            with self._cancellations_lock:
                self._cancellations.pop(run_id, None)

    def _spawn_action_loop(self, run_id: str, *, purpose: str) -> None:
        self._spawn(
            target=self._run_action_loop_background,
            args=(run_id,),
            name=f"trip-decider-{purpose}-{run_id}",
        )

    def _run_action_loop_background(self, run_id: str) -> None:
        try:
            snapshot = run_until_blocked(
                run_id,
                store=self.store,
                evidence_broker=self.evidence_broker,
                max_wait_seconds=30.0,
            )
            if snapshot.get("status") != "NEED_USER_INPUT":
                return
            run = self.store.get_run(run_id)
            if run.status is not RunStatus.RUNNING:
                return
            actions = snapshot.get("actions")
            action_types = (
                [
                    str(action.get("action_type"))
                    for action in actions
                    if isinstance(action, Mapping)
                ]
                if isinstance(actions, list)
                else []
            )
            reason = (
                "WEB_EVIDENCE_REQUIRED"
                if any(value.startswith("codex") for value in action_types)
                else "USER_INPUT_REQUIRED"
            )
            snapshot_result = snapshot.get("result")
            retained = (
                deepcopy(dict(snapshot_result))
                if isinstance(snapshot_result, Mapping)
                else run.result
                if isinstance(run.result, Mapping)
                else {
                    "action_loop_status": "BLOCKED",
                    "blocked_domains": [],
                }
            )
            self.store.block(run_id, retained, reason)
        except Exception as error:
            # 这里在后台线程里，重抛只会让线程静默死掉——比包装还糟。
            # 所以走「如实记类型」那一支：编程错误必须在对外叙述里自报家门，
            # 不得混进业务失败的话术，也不得只留一个错误码就把栈丢掉。
            programming_error = isinstance(error, NON_BUSINESS_ERRORS)
            if programming_error:
                _LOGGER.exception(
                    "action loop background thread hit a programming error "
                    "(run_id=%s)",
                    run_id,
                )
            current = self.store.get_run(run_id)
            if current.status is RunStatus.RUNNING:
                self.store.block(
                    run_id,
                    (
                        current.result
                        if isinstance(current.result, Mapping)
                        else {
                            "action_loop_status": "BLOCKED",
                            "blocked_domains": [],
                        }
                    ),
                    (
                        f"INTERNAL_ERROR_{type(error).__name__.upper()}"
                        if programming_error
                        else f"ACTION_LOOP_{type(error).__name__.upper()}"
                    ),
                )

    def _guided_evidence_path(self, run_id: str) -> Path:
        run_directory = self.store.run_directory(run_id)
        if run_directory is None:
            raise TripApplicationError(
                "guided evidence persistence is unavailable"
            )
        return run_directory / "evidence" / "guided-comparison.json"

    def _guided_evidence_read_path(self, run_id: str) -> Path:
        path = self._guided_evidence_path(run_id)
        if path.is_file():
            return path
        legacy = path.parents[1] / "guided-evidence.json"
        return legacy if legacy.is_file() else path

    @staticmethod
    def _spawn(
        *,
        target: Callable[..., None],
        args: tuple[object, ...],
        name: str,
    ) -> None:
        thread = threading.Thread(
            target=target,
            args=args,
            name=name,
            daemon=True,
        )
        thread.start()


def _audit_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    try:
        if "T" in normalized:
            return datetime.fromisoformat(normalized)
        return datetime.strptime(normalized, "%H:%M")
    except ValueError:
        return None


def _audit_plan_document(value: Mapping[str, object]) -> dict[str, object]:
    conflicts: list[dict[str, object]] = []
    suggestions: list[dict[str, str]] = []
    days = value.get("days")
    event_count = 0
    if not isinstance(days, list) or not days:
        conflicts.append(
            {
                "code": "AUDIT_DAYS_MISSING",
                "path": "/days",
                "message": "已有Plan没有可审计的每日安排。",
            }
        )
    else:
        for day_index, day in enumerate(days):
            day_path = f"/days/{day_index}"
            if not isinstance(day, Mapping):
                conflicts.append(
                    {
                        "code": "AUDIT_DAY_INVALID",
                        "path": day_path,
                        "message": "每日安排必须是对象。",
                    }
                )
                continue
            events = day.get("events", day.get("activities"))
            if not isinstance(events, list):
                conflicts.append(
                    {
                        "code": "AUDIT_EVENTS_MISSING",
                        "path": f"{day_path}/events",
                        "message": "该日没有结构化事件列表。",
                    }
                )
                continue
            previous_end: datetime | None = None
            for event_index, event in enumerate(events):
                event_count += 1
                event_path = f"{day_path}/events/{event_index}"
                if not isinstance(event, Mapping):
                    conflicts.append(
                        {
                            "code": "AUDIT_EVENT_INVALID",
                            "path": event_path,
                            "message": "行程事件必须是对象。",
                        }
                    )
                    continue
                start = _audit_time(
                    event.get("start_at", event.get("start"))
                )
                end = _audit_time(event.get("end_at", event.get("end")))
                if start is not None and end is not None and end <= start:
                    conflicts.append(
                        {
                            "code": "AUDIT_TIME_ORDER_INVALID",
                            "path": event_path,
                            "message": "事件结束时间不晚于开始时间。",
                        }
                    )
                if (
                    previous_end is not None
                    and start is not None
                    and start < previous_end
                ):
                    conflicts.append(
                        {
                            "code": "AUDIT_EVENT_OVERLAP",
                            "path": event_path,
                            "message": "该事件与前一事件时间重叠。",
                        }
                    )
                if end is not None:
                    previous_end = end
                event_type = event.get("type")
                location = event.get("location", event.get("place"))
                if (
                    event_type in {"transit", "attraction", "hotel"}
                    and not location
                ):
                    conflicts.append(
                        {
                            "code": "AUDIT_LOCATION_MISSING",
                            "path": event_path,
                            "message": "该事件缺少明确地点。",
                        }
                    )
    suggestions.append(
        {
            "code": (
                "RESOLVE_AUDIT_CONFLICTS"
                if conflicts
                else "RETAIN_EXISTING_PLAN"
            ),
            "message": (
                "先补齐缺失字段并消除时间重叠，再修改原计划。"
                if conflicts
                else "当前结构检查未发现冲突；仍需核验事实来源。"
            ),
        }
    )
    return {
        "input_kind": "structured_plan",
        "parsed": {
            "day_count": len(days) if isinstance(days, list) else 0,
            "event_count": event_count,
        },
        "validation_status": (
            "CONFLICTS_FOUND" if conflicts else "STRUCTURALLY_VALID"
        ),
        "conflicts": conflicts,
        "modification_suggestions": suggestions,
    }


def _audit_guide_content(value: str) -> dict[str, object]:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        raise TripApplicationError("攻略内容不能为空")
    timed_lines = [
        index + 1
        for index, line in enumerate(lines)
        if re.search(r"(?:[01]?\d|2[0-3]):[0-5]\d", line)
    ]
    conflicts: list[dict[str, object]] = []
    if not timed_lines:
        conflicts.append(
            {
                "code": "AUDIT_TIMELINE_UNSTRUCTURED",
                "path": "/content",
                "message": "攻略未提供可验证的明确时间安排。",
            }
        )
    return {
        "input_kind": "guide_text",
        "parsed": {
            "nonempty_line_count": len(lines),
            "timed_line_count": len(timed_lines),
        },
        "validation_status": (
            "INSUFFICIENT_STRUCTURE" if conflicts else "PARSED_FOR_REVIEW"
        ),
        "conflicts": conflicts,
        "modification_suggestions": [
            {
                "code": "STRUCTURE_GUIDE_TIMELINE",
                "message": (
                    "请补充每日时间、地点和交通衔接后再核验可行性。"
                    if conflicts
                    else "请继续核验交通、开放时间和费用来源。"
                ),
            }
        ],
    }


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TripApplicationError(f"{field_name} must be text")
    return value.strip()




_DEFAULT_APPLICATION: TripApplicationService | None = None


def default_trip_application_service() -> TripApplicationService:
    """进程级默认应用服务，首次调用时才构造（invariants.md I11）。"""

    global _DEFAULT_APPLICATION
    if _DEFAULT_APPLICATION is None:
        _DEFAULT_APPLICATION = TripApplicationService()
    return _DEFAULT_APPLICATION


def reset_default_trip_application_service() -> None:
    """丢弃已构造的默认应用服务。仅供测试隔离使用。"""

    global _DEFAULT_APPLICATION
    _DEFAULT_APPLICATION = None


__all__ = [
    "ApplicationOutcome",
    "DEFAULT_TRIP_APPLICATION_SERVICE",
    "TripApplicationError",
    "TripApplicationService",
]
