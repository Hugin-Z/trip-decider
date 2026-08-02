from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import trip_decider.agent_actions as agent_actions
from trip_decider.agent_actions import (
    execute_registered_action,
    start_action_loop,
)
from trip_decider.evidence_broker import (
    EvidenceBroker,
    FRESHNESS_POLICIES,
    evidence_query,
)
from trip_decider.guided_discovery import build_guided_comparison
from trip_decider.travel_agent import (
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
    TravelIntent,
)


class EvidenceBrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

    def test_freshness_policy_has_explicit_non_reusable_values(self) -> None:
        self.assertFalse(FRESHNESS_POLICIES["seat_availability"].stale_allowed)
        self.assertFalse(FRESHNESS_POLICIES["hotel_price"].stale_allowed)
        self.assertEqual(
            FRESHNESS_POLICIES["railway_schedule_fare"].stale_ttl_seconds,
            6 * 60 * 60,
        )
        self.assertEqual(
            FRESHNESS_POLICIES["route_duration"].stale_ttl_seconds,
            6 * 60 * 60,
        )
        self.assertEqual(
            FRESHNESS_POLICIES["poi_coordinate"].stale_ttl_seconds,
            30 * 24 * 60 * 60,
        )

    def test_exact_query_and_ttl_are_required_for_cross_run_stale(self) -> None:
        broker = EvidenceBroker(clock=lambda: self.now)
        query = self._query()
        broker.publish(
            run_id="seed-run",
            query=query,
            evidence=self._rail("seed-value"),
            collected_at=(self.now - timedelta(hours=1)).isoformat(),
        )
        failed = self._missing()
        reused = broker.stale_after_failure(
            run_id="fresh-run",
            query=query,
            live_failure=failed,
        )
        self.assertIsNotNone(reused)
        assert reused is not None
        self.assertEqual(reused.value["snapshot"]["status"], "STALE")
        self.assertEqual(
            reused.value["outbound"]["second_class_availability"],
            "UNKNOWN",
        )
        changed = evidence_query(
            provider=query.provider,
            origin=query.origin,
            destination="另一目的地",
            query_parameters=query.query_parameters,
            earliest_departure_at=query.earliest_departure_at,
            latest_return_at=query.latest_return_at,
            data_type=query.data_type,
        )
        self.assertIsNone(
            broker.stale_after_failure(
                run_id="different-run",
                query=changed,
                live_failure=failed,
            )
        )
        mismatches = (
            replace(query, provider="另一提供方"),
            replace(query, origin="另一出发地"),
            replace(query, destination="另一目的地"),
            replace(query, query_parameters={"travelers": 3}),
            replace(
                query,
                earliest_departure_at="2026-08-04T13:00:00+08:00",
            ),
            replace(
                query,
                latest_return_at="2026-08-07T21:00:00+08:00",
            ),
            replace(query, data_type="route_duration"),
        )
        for mismatch in mismatches:
            with self.subTest(field=mismatch.to_dict()):
                self.assertIsNone(
                    broker.stale_after_failure(
                        run_id="different-run",
                        query=mismatch,
                        live_failure=failed,
                    )
                )

    def test_expired_or_never_stale_values_are_not_reused(self) -> None:
        broker = EvidenceBroker(clock=lambda: self.now)
        expired = self._query()
        broker.publish(
            run_id="seed-run",
            query=expired,
            evidence=self._rail("old"),
            collected_at=(self.now - timedelta(hours=7)).isoformat(),
        )
        self.assertIsNone(
            broker.stale_after_failure(
                run_id="new-run",
                query=expired,
                live_failure=self._missing(),
            )
        )
        for data_type in ("seat_availability", "hotel_price"):
            query = evidence_query(
                provider="test-provider",
                origin="A",
                destination="B",
                query_parameters={"date": "2026-08-04"},
                earliest_departure_at="2026-08-04T12:00:00+08:00",
                latest_return_at="2026-08-07T22:00:00+08:00",
                data_type=data_type,
            )
            broker.publish(
                run_id="seed-run",
                query=query,
                evidence=self._sourced(data_type),
                collected_at=self.now.isoformat(),
            )
            self.assertIsNone(
                broker.stale_after_failure(
                    run_id="new-run",
                    query=query,
                    live_failure=self._missing(domain="railway"),
                )
            )

    def test_fixture_and_catalog_sources_are_rejected(self) -> None:
        broker = EvidenceBroker(clock=lambda: self.now)
        evidence = EvidenceItem(
            evidence_id="fixture-evidence",
            domain="railway",
            status=EvidenceStatus.SOURCED,
            value={"snapshot": {"retrieved_at": self.now.isoformat()}},
            sources=(
                {
                    "provider": "中国铁路12306",
                    "retrieved_at": self.now.isoformat(),
                    "locator": "golden-fixture/catalog",
                },
            ),
        )
        with self.assertRaisesRegex(Exception, "fixture or catalog"):
            broker.publish(
                run_id="run",
                query=self._query(),
                evidence=evidence,
                collected_at=self.now.isoformat(),
            )

    def test_two_fresh_runs_do_not_inherit_previous_run_evidence(self) -> None:
        with TemporaryDirectory() as root_value:
            root = Path(root_value)
            store = InMemoryAgentStore(runtime_root=root / "sessions")
            broker = EvidenceBroker(
                root / "cache",
                clock=lambda: self.now,
            )
            intent = self._intent("目的地甲")
            original_handler = agent_actions._TOOL_REGISTRY["railway"][
                "handler"
            ]
            try:
                agent_actions._TOOL_REGISTRY["railway"]["handler"] = (
                    lambda _intent, _state: self._rail("seed-value")
                )
                self._execute_railway(store, broker, intent)

                agent_actions._TOOL_REGISTRY["railway"]["handler"] = (
                    lambda _intent, _state: self._rail("fresh-value")
                )
                live_run = self._execute_railway(store, broker, intent)
                live_value = self._current_rail(store, live_run)
                self.assertEqual(live_value["marker"], "fresh-value")
                self.assertEqual(live_value["snapshot"]["status"], "LIVE")

                agent_actions._TOOL_REGISTRY["railway"]["handler"] = (
                    lambda _intent, _state: self._missing()
                )
                changed_run = self._execute_railway(
                    store,
                    broker,
                    self._intent("目的地乙"),
                )
                changed_document = self._current_document(store, changed_run)
                self.assertEqual(changed_document["status"], "missing")
                self.assertNotIn("marker", changed_document.get("value") or {})

                live_namespace = self._namespace(store, live_run)
                changed_namespace = self._namespace(store, changed_run)
                self.assertEqual(live_namespace["run_id"], live_run)
                self.assertEqual(changed_namespace["run_id"], changed_run)
                self.assertNotEqual(live_namespace["run_id"], changed_namespace["run_id"])
            finally:
                agent_actions._TOOL_REGISTRY["railway"][
                    "handler"
                ] = original_handler

    def test_guided_comparison_is_live_first_then_uses_exact_stale(self) -> None:
        broker = EvidenceBroker(clock=lambda: self.now)
        intent = TravelIntent.from_mapping(
            {
                "task_mode": "GUIDED_DISCOVERY",
                "origin": "Origin",
                "destination_anchor": "Region",
                "earliest_departure_at": "2026-08-04T12:00:00",
                "latest_return_at": "2026-08-07T22:00:00",
                "travelers": 2,
                "total_budget_cny": 6000,
            }
        )
        seeds = [
            {
                "id": "destination-one",
                "name": "Destination One",
                "region_label": "Region",
                "planning_city": "Destination One",
                "rail_gateway": "Destination One",
                "themes": [],
                "intensity": "standard",
            }
        ]
        calls: list[str] = []

        def live(_intent: TravelIntent) -> EvidenceItem:
            calls.append("live")
            return self._rail("guided-live")

        def failed(_intent: TravelIntent) -> EvidenceItem:
            calls.append("failed")
            return self._missing()

        with patch(
            "trip_decider.guided_discovery.guided_region_seeds",
            return_value=seeds,
        ):
            first = build_guided_comparison(
                intent,
                railway_collector=live,
                run_id="guided-one",
                evidence_broker=broker,
            clock=lambda: self.now,
            )
            second = build_guided_comparison(
                intent,
                railway_collector=failed,
                run_id="guided-two",
                evidence_broker=broker,
            clock=lambda: self.now,
            )
        self.assertEqual(calls, ["live", "failed"])
        self.assertEqual(
            first["options"][0]["roundtrip_transport"]["token"],
            "verified",
        )
        self.assertEqual(
            second["options"][0]["roundtrip_transport"]["token"],
            "sourced_stale",
        )
        self.assertTrue(
            second["options"][0]["roundtrip_transport"]["from_cache"]
        )

    def _execute_railway(
        self,
        store: InMemoryAgentStore,
        broker: EvidenceBroker,
        intent: TravelIntent,
    ) -> str:
        run = store.create(intent)
        store.confirm(run.run_id, None)
        start_action_loop(run.run_id, store=store)
        execute_registered_action(
            run.run_id,
            "railway",
            store=store,
            evidence_broker=broker,
        )
        return run.run_id

    def _current_document(
        self,
        store: InMemoryAgentStore,
        run_id: str,
    ) -> dict[str, object]:
        directory = store.run_directory(run_id)
        assert directory is not None
        document = json.loads(
            (directory / "evidence" / "current.json").read_text(
                encoding="utf-8"
            )
        )
        return next(
            item
            for item in document["current"]
            if item["domain"] == "railway"
        )

    def _current_rail(
        self,
        store: InMemoryAgentStore,
        run_id: str,
    ) -> dict[str, object]:
        return self._current_document(store, run_id)["value"]

    def _namespace(
        self,
        store: InMemoryAgentStore,
        run_id: str,
    ) -> dict[str, object]:
        directory = store.run_directory(run_id)
        assert directory is not None
        return json.loads(
            (directory / "evidence" / "namespace.json").read_text(
                encoding="utf-8"
            )
        )

    def _query(self):
        return evidence_query(
            provider="中国铁路12306",
            origin="出发地",
            destination="目的地甲",
            query_parameters={
                "travelers": 2,
                "total_budget_cny": 6000,
                "transport_preferences": ["rail"],
            },
            earliest_departure_at="2026-08-04T12:00:00+08:00",
            latest_return_at="2026-08-07T22:00:00+08:00",
            data_type="railway_schedule_fare",
        )

    def _intent(self, destination: str) -> TravelIntent:
        return TravelIntent.from_mapping(
            {
                "task_mode": "DIRECT_PLAN",
                "origin": "出发地",
                "destination_anchor": destination,
                "earliest_departure_at": "2026-08-04T12:00:00",
                "latest_return_at": "2026-08-07T22:00:00",
                "travelers": 2,
                "total_budget_cny": 6000,
                "pace": "relaxed",
                "transport_preferences": ["rail"],
            }
        )

    def _rail(self, marker: str) -> EvidenceItem:
        collected = (self.now - timedelta(minutes=5)).isoformat()
        return EvidenceItem(
            evidence_id=f"rail-{marker}",
            domain="railway",
            status=EvidenceStatus.SOURCED,
            value={
                "marker": marker,
                "snapshot": {
                    "status": "LIVE",
                    "retrieved_at": collected,
                },
                "outbound": {
                    "schedule_status": "LIVE",
                    "fare_status": "LIVE",
                    "second_class_availability": "有",
                },
                "return": {
                    "schedule_status": "LIVE",
                    "fare_status": "LIVE",
                    "second_class_availability": "有",
                },
            },
            sources=(
                {
                    "provider": "中国铁路12306",
                    "retrieved_at": collected,
                    "locator": "official-query",
                },
            ),
        )

    def _sourced(self, data_type: str) -> EvidenceItem:
        return EvidenceItem(
            evidence_id=data_type,
            domain="railway",
            status=EvidenceStatus.SOURCED,
            value={"retrieved_at": self.now.isoformat()},
            sources=(
                {
                    "provider": "test-provider",
                    "retrieved_at": self.now.isoformat(),
                    "locator": "official-query",
                },
            ),
        )

    @staticmethod
    def _missing(domain: str = "railway") -> EvidenceItem:
        return EvidenceItem(
            evidence_id="live-failure",
            domain=domain,
            status=EvidenceStatus.MISSING,
            value={"attempted_at": "2026-08-01T12:00:00+00:00"},
            missing_reason="http_failure",
        )


if __name__ == "__main__":
    unittest.main()
