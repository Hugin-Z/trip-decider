from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from trip_decider.product_web import (
    _agent_post,
    _api_response,
    _client_configuration,
    _product_discovery_request,
    _sse_event,
)
from trip_decider.codex_host import (
    confirm_trip_run,
    create_trip_run,
    execute_trip_run,
    revise_trip_run,
)
from trip_decider.agent_actions import (
    execute_registered_action,
    get_next_actions,
    start_action_loop,
    submit_evidence,
)
from trip_decider.destination_runtime import (
    collect_map_evidence,
    execute_destination_intent,
)
from trip_decider.travel_agent import (
    AgentRuntimeMode,
    DestinationCollectors,
    EvidenceItem,
    EvidenceStatus,
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

    def test_default_runtime_is_codex_hosted_without_web_nlp(self) -> None:
        status = runtime_status()
        self.assertEqual(
            status["mode"],
            AgentRuntimeMode.CODEX_HOSTED.value,
        )
        self.assertFalse(status["web_natural_language_enabled"])
        self.assertFalse(status["model_adapter_loaded"])

    def test_incomplete_intent_cannot_be_confirmed(self) -> None:
        store = InMemoryAgentStore()
        run = create_run(
            {
                "origin": "甲地",
                "destination_anchor": "乙地",
                "earliest_departure_at": None,
                "latest_return_at": None,
                "travelers": None,
                "total_budget_cny": None,
                "pace": None,
                "transport_preferences": [],
            },
            store=store,
        )
        self.assertIn("earliest_departure_at", run.intent.missing_fields)
        with self.assertRaisesRegex(
            Exception,
            "intent_missing_required_fields",
        ):
            confirm_intent(run.run_id, store=store)

    def test_codex_host_tools_send_only_structured_contracts(self) -> None:
        intent = {
            "origin": "甲地",
            "destination_anchor": "乙地",
            "earliest_departure_at": "2026-08-04T12:00",
            "latest_return_at": "2026-08-07T22:00",
            "travelers": 2,
            "total_budget_cny": 6000,
            "pace": "relaxed",
            "transport_preferences": ["high_speed_rail"],
        }
        with patch(
            "trip_decider.codex_host._post_json",
            return_value={"run": {"status": "created"}},
        ) as request:
            create_trip_run(intent)
            confirm_trip_run("12345678-abcd")
            execute_trip_run("12345678-abcd")
            revise_trip_run(
                "12345678-abcd",
                {"pace": "standard"},
            )
        self.assertEqual(request.call_count, 4)
        self.assertEqual(
            request.call_args_list[0].args[2],
            {"intent": intent},
        )
        self.assertEqual(
            request.call_args_list[3].args[2],
            {"revision": {"pace": "standard"}},
        )

    def test_map_collector_reuses_generic_amap_district_boundary(self) -> None:
        intent = TravelIntent.from_mapping(
            {
                "origin": "甲地",
                "destination_anchor": "乙地",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-05T20:00",
                "travelers": 1,
                "total_budget_cny": 1000,
                "pace": "standard",
            }
        )
        with patch(
            "trip_decider.destination_runtime.query_destination_district",
            return_value={
                "evidence_status": "sourced",
                "domain": "map",
                "destination": {
                    "name": "乙地",
                    "adcode": "000001",
                    "level": "district",
                },
                "source": {
                    "provider": "fake-map",
                    "retrieved_at": "2026-07-30T10:00:00+08:00",
                },
            },
        ):
            evidence = collect_map_evidence(intent)
        self.assertEqual(evidence.status.value, "sourced")
        self.assertEqual(evidence.domain, "map")

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
            "src/trip_decider/destination_runtime.py",
            "src/trip_decider/codex_host.py",
            "src/trip_decider/agent_actions.py",
            "src/trip_decider/planning_input_compiler.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            for city in forbidden:
                self.assertNotIn(city, source, msg=f"{city} found in {relative}")

    def test_static_product_waits_for_codex_then_shows_chinese_workbench(
        self,
    ) -> None:
        html = (ROOT / "src/trip_decider/web/index.html").read_text(
            encoding="utf-8"
        )
        script = (ROOT / "src/trip_decider/web/app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("请从 Codex 发起任务", html)
        self.assertNotIn("<textarea", html)
        self.assertIn(
            'id="confirmation" class="confirmation hidden"',
            html,
        )
        self.assertIn(
            'id="workbench" class="workbench hidden"',
            html,
        )
        for label in ("理解需求", "查询真实数据", "验证可行性", "生成行程"):
            self.assertIn(label, html)
        for status in ("等待", "进行中", "已完成", "受阻"):
            self.assertIn(status, html + script)
        for action in ("重新查询", "手动补充", "返回修改"):
            self.assertIn(action, html + script)
        for field_name in (
            "origin",
            "earliest_departure_at",
            "latest_return_at",
            "travelers",
            "total_budget_cny",
            "pace",
            "transport_preferences",
            "destination_anchor",
        ):
            self.assertIn(field_name, script)
        self.assertIn("<details", html)
        self.assertIn("执行详情", html)
        self.assertNotIn("Plan ID", html)
        self.assertNotIn("Context ID", html)
        self.assertIn("new EventSource", script)
        self.assertIn("/api/agent/current", script)

    def test_codex_cli_exposes_all_four_run_actions(self) -> None:
        source = (ROOT / "scripts/trip_agent.py").read_text(encoding="utf-8")
        for action in (
            "create_trip_run",
            "confirm_trip_run",
            "execute_trip_run",
            "revise_trip_run",
        ):
            self.assertIn(action, source)
        for command in ("create", "confirm", "execute", "revise"):
            self.assertIn(f'"{command}"', source)
        for action_command in (
            "next",
            "run-action",
            "run-until-blocked",
            "submit",
        ):
            self.assertIn(f'"{action_command}"', source)

    def test_action_loop_requires_sourced_evidence_before_planner(
        self,
    ) -> None:
        store = InMemoryAgentStore()
        run = create_run(
            {
                "origin": "甲站",
                "destination_anchor": "乙站",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T22:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["high_speed_rail"],
            },
            store=store,
        )
        confirm_intent(run.run_id, store=store)
        first = start_action_loop(run.run_id, store=store)
        self.assertEqual(first["status"], "ACTIONS_AVAILABLE")
        self.assertEqual(
            [item["action_id"] for item in first["actions"]],
            ["railway", "web"],
        )
        self.assertEqual(
            first["actions"][1]["action_type"],
            "codex_web_research",
        )

        sourced_rail = EvidenceItem(
            evidence_id="rail-test",
            domain="railway",
            status=EvidenceStatus.SOURCED,
            value={"roundtrip_fare_cny": 500},
            sources=({"provider": "fake-rail"},),
        )
        with patch(
            "trip_decider.agent_actions.collect_railway_evidence",
            return_value=sourced_rail,
        ):
            after_rail = execute_registered_action(
                run.run_id,
                "railway",
                store=store,
            )
        self.assertEqual(
            [item["action_id"] for item in after_rail["actions"]],
            ["web"],
        )

        after_web = submit_evidence(
            run.run_id,
            {
                "action_id": "web",
                "evidence_id": "web-test",
                "domain": "web",
                "status": "sourced",
                "value": {
                    "destination_official_name": "乙地区",
                    "verified_facts": [{"field": "official_name"}],
                },
                "sources": [{"publisher": "official-test"}],
            },
            store=store,
        )
        self.assertEqual(
            [item["action_id"] for item in after_web["actions"]],
            ["map"],
        )

        sourced_map = EvidenceItem(
            evidence_id="map-test",
            domain="map",
            status=EvidenceStatus.SOURCED,
            value={"destination": {"name": "乙地区"}},
            sources=({"provider": "fake-map"},),
        )
        with patch(
            "trip_decider.agent_actions.collect_map_evidence",
            return_value=sourced_map,
        ):
            after_map = execute_registered_action(
                run.run_id,
                "map",
                store=store,
            )
        self.assertEqual(
            [item["action_id"] for item in after_map["actions"]],
            ["planner"],
        )
        def nonempty_plan(context):
            return {
                "plan_id": "plan-test",
                "context_id": context["context_id"],
                "status": "CONTEXT_READY",
                "publishable": False,
                "days": [{"day": 1, "events": []}],
                "evidence_refs": [
                    item["evidence_id"]
                    for item in context["evidence"]
                ],
                "missing": [],
                "conflicting": [],
            }

        with patch(
            "trip_decider.agent_actions.plan_destination_context",
            side_effect=nonempty_plan,
        ):
            ready = execute_registered_action(
                run.run_id,
                "planner",
                store=store,
            )
        self.assertEqual(ready["status"], "NEED_USER_INPUT")
        self.assertIn(
            "cross_city_transport",
            ready["missing_requirements"],
        )
        self.assertIn("attraction", ready["missing_requirements"])
        self.assertIn("local_transit", ready["missing_requirements"])
        self.assertIn("accommodation_base", ready["missing_requirements"])
        self.assertEqual(
            store.get_run(run.run_id).status,
            RunStatus.RUNNING,
        )

    def test_missing_action_evidence_allows_partial_progress(self) -> None:
        store = InMemoryAgentStore()
        run = create_run(
            {
                "origin": "甲站",
                "destination_anchor": "乙站",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T22:00",
                "travelers": 1,
                "total_budget_cny": 1000,
                "pace": "standard",
                "transport_preferences": ["rail"],
            },
            store=store,
        )
        confirm_intent(run.run_id, store=store)
        start_action_loop(run.run_id, store=store)
        partial = submit_evidence(
            run.run_id,
            {
                "action_id": "web",
                "evidence_id": "web-missing",
                "domain": "web",
                "status": "missing",
                "value": None,
                "sources": [],
                "missing_reason": "official_source_unavailable",
            },
            store=store,
        )
        self.assertEqual(partial["status"], "ACTIONS_AVAILABLE")
        self.assertNotIn(
            "web",
            [item["action_id"] for item in partial["actions"]],
        )
        self.assertEqual(
            store.get_run(run.run_id).status,
            RunStatus.RUNNING,
        )

    def test_agent_run_endpoint_rejects_web_natural_language(self) -> None:
        with self.assertRaisesRegex(
            Exception,
            "CODEX_HOSTED",
        ):
            _agent_post(
                "/api/agent/runs",
                {"text": "请规划一次旅行"},
            )

    def test_acceptance_intent_is_complete_and_waits_for_confirmation(
        self,
    ) -> None:
        status, response = _agent_post(
            "/api/agent/runs",
            {
                "intent": {
                    "origin": "武汉",
                    "destination_anchor": "婺源",
                    "earliest_departure_at": "2026-08-04T12:00",
                    "latest_return_at": "2026-08-07T22:00",
                    "travelers": 2,
                    "total_budget_cny": 6000,
                    "pace": "relaxed",
                    "transport_preferences": ["high_speed_rail"],
                }
            },
        )
        self.assertEqual(status.value, 201)
        intent = response["run"]["intent"]
        self.assertEqual(response["run"]["status"], "AWAITING_CONFIRMATION")
        self.assertEqual(intent["task_mode"], "ANCHORED_PLAN")
        self.assertEqual(intent["origin"], "武汉")
        self.assertEqual(intent["destination_anchor"], "婺源")
        self.assertEqual(intent["earliest_departure_at"], "2026-08-04T12:00")
        self.assertEqual(intent["latest_return_at"], "2026-08-07T22:00")
        self.assertEqual(intent["travelers"], 2)
        self.assertEqual(intent["total_budget_cny"], 6000.0)
        self.assertEqual(intent["pace"], "relaxed")
        self.assertEqual(intent["transport_preferences"], ["high_speed_rail"])
        self.assertEqual(intent["missing_fields"], [])


if __name__ == "__main__":
    unittest.main()
