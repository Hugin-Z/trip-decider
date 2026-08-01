from __future__ import annotations

import json
import os
import shutil
import threading
import time
import unittest
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

import trip_decider.agent_actions as agent_actions
import trip_decider.product_web as product_web
from trip_decider.product_web import (
    _MODE_EXECUTION_HANDLERS,
    _client_configuration,
    _execute_direct_plan,
    _execute_guided_discovery,
    _execute_open_discovery,
    _map_payload_contract,
    _persist_guided_evidence,
    _presentation_contract,
    _sse_event,
    _trip_post,
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
    run_until_blocked,
    start_action_loop,
    submit_evidence,
)
from trip_decider.destination_runtime import (
    collect_map_evidence,
    execute_destination_intent,
)
from trip_decider.guided_discovery import (
    build_guided_comparison,
    guided_region_seeds,
)
from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.travel_agent import (
    AgentRuntimeMode,
    DEFAULT_AGENT_STORE,
    DestinationCollectors,
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
    Revision,
    RunStatus,
    TaskMode,
    TravelIntent,
    confirm_intent,
    continue_run_with_intent,
    create_run,
    execute_run,
    revise_run,
    runtime_status,
)


ROOT = Path(__file__).resolve().parents[1]


class ProductWebContractTests(unittest.TestCase):
    def test_detail_loop_runs_independent_missing_tools_in_parallel(
        self,
    ) -> None:
        store = InMemoryAgentStore()
        run = create_run(
            {
                "task_mode": "DIRECT_PLAN",
                "origin": "甲地",
                "destination_anchor": "乙地",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T22:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["rail"],
            },
            store=store,
        )
        confirm_intent(run.run_id, store=store)
        missing = {
            domain: EvidenceItem(
                evidence_id=f"guided-{domain}-missing",
                domain=domain,
                status=EvidenceStatus.MISSING,
                value=None,
                missing_reason=(
                    "web_search_collector_not_configured"
                    if domain == "web"
                    else "guided_query_missing"
                ),
            )
            for domain in ("railway", "map", "web")
        }
        first = start_action_loop(
            run.run_id,
            initial_evidence=missing,
            store=store,
        )
        self.assertEqual(
            [action["action_id"] for action in first["actions"]],
            ["railway", "web", "map"],
        )

        parallel_gate = threading.Barrier(2)

        def sourced(domain: str) -> EvidenceItem:
            parallel_gate.wait(timeout=1)
            return EvidenceItem(
                evidence_id=f"{domain}-fresh",
                domain=domain,
                status=EvidenceStatus.SOURCED,
                value=(
                    {"destination": {"adcode": "000000"}}
                    if domain == "map"
                    else {"roundtrip_fare_cny": 400}
                ),
                sources=(
                    {"source_type": "official_api", "locator": "test"},
                ),
            )

        with (
            patch(
                "trip_decider.agent_actions.collect_railway_evidence",
                side_effect=lambda intent: sourced("railway"),
            ),
            patch(
                "trip_decider.agent_actions.collect_map_evidence",
                side_effect=lambda intent: sourced("map"),
            ),
        ):
            paused = run_until_blocked(run.run_id, store=store)
        self.assertEqual(paused["status"], "NEED_USER_INPUT")
        self.assertEqual(paused["paused_at"], ["codex_web_research"])

    def test_action_without_progress_is_blocked_instead_of_staying_running(
        self,
    ) -> None:
        store = InMemoryAgentStore()
        run = create_run(
            {
                "task_mode": "DIRECT_PLAN",
                "origin": "甲地",
                "destination_anchor": "乙地",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T22:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["rail"],
            },
            store=store,
        )
        confirm_intent(run.run_id, store=store)
        start_action_loop(run.run_id, store=store)
        release = threading.Event()
        original = agent_actions._TOOL_REGISTRY["railway"]["handler"]

        def stalled_handler(intent, state):
            release.wait(2)
            return EvidenceItem(
                evidence_id="late-rail",
                domain="railway",
                status=EvidenceStatus.MISSING,
                value=None,
                missing_reason="late_result",
            )

        agent_actions._TOOL_REGISTRY["railway"]["handler"] = (
            stalled_handler
        )
        try:
            snapshot = run_until_blocked(
                run.run_id,
                store=store,
                max_wait_seconds=0.02,
            )
        finally:
            release.set()
            agent_actions._TOOL_REGISTRY["railway"]["handler"] = original
        self.assertEqual(snapshot["status"], "BLOCKED")
        blocked = store.get_run(run.run_id)
        self.assertEqual(blocked.status, RunStatus.BLOCKED)
        self.assertEqual(
            blocked.error_code,
            "RAILWAY_ACTION_STALLED",
        )

    def test_plan_audit_does_not_require_planning_intent_fields(self) -> None:
        intent = TravelIntent.from_mapping(
            {
                "task_mode": "PLAN_AUDIT",
                "interpretation": "检查已有计划",
            }
        )
        self.assertEqual(intent.blocking_missing_fields, ())

    def test_each_task_mode_has_an_independent_execution_handler(self) -> None:
        self.assertIs(
            _MODE_EXECUTION_HANDLERS[TaskMode.OPEN_DISCOVERY],
            _execute_open_discovery,
        )
        self.assertIs(
            _MODE_EXECUTION_HANDLERS[TaskMode.GUIDED_DISCOVERY],
            _execute_guided_discovery,
        )
        self.assertIs(
            _MODE_EXECUTION_HANDLERS[TaskMode.DIRECT_PLAN],
            _execute_direct_plan,
        )
        self.assertNotIn(TaskMode.PLAN_AUDIT, _MODE_EXECUTION_HANDLERS)

    def test_plan_audit_accepts_existing_plan_without_planner(self) -> None:
        _, created = _trip_post(
            "/api/trips",
            {"intent": {"task_mode": "PLAN_AUDIT"}},
        )
        run_id = created["run"]["run_id"]
        self.addCleanup(
            shutil.rmtree,
            DEFAULT_AGENT_STORE.runtime_root / run_id,
            True,
        )
        _trip_post(f"/api/trips/{run_id}/confirm", {})
        with patch.object(product_web, "start_action_loop") as planner:
            status, response = _trip_post(
                f"/api/trips/{run_id}/audit",
                {
                    "plan": {
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
                    }
                },
            )
        self.assertEqual(status, 200)
        planner.assert_not_called()
        self.assertEqual(response["run"]["result"]["stage"], "plan_audit")
        self.assertFalse(response["run"]["result"]["planner_invoked"])
        self.assertEqual(
            response["run"]["result"]["audit"]["validation_status"],
            "STRUCTURALLY_VALID",
        )

    def test_product_server_source_does_not_expose_legacy_routes(self) -> None:
        source = (
            ROOT / "src/trip_decider/product_web.py"
        ).read_text(encoding="utf-8")
        for legacy_path in (
            "/api/discover",
            "/api/select-destination",
            "/api/catalog",
            "/api/interpret-intent",
            "/api/agent/current",
        ):
            self.assertNotIn(legacy_path, source)
        self.assertNotIn("trip_decider.destination_discovery", source)

    def test_agent_core_is_model_neutral(self) -> None:
        status = runtime_status()
        source = (
            ROOT / "src/trip_decider/travel_agent.py"
        ).read_text(encoding="utf-8")
        self.assertFalse(status["model_required"])
        self.assertFalse(status["model_adapter_loaded"])
        self.assertNotIn("OPENAI_API_KEY", source)
        self.assertNotIn("urllib.request", source)

    def test_destination_commitment_determines_mode_generically(
        self,
    ) -> None:
        guided = TravelIntent.from_mapping(
            {
                "task_mode": "OPEN_DISCOVERY",
                "origin": "杭州",
                "destination_anchor": "绍兴",
                "destination_expression": "倾向绍兴一带",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-05T20:00",
                "travelers": 2,
                "total_budget_cny": 3000,
                "pace": "relaxed",
                "transport_preferences": ["rail"],
                "themes": ["人文"],
            }
        )
        direct = TravelIntent.from_mapping(
            {
                **guided.to_dict(),
                "destination_expression": "已经订了绍兴，就去这里",
                "task_mode": "OPEN_DISCOVERY",
            }
        )
        open_intent = TravelIntent.from_mapping(
            {
                "task_mode": "DIRECT_PLAN",
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
            guided.task_mode,
            TaskMode.GUIDED_DISCOVERY,
        )
        self.assertEqual(
            direct.task_mode,
            TaskMode.DIRECT_PLAN,
        )
        self.assertEqual(
            open_intent.task_mode,
            TaskMode.OPEN_DISCOVERY,
        )
        base = {
            **guided.to_dict(),
            "task_mode": "OPEN_DISCOVERY",
        }
        for marker in ("倾向", "优先", "大概想去", "考虑"):
            with self.subTest(marker=marker):
                classified = TravelIntent.from_mapping(
                    {
                        **base,
                        "destination_expression": f"{marker}绍兴一带",
                    }
                )
                self.assertEqual(
                    classified.task_mode,
                    TaskMode.GUIDED_DISCOVERY,
                )
        for marker in ("确定", "就去", "已经订了"):
            with self.subTest(marker=marker):
                classified = TravelIntent.from_mapping(
                    {
                        **base,
                        "destination_expression": f"{marker}绍兴",
                    }
                )
                self.assertEqual(
                    classified.task_mode,
                    TaskMode.DIRECT_PLAN,
                )

    def test_regional_preference_is_guided_not_direct_plan(self) -> None:
        intent = TravelIntent.from_mapping(
            {
                "origin": "武汉",
                "destination_anchor": "江西婺源、上饶那块",
                "destination_expression": "倾向江西婺源、上饶那块",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T22:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["high_speed_rail"],
                "themes": ["山水", "古村"],
            }
        )
        self.assertEqual(intent.task_mode, TaskMode.GUIDED_DISCOVERY)
        self.assertEqual(
            [item["name"] for item in guided_region_seeds(intent)],
            ["婺源", "三清山"],
        )

    def test_guided_options_are_coarse_checked_before_display(self) -> None:
        intent = TravelIntent.from_mapping(
            {
                "origin": "武汉",
                "destination_anchor": "江西婺源、上饶那块",
                "destination_expression": "优先江西婺源、上饶那块",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T22:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["high_speed_rail"],
                "themes": ["山水", "古村"],
            }
        )
        checked: list[str] = []

        def railway(contract: TravelIntent) -> EvidenceItem:
            checked.append(str(contract.destination_anchor))
            return EvidenceItem(
                evidence_id="rail-check",
                domain="railway",
                status=EvidenceStatus.SOURCED,
                value={
                    "roundtrip_duration_seconds": 36000,
                    "roundtrip_fare_cny": 800,
                    "snapshot": {
                        "status": "LIVE",
                        "retrieved_at": "2026-07-30T12:00:00+08:00",
                    },
                    "outbound": {
                        "train_code": "TEST",
                        "departure_at": "2026-08-04T13:00",
                        "arrival_at": "2026-08-04T16:00",
                        "duration_seconds": 10800,
                    },
                    "return": {
                        "train_code": "TEST",
                        "departure_at": "2026-08-07T17:00",
                        "arrival_at": "2026-08-07T21:00",
                        "duration_seconds": 14400,
                    },
                },
                sources=(
                    {
                        "source_type": "official_api",
                        "locator": "test",
                        "provider": "中国铁路12306",
                        "retrieved_at": "2026-07-30T12:00:00+08:00",
                    },
                ),
            )

        result = build_guided_comparison(
            intent,
            railway_collector=railway,
        )
        self.assertEqual(result["option_count"], 2)
        self.assertEqual(len(checked), 2)
        self.assertEqual(
            set(result["reusable_evidence"]),
            {str(option["destination_id"]) for option in result["options"]},
        )
        for option in result["options"]:
            self.assertEqual(
                option["feasibility_status"],
                "CONDITIONALLY_FEASIBLE",
            )
            self.assertEqual(
                option["local_transport_difficulty"]["status"],
                "MISSING",
            )
            self.assertGreater(
                option["playable_time_seconds"],
                0,
            )
            self.assertIn("当地交通难度", option["evidence_missing"])

    def test_guided_candidates_stream_as_parallel_checks_finish(self) -> None:
        intent = TravelIntent.from_mapping(
            {
                "task_mode": "GUIDED_DISCOVERY",
                "origin": "武汉",
                "destination_anchor": "江西婺源、上饶那块",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T22:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["rail"],
                "themes": ["山水"],
            }
        )
        started = time.monotonic()
        streamed: list[tuple[str, float]] = []

        def railway(contract: TravelIntent) -> EvidenceItem:
            time.sleep(
                0.03 if contract.destination_anchor == "婺源" else 0.15
            )
            return EvidenceItem(
                evidence_id="rail",
                domain="railway",
                status=EvidenceStatus.SOURCED,
                value={
                    "roundtrip_duration_seconds": 3600,
                    "roundtrip_fare_cny": 200,
                    "snapshot": {
                        "status": "LIVE",
                        "retrieved_at": "2026-07-30T12:00:00+08:00",
                    },
                },
                sources=(
                    {
                        "source_type": "official_api",
                        "locator": "test",
                        "provider": "中国铁路12306",
                        "retrieved_at": "2026-07-30T12:00:00+08:00",
                    },
                ),
            )

        def progress(status, destination, details):
            if status == "candidate_completed":
                streamed.append((destination, time.monotonic() - started))

        result = build_guided_comparison(
            intent,
            railway_collector=railway,
            progress=progress,
        )
        elapsed = time.monotonic() - started
        self.assertEqual(result["option_count"], 2)
        self.assertEqual(len(streamed), 2)
        self.assertLess(streamed[0][1], 0.12)
        self.assertLess(elapsed, 0.24)

    def test_guided_domain_timeout_is_partial_and_does_not_block(self) -> None:
        intent = TravelIntent.from_mapping(
            {
                "task_mode": "GUIDED_DISCOVERY",
                "origin": "武汉",
                "destination_anchor": "江西婺源、上饶那块",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T22:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["rail"],
                "themes": ["山水"],
            }
        )

        def slow_railway(contract: TravelIntent) -> EvidenceItem:
            del contract
            time.sleep(0.2)
            return EvidenceItem(
                evidence_id="late",
                domain="railway",
                status=EvidenceStatus.MISSING,
                value=None,
                missing_reason="late",
            )

        started = time.monotonic()
        result = build_guided_comparison(
            intent,
            railway_collector=slow_railway,
            timeouts={"railway": 0.02},
        )
        self.assertLess(time.monotonic() - started, 0.12)
        self.assertEqual(result["option_count"], 2)
        for option in result["options"]:
            rail = next(
                item
                for item in option["evidence_statuses"]
                if item["domain"] == "railway"
            )
            self.assertEqual(rail["status"], "MISSING")
            self.assertTrue(rail["timed_out"])

    def test_guided_broker_queries_live_before_exact_stale_fallback(self) -> None:
        intent = TravelIntent.from_mapping(
            {
                "task_mode": "GUIDED_DISCOVERY",
                "origin": "武汉",
                "destination_anchor": "江西婺源、上饶那块",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T22:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["rail"],
                "themes": ["山水"],
            }
        )
        calls = 0
        broker = EvidenceBroker(
            clock=lambda: datetime(
                2026,
                7,
                30,
                12,
                30,
                tzinfo=timezone.utc,
            )
        )

        def railway(contract: TravelIntent) -> EvidenceItem:
            nonlocal calls
            calls += 1
            if calls > 2:
                return EvidenceItem(
                    evidence_id="refresh-failed",
                    domain="railway",
                    status=EvidenceStatus.MISSING,
                    value={"attempted_at": "2026-07-30T12:30:00+00:00"},
                    missing_reason="rail_http",
                )
            return EvidenceItem(
                evidence_id=str(contract.destination_anchor),
                domain="railway",
                status=EvidenceStatus.SOURCED,
                value={
                    "roundtrip_duration_seconds": 3600,
                    "roundtrip_fare_cny": 200,
                    "snapshot": {
                        "status": "LIVE",
                        "retrieved_at": "2026-07-30T12:00:00+08:00",
                    },
                },
                sources=(
                    {
                        "source_type": "official_api",
                        "locator": "test",
                        "provider": "中国铁路12306",
                        "retrieved_at": "2026-07-30T12:00:00+00:00",
                    },
                ),
            )

        build_guided_comparison(
            intent,
            railway_collector=railway,
            run_id="guided-run-one",
            evidence_broker=broker,
        )
        reused = build_guided_comparison(
            intent,
            railway_collector=railway,
            run_id="guided-run-two",
            evidence_broker=broker,
        )
        self.assertEqual(calls, 4)
        for option in reused["options"]:
            self.assertEqual(
                option["roundtrip_transport"]["status"],
                "STALE",
            )
            self.assertTrue(
                option["roundtrip_transport"]["from_cache"]
            )
            self.assertEqual(
                option["roundtrip_transport"]["retrieved_at"],
                "2026-07-30T12:00:00+08:00",
            )

    def test_guided_selection_continues_in_same_run(self) -> None:
        store = InMemoryAgentStore()
        guided = TravelIntent.from_mapping(
            {
                "task_mode": "GUIDED_DISCOVERY",
                "origin": "甲地",
                "destination_anchor": "乙地区域",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T22:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["rail"],
            }
        )
        created = create_run(guided, store=store)
        confirm_intent(created.run_id, store=store)
        completed = execute_run(
            created.run_id,
            executor=lambda intent, emit: {
                "stage": "guided_discovery",
                "options": [{"destination_id": "one"}],
            },
            store=store,
        )
        direct_value = guided.to_dict()
        direct_value.update(
            {
                "task_mode": "DIRECT_PLAN",
                "destination_anchor": "乙地",
                "destination_expression": "确定乙地",
            }
        )
        continued = continue_run_with_intent(
            completed.run_id,
            direct_value,
            store=store,
        )
        self.assertEqual(continued.run_id, created.run_id)
        self.assertEqual(continued.session_id, created.session_id)
        self.assertEqual(continued.status, RunStatus.CONFIRMED)
        self.assertEqual(continued.intent.task_mode, TaskMode.DIRECT_PLAN)
        self.assertEqual(
            continued.result["stage"],
            "guided_discovery",
        )

    def test_guided_selection_endpoint_reuses_the_current_run(self) -> None:
        created = create_run(
            {
                "task_mode": "GUIDED_DISCOVERY",
                "origin": "甲地",
                "destination_anchor": "乙地区域",
                "earliest_departure_at": "2026-08-04T12:00",
                "latest_return_at": "2026-08-07T22:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["rail"],
            }
        )
        self.addCleanup(
            shutil.rmtree,
            DEFAULT_AGENT_STORE.runtime_root / created.run_id,
            True,
        )
        confirm_intent(created.run_id)
        execute_run(
            created.run_id,
            executor=lambda intent, emit: {
                "stage": "guided_discovery",
                "options": [
                    {
                        "destination_id": "option-one",
                        "destination_anchor": "乙地",
                        "feasibility_status": "CONDITIONALLY_FEASIBLE",
                        "roundtrip_transport": {
                            "status": "LIVE",
                            "duration_seconds": 7200,
                            "known_cost_cny": 400,
                        },
                        "evidence_statuses": [
                            {"domain": "railway", "status": "LIVE"},
                            {"domain": "map", "status": "LIVE"},
                            {"domain": "web", "status": "MISSING"},
                        ],
                        "evidence_missing": ["网页事实"],
                    }
                ],
            },
        )
        sourced_rail = EvidenceItem(
            evidence_id="guided-rail",
            domain="railway",
            status=EvidenceStatus.SOURCED,
            value={
                "roundtrip_duration_seconds": 7200,
                "roundtrip_fare_cny": 400,
            },
            sources=({"source_type": "official_api", "locator": "test"},),
        )
        sourced_map = EvidenceItem(
            evidence_id="guided-map",
            domain="map",
            status=EvidenceStatus.SOURCED,
            value={"destination": {"adcode": "000000"}},
            sources=({"source_type": "official_api", "locator": "test"},),
        )
        missing_web = EvidenceItem(
            evidence_id="guided-web-missing",
            domain="web",
            status=EvidenceStatus.MISSING,
            value=None,
            missing_reason="web_search_collector_not_configured",
        )
        _persist_guided_evidence(
            created.run_id,
            {
                "option-one": {
                    "railway": sourced_rail.to_dict(),
                    "map": sourced_map.to_dict(),
                    "web": missing_web.to_dict(),
                }
            },
        )
        status, response = _trip_post(
            f"/api/trips/{created.run_id}/candidates/option-one/select",
            {},
        )
        self.assertEqual(status.value, 202)
        self.assertEqual(response["run"]["run_id"], created.run_id)
        self.assertEqual(
            response["run"]["intent"]["task_mode"],
            "DIRECT_PLAN",
        )
        self.assertEqual(
            response["run"]["intent"]["destination_anchor"],
            "乙地",
        )
        self.assertEqual(
            [
                action["action_id"]
                for action in response["action_loop"]["actions"]
            ],
            ["web"],
        )
        self.assertEqual(
            response["presentation"]["compact_progress"]["state"],
            "running",
        )
        self.assertEqual(
            response["presentation"]["compact_progress"][
                "completed_count"
            ],
            2,
        )
        self.assertEqual(
            response["presentation"]["planning_handoff"][
                "roundtrip_transport"
            ]["known_cost_cny"],
            400,
        )
        with patch(
            "trip_decider.agent_actions.collect_railway_evidence"
        ) as railway_query:
            progressed_status, progressed = _trip_post(
                f"/api/trips/{created.run_id}/execute",
                {},
            )
        self.assertEqual(progressed_status.value, 200)
        self.assertEqual(
            progressed["run"]["run_id"],
            created.run_id,
        )
        railway_query.assert_not_called()

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
        self.assertEqual(revised.run_id, run.run_id)
        self.assertEqual(
            store.get_session(run.session_id).run_ids,
            [run.run_id],
        )
        self.assertIsNone(revised.parent_run_id)
        events = store.events_after(run.session_id, 0)
        self.assertEqual(events[-1].event_type, "run.completed")
        encoded = _sse_event(events[-1].to_dict()).decode("utf-8")
        self.assertIn("event: agent_event", encoded)
        self.assertIn('"event_type": "run.completed"', encoded)

    def test_same_run_revision_persists_version_and_retains_old_on_failure(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            store = InMemoryAgentStore(Path(temporary) / "sessions")
            run = create_run(
                {
                    "origin": "甲地",
                    "destination_anchor": "乙地",
                    "earliest_departure_at": "2026-08-04T12:00",
                    "latest_return_at": "2026-08-07T20:00",
                    "travelers": 2,
                    "total_budget_cny": 6000,
                    "pace": "relaxed",
                    "transport_preferences": ["high_speed_rail"],
                },
                store=store,
            )
            confirm_intent(run.run_id, store=store)
            completed = execute_run(
                run.run_id,
                executor=lambda intent, emit: {
                    "plan": {
                        "pace": intent.pace,
                        "days": [{"day": 1, "events": []}],
                    }
                },
                store=store,
            )
            old_result = completed.result
            revised = revise_run(
                run.run_id,
                Revision(pace="standard"),
                executor=lambda previous, revision, emit: {
                    "plan": {
                        "pace": revision.pace,
                        "days": [{"day": 1, "events": []}],
                    },
                    "previous": previous,
                },
                store=store,
            )
            self.assertEqual(revised.run_id, run.run_id)
            version = json.loads(
                (
                    store.run_directory(run.run_id)
                    / "plan-version.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(version["plan_version"], 1)
            with self.assertRaisesRegex(RuntimeError, "revision failed"):
                revise_run(
                    run.run_id,
                    Revision(pace="intensive"),
                    executor=lambda previous, revision, emit: (
                        (_ for _ in ()).throw(
                            RuntimeError("revision failed")
                        )
                    ),
                    store=store,
                )
            failed = store.get_run(run.run_id)
            self.assertEqual(failed.status, RunStatus.FAILED)
            self.assertEqual(failed.result, revised.result)
            self.assertNotEqual(failed.result, old_result)

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

    def test_map_payload_projects_only_persisted_geometry(self) -> None:
        run = {
            "result": {
                "context": {
                    "evidence": [
                        {
                            "domain": "railway",
                            "value": {
                                "snapshot": {
                                    "status": "STALE",
                                    "retrieved_at": "2026-07-30T12:00:00+08:00",
                                }
                            },
                            "sources": [],
                        },
                        {
                            "domain": "web",
                            "value": {
                                "retrieved_at": "2026-07-30T12:01:00+08:00",
                                "hotel_area": {
                                    "name": "住宿片区",
                                    "longitude": 117.86,
                                    "latitude": 29.25,
                                },
                            },
                            "sources": [],
                        },
                        {
                            "domain": "map",
                            "value": {
                                "snapshot_status": "STALE",
                                "retrieved_at": "2026-07-30T12:02:00+08:00",
                                "places": [
                                    {
                                        "name": "景点甲",
                                        "longitude": 117.88,
                                        "latitude": 29.27,
                                    }
                                ],
                                "local_transit": [
                                    {
                                        "route_id": "map-local-1",
                                        "polyline": [
                                            [117.86, 29.25],
                                            [117.88, 29.27],
                                        ],
                                    }
                                ],
                            },
                            "sources": [],
                        },
                    ]
                },
                "plan": {
                    "days": [
                        {
                            "day": 1,
                            "date": "2026-08-04",
                            "events": [
                                {
                                    "event_id": "rail-outbound",
                                    "type": "transit",
                                    "name": "去程 G1",
                                    "from": "出发站",
                                    "to": "目的站",
                                    "from_location": {
                                        "longitude": 114.30,
                                        "latitude": 30.59,
                                    },
                                    "to_location": {
                                        "longitude": 117.86,
                                        "latitude": 29.25,
                                    },
                                    "start_at": "2026-08-04T12:00",
                                    "end_at": "2026-08-04T15:00",
                                },
                                {
                                    "event_id": "attraction-1",
                                    "type": "attraction",
                                    "name": "景点甲",
                                },
                            ],
                        }
                    ],
                    "planning_input": {
                        "local_transit_events": [
                            {
                                "event_id": "map-local-1",
                                "type": "transit",
                                "from": "住宿片区",
                                "to": "景点甲",
                                "mode": "public_transit",
                                "schedule_status": "STALE",
                            }
                        ]
                    },
                },
            }
        }
        payload = _map_payload_contract(run, plan_version=3)
        self.assertEqual(payload["plan_version"], 3)
        self.assertEqual(
            set(payload),
            {"plan_version", "day", "markers", "route_polylines"},
        )
        self.assertEqual(
            sum(bool(item.get("position")) for item in payload["markers"]),
            4,
        )
        self.assertEqual(
            payload["route_polylines"][0]["geometry_status"],
            "EXISTING_POLYLINE",
        )
        self.assertEqual(
            payload["route_polylines"][0]["evidence_status"],
            "STALE",
        )
        self.assertEqual(
            len(payload["route_polylines"][0]["polyline"]),
            2,
        )

    def test_map_payload_keeps_missing_geometry_explicit(self) -> None:
        payload = _map_payload_contract(
            {
                "result": {
                    "context": {
                        "evidence": [
                            {
                                "domain": "map",
                                "value": {
                                    "local_transit": [
                                        {"route_id": "map-local-1"}
                                    ]
                                },
                            }
                        ]
                    },
                    "plan": {
                        "days": [
                            {
                                "day": 1,
                                "events": [
                                    {
                                        "event_id": "attraction-1",
                                        "type": "attraction",
                                        "name": "景点甲",
                                    }
                                ],
                            }
                        ],
                        "planning_input": {
                            "local_transit_events": [
                                {
                                    "event_id": "map-local-1",
                                    "from": "住宿片区",
                                    "to": "景点甲",
                                }
                            ]
                        },
                    },
                }
            },
            plan_version=1,
        )
        self.assertEqual(
            sum(bool(item.get("position")) for item in payload["markers"]),
            0,
        )
        self.assertEqual(
            payload["route_polylines"][0]["geometry_status"],
            "MISSING_GEOMETRY",
        )
        self.assertEqual(payload["route_polylines"][0]["polyline"], [])

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
            "src/trip_decider/guided_discovery.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            for city in forbidden:
                self.assertNotIn(city, source, msg=f"{city} found in {relative}")

    def test_home_only_exposes_new_history_and_explicit_continue_entry(
        self,
    ) -> None:
        html = (ROOT / "src/trip_decider/web/index.html").read_text(
            encoding="utf-8"
        )
        script = (ROOT / "src/trip_decider/web/app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("新建旅行任务", html)
        self.assertIn("历史行程", html)
        self.assertIn("继续上一次行程", html)
        self.assertIn("<textarea", html)
        self.assertIn(
            'id="confirmation" class="confirmation hidden"',
            html,
        )
        self.assertIn(
            'id="workbench" class="workbench hidden"',
            html,
        )
        for map_element in (
            "map-column",
            "map-day-tabs",
            "map-canvas",
            "railway-map-cards",
            "map-missing-geometry",
        ):
            self.assertIn(map_element, html)
        for map_behavior in (
            "/api/client-config",
            "https://webapi.amap.com/maps?v=2.0",
            "renderMapPanel",
            "applyMapDayFilter",
            "bindTimelineMapEvent",
            "setSelectedEvent",
            "EXISTING_POLYLINE",
            "ENDPOINTS_ONLY",
        ):
            self.assertIn(map_behavior, script)
        self.assertNotIn('id="progress-grid"', html)
        self.assertNotIn('id="run-message"', html)
        for compact_id in (
            "compact-progress",
            "compact-progress-fill",
            "compact-progress-percent",
            "compact-progress-task",
            "compact-progress-elapsed",
        ):
            self.assertIn(compact_id, html)
        for action in ("继续查询", "手动补充", "暂时跳过"):
            self.assertIn(action, html + script)
        self.assertIn("开始比较区域方案", html + script)
        self.assertNotIn("直接规划该目的地", html + script)
        self.assertNotIn("直接规划婺源", html + script)
        for field in (
            "往返交通",
            "已知费用",
            "可游玩时间",
            "当地交通难度",
            "预算余量",
            "证据缺失",
            "粗计划状态",
        ):
            self.assertIn(field, script)
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
        self.assertNotIn("<details", html)
        self.assertNotIn("查看技术详情", html + script)
        self.assertNotIn("执行事件", html + script)
        self.assertNotIn("Plan ID", html)
        self.assertNotIn("Context ID", html)
        self.assertIn("new EventSource", script)
        self.assertNotIn("/api/agent/", script)
        self.assertIn("/api/trips", script)
        self.assertIn('"revise_existing"', script)
        self.assertIn("/revisions", script)
        self.assertIn("当前继续显示上一版行程", script)
        self.assertIn("继续完善行程", script)
        self.assertIn("/execute", script)
        self.assertIn("renderTimeline", script)
        for evidence_status in ("LIVE", "STALE", "MISSING"):
            self.assertIn(evidence_status, script)

    def test_presentation_requires_three_attractions_and_route_chain(
        self,
    ) -> None:
        events = [
            {
                "event_id": "rail-outbound",
                "type": "transit",
                "snapshot_status": "STALE",
            },
            {
                "event_id": "rail-return",
                "type": "transit",
                "snapshot_status": "STALE",
            },
            *[
                {
                    "event_id": f"attraction-{index}",
                    "type": "attraction",
                }
                for index in range(3)
            ],
            *[
                {
                    "event_id": f"map-local-{index}",
                    "type": "transit",
                }
                for index in range(3)
            ],
        ]
        presentation = _presentation_contract(
            {
                "result": {
                    "plan": {
                        "days": [{"day": 1, "events": events}],
                        "display_requirements": {
                            "accommodation_base": True,
                        },
                        "conditional_blockers": [
                            {"blocker_id": "HOTEL_DETAIL_PENDING"}
                        ],
                    }
                }
            }
        )
        self.assertEqual(presentation["day_count"], 1)
        self.assertEqual(presentation["event_count"], 8)
        self.assertEqual(presentation["attraction_count"], 3)
        self.assertEqual(presentation["local_transit_count"], 3)
        self.assertTrue(presentation["detailed_itinerary_ready"])
        statuses = {
            item["domain"]: item["status"]
            for item in presentation["evidence_statuses"]
        }
        self.assertEqual(statuses["railway"], "STALE")
        self.assertEqual(statuses["attraction"], "LIVE")
        self.assertEqual(statuses["local_transit"], "LIVE")
        self.assertEqual(statuses["accommodation"], "LIVE")

        events.pop()
        presentation = _presentation_contract(
            {
                "result": {
                    "plan": {
                        "days": [{"day": 1, "events": events}],
                        "display_requirements": {
                            "accommodation_base": True,
                        },
                    }
                }
            }
        )
        self.assertFalse(presentation["detailed_itinerary_ready"])

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
            _trip_post(
                "/api/trips",
                {"text": "请规划一次旅行"},
            )

    def test_acceptance_intent_is_complete_and_waits_for_confirmation(
        self,
    ) -> None:
        status, response = _trip_post(
            "/api/trips",
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
        self.addCleanup(
            shutil.rmtree,
            DEFAULT_AGENT_STORE.runtime_root / response["run"]["run_id"],
            True,
        )
        intent = response["run"]["intent"]
        self.assertEqual(response["run"]["status"], "AWAITING_CONFIRMATION")
        self.assertEqual(intent["task_mode"], "GUIDED_DISCOVERY")
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
