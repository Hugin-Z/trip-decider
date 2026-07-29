from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from trip_decider import intercity_rail
from trip_decider.intercity_rail import rail_snapshot_metadata
from trip_decider.itinerary_planner import (
    evaluate_pace,
    make_attraction_event,
    make_duration_event,
    make_event,
    make_meal_event,
    make_rail_event,
    plan_destination_context,
    resolve_pace_settings,
    resolve_planner_defaults,
    revise_destination_plan,
    schedule_change,
    validate_destination_plan,
)


class ItineraryPlannerTests(unittest.TestCase):
    def test_pace_profiles_and_independent_caps_are_city_neutral(self) -> None:
        relaxed, _ = resolve_pace_settings(
            pace="relaxed",
            physical_level=None,
            early_start=None,
            night_activity=None,
            transport_tolerance=None,
            depth_preference=None,
            overrides=None,
        )
        self.assertEqual(relaxed["max_attractions_per_day"], 1)
        self.assertEqual(relaxed["lunch_minutes"], 75)
        self.assertFalse(relaxed["default_night_activity"])

        custom, _ = resolve_pace_settings(
            pace="custom",
            physical_level="low",
            early_start=False,
            night_activity=False,
            transport_tolerance="low",
            depth_preference="deep",
            overrides={
                "max_attractions_per_day": 4,
                "earliest_departure": "06:00",
                "latest_return": "21:00",
                "max_daily_active_minutes": 800,
                "max_continuous_attraction_minutes": 200,
                "max_transfers_per_day": 5,
                "default_night_activity": True,
                "drop_low_priority": False,
            },
        )
        self.assertEqual(custom["earliest_departure"], "08:00")
        self.assertEqual(custom["max_continuous_attraction_minutes"], 90)
        self.assertEqual(custom["max_transfers_per_day"], 1)
        self.assertFalse(custom["default_night_activity"])

    def test_default_contract_and_all_event_types_are_supported(self) -> None:
        values, contract = resolve_planner_defaults(None)
        self.assertEqual(values["rail_wait_minutes"], 45)
        self.assertEqual(
            contract["hotel_checkin_minutes"]["origin"],
            "planner_default",
        )
        start = datetime.fromisoformat("2026-08-05T09:00")
        events = [
            make_event(
                event_id="transit",
                event_type="transit",
                name="Transit",
                start_at=start,
                minutes=30,
                why="test",
                timing_status="estimated",
                value_origin="api_estimate",
            ),
            make_attraction_event(
                event_id="attraction",
                attraction={
                    "id": "a",
                    "name": "A",
                    "features": [],
                    "suitable_for": [],
                    "scheduling_traits": [],
                    "opening_hours": {"status": "unknown"},
                    "ticket": {"status": "unknown"},
                },
                start_at=start,
                end_at=start.replace(hour=10),
                phase="visit",
                why="test",
            ),
            make_meal_event(
                event_id="meal",
                meal_kind="lunch",
                start_at=start,
                minutes=60,
                location="local",
                why="test",
            ),
            make_duration_event(
                event_id="hotel",
                event_type="hotel",
                name="Hotel",
                start_at=start,
                minutes=30,
                why="test",
                adjustable=(),
            ),
            make_duration_event(
                event_id="buffer",
                event_type="buffer",
                name="Buffer",
                start_at=start,
                minutes=10,
                why="test",
                adjustable=(),
            ),
            make_duration_event(
                event_id="rest",
                event_type="rest",
                name="Rest",
                start_at=start,
                minutes=30,
                why="test",
                adjustable=(),
            ),
        ]
        self.assertEqual(
            {event["type"] for event in events},
            {"transit", "attraction", "meal", "hotel", "buffer", "rest"},
        )

    def test_evaluation_preserves_changes_and_conditional_return(self) -> None:
        settings, _ = resolve_pace_settings(
            pace="standard",
            physical_level=None,
            early_start=None,
            night_activity=None,
            transport_tolerance=None,
            depth_preference=None,
            overrides=None,
        )
        start = datetime.fromisoformat("2026-08-05T18:00")
        result = evaluate_pace(
            days=[
                {
                    "day": 1,
                    "selected_branch": "night",
                    "events": [
                        make_event(
                            event_id="return",
                            event_type="transit",
                            name="Return",
                            start_at=start,
                            why="unknown",
                            timing_status="unknown",
                            value_origin="unknown",
                            branch="night",
                            extra={"transport_mode": "ride_hailing"},
                        )
                    ],
                    "pace_decisions": [
                        schedule_change(
                            "removed",
                            attraction="B",
                            reason="daily limit",
                        )
                    ],
                }
            ],
            settings=settings,
        )
        self.assertEqual(result["status"], "CONDITIONAL")
        self.assertEqual(
            result["days"][0]["conditions"],
            ["latest_return_unverified"],
        )
        self.assertEqual(result["changes"][0]["action"], "removed")

    def test_stale_snapshot_requires_collection_time(self) -> None:
        stale = rail_snapshot_metadata(
            "STALE",
            retrieved_at="2026-07-29T10:00:00+08:00",
        )
        self.assertEqual(stale["status"], "STALE")
        self.assertIn("2026-07-29T10:00:00+08:00", stale["display"])
        self.assertIn("不代表当前余票", stale["display"])
        with self.assertRaises(ValueError):
            rail_snapshot_metadata("STALE")

    def test_stale_rail_event_never_claims_current_availability(self) -> None:
        event = make_rail_event(
            event_id="rail",
            train={
                "train_code": "G1",
                "origin_station": "A",
                "destination_station": "B",
                "departure_at": "2026-08-05T08:00",
                "arrival_at": "2026-08-05T10:00",
                "second_class_fare_cny_per_person": 100.0,
            },
            name_prefix="A→B",
            snapshot=rail_snapshot_metadata(
                "STALE",
                retrieved_at="2026-07-29T10:00:00+08:00",
            ),
        )
        self.assertEqual(event["snapshot_status"], "STALE")
        self.assertEqual(
            event["availability_semantics"],
            "not_current_availability",
        )

    def test_generic_context_keeps_missing_and_never_uses_catalog(self) -> None:
        context = {
            "context_id": "context-1",
            "intent": {
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-05T20:00",
                "travelers": 1,
                "total_budget_cny": 1000,
                "pace": "standard",
            },
            "evidence": [
                {"evidence_id": "user", "domain": "user_input"},
                {"evidence_id": "rail", "domain": "railway"},
                {"evidence_id": "map", "domain": "map"},
                {"evidence_id": "web", "domain": "web"},
            ],
            "missing_domains": ["map", "web"],
            "conflicting_domains": [],
        }
        plan = plan_destination_context(context)
        self.assertEqual(plan["status"], "CONTEXT_INCOMPLETE")
        self.assertTrue(validate_destination_plan(context, plan)["valid"])
        revised = revise_destination_plan(
            {"context": context, "plan": plan},
            planner_edits={"must_visit": ["place-a"]},
            pace="relaxed",
        )
        self.assertEqual(
            revised["plan"]["revision"]["status"],
            "NO_SCHEDULED_EVENTS",
        )

    def test_rail_accepts_arbitrary_origin_destination_and_window(self) -> None:
        def train(
            code: str,
            origin: str,
            destination: str,
            departure_at: str,
            arrival_at: str,
        ) -> intercity_rail._Train:
            return intercity_rail._Train(
                train_no=code,
                train_code=code,
                origin_station=origin,
                destination_station=destination,
                origin_code="AAA" if origin == "Alpha" else "BBB",
                destination_code="BBB" if destination == "Beta" else "AAA",
                origin_station_no="01",
                destination_station_no="02",
                seat_types="O",
                departure_at=datetime.fromisoformat(departure_at),
                arrival_at=datetime.fromisoformat(arrival_at),
                duration_seconds=7200,
                second_class_availability="available",
            )

        class FakeRailClient:
            def __init__(self) -> None:
                self.network_attempts = 0

            def initialize_web_session(self) -> None:
                return None

            def station_codes(self):
                return (
                    {"Alpha": "AAA", "Beta": "BBB"},
                    {"AAA": "Alpha", "BBB": "Beta"},
                )

            def query_direct(
                self,
                *,
                travel_date,
                origin_code,
                destination_code,
                station_names,
            ):
                del travel_date, destination_code, station_names
                if origin_code == "AAA":
                    return [
                        train(
                            "TOO-EARLY",
                            "Alpha",
                            "Beta",
                            "2026-08-04T10:00",
                            "2026-08-04T12:00",
                        ),
                        train(
                            "OUTBOUND",
                            "Alpha",
                            "Beta",
                            "2026-08-04T12:30",
                            "2026-08-04T14:30",
                        ),
                    ]
                return [
                    train(
                        "RETURN",
                        "Beta",
                        "Alpha",
                        "2026-08-05T17:00",
                        "2026-08-05T19:00",
                    ),
                    train(
                        "TOO-LATE",
                        "Beta",
                        "Alpha",
                        "2026-08-05T19:00",
                        "2026-08-05T21:00",
                    ),
                ]

            def second_class_price(self, *, train, travel_date):
                del train, travel_date
                return Decimal("100")

        with patch.object(intercity_rail, "_RailClient", FakeRailClient):
            result = intercity_rail.query_intercity_rail(
                origin="Alpha",
                destination="Beta",
                earliest_departure_at="2026-08-04T12:00",
                latest_return_at="2026-08-05T20:00",
                travelers=2,
                budget_cny=1000,
            )
        self.assertEqual(result["evidence_status"], "sourced")
        self.assertEqual(result["outbound"]["train_code"], "OUTBOUND")
        self.assertEqual(result["return"]["train_code"], "RETURN")
        self.assertEqual(result["roundtrip_fare_cny"], 400.0)


if __name__ == "__main__":
    unittest.main()
