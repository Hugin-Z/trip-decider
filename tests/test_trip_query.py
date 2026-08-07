from __future__ import annotations

import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider import product_web
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService
from trip_decider.travel_agent import InMemoryAgentStore


def _intent(*, mode: str = "DIRECT_PLAN") -> dict[str, object]:
    return {
        "task_mode": mode,
        "origin": "甲地",
        "destination_anchor": (
            "乙地" if mode not in {"OPEN_DISCOVERY", "PLAN_AUDIT"} else None
        ),
        "earliest_departure_at": (
            "2026-08-04T12:00" if mode != "PLAN_AUDIT" else None
        ),
        "latest_return_at": (
            "2026-08-07T22:00" if mode != "PLAN_AUDIT" else None
        ),
        "travelers": 2 if mode != "PLAN_AUDIT" else None,
        "total_budget_cny": 6000 if mode != "PLAN_AUDIT" else None,
        "pace": "relaxed" if mode != "PLAN_AUDIT" else None,
        "transport_preferences": (
            ["rail"] if mode != "PLAN_AUDIT" else []
        ),
    }


class TripQueryServiceTests(unittest.TestCase):
    def test_application_only_uses_its_store(self) -> None:
        store = InMemoryAgentStore()
        application = TripApplicationService(store=store)

        query = TripQueryService(application_service=application)

        self.assertIs(query.store, store)
        self.assertIs(query.application_service, application)

    def test_store_only_builds_a_matching_application_service(self) -> None:
        store = InMemoryAgentStore()

        query = TripQueryService(store=store)

        self.assertIs(query.store, store)
        self.assertIs(query.application_service.store, store)

    def test_query_and_command_services_must_share_one_store(self) -> None:
        first = InMemoryAgentStore()
        second = InMemoryAgentStore()
        application = TripApplicationService(store=first)

        with self.assertRaisesRegex(ValueError, "must share one run store"):
            TripQueryService(
                store=second,
                application_service=application,
            )

    def test_run_plan_map_and_events_share_one_read_model(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "sessions"
            store = InMemoryAgentStore(root)
            application = TripApplicationService(store=store)
            query = TripQueryService(
                store=store,
                application_service=application,
            )
            run = application.create_trip(_intent())
            application.confirm_trip(run.run_id)
            store.persist_plan_version(
                run.run_id,
                {
                    "planning_state": "PARTIAL_READY",
                    "plan": {
                        "artifact_kind": "PlanVersion",
                        "planning_state": "PARTIAL_READY",
                        "displayable": True,
                        "days": [{"day": 1, "events": []}],
                    },
                    "context": {"evidence": []},
                },
            )

            read_model = query.trip(run.run_id)
            current_plan = query.current_plan(run.run_id)

            self.assertEqual(read_model["run"]["run_id"], run.run_id)
            self.assertEqual(read_model["presentation"]["plan_version"], 1)
            self.assertEqual(current_plan["plan_version"], 1)
            self.assertEqual(
                query.map_payload(run.run_id),
                read_model["presentation"]["map_payload"],
            )
            self.assertEqual(
                query.events(run.run_id),
                read_model["events"],
            )

            restored_store = InMemoryAgentStore(root)
            restored_application = TripApplicationService(
                store=restored_store
            )
            restored_query = TripQueryService(
                store=restored_store,
                application_service=restored_application,
            )
            self.assertEqual(
                restored_query.current_plan(run.run_id)["plan_version"],
                1,
            )
            self.assertEqual(
                restored_query.trip(run.run_id)["presentation"][
                    "plan_version"
                ],
                1,
            )

    def test_candidates_and_audit_are_query_contracts(self) -> None:
        store = InMemoryAgentStore()
        application = TripApplicationService(store=store)
        query = TripQueryService(
            store=store,
            application_service=application,
        )
        discovery = application.create_trip(
            _intent(mode="GUIDED_DISCOVERY")
        )
        application.confirm_trip(discovery.run_id)
        store.start(discovery.run_id)
        store.append_event(
            discovery.run_id,
            event_type="guided.candidate.completed",
            status="completed",
            message="候选已完成粗验证。",
            details={
                "option": {
                    "destination_id": "candidate-one",
                    "destination_anchor": "乙地",
                }
            },
        )
        candidates = query.candidates(discovery.run_id)
        self.assertFalse(candidates["comparison_completed"])
        self.assertEqual(
            candidates["candidates"][0]["destination_id"],
            "candidate-one",
        )

        audit = application.create_trip(_intent(mode="PLAN_AUDIT"))
        application.confirm_trip(audit.run_id)
        application.audit_trip(
            audit.run_id,
            plan={"days": [{"day": 1, "events": []}]},
        )
        self.assertEqual(
            query.audit_result(audit.run_id)["stage"],
            "plan_audit",
        )

    def test_web_adapter_does_not_read_store_business_state(self) -> None:
        source = inspect.getsource(product_web)
        for forbidden in (
            "default_agent_store().get_run(",
            "default_agent_store().get_session(",
            "default_agent_store().list_runs(",
            "default_agent_store().run_directory(",
            "default_agent_store().events_after(",
            "default_agent_store().wait_for_events(",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("_query_service().trip(run_id)", source)
        self.assertIn("query_service.wait_for_events(", source)


if __name__ == "__main__":
    unittest.main()
