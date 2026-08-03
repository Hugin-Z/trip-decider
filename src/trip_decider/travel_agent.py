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
import json
import os
from pathlib import Path

from trip_decider.evidence_core import (
    collection_metadata,
    derive_facts,
    support_from_legacy_name,
)
from threading import Condition, RLock
from typing import Any
from uuid import uuid4


_PROGRESS_STEPS = (
    ("understand", "理解需求"),
    ("collect", "查询真实数据"),
    ("validate", "验证可行性"),
    ("plan", "生成行程"),
)

_REQUIRED_INTENT_FIELDS = (
    "origin",
    "earliest_departure_at",
    "latest_return_at",
    "travelers",
    "total_budget_cny",
    "pace",
    "transport_preferences",
)


class TravelAgentError(RuntimeError):
    """Raised when an agent contract or lifecycle transition is invalid."""


#: 编程错误——**不是**业务失败。
#:
#: 宽捕获 + 专属失败叙述 = 任何 bug 都穿它的外衣。此前一处
#: ``except Exception`` 把 ``NameError`` 包装成「真实证据不足」，对外叙述与
#: 事故原因毫无关系，归因浪费了一整轮：日志里写着证据不足，于是所有人去查
#: 采集器和数据源，而故障在代码里。
#:
#: 判据是「这个异常说明输入不合预期，还是说明代码写错了」。下面这几类只可能
#: 是后者：它们不该被任何 ``except Exception`` 消化成一句业务话术，要么重抛，
#: 要么如实记下类型。业务失败保留原叙述——本注释不是要消灭宽捕获，是要它
#: 别说谎。
NON_BUSINESS_ERRORS: tuple[type[BaseException], ...] = (
    NameError,
    AttributeError,
    TypeError,
    ImportError,
)


#: ``run.error_code`` 的完整取值域（P5 轮 2 收敛，`p5r1-handoff.md` §3 裁决 2）。
#:
#: 此前这个字段**没有取值域**：唯一的两个写入口 ``fail()`` / ``block()`` 收任意
#: 字符串，而九个生产点里有四个把异常类名插进码里
#: （``f"EXECUTOR_{型名}"`` 之类）。取值域因此是「能逃出那四个 try 的每一个异常
#: 类名」——穷举不了，前端也就不可能查得全，实测 4 键的查表漏掉了
#: ``WEB_ACTION_STALLED`` 与四个 ``*_EVIDENCE_BLOCKED``，全部静默落到兜底文案。
#:
#: 收敛成两段式：**码本身有限**，异常类名降进 ``AgentRun.error_detail``。
#: 有限性由形状保证而不是靠九个调用点自律——``fail()`` / ``block()`` 在入口
#: 校验，未注册的码直接抛（D20）。同仓已有先例：
#: ``adapters/contracts.py`` 的 ``INGESTION_PROBLEM_CODES`` 就是这么做的。
#:
#: 命名原则与 blocker_id 同源：说**动作为什么停**，不复述证据状态。
#: ``*_EVIDENCE_BLOCKED`` 说的是证据不是动作，故改 ``*_ACTION_FAILED``；
#: ``WEB_EVIDENCE_REQUIRED`` 的判据只看 ``action_type`` 前缀、根本不看 domain，
#: 故改 ``CODEX_ACTION_REQUIRED``。``*_ACTION_STALLED`` 有意保留原名（裁决 1：
#: 「停滞」与「超时」的语义差不值一次全量同步的风险）。
_ACTION_DOMAINS: tuple[str, ...] = ("RAILWAY", "WEB", "MAP", "PLANNER")

RUN_ERROR_CODES: frozenset[str] = frozenset(
    {
        # 动作超时：等满 30 秒没有新进展，我们不再等了
        *(f"{domain}_ACTION_STALLED" for domain in _ACTION_DOMAINS),
        # 动作执行失败：注册工具抛了业务异常，这个域没有下一步可试
        *(f"{domain}_ACTION_FAILED" for domain in _ACTION_DOMAINS),
        # 停下来等外部动作
        "CODEX_ACTION_REQUIRED",
        "USER_INPUT_REQUIRED",
        # 阶段性失败（业务）
        "RUN_EXECUTION_FAILED",
        "REVISION_EXECUTION_FAILED",
        "ACTION_LOOP_FAILED",
        "GUIDED_COMPARISON_UNAVAILABLE",
        # 我们自己的代码坏了（D12：非业务异常必须自报家门，不穿业务外衣）
        "INTERNAL_ERROR",
    }
)


def _require_registered_error_code(code: str) -> None:
    """写入口守门：未注册的码直接抛，不静默放行。

    这一条是收敛能不能守住的**全部**保证。九个生产点里有六个是 f-string 拼的，
    靠 review 盯着「别再往码里插变量」是纪律，纪律会被下一个人绕过；把校验放在
    仅有的两个写入口，绕过它就得改这个函数——D20 说的「让不小心无从发生」。

    只管写，不管读：盘上的历史旧码照常读得回来（见 ``_run_from_persisted``）。
    """

    if code not in RUN_ERROR_CODES:
        raise TravelAgentError(
            f"unregistered run error_code: {code!r}. "
            "取值域是 travel_agent.RUN_ERROR_CODES；"
            "异常类名放 error_detail，不要拼进码里。"
        )


def run_error_code(error: BaseException, business_code: str) -> tuple[str, str]:
    """按 D12 分流，返回 ``(error_code, error_detail)``。

    非业务异常（``NON_BUSINESS_ERRORS``）一律归 ``INTERNAL_ERROR``——「这段代码
    有 bug」和「采集器没拿到数据」在可观测层面完全一样，不在码上分开，归因就得
    靠猜。业务失败用调用点给的有限码。

    两支都把异常类名放进 ``error_detail``：类型信息一条都不能丢（D12 的
    「如实记下类型」），但它不进码本身，否则取值域立刻回到无界。
    """

    detail = type(error).__name__
    if isinstance(error, NON_BUSINESS_ERRORS):
        return "INTERNAL_ERROR", detail
    return business_code, detail


class TaskMode(str, Enum):
    """Top-level routing selected before tool execution."""

    OPEN_DISCOVERY = "OPEN_DISCOVERY"
    GUIDED_DISCOVERY = "GUIDED_DISCOVERY"
    DIRECT_PLAN = "DIRECT_PLAN"
    PLAN_AUDIT = "PLAN_AUDIT"


_GUIDED_DESTINATION_MARKERS = (
    "倾向",
    "优先",
    "大概想去",
    "考虑",
)
_DIRECT_DESTINATION_MARKERS = (
    "确定",
    "就去",
    "已经订了",
)
_LEGACY_TASK_MODE_ALIASES = {
    "ANCHORED_PLAN": TaskMode.DIRECT_PLAN,
}


def _classify_task_mode(
    *,
    requested_mode: object,
    destination_anchor: str | None,
    destination_expression: str | None,
) -> tuple[TaskMode, str]:
    """Classify routing without treating every destination hint as fixed."""

    if requested_mode is None:
        parsed_mode = None
    else:
        raw_mode = str(requested_mode)
        parsed_mode = _LEGACY_TASK_MODE_ALIASES.get(raw_mode)
        if parsed_mode is None:
            try:
                parsed_mode = TaskMode(raw_mode)
            except ValueError:
                raise TravelAgentError("unsupported task_mode") from None
    if parsed_mode is TaskMode.PLAN_AUDIT:
        return parsed_mode, "explicit_plan_audit"
    if destination_anchor is None:
        return TaskMode.OPEN_DISCOVERY, "no_destination_region"
    if parsed_mode is TaskMode.DIRECT_PLAN:
        return parsed_mode, "explicit_direct_plan"
    if parsed_mode is TaskMode.GUIDED_DISCOVERY:
        return parsed_mode, "explicit_guided_discovery"

    expression = destination_expression or ""
    if any(marker in expression for marker in _DIRECT_DESTINATION_MARKERS):
        return TaskMode.DIRECT_PLAN, "destination_expression_direct_marker"
    if any(marker in expression for marker in _GUIDED_DESTINATION_MARKERS):
        return (
            TaskMode.GUIDED_DISCOVERY,
            "destination_expression_guided_marker",
        )
    return (
        TaskMode.GUIDED_DISCOVERY,
        "destination_anchor_without_direct_commitment",
    )


class AgentRuntimeMode(str, Enum):
    """How a structured intent reaches the model-neutral runtime."""

    CODEX_HOSTED = "CODEX_HOSTED"
    STANDALONE_WEB = "STANDALONE_WEB"


class RunStatus(str, Enum):
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


# domain -> data_type。与 evidence_projection.DOMAIN_DATA_TYPES 同源；写在这里
# 是为了让 EvidenceItem.facts 不必反向依赖读取层。
_DOMAIN_DATA_TYPES = {
    "railway": "railway_schedule_fare",
    "web": "destination_profile",
    "map": "poi_coordinate",
}


class EvidenceStatus(str, Enum):
    """证据的 support 轴（``docs/contracts/evidence-axes.md`` §1）。

    ``ESTIMATED`` 于 2026-08-02（P3b）加入。此前只有三态，于是「有可用值」
    这件事只能用 ``SOURCED`` 表达——``p3b-gate-inventory.md`` §4.1 记录的
    29 处二值闸门全部源于此。判断「能不能用」请用 :attr:`is_usable`，不要
    直接与 ``SOURCED`` 比较。
    """

    SOURCED = "sourced"
    ESTIMATED = "estimated"
    MISSING = "missing"
    CONFLICTING = "conflicting"

    @property
    def support(self) -> str:
        """support 轴取值（evidence-axes.md §6.3 的映射）。

        映射本身住在内核，全仓只此一份——词表映射和 token 一样，实现数
        必须是 1（基线报告 M1「四套词表」）。
        """

        return support_from_legacy_name(self.value)

    @property
    def is_usable(self) -> bool:
        """是否携带单一可用值。

        ``sourced`` 与 ``estimated`` 都携带；``missing`` 没有值；
        ``conflicting`` 有多个互斥的值，取任何一个都是替用户做裁决。
        """

        return self in {EvidenceStatus.SOURCED, EvidenceStatus.ESTIMATED}


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
    destination_expression: str | None = None
    accommodation_budget_total_cny: float | None = None
    accommodation_budget_per_night_cny: float | None = None
    rooms: int | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> TravelIntent:
        destination = _optional_text(
            value.get("destination_anchor"),
            "destination_anchor",
        )
        destination_expression = _optional_text(
            value.get("destination_expression"),
            "destination_expression",
        )
        requested_mode = value.get("task_mode")
        parsed_mode, mode_basis = _classify_task_mode(
            requested_mode=requested_mode,
            destination_anchor=destination,
            destination_expression=destination_expression,
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
        accommodation_total = _optional_positive_number(
            value.get("accommodation_budget_total_cny"),
            "accommodation_budget_total_cny",
        )
        accommodation_per_night = _optional_positive_number(
            value.get("accommodation_budget_per_night_cny"),
            "accommodation_budget_per_night_cny",
        )
        rooms = value.get("rooms")
        if rooms is not None and (
            not isinstance(rooms, int)
            or isinstance(rooms, bool)
            or rooms < 1
        ):
            raise TravelAgentError("rooms must be a positive integer or null")
        pace = _optional_text(value.get("pace"), "pace")
        if pace is not None and pace not in {
            "relaxed",
            "standard",
            "intensive",
            "custom",
        }:
            raise TravelAgentError("unsupported pace")
        origin = _optional_text(value.get("origin"), "origin")
        transport_preferences = _text_tuple(
            value.get("transport_preferences", ()),
            "transport_preferences",
        )
        supplied_missing = _text_tuple(
            value.get("missing_fields", ()),
            "missing_fields",
        )
        required_fields = (
            ()
            if parsed_mode is TaskMode.PLAN_AUDIT
            else _REQUIRED_INTENT_FIELDS
        )
        inferred_missing = [
            field_name
            for field_name, field_value in (
                ("origin", origin),
                ("earliest_departure_at", earliest),
                ("latest_return_at", latest),
                ("travelers", travelers),
                (
                    "total_budget_cny",
                    float(budget) if budget is not None else None,
                ),
                ("pace", pace),
                ("transport_preferences", transport_preferences),
            )
            if field_name in required_fields
            if field_value is None or field_value == ()
        ]
        if parsed_mode in {
            TaskMode.GUIDED_DISCOVERY,
            TaskMode.DIRECT_PLAN,
        } and destination is None:
            inferred_missing.append("destination_anchor")
        missing = tuple(
            dict.fromkeys((*inferred_missing, *supplied_missing))
        )
        return cls(
            task_mode=parsed_mode,
            origin=origin,
            destination_anchor=destination,
            earliest_departure_at=earliest,
            latest_return_at=latest,
            travelers=travelers,
            total_budget_cny=float(budget) if budget is not None else None,
            pace=pace,
            transport_preferences=transport_preferences,
            themes=_text_tuple(value.get("themes", ()), "themes"),
            needs_confirmation=_text_tuple(
                value.get("needs_confirmation", ()),
                "needs_confirmation",
            ),
            missing_fields=missing,
            interpretation=str(value.get("interpretation", "")),
            classification_basis=str(
                value.get("classification_basis", mode_basis)
            ),
            destination_expression=destination_expression,
            accommodation_budget_total_cny=accommodation_total,
            accommodation_budget_per_night_cny=accommodation_per_night,
            rooms=rooms,
        )

    @property
    def blocking_missing_fields(self) -> tuple[str, ...]:
        """Return fields that prohibit confirmation and execution."""

        values: dict[str, object] = {
            "origin": self.origin,
            "earliest_departure_at": self.earliest_departure_at,
            "latest_return_at": self.latest_return_at,
            "travelers": self.travelers,
            "total_budget_cny": self.total_budget_cny,
            "pace": self.pace,
            "transport_preferences": self.transport_preferences,
            "destination_anchor": self.destination_anchor,
        }
        required = (
            []
            if self.task_mode is TaskMode.PLAN_AUDIT
            else list(_REQUIRED_INTENT_FIELDS)
        )
        if self.task_mode in {
            TaskMode.GUIDED_DISCOVERY,
            TaskMode.DIRECT_PLAN,
        }:
            required.append("destination_anchor")
        inferred = [
            field_name
            for field_name in required
            if values[field_name] is None or values[field_name] == ()
        ]
        return tuple(dict.fromkeys((*inferred, *self.missing_fields)))

    def _persisted_value(self) -> object:
        """v2 落盘形状：facts 数组 + 采集元数据（persistence-v2.md §1.3）。"""

        value = self.value
        if not isinstance(value, Mapping):
            return deepcopy(value)
        if isinstance(value.get("facts"), (list, tuple)):
            return deepcopy(dict(value))
        return deepcopy(
            {
                **collection_metadata(value),
                "facts": [dict(fact) for fact in self.facts],
            }
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
            "destination_expression": self.destination_expression,
            "accommodation_budget_total_cny": (
                self.accommodation_budget_total_cny
            ),
            "accommodation_budget_per_night_cny": (
                self.accommodation_budget_per_night_cny
            ),
            "rooms": self.rooms,
        }


@dataclass(frozen=True)
class Revision:
    """Explicit, structured changes to an existing run."""

    removed_attraction_ids: tuple[str, ...] = ()
    forced_days: Mapping[str, int] = field(default_factory=dict)
    event_duration_minutes: Mapping[str, int] = field(default_factory=dict)
    locked_event_ids: tuple[str, ...] = ()
    must_visit: tuple[str, ...] = ()
    day_start_times: Mapping[str, str] = field(default_factory=dict)
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
        raw_day_starts = value.get("day_start_times", {})
        if not isinstance(raw_day_starts, Mapping):
            raise TravelAgentError("day_start_times must be an object")
        day_start_times: dict[str, str] = {}
        for day, clock in raw_day_starts.items():
            if (
                not isinstance(day, str)
                or not day.isdigit()
                or int(day) < 1
                or not isinstance(clock, str)
            ):
                raise TravelAgentError(
                    "day_start_times must map positive day numbers to HH:MM"
                )
            try:
                parsed_clock = datetime.strptime(clock, "%H:%M")
            except ValueError:
                raise TravelAgentError(
                    "day_start_times values must use HH:MM"
                ) from None
            day_start_times[day] = parsed_clock.strftime("%H:%M")
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
            day_start_times=day_start_times,
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
            "day_start_times": dict(self.day_start_times),
        }

    def _persisted_value(self) -> object:
        """v2 落盘形状：facts 数组 + 采集元数据（persistence-v2.md §1.3）。"""

        value = self.value
        if not isinstance(value, Mapping):
            return deepcopy(value)
        if isinstance(value.get("facts"), (list, tuple)):
            return deepcopy(dict(value))
        return deepcopy(
            {
                **collection_metadata(value),
                "facts": [dict(fact) for fact in self.facts],
            }
        )

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
        if status.is_usable and not raw_sources:
            raise TravelAgentError(
                "evidence carrying a value requires a source"
            )
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

    @property
    def facts(self) -> tuple[Mapping[str, object], ...]:
        """字段级 facts（persistence-v2.md §1.3）。

        两个分支都是活的，**不是双读残余**：

        * ``value`` 已是 v2（从落盘反序列化来的 item）——直读；
        * ``value`` 是 v1 裸 mapping（采集器刚产出，还没落盘）——推导。

        后者是 **v1-in-memory → v2-on-disk 的转换器**：采集器返回的是业务字段
        平铺的 mapping，``_persisted_value`` 靠这条推导把它转成 facts 再写盘。
        它不随双读拆除而消失；消失的只是「读落盘时可能需要推导」那个分支
        （见 ``evidence_projection.item_facts``）。

        support 只下调不上调：``value`` 里为 ``None`` 或字面量 ``"UNKNOWN"``
        的字段降为 ``unknown``，其余继承 item 级。
        """

        if isinstance(self.value, Mapping) and isinstance(
            self.value.get("facts"), (list, tuple)
        ):
            return tuple(
                item for item in self.value["facts"] if isinstance(item, Mapping)
            )
        return derive_facts(
            self.value,
            self.evidence_id,
            self.domain,
            item_support=self.status.support,
            data_type=_DOMAIN_DATA_TYPES.get(self.domain, ""),
            retrieved_at=next(
                (
                    source["retrieved_at"]
                    for source in self.sources
                    if isinstance(source.get("retrieved_at"), str)
                ),
                None,
            ),
            reason=self.missing_reason,
            conflict_details=self.conflict_details,
        )

    def _persisted_value(self) -> object:
        """v2 落盘形状：facts 数组 + 采集元数据（persistence-v2.md §1.3）。"""

        value = self.value
        if not isinstance(value, Mapping):
            return deepcopy(value)
        if isinstance(value.get("facts"), (list, tuple)):
            return deepcopy(dict(value))
        return deepcopy(
            {
                **collection_metadata(value),
                "facts": [dict(fact) for fact in self.facts],
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "domain": self.domain,
            "status": self.status.value,
            "value": self._persisted_value(),
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

    def _persisted_value(self) -> object:
        """v2 落盘形状：facts 数组 + 采集元数据（persistence-v2.md §1.3）。"""

        value = self.value
        if not isinstance(value, Mapping):
            return deepcopy(value)
        if isinstance(value.get("facts"), (list, tuple)):
            return deepcopy(dict(value))
        return deepcopy(
            {
                **collection_metadata(value),
                "facts": [dict(fact) for fact in self.facts],
            }
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

    def _persisted_value(self) -> object:
        """v2 落盘形状：facts 数组 + 采集元数据（persistence-v2.md §1.3）。"""

        value = self.value
        if not isinstance(value, Mapping):
            return deepcopy(value)
        if isinstance(value.get("facts"), (list, tuple)):
            return deepcopy(dict(value))
        return deepcopy(
            {
                **collection_metadata(value),
                "facts": [dict(fact) for fact in self.facts],
            }
        )

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
    #: 停下来的补充事实——目前只放异常类名。与 ``error_code`` 分成两段是为了
    #: 让码保持有限可查表（``RUN_ERROR_CODES``）而类型信息不丢（D12）。
    #: I1：这是**失败时刻的事实**，写入后不再变化，不是「现在该怎么显示」的
    #: 结论，与 ``refresh_failure`` 同性质（`invariants.md` I1 白名单）。
    error_detail: str | None = None

    def _persisted_value(self) -> object:
        """v2 落盘形状：facts 数组 + 采集元数据（persistence-v2.md §1.3）。"""

        value = self.value
        if not isinstance(value, Mapping):
            return deepcopy(value)
        if isinstance(value.get("facts"), (list, tuple)):
            return deepcopy(dict(value))
        return deepcopy(
            {
                **collection_metadata(value),
                "facts": [dict(fact) for fact in self.facts],
            }
        )

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
            "error_detail": self.error_detail,
        }


@dataclass
class AgentSession:
    session_id: str
    created_at: str
    run_ids: list[str]
    current_run_id: str

    def _persisted_value(self) -> object:
        """v2 落盘形状：facts 数组 + 采集元数据（persistence-v2.md §1.3）。"""

        value = self.value
        if not isinstance(value, Mapping):
            return deepcopy(value)
        if isinstance(value.get("facts"), (list, tuple)):
            return deepcopy(dict(value))
        return deepcopy(
            {
                **collection_metadata(value),
                "facts": [dict(fact) for fact in self.facts],
            }
        )

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
    """Session/run/event storage with optional durable runtime files."""

    def __init__(
        self,
        runtime_root: Path | str | None = None,
    ) -> None:
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._sessions: dict[str, AgentSession] = {}
        self._runs: dict[str, AgentRun] = {}
        self._events: dict[str, list[AgentEvent]] = {}
        self._sequence = 0
        self._runtime_root = (
            Path(runtime_root).resolve()
            if runtime_root is not None
            else None
        )
        if self._runtime_root is not None:
            self._runtime_root.mkdir(parents=True, exist_ok=True)
            self._load_runtime()

    @property
    def runtime_root(self) -> Path | None:
        return self._runtime_root

    def run_directory(self, run_id: str) -> Path | None:
        if self._runtime_root is None:
            return None
        if not run_id or any(
            character not in "0123456789abcdef-"
            for character in run_id.lower()
        ):
            raise TravelAgentError("run_id is not safe for persistence")
        return self._runtime_root / run_id

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

    def latest_run(self) -> AgentRun | None:
        """Return the most recently created run, if one exists."""

        with self._lock:
            if not self._runs:
                return None
            return deepcopy(next(reversed(self._runs.values())))

    def list_runs(self) -> list[AgentRun]:
        """Return persisted runs newest first without changing current state."""

        with self._lock:
            return [
                deepcopy(run)
                for run in reversed(tuple(self._runs.values()))
            ]

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

    def record_result(
        self,
        run_id: str,
        result: Mapping[str, object],
    ) -> AgentRun:
        """把 ``result`` 落进 ``run.json``，不改 run 状态。

        persistence-v2.md §13.1 的写入顺序约束需要这个入口：``run.json`` 是
        ``result`` 的**权威**，必须先落；``action-loop.json`` 后落，且不再存
        副本。此前唯一能把 ``result`` 写进 ``run.json`` 的是 ``complete()``，
        而它同时把 run 判为 COMPLETED——草稿态（证据没补齐、不该完成）就没有
        任何途径先落权威，只能让 action-loop 先写。顺序颠倒的根因在这里，
        不在调用点。
        """

        with self._condition:
            run = self._required_run(run_id)
            run.result = deepcopy(dict(result))
            self._persist_unlocked(run)
            self._condition.notify_all()
            return deepcopy(run)

    def resume(self, run_id: str) -> AgentRun:
        """Resume one completed run for an explicit evidence refresh."""

        with self._condition:
            run = self._required_run(run_id)
            if run.status is not RunStatus.COMPLETED:
                raise TravelAgentError(
                    "only a completed run can resume evidence collection"
                )
            run.status = RunStatus.RUNNING
            run.completed_at = None
            self._append_unlocked(
                run,
                event_type="run.resumed",
                status="running",
                message="沿用当前会话和证据，开始显式重新查询。",
            )
            return deepcopy(run)

    def continue_with_intent(
        self,
        run_id: str,
        intent: TravelIntent,
    ) -> AgentRun:
        """Continue one completed discovery run under a selected destination."""

        with self._condition:
            run = self._required_run(run_id)
            if run.status is not RunStatus.COMPLETED:
                raise TravelAgentError(
                    "only a completed run can continue with a selection"
                )
            if intent.blocking_missing_fields:
                raise TravelAgentError(
                    "selected intent is missing required fields"
                )
            previous_mode = run.intent.task_mode
            run.intent = intent
            run.status = RunStatus.CONFIRMED
            run.confirmed_at = _now()
            run.completed_at = None
            run.error_code = None
            self._append_unlocked(
                run,
                event_type="discovery.option_selected",
                status="completed",
                message="用户已选定区域方案，将在同一任务中继续详细规划。",
                details={
                    "previous_task_mode": previous_mode.value,
                    "task_mode": intent.task_mode.value,
                    "destination_anchor": intent.destination_anchor,
                },
            )
            return deepcopy(run)

    def prepare_revision(
        self,
        run_id: str,
        *,
        intent: TravelIntent | None = None,
        revision: Revision | None = None,
    ) -> AgentRun:
        """Prepare a new version on the same run without hiding its result."""

        with self._condition:
            run = self._required_run(run_id)
            if (
                run.status
                not in {
                    RunStatus.COMPLETED,
                    RunStatus.BLOCKED,
                    RunStatus.FAILED,
                }
                or run.result is None
            ):
                raise TravelAgentError(
                    "only a run with a retained result can be revised"
                )
            next_intent = intent or run.intent
            if next_intent.blocking_missing_fields:
                raise TravelAgentError(
                    "revised intent is missing required fields"
                )
            run.intent = next_intent
            run.revision = revision
            run.status = RunStatus.CONFIRMED
            run.confirmed_at = _now()
            run.completed_at = None
            run.error_code = None
            self._append_unlocked(
                run,
                event_type="revision.started",
                status="running",
                message="已在当前任务中开始生成新版本；上一版继续可用。",
                details={
                    "same_run": True,
                    "revision": (
                        revision.to_dict()
                        if revision is not None
                        else None
                    ),
                },
            )
            return deepcopy(run)

    @staticmethod
    def _plan_version_context(
        context: Mapping[str, object],
    ) -> dict[str, object]:
        """PlanVersion 的 context：只留结构与引用，不留证据副本。

        persistence-v2.md §2.3 要求 ``context.evidence`` 删除、改为引用读时解析；
        §5.1 的 R2 是硬要求——引用解析失败必须产出 ``unknown`` + ``next_action``，
        **不得回落到文件内的旧值**。

        落法是让文件里**根本没有可回落的值**：R2 因此由数据形状保证，而不是靠
        读取层自律。留一份内联副本，R2 就退化成一句纪律——而纪律会被下一个人
        绕过，形状不会。
        """

        return trimmed_context(context)

    def persist_plan_version(
        self,
        run_id: str,
        result: Mapping[str, object],
    ) -> dict[str, object] | None:
        """Persist one immutable plan version for an existing run."""

        run_directory = self.run_directory(run_id)
        if run_directory is None:
            return None
        plan = result.get("plan")
        if not isinstance(plan, Mapping):
            raise TravelAgentError("planner result omitted plan")
        # 写入侧只验结构完整（persistence-v2.md §6.2）。「够不够格显示」
        # 是读取时的问题：它会随 now 变，写进盘就冻死了。
        days = plan.get("days")
        if (
            plan.get("artifact_kind") != "PlanVersion"
            or not isinstance(days, list)
            or not days
        ):
            raise TravelAgentError(
                "planner result omitted the PlanVersion installation contract"
            )
        versions = run_directory / "plans"
        versions.mkdir(parents=True, exist_ok=True)
        version = len(list(versions.glob("plan-*.json"))) + 1
        payload = {
            "run_id": run_id,
            "plan_version": version,
            "plan": deepcopy(dict(plan)),
        }
        context = result.get("context")
        if isinstance(context, Mapping):
            payload["context"] = self._plan_version_context(context)
        _atomic_json(
            versions / f"plan-{version:04d}.json",
            payload,
        )
        _atomic_json(
            run_directory / "plan-version.json",
            payload,
        )
        return deepcopy(payload)

    def fail(
        self,
        run_id: str,
        error_code: str,
        *,
        error_detail: str | None = None,
    ) -> AgentRun:
        _require_registered_error_code(error_code)
        with self._condition:
            run = self._required_run(run_id)
            run.status = RunStatus.FAILED
            run.error_code = error_code
            run.error_detail = error_detail
            run.completed_at = _now()
            self._append_unlocked(
                run,
                event_type="run.failed",
                status="failed",
                message="旅行任务执行失败。",
                details={
                    "error_code": error_code,
                    "error_detail": error_detail,
                },
            )
            return deepcopy(run)

    def block(
        self,
        run_id: str,
        result: Mapping[str, object],
        reason_code: str,
        *,
        error_detail: str | None = None,
    ) -> AgentRun:
        """Finish an action loop that cannot make honest progress."""

        _require_registered_error_code(reason_code)
        with self._condition:
            run = self._required_run(run_id)
            if run.status is not RunStatus.RUNNING:
                raise TravelAgentError("run is not running")
            run.status = RunStatus.BLOCKED
            run.result = deepcopy(dict(result))
            run.error_code = reason_code
            run.error_detail = error_detail
            run.completed_at = _now()
            self._append_unlocked(
                run,
                event_type="run.blocked",
                status="failed",
                message="真实证据不足，当前运行已停止。",
                details={
                    "reason_code": reason_code,
                    "error_detail": error_detail,
                },
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
        self._persist_unlocked(run)
        self._condition.notify_all()
        return event

    def _persist_unlocked(self, run: AgentRun) -> None:
        run_directory = self.run_directory(run.run_id)
        if run_directory is None:
            return
        run_directory.mkdir(parents=True, exist_ok=True)
        evidence_directory = run_directory / "evidence"
        evidence_directory.mkdir(parents=True, exist_ok=True)
        namespace_path = evidence_directory / "namespace.json"
        if not namespace_path.exists():
            _atomic_json(
                namespace_path,
                {
                    "schema_version": "1",
                    "run_id": run.run_id,
                    "created_at": run.created_at,
                },
            )
        session = self._sessions[run.session_id]
        _atomic_json(run_directory / "session.json", session.to_dict())
        _atomic_json(run_directory / "run.json", run.to_dict())
        events = [
            event.to_dict()
            for event in self._events[run.session_id]
            if event.run_id == run.run_id
        ]
        _atomic_json_lines(run_directory / "events.jsonl", events)

    def _load_runtime(self) -> None:
        assert self._runtime_root is not None
        loaded_events: dict[str, AgentEvent] = {}
        loaded_runs: list[AgentRun] = []
        for run_directory in sorted(self._runtime_root.iterdir()):
            if not run_directory.is_dir():
                continue
            run_path = run_directory / "run.json"
            session_path = run_directory / "session.json"
            events_path = run_directory / "events.jsonl"
            if not run_path.exists() and not session_path.exists():
                continue
            if not run_path.is_file() or not session_path.is_file():
                raise TravelAgentError(
                    "persisted runtime omitted run or session metadata"
                )
            run = _run_from_mapping(_read_json_object(run_path))
            if run.run_id != run_directory.name:
                raise TravelAgentError(
                    "persisted run_id does not match its directory"
                )
            session = _session_from_mapping(
                _read_json_object(session_path)
            )
            if run.session_id != session.session_id:
                raise TravelAgentError(
                    "persisted run and session linkage mismatch"
                )
            existing_session = self._sessions.get(session.session_id)
            if (
                existing_session is not None
                and existing_session.created_at != session.created_at
            ):
                raise TravelAgentError(
                    "persisted session creation time is inconsistent"
                )
            if (
                existing_session is None
                or len(session.run_ids) > len(existing_session.run_ids)
            ):
                self._sessions[session.session_id] = session
            self._runs[run.run_id] = run
            loaded_runs.append(run)
            if events_path.exists():
                for event in _read_json_lines(events_path):
                    parsed = _event_from_mapping(event)
                    if parsed.run_id != run.run_id:
                        raise TravelAgentError(
                            "persisted event belongs to another run"
                        )
                    loaded_events[parsed.event_id] = parsed
        self._runs = {
            run.run_id: run
            for run in sorted(loaded_runs, key=lambda item: item.created_at)
        }
        runs_by_session: dict[str, list[AgentRun]] = {}
        for run in self._runs.values():
            runs_by_session.setdefault(run.session_id, []).append(run)
        for session_id, session_runs in runs_by_session.items():
            session = self._sessions[session_id]
            ordered_ids = [run.run_id for run in session_runs]
            session.run_ids = ordered_ids
            session.current_run_id = ordered_ids[-1]
        for event in sorted(
            loaded_events.values(),
            key=lambda item: item.sequence,
        ):
            self._events.setdefault(event.session_id, []).append(event)
            self._sequence = max(self._sequence, event.sequence)
        for session_id in self._sessions:
            self._events.setdefault(session_id, [])


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TravelAgentError(
            f"persisted runtime file is unreadable: {path.name}"
        ) from error
    if not isinstance(value, dict):
        raise TravelAgentError(
            f"persisted runtime file is not an object: {path.name}"
        )
    return value


def _read_json_lines(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise TravelAgentError(
            f"persisted runtime file is unreadable: {path.name}"
        ) from error
    values: list[dict[str, object]] = []
    for line in lines:
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise TravelAgentError(
                "persisted event line is invalid JSON"
            ) from error
        if not isinstance(value, dict):
            raise TravelAgentError(
                "persisted event line is not an object"
            )
        values.append(value)
    return values


# P3b：EvidenceStatus 加入 estimated 后，落盘的 status 取值域从 3 值变 4 值。
# 按 PLAN.md v4 §7 约束 3，落盘契约变更必须携带版本标记——基线报告 H1 记录过
# 一次无版本变更的后果（此前全部 run 的已安装计划变为不可读）。
#
# 本次是**最小打标**：只加版本号，不改落盘结构。完整的落盘契约改造属 P4。
RUNTIME_SCHEMA_VERSION = 2

# 需要打标的文件——它们承载 EvidenceItem.status，正是取值域变化的载体。
# 裁决点名的三个文件里有两个已改用新布局（evidence/current.json 与
# evidence/guided-comparison.json），旧名保留是因为读取端仍有回退分支
# （agent_actions.py:2042、trip_application.py:861）。
_VERSIONED_RUNTIME_FILES = frozenset(
    {
        "run.json",
        "current.json",
        "guided-comparison.json",
        "evidence.json",
        "guided-evidence.json",
    }
)


def runtime_schema_version(document: Mapping[str, object]) -> int:
    """读取落盘文件的 schema 版本。无该字段的文件按 1 处理。

    1 = P3b 之前，``status`` 取值域是 sourced/missing/conflicting 三值。
    2 = P3b 起，加入 estimated。
    """

    raw = document.get("schema_version")
    return int(raw) if isinstance(raw, int) and raw > 0 else 1


def stamp_schema_version(
    path: Path,
    value: Mapping[str, object],
) -> dict[str, object]:
    """给需要打标的落盘文件补上 schema_version。

    落盘写入分散在三个模块各自的原子写函数里（``travel_agent._atomic_json``、
    ``agent_actions._atomic_runtime_json``、``trip_application._atomic_json``），
    三者都必须走这一处打标，否则同一批文件会出现版本不一致。
    """

    payload = dict(value)
    if path.name in _VERSIONED_RUNTIME_FILES:
        payload.setdefault("schema_version", RUNTIME_SCHEMA_VERSION)
    return payload


def atomic_runtime_json(path: Path, value: Mapping[str, object]) -> None:
    """写一个 runtime JSON 文件：建目录、打版本标、原子替换。

    **这是全仓唯一的 runtime JSON 写实现。** v1 时期有三份独立实现
    （本函数、``agent_actions._atomic_runtime_json``、
    ``trip_application._atomic_json``），格式还不一致，导致 P3b 的
    schema_version 打标第一次只覆盖了其中一份。任何落盘契约变更要改三处、
    而漏改不会立刻报错——这正是 persistence-v2.md §12.1 记录的问题。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    payload_value = stamp_schema_version(path, value)
    payload = json.dumps(
        payload_value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    _atomic_bytes(path, payload + b"\n")


# 模块内旧名，保留以免一次改动横跨太多调用点。外部一律用 atomic_runtime_json。
_atomic_json = atomic_runtime_json


def _atomic_json_lines(
    path: Path,
    values: list[Mapping[str, object]],
) -> None:
    payload = b"".join(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
        for value in values
    )
    _atomic_bytes(path, payload)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _loaded_optional_text(
    value: object,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TravelAgentError(
            f"persisted {field_name} must be text or null"
        )
    stripped = value.strip()
    return stripped or None


def _loaded_required_text(value: object, field_name: str) -> str:
    text = _loaded_optional_text(value, field_name)
    if text is None:
        raise TravelAgentError(f"persisted {field_name} is required")
    return text


def _loaded_text_tuple(
    value: object,
    field_name: str,
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise TravelAgentError(
            f"persisted {field_name} must be an array of text"
        )
    return tuple(value)


def _intent_from_persisted(
    value: Mapping[str, object],
) -> TravelIntent:
    try:
        raw_task_mode = str(value["task_mode"])
        task_mode = (
            _LEGACY_TASK_MODE_ALIASES[raw_task_mode]
            if raw_task_mode in _LEGACY_TASK_MODE_ALIASES
            else TaskMode(raw_task_mode)
        )
    except (KeyError, ValueError):
        raise TravelAgentError(
            "persisted intent has invalid task_mode"
        ) from None
    travelers = value.get("travelers")
    budget = value.get("total_budget_cny")
    if travelers is not None and (
        not isinstance(travelers, int)
        or isinstance(travelers, bool)
        or travelers < 1
    ):
        raise TravelAgentError(
            "persisted intent has invalid travelers"
        )
    if budget is not None and (
        not isinstance(budget, (int, float))
        or isinstance(budget, bool)
        or float(budget) <= 0
    ):
        raise TravelAgentError(
            "persisted intent has invalid total_budget_cny"
        )
    return TravelIntent(
        task_mode=task_mode,
        origin=_loaded_optional_text(value.get("origin"), "origin"),
        destination_anchor=_loaded_optional_text(
            value.get("destination_anchor"),
            "destination_anchor",
        ),
        earliest_departure_at=_loaded_optional_text(
            value.get("earliest_departure_at"),
            "earliest_departure_at",
        ),
        latest_return_at=_loaded_optional_text(
            value.get("latest_return_at"),
            "latest_return_at",
        ),
        travelers=travelers,
        total_budget_cny=float(budget) if budget is not None else None,
        pace=_loaded_optional_text(value.get("pace"), "pace"),
        transport_preferences=_loaded_text_tuple(
            value.get("transport_preferences", []),
            "transport_preferences",
        ),
        themes=_loaded_text_tuple(value.get("themes", []), "themes"),
        needs_confirmation=_loaded_text_tuple(
            value.get("needs_confirmation", []),
            "needs_confirmation",
        ),
        missing_fields=_loaded_text_tuple(
            value.get("missing_fields", []),
            "missing_fields",
        ),
        interpretation=_loaded_required_text(
            value.get("interpretation", ""),
            "interpretation",
        )
        if value.get("interpretation")
        else "",
        classification_basis=_loaded_required_text(
            value.get("classification_basis"),
            "classification_basis",
        ),
        destination_expression=_loaded_optional_text(
            value.get("destination_expression"),
            "destination_expression",
        ),
    )


def _revision_from_persisted(
    value: Mapping[str, object],
) -> Revision:
    forced_days = value.get("forced_days")
    durations = value.get("event_duration_minutes")
    if not isinstance(forced_days, Mapping) or not isinstance(
        durations,
        Mapping,
    ):
        raise TravelAgentError(
            "persisted revision has invalid numeric mappings"
        )
    normalized_forced: dict[str, int] = {}
    normalized_durations: dict[str, int] = {}
    for source, target, field_name in (
        (forced_days, normalized_forced, "forced_days"),
        (durations, normalized_durations, "event_duration_minutes"),
    ):
        for key, item in source.items():
            if (
                not isinstance(key, str)
                or not isinstance(item, int)
                or isinstance(item, bool)
            ):
                raise TravelAgentError(
                    f"persisted revision has invalid {field_name}"
                )
            target[key] = item
    night_activity = value.get("night_activity")
    if night_activity is not None and not isinstance(
        night_activity,
        bool,
    ):
        raise TravelAgentError(
            "persisted revision has invalid night_activity"
        )
    return Revision(
        removed_attraction_ids=_loaded_text_tuple(
            value.get("removed_attraction_ids", []),
            "removed_attraction_ids",
        ),
        forced_days=normalized_forced,
        event_duration_minutes=normalized_durations,
        locked_event_ids=_loaded_text_tuple(
            value.get("locked_event_ids", []),
            "locked_event_ids",
        ),
        must_visit=_loaded_text_tuple(
            value.get("must_visit", []),
            "must_visit",
        ),
        pace=_loaded_optional_text(value.get("pace"), "pace"),
        night_activity=night_activity,
        user_message=_loaded_optional_text(
            value.get("user_message"),
            "user_message",
        ),
    )


def _run_from_mapping(value: Mapping[str, object]) -> AgentRun:
    try:
        status = RunStatus(str(value["status"]))
    except (KeyError, ValueError):
        raise TravelAgentError("persisted run has invalid status") from None
    intent_raw = value.get("intent")
    if not isinstance(intent_raw, Mapping):
        raise TravelAgentError("persisted run omitted intent")
    revision_raw = value.get("revision")
    if revision_raw is not None and not isinstance(revision_raw, Mapping):
        raise TravelAgentError("persisted run has invalid revision")
    result = value.get("result")
    if result is not None and not isinstance(result, Mapping):
        raise TravelAgentError("persisted run has invalid result")
    return AgentRun(
        run_id=_loaded_required_text(value.get("run_id"), "run_id"),
        session_id=_loaded_required_text(
            value.get("session_id"),
            "session_id",
        ),
        intent=_intent_from_persisted(intent_raw),
        status=status,
        created_at=_loaded_required_text(
            value.get("created_at"),
            "created_at",
        ),
        parent_run_id=_loaded_optional_text(
            value.get("parent_run_id"),
            "parent_run_id",
        ),
        revision=(
            _revision_from_persisted(revision_raw)
            if isinstance(revision_raw, Mapping)
            else None
        ),
        confirmed_at=_loaded_optional_text(
            value.get("confirmed_at"),
            "confirmed_at",
        ),
        started_at=_loaded_optional_text(
            value.get("started_at"),
            "started_at",
        ),
        completed_at=_loaded_optional_text(
            value.get("completed_at"),
            "completed_at",
        ),
        result=deepcopy(dict(result)) if isinstance(result, Mapping) else None,
        error_code=_loaded_optional_text(
            value.get("error_code"),
            "error_code",
        ),
        # 读侧**不校验** error_code 属不属于 RUN_ERROR_CODES。盘上已经躺着
        # 收敛前写下的旧码（`EXECUTOR_TRAVELAGENTERROR`、
        # `RAILWAY_EVIDENCE_BLOCKED` 之类），读它们不该崩——校验的位置是写入口，
        # 读取只负责如实还原历史。旧文件没有 error_detail 键，缺省 None。
        error_detail=_loaded_optional_text(
            value.get("error_detail"),
            "error_detail",
        ),
    )


def _session_from_mapping(value: Mapping[str, object]) -> AgentSession:
    raw_run_ids = value.get("run_ids")
    if (
        not isinstance(raw_run_ids, list)
        or any(not isinstance(item, str) for item in raw_run_ids)
    ):
        raise TravelAgentError("persisted session has invalid run_ids")
    return AgentSession(
        session_id=_loaded_required_text(
            value.get("session_id"),
            "session_id",
        ),
        created_at=_loaded_required_text(
            value.get("created_at"),
            "created_at",
        ),
        run_ids=list(raw_run_ids),
        current_run_id=_loaded_required_text(
            value.get("current_run_id"),
            "current_run_id",
        ),
    )


def _event_from_mapping(value: Mapping[str, object]) -> AgentEvent:
    sequence = value.get("sequence")
    details = value.get("details", {})
    if (
        not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence < 1
        or not isinstance(details, Mapping)
    ):
        raise TravelAgentError("persisted event has invalid shape")
    return AgentEvent(
        sequence=sequence,
        event_id=_loaded_required_text(
            value.get("event_id"),
            "event_id",
        ),
        session_id=_loaded_required_text(
            value.get("session_id"),
            "session_id",
        ),
        run_id=_loaded_required_text(value.get("run_id"), "run_id"),
        event_type=_loaded_required_text(
            value.get("event_type"),
            "event_type",
        ),
        status=_loaded_required_text(value.get("status"), "status"),
        message=_loaded_required_text(value.get("message"), "message"),
        occurred_at=_loaded_required_text(
            value.get("occurred_at"),
            "occurred_at",
        ),
        details=deepcopy(dict(details)),
    )


_RUNTIME_ROOT_ENV = "TRIP_DECIDER_RUNTIME_ROOT"
_DEFAULT_STORE: InMemoryAgentStore | None = None


def default_runtime_root() -> Path:
    """runtime 根目录。环境变量优先，其次当前工作目录。

    v1 用的是 ``Path(__file__).resolve().parents[2]``，假定源码位于
    ``<repo>/src/trip_decider/``——装成 wheel 后它指向 site-packages 的上两级，
    本来就是错的（基线报告 M8）。运行数据不该住在包目录里，所以改为显式的
    环境变量加 cwd。脚本入口一律显式设置 ``TRIP_DECIDER_RUNTIME_ROOT``。
    """

    override = os.environ.get(_RUNTIME_ROOT_ENV)
    if override and override.strip():
        return Path(override).expanduser()
    return Path.cwd() / "runtime" / "sessions"


def default_agent_store() -> InMemoryAgentStore:
    """进程级默认 store，**首次调用时**才建目录读盘。

    v1 在 import 时就构造它，于是任何 ``import trip_decider.travel_agent``
    都会 mkdir 加全量读盘（基线报告 M8）。改为显式工厂而不是模块级
    ``__getattr__`` 懒加载，两个理由：默认参数在函数定义时求值，
    ``def f(store=DEFAULT_AGENT_STORE)`` 会在 import 时就触发 ``__getattr__``，
    延迟不了；而且工厂让「这里有 I/O」在调用点看得见。
    """

    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = InMemoryAgentStore(default_runtime_root())
    return _DEFAULT_STORE


def reset_default_agent_store() -> None:
    """丢弃已构造的默认 store。仅供测试隔离使用。"""

    global _DEFAULT_STORE
    _DEFAULT_STORE = None


def create_run(
    intent: TravelIntent | Mapping[str, object],
    *,
    store: InMemoryAgentStore | None = None,
) -> AgentRun:
    """Create a new session and an unconfirmed run."""
    store = store if store is not None else default_agent_store()

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
    store: InMemoryAgentStore | None = None,
) -> AgentRun:
    """Confirm the extracted contract once, optionally with user corrections."""
    store = store if store is not None else default_agent_store()

    contract = (
        intent
        if isinstance(intent, TravelIntent)
        else (
            TravelIntent.from_mapping(intent)
            if intent is not None
            else None
        )
    )
    candidate = contract or store.get_run(run_id).intent
    missing = candidate.blocking_missing_fields
    if missing:
        raise TravelAgentError(
            "intent_missing_required_fields:" + ",".join(missing)
        )
    return store.confirm(run_id, contract)


def execute_run(
    run_id: str,
    *,
    executor: RunExecutor,
    store: InMemoryAgentStore | None = None,
) -> AgentRun:
    """Execute one confirmed run and persist public tool events."""
    store = store if store is not None else default_agent_store()

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
        code, detail = run_error_code(error, "RUN_EXECUTION_FAILED")
        store.fail(run_id, code, error_detail=detail)
        raise


def continue_run_with_intent(
    run_id: str,
    intent: TravelIntent | Mapping[str, object],
    *,
    store: InMemoryAgentStore | None = None,
) -> AgentRun:
    """Keep the same session/run while advancing discovery into planning."""
    store = store if store is not None else default_agent_store()

    contract = (
        intent
        if isinstance(intent, TravelIntent)
        else TravelIntent.from_mapping(intent)
    )
    if contract.task_mode is not TaskMode.DIRECT_PLAN:
        raise TravelAgentError(
            "a guided discovery selection must continue as DIRECT_PLAN"
        )
    return store.continue_with_intent(run_id, contract)


#: 用户输入证据的固定 id。**不是 uuid**：它必须在两次重建之间稳定，因为
#: PlanVersion 的事件靠 ``fact_id``（``<evidence_id>#<field>``）指向行程窗事实，
#: id 一变引用就全部解析不到（D13：内部寻址方式变了，对外形状不该跟着变）。
USER_INPUT_EVIDENCE_ID = "confirmed-travel-intent"


def trimmed_context(context: Mapping[str, object]) -> dict[str, object]:
    """去掉 context 里的内联证据，只留 ``evidence_refs``。

    `persistence-v2.md` §2.1.1 的 A 收敛。与 PlanVersion 的 context 同一条规则
    ——那是 P4 给 ``plan-NNNN.json`` 定的，本函数把 ``run.json`` 拉齐，并成为两处
    共同的出处（D5：两份并列的名单早晚有人只改一份）。

    证据的权威容器是 ``evidence/current.json``；``result`` 里留一份内联副本，
    两份就可以不一致，而没有地方写着该信哪一份（D19）。
    """

    trimmed = deepcopy(dict(context))
    evidence = trimmed.pop("evidence", None)
    # **必须幂等**：重排链路会把上一版（已裁剪的）context 再传一遍。无条件
    # 覆盖 evidence_refs 会在第二次裁剪时把它清空——那份 context 已经没有
    # 内联证据可数了。清空表现出来是「计划突然指不到任何证据」，而根因是
    # 裁剪被执行了两次，从现场完全看不出来。
    trimmed.setdefault(
        "evidence_refs",
        [
            str(item["evidence_id"])
            for item in (evidence if isinstance(evidence, list) else [])
            if isinstance(item, Mapping)
            and isinstance(item.get("evidence_id"), str)
        ],
    )
    return trimmed


def user_input_evidence(intent: TravelIntent) -> EvidenceItem:
    """把 intent 投影成 ``user_input`` 域证据。

    **它不是采集来的证据，是 intent 的投影**——``_planner_handler`` 一直是现造
    这一条，从来没有哪个采集器产出过它。因此它不必落盘：读取时从
    ``run.intent`` 重建即可，与整个「读时计算」的架构同构，也顺带消灭一份副本
    （`persistence-v2.md` §2.1.1，2026-08-03 裁决）。

    **重建必须稳定**：同一个 intent 两次重建得到同一个 ``evidence_id``，
    因而得到同一批 ``fact_id``。事件的 ``fact_refs`` 指着它们，不稳定就等于
    每次读取都把引用打断一次。
    """

    return EvidenceItem(
        evidence_id=USER_INPUT_EVIDENCE_ID,
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
                {"support": "unknown"},
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
        "context": trimmed_context(context.to_dict()),
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
    intent: TravelIntent | Mapping[str, object] | None = None,
    store: InMemoryAgentStore | None = None,
) -> AgentRun:
    """Create and atomically install a new version on the same run."""
    store = store if store is not None else default_agent_store()

    previous = store.get_run(run_id)
    if (
        previous.status
        not in {
            RunStatus.COMPLETED,
            RunStatus.BLOCKED,
            RunStatus.FAILED,
        }
        or previous.result is None
    ):
        raise TravelAgentError("only a run with a retained result can be revised")
    contract = (
        revision
        if isinstance(revision, Revision)
        else Revision.from_mapping(revision)
    )
    next_intent = (
        intent
        if isinstance(intent, TravelIntent)
        else (
            TravelIntent.from_mapping(intent)
            if intent is not None
            else previous.intent
        )
    )
    store.prepare_revision(
        run_id,
        intent=next_intent,
        revision=contract,
    )
    store.start(run_id)

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
        result = executor(previous.result, contract, emit)
        if not isinstance(result, Mapping):
            raise TravelAgentError("revision executor must return an object")
        store.persist_plan_version(run_id, result)
        return store.complete(run_id, result)
    except Exception as error:
        code, detail = run_error_code(error, "REVISION_EXECUTION_FAILED")
        store.fail(run_id, code, error_detail=detail)
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
        "mode": AgentRuntimeMode.STANDALONE_WEB.value,
        "web_natural_language_enabled": True,
        "model_required": False,
        "model_adapter_loaded": False,
        "display": "本地结构化提取模式",
        "fact_policy": "数字只能来自工具或用户显式输入。",
    }


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TravelAgentError(f"{field_name} must be text or null")
    stripped = value.strip()
    return stripped or None


def _optional_positive_number(
    value: object,
    field_name: str,
) -> float | None:
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or float(value) <= 0
    ):
        raise TravelAgentError(
            f"{field_name} must be a positive number or null"
        )
    return float(value)


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
    "AgentRuntimeMode",
    "AgentRun",
    "AgentSession",
    "default_agent_store",
    "default_runtime_root",
    "reset_default_agent_store",
    "DestinationCollectors",
    "DestinationContext",
    "EvidenceItem",
    "EvidenceStatus",
    "InMemoryAgentStore",
    "NON_BUSINESS_ERRORS",
    "RUN_ERROR_CODES",
    "Revision",
    "RunStatus",
    "TaskMode",
    "TravelAgentError",
    "TravelIntent",
    "continue_run_with_intent",
    "confirm_intent",
    "collect_destination_evidence",
    "create_run",
    "execute_destination_pipeline",
    "execute_run",
    "build_destination_context",
    "progress_contract",
    "revise_run",
    "run_error_code",
    "runtime_status",
    "trimmed_context",
    "user_input_evidence",
    "USER_INPUT_EVIDENCE_ID",
]
