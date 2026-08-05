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
import time

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
from trip_decider.evidence_projection import (
    REFETCH_BUDGET_SECONDS,
    project_domain,
    resolve_stale_evidence,
    verdict_payload,
)
from trip_decider.travel_agent import (
    default_agent_store,
    InMemoryAgentStore,
    RunStatus,
    TaskMode,
    TravelAgentError,
    user_input_evidence,
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
        refetcher: object = None,
        live_refetch: bool = False,
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
        # 读时同步重采的采集器，由调用方注入（默认 None = 不重采）。
        # 采集器住在上层模块，读取层导入它们会成环，也会把只读的读取层
        # 变成能自己发网络请求的东西——与内核「策略由调用方注入」同理。
        self._refetcher = refetcher
        # 生产路径按 run 绑定采集器（解析步只传 (domain, item)，
        # 采集器要 intent）。测试注入的 `refetcher` 优先，便于
        # 用假采集器观察行为。
        self._live_refetch = live_refetch

    def _compile_evidence(
        self,
        run_id: str,
        run: object,
    ) -> dict:
        """编译输入的证据：容器 B + 重建的 user_input。

        A（`run.result["context"]["evidence"]`）已收敛，不再是证据来源
        （`persistence-v2.md` §2.1.1）。`user_input` 不在 B 里——它是 intent 的
        投影不是采集证据，按 `travel_agent.user_input_evidence` 重建，id 稳定。
        """

        evidence = dict(
            self.application_service.current_run_evidence(run_id)
        )
        intent = getattr(run, "intent", None)
        if intent is not None:
            evidence["user_input"] = user_input_evidence(intent).to_dict()
        return evidence

    def _refetcher_for(self, run_id: str):
        """本次读取要用的重采器。``None`` = 不重采。"""

        if self._refetcher is not None:
            return self._refetcher
        if not self._live_refetch:
            return None
        return self.application_service.live_refetcher(run_id)

    def _flush_pending(
        self,
        run_id: str,
        pending: object,
    ) -> None:
        """把重采的待写回标记交给应用层落盘。

        读取层自己不写盘：那会破它的只读契约，也会让两次读取产生不同的文件
        内容（I5）。写入走应用层——它本来就是唯一的写入协调者。

        落盘之后节流才真正生效：失败那一支写的是
        ``refresh_failure.attempted_at``，节流的状态存在它上面。
        """

        if not pending:
            return
        self.application_service.record_refetched_evidence(run_id, pending)

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
        # 解析步的**装载点三**：evidence/current.json（动作循环维护的证据表）。
        # 它与 run.result["context"]["evidence"] 是两份独立落盘的副本，写回只对
        # 这一份生效——两份的权威归属见 freshness-policy.md §5.2.3。
        trip_refetcher = self._refetcher_for(run_id)
        if trip_refetcher is not None:
            resolved = resolve_stale_evidence(
                dict(evidence),
                now=read_at,
                refetcher=trip_refetcher,
            )
            evidence = resolved.items
            self._flush_pending(run_id, resolved.pending_writes)
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
            # 只在**有计划可展示**时供给证据。上面刻意把未安装草稿的 result 置
            # 空，地图因此不该有标记；无条件注入容器 B 会让证据里的住宿片区
            # 在「草稿未安装」的状态下冒出来——那是行为变更，不在 A 收敛的
            # 预期变化集里（D8：表外的即停）。
            evidence=(
                evidence
                if isinstance(read_run_value.get("result"), Mapping)
                else None
            ),
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
            # 「有比较阶段的 result」不等于「比较完成了」。旧代码在这里无条件
            # 写 True，于是比较抛异常之后读取层仍报 comparison_completed=True
            # + candidates=[]，宿主据此以为是「比较完了，一个都不可行」。那是
            # 一句假话：比较根本没跑完（D14 的同类——存在性冒充可用性）。
            comparison_completed = not bool(result.get("comparison_failed"))
            fallback = result.get("fallback_options")
            if isinstance(fallback, list):
                # 退路卡自带 comparison_status=not_compared，与比较出来的候选
                # 在同一个列表里可区分。
                options = [*options, *fallback]
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
        # 解析步的**装载点二**：guided-comparison 容器（按目的地、再按域的
        # mapping）。与装载点一走**同一个** resolve_stale_evidence——容器有两种
        # 是落盘历史造成的事实，逻辑必须只有一份（D5/D20）。这里只有容器形状
        # 和写回位置是本地知识。
        #
        # 预算按整次读取算，不是按目的地：候选比较有 N 个目的地，逐个给 8 秒
        # 会把一次页面刷新拖成 N×8 秒。
        candidates_refetcher = self._refetcher_for(run_id)
        if candidates_refetcher is not None:
            deadline = time.monotonic() + REFETCH_BUDGET_SECONDS
            refreshed: dict[str, Mapping[str, object]] = {}
            pending: list[tuple[str, Mapping[str, object]]] = []
            for destination_id, domains in by_destination.items():
                if not isinstance(domains, Mapping):
                    refreshed[destination_id] = domains
                    continue
                resolved = resolve_stale_evidence(
                    {
                        domain: item
                        for domain, item in domains.items()
                        if isinstance(item, Mapping)
                    },
                    now=read_at,
                    refetcher=candidates_refetcher,
                    budget_seconds=max(0.0, deadline - time.monotonic()),
                )
                refreshed[destination_id] = {**dict(domains), **resolved.items}
                pending.extend(resolved.pending_writes)
            by_destination = refreshed
            self._flush_pending(run_id, pending)
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
        verdict = plan_verdict_from_result(
            run.result,
            now=read_at,
            evidence=self._compile_evidence(run_id, run),
            refetcher=self._refetcher_for(run_id),
        )
        # 读取层不落盘：待写回交给应用层——唯一的写入协调者（§5.2.2）。
        self._flush_pending(run_id, verdict.pending_writes)
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
        """还缺什么，**以及每一项要按什么形状补**。

        第六次实测（2026-08-05）：`submit_trip_evidence` 的描述白纸黑字写着
        「可以先 read_trip(view="missing") 看当前待补动作的 required_fields /
        optional_fields」，而这个视图当时只回 planning_draft——里面一个
        `required_fields` 都没有。宿主连交三轮、拿不到一个字段名，只能止损。

        **系统要求证据却不公布证据 schema，是这个产品的自我违背。** 待补动作
        本来就带着 `required_fields` / `optional_fields` / `example`，它们在
        动作快照里，只是从没有接到这个视图上。这里补上——不新造一份 schema
        （那就是第二张表，D2），而是把动作快照里已有的那份原样带出来。
        """

        presentation = self.trip(run_id).get("presentation")
        draft = (
            presentation.get("planning_draft")
            if isinstance(presentation, Mapping)
            else None
        )
        view = deepcopy(dict(draft)) if isinstance(draft, Mapping) else {}
        view["pending_actions"] = self._pending_action_schemas(run_id)
        return view

    def _pending_action_schemas(self, run_id: str) -> list[dict[str, object]]:
        """待补动作连同它们各自声明的字段清单。"""

        try:
            snapshot = self.application_service.next_actions(run_id)
        except (TravelAgentError, TripQueryError):
            return []
        # 阻塞态的 `actions` 恒为空（没有可立刻派发的动作），但它另带一份
        # `pending_actions`——「还缺什么」与「能不能推」是两个问题。
        actions = snapshot.get("actions") or snapshot.get("pending_actions")
        if not isinstance(actions, list):
            return []
        pending: list[dict[str, object]] = []
        for action in actions:
            if not isinstance(action, Mapping):
                continue
            entry: dict[str, object] = {
                "action_id": action.get("action_id"),
                "submit_action_id": action.get(
                    "submit_action_id", action.get("action_id")
                ),
                "title": action.get("title"),
                "required_fields": list(action.get("required_fields") or []),
                "optional_fields": list(action.get("optional_fields") or []),
            }
            if action.get("example"):
                entry["example"] = deepcopy(action["example"])
            pending.append(entry)
        return pending

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
