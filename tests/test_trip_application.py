from __future__ import annotations

import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider import product_web
from trip_decider.trip_application import TripApplicationService
from trip_decider.travel_agent import (
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
    RunStatus,
)


class _NoBackgroundService(TripApplicationService):
    @staticmethod
    def _spawn(*, target, args, name) -> None:
        del target, args, name


def _intent(*, mode: str = "DIRECT_PLAN") -> dict[str, object]:
    return {
        "task_mode": mode,
        "origin": "甲地",
        "destination_anchor": (
            "乙地区" if mode != "PLAN_AUDIT" else None
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


class TripApplicationServiceTests(unittest.TestCase):
    def test_direct_plan_mode_starts_one_authoritative_action_loop(self) -> None:
        store = InMemoryAgentStore()
        service = _NoBackgroundService(store=store)
        created = service.create_trip(_intent())
        service.confirm_trip(created.run_id)

        outcome = service.execute_trip(created.run_id)

        self.assertTrue(outcome.accepted)
        self.assertEqual(outcome.run_id, created.run_id)
        self.assertEqual(
            store.get_run(created.run_id).status,
            RunStatus.RUNNING,
        )
        self.assertEqual(
            [
                action["action_id"]
                for action in outcome.action_loop["actions"]
            ],
            ["railway", "web"],
        )

    def test_candidate_selection_reuses_same_run_and_evidence_namespace(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            store = InMemoryAgentStore(Path(temporary) / "sessions")
            service = _NoBackgroundService(store=store)
            run = service.create_trip(_intent(mode="GUIDED_DISCOVERY"))
            service.confirm_trip(run.run_id)
            store.start(run.run_id)
            store.complete(
                run.run_id,
                {
                    "stage": "guided_discovery",
                    "options": [
                        {
                            "destination_id": "option-one",
                            "destination_anchor": "乙地",
                        }
                    ],
                },
            )
            missing = {
                domain: EvidenceItem(
                    evidence_id=f"{domain}-missing",
                    domain=domain,
                    status=EvidenceStatus.MISSING,
                    value=None,
                    missing_reason=(
                        "web_search_collector_not_configured"
                        if domain == "web"
                        else "not_collected"
                    ),
                ).to_dict()
                for domain in ("railway", "map", "web")
            }
            service.persist_guided_evidence(
                run.run_id,
                {"option-one": missing},
            )

            outcome = service.select_candidate(
                run.run_id,
                "option-one",
            )

            current = store.get_run(run.run_id)
            self.assertEqual(outcome.run_id, run.run_id)
            self.assertEqual(current.run_id, run.run_id)
            self.assertEqual(current.intent.task_mode.value, "DIRECT_PLAN")
            self.assertEqual(current.intent.destination_anchor, "乙地")
            self.assertTrue(
                (
                    store.run_directory(run.run_id)
                    / "evidence"
                    / "guided-comparison.json"
                ).is_file()
            )

    def test_plan_audit_is_independent_from_planner_action_loop(self) -> None:
        store = InMemoryAgentStore()
        service = _NoBackgroundService(store=store)
        run = service.create_trip(_intent(mode="PLAN_AUDIT"))
        service.confirm_trip(run.run_id)

        outcome = service.audit_trip(
            run.run_id,
            plan={
                "days": [
                    {
                        "day": 1,
                        "events": [
                            {
                                "type": "attraction",
                                "start": "09:00",
                                "end": "11:00",
                                "location": "某景点",
                            }
                        ],
                    }
                ]
            },
        )

        result = store.get_run(run.run_id).result
        self.assertEqual(outcome.audit_execution["status"], "AUDIT_COMPLETED")
        self.assertEqual(result["stage"], "plan_audit")
        self.assertFalse(result["planner_invoked"])

    def test_http_command_adapter_does_not_wire_runtime_components(self) -> None:
        source = inspect.getsource(product_web._trip_post)
        self.assertIn("_application_service()", source)
        for forbidden in (
            "create_run(",
            "confirm_intent(",
            "continue_run_with_intent(",
            "revise_run(",
            "execute_registered_action(",
            "run_until_blocked(",
            "submit_evidence(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
