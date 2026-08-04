"""City-neutral compilation from DestinationContext to itinerary inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from typing import NamedTuple

from trip_decider.evidence_core import (
    FRESHNESS_STALE,
    SUPPORT_UNKNOWN,
    is_confirmed_absent,
    token_freshness,
    token_support,
)
from trip_decider.evidence_projection import (
    item_facts,
    project_domain,
    resolve_stale_evidence,
    usable_fact_values,
)
from trip_decider.itinerary_planner import (
    RAIL_EVENT_REQUIRED_TRAIN_FIELDS,
    make_attraction_event,
    make_duration_event,
    make_event,
    make_meal_event,
    make_rail_event,
    resolve_pace_settings,
    resolve_planner_defaults,
)
from trip_decider.travel_agent import DestinationContext


#: 「当前可用」的 planning_state 集合——**单一出处**。
#:
#: 此前有三份并列：本模块的 ``_INSTALLABLE_STATES``、``trip_query`` 的
#: ``_USABLE_PLAN_STATES``、``agent_actions._result_is_displayable`` 里的一个
#: 内联字面量。三份都写着同两个取值，但没有任何东西保证它们一起改（D5：
#: 成对操作必须引用同一份粒度定义，两份并列的名单早晚有人只改一份）。
INSTALLABLE_STATES: frozenset[str] = frozenset(
    {"PARTIAL_READY", "PLAN_READY"}
)

_INSTALLABLE_STATES = INSTALLABLE_STATES


class PlanVerdict(NamedTuple):
    """「这份计划**当前**够不够格呈现」的读取时刻结论。

    与「已写入」是两件事（`persistence-v2.md` §6.2/6.3）：版本号写下就不变，
    而可用性是 ``now`` 的函数——同一份 PlanVersion 在容差窗内外给出不同答案。
    """

    planning_state: str | None
    usable_now: bool
    blockers: tuple[Mapping[str, object], ...]
    #: 读时重采的待写回标记。**本模块不落盘**——写回由应用层执行
    #: （`freshness-policy.md` §5.2.2）。调用方不写也不会错，只是节流不生效。
    pending_writes: tuple[tuple[str, Mapping[str, object]], ...] = ()


_ABSENT_VERDICT = PlanVerdict(
    planning_state=None,
    usable_now=False,
    blockers=(),
)


def _resolved_context(
    context: Mapping[str, object],
    *,
    now: datetime,
    refetcher: object,
) -> tuple[Mapping[str, object], tuple[tuple[str, Mapping[str, object]], ...]]:
    """解析步的**装载点一**：``run.result["context"]["evidence"]``（列表容器）。

    容器形状是这里唯一的本地知识——转成按域的 mapping 交给唯一实现
    ``resolve_stale_evidence``，再按原形状写回。逻辑一份，装载点两个
    （另一个是 ``trip_query`` 的 guided-comparison 容器）。
    """

    if refetcher is None:
        return context, ()
    raw = context.get("evidence")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return context, ()
    by_domain: dict[str, Mapping[str, object]] = {}
    for item in raw:
        if isinstance(item, Mapping) and isinstance(item.get("domain"), str):
            by_domain[str(item["domain"])] = item
    if not by_domain:
        return context, ()
    resolved = resolve_stale_evidence(
        by_domain,
        now=now,
        refetcher=refetcher,
    )
    if not resolved.refetched and not resolved.failed:
        return context, resolved.pending_writes
    # 整份替换：同一次读取里，token 的依据与 fact_values 的依据必须是同一个
    # 实例。只换 token 不换值，就是这条解析步存在的理由所要防的那件事。
    replaced = [
        resolved.items.get(str(item["domain"]), item)
        if isinstance(item, Mapping)
        and isinstance(item.get("domain"), str)
        else item
        for item in raw
    ]
    return (
        {**dict(context), "evidence": replaced},
        resolved.pending_writes,
    )


def plan_verdict_from_result(
    result: Mapping[str, object] | None,
    *,
    now: datetime,
    evidence: Mapping[str, Mapping[str, object]] | None = None,
    refetcher: object = None,
) -> PlanVerdict:
    """从 ``run.result`` 取 context，按读取时刻编译出计划准入结论。

    **这是该判定的唯一实现。** 此前有两份：``trip_query.plan_readiness`` 自己
    compile 一次，``agent_actions.recomputed_planning_state`` 又 compile 一次。
    两份各自读 ``result["context"]``、各自判 ``PARTIAL_READY/PLAN_READY``，
    于是同一份证据在两个读取面可能给出不同结论——那与「结论和数据不同步」
    同族，只是错位发生在同一时刻的两次读取之间。收敛到这里之后，
    ``agent_actions`` 拿结论，不再自己碰证据 mapping。

    这里也是 auto_refetch 读时解析步的装载点：证据在这一层被解析成结论，
    重采若要发生，必须发生在 compile **之前**，一次替换整份
    （`freshness-policy.md` §5.2）。
    """

    if not isinstance(result, Mapping):
        return _ABSENT_VERDICT
    context = result.get("context")
    if not isinstance(context, Mapping):
        return _ABSENT_VERDICT
    if evidence is not None:
        # 证据来自容器 B（`evidence/current.json`），不再读 context 里的内联
        # 副本——A 已收敛（`persistence-v2.md` §2.1.1）。`user_input` 域不在 B
        # 里，由调用方按 `travel_agent.user_input_evidence` 重建后一并传入。
        context = {
            **dict(context),
            "evidence": [dict(item) for item in evidence.values()],
        }
    context, pending = _resolved_context(context, now=now, refetcher=refetcher)
    try:
        compiled = PlanningInputCompiler().compile(context, now=now)
    except Exception:  # noqa: BLE001 - 结构不完整的历史数据不该让读取崩掉
        return _ABSENT_VERDICT._replace(pending_writes=pending)
    state = str(compiled.get("planning_state") or "") or None
    return PlanVerdict(
        planning_state=state,
        usable_now=state in INSTALLABLE_STATES,
        blockers=tuple(
            deepcopy(dict(item))
            for item in compiled.get("conditional_blockers", ())
            if isinstance(item, Mapping)
        ),
        pending_writes=pending,
    )


class _PlanRefs(NamedTuple):
    """一次编译里反复要用的引用，算一次传下去。

    每个事件都该说清「我出自哪些事实」——读取层拿 ``fact_refs`` 按读取时刻重算
    token，PlanVersion 文件里没有可回落的值，R2（引用解析失败必须产出 unknown）
    因此由数据形状保证而不是靠代码自律（persistence-v2.md §5.1）。

    规划器默认值派生的事件（餐食、休息、缓冲、自由活动）出自**行程窗口**，
    那是用户输入的事实；与铁路时刻挂钩的缓冲另外引用对应的车次事实。

    后两项是**证据级**引用（``evidence_dependencies`` 用），与前四项的字段级
    引用分成两组字段而不是合成一组：两种粒度指的东西不同，合了就没法在调用点
    看出这一处该给哪一种（D20 的同类判断，`engineering-discipline.md`）。
    两种粒度都从传进来的证据现算——写死 id 是本模块此前唯一的引用缺陷来源。
    """

    intent_window: tuple[str, ...] = ()
    rail_arrival: tuple[str, ...] = ()
    rail_departure: tuple[str, ...] = ()
    hotel_area: tuple[str, ...] = ()
    user_evidence: tuple[str, ...] = ()
    rail_evidence: tuple[str, ...] = ()


class PlanningInputCompiler:
    """Compile evidence-backed inputs for the existing itinerary planner."""

    def compile(
        self,
        context: DestinationContext | Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """``now`` 是读取时刻，判定 freshness 用。

        本次只接线不使用：铁路段仍读落盘的 ``snapshot.status``。换成读取时
        token 需要连带翻整份表征基线（见 p4b-baseline-flip-preview.md），
        安排在 agent_actions 四子批之后，好让基线在那批期间保持可用。
        """

        read_at = now if now is not None else datetime.now(timezone.utc)
        payload = (
            context.to_dict()
            if isinstance(context, DestinationContext)
            else deepcopy(dict(context))
        )
        intent = _mapping(payload.get("intent"), "context intent")
        evidence = _evidence_by_domain(payload.get("evidence"))
        earliest = _wall_datetime(
            intent.get("earliest_departure_at"),
            "earliest_departure_at",
        )
        latest = _wall_datetime(
            intent.get("latest_return_at"),
            "latest_return_at",
        )
        if latest <= earliest:
            raise ValueError("travel window must be positive")
        pace = str(intent.get("pace") or "standard")
        pace_values, pace_contract = resolve_pace_settings(
            pace=pace,
            physical_level=None,
            early_start=None,
            night_activity=None,
            transport_tolerance=None,
            depth_preference=None,
            overrides=None,
        )
        defaults, default_contract = resolve_planner_defaults(
            None,
            profile_values=pace_values,
        )
        days = _day_shells(earliest, latest)
        events_by_type: dict[str, list[dict[str, object]]] = {
            event_type: []
            for event_type in (
                "transit",
                "attraction",
                "meal",
                "hotel",
                "buffer",
                "rest",
            )
        }
        blockers: list[dict[str, object]] = []
        dependencies: dict[str, list[str]] = {
            event_type: [] for event_type in events_by_type
        }

        railway = evidence.get("railway")
        _compile_railway(
            railway,
            now=read_at,
            days=days,
            events_by_type=events_by_type,
            dependencies=dependencies,
            blockers=blockers,
        )
        map_item = evidence.get("map")
        web_item = evidence.get("web")
        hotel_area = _hotel_area(web_item)
        plan_refs = _PlanRefs(
            intent_window=tuple(
                _field_refs(
                    evidence.get("user_input"),
                    "earliest_departure_at",
                    "latest_return_at",
                )
            ),
            rail_arrival=tuple(_field_refs(railway, "outbound.arrival_at")),
            rail_departure=tuple(
                _field_refs(railway, "return.departure_at")
            ),
            hotel_area=tuple(_field_refs(web_item, "hotel_area.name")),
            user_evidence=tuple(_evidence_ref(evidence.get("user_input"))),
            rail_evidence=tuple(_evidence_ref(railway)),
        )
        _compile_local_transit(
            map_item,
            earliest=earliest,
            latest=latest,
            days=days,
            events_by_type=events_by_type,
            dependencies=dependencies,
            blockers=blockers,
        )
        _compile_attractions(
            map_item,
            web_item,
            earliest=earliest,
            latest=latest,
            max_visit_minutes=int(
                pace_values["max_continuous_attraction_minutes"]
            ),
            lunch_minutes=int(defaults["lunch_minutes"]),
            lunch_window_end=time.fromisoformat(
                str(defaults["lunch_window_end"])
            ),
            inter_event_buffer_minutes=int(
                defaults["inter_event_buffer_minutes"]
            ),
            planner_defaults=defaults,
            plan_refs=plan_refs,
            days=days,
            events_by_type=events_by_type,
            dependencies=dependencies,
            blockers=blockers,
        )
        _compile_defaults(
            earliest=earliest,
            latest=latest,
            defaults=defaults,
            hotel_area=hotel_area,
            web_evidence_refs=_evidence_ref(web_item),
            plan_refs=plan_refs,
            days=days,
            events_by_type=events_by_type,
            dependencies=dependencies,
            blockers=blockers,
        )
        _compile_free_time(
            earliest=earliest,
            latest=latest,
            hotel_area=hotel_area,
            plan_refs=plan_refs,
            days=days,
            events_by_type=events_by_type,
            dependencies=dependencies,
        )
        _record_evidence_blockers(evidence, blockers)
        raw_hard_conflicts = payload.get("hard_constraint_conflicts")
        if isinstance(raw_hard_conflicts, Sequence) and not isinstance(
            raw_hard_conflicts,
            (str, bytes, bytearray),
        ):
            for index, conflict in enumerate(raw_hard_conflicts, start=1):
                blockers.append(
                    _blocker(
                        f"HARD_CONSTRAINT_CONFLICT_{index}",
                        "constraints",
                        reason=(
                            conflict
                            if isinstance(conflict, str)
                            else "unresolved hard constraint conflict"
                        ),
                        severity="hard",
                    )
                )

        for day in days:
            day["events"].sort(
                key=lambda event: (
                    str(event.get("start_at") or "9999"),
                    str(event.get("event_id") or ""),
                )
            )
            day["conditions"] = [
                blocker["blocker_id"]
                for blocker in blockers
                if blocker.get("day") in {None, day["day"]}
            ]

        unique_blockers = _unique_blockers(blockers)
        rail_events = [
            event
            for event in events_by_type["transit"]
            if str(event.get("event_id", "")).startswith("rail-")
        ]
        local_transit_events = [
            event
            for event in events_by_type["transit"]
            if not str(event.get("event_id", "")).startswith("rail-")
        ]
        destination_resolved = _destination_resolved(map_item, web_item)
        attraction_transit_coverage = all(
            isinstance(event.get("inbound_transit_event_id"), str)
            and bool(str(event["inbound_transit_event_id"]).strip())
            for event in events_by_type["attraction"]
        ) and bool(events_by_type["attraction"])
        hard_constraints_clear = not any(
            blocker.get("severity") == "hard" for blocker in unique_blockers
        )
        display_requirements = {
            "destination_resolved": destination_resolved,
            "outbound_transport": any(
                event.get("event_id") == "rail-outbound"
                for event in rail_events
            ),
            "return_transport": any(
                event.get("event_id") == "rail-return"
                for event in rail_events
            ),
            "attraction": bool(events_by_type["attraction"]),
            "local_transit": bool(local_transit_events),
            "attraction_transit_coverage": attraction_transit_coverage,
            "accommodation_base": hotel_area is not None,
            "hard_constraints_clear": hard_constraints_clear,
        }
        display_requirements["cross_city_transport"] = (
            display_requirements["outbound_transport"]
            and display_requirements["return_transport"]
        )
        missing_requirements = [
            name
            for name, present in display_requirements.items()
            if present is not True and name != "cross_city_transport"
        ]
        if not hard_constraints_clear:
            planning_state = "BLOCKED"
        elif missing_requirements:
            planning_state = "COLLECTING_EVIDENCE"
        elif any(
            blocker.get("severity") != "advisory"
            for blocker in unique_blockers
        ):
            planning_state = "PARTIAL_READY"
        else:
            planning_state = "PLAN_READY"
        displayable = planning_state in _INSTALLABLE_STATES
        status = (
            "PARTIAL_PLAN_WITH_BLOCKERS"
            if unique_blockers
            else "CONDITIONALLY_FEASIBLE"
        )
        return {
            "artifact_kind": "PlanningDraft",
            "planning_state": planning_state,
            "status": status,
            "displayable": displayable,
            "display_requirements": display_requirements,
            "missing_requirements": missing_requirements,
            "days": days,
            "cross_city_rail_events": rail_events,
            "attraction_events": events_by_type["attraction"],
            "local_transit_events": local_transit_events,
            "map_points": _compiled_map_points(map_item, web_item),
            "meal_events": events_by_type["meal"],
            "hotel_events": events_by_type["hotel"],
            "buffer_events": events_by_type["buffer"],
            "rest_events": events_by_type["rest"],
            "evidence_dependencies": dependencies,
            "conditional_blockers": unique_blockers,
            "planner_defaults": default_contract,
            "pace_contract": pace_contract,
        }


def _compile_railway(
    evidence: Mapping[str, object] | None,
    *,
    now: datetime,
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
    blockers: list[dict[str, object]],
) -> None:
    # 判定点 3（p3b-gate-inventory.md §2.1，丙型）。旧实现在此静默 return，
    # 连 blocker 都不产——unknown/conflicting 的铁路证据会让整段编译悄悄跳过，
    # 计划照常生成而用户看不到任何提示（I7 第 2 条）。
    if not _is_usable(evidence):
        blockers.append(
            _blocker(
                "RAILWAY_INPUT_UNAVAILABLE",
                "railway",
                reason=(
                    evidence.get("missing_reason")
                    if evidence is not None
                    else None
                ),
                evidence_refs=_evidence_ref(evidence),
            )
        )
        return
    facts = item_facts(evidence)
    if not facts:
        blockers.append(
            _blocker(
                "RAILWAY_INPUT_UNAVAILABLE",
                "railway",
                evidence_refs=_evidence_ref(evidence),
            )
        )
        return
    absent = next(
        (fact for fact in facts if is_confirmed_absent(fact.get("value"))),
        None,
    )
    if absent is not None:
        value = dict(absent.get("value") or {})
        # 已核实该时间窗内没有直达车。这是一个确定的结论，不是「没查到」。
        blockers.append(
            _blocker(
                "RAILWAY_NO_DIRECT_TRAIN",
                "railway",
                reason=value.get("scope"),
                evidence_refs=_evidence_ref(evidence),
            )
        )
        return
    # 时刻可靠性由读取时刻判定，不再读落盘的 snapshot.status——那是采集时
    # 冻结的判断，同一份字节无论何时读都给同一个答案（I5）。
    # 本判定排在确认否定分支**之后**：已核实无直达车是确定结论，与新鲜度无关。
    evidence_id = str(evidence.get("evidence_id"))
    token = project_domain({"railway": evidence}, "railway", now=now).token
    # 「没结论」与「过期」在规划层是同一个后果：这份铁路输入不能据以推进。
    # 二者的区分不在 blocker_id 里复述，消费方顺 fact_id 读 token 得知
    # （persistence-v2.md §7.2）。
    if token_support(token) == SUPPORT_UNKNOWN:
        blockers.append(
            _blocker(
                "RAILWAY_INPUT_UNAVAILABLE",
                "railway",
                evidence_refs=[evidence_id],
            )
        )
        return
    if token_freshness(token) == FRESHNESS_STALE:
        blockers.extend(
            (
                _blocker(
                    "RAILWAY_INPUT_UNAVAILABLE",
                    "railway",
                    evidence_refs=[evidence_id],
                ),
                # 余票不是「未知状态」而是「不保证有座」——后者是规划层结论。
                # 这一支的指代对象是**余票字段本身**（persistence-v2.md §7.2），
                # 不是整个铁路域：本分支里证据是可用的（只是过期），两个方向的
                # 余票事实都在，字段级引用指得到，故用 fact_refs 而非
                # evidence_refs。分方向两个 fact，引用天然是复数。
                _blocker(
                    "RAILWAY_SEAT_NOT_GUARANTEED",
                    "railway",
                    fact_refs=_field_refs(
                        evidence,
                        "second_class_availability",
                    ),
                ),
            )
        )
    usable = usable_fact_values(item_facts(evidence))
    for direction, prefix in (
        ("outbound", "去程"),
        ("return", "返程"),
    ):
        train = usable.get(direction)
        # 「整体缺席」与「在场但排不出事件」是同一个规划后果，走同一个 blocker。
        # 判据用 make_rail_event 自己的必填集，不在这里另抄一份键名（D2）。
        #
        # 第二支不是防御性冗余：字段级投影会把 support 不可用的字段**整个丢掉**
        # （usable_fact_values 跳过 value 为 None 的 fact），所以一份形状完全
        # 正常的采集结果，只要 origin_station 回了 None，这里拿到的就是一个缺
        # 键的 mapping。提交门（agent_actions._validate_railway_value）现在会在
        # 门口拦掉这种提交，但**盘上还有门之前写下的证据**——那些恢复回来时不能
        # 让编译器崩。缺键不补默认值：车站名编不出来，编不出来就是排不出事件。
        missing_fields = (
            [
                field
                for field in RAIL_EVENT_REQUIRED_TRAIN_FIELDS
                if train.get(field) is None
            ]
            if isinstance(train, Mapping)
            else []
        )
        if not isinstance(train, Mapping) or missing_fields:
            # 规划后果：该方向排不出车次事件。与 LOCAL_TRANSIT_DURATION_MISSING
            # 同类——说的是「这段规划不出来」，不是在复述某个 support 取值。
            blockers.append(
                _blocker(
                    f"RAILWAY_{direction.upper()}_MISSING",
                    "railway",
                    reason=(
                        "缺少排程必需字段：" + "、".join(missing_fields)
                        if missing_fields
                        else None
                    ),
                    evidence_refs=[evidence_id],
                )
            )
            continue
        event = make_rail_event(
            event_id=f"rail-{direction}",
            train=train,
            name_prefix=prefix,
            fact_refs=[
                str(fact["fact_id"])
                for fact in item_facts(evidence)
                if str(fact.get("field", "")).startswith(
                    (f"snapshot.{direction}.", f"{direction}.")
                )
            ],
        )
        # 无需新条件：support 不可用的字段根本不在 usable 里，默认值即兜底
        # （v1 §0.2 对照表第三行）。
        event["second_class_availability"] = train.get(
            "second_class_availability", "UNKNOWN"
        )
        event["evidence_dependencies"] = [evidence_id]
        event["location"] = {
            "from": train.get("origin_station"),
            "to": train.get("destination_station"),
            "kind": "intercity_rail",
        }
        _add_event(days, event)
        events_by_type["transit"].append(event)
        dependencies["transit"].append(evidence_id)


def _usable_services(route: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = route.get("services")
    return [item for item in value if isinstance(item, Mapping)] if isinstance(
        value, list
    ) else []


def _transfer_points(route: Mapping[str, object]) -> list[dict[str, object]]:
    """换乘点：由相邻两段线路**推出**，不另存一份。

    第 n 段的 ``alight_at`` 与第 n+1 段的 ``board_at`` 之间就是一次换乘。两者
    通常同名（同站换乘），不同名则是走一段路换乘——高德只给整条路线的总步行
    距离，**分不到每次换乘头上**，所以这里不写每次换乘走多远（见
    `docs/contracts/local-transit-coverage.md` 的缺口 2）。

    推出而不是存一份：存下来就是第二份可以和 ``services`` 不一致的数据（D19）。
    """

    services = _usable_services(route)
    return [
        {
            "from_service": previous.get("service"),
            "to_service": nxt.get("service"),
            "alight_at": previous.get("alight_at"),
            "board_at": nxt.get("board_at"),
            "same_stop": previous.get("alight_at") == nxt.get("board_at"),
        }
        for previous, nxt in zip(services, services[1:])
    ]


def _compile_local_transit(
    evidence: Mapping[str, object] | None,
    *,
    earliest: datetime,
    latest: datetime,
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
    blockers: list[dict[str, object]],
) -> None:
    routes = _value_list(evidence, "local_transit")
    if not routes:
        # persistence-v2.md §7.2：并入 map 域的动态族，与 _record_evidence_blockers
        # 产的是同一个 blocker_id，重复由 _unique_blockers 收敛。
        blockers.append(
            _blocker(
                "MAP_INPUT_UNAVAILABLE",
                "map",
                evidence_refs=_evidence_ref(evidence),
            )
        )
        return
    evidence_id = str(evidence.get("evidence_id"))
    cursor = _bounded_time(earliest, latest, 1, time(8, 30))
    for index, route in enumerate(routes, start=1):
        duration = route.get("duration_seconds")
        if (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration <= 0
        ):
            blockers.append(
                _blocker(
                    "LOCAL_TRANSIT_DURATION_MISSING",
                    "map",
                    evidence_refs=[evidence_id],
                )
            )
            continue
        start_at = cursor + timedelta(minutes=(index - 1) * 45)
        if start_at >= latest:
            break
        event = make_event(
            event_id=str(route.get("route_id") or f"local-transit-{index}"),
            event_type="transit",
            name=(
                f"{str(route.get('from') or '起点')}→"
                f"{str(route.get('to') or '终点')}"
            ),
            start_at=start_at,
            end_at=min(start_at + timedelta(seconds=duration), latest),
            why="使用地图工具返回的当地交通估计",
            value_origin="api_estimate",
            adjustable=("start_at", "transport_choice"),
            extra={
                "from": route.get("from"),
                "to": route.get("to"),
                "location": {
                    "from": route.get("from"),
                    "to": route.get("to"),
                    "kind": "local_transit",
                },
                "transport_mode": route.get("mode"),
                "duration_seconds": duration,
                "distance_meters": route.get("distance_meters"),
                # 「乘什么、在哪换、走多远」进事件 detail。此前这一段只给时长，
                # 用户实测点名过：行程说「30 分钟到」，但没说坐几路、在哪上车。
                # 数据一直在 map 证据里，缺的是这三行。
                "services": deepcopy(_usable_services(route)),
                "legs": deepcopy(route.get("legs")),
                "transfers": _transfer_points(route),
                "walking_distance_meters": route.get(
                    "walking_distance_meters"
                ),
                # 「多久一班」。景区班车与摆渡车最要紧的就是这个——宿主第三次
                # 实测手写的班车证据里带了它（首班 06:30、每 25 分钟一班），
                # 此前编译器不抄，于是写了也白写。
                "headway_minutes": route.get("headway_minutes"),
                "first_departure": route.get("first_departure"),
                "last_departure": route.get("last_departure"),
                "from_location": deepcopy(route.get("from_location")),
                "to_location": deepcopy(route.get("to_location")),
                "polyline": deepcopy(route.get("polyline")),
                "retrieved_at": route.get("retrieved_at"),
                "fare": deepcopy(
                    route.get(
                        "fare",
                        {"status": "unknown", "amount_cny": None},
                    )
                ),
                "evidence_dependencies": [evidence_id],
                "reference_only": True,
                "fact_refs": [
                    str(fact["fact_id"])
                    for fact in item_facts(evidence)
                    if str(fact.get("field", "")).startswith(
                        f"local_transit[{index - 1}]."
                    )
                ],
            },
        )
        events_by_type["transit"].append(event)
        dependencies["transit"].append(evidence_id)


def _compile_attractions(
    map_item: Mapping[str, object] | None,
    web_item: Mapping[str, object] | None,
    *,
    earliest: datetime,
    latest: datetime,
    max_visit_minutes: int,
    lunch_minutes: int,
    lunch_window_end: time,
    inter_event_buffer_minutes: int,
    planner_defaults: Mapping[str, object],
    plan_refs: _PlanRefs,
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
    blockers: list[dict[str, object]],
) -> None:
    # 第三项是该景点的字段级引用。采集时就算好——出了这个循环就不知道它在
    # 源证据的 attractions[] 里排第几了，而 fact_id 的字段路径带下标。
    # 形状与本地交通事件一致（local_transit[i]. 前缀匹配，commit e901c69）。
    candidates: list[tuple[Mapping[str, object], str, list[str]]] = []
    seen: set[str] = set()
    for evidence in (map_item, web_item):
        if not _is_usable(evidence):
            continue
        evidence_id = str(evidence.get("evidence_id"))
        facts = item_facts(evidence)
        for position, value in enumerate(_value_list(evidence, "attractions")):
            attraction_id = str(
                value.get("attraction_id") or value.get("id") or ""
            )
            if not attraction_id or attraction_id in seen:
                continue
            seen.add(attraction_id)
            prefix = f"attractions[{position}]."
            candidates.append((
                value,
                evidence_id,
                [
                    str(fact["fact_id"])
                    for fact in facts
                    if str(fact.get("field", "")).startswith(prefix)
                ],
            ))
    if not candidates:
        # persistence-v2.md §7.2：并入 web 域的动态族。
        blockers.append(
            _blocker(
                "WEB_INPUT_UNAVAILABLE",
                "web",
                evidence_refs=_evidence_ref(web_item),
            )
        )
        return
    local_routes = [
        event
        for event in events_by_type["transit"]
        if not str(event.get("event_id", "")).startswith("rail-")
    ]

    def route_position(
        item: tuple[Mapping[str, object], str, list[str]],
    ) -> int:
        attraction = item[0]
        name = str(attraction.get("name") or "")
        route_query_name = str(attraction.get("route_query_name") or name)
        for route_index, route in enumerate(local_routes):
            destination = str(route.get("to") or "")
            if (
                name
                and name in destination
                or destination
                and destination in route_query_name
            ):
                return route_index
        return len(local_routes) + len(candidates)

    candidates.sort(key=route_position)
    arrival_ready = _rail_time(
        events_by_type["transit"],
        "rail-outbound",
        "end_at",
    )
    if arrival_ready is not None:
        arrival_ready += timedelta(
            minutes=(
                int(planner_defaults["arrival_buffer_minutes"])
                + int(planner_defaults["hotel_checkin_minutes"])
            )
        )
    return_cutoff = _rail_time(
        events_by_type["transit"],
        "rail-return",
        "start_at",
    )
    if return_cutoff is not None:
        return_cutoff -= timedelta(
            minutes=(
                int(planner_defaults["rail_wait_minutes"])
                + int(planner_defaults["hotel_checkout_minutes"])
            )
        )
    for index, (attraction, evidence_id, attraction_refs) in enumerate(
        candidates,
        start=1,
    ):
        start_at = _bounded_time(
            earliest,
            latest,
            min(index, max(0, len(days) - 1)),
            time(9, 30),
        )
        minutes = attraction.get("visit_minutes", 120)
        if (
            not isinstance(minutes, int)
            or isinstance(minutes, bool)
            or minutes <= 0
        ):
            minutes = 120
        minutes = min(minutes, max_visit_minutes)
        if arrival_ready is not None and start_at.date() == arrival_ready.date():
            start_at = max(start_at, arrival_ready)
        if (
            return_cutoff is not None
            and start_at.date() == return_cutoff.date()
            and start_at + timedelta(minutes=minutes) > return_cutoff
        ):
            blockers.append(
                _blocker(
                    "ATTRACTION_RETAINED_UNSCHEDULED",
                    "web",
                    reason=(
                        f"{attraction.get('name')}在返程候车前没有足够时间，"
                        "保留为未排入候选"
                    ),
                    evidence_refs=[evidence_id],
                )
            )
            continue
        matching_route = next(
            (
                route
                for route in local_routes
                if (
                    str(attraction.get("name") or "")
                    in str(route.get("to") or "")
                    or str(route.get("to") or "")
                    in str(
                        attraction.get("route_query_name")
                        or attraction.get("name")
                        or ""
                    )
                )
            ),
            None,
        )
        if matching_route is not None:
            matching_route["reference_only"] = False
            route_duration = int(
                matching_route.get("duration_seconds") or 0
            )
            route_end_at = start_at - timedelta(minutes=15)
            matching_route["start_at"] = (
                route_end_at - timedelta(seconds=route_duration)
            ).isoformat(timespec="minutes")
            matching_route["end_at"] = route_end_at.isoformat(
                timespec="minutes"
            )
            _add_event(days, matching_route)
            route_end = matching_route.get("end_at")
            if isinstance(route_end, str):
                start_at = max(
                    start_at,
                    datetime.fromisoformat(route_end)
                    + timedelta(minutes=15),
                )
                latest_lunch_start = datetime.combine(
                    start_at.date(),
                    lunch_window_end,
                ) - timedelta(
                    minutes=(
                        lunch_minutes
                        + inter_event_buffer_minutes
                    )
                )
                minutes = min(
                    minutes,
                    max(
                        30,
                        int(
                            (
                                latest_lunch_start - start_at
                            ).total_seconds()
                            // 60
                        ),
                    ),
                )
        else:
            blockers.append(
                _blocker(
                    "ATTRACTION_TRANSIT_MISSING",
                    "map",
                    reason=(
                        f"{attraction.get('name')}缺少对应的到达交通证据"
                    ),
                    # 引用 map 域证据：缺的是到达交通事实，与 domain 一致。
                    evidence_refs=_evidence_ref(map_item),
                )
            )
        end_at = min(start_at + timedelta(minutes=minutes), latest)
        payload = {
            "id": str(
                attraction.get("attraction_id")
                or attraction.get("id")
            ),
            "name": str(attraction.get("name")),
            "features": deepcopy(attraction.get("features", [])),
            "suitable_for": deepcopy(
                attraction.get("suitable_for", [])
            ),
            "scheduling_traits": deepcopy(
                attraction.get("scheduling_traits", [])
            ),
            "opening_hours": deepcopy(
                attraction.get(
                    "opening_hours",
                    {"status": "unknown"},
                )
            ),
            "ticket": deepcopy(
                attraction.get("ticket", {"status": "unknown"})
            ),
        }
        event = make_attraction_event(
            event_id=f"attraction-{payload['id']}",
            attraction=payload,
            start_at=start_at,
            end_at=end_at,
            phase="游览",
            why="按已取得的景点证据编入条件化日程",
        )
        event["location"] = deepcopy(
            attraction.get("location")
            or {
                "name": attraction.get("name"),
                "kind": "attraction",
            }
        )
        event["evidence_dependencies"] = [evidence_id]
        # 景点事件出自该景点的字段级事实；到达交通由 inbound 事件自己引用。
        event["fact_refs"] = list(attraction_refs)
        event["inbound_transit_event_id"] = (
            matching_route.get("event_id")
            if matching_route is not None
            else None
        )
        _add_event(days, event)
        events_by_type["attraction"].append(event)
        dependencies["attraction"].append(evidence_id)
        return_route = next(
            (
                route
                for route in local_routes
                if (
                    str(attraction.get("name") or "")
                    in str(route.get("from") or "")
                    and route is not matching_route
                )
            ),
            None,
        )
        if return_route is not None:
            route_start = end_at + timedelta(
                minutes=inter_event_buffer_minutes
            )
            route_duration = int(
                return_route.get("duration_seconds") or 0
            )
            route_end = route_start + timedelta(seconds=route_duration)
            if return_cutoff is None or route_end <= return_cutoff:
                return_route["reference_only"] = False
                return_route["start_at"] = route_start.isoformat(
                    timespec="minutes"
                )
                return_route["end_at"] = route_end.isoformat(
                    timespec="minutes"
                )
                _add_event(days, return_route)


def _compile_defaults(
    *,
    earliest: datetime,
    latest: datetime,
    defaults: Mapping[str, object],
    hotel_area: str | None,
    web_evidence_refs: Sequence[str],
    plan_refs: _PlanRefs,
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
    blockers: list[dict[str, object]],
) -> None:
    # 现算，不写死。此前这里是全模块唯一把 evidence_id 当常量写的地方——
    # 其余五个分支都做 ``str(evidence.get("evidence_id"))``，而本函数是唯一
    # 拿不到证据表的分支，于是作者按当时的生产点把名字抄了进来。抄来的名字
    # 只在实采路径成立：采集器未配置走 ``{domain}-{uuid4()}``，提交面
    # （HTTP / MCP 的 submit_evidence）由调用方给 id，夹具走 ``{domain}-{state}``。
    user_dependency = list(plan_refs.user_evidence)
    if hotel_area is None:
        blockers.append(
            _blocker(
                "HOTEL_SELECTION_MISSING",
                "web",
                evidence_refs=web_evidence_refs,
            )
        )
        hotel_area = "住宿地点待用户确认"
    else:
        blockers.append(
            _blocker(
                "HOTEL_DETAIL_PENDING",
                "web",
                severity="advisory",
                reason=(
                    "具体酒店未选择，当前使用住宿片区或交通枢纽；"
                    "首末段交通待酒店确定后细化"
                ),
                evidence_refs=web_evidence_refs,
            )
        )

    arrival = _rail_time(events_by_type["transit"], "rail-outbound", "end_at")
    if arrival is not None:
        arrival_station = _rail_field(
            events_by_type["transit"],
            "rail-outbound",
            "to",
        )
        buffer_event = make_duration_event(
            event_id="arrival-buffer",
            event_type="buffer",
            name="抵达后缓冲",
            start_at=arrival,
            minutes=int(defaults["arrival_buffer_minutes"]),
            why="使用可编辑的Planner到站缓冲默认约束",
            adjustable=("duration_minutes",),
            extra={"location": arrival_station or "抵达车站"},
        )
        buffer_event["evidence_dependencies"] = [
            *plan_refs.rail_evidence,
            *user_dependency,
        ]
        # 到站缓冲的起点是车次到站时刻——那份事实过期，这个缓冲就不再成立。
        buffer_event["fact_refs"] = [
            *plan_refs.rail_arrival,
            *plan_refs.intent_window,
        ]
        _add_event(days, buffer_event)
        events_by_type["buffer"].append(buffer_event)
        dependencies["buffer"].extend(buffer_event["evidence_dependencies"])
        checkin = make_duration_event(
            event_id="hotel-checkin",
            event_type="hotel",
            name="住宿办理",
            start_at=datetime.fromisoformat(str(buffer_event["end_at"])),
            minutes=int(defaults["hotel_checkin_minutes"]),
            why="使用可编辑的Planner入住默认约束",
            adjustable=("start_at", "duration_minutes", "hotel_choice"),
            extra={"location": hotel_area},
        )
        checkin["evidence_dependencies"] = list(user_dependency)
        checkin["fact_refs"] = [
            *plan_refs.hotel_area,
            *plan_refs.intent_window,
        ]
        _add_event(days, checkin)
        events_by_type["hotel"].append(checkin)
        dependencies["hotel"].extend(user_dependency)

    departure = _rail_time(
        events_by_type["transit"],
        "rail-return",
        "start_at",
    )
    if departure is not None:
        wait_start = departure - timedelta(
            minutes=int(defaults["rail_wait_minutes"])
        )
        checkout_start = wait_start - timedelta(
            minutes=int(defaults["hotel_checkout_minutes"])
        )
        checkout = make_duration_event(
            event_id="hotel-checkout",
            event_type="hotel",
            name="退房",
            start_at=checkout_start,
            minutes=int(defaults["hotel_checkout_minutes"]),
            why="使用可编辑的Planner退房默认约束",
            adjustable=("start_at", "duration_minutes", "hotel_choice"),
            extra={"location": hotel_area},
        )
        checkout["evidence_dependencies"] = list(user_dependency)
        checkout["fact_refs"] = [
            *plan_refs.rail_departure,
            *plan_refs.hotel_area,
            *plan_refs.intent_window,
        ]
        _add_event(days, checkout)
        events_by_type["hotel"].append(checkout)
        dependencies["hotel"].extend(user_dependency)
        wait = make_event(
            event_id="rail-wait-buffer",
            event_type="buffer",
            name="高铁候车",
            start_at=wait_start,
            end_at=departure,
            why="使用可编辑的Planner高铁候车默认约束",
            value_origin="planner_default",
            adjustable=("duration_minutes",),
            extra={
                "location": _rail_field(
                    events_by_type["transit"],
                    "rail-return",
                    "from",
                ) or "返程车站",
                "evidence_dependencies": [
                    *plan_refs.rail_evidence,
                    *user_dependency,
                ]
            },
        )
        wait["fact_refs"] = [
            *plan_refs.rail_departure,
            *plan_refs.intent_window,
        ]
        _add_event(days, wait)
        events_by_type["buffer"].append(wait)
        dependencies["buffer"].extend(wait["evidence_dependencies"])

    for attraction in list(events_by_type["attraction"]):
        end_value = attraction.get("end_at")
        attraction_id = attraction.get("attraction_id")
        if not isinstance(end_value, str) or not isinstance(
            attraction_id,
            str,
        ):
            continue
        start_at = datetime.fromisoformat(end_value)
        buffer_end = start_at + timedelta(
            minutes=int(defaults["inter_event_buffer_minutes"])
        )
        day = next(
            (
                item
                for item in days
                if item["date"] == start_at.date().isoformat()
            ),
            None,
        )
        occupied = (
            [
                value
                for value in day["events"]
                if value is not attraction
                and isinstance(value.get("start_at"), str)
                and isinstance(value.get("end_at"), str)
            ]
            if day is not None
            else []
        )
        if any(
            datetime.fromisoformat(str(value["start_at"])) < buffer_end
            and datetime.fromisoformat(str(value["end_at"])) > start_at
            for value in occupied
        ):
            continue
        buffer_event = make_event(
            event_id=f"activity-buffer-{attraction_id}",
            event_type="buffer",
            name="活动间缓冲",
            start_at=start_at,
            end_at=buffer_end,
            why="使用可编辑的Planner活动间缓冲默认约束",
            value_origin="planner_default",
            adjustable=("duration_minutes",),
            extra={
                "remove_with_attraction_id": attraction_id,
                "location": deepcopy(attraction.get("location")),
                "evidence_dependencies": list(user_dependency),
                # 它依附于某个景点事件而存在，引用跟着那个景点的事实走。
                "fact_refs": [
                    *(attraction.get("fact_refs") or []),
                    *plan_refs.intent_window,
                ],
            },
        )
        _add_event(days, buffer_event)
        events_by_type["buffer"].append(buffer_event)
        dependencies["buffer"].extend(user_dependency)

    def scheduled_meal_start(
        day: Mapping[str, object],
        preferred: datetime,
        minutes: int,
        window_end: datetime | None,
    ) -> tuple[datetime, str | None] | None:
        cursor = max(preferred, earliest)
        events = sorted(
            (
                value
                for value in day["events"]
                if isinstance(value.get("start_at"), str)
                and isinstance(value.get("end_at"), str)
            ),
            key=lambda value: str(value["start_at"]),
        )
        while True:
            end = cursor + timedelta(minutes=minutes)
            overlap = next(
                (
                    value
                    for value in events
                    if datetime.fromisoformat(str(value["start_at"])) < end
                    and datetime.fromisoformat(str(value["end_at"])) > cursor
                ),
                None,
            )
            if overlap is None:
                if end <= latest and (
                    window_end is None or end <= window_end
                ):
                    return cursor, None
                break
            cursor = datetime.fromisoformat(str(overlap["end_at"]))
            if window_end is not None and cursor + timedelta(
                minutes=minutes
            ) > window_end:
                break
        rail = next(
            (
                value
                for value in events
                if str(value.get("event_id"))
                in {"rail-outbound", "rail-return"}
                and datetime.fromisoformat(str(value["start_at"]))
                <= preferred
                < datetime.fromisoformat(str(value["end_at"]))
            ),
            None,
        )
        if rail is not None:
            rail_start = datetime.fromisoformat(str(rail["start_at"]))
            rail_end = datetime.fromisoformat(str(rail["end_at"]))
            meal_at = max(
                rail_start,
                min(preferred, rail_end - timedelta(minutes=minutes)),
            )
            if meal_at + timedelta(minutes=minutes) <= rail_end:
                return meal_at, str(rail["event_id"])
        return None

    for day_index, day in enumerate(days):
        date_value = datetime.fromisoformat(str(day["date"])).date()
        meal_specs = (
            (
                "breakfast",
                time(8, 0),
                int(defaults["breakfast_minutes"]),
                None,
            ),
            (
                "lunch",
                time.fromisoformat(str(defaults["lunch_window_start"])),
                int(defaults["lunch_minutes"]),
                time.fromisoformat(str(defaults["lunch_window_end"])),
            ),
            (
                "dinner",
                time.fromisoformat(str(defaults["dinner_window_start"])),
                int(defaults["dinner_minutes"]),
                time.fromisoformat(str(defaults["dinner_window_end"])),
            ),
        )
        for meal_kind, preferred_clock, minutes, end_clock in meal_specs:
            preferred = datetime.combine(date_value, preferred_clock)
            window_end = (
                datetime.combine(date_value, end_clock)
                if end_clock is not None
                else datetime.combine(date_value, time(10, 0))
            )
            slot = scheduled_meal_start(
                day,
                preferred,
                minutes,
                window_end,
            )
            if slot is None:
                continue
            meal_at, overlaps_event_id = slot
            meal = make_meal_event(
                event_id=f"meal-{meal_kind}-{day_index + 1}",
                meal_kind=meal_kind,
                start_at=meal_at,
                minutes=minutes,
                location=(
                    "列车上（餐食待用户准备）"
                    if overlaps_event_id is not None
                    else _meal_location(
                        meal_at,
                        transit_events=events_by_type["transit"],
                        hotel_area=hotel_area,
                    )
                ),
                why="使用可编辑的Planner餐食默认约束；金额保持unknown",
            )
            if overlaps_event_id is not None:
                meal["overlaps_event_id"] = overlaps_event_id
            meal["evidence_dependencies"] = list(user_dependency)
            meal["fact_refs"] = list(plan_refs.intent_window)
            _add_event(days, meal)
            events_by_type["meal"].append(meal)
            dependencies["meal"].extend(user_dependency)

        if day_index < len(days) - 1:
            rest_start = datetime.combine(date_value, time(22, 0))
            rest_end = datetime.combine(
                date_value + timedelta(days=1),
                time(7, 0),
            )
            if rest_start < latest and rest_end > earliest:
                rest = make_event(
                    event_id=f"rest-{day_index + 1}",
                    event_type="rest",
                    name="夜间休息",
                    start_at=max(rest_start, earliest),
                    end_at=min(rest_end, latest),
                    why="使用可编辑的Planner休息默认约束",
                    value_origin="planner_default",
                    adjustable=("start_at", "end_at"),
                    extra={
                        "location": hotel_area,
                        "evidence_dependencies": list(user_dependency),
                        "fact_refs": list(plan_refs.intent_window),
                    },
                )
                _add_event(days, rest)
                events_by_type["rest"].append(rest)
                dependencies["rest"].extend(user_dependency)


def _record_evidence_blockers(
    evidence: Mapping[str, Mapping[str, object]],
    blockers: list[dict[str, object]],
) -> None:
    # persistence-v2.md §7.1：三个触发条件合并为一个 blocker_id。规划层的后果
    # 是同一个——这个域没有可用输入，规划无法据此推进。至于是压根没这个域、
    # 没采到、还是采到了打架，是**证据层**的区分，消费方顺着 fact_id 读该事实
    # 的 token 得知；在 blocker_id 里复述一遍正是命名原则要消灭的东西。
    # 触发条件三分不变，只是三支产同一个 id。
    for domain in ("railway", "map", "web"):
        item = evidence.get(domain)
        if item is None:
            # 该域压根没有证据，没有可指的事实——省掉引用而不是写个空的。
            blockers.append(
                _blocker(f"{domain.upper()}_INPUT_UNAVAILABLE", domain)
            )
        elif item.get("status") == "missing":
            blockers.append(
                _blocker(
                    f"{domain.upper()}_INPUT_UNAVAILABLE",
                    domain,
                    reason=item.get("missing_reason"),
                    evidence_refs=_evidence_ref(item),
                )
            )
        elif item.get("status") == "conflicting":
            blockers.append(
                _blocker(
                    f"{domain.upper()}_INPUT_UNAVAILABLE",
                    domain,
                    evidence_refs=_evidence_ref(item),
                )
            )


def _rail_field(
    events: list[dict[str, object]],
    event_id: str,
    field_name: str,
) -> object:
    event = next(
        (value for value in events if value.get("event_id") == event_id),
        None,
    )
    return event.get(field_name) if isinstance(event, Mapping) else None


def _meal_location(
    moment: datetime,
    *,
    transit_events: list[dict[str, object]],
    hotel_area: str,
) -> str:
    outbound = next(
        (
            value
            for value in transit_events
            if value.get("event_id") == "rail-outbound"
        ),
        None,
    )
    returning = next(
        (
            value
            for value in transit_events
            if value.get("event_id") == "rail-return"
        ),
        None,
    )
    if isinstance(outbound, Mapping):
        departure = outbound.get("start_at")
        arrival = outbound.get("end_at")
        if isinstance(departure, str) and moment < datetime.fromisoformat(
            departure
        ):
            return str(outbound.get("from") or "出发地")
        if (
            isinstance(arrival, str)
            and moment < datetime.fromisoformat(arrival)
        ):
            return "列车上（餐食待用户准备）"
    if isinstance(returning, Mapping):
        departure = returning.get("start_at")
        arrival = returning.get("end_at")
        if (
            isinstance(departure, str)
            and isinstance(arrival, str)
            and datetime.fromisoformat(departure)
            <= moment
            < datetime.fromisoformat(arrival)
        ):
            return "列车上（餐食待用户准备）"
        if isinstance(arrival, str) and moment >= datetime.fromisoformat(
            arrival
        ):
            return str(returning.get("to") or "返回地")
    return hotel_area


def _compile_free_time(
    *,
    earliest: datetime,
    latest: datetime,
    hotel_area: str | None,
    plan_refs: _PlanRefs,
    days: list[dict[str, object]],
    events_by_type: dict[str, list[dict[str, object]]],
    dependencies: dict[str, list[str]],
) -> None:
    """Make daytime gaps visible without treating them as attractions."""

    dependency = list(plan_refs.user_evidence)
    base = hotel_area or "当日所在地"
    for day in days:
        day_date = datetime.fromisoformat(str(day["date"])).date()
        window_start = max(
            earliest,
            datetime.combine(day_date, time(9, 0)),
        )
        window_end = min(
            latest,
            datetime.combine(day_date, time(18, 0)),
        )
        if window_end <= window_start:
            continue
        occupied: list[tuple[datetime, datetime]] = []
        for event in day["events"]:
            start = event.get("start_at")
            end = event.get("end_at")
            if not isinstance(start, str) or not isinstance(end, str):
                continue
            start_at = max(window_start, datetime.fromisoformat(start))
            end_at = min(window_end, datetime.fromisoformat(end))
            if end_at > start_at:
                occupied.append((start_at, end_at))
        occupied.sort()
        merged: list[tuple[datetime, datetime]] = []
        for start_at, end_at in occupied:
            if not merged or start_at > merged[-1][1]:
                merged.append((start_at, end_at))
            else:
                merged[-1] = (
                    merged[-1][0],
                    max(merged[-1][1], end_at),
                )
        cursor = window_start
        gap_index = 0
        for start_at, end_at in [*merged, (window_end, window_end)]:
            if (start_at - cursor).total_seconds() >= 30 * 60:
                gap_index += 1
                free = make_event(
                    event_id=f"free-day-{day['day']}-{gap_index}",
                    event_type="rest",
                    name="自由活动 / 休息",
                    start_at=cursor,
                    end_at=start_at,
                    why="日程空档显式保留，可由用户调整",
                    value_origin="rule_derived",
                    adjustable=("start_at", "end_at"),
                    extra={
                        "location": base,
                        "free_time": True,
                        "evidence_dependencies": list(dependency),
                        "fact_refs": list(plan_refs.intent_window),
                    },
                )
                _add_event(days, free)
                events_by_type["rest"].append(free)
                dependencies["rest"].extend(dependency)
            cursor = max(cursor, end_at)


def _compiled_map_points(
    map_item: Mapping[str, object] | None,
    web_item: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    values = [
        deepcopy(dict(item))
        for item in _value_list(map_item, "map_points")
    ]
    if not _is_usable(web_item):
        return values
    web_value = usable_fact_values(item_facts(web_item))
    if not web_value:
        return values
    raw_web_points = web_value.get("map_points")
    if isinstance(raw_web_points, list):
        values.extend(
            deepcopy(dict(item))
            for item in raw_web_points
            if isinstance(item, Mapping)
        )
    for collection, kind in (
        (web_value.get("attractions"), "attraction"),
        (web_value.get("hotel_candidates"), "hotel_candidate"),
    ):
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, Mapping):
                continue
            position = item.get("location")
            if not isinstance(position, Mapping):
                continue
            values.append(
                {
                    "name": item.get("name"),
                    "kind": kind,
                    "location": deepcopy(position),
                    **deepcopy(dict(position)),
                                "retrieved_at": web_value.get("retrieved_at"),
                }
            )
    base = web_value.get("hotel_area")
    if isinstance(base, Mapping):
        values.append(
            {
                "name": base.get("name"),
                "kind": "accommodation",
                "location": deepcopy(base.get("location")),
                "longitude": base.get("longitude"),
                "latitude": base.get("latitude"),
                "coordinate_system": base.get(
                    "coordinate_system",
                    "GCJ-02",
                ),
                        "retrieved_at": web_value.get("retrieved_at"),
            }
        )
    return values


def _evidence_by_domain(value: object) -> dict[str, Mapping[str, object]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
    ):
        raise ValueError("context evidence must be an array")
    result: dict[str, Mapping[str, object]] = {}
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("context evidence items must be objects")
        domain = item.get("domain")
        if isinstance(domain, str):
            result[domain] = item
    return result


def _value_list(
    evidence: Mapping[str, object] | None,
    key: str,
) -> list[Mapping[str, object]]:
    if not _is_usable(evidence):
        return []
    raw = usable_fact_values(item_facts(evidence)).get(key)
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _hotel_area(evidence: Mapping[str, object] | None) -> str | None:
    if not _is_usable(evidence):
        return None
    hotel = usable_fact_values(item_facts(evidence)).get("hotel_area")
    name = hotel.get("name") if isinstance(hotel, Mapping) else None
    return name.strip() if isinstance(name, str) and name.strip() else None


def _destination_resolved(
    map_item: Mapping[str, object] | None,
    web_item: Mapping[str, object] | None,
) -> bool:
    """Return true only when sourced evidence identifies the destination."""

    map_facts = item_facts(map_item)
    if _is_usable(map_item) and not any(
        is_confirmed_absent(fact.get("value")) for fact in map_facts
    ):
        destination = usable_fact_values(map_facts).get("destination")
        if isinstance(destination, Mapping) and any(
            isinstance(destination.get(field), str)
            and bool(str(destination[field]).strip())
            for field in ("name", "adcode", "provider_record_id")
        ):
            return True
    web_facts = item_facts(web_item)
    if _is_usable(web_item) and not any(
        is_confirmed_absent(fact.get("value")) for fact in web_facts
    ):
        name = usable_fact_values(web_facts).get("destination_official_name")
        if isinstance(name, str) and name.strip():
            return True
    return False


def _day_shells(
    earliest: datetime,
    latest: datetime,
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    cursor = earliest.date()
    while cursor <= latest.date():
        values.append(
            {
                "day": len(values) + 1,
                "date": cursor.isoformat(),
                "events": [],
                "conditions": [],
            }
        )
        cursor += timedelta(days=1)
    return values


def _add_event(
    days: list[dict[str, object]],
    event: dict[str, object],
) -> None:
    raw = event.get("start_at")
    if not isinstance(raw, str):
        return
    date_value = datetime.fromisoformat(raw).date().isoformat()
    day = next((item for item in days if item["date"] == date_value), None)
    if day is not None:
        day["events"].append(event)


def _bounded_time(
    earliest: datetime,
    latest: datetime,
    day_offset: int,
    clock: time,
) -> datetime:
    candidate = datetime.combine(
        earliest.date() + timedelta(days=day_offset),
        clock,
    )
    if candidate < earliest:
        return earliest
    if candidate >= latest:
        return latest - timedelta(minutes=1)
    return candidate


def _rail_time(
    events: Sequence[Mapping[str, object]],
    event_id: str,
    field: str,
) -> datetime | None:
    for event in events:
        if event.get("event_id") == event_id:
            raw = event.get(field)
            return datetime.fromisoformat(raw) if isinstance(raw, str) else None
    return None


def _wall_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError(f"{field} must be local wall time")
    return parsed


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value



_USABLE_STATUSES = frozenset({"sourced", "estimated"})


def _is_usable(evidence: Mapping[str, object] | None) -> bool:
    """该证据是否携带单一可用值（evidence-axes.md §1）。

    ``sourced`` 与 ``estimated`` 都携带；``missing`` 没有值；``conflicting``
    有多个互斥的值，取任何一个都是替用户做裁决。P3b 之前这七处直接与
    ``"sourced"`` 比较，那是三态时期「有值」的唯一说法。
    """

    return (
        evidence is not None
        and str(evidence.get("status")) in _USABLE_STATUSES
    )


def _evidence_ref(evidence: Mapping[str, object] | None) -> list[str]:
    """blocker 的 ``evidence_refs``：指向该域证据。

    引用是命名原则的另一半（persistence-v2.md §7.3）。``blocker_id`` 只说规划
    层后果，「为什么没有可用输入」由消费方顺着这个引用读该事实的 token 得知；
    只改名不补引用等于把那半边信息丢了。

    没有证据可指时返回空列表——``_blocker`` 会省掉这个键，而不是写一个指不到
    任何东西的空引用。
    """

    if not isinstance(evidence, Mapping):
        return []
    reference = str(evidence.get("evidence_id") or "").strip()
    return [reference] if reference else []


def _field_refs(
    evidence: Mapping[str, object] | None,
    *suffixes: str,
) -> list[str]:
    """按字段名后缀挑出字段级 ``fact_refs``。

    与事件的 ``fact_refs`` 同形（``<evidence_id>#<field>``），走的是
    ``evidence_projection.item_facts`` 已经算好的 ``fact_id``，不在这里自己拼——
    两侧各拼一套会让引用在读取时对不上（``evidence_core.fact_id`` 的文档说明）。
    """

    if not isinstance(evidence, Mapping):
        return []
    return [
        str(fact["fact_id"])
        for fact in item_facts(evidence)
        if str(fact.get("field", "")).endswith(suffixes)
    ]


def _blocker(
    blocker_id: str,
    domain: str,
    *,
    reason: object = None,
    severity: str = "conditional",
    evidence_refs: Sequence[str] = (),
    fact_refs: Sequence[str] = (),
) -> dict[str, object]:
    """构造一个 conditional blocker。

    **两个引用键，各有一个确定含义**（persistence-v2.md §7.4 的键名裁决）：

    * ``evidence_refs`` —— 指向整个证据项（``evidence_id``）。用在指代对象是
      「该域的裁断」时，包括该证据**没有任何字段级事实**的情形；
    * ``fact_refs`` —— 指向具体字段（``<evidence_id>#<field>``）。用在指代对象
      确实是某几个字段时。

    此前这里是一个单数 ``fact_id``，装的却是域级 ``evidence_id``——名实不符。
    不能靠「把值升成字段级」了结：``*_INPUT_UNAVAILABLE` 恰恰在证据 missing /
    unknown 时触发，那时 ``item_facts()`` 返回**空**，字段级引用会退化成空列表，
    把引用丢干净——而那正是最需要引用的一类 blocker。所以按语义分两个键，
    单数 ``fact_id`` 就此消失。
    """

    suggested_actions = {
        "railway": ["重新查询铁路", "手动填写车次"],
        "map": ["查询高德公交或路线"],
        "web": ["搜索景点、开放时间或住宿片区", "用户补充住宿基地"],
    }
    return {
        "blocker_id": blocker_id,
        "domain": domain,
        "severity": severity,
        # 裁决 8.2 / evidence-axes.md §5.5：结论层不复述证据状态，改为引用。
        # 消费方顺着引用读该事实的 token，得知是「没结论」还是「打架」。
        **({"evidence_refs": list(evidence_refs)} if evidence_refs else {}),
        **({"fact_refs": list(fact_refs)} if fact_refs else {}),
        "reason": reason,
        "suggested_actions": suggested_actions.get(
            domain,
            ["补充有效证据"],
        ),
    }


def _unique_blockers(
    blockers: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for blocker in blockers:
        blocker_id = str(blocker.get("blocker_id"))
        if blocker_id in seen:
            continue
        seen.add(blocker_id)
        result.append(deepcopy(dict(blocker)))
    return result


__all__ = ["PlanningInputCompiler"]
