"""Headless, protocol-neutral MCP-facing adapter.

This module intentionally knows only the application command boundary and the
query/read-model boundary.  It does not import HTTP, the run store, planners,
or provider tools.  MCP App enrichment may consume the existing evidence
projection, but never derives an evidence token itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import time
from uuid import uuid4

from trip_decider.trip_application import (
    TripApplicationError,
    TripApplicationService,
)
from trip_decider.agent_actions import (
    MAP_SEGMENT_EXAMPLE,
    RAILWAY_MANUAL_EXAMPLE,
    WEB_EXAMPLE,
)
from trip_decider.evidence_projection import usable_fact_values
from trip_decider.itinerary_verification import (
    split_by_shape,
    summarize_dicts,
    verification_token,
    verify_checkable_incrementally,
)
from trip_decider.verification_registry import (
    VerificationCapacityError,
    VerificationRegistry,
)
from trip_decider.trip_query import TripQueryError, TripQueryService
from trip_decider.travel_agent import RETRYABLE_BLOCK_CODES, TravelAgentError


#: 显式表示「这条错误确实没有下一步可给」。传它是一个决定，会被守卫看见；
#: 省略 `next_call` 则是语法错误。两者的区别就是 D20 的全部意思。
NO_NEXT_CALL = "no_further_action"


class TripMCPError(ValueError):
    """A stable host-facing trip tool error.

    错误消息里**总是带下一步**。宿主实测的试错有一半花在猜「下一步调什么」上：
    错误只回一句业务描述，宿主拿不到「该调哪个工具、缺哪个字段」，于是靠试。

    ``next_call`` 既进结构化字段，也拼进 ``str(self)``——MCP 把异常渲染成文本，
    只放字段宿主看不见。
    """

    #: ``next_call`` **没有默认值**，这是有意的（D20：把纪律做成形状）。
    #: 上一轮的守卫按「当时的错误清单」逐条核对，于是新增的错误类型漏网——
    #: 宿主拿到一句没有下一步的 "action loop was not started"，盲试了好几次。
    #: 按清单核对的守卫总会漏掉清单之后新增的东西；让**省略在语法上不可能**
    #: 才是真的守住。确实无路可走时显式传 ``NO_NEXT_CALL``，那是一个决定，
    #: 不是一次遗忘。
    def __init__(
        self,
        message: str,
        *,
        next_call: str,
    ) -> None:
        if not isinstance(next_call, str) or not next_call.strip():
            raise ValueError(
                "TripMCPError 必须带 next_call；真的无路可走就传 NO_NEXT_CALL"
            )
        self.next_call = next_call
        super().__init__(
            message
            if next_call == NO_NEXT_CALL
            else f"{message}｜下一步：{next_call}"
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
_EVIDENCE_HINT_BY_DOMAIN = {
    domain: "submit_trip_evidence(run_id, evidence="
    + json.dumps(example, ensure_ascii=False)
    + ")"
    for domain, example in {
        "railway": RAILWAY_MANUAL_EXAMPLE,
        "map": MAP_SEGMENT_EXAMPLE,
        "web": WEB_EXAMPLE,
    }.items()
}

#: 不知道宿主想提交哪个域时的通用提示。**先看 missing** 比猜一个域有用。
_EVIDENCE_HINT = (
    'read_trip(run_id, view="missing") 看当前待补的动作与它的 '
    "required_fields / optional_fields，再按那份清单提交"
)


def _evidence_hint(action_id: object) -> str:
    """按宿主**实际在提交的那个域**给示例。

    此前不论提交什么域，报错都贴一条 railway 的示例——宿主提交班车证据被拒后
    拿到的是「铁路怎么填」，等于没提示。
    """

    if isinstance(action_id, str):
        specific = _EVIDENCE_HINT_BY_DOMAIN.get(action_id.strip())
        if specific is not None:
            return specific
    return _EVIDENCE_HINT


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
            next_call=_evidence_hint(action_id),
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
            next_call=_evidence_hint(action_id),
        )
    if action_id == "map":
        value["value"] = _sweeten_local_transit(value.get("value"))
    return value


def _sweeten_local_transit(value: object) -> object:
    """接住宿主更自然的写法，**只做形状搬运，不补任何事实**。

    宿主第三次实测手写班车证据时用的是「线路」词汇——``line`` / ``board_at`` /
    ``alight_at`` 直接摊在段上，``fare`` 是个裸数字。采集器产出的却是嵌套的
    ``services[]`` 加 ``fare.{status,amount_cny}``。两种写法说的是同一件事，
    要求宿主背下后者没有任何收益。

    **不补 from/to/duration_seconds**：那三个是「这一段到底是从哪到哪、要多久」，
    编不出来也不该编——缺了就让提交门如实拒绝并说明（I12）。这里只翻译措辞，
    不制造事实。
    """

    if not isinstance(value, Mapping):
        return value
    routes = value.get("local_transit")
    if not isinstance(routes, list):
        return value
    sweetened: list[object] = []
    for route in routes:
        if not isinstance(route, Mapping):
            sweetened.append(route)
            continue
        item = dict(route)
        # 摊平的线路字段 → services[0]
        inline = {
            key: item.pop(key)
            for key in ("line", "service", "board_at", "alight_at")
            if key in item
        }
        if inline and not item.get("services"):
            service = {
                "service": inline.get("line") or inline.get("service"),
                "board_at": inline.get("board_at"),
                "alight_at": inline.get("alight_at"),
                "operating_start": item.get("first_departure"),
                "operating_end": item.get("last_departure"),
            }
            if service["service"]:
                item["services"] = [service]
        # 裸票价 → {status, amount_cny}。status 用 sourced：宿主是带着
        # sources 提交的，这是它查到的值，不是我们估的。
        fare = item.get("fare")
        if isinstance(fare, (int, float)) and not isinstance(fare, bool):
            item["fare"] = {"status": "sourced", "amount_cny": float(fare)}
        sweetened.append(item)
    return {**value, "local_transit": sweetened}


def _coordinate(value: object) -> dict[str, object] | None:
    """Return an explicitly supplied point; never geocode or guess one."""

    if not isinstance(value, Mapping):
        return None
    for key in ("position", "coordinates", "location", "center"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            point = _coordinate(nested)
            if point is not None:
                return point
    longitude = value.get("longitude", value.get("lon"))
    latitude = value.get("latitude", value.get("lat"))
    if (
        not isinstance(longitude, (int, float))
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or isinstance(latitude, bool)
        or not -180 <= float(longitude) <= 180
        or not -90 <= float(latitude) <= 90
    ):
        return None
    return {
        "longitude": float(longitude),
        "latitude": float(latitude),
        "coordinate_system": str(
            value.get("coordinate_system", value.get("crs", "GCJ-02"))
            or "GCJ-02"
        ),
    }


def _candidate_map(evidence: Mapping[str, object]) -> dict[str, object]:
    """Project only fact-backed POI coordinates for one candidate card."""

    markers: list[dict[str, object]] = []
    seen: set[tuple[float, float, str]] = set()

    def add(name: object, value: object, kind: str) -> None:
        if not isinstance(name, str) or not name.strip():
            return
        point = _coordinate(value)
        if point is None:
            return
        identity = (
            float(point["longitude"]),
            float(point["latitude"]),
            name.strip(),
        )
        if identity in seen:
            return
        seen.add(identity)
        markers.append(
            {
                "marker_id": f"candidate-point-{len(markers) + 1}",
                "name": name.strip(),
                "kind": kind,
                "position": point,
            }
        )

    for domain, raw_item in evidence.items():
        facts = getattr(raw_item, "facts", ())
        value = usable_fact_values(facts)
        for key, kind in (
            ("attractions", "attraction"),
            ("hotel_candidates", "accommodation"),
            ("map_points", "place"),
            ("places", "place"),
        ):
            rows = value.get(key)
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, Mapping):
                        add(
                            row.get("name") or row.get("display_name"),
                            row,
                            kind,
                        )
        base = value.get("hotel_area")
        if isinstance(base, Mapping):
            add(base.get("name"), base, "accommodation")
        resolutions = value.get("local_transit_place_resolutions")
        if isinstance(resolutions, Mapping):
            for name, row in resolutions.items():
                add(name, row, "transit_stop")
    return {"markers": markers, "route_polylines": []}


def _source_view(item: Mapping[str, object]) -> list[dict[str, object]]:
    sources = item.get("sources")
    return [
        {
            "provider": str(
                source.get("provider")
                or source.get("publisher")
                or source.get("source_type")
                or "未标明来源"
            ),
            **(
                {"retrieved_at": str(source["retrieved_at"])}
                if isinstance(source.get("retrieved_at"), str)
                else {}
            ),
        }
        for source in (sources if isinstance(sources, (list, tuple)) else ())
        if isinstance(source, Mapping)
    ]


def _event_evidence_view(
    plan_payload: Mapping[str, object],
    trip_payload: Mapping[str, object],
    evidence: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Resolve event fact_refs to the read-time projection already in trip().

    The adapter only joins references to projection rows.  ``token`` and
    ``next_action`` are copied verbatim from the read model; no support or
    freshness condition exists here.
    """

    presentation = trip_payload.get("presentation")
    statuses = (
        presentation.get("evidence_statuses")
        if isinstance(presentation, Mapping)
        else None
    )
    status_rows = [
        row for row in statuses if isinstance(row, Mapping)
    ] if isinstance(statuses, list) else []
    status_by_projection_domain = {
        str(row.get("domain")): row for row in status_rows
    }
    item_by_id: dict[str, tuple[str, Mapping[str, object]]] = {}
    for domain, item in evidence.items():
        evidence_id = item.get("evidence_id")
        if isinstance(evidence_id, str):
            item_by_id[evidence_id] = (str(domain), item)

    installed_plan = plan_payload.get("plan")
    days = (
        installed_plan.get("days")
        if isinstance(installed_plan, Mapping)
        else None
    )
    output: dict[str, object] = {}
    for day in days if isinstance(days, list) else ():
        if not isinstance(day, Mapping):
            continue
        events = day.get("events")
        for event in events if isinstance(events, list) else ():
            if not isinstance(event, Mapping):
                continue
            event_id = event.get("event_id")
            if not isinstance(event_id, str):
                continue
            references = [
                str(reference)
                for reference in (
                    event.get("fact_refs")
                    if isinstance(event.get("fact_refs"), list)
                    else []
                )
                if isinstance(reference, str)
            ]
            grouped: dict[str, list[str]] = {}
            unresolved: list[str] = []
            for reference in references:
                evidence_id = reference.partition("#")[0]
                if evidence_id in item_by_id:
                    grouped.setdefault(evidence_id, []).append(reference)
                else:
                    unresolved.append(reference)
            badges: list[dict[str, object]] = []
            for evidence_id, fact_refs in grouped.items():
                domain, item = item_by_id[evidence_id]
                projection_domain = {
                    "railway": "railway",
                    "map": "local_transit",
                    "web": (
                        "accommodation"
                        if event.get("type") in {"hotel", "rest"}
                        else "attraction"
                    ),
                }.get(domain)
                status = status_by_projection_domain.get(
                    str(projection_domain or "")
                )
                if not isinstance(status, Mapping) or not isinstance(
                    status.get("token"), str
                ):
                    unresolved.extend(fact_refs)
                    continue
                badge = {
                    "fact_refs": fact_refs,
                    "label": status.get("label") or domain,
                    "token": status["token"],
                    "retrieved_at": status.get("retrieved_at"),
                    "sources": _source_view(item),
                }
                if isinstance(status.get("next_action"), Mapping):
                    badge["next_action"] = deepcopy(status["next_action"])
                badges.append(badge)
            output[event_id] = {
                "badges": badges,
                "unresolved_fact_refs": unresolved,
            }
    return output


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
        self._verifications = VerificationRegistry()

    def create_trip_task(
        self,
        intent: Mapping[str, object],
    ) -> dict[str, object]:
        """Create a durable run and return its canonical read model."""

        return self._guard(
            lambda: self._query.trip(
                self._application.create_trip(intent).run_id
            ),
            next_call=(
                "被拒多半是 intent 字段问题：时间要用不带时区的本地 ISO"
                "（2026-08-11T12:00），pace 与 transport_preferences 必填。"
                "改好后重新调 create_trip_task(intent={...})"
            ),
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
            raise TripMCPError(
                "wait_seconds 要在 0 到 30 之间",
                next_call=(
                    "advance_trip_task(run_id, wait_seconds=10) —— "
                    "10 秒是常用值；只想立刻拿状态就传 0"
                ),
            )

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
                outcome = self._application.execute_trip(
                    run_id,
                    drive_budget_seconds=_SYNCHRONOUS_DRIVE_BUDGET_SECONDS,
                )
                progress = outcome.action_loop
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
            return self._checkpoint(run_id, current, progress=progress)

        return self._guard(
            operation,
            next_call=(
                "advance_trip_task(run_id) 再推一次；"
                "想只看状态不推进用 read_trip(run_id)"
            ),
        )

    def read_trip(
        self,
        run_id: str,
        *,
        view: str = "overview",
    ) -> dict[str, object]:
        """Read one canonical query view without transport-specific projection."""

        if view not in self._READ_VIEWS:
            raise TripMCPError(
                f"view={view!r} 不是可读视图",
                next_call=(
                    'read_trip(run_id, view="overview")｜可选值：'
                    "overview、candidates、plan、missing、map、audit"
                ),
            )
        readers = {
            "overview": self._query.trip,
            "candidates": self._query.candidates,
            "plan": self._query.current_plan,
            "missing": self._query.missing_information,
            "map": self._query.map_payload,
            "audit": self._query.audit_result,
        }
        return self._guard(
            lambda: readers[view](run_id),
            next_call=(
                f'这个视图现在读不出来。先用 read_trip(run_id, view="overview") '
                "看任务整体状态，overview 里的 checkpoint 会说明当前该做什么"
            ),
        )

    def render_trip_candidates(
        self,
        run_id: str,
    ) -> dict[str, object]:
        """Return the canonical candidate view in an MCP App envelope."""

        def operation() -> dict[str, object]:
            candidates = self._query.candidates(run_id)
            maps: dict[str, object] = {}
            options = candidates.get("candidates")
            for option in options if isinstance(options, list) else ():
                if not isinstance(option, Mapping):
                    continue
                destination_id = option.get("destination_id")
                if not isinstance(destination_id, str):
                    continue
                try:
                    evidence = self._application.guided_evidence_for_selection(
                        run_id,
                        destination_id,
                    )
                except TripApplicationError:
                    continue
                candidate_map = _candidate_map(evidence)
                if candidate_map["markers"]:
                    maps[destination_id] = candidate_map
            return {
                "view": "candidates",
                "run_id": run_id,
                "current_version": None,
                "candidates": candidates,
                "candidate_maps": maps,
            }

        return self._guard(
            operation,
            next_call=(
                "候选还没准备好。advance_trip_task(run_id) 推到 "
                "CANDIDATES_READY 再来"
            ),
        )

    def render_trip_plan(
        self,
        run_id: str,
    ) -> dict[str, object]:
        """Return canonical trip and plan views in an MCP App envelope."""

        def operation() -> dict[str, object]:
            plan = self._query.current_plan(run_id)
            trip = self._query.trip(run_id)
            version = plan.get("plan_version")
            return {
                "view": "plan",
                "run_id": run_id,
                "current_version": version,
                "trip": trip,
                "plan": plan,
                "event_evidence": _event_evidence_view(
                    plan,
                    trip,
                    self._application.current_run_evidence(run_id),
                ),
            }

        return self._guard(
            operation,
            next_call=(
                "行程还没装上。advance_trip_task(run_id) 推到 "
                "PLAN_OR_PARTIAL_RESULT_READY；缺证据就按 next_call 去补"
            ),
        )

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

        return self._guard(
            operation,
            next_call=(
                "candidate_id 要用 show_trip_candidates 返回的 destination_id "
                "原样传回，不要自己拼。先 read_trip(run_id, view=\"candidates\") "
                "看有哪些可选"
            ),
        )

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

        return self._guard(
            operation,
            next_call=_evidence_hint(normalized.get("action_id")),
        )

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

        return self._guard(
            operation,
            next_call=(
                'revise_trip_plan(run_id, revision={"pace": "relaxed", '
                '"user_message": "第二天太赶"}) —— 给的是约束不是时间轴'
            ),
        )

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

        return self._guard(
            operation,
            next_call=(
                "audit_trip_plan(plan={...}) 或 audit_trip_plan(content=\"攻略原文\")"
                "——两者给其一"
            ),
        )

    def _checkpoint(
        self,
        run_id: str,
        trip: Mapping[str, object],
        *,
        progress: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        status = _run_status(trip)
        checkpoint = _checkpoint_name(trip)
        # 候选比较进行中：报「比较中 + 进度」而不是光秃秃的 RUNNING。宿主拿到
        # 2/3 知道再等值得，拿到 RUNNING 只能猜——上一轮的 4 分钟就是这么熬掉的。
        if (
            checkpoint == "RUNNING"
            and isinstance(progress, Mapping)
            and str(progress.get("status")) == "COMPARING"
        ):
            checkpoint = "COMPARING_CANDIDATES"
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
        if checkpoint == "COMPARING_CANDIDATES" and isinstance(
            progress, Mapping
        ):
            response["progress"] = dict(progress)
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
        if not assertions:
            raise TripMCPError(
                "assertions 不能为空",
                next_call=_VERIFY_HINT,
            )
        if len(assertions) > MAX_VERIFIED_ASSERTIONS:
            # 分批而不是偷偷截断：截断会让宿主以为全核过了。
            raise TripMCPError(
                f"一次最多核 {MAX_VERIFIED_ASSERTIONS} 条，本次收到 "
                f"{len(assertions)} 条。请分批提交",
                next_call=(
                    f"verify_itinerary(assertions=[前 {MAX_VERIFIED_ASSERTIONS} 条])"
                    "，然后对余下的再调一次"
                ),
            )
        # 收下活，立刻回执。实采在后台——同步核会把这次调用拖到分钟级，
        # 那正是第四次实测宿主放弃的原因（I14）。
        immediate, checkable = split_by_shape(assertions)
        canonical = json.dumps(
            assertions,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=repr,
        ).encode("utf-8")
        try:
            started = self._verifications.start_background(
                total=len(assertions),
                immediate=immediate,
                collect=lambda report: verify_checkable_incrementally(
                    checkable,
                    report=report,
                ),
                dedupe_key=hashlib.sha256(canonical).hexdigest(),
                retry_items=assertions,
            )
        except VerificationCapacityError as error:
            raise TripMCPError(
                str(error),
                next_call="等待几秒后用相同 assertions 重试 verify_itinerary",
            ) from None
        return self._verification_view(started)

    def read_verification(self, verify_id: str) -> dict[str, object]:
        """取一份核验的当前结果（含增量）。"""

        snapshot = self._verifications.read(str(verify_id))
        if snapshot is None:
            raise TripMCPError(
                f"verify_id={verify_id!r} 不存在。"
                "核验结果只在本进程内保留一小时；服务重启或超时后需要重新提交",
                next_call=_VERIFY_HINT,
            )
        return self._verification_view(snapshot)

    @staticmethod
    def _verification_view(snapshot: Mapping[str, object]) -> dict[str, object]:
        findings = snapshot.get("findings")
        findings = findings if isinstance(findings, list) else []
        # 登记处保存的是采集事实，不保存一个永远不变的展示 token。每次读取都按
        # retrieved_at 重算，长时间轮询也不能把旧数据继续叫作 verified。
        refreshed_findings: list[dict[str, object]] = []
        for raw_finding in findings:
            if not isinstance(raw_finding, Mapping):
                continue
            finding = dict(raw_finding)
            verdict = str(finding.get("verdict"))
            try:
                finding["token"] = verification_token(
                    verdict,
                    finding.get("retrieved_at"),
                )
            except KeyError:
                pass
            refreshed_findings.append(finding)
        findings = refreshed_findings
        status = str(snapshot.get("status"))
        # FINALIZING = 结论已到齐、后台还没宣告收工。对宿主而言仍要再取一次，
        # 所以和 RUNNING 同样处理，但状态名如实区分（R1）。
        running = status in {"RUNNING", "FINALIZING"}
        view = {
            "view": "verification",
            "artifact_kind": "ItineraryVerification",
            "domain": "railway",
            **dict(snapshot),
            "findings": findings,
            # 总评按**已核出的**算，并明说还剩几条——不把未核的算成有据。
            "summary": summarize_dicts(findings),
            "scope_note": (
                "v0 只核铁路域（车次存在性、时刻、票价）。住宿、门票、当地交通"
                "未核验——没有核验不等于没有问题。"
            ),
        }
        for finding in findings:
            if finding.get("retrieved_at") is not None:
                finding["sources"] = [{"provider": "中国铁路12306"}]
            suggested = finding.get("suggested_action")
            if isinstance(suggested, str) and suggested.strip():
                finding["next_action"] = {"detail": suggested}
        if running:
            if status == "FINALIZING":
                detail = (
                    "全部结论已经到齐，后台正在提交终态。"
                    "再取一次即可；不要用 pending 判断是否收工。"
                )
            else:
                detail = (
                    f"还有 {snapshot.get('pending')} 条在实查 12306。"
                    "每条约 2 秒，隔几秒再取一次即可。"
                    "本响应里已核出的部分是最终结论，不会再变。"
                )
            view["next_call"] = {
                "reason": "VERIFICATION_IN_PROGRESS",
                "options": [
                    {
                        "kind": "poll",
                        "entrypoint": "read_verification",
                        "arguments": {"verify_id": snapshot.get("verify_id")},
                        "detail": detail,
                    }
                ],
            }
        else:
            # R3：完成态要一眼可判——状态词固定、计数总评完整、建议动作具体。
            summary = view["summary"]
            flagged = summary.get("needs_confirmation") or []
            view["status"] = "completed" if status == "COMPLETE" else "failed"
            view["terminal"] = True
            view["complete"] = status == "COMPLETE"
            if status == "COMPLETE":
                detail = (
                    f"核验完成：{summary.get('sentence')}。"
                    + (
                        f"建议逐条落实第 {'、'.join(str(i) for i in flagged)} 条"
                        "——conflicting 附了两边的值，unknown 请注意它表示"
                        "「查无实据」而不是「假」。"
                        if flagged
                        else "已提交的铁路断言全部对得上；其他出行域仍未核验。"
                    )
                )
                options: list[dict[str, object]] = []
            else:
                retry_assertions = snapshot.get("retry_assertions")
                retry_assertions = (
                    retry_assertions
                    if isinstance(retry_assertions, list)
                    else []
                )
                detail = (
                    f"核验中断：{snapshot.get('error')}。"
                    f"已核出的 {summary.get('total')} 条仍然有效；"
                    f"余下 {len(retry_assertions)} 条可以重新提交。"
                )
                options = (
                    [
                        {
                            "kind": "retry",
                            "entrypoint": "verify_itinerary",
                            "arguments": {"assertions": retry_assertions},
                            "detail": "只重试尚未得到结论的断言。",
                        }
                    ]
                    if retry_assertions
                    else []
                )
            view["next_call"] = {
                "reason": view["status"].upper(),
                "options": options,
                "detail": detail,
            }
        return view

    @staticmethod
    def _guard(
        operation: object,
        *,
        next_call: str,
    ) -> dict[str, object]:
        try:
            result = operation()
        except (TripApplicationError, TripQueryError, TravelAgentError) as error:
            raise TripMCPError(str(error), next_call=next_call) from None
        if not isinstance(result, dict):
            raise TripMCPError(
                "trip service returned a non-object result",
                next_call=(
                    "这是服务端内部错误，不是调用姿势问题。"
                    "用 read_trip(run_id) 看当前状态，并把这条报错反馈给维护者"
                ),
            )
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
        "COMPARING_CANDIDATES": (
            "advance_trip_task",
            "候选还在逐个实查往返车次（本响应的 progress 里有进度）。"
            "再调一次即可，通常 20–40 秒内出结果。",
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
    accepted = bool(getattr(outcome, "accepted", False))
    view: dict[str, object] = {
        "trip": trip,
        "accepted": accepted,
        "action_loop": dict(action_loop) if isinstance(action_loop, Mapping) else None,
    }
    # 收活的命令要回报「解析出多少条事实」。宿主此前只看到 accepted:false，
    # 无从判断证据到底进没进去（实际是进了）——数字比布尔诚实得多。
    parsed = getattr(outcome, "parsed_facts_count", None)
    if parsed is not None:
        view["parsed_facts_count"] = int(parsed)
    # 否定语义必须自带解释（D20 的运行时那一半）。
    if not accepted:
        reason = getattr(outcome, "rejection_reason", None)
        if reason:
            view["rejection_reason"] = reason
        missing_keys = tuple(getattr(outcome, "missing_keys", ()) or ())
        if missing_keys:
            view["missing_keys"] = list(missing_keys)
        schema_ref = getattr(outcome, "schema_ref", None)
        if schema_ref:
            view["schema_ref"] = schema_ref
    return view


__all__ = ["TripMCPAdapter", "TripMCPError"]
