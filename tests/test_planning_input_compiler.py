from __future__ import annotations

from dataclasses import replace
from trip_decider.evidence_projection import business_view

from datetime import datetime, timezone

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import trip_decider.agent_actions as agent_actions
import trip_decider.product_web as product_web
from trip_decider.agent_actions import (
    execute_registered_action,
    get_next_actions,
    run_until_blocked,
    start_action_loop,
    submit_evidence,
)
from trip_decider.planning_input_compiler import PlanningInputCompiler
from trip_decider.travel_agent import (
    DestinationContext,
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
    TravelIntent,
    confirm_intent,
    create_run,
)


def _intent(destination: str) -> TravelIntent:
    return TravelIntent.from_mapping(
        {
            "origin": "甲站",
            "destination_anchor": destination,
            "earliest_departure_at": "2026-08-04T12:00",
            "latest_return_at": "2026-08-07T22:00",
            "travelers": 2,
            "total_budget_cny": 6000,
            "pace": "relaxed",
            "transport_preferences": ["high_speed_rail"],
        }
    )


# 读取时刻钉死在夹具采集时刻之后 1 小时。不钉的话编译器读墙钟，而夹具时间戳
# 是写死的——两者差值每天在变，同一份夹具隔天会得到不同的 freshness。这与
# characterization_support.CHAR_NOW 是同一件事。
READ_AT = datetime(2026, 7, 30, 3, 44, tzinfo=timezone.utc)  # = 11:44+08:00


def _railway(acquisition: str = "live_fetch") -> EvidenceItem:
    retrieved_at = "2026-07-30T10:44:00+08:00"
    return EvidenceItem(
        evidence_id="railway-live-query",
        domain="railway",
        status=EvidenceStatus.SOURCED,
        value={
            "support": "sourced",
            "domain": "railway",
            "origin": "甲站",
            "destination": "乙站",
            "outbound": {
                "train_code": "G100",
                "origin_station": "甲站",
                "destination_station": "乙站",
                "departure_at": "2026-08-04T13:00",
                "arrival_at": "2026-08-04T16:00",
                "duration_seconds": 10800,
                "second_class_fare_cny_per_person": 200.0,
                "second_class_availability": "available",
            },
            "return": {
                "train_code": "G101",
                "origin_station": "乙站",
                "destination_station": "甲站",
                "departure_at": "2026-08-07T18:00",
                "arrival_at": "2026-08-07T21:00",
                "duration_seconds": 10800,
                "second_class_fare_cny_per_person": 200.0,
                "second_class_availability": "available",
            },
            "snapshot": {
                "acquisition": acquisition,
                "retrieved_at": retrieved_at,
                "attempted_at": retrieved_at,
                "availability_semantics": (
                    "current_at_retrieval_only"
                    if acquisition == "live_fetch"
                    else "not_current_availability"
                ),
            },
            "roundtrip_fare_cny": 800.0,
        },
        sources=(
            {
                "provider": "official-rail",
                "retrieved_at": retrieved_at,
            },
        ),
    )


def _map(destination: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="map-live-query",
        domain="map",
        status=EvidenceStatus.SOURCED,
        value={
            "destination": {"name": destination},
            "local_transit": [
                {
                    "route_id": "local-route-1",
                    "from": "乙站",
                    "to": "住宿片区",
                    "duration_seconds": 1800,
                    "distance_meters": 12000,
                    "fare": {"status": "unknown", "amount_cny": None},
                },
                {
                    "route_id": "local-route-2",
                    "from": "住宿片区",
                    "to": "景点甲",
                    "duration_seconds": 1200,
                    "distance_meters": 6000,
                    "fare": {"status": "unknown", "amount_cny": None},
                }
            ],
        },
        sources=({"provider": "official-map"},),
    )


def _web(destination: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="web-official-query",
        domain="web",
        status=EvidenceStatus.SOURCED,
        value={
            "destination_official_name": destination,
            "verified_facts": [
                {
                    "field": "official_administrative_name",
                    "value": destination,
                }
            ],
            "attractions": [
                {
                    "attraction_id": "spot-1",
                    "name": "景点甲",
                    "visit_minutes": 90,
                }
            ],
            "hotel_area": {"name": "住宿片区"},
        },
        sources=({"publisher": "official-web"},),
    )


def _loop_evidence(run_id: str, store) -> dict:
    """容器 B（动作循环的证据表）。

    A 收敛后 `result["context"]` 不再内联证据，取证据要从这里
    （persistence-v2.md §2.1.1）。用内存态而非盘上那份，因为部分用例的 store
    没有 runtime_root，盘上根本没有文件。
    """

    state = agent_actions._state(run_id, store)
    return {
        domain: item.to_dict() for domain, item in state.evidence.items()
    }


def _planning_state(run_id, store, result):
    return agent_actions.recomputed_planning_state(
        result,
        _loop_evidence(run_id, store),
    )


class PlanningInputCompilerTests(unittest.TestCase):
    def test_two_destinations_use_one_generic_compiler_path(self) -> None:
        signatures = []
        for destination in ("乙地", "丙地"):
            context = DestinationContext(
                context_id=f"context-{destination}",
                intent=_intent(destination),
                evidence=(
                    EvidenceItem(
                        evidence_id="user",
                        domain="user_input",
                        status=EvidenceStatus.SOURCED,
                        value=_intent(destination).to_dict(),
                        sources=({"source_type": "user_supplied"},),
                    ),
                    _railway(),
                    _map(destination),
                    _web(destination),
                ),
                built_at="2026-07-30T11:00:00+08:00",
            )
            compiled = PlanningInputCompiler().compile(context, now=READ_AT)
            event_types = {
                event["type"]
                for day in compiled["days"]
                for event in day["events"]
            }
            self.assertEqual(
                event_types,
                {
                    "transit",
                    "attraction",
                    "meal",
                    "hotel",
                    "buffer",
                    "rest",
                },
            )
            self.assertTrue(compiled["displayable"])
            self.assertEqual(compiled["planning_state"], "PLAN_READY")
            self.assertEqual(
                [
                    blocker["blocker_id"]
                    for blocker in compiled["conditional_blockers"]
                ],
                ["HOTEL_DETAIL_PENDING"],
            )
            signatures.append(
                [
                    event["type"]
                    for day in compiled["days"]
                    for event in day["events"]
                ]
            )
        self.assertEqual(signatures[0], signatures[1])

    def test_partial_context_keeps_supported_events_and_blockers(self) -> None:
        intent = _intent("乙地")
        context = DestinationContext(
            context_id="context-partial",
            intent=intent,
            evidence=(
                EvidenceItem(
                    evidence_id="user",
                    domain="user_input",
                    status=EvidenceStatus.SOURCED,
                    value=intent.to_dict(),
                    sources=({"source_type": "user_supplied"},),
                ),
                _railway("cache_fallback"),
                EvidenceItem(
                    evidence_id="map-missing",
                    domain="map",
                    status=EvidenceStatus.MISSING,
                    value=None,
                    missing_reason="map_http",
                ),
                EvidenceItem(
                    evidence_id="web-missing",
                    domain="web",
                    status=EvidenceStatus.MISSING,
                    value=None,
                    missing_reason="official_page_unavailable",
                ),
            ),
            built_at="2026-07-30T11:00:00+08:00",
        )
        compiled = PlanningInputCompiler().compile(context, now=READ_AT)
        self.assertEqual(
            compiled["status"],
            "PARTIAL_PLAN_WITH_BLOCKERS",
        )
        self.assertTrue(compiled["days"])
        rail_events = [
            event
            for day in compiled["days"]
            for event in day["events"]
            if event.get("event_id") in {"rail-outbound", "rail-return"}
        ]
        self.assertEqual(len(rail_events), 2)
        self.assertTrue(compiled["conditional_blockers"])
        self.assertFalse(compiled["displayable"])

    def test_failed_refresh_retains_stale_snapshot_in_same_run(self) -> None:
        store = InMemoryAgentStore()
        run = create_run(_intent("乙地"), store=store)
        confirm_intent(run.run_id, store=store)
        start_action_loop(run.run_id, store=store)
        with patch(
            "trip_decider.agent_actions.collect_railway_evidence",
            return_value=_railway(),
        ):
            execute_registered_action(run.run_id, "railway", store=store)

        failed_refresh = EvidenceItem(
            evidence_id="railway-live-query",
            domain="railway",
            status=EvidenceStatus.MISSING,
            value={
                "attempted_at": "2026-07-30T11:05:00+08:00",
                "failure": {"stage": "rail_http", "http_status": 503},
            },
            missing_reason="rail_http",
        )
        with patch(
            "trip_decider.agent_actions.collect_railway_evidence",
            return_value=failed_refresh,
        ):
            refreshed = execute_registered_action(
                run.run_id,
                "railway",
                store=store,
            )
        self.assertNotEqual(refreshed["status"], "BLOCKED")

        submit_evidence(
            run.run_id,
            {**_web("乙地").to_dict(), "action_id": "web"},
            store=store,
        )
        with patch(
            "trip_decider.agent_actions.collect_map_evidence",
            return_value=_map("乙地"),
        ):
            execute_registered_action(run.run_id, "map", store=store)
        ready = execute_registered_action(
            run.run_id,
            "planner",
            store=store,
        )
        self.assertEqual(ready["status"], "READY")
        railway = _loop_evidence(run.run_id, store)["railway"]
        self.assertEqual(business_view(railway)["snapshot"]["acquisition"], "cache_fallback")
        # 余票 support 为 unknown 后**字段缺席**，不是留一个 "UNKNOWN"
        # 字面量——不可知的字段不得保留旧值，也不该假装有值。
        self.assertNotIn(
            "second_class_availability",
            business_view(railway)["outbound"],
        )
        # 展示态字段已停止落盘（P4-b3）；陈旧与否读时算。
        self.assertNotIn(
            "schedule_status",
            business_view(railway)["outbound"],
        )
        # 展示态字段已停止落盘（P4-b3）；陈旧与否读时算。
        self.assertNotIn(
            "fare_status",
            business_view(railway)["outbound"],
        )
        self.assertNotIn(
            "second_class_availability",
            business_view(railway)["return"],
        )
        self.assertEqual(
            ready["result"]["plan"]["status"],
            "PARTIAL_PLAN_WITH_BLOCKERS",
        )
        # planning_state / displayable 不再落盘（会随 now 变，写进盘就是 I5
        # 违反）。判定改由读取时重算——同一个判定，换了产出时机。
        self.assertEqual(
            _planning_state(run.run_id, store, ready["result"]),
            "PARTIAL_READY",
        )
        self.assertIn(
            "具体酒店未选择",
            ready["result"]["plan"]["accommodation_notice"],
        )
        rail_events = [
            event
            for day in ready["result"]["plan"]["days"]
            for event in day["events"]
            if event.get("event_id") in {"rail-outbound", "rail-return"}
        ]
        # 断言换语义：票价不再自带 status。旧代码在陈旧快照上把 fare.status
        # 盖成 "stale"，那是把 freshness 冻进计划里；现在票价只是一个数，
        # 它的可靠性由 fact_refs 指向的 fact 在读取时决定。
        self.assertTrue(rail_events)
        for event in rail_events:
            self.assertNotIn("status", event["fare"])
            self.assertTrue(event["fact_refs"])
        self.assertTrue(ready["result"]["plan"]["days"])

    def test_meal_and_rest_shell_is_not_a_displayable_itinerary(self) -> None:
        intent = _intent("乙地")
        context = DestinationContext(
            context_id="context-shell-only",
            intent=intent,
            evidence=(
                EvidenceItem(
                    evidence_id="user",
                    domain="user_input",
                    status=EvidenceStatus.SOURCED,
                    value=intent.to_dict(),
                    sources=({"source_type": "user_supplied"},),
                ),
                EvidenceItem(
                    evidence_id="rail-missing",
                    domain="railway",
                    status=EvidenceStatus.MISSING,
                    value=None,
                    missing_reason="rail_http",
                ),
                EvidenceItem(
                    evidence_id="map-missing",
                    domain="map",
                    status=EvidenceStatus.MISSING,
                    value=None,
                    missing_reason="map_http",
                ),
                EvidenceItem(
                    evidence_id="web-missing",
                    domain="web",
                    status=EvidenceStatus.MISSING,
                    value=None,
                    missing_reason="web_unavailable",
                ),
            ),
            built_at="2026-07-30T11:00:00+08:00",
        )
        compiled = PlanningInputCompiler().compile(context, now=READ_AT)
        self.assertFalse(compiled["displayable"])
        self.assertEqual(
            compiled["display_requirements"],
            {
                "destination_resolved": False,
                "outbound_transport": False,
                "return_transport": False,
                "attraction": False,
                "local_transit": False,
                "attraction_transit_coverage": False,
                "accommodation_base": False,
                "hard_constraints_clear": True,
                "cross_city_transport": False,
            },
        )
        self.assertEqual(compiled["planning_state"], "COLLECTING_EVIDENCE")
        self.assertEqual(compiled["artifact_kind"], "PlanningDraft")
        self.assertTrue(compiled["meal_events"])
        self.assertTrue(compiled["rest_events"])
        with TemporaryDirectory() as temporary:
            store = InMemoryAgentStore(Path(temporary) / "sessions")
            run = create_run(intent, store=store)
            confirm_intent(run.run_id, store=store)
            start_action_loop(run.run_id, store=store)
            for item in context.evidence:
                if item.domain not in {"railway", "map", "web"}:
                    continue
                submit_evidence(
                    run.run_id,
                    {**item.to_dict(), "action_id": item.domain},
                    store=store,
                )
            result = execute_registered_action(
                run.run_id,
                "planner",
                store=store,
            )
            self.assertEqual(result["status"], "NEED_USER_INPUT")
            self.assertNotIn("plan", result["result"])
            self.assertTrue(
                result["result"]["planning_draft"]["planning_input"][
                    "meal_events"
                ]
            )
            self.assertTrue(
                result["result"]["planning_draft"]["planning_input"][
                    "rest_events"
                ]
            )
            self.assertFalse(
                (store.run_directory(run.run_id) / "plan-version.json").exists()
            )

    def test_missing_required_attraction_transit_keeps_draft_uninstalled(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            store = InMemoryAgentStore(Path(temporary) / "sessions")
            run = create_run(_intent("乙地"), store=store)
            confirm_intent(run.run_id, store=store)
            start_action_loop(run.run_id, store=store)
            # 在 EvidenceItem 层裁剪，不改落盘 dict——v2 的 value 是 facts
            # 数组，业务键不在顶层。
            full_map = _map("乙地")
            trimmed = dict(full_map.value)
            trimmed["local_transit"] = trimmed["local_transit"][:1]
            incomplete_map = replace(full_map, value=trimmed).to_dict()
            for action_id, item in (
                ("railway", _railway().to_dict()),
                ("web", _web("乙地").to_dict()),
                ("map", incomplete_map),
            ):
                submit_evidence(
                    run.run_id,
                    {**item, "action_id": action_id},
                    store=store,
                )
            result = execute_registered_action(
                run.run_id,
                "planner",
                store=store,
            )
            self.assertEqual(result["status"], "NEED_USER_INPUT")
            self.assertEqual(
                _planning_state(run.run_id, store, result["result"]),
                "COLLECTING_EVIDENCE",
            )
            self.assertNotIn("plan", result["result"])
            draft = result["result"]["planning_draft"]
            self.assertEqual(draft["artifact_kind"], "PlanningDraft")
            inputs = draft["planning_input"]
            self.assertEqual(len(inputs["cross_city_rail_events"]), 2)
            self.assertEqual(len(inputs["attraction_events"]), 1)
            self.assertEqual(len(inputs["local_transit_events"]), 1)
            self.assertIn(
                "attraction_transit_coverage",
                draft["missing_requirements"],
            )
            self.assertIn(
                "local_transit_manual",
                {
                    action["action_id"]
                    for action in result["actions"]
                },
            )
            self.assertFalse(
                (store.run_directory(run.run_id) / "plan-version.json").exists()
            )
            with patch.object(
                product_web,
                "_CONFIGURED_STORE",
                store,
            ), patch.object(
                product_web,
                "get_next_actions",
                side_effect=lambda value: get_next_actions(
                    value,
                    store=store,
                ),
            ):
                response = product_web._run_response(run.run_id)
            self.assertIsNone(response["run"]["result"])
            self.assertEqual(response["presentation"]["day_count"], 0)
            self.assertEqual(response["presentation"]["event_count"], 0)
            self.assertIsNone(response["presentation"]["budget_summary"])
            self.assertEqual(
                response["presentation"]["map_payload"]["markers"],
                [],
            )
            self.assertEqual(
                response["presentation"]["map_payload"][
                    "route_polylines"
                ],
                [],
            )
            self.assertEqual(
                response["presentation"]["planning_draft"][
                    "collected_information"
                ]["attraction_count"],
                1,
            )

    def test_runtime_restart_restores_session_evidence_and_plan_version(
        self,
    ) -> None:
        # 这条走真实动作循环，读取时刻来自 agent_actions._READ_CLOCK（产品
        # 默认墙钟）。钉住它，理由同 READ_AT。
        agent_actions.set_read_clock(lambda: READ_AT)
        self.addCleanup(agent_actions.reset_read_clock)
        with TemporaryDirectory() as temporary:
            runtime_root = Path(temporary) / "sessions"
            store = InMemoryAgentStore(runtime_root)
            run = create_run(_intent("乙地"), store=store)
            confirm_intent(run.run_id, store=store)
            start_action_loop(run.run_id, store=store)
            submit_evidence(
                run.run_id,
                {**_railway().to_dict(), "action_id": "railway"},
                store=store,
            )
            submit_evidence(
                run.run_id,
                {**_web("乙地").to_dict(), "action_id": "web"},
                store=store,
            )

            agent_actions._STATES.pop(run.run_id, None)
            restored = InMemoryAgentStore(runtime_root)
            self.assertEqual(
                restored.get_run(run.run_id).status.value,
                "RUNNING",
            )
            actions = get_next_actions(run.run_id, store=restored)
            self.assertEqual(
                [action["action_id"] for action in actions["actions"]],
                ["map"],
            )
            submit_evidence(
                run.run_id,
                {**_map("乙地").to_dict(), "action_id": "map"},
                store=restored,
            )
            ready = execute_registered_action(
                run.run_id,
                "planner",
                store=restored,
            )
            self.assertEqual(ready["status"], "READY")
            self.assertEqual(
                _planning_state(run.run_id, store, ready["result"]),
                "PLAN_READY",
            )
            self.assertEqual(
                ready["result"]["plan"]["artifact_kind"],
                "PlanVersion",
            )

            run_directory = runtime_root / run.run_id
            for relative in (
                "session.json",
                "run.json",
                "events.jsonl",
                "action-loop.json",
                "evidence/namespace.json",
                "evidence/current.json",
                "plan-version.json",
                "plans/plan-0001.json",
            ):
                self.assertTrue((run_directory / relative).is_file())
            with patch.object(
                product_web,
                "_CONFIGURED_STORE",
                restored,
            ):
                installed = product_web._current_plan_response(run.run_id)
                response = product_web._run_response(run.run_id)
            # plan-version.json 不再落 planning_state——它是读取时刻的函数。
            # 落盘只保证结构完整（persistence-v2 §6.2）。
            self.assertNotIn("planning_state", installed)
            self.assertEqual(
                installed["plan"]["artifact_kind"],
                "PlanVersion",
            )
            self.assertGreater(response["presentation"]["day_count"], 0)
            self.assertIsNotNone(
                response["presentation"]["budget_summary"]
            )
            evidence = json.loads(
                (run_directory / "evidence" / "current.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                {item["domain"] for item in evidence["current"]},
                {"railway", "web", "map"},
            )

            agent_actions._STATES.pop(run.run_id, None)
            second_restart = InMemoryAgentStore(runtime_root)
            self.assertEqual(
                second_restart.get_run(run.run_id).status.value,
                "COMPLETED",
            )
            self.assertEqual(
                get_next_actions(run.run_id, store=second_restart)["status"],
                "READY",
            )

    def test_failed_refresh_after_restart_persists_stale_rail(self) -> None:
        with TemporaryDirectory() as temporary:
            runtime_root = Path(temporary) / "sessions"
            store = InMemoryAgentStore(runtime_root)
            run = create_run(_intent("乙地"), store=store)
            confirm_intent(run.run_id, store=store)
            start_action_loop(run.run_id, store=store)
            submit_evidence(
                run.run_id,
                {**_railway().to_dict(), "action_id": "railway"},
                store=store,
            )

            agent_actions._STATES.pop(run.run_id, None)
            restarted = InMemoryAgentStore(runtime_root)
            submit_evidence(
                run.run_id,
                {
                    "action_id": "railway",
                    "evidence_id": "rail-refresh-failed",
                    "domain": "railway",
                    "status": "missing",
                    "value": {
                        "attempted_at": "2026-07-30T12:00:00+08:00"
                    },
                    "sources": [],
                    "missing_reason": "rail_http",
                },
                store=restarted,
            )
            persisted = json.loads(
                (
                    runtime_root / run.run_id / "evidence" / "current.json"
                ).read_text(encoding="utf-8")
            )
            railway = next(
                item
                for item in persisted["current"]
                if item["domain"] == "railway"
            )
            self.assertEqual(
                business_view(railway)["snapshot"]["acquisition"],
                "cache_fallback",
            )
            # 余票 support 为 unknown 后**字段缺席**，不是留一个 "UNKNOWN"
            # 字面量——不可知的字段不得保留旧值，也不该假装有值。
            self.assertNotIn(
                "second_class_availability",
                business_view(railway)["outbound"],
            )

            agent_actions._STATES.pop(run.run_id, None)
            second_restart = InMemoryAgentStore(runtime_root)
            get_next_actions(run.run_id, store=second_restart)
            restored_state = agent_actions._state(
                run.run_id,
                second_restart,
            )
            self.assertEqual(
                restored_state.evidence["railway"].value["snapshot"][
                    "acquisition"
                ],
                "cache_fallback",
            )

    def test_completed_run_refreshes_in_place_and_keeps_stale_plan(
        self,
    ) -> None:
        store = InMemoryAgentStore()
        run = create_run(_intent("乙地"), store=store)
        confirm_intent(run.run_id, store=store)
        start_action_loop(run.run_id, store=store)
        for action_id, item in (
            ("railway", _railway()),
            ("web", _web("乙地")),
            ("map", _map("乙地")),
        ):
            submit_evidence(
                run.run_id,
                {**item.to_dict(), "action_id": action_id},
                store=store,
            )
        ready = execute_registered_action(
            run.run_id,
            "planner",
            store=store,
        )
        self.assertEqual(ready["status"], "READY")

        failed_refresh = EvidenceItem(
            evidence_id="rail-refresh",
            domain="railway",
            status=EvidenceStatus.MISSING,
            value={
                "attempted_at": "2026-07-30T12:30:00+08:00",
            },
            missing_reason="rail_http",
        )
        with patch(
            "trip_decider.agent_actions.collect_railway_evidence",
            return_value=failed_refresh,
        ):
            resumed = execute_registered_action(
                run.run_id,
                "railway",
                store=store,
            )
        self.assertEqual(
            store.get_run(run.run_id).status.value,
            "RUNNING",
        )
        self.assertEqual(
            [action["action_id"] for action in resumed["actions"]],
            ["planner"],
        )
        refreshed = execute_registered_action(
            run.run_id,
            "planner",
            store=store,
        )
        self.assertEqual(refreshed["status"], "READY")
        self.assertEqual(refreshed["run_id"], run.run_id)
        railway = _loop_evidence(run.run_id, store)["railway"]
        self.assertEqual(
            business_view(railway)["snapshot"]["acquisition"],
            "cache_fallback",
        )
        # 余票 support 为 unknown 后**字段缺席**，不是留一个 "UNKNOWN"
        # 字面量——不可知的字段不得保留旧值，也不该假装有值。
        self.assertNotIn(
            "second_class_availability",
            business_view(railway)["outbound"],
        )

    def test_run_until_blocked_resumes_same_run_after_web_evidence(
        self,
    ) -> None:
        store = InMemoryAgentStore()
        run = create_run(_intent("乙地"), store=store)
        confirm_intent(run.run_id, store=store)
        start_action_loop(run.run_id, store=store)
        with patch(
            "trip_decider.agent_actions.collect_railway_evidence",
            return_value=_railway(),
        ):
            paused = run_until_blocked(run.run_id, store=store)
        self.assertEqual(paused["status"], "NEED_USER_INPUT")
        self.assertIn(
            "codex_web_research",
            paused["paused_at"],
        )

        submit_evidence(
            run.run_id,
            {**_web("乙地").to_dict(), "action_id": "web"},
            store=store,
        )
        with patch(
            "trip_decider.agent_actions.collect_map_evidence",
            return_value=_map("乙地"),
        ):
            ready = run_until_blocked(run.run_id, store=store)
        self.assertEqual(ready["status"], "READY")
        self.assertEqual(ready["run_id"], run.run_id)
        self.assertIn(
            _planning_state(run.run_id, store, ready["result"]),
            {"PARTIAL_READY", "PLAN_READY"},
        )

    def test_new_attractions_require_same_run_local_route_refresh(
        self,
    ) -> None:
        state = agent_actions._LoopState(
            evidence={
                "web": EvidenceItem(
                    evidence_id="web",
                    domain="web",
                    status=EvidenceStatus.SOURCED,
                    value={
                        "destination_official_name": "乙地区",
                        "hotel_area": {"name": "乙站"},
                        "verified_facts": [{"field": "identity"}],
                        "attractions": [
                            {"attraction_id": "a", "name": "景点甲"},
                            {"attraction_id": "b", "name": "景点乙"},
                            {"attraction_id": "c", "name": "景点丙"},
                        ],
                    },
                    sources=({"publisher": "official-test"},),
                ),
                "map": EvidenceItem(
                    evidence_id="map",
                    domain="map",
                    status=EvidenceStatus.SOURCED,
                    value={
                        "destination": {"adcode": "000000"},
                        "local_transit_input_signature": ["乙站", "景点甲"],
                        "local_transit": [
                            {
                                "route_id": "route-1",
                                "from": "乙站",
                                "to": "景点甲",
                                "duration_seconds": 600,
                            }
                        ],
                    },
                    sources=({"provider": "fake-map"},),
                ),
            }
        )
        self.assertTrue(agent_actions._needs_local_transit(state))

    def test_map_route_snapshot_replaces_old_signature_and_failure(
        self,
    ) -> None:
        previous = EvidenceItem(
            evidence_id="map-old",
            domain="map",
            status=EvidenceStatus.SOURCED,
            value={
                "destination": {"adcode": "000000"},
                "local_transit_input_signature": ["基地", "景点甲"],
                "local_transit_outcome": "FAILED",
                "local_transit_refresh_failure": {"stage": "poi_transport"},
                "local_transit": [
                    {
                        "route_id": "route-1",
                        "from": "基地",
                        "to": "景点甲",
                        "duration_seconds": 600,
                    }
                ],
            },
            sources=({"provider": "fake-map"},),
        )
        current = EvidenceItem(
            evidence_id="map-current",
            domain="map",
            status=EvidenceStatus.SOURCED,
            value={
                "destination": {"adcode": "000000"},
                "local_transit_input_signature": [
                    "基地",
                    "景点甲",
                    "景点乙",
                    "景点丙",
                ],
                "local_transit_outcome": "AVAILABLE",
                "local_transit": [
                    {
                        "route_id": f"route-{index}",
                        "from": f"地点{index}",
                        "to": f"地点{index + 1}",
                        "duration_seconds": 600,
                    }
                    for index in range(1, 4)
                ],
            },
            sources=({"provider": "fake-map"},),
        )
        merged = agent_actions._merge_sourced_evidence(previous, current)
        self.assertEqual(
            merged.value["local_transit_input_signature"],
            ["基地", "景点甲", "景点乙", "景点丙"],
        )
        self.assertEqual(len(merged.value["local_transit"]), 3)
        self.assertEqual(
            merged.value["local_transit_outcome"],
            "AVAILABLE",
        )
        self.assertNotIn("local_transit_refresh_failure", merged.value)


class EvidenceDependenciesResolveTests(unittest.TestCase):
    """``evidence_dependencies`` 里的每个 id 都必须在 context.evidence 里找得到。

    这是**引用可解析性**，不是行为——规划结论不看这个键（全仓唯一消费点是
    ``agent_actions._planner_handler`` 的原样拷贝），所以写错了没有任何东西会
    报错，只会在盘上留下一个指不到的名字。用例本身就是这个「没人会报错」的
    补位：D2 的消费点同表核对，机械化成一条断言。

    参数化两个 id 形状是要点。写死的字面量在**恰好那个形状**下是绿的——旧代码
    在实采路径下 ``railway-live-query`` 就解析得到，只有换个生产点才露馅。
    """

    _ID_SHAPES = (
        # 实采路径：destination_runtime 的两个分支都产这两个 id
        ("live", "confirmed-travel-intent", "railway-live-query"),
        # 采集器未配置：travel_agent.collect_destination_evidence 的 uuid 形状
        ("uuid", "user-3f1c", "railway-9ab2"),
        # 提交面：HTTP / MCP 的 submit_evidence 由调用方给 id
        ("submitted", "user", "railway-manual-entry"),
    )

    def _compile(self, user_id: str, railway_id: str) -> dict:
        railway = replace(_railway(), evidence_id=railway_id)
        context = DestinationContext(
            context_id="context-refs",
            intent=_intent("乙地"),
            evidence=(
                EvidenceItem(
                    evidence_id=user_id,
                    domain="user_input",
                    status=EvidenceStatus.SOURCED,
                    value=_intent("乙地").to_dict(),
                    sources=({"source_type": "user_supplied"},),
                ),
                railway,
                _map("乙地"),
                _web("乙地"),
            ),
            built_at="2026-07-30T11:00:00+08:00",
        )
        return PlanningInputCompiler().compile(context, now=READ_AT)

    @staticmethod
    def _referenced(compiled: dict) -> set[str]:
        seen: set[str] = set()
        for bucket in compiled["evidence_dependencies"].values():
            seen.update(str(value) for value in bucket)
        for key in (
            "cross_city_rail_events",
            "local_transit_events",
            "attraction_events",
            "meal_events",
            "hotel_events",
            "buffer_events",
            "rest_events",
        ):
            for event in compiled[key]:
                seen.update(
                    str(value)
                    for value in event.get("evidence_dependencies", ())
                )
        return seen

    def test_no_dependency_points_outside_the_context_evidence(self) -> None:
        for label, user_id, railway_id in self._ID_SHAPES:
            with self.subTest(shape=label):
                compiled = self._compile(user_id, railway_id)
                known = {
                    user_id,
                    railway_id,
                    "map-live-query",
                    "web-official-query",
                }
                self.assertEqual(
                    sorted(self._referenced(compiled) - known),
                    [],
                    f"{label}：这些 evidence_dependencies 在 context.evidence 里不存在",
                )

    def test_rail_derived_buffers_still_name_the_railway_evidence(self) -> None:
        """负向的另一半：解析得到不等于指对了东西。

        改正引用时把两个缓冲的铁路依赖整条删掉，上一个用例照样全绿——空集合
        永远是子集。这一条钉住它们**确实**指着铁路证据（D14：存在性检查不能
        冒充可用性检查，这里是「可解析」不能冒充「指对」）。
        """

        for label, user_id, railway_id in self._ID_SHAPES:
            with self.subTest(shape=label):
                compiled = self._compile(user_id, railway_id)
                by_id = {
                    str(event["event_id"]): event
                    for event in compiled["buffer_events"]
                }
                for event_id in ("arrival-buffer", "rail-wait-buffer"):
                    self.assertIn(event_id, by_id)
                    self.assertEqual(
                        by_id[event_id]["evidence_dependencies"],
                        [railway_id, user_id],
                    )


if __name__ == "__main__":
    unittest.main()
