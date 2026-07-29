"""Model-neutral contracts for trip-decider agent runs.

The core accepts structured :class:`TravelIntent` and :class:`Revision`
objects.  It does not load a model adapter, inspect model credentials, or
interpret natural language.  A caller such as Codex may construct the
contracts directly and then drive the run through the public lifecycle.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Condition, RLock
from typing import Any
from uuid import uuid4


_PROGRESS_STEPS = (
    ("understand", "正在理解需求"),
    ("intercity", "正在验证跨城交通"),
    ("local_route", "正在查询当地路线"),
    ("facts", "正在核验门票/开放时间"),
    ("plan", "正在生成可行方案"),
)


class TravelAgentError(RuntimeError):
    """Raised when an agent contract or lifecycle transition is invalid."""


class TaskMode(str, Enum):
    """Top-level routing selected before tool execution."""

    OPEN_DISCOVERY = "OPEN_DISCOVERY"
    ANCHORED_PLAN = "ANCHORED_PLAN"
    PLAN_AUDIT = "PLAN_AUDIT"


class RunStatus(str, Enum):
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EvidenceStatus(str, Enum):
    SOURCED = "sourced"
    MISSING = "missing"
    CONFLICTING = "conflicting"


@dataclass(frozen=True)
class TravelIntent:
    """Structured user intent accepted by the model-neutral core."""

    task_mode: TaskMode
    origin: str | None
    destination_anchor: str | None
    earliest_departure_at: str | None
    latest_return_at: str | None
    travelers: int | None
    total_budget_cny: float | None
    pace: str | None
    transport_preferences: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    needs_confirmation: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    interpretation: str = ""
    classification_basis: str = "caller_supplied"

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> TravelIntent:
        destination = _optional_text(
            value.get("destination_anchor"),
            "destination_anchor",
        )
        requested_mode = value.get("task_mode")
        try:
            parsed_mode = (
                TaskMode(str(requested_mode))
                if requested_mode is not None
                else TaskMode.OPEN_DISCOVERY
            )
        except ValueError:
            raise TravelAgentError("unsupported task_mode") from None
        if parsed_mode is not TaskMode.PLAN_AUDIT:
            parsed_mode = (
                TaskMode.ANCHORED_PLAN
                if destination
                else TaskMode.OPEN_DISCOVERY
            )
        earliest = _optional_wall_datetime(
            value.get("earliest_departure_at"),
            "earliest_departure_at",
        )
        latest = _optional_wall_datetime(
            value.get("latest_return_at"),
            "latest_return_at",
        )
        if earliest and latest and datetime.fromisoformat(latest) <= datetime.fromisoformat(earliest):
            raise TravelAgentError(
                "latest_return_at must be after earliest_departure_at"
            )
        travelers = value.get("travelers")
        if travelers is not None and (
            not isinstance(travelers, int)
            or isinstance(travelers, bool)
            or travelers < 1
        ):
            raise TravelAgentError(
                "travelers must be a positive integer or null"
            )
        budget = value.get("total_budget_cny")
        if budget is not None and (
            not isinstance(budget, (int, float))
            or isinstance(budget, bool)
            or float(budget) <= 0
        ):
            raise TravelAgentError(
                "total_budget_cny must be a positive number or null"
            )
        pace = _optional_text(value.get("pace"), "pace")
        if pace is not None and pace not in {
            "relaxed",
            "standard",
            "intensive",
            "custom",
        }:
            raise TravelAgentError("unsupported pace")
        return cls(
            task_mode=parsed_mode,
            origin=_optional_text(value.get("origin"), "origin"),
            destination_anchor=destination,
            earliest_departure_at=earliest,
            latest_return_at=latest,
            travelers=travelers,
            total_budget_cny=float(budget) if budget is not None else None,
            pace=pace,
            transport_preferences=_text_tuple(
                value.get("transport_preferences", ()),
                "transport_preferences",
            ),
            themes=_text_tuple(value.get("themes", ()), "themes"),
            needs_confirmation=_text_tuple(
                value.get("needs_confirmation", ()),
                "needs_confirmation",
            ),
            missing_fields=_text_tuple(
                value.get("missing_fields", ()),
                "missing_fields",
            ),
            interpretation=str(value.get("interpretation", "")),
            classification_basis=str(
                value.get("classification_basis", "caller_supplied")
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "task_mode": self.task_mode.value,
            "origin": self.origin,
            "destination_anchor": self.destination_anchor,
            "earliest_departure_at": self.earliest_departure_at,
            "latest_return_at": self.latest_return_at,
            "travelers": self.travelers,
            "total_budget_cny": self.total_budget_cny,
            "pace": self.pace,
            "transport_preferences": list(self.transport_preferences),
            "themes": list(self.themes),
            "needs_confirmation": list(self.needs_confirmation),
            "missing_fields": list(self.missing_fields),
            "interpretation": self.interpretation,
            "classification_basis": self.classification_basis,
        }


@dataclass(frozen=True)
class Revision:
    """Explicit, structured changes to an existing run."""

    removed_attraction_ids: tuple[str, ...] = ()
    forced_days: Mapping[str, int] = field(default_factory=dict)
    event_duration_minutes: Mapping[str, int] = field(default_factory=dict)
    locked_event_ids: tuple[str, ...] = ()
    must_visit: tuple[str, ...] = ()
    pace: str | None = None
    night_activity: bool | None = None
    user_message: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> Revision:
        forced_days = _integer_mapping(
            value.get("forced_days", {}),
            "forced_days",
            minimum=1,
            maximum=366,
        )
        durations = _integer_mapping(
            value.get("event_duration_minutes", {}),
            "event_duration_minutes",
            minimum=15,
            maximum=720,
        )
        pace = _optional_text(value.get("pace"), "pace")
        if pace is not None and pace not in {
            "relaxed",
            "standard",
            "intensive",
            "custom",
        }:
            raise TravelAgentError("unsupported revision pace")
        night = value.get("night_activity")
        if night is not None and not isinstance(night, bool):
            raise TravelAgentError(
                "night_activity must be a boolean or null"
            )
        return cls(
            removed_attraction_ids=_text_tuple(
                value.get("removed_attraction_ids", ()),
                "removed_attraction_ids",
            ),
            forced_days=forced_days,
            event_duration_minutes=durations,
            locked_event_ids=_text_tuple(
                value.get("locked_event_ids", ()),
                "locked_event_ids",
            ),
            must_visit=_text_tuple(
                value.get("must_visit", ()),
                "must_visit",
            ),
            pace=pace,
            night_activity=night,
            user_message=_optional_text(
                value.get("user_message"),
                "user_message",
            ),
        )

    def planner_edits(self) -> dict[str, object]:
        return {
            "removed_attraction_ids": list(self.removed_attraction_ids),
            "forced_days": dict(self.forced_days),
            "event_duration_minutes": dict(
                self.event_duration_minutes
            ),
            "locked_event_ids": list(self.locked_event_ids),
            "must_visit": list(self.must_visit),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.planner_edits(),
            "pace": self.pace,
            "night_activity": self.night_activity,
            "user_message": self.user_message,
        }


@dataclass(frozen=True)
class EvidenceItem:
    """One tool-owned input to a destination context."""

    evidence_id: str
    domain: str
    status: EvidenceStatus
    value: object
    sources: tuple[Mapping[str, object], ...] = ()
    missing_reason: str | None = None
    conflict_details: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> EvidenceItem:
        try:
            status = EvidenceStatus(str(value["status"]))
        except (KeyError, ValueError):
            raise TravelAgentError("evidence has invalid status") from None
        evidence_id = _required_text(
            value.get("evidence_id"),
            "evidence_id",
        )
        domain = _required_text(value.get("domain"), "domain")
        raw_sources = value.get("sources", ())
        if (
            not isinstance(raw_sources, (list, tuple))
            or any(not isinstance(item, Mapping) for item in raw_sources)
        ):
            raise TravelAgentError("evidence sources must be objects")
        missing_reason = _optional_text(
            value.get("missing_reason"),
            "missing_reason",
        )
        conflicts = _text_tuple(
            value.get("conflict_details", ()),
            "conflict_details",
        )
        if status is EvidenceStatus.SOURCED and not raw_sources:
            raise TravelAgentError("sourced evidence requires a source")
        if status is EvidenceStatus.MISSING and missing_reason is None:
            raise TravelAgentError(
                "missing evidence requires missing_reason"
            )
        if status is EvidenceStatus.CONFLICTING and not conflicts:
            raise TravelAgentError(
                "conflicting evidence requires conflict_details"
            )
        return cls(
            evidence_id=evidence_id,
            domain=domain,
            status=status,
            value=deepcopy(value.get("value")),
            sources=tuple(deepcopy(dict(item)) for item in raw_sources),
            missing_reason=missing_reason,
            conflict_details=conflicts,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "domain": self.domain,
            "status": self.status.value,
            "value": deepcopy(self.value),
            "sources": [deepcopy(dict(item)) for item in self.sources],
            "missing_reason": self.missing_reason,
            "conflict_details": list(self.conflict_details),
        }


@dataclass(frozen=True)
class DestinationContext:
    """Run-local facts built only from user input and invoked tools."""

    context_id: str
    intent: TravelIntent
    evidence: tuple[EvidenceItem, ...]
    built_at: str

    @property
    def missing_domains(self) -> tuple[str, ...]:
        return tuple(
            item.domain
            for item in self.evidence
            if item.status is EvidenceStatus.MISSING
        )

    @property
    def conflicting_domains(self) -> tuple[str, ...]:
        return tuple(
            item.domain
            for item in self.evidence
            if item.status is EvidenceStatus.CONFLICTING
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "context_id": self.context_id,
            "intent": self.intent.to_dict(),
            "evidence": [item.to_dict() for item in self.evidence],
            "missing_domains": list(self.missing_domains),
            "conflicting_domains": list(self.conflicting_domains),
            "built_at": self.built_at,
        }


EvidenceCollector = Callable[
    [TravelIntent],
    EvidenceItem | Mapping[str, object] | list[EvidenceItem | Mapping[str, object]],
]
ContextPlanner = Callable[[DestinationContext], Mapping[str, object]]
PlanValidator = Callable[
    [DestinationContext, Mapping[str, object]],
    Mapping[str, object],
]


@dataclass(frozen=True)
class DestinationCollectors:
    railway: EvidenceCollector | None = None
    map: EvidenceCollector | None = None
    web: EvidenceCollector | None = None


@dataclass(frozen=True)
class AgentEvent:
    sequence: int
    event_id: str
    session_id: str
    run_id: str
    event_type: str
    status: str
    message: str
    occurred_at: str
    details: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "event_type": self.event_type,
            "status": self.status,
            "message": self.message,
            "occurred_at": self.occurred_at,
            "details": deepcopy(dict(self.details)),
        }


@dataclass
class AgentRun:
    run_id: str
    session_id: str
    intent: TravelIntent
    status: RunStatus
    created_at: str
    parent_run_id: str | None = None
    revision: Revision | None = None
    confirmed_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    result: dict[str, object] | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": self.status.value,
            "intent": self.intent.to_dict(),
            "parent_run_id": self.parent_run_id,
            "revision": (
                self.revision.to_dict()
                if self.revision is not None
                else None
            ),
            "created_at": self.created_at,
            "confirmed_at": self.confirmed_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": deepcopy(self.result),
            "error_code": self.error_code,
        }


@dataclass
class AgentSession:
    session_id: str
    created_at: str
    run_ids: list[str]
    current_run_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "run_ids": list(self.run_ids),
            "current_run_id": self.current_run_id,
        }


ToolEvent = Callable[
    [str, str, str, Mapping[str, object] | None],
    None,
]
RunExecutor = Callable[[TravelIntent, ToolEvent], Mapping[str, object]]
RevisionExecutor = Callable[
    [Mapping[str, object], Revision, ToolEvent],
    Mapping[str, object],
]


class InMemoryAgentStore:
    """Process-local session/run/event storage for the local product."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._sessions: dict[str, AgentSession] = {}
        self._runs: dict[str, AgentRun] = {}
        self._events: dict[str, list[AgentEvent]] = {}
        self._sequence = 0

    def create(
        self,
        intent: TravelIntent,
        *,
        session_id: str | None = None,
        parent_run_id: str | None = None,
        revision: Revision | None = None,
    ) -> AgentRun:
        now = _now()
        with self._condition:
            active_session_id = session_id or str(uuid4())
            if session_id is not None and session_id not in self._sessions:
                raise TravelAgentError("session does not exist")
            run = AgentRun(
                run_id=str(uuid4()),
                session_id=active_session_id,
                intent=intent,
                status=RunStatus.AWAITING_CONFIRMATION,
                created_at=now,
                parent_run_id=parent_run_id,
                revision=revision,
            )
            self._runs[run.run_id] = run
            if session_id is None:
                self._sessions[active_session_id] = AgentSession(
                    session_id=active_session_id,
                    created_at=now,
                    run_ids=[run.run_id],
                    current_run_id=run.run_id,
                )
                self._events[active_session_id] = []
            else:
                session = self._sessions[active_session_id]
                session.run_ids.append(run.run_id)
                session.current_run_id = run.run_id
            self._append_unlocked(
                run,
                event_type="intent.received",
                status="completed",
                message="已接收结构化旅行意图，等待用户确认。",
                details={"task_mode": intent.task_mode.value},
            )
            return deepcopy(run)

    def get_run(self, run_id: str) -> AgentRun:
        with self._lock:
            try:
                return deepcopy(self._runs[run_id])
            except KeyError:
                raise TravelAgentError("run does not exist") from None

    def get_session(self, session_id: str) -> AgentSession:
        with self._lock:
            try:
                return deepcopy(self._sessions[session_id])
            except KeyError:
                raise TravelAgentError("session does not exist") from None

    def confirm(
        self,
        run_id: str,
        intent: TravelIntent | None,
    ) -> AgentRun:
        with self._condition:
            run = self._required_run(run_id)
            if run.status is not RunStatus.AWAITING_CONFIRMATION:
                raise TravelAgentError("run is not awaiting confirmation")
            if intent is not None:
                run.intent = intent
            run.status = RunStatus.CONFIRMED
            run.confirmed_at = _now()
            self._append_unlocked(
                run,
                event_type="intent.confirmed",
                status="completed",
                message="用户已确认结构化旅行意图。",
                details={"task_mode": run.intent.task_mode.value},
            )
            return deepcopy(run)

    def start(self, run_id: str) -> AgentRun:
        with self._condition:
            run = self._required_run(run_id)
            if run.status is not RunStatus.CONFIRMED:
                raise TravelAgentError("run must be confirmed before execution")
            run.status = RunStatus.RUNNING
            run.started_at = _now()
            self._append_unlocked(
                run,
                event_type="run.started",
                status="running",
                message="开始执行已确认的旅行任务。",
            )
            return deepcopy(run)

    def complete(
        self,
        run_id: str,
        result: Mapping[str, object],
    ) -> AgentRun:
        with self._condition:
            run = self._required_run(run_id)
            if run.status is not RunStatus.RUNNING:
                raise TravelAgentError("run is not running")
            run.status = RunStatus.COMPLETED
            run.result = deepcopy(dict(result))
            run.completed_at = _now()
            self._append_unlocked(
                run,
                event_type="run.completed",
                status="completed",
                message="旅行任务执行完成。",
            )
            return deepcopy(run)

    def fail(self, run_id: str, error_code: str) -> AgentRun:
        with self._condition:
            run = self._required_run(run_id)
            run.status = RunStatus.FAILED
            run.error_code = error_code
            run.completed_at = _now()
            self._append_unlocked(
                run,
                event_type="run.failed",
                status="failed",
                message="旅行任务执行失败。",
                details={"error_code": error_code},
            )
            return deepcopy(run)

    def append_event(
        self,
        run_id: str,
        *,
        event_type: str,
        status: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> AgentEvent:
        with self._condition:
            run = self._required_run(run_id)
            return deepcopy(
                self._append_unlocked(
                    run,
                    event_type=event_type,
                    status=status,
                    message=message,
                    details=details,
                )
            )

    def events_after(
        self,
        session_id: str,
        sequence: int,
    ) -> list[AgentEvent]:
        with self._lock:
            if session_id not in self._sessions:
                raise TravelAgentError("session does not exist")
            return [
                deepcopy(event)
                for event in self._events[session_id]
                if event.sequence > sequence
            ]

    def wait_for_events(
        self,
        session_id: str,
        sequence: int,
        timeout: float,
    ) -> list[AgentEvent]:
        with self._condition:
            if session_id not in self._sessions:
                raise TravelAgentError("session does not exist")
            available = [
                event
                for event in self._events[session_id]
                if event.sequence > sequence
            ]
            if not available:
                self._condition.wait(timeout)
            return [
                deepcopy(event)
                for event in self._events[session_id]
                if event.sequence > sequence
            ]

    def _required_run(self, run_id: str) -> AgentRun:
        try:
            return self._runs[run_id]
        except KeyError:
            raise TravelAgentError("run does not exist") from None

    def _append_unlocked(
        self,
        run: AgentRun,
        *,
        event_type: str,
        status: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> AgentEvent:
        self._sequence += 1
        event = AgentEvent(
            sequence=self._sequence,
            event_id=str(uuid4()),
            session_id=run.session_id,
            run_id=run.run_id,
            event_type=event_type,
            status=status,
            message=message,
            occurred_at=_now(),
            details=deepcopy(dict(details or {})),
        )
        self._events[run.session_id].append(event)
        self._condition.notify_all()
        return event


DEFAULT_AGENT_STORE = InMemoryAgentStore()


def create_run(
    intent: TravelIntent | Mapping[str, object],
    *,
    store: InMemoryAgentStore = DEFAULT_AGENT_STORE,
) -> AgentRun:
    """Create a new session and an unconfirmed run."""

    contract = (
        intent
        if isinstance(intent, TravelIntent)
        else TravelIntent.from_mapping(intent)
    )
    return store.create(contract)


def confirm_intent(
    run_id: str,
    intent: TravelIntent | Mapping[str, object] | None = None,
    *,
    store: InMemoryAgentStore = DEFAULT_AGENT_STORE,
) -> AgentRun:
    """Confirm the extracted contract once, optionally with user corrections."""

    contract = (
        intent
        if isinstance(intent, TravelIntent)
        else (
            TravelIntent.from_mapping(intent)
            if intent is not None
            else None
        )
    )
    return store.confirm(run_id, contract)


def execute_run(
    run_id: str,
    *,
    executor: RunExecutor,
    store: InMemoryAgentStore = DEFAULT_AGENT_STORE,
) -> AgentRun:
    """Execute one confirmed run and persist public tool events."""

    run = store.start(run_id)

    def emit(
        tool: str,
        status: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        store.append_event(
            run_id,
            event_type=f"tool.{status}",
            status=status,
            message=message,
            details={"tool": tool, **dict(details or {})},
        )

    try:
        result = executor(run.intent, emit)
        if not isinstance(result, Mapping):
            raise TravelAgentError("run executor must return an object")
        return store.complete(run_id, result)
    except Exception as error:
        store.fail(run_id, f"EXECUTOR_{type(error).__name__.upper()}")
        raise


def collect_destination_evidence(
    intent: TravelIntent,
    *,
    collectors: DestinationCollectors,
    emit: ToolEvent,
) -> tuple[EvidenceItem, ...]:
    """Collect all context inputs without catalog or static-data fallback."""

    user_item = EvidenceItem(
        evidence_id=f"user-{uuid4()}",
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
    evidence: list[EvidenceItem] = [user_item]
    for domain, collector in (
        ("railway", collectors.railway),
        ("map", collectors.map),
        ("web", collectors.web),
    ):
        if collector is None:
            evidence.append(
                EvidenceItem(
                    evidence_id=f"{domain}-{uuid4()}",
                    domain=domain,
                    status=EvidenceStatus.MISSING,
                    value=None,
                    missing_reason=f"{domain}_collector_not_configured",
                )
            )
            emit(
                domain,
                "completed",
                f"{domain}数据源未配置，结果保持missing。",
                {"evidence_status": "missing"},
            )
            continue
        emit(domain, "started", f"开始收集{domain}证据。", None)
        collected = collector(intent)
        raw_items = collected if isinstance(collected, list) else [collected]
        if not raw_items:
            raise TravelAgentError(
                f"{domain} collector returned no evidence item"
            )
        normalized = [
            item
            if isinstance(item, EvidenceItem)
            else EvidenceItem.from_mapping(item)
            for item in raw_items
        ]
        if any(item.domain != domain for item in normalized):
            raise TravelAgentError(
                f"{domain} collector returned another domain"
            )
        evidence.extend(normalized)
        emit(
            domain,
            "completed",
            f"{domain}证据收集完成。",
            {
                "evidence_statuses": [
                    item.status.value for item in normalized
                ]
            },
        )
    return tuple(evidence)


def build_destination_context(
    intent: TravelIntent,
    evidence: tuple[EvidenceItem, ...],
) -> DestinationContext:
    """Build an immutable context from this run's collected evidence."""

    domains = [item.domain for item in evidence]
    if "user_input" not in domains:
        raise TravelAgentError("destination context requires user evidence")
    for required in ("railway", "map", "web"):
        if required not in domains:
            raise TravelAgentError(
                f"destination context omitted {required} evidence"
            )
    return DestinationContext(
        context_id=str(uuid4()),
        intent=intent,
        evidence=tuple(evidence),
        built_at=_now(),
    )


def execute_destination_pipeline(
    intent: TravelIntent,
    emit: ToolEvent,
    *,
    collectors: DestinationCollectors,
    planner: ContextPlanner,
    validator: PlanValidator,
) -> Mapping[str, object]:
    """Run parse → collect → context → plan → validate."""

    emit(
        "parse_intent",
        "completed",
        "结构化TravelIntent已通过合同校验。",
        {"task_mode": intent.task_mode.value},
    )
    evidence = collect_destination_evidence(
        intent,
        collectors=collectors,
        emit=emit,
    )
    emit(
        "destination_context",
        "started",
        "正在构建本次运行的DestinationContext。",
        None,
    )
    context = build_destination_context(intent, evidence)
    emit(
        "destination_context",
        "completed",
        "DestinationContext构建完成。",
        {
            "missing_domains": list(context.missing_domains),
            "conflicting_domains": list(context.conflicting_domains),
        },
    )
    emit("planner", "started", "开始生成上下文约束下的计划。", None)
    plan = planner(context)
    if not isinstance(plan, Mapping):
        raise TravelAgentError("planner must return an object")
    emit("planner", "completed", "计划生成完成。", None)
    emit("validator", "started", "开始验证计划与证据边界。", None)
    validation = validator(context, plan)
    if not isinstance(validation, Mapping):
        raise TravelAgentError("validator must return an object")
    emit(
        "validator",
        "completed",
        "计划验证完成。",
        {"valid": validation.get("valid")},
    )
    return {
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


def revise_run(
    run_id: str,
    revision: Revision | Mapping[str, object],
    *,
    executor: RevisionExecutor,
    store: InMemoryAgentStore = DEFAULT_AGENT_STORE,
) -> AgentRun:
    """Create and execute a child run that reuses the previous result."""

    previous = store.get_run(run_id)
    if previous.status is not RunStatus.COMPLETED or previous.result is None:
        raise TravelAgentError("only a completed run can be revised")
    contract = (
        revision
        if isinstance(revision, Revision)
        else Revision.from_mapping(revision)
    )
    child = store.create(
        previous.intent,
        session_id=previous.session_id,
        parent_run_id=previous.run_id,
        revision=contract,
    )
    store.confirm(child.run_id, None)
    child = store.start(child.run_id)

    def emit(
        tool: str,
        status: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        store.append_event(
            child.run_id,
            event_type=f"tool.{status}",
            status=status,
            message=message,
            details={"tool": tool, **dict(details or {})},
        )

    try:
        result = executor(previous.result, contract, emit)
        if not isinstance(result, Mapping):
            raise TravelAgentError("revision executor must return an object")
        return store.complete(child.run_id, result)
    except Exception as error:
        store.fail(
            child.run_id,
            f"REVISION_EXECUTOR_{type(error).__name__.upper()}",
        )
        raise


def progress_contract() -> list[dict[str, str]]:
    """Return stable public progress labels without claiming work occurred."""

    return [
        {"id": identifier, "label": label, "status": "pending"}
        for identifier, label in _PROGRESS_STEPS
    ]


def runtime_status() -> dict[str, object]:
    """Describe the core without inspecting any model configuration."""

    return {
        "mode": "structured_contract",
        "model_required": False,
        "model_adapter_loaded": False,
        "display": "结构化 Agent 合同已就绪",
        "fact_policy": "数字只能来自工具或用户显式输入。",
    }


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TravelAgentError(f"{field_name} must be text or null")
    stripped = value.strip()
    return stripped or None


def _required_text(value: object, field_name: str) -> str:
    text = _optional_text(value, field_name)
    if text is None:
        raise TravelAgentError(f"{field_name} is required")
    return text


def _optional_wall_datetime(
    value: object,
    field_name: str,
) -> str | None:
    text = _optional_text(value, field_name)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise TravelAgentError(
            f"{field_name} must be an ISO local datetime"
        ) from None
    if parsed.tzinfo is not None:
        raise TravelAgentError(
            f"{field_name} must be a local wall datetime"
        )
    return parsed.isoformat(timespec="minutes")


def _text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise TravelAgentError(
            f"{field_name} must be an array of non-empty text"
        )
    return tuple(item.strip() for item in value)


def _integer_mapping(
    value: object,
    field_name: str,
    *,
    minimum: int,
    maximum: int,
) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise TravelAgentError(f"{field_name} must be an object")
    result: dict[str, int] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(item, int)
            or isinstance(item, bool)
            or not minimum <= item <= maximum
        ):
            raise TravelAgentError(f"{field_name} contains an invalid entry")
        result[key] = item
    return result


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


__all__ = [
    "AgentEvent",
    "AgentRun",
    "AgentSession",
    "DEFAULT_AGENT_STORE",
    "DestinationCollectors",
    "DestinationContext",
    "EvidenceItem",
    "EvidenceStatus",
    "InMemoryAgentStore",
    "Revision",
    "RunStatus",
    "TaskMode",
    "TravelAgentError",
    "TravelIntent",
    "confirm_intent",
    "collect_destination_evidence",
    "create_run",
    "execute_destination_pipeline",
    "execute_run",
    "build_destination_context",
    "progress_contract",
    "revise_run",
    "runtime_status",
]
