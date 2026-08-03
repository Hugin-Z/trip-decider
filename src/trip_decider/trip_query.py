"""Protocol-neutral queries over the authoritative trip runtime.

This module is the shared query boundary for REST, SSE, and future host
adapters.  It owns Store reads and user-level projections, but never mutates a
run and never creates an alternative runtime.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
import json

from trip_decider.trip_application import (
    default_trip_application_service,
    TripApplicationService,
)
from trip_decider.trip_read_model import (
    _map_payload_contract,
    _planning_draft_read_model,
    _presentation_contract,
)
from trip_decider.planning_input_compiler import (
    PlanningInputCompiler,
    plan_verdict_from_result,
)
from trip_decider.evidence_projection import project_domain, verdict_payload
from trip_decider.travel_agent import (
    default_agent_store,
    InMemoryAgentStore,
    RunStatus,
    TaskMode,
    TravelAgentError,
)


Clock = Callable[[], datetime]


class TripQueryError(ValueError):
    """The requested user-level read model is not available."""


class TripQueryService:
    """Read the single authoritative run/evidence/plan state."""

    def __init__(
        self,
        *,
        store: InMemoryAgentStore | None = None,
        application_service: TripApplicationService | None = None,
        clock: Clock | None = None,
    ) -> None:
        store = store if store is not None else default_agent_store()
        if application_service is None:
            application_service = default_trip_application_service()
        if store is None:
            store = application_service.store
        if application_service.store is not store:
            raise ValueError(
                "query and application services must share one run store"
            )
        self.store = store
        self.application_service = application_service
        # Same injection shape as EvidenceBroker (evidence_broker.py:131-134).
        # Read time drives the freshness axis, so it has to be substitutable
        # for a test to observe two different instants (invariants.md I5).
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def now(self) -> datetime:
        """Return the instant this read is evaluated against."""

        return self._clock()

    def trip(self, run_id: str) -> dict[str, object]:
        """Return the canonical user-level run read model."""

        run = self.store.get_run(run_id)
        session = self.store.get_session(run.session_id)
        run_value = run.to_dict()
        events = self.events(run_id)
        installed = self._current_plan_payload(run_id)
        plan_version = (
            installed.get("plan_version")
            if isinstance(installed, Mapping)
            and isinstance(installed.get("plan_version"), int)
            else None
        )
        read_run_value = deepcopy(run_value)
        current_result = run_value.get("result")
        if isinstance(installed, Mapping) and isinstance(
            installed.get("plan"),
            Mapping,
        ):
            read_run_value["result"] = {
                "plan": deepcopy(installed["plan"]),
                "context": deepcopy(installed.get("context", {})),
            }
        elif isinstance(current_result, Mapping) and (
            "planning_draft" in current_result or "plan" in current_result
        ):
            read_run_value["result"] = None

        read_at = self.now()
        evidence = self.application_service.current_run_evidence(run_id)
        presentation = _presentation_contract(
            read_run_value,
            events,
            evidence=evidence,
            now=read_at,
        )
        presentation["plan_version"] = plan_version
        if not isinstance(installed, Mapping):
            presentation["budget_summary"] = None
        presentation["planning_draft"] = _planning_draft_read_model(
            run_value
        )
        presentation["map_payload"] = _map_payload_contract(
            read_run_value,
            plan_version=plan_version,
            now=read_at,
        )
        response: dict[str, object] = {
            "session": session.to_dict(),
            "run": read_run_value,
            "presentation": presentation,
            "events": events,
        }
        if run.status is RunStatus.RUNNING:
            try:
                action_loop = self.application_service.next_actions(run_id)
                response["action_loop"] = action_loop
                draft_source = {
                    "result": (
                        action_loop.get("result")
                        if isinstance(action_loop, Mapping)
                        else None
                    )
                }
                draft_read_model = _planning_draft_read_model(draft_source)
                if draft_read_model is not None:
                    presentation["planning_draft"] = draft_read_model
            except TravelAgentError:
                pass
        return response

    def trips(self) -> dict[str, object]:
        runs = self.store.list_runs()
        return {
            "runs": [
                {
                    "run_id": run.run_id,
                    "created_at": run.created_at,
                    "status": run.status.value,
                    "task_mode": run.intent.task_mode.value,
                    "origin": run.intent.origin,
                    "destination": run.intent.destination_anchor,
                    "themes": list(run.intent.themes),
                }
                for run in runs
            ],
            "continue_run_id": runs[0].run_id if runs else None,
        }

    def candidates(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        result = run.result
        if isinstance(result, Mapping) and result.get("stage") in {
            "open_discovery",
            "guided_discovery",
        }:
            options = result.get("options")
            if not isinstance(options, list):
                raise TripQueryError("candidate comparison omitted options")
            stage = result.get("stage")
            comparison_completed = True
        else:
            by_id: dict[str, dict[str, object]] = {}
            candidate_events = self.events(run_id)
            for event in candidate_events:
                event_type = str(event.get("event_type", ""))
                if not event_type.endswith(
                    ".candidate.completed"
                ):
                    continue
                details = event.get("details")
                option = (
                    details.get("option")
                    if isinstance(details, Mapping)
                    else None
                )
                destination_id = (
                    option.get("destination_id")
                    if isinstance(option, Mapping)
                    else None
                )
                if isinstance(destination_id, str):
                    by_id[destination_id] = deepcopy(dict(option))
            if not by_id:
                raise TripQueryError(
                    "candidate comparison is not available for this run"
                )
            options = list(by_id.values())
            guided = any(
                str(event.get("event_type", "")).startswith("guided.")
                for event in candidate_events
            )
            stage = (
                "guided_discovery" if guided else "open_discovery"
            )
            comparison_completed = any(
                str(event.get("event_type", "")).endswith(
                    ".comparison.completed"
                )
                for event in candidate_events
            )
        return {
            "run_id": run_id,
            "task_mode": run.intent.task_mode.value,
            "stage": stage,
            "comparison_completed": comparison_completed,
            "selection_required": True,
            "candidates": self._with_recomputed_tokens(run_id, options),
        }

    def _comparison_evidence(self, run_id: str) -> Mapping[str, object]:
        """比较阶段为每个候选落下的证据，按 destination_id / domain 索引。"""

        run_directory = self.store.run_directory(run_id)
        if run_directory is None:
            return {}
        path = run_directory / "evidence" / "guided-comparison.json"
        if not path.is_file():
            return {}
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        destinations = document.get("destinations")
        return destinations if isinstance(destinations, Mapping) else {}

    def _with_recomputed_tokens(
        self,
        run_id: str,
        options: object,
        *,
        now: datetime | None = None,
    ) -> list:
        """按**读取时刻**重算候选卡上的 token。

        事件流里只留 ``evidence_id`` 与结构——token 是 now 的函数，写进
        append-only 的事件流就冻死了（I5），而本方法的调用方在 run.result 被
        后续阶段覆盖后正是从那里重建候选卡。

        两条分支共用它：直读分支拿的是比较阶段的内存产物，重建分支拿的是剥过
        投影的事件副本，重算之后两者必须一致——那正是本改造的判据。
        """

        read_at = now if now is not None else datetime.now(timezone.utc)
        by_destination = self._comparison_evidence(run_id)
        enriched: list = []
        for option in deepcopy(options if isinstance(options, list) else []):
            if not isinstance(option, Mapping):
                enriched.append(option)
                continue
            option = dict(option)
            statuses = option.get("evidence_statuses")
            if not isinstance(statuses, list):
                enriched.append(option)
                continue
            domains = by_destination.get(str(option.get("destination_id")))
            rebuilt: list = []
            for entry in statuses:
                if not isinstance(entry, Mapping):
                    rebuilt.append(entry)
                    continue
                entry = dict(entry)
                domain = str(entry.get("domain") or "")
                item = (
                    domains.get(domain)
                    if isinstance(domains, Mapping)
                    else None
                )
                if isinstance(item, Mapping):
                    entry.update(
                        verdict_payload(
                            project_domain({domain: item}, domain, now=read_at)
                        )
                    )
                rebuilt.append(entry)
            option["evidence_statuses"] = rebuilt
            enriched.append(option)
        return enriched

    def plan_readiness(
        self,
        run_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """这份计划**当前**够不够格呈现（persistence-v2.md §6.2/6.3）。

        与 ``plan_version`` 拆成两个词，因为它们是两种东西：

        * **已写入**：版本号。写下就不变，是永久事实，落盘保证它的结构完整。
        * **当前可用**：读取时刻的结论。同一份 PlanVersion 在容差窗内外给出
          不同答案——证据会过期，而计划是拿证据拼的。

        旧实现把后者也读盘，于是一份三天前判定「可呈现」的计划三天后仍然
        宣称自己可呈现。冻结值不会自己腐烂，它只是停在原地看着世界变化。
        """

        installed = self._current_plan_payload(run_id)
        written = isinstance(installed, Mapping)
        readiness: dict[str, object] = {
            "written": written,
            "plan_version": (
                installed.get("plan_version") if written else None
            ),
            "usable_now": False,
            "planning_state": None,
            "blockers": [],
        }
        if not written:
            return readiness
        run = self.store.get_run(run_id)
        read_at = now if now is not None else datetime.now(timezone.utc)
        # 与 agent_actions.get_next_actions 走**同一个**判定实现。此前两边各
        # compile 一次、各判一次 PARTIAL_READY/PLAN_READY，没有任何东西保证
        # 它们给同一个答案——同一份证据在两个读取面分叉，与「结论和数据不
        # 同步」同族（2026-08-03 裁决：四入口收敛，不分叉）。
        verdict = plan_verdict_from_result(run.result, now=read_at)
        readiness["planning_state"] = verdict.planning_state
        readiness["usable_now"] = verdict.usable_now
        readiness["blockers"] = [dict(item) for item in verdict.blockers]
        return readiness

    def current_plan(self, run_id: str) -> dict[str, object]:
        value = self._current_plan_payload(run_id)
        if value is None:
            raise TripQueryError("current plan does not exist")
        payload = dict(value)
        # 「已写入」的载荷加挂「当前可用」的结论。两者同时给出，调用方就
        # 不必在「有没有」与「能不能用」之间猜。
        payload["readiness"] = self.plan_readiness(run_id)
        return payload

    def current_plan_version(self, run_id: str) -> int | None:
        value = self._current_plan_payload(run_id)
        version = (
            value.get("plan_version")
            if isinstance(value, Mapping)
            else None
        )
        return (
            version
            if isinstance(version, int) and not isinstance(version, bool)
            else None
        )

    def map_payload(self, run_id: str) -> dict[str, object]:
        presentation = self.trip(run_id).get("presentation")
        payload = (
            presentation.get("map_payload")
            if isinstance(presentation, Mapping)
            else None
        )
        return deepcopy(dict(payload)) if isinstance(payload, Mapping) else {}

    def missing_information(self, run_id: str) -> dict[str, object]:
        presentation = self.trip(run_id).get("presentation")
        draft = (
            presentation.get("planning_draft")
            if isinstance(presentation, Mapping)
            else None
        )
        return deepcopy(dict(draft)) if isinstance(draft, Mapping) else {}

    def audit_result(self, run_id: str) -> dict[str, object]:
        run = self.store.get_run(run_id)
        result = run.result
        if (
            run.intent.task_mode is not TaskMode.PLAN_AUDIT
            or not isinstance(result, Mapping)
            or result.get("stage") != "plan_audit"
        ):
            raise TripQueryError("audit result is not available for this run")
        return deepcopy(dict(result))

    def events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[dict[str, object]]:
        run = self.store.get_run(run_id)
        return [
            event.to_dict()
            for event in self.store.events_after(
                run.session_id,
                after_sequence,
            )
            if event.run_id == run_id
        ]

    def wait_for_events(
        self,
        run_id: str,
        *,
        after_sequence: int,
        timeout: float,
    ) -> dict[str, object]:
        run = self.store.get_run(run_id)
        events = [
            event.to_dict()
            for event in self.store.wait_for_events(
                run.session_id,
                after_sequence,
                timeout,
            )
            if event.run_id == run_id
        ]
        current = self.store.get_run(run_id)
        return {
            "run_id": run_id,
            "session_id": run.session_id,
            "events": events,
            "terminal": current.status
            in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.BLOCKED},
            "status": current.status.value,
        }

    def _current_plan_payload(
        self,
        run_id: str,
    ) -> dict[str, object] | None:
        run_directory = self.store.run_directory(run_id)
        if run_directory is None:
            return None
        path = run_directory / "plan-version.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(value, Mapping):
            return None
        plan = value.get("plan")
        # 只验结构：planning_state / displayable 已不再落盘（会随 now 变，
        # 写进盘就是 I5 违反）。「这份计划当前够不够格呈现」的准入语义重建
        # 属 P4-c——它要把「已写入」与「当前可用」拆成两个词，本阶段不动。
        days = plan.get("days") if isinstance(plan, Mapping) else None
        if (
            not isinstance(plan, Mapping)
            or plan.get("artifact_kind") != "PlanVersion"
            or not isinstance(days, list)
            or not days
        ):
            return None
        return deepcopy(dict(value))


# 「当前可用」的判据已收敛到
# `planning_input_compiler.INSTALLABLE_STATES`（单一出处）。本模块此前在这里
# 留了一份同值的副本，`agent_actions` 里还有第三份内联字面量——三份都写着同两
# 个取值，但没有任何东西保证它们一起改（D5）。


_DEFAULT_QUERY: TripQueryService | None = None


def default_trip_query_service() -> TripQueryService:
    """进程级默认查询服务，首次调用时才构造（invariants.md I11）。"""

    global _DEFAULT_QUERY
    if _DEFAULT_QUERY is None:
        _DEFAULT_QUERY = TripQueryService()
    return _DEFAULT_QUERY


def reset_default_trip_query_service() -> None:
    """丢弃已构造的默认查询服务。仅供测试隔离使用。"""

    global _DEFAULT_QUERY
    _DEFAULT_QUERY = None


__all__ = [
    "DEFAULT_TRIP_QUERY_SERVICE",
    "TripQueryError",
    "TripQueryService",
]
