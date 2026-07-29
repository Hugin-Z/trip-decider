from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from trip_decider.product_web import (
    _api_response,
    _client_configuration,
    _product_discovery_request,
    _sse_event,
)
from trip_decider.destination_runtime import execute_destination_intent
from trip_decider.travel_agent import (
    DestinationCollectors,
    EvidenceItem,
    InMemoryAgentStore,
    Revision,
    RunStatus,
    TaskMode,
    TravelIntent,
    confirm_intent,
    create_run,
    execute_run,
    revise_run,
    runtime_status,
)


ROOT = Path(__file__).resolve().parents[1]


class ProductWebContractTests(unittest.TestCase):
    def test_datetime_window_derives_three_and_a_half_days(self) -> None:
        request, window = _product_discovery_request(
            {
                "origin": "武汉市",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-08T00:00",
                "total_budget": 6000,
                "travelers": 2,
                "themes": ["山水"],
                "pace": "适中",
                "transport_preferences": ["高铁"],
            }
        )
        self.assertEqual(request["approximate_start_date"], "2026-08-04")
        self.assertEqual(request["days"], 3.5)
        self.assertEqual(window["available_duration_hours"], 84.0)

    def test_discover_preserves_submitted_6000_budget(self) -> None:
        result = _api_response(
            "/api/discover",
            {
                "origin": "上海市",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-08T00:00",
                "total_budget": 6000,
                "travelers": 2,
                "themes": ["山水", "古村"],
                "pace": "适中",
                "transport_preferences": ["高铁"],
            },
        )
        self.assertEqual(result["request"]["total_budget"], 6000.0)
        self.assertEqual(result["request"]["travelers"], 2)
        self.assertEqual(
            result["request"]["earliest_departure_at"],
            "2026-08-04T12:00",
        )
        self.assertEqual(len(result["preliminary_candidates"]), 5)

    def test_agent_core_is_model_neutral(self) -> None:
        status = runtime_status()
        source = (
            ROOT / "src/trip_decider/travel_agent.py"
        ).read_text(encoding="utf-8")
        self.assertFalse(status["model_required"])
        self.assertFalse(status["model_adapter_loaded"])
        self.assertNotIn("OPENAI_API_KEY", source)
        self.assertNotIn("urllib.request", source)

    def test_destination_anchor_determines_anchored_mode_generically(
        self,
    ) -> None:
        anchored = TravelIntent.from_mapping(
            {
                "task_mode": "OPEN_DISCOVERY",
                "origin": "杭州",
                "destination_anchor": "绍兴",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-05T20:00",
                "travelers": 2,
                "total_budget_cny": 3000,
                "pace": "relaxed",
                "transport_preferences": ["rail"],
                "themes": ["人文"],
            }
        )
        open_intent = TravelIntent.from_mapping(
            {
                "task_mode": "ANCHORED_PLAN",
                "origin": "杭州",
                "destination_anchor": None,
                "earliest_departure_at": None,
                "latest_return_at": None,
                "travelers": None,
                "total_budget_cny": None,
                "pace": None,
            }
        )
        self.assertEqual(
            anchored.task_mode,
            TaskMode.ANCHORED_PLAN,
        )
        self.assertEqual(
            open_intent.task_mode,
            TaskMode.OPEN_DISCOVERY,
        )

    def test_codex_can_drive_run_lifecycle_and_revision(self) -> None:
        store = InMemoryAgentStore()
        intent = TravelIntent.from_mapping(
            {
                "origin": "武汉",
                "destination_anchor": "婺源",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T20:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["high_speed_rail"],
            }
        )
        run = create_run(intent, store=store)
        self.assertEqual(run.status, RunStatus.AWAITING_CONFIRMATION)
        confirmed = confirm_intent(run.run_id, store=store)
        self.assertEqual(confirmed.status, RunStatus.CONFIRMED)

        def executor(contract, emit):
            emit(
                "fake_rail",
                "started",
                "开始离线测试工具。",
                {"network": False},
            )
            emit(
                "fake_rail",
                "completed",
                "离线测试工具完成。",
                {"network": False},
            )
            return {"plan": {"pace": contract.pace}}

        completed = execute_run(
            run.run_id,
            executor=executor,
            store=store,
        )
        self.assertEqual(completed.status, RunStatus.COMPLETED)

        revised = revise_run(
            run.run_id,
            Revision(pace="standard"),
            executor=lambda previous, revision, emit: {
                "plan": {"pace": revision.pace},
                "previous": previous,
            },
            store=store,
        )
        self.assertEqual(revised.status, RunStatus.COMPLETED)
        events = store.events_after(run.session_id, 0)
        self.assertEqual(events[-1].event_type, "run.completed")
        encoded = _sse_event(events[-1].to_dict()).decode("utf-8")
        self.assertIn("event: agent_event", encoded)
        self.assertIn('"event_type": "run.completed"', encoded)

    def test_map_configuration_uses_separate_frontend_variables(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AMAP_WEB_SERVICE_KEY": "backend-only",
                "AMAP_JS_API_KEY": "frontend-key",
                "AMAP_JS_SECURITY_CODE": "frontend-security",
            },
            clear=True,
        ):
            result = _client_configuration()
        self.assertTrue(result["amap_js"]["configured"])
        self.assertEqual(result["amap_js"]["key"], "frontend-key")
        self.assertTrue(result["amap_js"]["web_service_key_separate"])
        self.assertNotEqual(
            result["amap_js"]["key"],
            "backend-only",
        )

    def test_two_destinations_use_the_same_runtime_pipeline(self) -> None:
        paths = (
            ROOT
            / "fixtures/golden_cases/wuhan_wuyuan/destination-context.json",
            ROOT
            / "fixtures/golden_cases/hangzhou_shaoxing/destination-context.json",
        )
        observed: list[dict[str, object]] = []
        for path in paths:
            document = json.loads(path.read_text(encoding="utf-8"))
            intent = TravelIntent.from_mapping(document["intent"])
            by_domain = {
                item["domain"]: EvidenceItem.from_mapping(item)
                for item in document["collector_evidence"]
            }
            calls: list[tuple[str, str]] = []
            collectors = DestinationCollectors(
                railway=lambda _intent, values=by_domain: values["railway"],
                map=lambda _intent, values=by_domain: values["map"],
                web=lambda _intent, values=by_domain: values["web"],
            )
            result = execute_destination_intent(
                intent,
                lambda tool, status, _message, _details: calls.append(
                    (tool, status)
                ),
                collectors=collectors,
            )
            observed.append(
                {
                    "pipeline": result["pipeline"],
                    "tools": [tool for tool, _status in calls],
                    "valid": result["validation"]["valid"],
                    "destination": result["context"]["intent"][
                        "destination_anchor"
                    ],
                }
            )
        self.assertNotEqual(
            observed[0]["destination"],
            observed[1]["destination"],
        )
        self.assertEqual(observed[0]["pipeline"], observed[1]["pipeline"])
        self.assertEqual(observed[0]["tools"], observed[1]["tools"])
        self.assertTrue(observed[0]["valid"])
        self.assertTrue(observed[1]["valid"])

    def test_core_runtime_files_do_not_name_cities(self) -> None:
        forbidden = ("武汉", "婺源", "上饶", "上海", "杭州", "绍兴")
        for relative in (
            "src/trip_decider/travel_agent.py",
            "src/trip_decider/product_web.py",
            "src/trip_decider/itinerary_planner.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            for city in forbidden:
                self.assertNotIn(city, source, msg=f"{city} found in {relative}")

    def test_static_product_has_no_demo_or_default_submit(self) -> None:
        html = (ROOT / "src/trip_decider/web/index.html").read_text(
            encoding="utf-8"
        )
        script = (ROOT / "src/trip_decider/web/app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="budget"', html)
        self.assertIn('min="0"', html)
        self.assertIn('step="100"', html)
        self.assertEqual(html.count('type="datetime-local"'), 2)
        self.assertNotIn("填入武汉示例", html)
        self.assertNotIn("fillDemo", script)
        self.assertNotIn("\nsubmitDiscovery();", script)
        self.assertIn("state.submittedDraft", script)


if __name__ == "__main__":
    unittest.main()
