"""Headless, protocol-neutral MCP-facing adapter.

This module intentionally knows only the application command boundary and the
query/read-model boundary.  It does not import HTTP, the run store, projection
helpers, planners, or provider tools.
"""

from __future__ import annotations

from collections.abc import Mapping
import time
from uuid import uuid4

from trip_decider.trip_application import (
    TripApplicationError,
    TripApplicationService,
)
from trip_decider.itinerary_verification import verify_railway_assertions
from trip_decider.trip_query import TripQueryError, TripQueryService
from trip_decider.travel_agent import RETRYABLE_BLOCK_CODES, TravelAgentError


class TripMCPError(ValueError):
    """A stable host-facing trip tool error.

    错误消息里**总是带下一步**。宿主实测的试错有一半花在猜「下一步调什么」上：
    错误只回一句业务描述，宿主拿不到「该调哪个工具、缺哪个字段」，于是靠试。

    ``next_call`` 既进结构化字段，也拼进 ``str(self)``——MCP 把异常渲染成文本，
    只放字段宿主看不见。
    """

    def __init__(
        self,
        message: str,
        *,
        next_call: str | None = None,
    ) -> None:
        self.next_call = next_call
        super().__init__(
            f"{message}｜下一步：{next_call}" if next_call else message
        )


#: 一次 `verify_itinerary` 最多核多少条断言。每条最坏一次时刻表查询加一次票价
#: 查询；12 条是在 I13 上界内留足余量的保守值。超了要求分批，**不截断**——
#: 截断会让宿主以为整份都核过了。
MAX_VERIFIED_ASSERTIONS = 12

_VERIFY_HINT = (
    'verify_itinerary(assertions=[{"train_code": "G1234", '
    '"origin_station": "<出发站全称>", "destination_station": "<到达站全称>", '
    '"departure_at": "2026-08-11T12:40", "arrival_at": "2026-08-11T16:28", '
    '"price_cny": 149.0}])'
)

#: 一次 MCP 工具调用允许占用的墙钟上限（秒）。见 invariants.md I13。
#: 宿主的超时线是 60 秒级，取 45 留出传输与序列化的余量。**这不是目标值是上限**：
#: 正常调用都在 1 秒内，只有 `advance_trip_task` 会主动等到 `wait_seconds`。
MCP_CALL_BUDGET_SECONDS = 45.0

#: `advance_trip_task` 里同步推进动作循环的预算。真正的采集在后台线程里，
#: 这一脚只负责把循环踢动。加上 `wait_seconds`（≤30）仍远低于上面的上限。
_SYNCHRONOUS_DRIVE_BUDGET_SECONDS = 5.0

#: 域 → 该域的手工提交长什么样。**只用于错误提示**，不参与校验——校验的唯一
#: 出处是 `agent_actions` 的提交门（railway 的必填集又从
#: `itinerary_planner.RAIL_EVENT_REQUIRED_TRAIN_FIELDS` 派生）。这里再抄一份
#: 校验逻辑就又是两张表（D2）。
_EVIDENCE_HINT = (
    'submit_trip_evidence(run_id, evidence={"action_id": "railway", '
    '"value": {...}, "sources": [{"provider": "中国铁路12306", '
    '"retrieved_at": "2026-08-04T10:00:00+08:00"}]})'
)


def _normalize_host_evidence(evidence: Mapping[str, object]) -> dict[str, object]:
    """把宿主提交补全成内核要的形状。**只补能推出来的，不编来源。**

    宿主实测里这一处试错最多。内核的 `EvidenceItem.from_mapping` 要六个键，
    其中三个宿主根本不该被问：

    * ``domain`` —— 内核随后就断言 ``item.domain == action_id``，两者恒等。
      问两遍是纯重复，还给了填错的机会（D19：两份可以不一致）。这里从
      ``action_id`` 派生。
    * ``evidence_id`` —— 宿主得凭空发明一个字符串。它只需要在 run 内稳定，
      服务端生成即可。宿主自己给了就尊重（重复提交同一 id 是幂等的）。
    * ``status`` —— 给了 ``value`` 就是 ``sourced``。宿主要报缺失/冲突时仍可
      显式写，显式优先。

    ``sources`` **不补默认值**：来源是证据之所以是证据的全部理由，编一个出来
    就是伪造出处。缺了就报错，并在错误里说清该给什么。
    """

    value = dict(evidence)
    action_id = value.get("action_id")
    if not isinstance(action_id, str) or not action_id.strip():
        raise TripMCPError(
            "evidence 缺少 action_id（railway / web / map 之一）",
            next_call=_EVIDENCE_HINT,
        )
    action_id = action_id.strip()
    declared_domain = value.get("domain")
    if (
        isinstance(declared_domain, str)
        and declared_domain.strip()
        and declared_domain.strip() != action_id
    ):
        raise TripMCPError(
            f"domain={declared_domain!r} 与 action_id={action_id!r} 不一致。"
            "domain 可以不填，它总是等于 action_id",
            next_call=_EVIDENCE_HINT,
        )
    value["domain"] = action_id
    if not isinstance(value.get("evidence_id"), str) or not str(
        value.get("evidence_id")
    ).strip():
        value["evidence_id"] = f"{action_id}-user-supply-{uuid4()}"
    if not isinstance(value.get("status"), str) or not str(
        value.get("status")
    ).strip():
        value["status"] = "sourced" if value.get("value") is not None else "missing"
    if value["status"] == "sourced" and not value.get("sources"):
        raise TripMCPError(
            "sourced 证据必须带 sources（至少一条 provider + retrieved_at）。"
            "这一项不会自动补——来源是证据之所以成立的理由，不能由服务端代填",
            next_call=_EVIDENCE_HINT,
        )
    return value


class TripMCPAdapter:
    """User-goal operations over the one authoritative trip runtime."""

    _READ_VIEWS = {
        "overview",
        "candidates",
        "plan",
        "missing",
        "map",
        "audit",
    }
    _CHECKPOINT_STATUSES = {
        "AWAITING_CONFIRMATION",
        "COMPLETED",
        "BLOCKED",
        "FAILED",
    }

    def __init__(
        self,
        application: TripApplicationService,
        query: TripQueryService,
    ) -> None:
        if query.application_service is not application:
            raise ValueError(
                "MCP application and query boundaries must be the same bundle"
            )
        self._application = application
        self._query = query

    def create_trip_task(
        self,
        intent: Mapping[str, object],
    ) -> dict[str, object]:
        """Create a durable run and return its canonical read model."""

        return self._guard(
            lambda: self._query.trip(
                self._application.create_trip(intent).run_id
            )
        )

    def confirm_trip_intent(
        self,
        run_id: str,
        intent: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Confirm, or explicitly correct and confirm, one run's intent."""

        def operation() -> dict[str, object]:
            # 重复确认幂等。此前第二次调用抛「run is not awaiting confirmation」
            # ——而宿主重复确认的典型原因恰恰是**上一次没看懂结果**：它拿到一个
            # 不熟悉的返回体，保守地又确认一次，然后收到一句听起来像出错的话，
            # 于是开始试别的调用。已经确认过、又没有要改的条件，就是已达成状态，
            # 回当前视图即可。
            #
            # 带 intent 的重复调用**不吞**：那是「改条件」，改不了必须说。
            current = self._query.trip(run_id)
            if intent is None and _run_status(current) != "AWAITING_CONFIRMATION":
                return current
            return self._query.trip(
                self._application.confirm_trip(run_id, intent).run_id
            )

        return self._guard(
            operation,
            next_call=(
                "advance_trip_task(run_id) 继续推进；"
                "要改条件用 confirm_trip_intent(run_id, intent={...})"
            ),
        )

    def advance_trip_task(
        self,
        run_id: str,
        *,
        wait_seconds: float = 10.0,
    ) -> dict[str, object]:
        """Advance until the next durable host/user checkpoint or timeout."""

        if (
            not isinstance(wait_seconds, (int, float))
            or isinstance(wait_seconds, bool)
            or not 0 <= float(wait_seconds) <= 30
        ):
            raise TripMCPError("wait_seconds must be between 0 and 30")

        def operation() -> dict[str, object]:
            before = self._query.trip(run_id)
            status = _run_status(before)
            if status not in self._CHECKPOINT_STATUSES or _is_retryable_block(
                before
            ):
                # 同步推进只给一点点预算。真正的采集在后台线程里跑，本次调用
                # 只负责「踢一脚 + 在 wait_seconds 内看看到没到检查点」。
                # 不限的话这里能自己跑满 30 秒，再叠上下面的轮询等待，
                # 一次工具调用就逼近宿主的超时线（I13）。
                self._application.execute_trip(
                    run_id,
                    drive_budget_seconds=_SYNCHRONOUS_DRIVE_BUDGET_SECONDS,
                )
            elif status == "COMPLETED":
                # A completed discovery run is already waiting for selection;
                # a completed plan/audit run is already a stable checkpoint.
                return self._checkpoint(run_id, before)
            elif status in {"BLOCKED", "FAILED"}:
                return self._checkpoint(run_id, before)
            else:
                return self._checkpoint(run_id, before)

            deadline = time.monotonic() + float(wait_seconds)
            current = self._query.trip(run_id)
            while (
                _run_status(current) not in self._CHECKPOINT_STATUSES
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
                current = self._query.trip(run_id)
            return self._checkpoint(run_id, current)

        return self._guard(operation)

    def read_trip(
        self,
        run_id: str,
        *,
        view: str = "overview",
    ) -> dict[str, object]:
        """Read one canonical query view without transport-specific projection."""

        if view not in self._READ_VIEWS:
            raise TripMCPError(
                "view must be overview, candidates, plan, missing, map, or audit"
            )
        readers = {
            "overview": self._query.trip,
            "candidates": self._query.candidates,
            "plan": self._query.current_plan,
            "missing": self._query.missing_information,
            "map": self._query.map_payload,
            "audit": self._query.audit_result,
        }
        return self._guard(lambda: readers[view](run_id))

    def render_trip_candidates(
        self,
        run_id: str,
    ) -> dict[str, object]:
        """Return the canonical candidate view in an MCP App envelope."""

        return self._guard(
            lambda: {
                "view": "candidates",
                "run_id": run_id,
                "current_version": None,
                "candidates": self._query.candidates(run_id),
            }
        )

    def render_trip_plan(
        self,
        run_id: str,
    ) -> dict[str, object]:
        """Return canonical trip and plan views in an MCP App envelope."""

        def operation() -> dict[str, object]:
            plan = self._query.current_plan(run_id)
            version = plan.get("plan_version")
            return {
                "view": "plan",
                "run_id": run_id,
                "current_version": version,
                "trip": self._query.trip(run_id),
                "plan": plan,
            }

        return self._guard(operation)

    def select_trip_candidate(
        self,
        run_id: str,
        candidate_id: str,
    ) -> dict[str, object]:
        """Select a compared destination while retaining the same run."""

        def operation() -> dict[str, object]:
            outcome = self._application.select_candidate(
                run_id,
                candidate_id,
            )
            return _with_outcome(self._query.trip(run_id), outcome)

        return self._guard(operation)

    def submit_trip_evidence(
        self,
        run_id: str,
        evidence: Mapping[str, object],
    ) -> dict[str, object]:
        """Submit explicit sourced/missing/conflicting evidence to one run."""

        normalized = _normalize_host_evidence(evidence)

        def operation() -> dict[str, object]:
            outcome = self._application.submit_run_evidence(
                run_id,
                normalized,
            )
            return _with_outcome(self._query.trip(run_id), outcome)

        return self._guard(operation, next_call=_EVIDENCE_HINT)

    def revise_trip_plan(
        self,
        run_id: str,
        revision: Mapping[str, object],
    ) -> dict[str, object]:
        """Atomically install a revised plan version on the same run."""

        def operation() -> dict[str, object]:
            outcome = self._application.revise_trip(
                run_id,
                revision=revision,
            )
            return {
                "trip": self._query.trip(outcome.run_id),
                "plan": self._query.current_plan(outcome.run_id),
            }

        return self._guard(operation)

    def audit_trip_plan(
        self,
        *,
        run_id: str | None = None,
        plan: Mapping[str, object] | None = None,
        content: str | None = None,
    ) -> dict[str, object]:
        """Audit an existing Plan or guide without invoking normal planning."""

        def operation() -> dict[str, object]:
            active_run_id = run_id
            if active_run_id is None:
                active_run_id = self._application.create_trip(
                    {"task_mode": "PLAN_AUDIT"}
                ).run_id
                self._application.confirm_trip(active_run_id)
            self._application.audit_trip(
                active_run_id,
                plan=plan,
                content=content,
            )
            return {
                "trip": self._query.trip(active_run_id),
                "audit": self._query.audit_result(active_run_id),
            }

        return self._guard(operation)

    def _checkpoint(
        self,
        run_id: str,
        trip: Mapping[str, object],
    ) -> dict[str, object]:
        status = _run_status(trip)
        checkpoint = _checkpoint_name(trip)
        response: dict[str, object] = {
            "trip": dict(trip),
            "checkpoint": checkpoint,
        }
        if status == "COMPLETED":
            try:
                response["plan"] = self._query.current_plan(run_id)
            except TripQueryError:
                try:
                    response["candidates"] = self._query.candidates(run_id)
                except TripQueryError:
                    pass
        if status in {"RUNNING", "BLOCKED", "FAILED"}:
            response["missing"] = self._query.missing_information(run_id)
        # 每个检查点都自带下一步。宿主实测的试错有一半是在猜「下一步调什么」：
        # checkpoint 名（NEED_INTENT_CONFIRMATION 之类）说的是**现在在哪**，
        # 不是**接下来做什么**，两者之间的映射此前只存在于代码里。
        response["next_call"] = _next_call(
            checkpoint,
            run_id,
            trip,
            recovery=self._recovery(run_id, status),
        )
        return response

    def _recovery(self, run_id: str, status: str) -> object:
        """阻塞态的出路清单。

        动作循环快照才有它（`agent_actions._blocked_recovery` 按 error_code 与
        task_mode 算），而 `trip_query.trip()` 只在 RUNNING 时挂 action_loop——
        阻塞态恰恰是最需要出路的时候，却拿不到。这里为阻塞态显式取一次。
        """

        if status not in {"BLOCKED", "FAILED"}:
            return None
        try:
            snapshot = self._application.next_actions(run_id)
        except (TripApplicationError, TravelAgentError):
            return None
        return snapshot.get("recovery") if isinstance(snapshot, Mapping) else None

    def verify_itinerary(
        self,
        assertions: object,
    ) -> dict[str, object]:
        """逐条核验别处排好的行程。无状态，不建 run。"""

        if not isinstance(assertions, list):
            raise TripMCPError(
                "assertions 必须是断言列表",
                next_call=_VERIFY_HINT,
            )
        if len(assertions) > MAX_VERIFIED_ASSERTIONS:
            # 一次核太多会撞 I13 的上界——每条断言最坏要一次时刻表查询加一次
            # 票价查询。分批而不是偷偷截断：截断会让宿主以为全核过了。
            raise TripMCPError(
                f"一次最多核 {MAX_VERIFIED_ASSERTIONS} 条，本次收到 "
                f"{len(assertions)} 条。请分批提交——"
                "分批是为了每次调用都能在宿主超时前返回",
                next_call=(
                    f"verify_itinerary(assertions=[前 {MAX_VERIFIED_ASSERTIONS} 条])"
                    "，然后对余下的再调一次"
                ),
            )
        try:
            return verify_railway_assertions(assertions)
        except ValueError as error:
            raise TripMCPError(str(error), next_call=_VERIFY_HINT) from None

    @staticmethod
    def _guard(
        operation: object,
        *,
        next_call: str | None = None,
    ) -> dict[str, object]:
        try:
            result = operation()
        except (TripApplicationError, TripQueryError, TravelAgentError) as error:
            raise TripMCPError(str(error), next_call=next_call) from None
        if not isinstance(result, dict):
            raise TripMCPError("trip service returned a non-object result")
        return result


def _is_retryable_block(value: Mapping[str, object]) -> bool:
    """这个 BLOCKED 是不是「还能再推一次」的那种。

    ``BLOCKED`` 一直被当作终局检查点，于是 ``advance_trip_task`` 在阻塞态直接
    回快照、不再调 ``execute_trip``。应用层现在允许重试候选比较，宿主面却不放行
    ——那样 ``recovery`` 里写的 ``retry_comparison`` 就是一条**声明了却调不通**
    的出路，比不写更坏（D14：存在性不冒充可用性）。

    判据取自 ``travel_agent.RETRYABLE_BLOCK_CODES``，不在这里另抄一份码字面量
    （D5：名单与按名单操作的函数必须同居）。
    """

    run = value.get("run")
    if not isinstance(run, Mapping):
        return False
    return (
        str(run.get("status")) == "BLOCKED"
        and str(run.get("error_code")) in RETRYABLE_BLOCK_CODES
    )


def _run_status(value: Mapping[str, object]) -> str:
    run = value.get("run")
    status = run.get("status") if isinstance(run, Mapping) else None
    return str(status) if status is not None else "UNKNOWN"


def _checkpoint_name(value: Mapping[str, object]) -> str:
    run = value.get("run")
    if not isinstance(run, Mapping):
        return "UNKNOWN"
    status = str(run.get("status", "UNKNOWN"))
    result = run.get("result")
    stage = result.get("stage") if isinstance(result, Mapping) else None
    if status == "AWAITING_CONFIRMATION":
        return "NEED_INTENT_CONFIRMATION"
    if status == "RUNNING":
        return "RUNNING"
    if status in {"BLOCKED", "FAILED"}:
        return "NEED_USER_INPUT_OR_EVIDENCE"
    if stage in {"open_discovery", "guided_discovery"}:
        return "CANDIDATES_READY"
    if stage == "plan_audit":
        return "AUDIT_READY"
    if status == "COMPLETED":
        return "PLAN_OR_PARTIAL_RESULT_READY"
    return status


def _next_call(
    checkpoint: str,
    run_id: str,
    trip: Mapping[str, object],
    *,
    recovery: object = None,
) -> dict[str, object]:
    """检查点 → 下一步调什么。

    只给**真的能调通**的入口（D14）。阻塞态优先透传 run 自己算出来的
    ``recovery``——那是按具体阻塞原因给的，比按检查点名给的粗粒度建议准；
    两者都写就会有两份可以不一致的指引（D19）。

    ``recovery`` 有两个来源，都是同一份语义：动作循环快照（DIRECT_PLAN 的阻塞）
    与 ``run.result``（比较失败）。调用方给哪个用哪个，都没有才落到按检查点名
    的通用建议。
    """

    run = trip.get("run") if isinstance(trip.get("run"), Mapping) else {}
    if not (isinstance(recovery, list) and recovery):
        result = run.get("result") if isinstance(run, Mapping) else None
        recovery = (
            result.get("recovery") if isinstance(result, Mapping) else None
        )
    if isinstance(recovery, list) and recovery:
        return {
            "reason": str(run.get("error_code") or checkpoint),
            "options": [
                dict(item) for item in recovery if isinstance(item, Mapping)
            ],
        }
    guidance = {
        "NEED_INTENT_CONFIRMATION": (
            "confirm_trip_intent",
            "确认需求。条件已经齐了就只传 run_id；要改条件才传 intent。",
        ),
        "RUNNING": (
            "advance_trip_task",
            "继续推进，直到下一个检查点。",
        ),
        "CANDIDATES_READY": (
            "select_trip_candidate",
            "从 show_trip_candidates 的列表里挑一个 destination_id 传进来。",
        ),
        "NEED_USER_INPUT_OR_EVIDENCE": (
            "submit_trip_evidence",
            "补一条证据后自动续跑；缺哪个域看本响应的 missing 字段。",
        ),
        "PLAN_OR_PARTIAL_RESULT_READY": (
            "show_trip_plan",
            "展示行程；要改用 revise_trip_plan。",
        ),
        "AUDIT_READY": (
            "read_trip",
            'view="audit" 取审计结论。',
        ),
    }.get(checkpoint)
    if guidance is None:
        return {"reason": checkpoint, "options": []}
    tool, detail = guidance
    return {
        "reason": checkpoint,
        "options": [
            {
                "kind": "continue",
                "entrypoint": tool,
                "arguments": {"run_id": run_id},
                "detail": detail,
            }
        ],
    }


def _with_outcome(
    trip: dict[str, object],
    outcome: object,
) -> dict[str, object]:
    action_loop = getattr(outcome, "action_loop", None)
    return {
        "trip": trip,
        "accepted": bool(getattr(outcome, "accepted", False)),
        "action_loop": dict(action_loop) if isinstance(action_loop, Mapping) else None,
    }


__all__ = ["TripMCPAdapter", "TripMCPError"]
