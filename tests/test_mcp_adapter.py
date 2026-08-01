from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from urllib.request import Request, urlopen

from mcp.client._memory import InMemoryTransport
from mcp.client.session import ClientSession

from trip_decider import mcp_adapter, product_web
from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.mcp_adapter import TripMCPAdapter
from trip_decider.mcp_app import (
    TRIP_MCP_APP_MIME_TYPE,
    TRIP_MCP_APP_URI,
)
from trip_decider.mcp_server import build_mcp_server
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService
from trip_decider.travel_agent import (
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
)


class _NoBackgroundApplication(TripApplicationService):
    @staticmethod
    def _spawn(*, target: object, args: object, name: str) -> None:
        del target, args, name


def _intent() -> dict[str, object]:
    return {
        "task_mode": "GUIDED_DISCOVERY",
        "origin": "甲地",
        "destination_anchor": "乙地区",
        "destination_expression": "倾向乙地区",
        "earliest_departure_at": "2026-08-04T12:00",
        "latest_return_at": "2026-08-07T22:00",
        "travelers": 2,
        "total_budget_cny": 6000,
        "pace": "relaxed",
        "transport_preferences": ["rail"],
        "themes": ["自然", "古村"],
    }


def _railway() -> EvidenceItem:
    retrieved_at = "2026-08-01T09:00:00+08:00"
    return EvidenceItem(
        evidence_id="controlled-railway",
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
                "status": "LIVE",
                "retrieved_at": retrieved_at,
                "attempted_at": retrieved_at,
                "availability_semantics": "current_at_retrieval_only",
                "display": "LIVE",
            },
            "roundtrip_fare_cny": 800.0,
        },
        sources=(
            {
                "provider": "controlled-rail",
                "retrieved_at": retrieved_at,
            },
        ),
    )


def _map() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="controlled-map",
        domain="map",
        status=EvidenceStatus.SOURCED,
        value={
            "destination": {"name": "乙地"},
            "local_transit": [
                {
                    "route_id": "route-station-base",
                    "from": "乙站",
                    "to": "住宿片区",
                    "duration_seconds": 1800,
                    "distance_meters": 12000,
                    "fare": {"status": "unknown", "amount_cny": None},
                },
                {
                    "route_id": "route-base-spot",
                    "from": "住宿片区",
                    "to": "景点甲",
                    "duration_seconds": 1200,
                    "distance_meters": 6000,
                    "fare": {"status": "unknown", "amount_cny": None},
                },
            ],
        },
        sources=({"provider": "controlled-map"},),
    )


def _web() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="controlled-web",
        domain="web",
        status=EvidenceStatus.SOURCED,
        value={
            "destination_official_name": "乙地",
            "verified_facts": [
                {
                    "field": "official_administrative_name",
                    "value": "乙地",
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
        sources=({"publisher": "controlled-web"},),
    )


def _comparison(intent: object, **arguments: object) -> dict[str, object]:
    del intent
    option = {
        "destination_id": "candidate-one",
        "destination_anchor": "乙地",
        "coarse_feasibility": "CONDITIONALLY_FEASIBLE",
    }
    progress = arguments.get("progress")
    if callable(progress):
        progress("comparison_started", "乙地区", {"candidate_count": 1})
        progress("candidate_completed", "乙地", {"option": option})
    evidence = {
        item.domain: item.to_dict()
        for item in (_railway(), _map(), _web())
    }
    return {
        "stage": "guided_discovery",
        "task_mode": "GUIDED_DISCOVERY",
        "options": [option],
        "option_count": 1,
        "selection_required": True,
        "reusable_evidence": {"candidate-one": evidence},
    }


def _services(root: Path) -> tuple[TripApplicationService, TripQueryService]:
    store = InMemoryAgentStore(root)
    application = TripApplicationService(
        store=store,
        evidence_broker=EvidenceBroker(root.parent / "evidence-cache"),
        comparison_builder=_comparison,
    )
    query = TripQueryService(
        store=store,
        application_service=application,
    )
    return application, query


async def _call(
    session: ClientSession,
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    result = await session.call_tool(name, arguments)
    if result.is_error:
        detail = result.content[0].text if result.content else "MCP error"
        raise AssertionError(detail)
    if not isinstance(result.structured_content, dict):
        raise AssertionError("tool omitted structured content")
    return result.structured_content


def _http_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class TripMCPAdapterTests(unittest.TestCase):
    def test_adapter_has_no_store_http_or_projection_dependency(self) -> None:
        source = inspect.getsource(mcp_adapter)
        for forbidden in (
            "InMemoryAgentStore",
            "DEFAULT_AGENT_STORE",
            "product_web",
            "urllib",
            "trip_read_model",
            "_presentation_contract",
            "_map_payload_contract",
        ):
            self.assertNotIn(forbidden, source)

    def test_sourced_evidence_resumes_a_blocked_direct_run(self) -> None:
        store = InMemoryAgentStore()
        application = _NoBackgroundApplication(store=store)
        query = TripQueryService(
            store=store,
            application_service=application,
        )
        adapter = TripMCPAdapter(application, query)
        intent = _intent()
        intent.update(
            {
                "task_mode": "DIRECT_PLAN",
                "destination_anchor": "乙地",
                "destination_expression": "确定乙地",
            }
        )
        run_id = str(adapter.create_trip_task(intent)["run"]["run_id"])
        adapter.confirm_trip_intent(run_id)
        application.execute_trip(run_id)
        store.block(
            run_id,
            {"action_loop_status": "BLOCKED", "blocked_domains": ["web"]},
            "WEB_EVIDENCE_REQUIRED",
        )

        response = adapter.submit_trip_evidence(
            run_id,
            {**_web().to_dict(), "action_id": "web"},
        )

        self.assertEqual(response["trip"]["run"]["status"], "RUNNING")
        self.assertIsNotNone(response["action_loop"])

    def test_mcp_and_web_share_versions_and_restart_recovery(self) -> None:
        asyncio.run(self._lifecycle())

    async def _lifecycle(self) -> None:
        with TemporaryDirectory() as temporary:
            sessions_root = Path(temporary) / "sessions"
            old_services = (
                product_web.DEFAULT_TRIP_APPLICATION_SERVICE,
                product_web.DEFAULT_TRIP_QUERY_SERVICE,
            )
            application, query = _services(sessions_root)
            product_web.configure_services(application, query)
            web_server = product_web.make_server("127.0.0.1", 0)
            web_thread = threading.Thread(
                target=web_server.serve_forever,
                daemon=True,
            )
            web_thread.start()
            host, port = web_server.server_address
            base_url = f"http://{host}:{port}"
            try:
                server = build_mcp_server(TripMCPAdapter(application, query))
                async with InMemoryTransport(server) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        self.assertEqual(
                            [tool.name for tool in tools.tools],
                            [
                                "create_trip_task",
                                "confirm_trip_intent",
                                "advance_trip_task",
                                "read_trip",
                                "show_trip_candidates",
                                "show_trip_plan",
                                "select_trip_candidate",
                                "submit_trip_evidence",
                                "revise_trip_plan",
                                "audit_trip_plan",
                            ],
                        )
                        render_tools = {
                            tool.name: tool for tool in tools.tools
                            if tool.name.startswith("show_trip_")
                        }
                        self.assertEqual(
                            set(render_tools),
                            {"show_trip_candidates", "show_trip_plan"},
                        )
                        for tool in render_tools.values():
                            self.assertEqual(
                                tool.meta["ui"]["resourceUri"],
                                TRIP_MCP_APP_URI,
                            )
                        by_name = {tool.name: tool for tool in tools.tools}
                        for name in (
                            "advance_trip_task",
                            "select_trip_candidate",
                            "revise_trip_plan",
                            "show_trip_candidates",
                            "show_trip_plan",
                        ):
                            self.assertIn(
                                "app",
                                by_name[name].meta["ui"]["visibility"],
                            )
                            self.assertTrue(
                                by_name[name].meta[
                                    "openai/widgetAccessible"
                                ]
                            )
                            self.assertEqual(
                                tool.meta["openai/outputTemplate"],
                                TRIP_MCP_APP_URI,
                            )
                        resources = await session.list_resources()
                        self.assertEqual(len(resources.resources), 1)
                        self.assertEqual(
                            str(resources.resources[0].uri),
                            TRIP_MCP_APP_URI,
                        )
                        self.assertEqual(
                            resources.resources[0].mime_type,
                            TRIP_MCP_APP_MIME_TYPE,
                        )
                        resource = await session.read_resource(
                            TRIP_MCP_APP_URI
                        )
                        self.assertEqual(len(resource.contents), 1)
                        app_html = resource.contents[0].text
                        for required in (
                            'request("ui/initialize"',
                            'request("tools/call"',
                            '"select_trip_candidate"',
                            '"advance_trip_task"',
                            '"revise_trip_plan"',
                            "requestDisplayMode",
                        ):
                            self.assertIn(required, app_html)
                        for forbidden in (
                            "/api/",
                            "localStorage",
                            "sessionStorage",
                            "innerHTML",
                        ):
                            self.assertNotIn(forbidden, app_html)
                        created = await _call(
                            session,
                            "create_trip_task",
                            {"intent": _intent()},
                        )
                        run_id = str(created["run"]["run_id"])
                        await _call(
                            session,
                            "confirm_trip_intent",
                            {"run_id": run_id},
                        )
                        comparison = await _call(
                            session,
                            "advance_trip_task",
                            {"run_id": run_id, "wait_seconds": 5},
                        )
                        self.assertEqual(
                            comparison["checkpoint"],
                            "CANDIDATES_READY",
                        )
                        candidates = await _call(
                            session,
                            "read_trip",
                            {"run_id": run_id, "view": "candidates"},
                        )
                        self.assertEqual(
                            candidates["candidates"][0]["destination_id"],
                            "candidate-one",
                        )
                        candidate_app = await _call(
                            session,
                            "show_trip_candidates",
                            {"run_id": run_id},
                        )
                        self.assertEqual(candidate_app["view"], "candidates")
                        self.assertEqual(
                            candidate_app["candidates"],
                            candidates,
                        )
                        await _call(
                            session,
                            "select_trip_candidate",
                            {
                                "run_id": run_id,
                                "candidate_id": "candidate-one",
                            },
                        )
                        planned = await _call(
                            session,
                            "advance_trip_task",
                            {"run_id": run_id, "wait_seconds": 5},
                        )
                        self.assertEqual(
                            planned["checkpoint"],
                            "PLAN_OR_PARTIAL_RESULT_READY",
                        )
                        plan_one = await _call(
                            session,
                            "read_trip",
                            {"run_id": run_id, "view": "plan"},
                        )
                        self.assertEqual(plan_one["plan_version"], 1)
                        plan_app_one = await _call(
                            session,
                            "show_trip_plan",
                            {"run_id": run_id},
                        )
                        self.assertEqual(plan_app_one["view"], "plan")
                        self.assertEqual(plan_app_one["current_version"], 1)
                        self.assertEqual(plan_app_one["plan"], plan_one)

                        web_candidates = _http_json(
                            f"{base_url}/api/trips/{run_id}/candidates"
                        )
                        web_plan_one = _http_json(
                            f"{base_url}/api/trips/{run_id}/plans/current"
                        )
                        self.assertEqual(
                            web_candidates["candidates"],
                            candidates["candidates"],
                        )
                        self.assertTrue(
                            web_candidates["comparison_completed"]
                        )
                        self.assertEqual(web_plan_one, plan_one)

                        web_revision = _http_json(
                            f"{base_url}/api/trips/{run_id}/revisions",
                            method="POST",
                            payload={
                                "revision": {
                                    "pace": "standard",
                                    "user_message": "调整为标准节奏",
                                }
                            },
                        )
                        self.assertEqual(
                            web_revision["presentation"]["plan_version"],
                            2,
                        )
                        plan_two = await _call(
                            session,
                            "read_trip",
                            {"run_id": run_id, "view": "plan"},
                        )
                        self.assertEqual(plan_two["plan_version"], 2)
                        self.assertIn("revision", plan_two["plan"])
                        self.assertIn("diff", plan_two["plan"]["revision"])
                        plan_app_two = await _call(
                            session,
                            "show_trip_plan",
                            {"run_id": run_id},
                        )
                        self.assertEqual(plan_app_two["current_version"], 2)
                        self.assertEqual(plan_app_two["plan"], plan_two)
                        audit = await _call(
                            session,
                            "audit_trip_plan",
                            {
                                "plan": {
                                    "days": [
                                        {"day": 1, "events": []},
                                    ]
                                }
                            },
                        )
                        self.assertEqual(
                            audit["audit"]["stage"],
                            "plan_audit",
                        )
                        self.assertFalse(
                            audit["audit"]["planner_invoked"]
                        )
            finally:
                web_server.shutdown()
                web_server.server_close()
                web_thread.join(timeout=5)

            restored_application, restored_query = _services(sessions_root)
            product_web.configure_services(
                restored_application,
                restored_query,
            )
            restored_web = product_web.make_server("127.0.0.1", 0)
            restored_thread = threading.Thread(
                target=restored_web.serve_forever,
                daemon=True,
            )
            restored_thread.start()
            restored_host, restored_port = restored_web.server_address
            try:
                restored_server = build_mcp_server(
                    TripMCPAdapter(restored_application, restored_query)
                )
                async with InMemoryTransport(restored_server) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        restored_plan = await _call(
                            session,
                            "read_trip",
                            {"run_id": run_id, "view": "plan"},
                        )
                        self.assertEqual(restored_plan["plan_version"], 2)
                        self.assertIn(
                            "diff",
                            restored_plan["plan"]["revision"],
                        )
                        restored_app = await _call(
                            session,
                            "show_trip_plan",
                            {"run_id": run_id},
                        )
                        self.assertEqual(
                            restored_app["current_version"],
                            2,
                        )
                        self.assertEqual(
                            restored_app["plan"],
                            restored_plan,
                        )
                restored_web_plan = _http_json(
                    "http://"
                    f"{restored_host}:{restored_port}/api/trips/"
                    f"{run_id}/plans/current"
                )
                self.assertEqual(restored_web_plan, restored_plan)
            finally:
                restored_web.shutdown()
                restored_web.server_close()
                restored_thread.join(timeout=5)
                product_web.configure_services(*old_services)


if __name__ == "__main__":
    unittest.main()
