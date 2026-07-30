from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import trip_decider.agent_actions as agent_actions
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


def _railway(status: str = "LIVE") -> EvidenceItem:
    retrieved_at = "2026-07-30T10:44:00+08:00"
    return EvidenceItem(
        evidence_id="railway-live-query",
        domain="railway",
        status=EvidenceStatus.SOURCED,
        value={
            "evidence_status": "sourced",
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
                "status": status,
                "retrieved_at": retrieved_at,
                "attempted_at": retrieved_at,
                "availability_semantics": (
                    "current_at_retrieval_only"
                    if status == "LIVE"
                    else "not_current_availability"
                ),
                "display": status,
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
            compiled = PlanningInputCompiler().compile(context)
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
            self.assertEqual(
                compiled["display_status"],
                "DISPLAYABLE_CONDITIONAL_ITINERARY",
            )
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
                _railway("STALE"),
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
        compiled = PlanningInputCompiler().compile(context)
        self.assertEqual(
            compiled["status"],
            "PARTIAL_PLAN_WITH_BLOCKERS",
        )
        self.assertTrue(compiled["days"])
        rail_events = [
            event
            for day in compiled["days"]
            for event in day["events"]
            if event.get("snapshot_status") == "STALE"
        ]
        self.assertEqual(len(rail_events), 2)
        self.assertTrue(compiled["conditional_blockers"])
        self.assertFalse(compiled["displayable"])
        self.assertEqual(
            compiled["display_status"],
            "SUPPLEMENTING_DATA",
        )

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
        railway = next(
            item
            for item in ready["result"]["context"]["evidence"]
            if item["domain"] == "railway"
        )
        self.assertEqual(railway["value"]["snapshot"]["status"], "STALE")
        self.assertEqual(
            railway["value"]["outbound"][
                "second_class_availability"
            ],
            "UNKNOWN",
        )
        self.assertEqual(
            railway["value"]["outbound"]["schedule_status"],
            "STALE",
        )
        self.assertEqual(
            railway["value"]["outbound"]["fare_status"],
            "STALE",
        )
        self.assertEqual(
            railway["value"]["return"]["second_class_availability"],
            "UNKNOWN",
        )
        self.assertEqual(
            ready["result"]["plan"]["status"],
            "PARTIAL_PLAN_WITH_BLOCKERS",
        )
        self.assertTrue(ready["result"]["plan"]["displayable"])
        self.assertIn(
            "具体酒店未选择",
            ready["result"]["plan"]["accommodation_notice"],
        )
        stale_events = [
            event
            for day in ready["result"]["plan"]["days"]
            for event in day["events"]
            if event.get("snapshot_status") == "STALE"
        ]
        self.assertEqual(
            {event["fare"]["status"] for event in stale_events},
            {"stale"},
        )
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
        compiled = PlanningInputCompiler().compile(context)
        self.assertFalse(compiled["displayable"])
        self.assertEqual(
            compiled["display_requirements"],
            {
                "cross_city_transport": False,
                "attraction": False,
                "local_transit": False,
                "accommodation_base": False,
            },
        )
        self.assertTrue(compiled["meal_events"])
        self.assertTrue(compiled["rest_events"])

    def test_runtime_restart_restores_session_evidence_and_plan_version(
        self,
    ) -> None:
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

            run_directory = runtime_root / run.run_id
            for relative in (
                "session.json",
                "run.json",
                "events.jsonl",
                "action-loop.json",
                "evidence.json",
                "plan-version.json",
                "plans/plan-0001.json",
            ):
                self.assertTrue((run_directory / relative).is_file())
            evidence = json.loads(
                (run_directory / "evidence.json").read_text(
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
                    runtime_root / run.run_id / "evidence.json"
                ).read_text(encoding="utf-8")
            )
            railway = next(
                item
                for item in persisted["current"]
                if item["domain"] == "railway"
            )
            self.assertEqual(
                railway["value"]["snapshot"]["status"],
                "STALE",
            )
            self.assertEqual(
                railway["value"]["outbound"][
                    "second_class_availability"
                ],
                "UNKNOWN",
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
                    "status"
                ],
                "STALE",
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
        railway = next(
            item
            for item in refreshed["result"]["context"]["evidence"]
            if item["domain"] == "railway"
        )
        self.assertEqual(
            railway["value"]["snapshot"]["status"],
            "STALE",
        )
        self.assertEqual(
            railway["value"]["outbound"][
                "second_class_availability"
            ],
            "UNKNOWN",
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
        self.assertTrue(ready["result"]["plan"]["displayable"])


if __name__ == "__main__":
    unittest.main()
