"""读取层适配器的核对。

契约：docs/contracts/freshness-policy.md §2.2、docs/contracts/reason-code-inventory.md
阶段：P3a
"""

from __future__ import annotations

from trip_decider.travel_agent import EvidenceItem, EvidenceStatus

from datetime import datetime, timedelta, timezone
import unittest

from trip_decider.evidence_core import REASON_CODES
from trip_decider.evidence_projection import (
    DOMAIN_DATA_TYPES,
    READ_POLICIES,
    internal_contract_violation_event,
    is_supported,
    project_domain,
    reason_code_for,
    verdict_payload,
)

from tests.invariant_support import parse_policy_registry

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _item(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "evidence_id": "e1",
        "domain": "railway",
        "status": "sourced",
        "value": {
            "departure_at": "2026-08-04T13:00",
            "retrieved_at": (NOW - timedelta(hours=1)).isoformat(),
        },
        "sources": [
            {
                "provider": "12306",
                "retrieved_at": (NOW - timedelta(hours=1)).isoformat(),
            }
        ],
        "missing_reason": None,
        "conflict_details": [],
    }
    base.update(overrides)
    # 经真实写入路径产出 v2 形状。读取层只认 v2——手写 v1 dict 喂进去会
    # 得到零 facts，测的就不是产品会遇到的输入了。
    return EvidenceItem(
        evidence_id=str(base["evidence_id"]),
        domain=str(base["domain"]),
        status=EvidenceStatus(str(base["status"])),
        value=base["value"],
        sources=tuple(dict(item) for item in base["sources"]),
        missing_reason=base["missing_reason"],
        conflict_details=tuple(base["conflict_details"]),
    ).to_dict()


class PolicyMirrorCase(unittest.TestCase):
    """READ_POLICIES 是契约表的手工镜像，漂移必须被抓住。"""

    def test_read_policies_match_the_contract_registry(self) -> None:
        registry = parse_policy_registry()
        self.assertEqual(
            sorted(registry),
            sorted(READ_POLICIES),
            "READ_POLICIES 的键与 freshness-policy.md §2.2 不一致",
        )
        problems: list[str] = []
        for name, row in sorted(registry.items()):
            policy = READ_POLICIES[name]
            if policy.tolerance_seconds != row["tolerance_seconds"]:
                problems.append(
                    f"{name}: tolerance {policy.tolerance_seconds} != "
                    f"{row['tolerance_seconds']}"
                )
            if policy.feasibility_critical != row["feasibility_critical"]:
                problems.append(
                    f"{name}: feasibility_critical "
                    f"{policy.feasibility_critical} != {row['feasibility_critical']}"
                )
            if policy.on_stale != row["on_stale"]:
                problems.append(
                    f"{name}: on_stale {policy.on_stale} != {row['on_stale']}"
                )
            if policy.stale_allowed != row["stale_allowed"]:
                problems.append(
                    f"{name}: stale_allowed "
                    f"{policy.stale_allowed} != {row['stale_allowed']}"
                )
        self.assertEqual(
            [], problems, "策略镜像与契约漂移：\n  " + "\n  ".join(problems)
        )

    def test_every_domain_maps_to_a_registered_data_type(self) -> None:
        for domain, data_type in DOMAIN_DATA_TYPES.items():
            with self.subTest(domain=domain):
                self.assertIn(data_type, READ_POLICIES)
        self.assertIn("route_duration", READ_POLICIES)


class ReasonCodeMappingCase(unittest.TestCase):
    def test_every_mapped_code_is_in_the_contract_vocabulary(self) -> None:
        literals = [
            "collector_not_configured",
            "amap_web_service_key_not_configured",
            "credential",
            "collector_timeout",
            "rail_http",
            "district_parse",
            "exact_destination_district_not_found",
            "cancelled_by_user",
            "destination_anchor_not_supplied",
            "input_validation",
            "route_input",
            "district_observation_policy",
            "poi_observation_policy",
        ]
        for literal in literals:
            with self.subTest(literal=literal):
                self.assertIn(reason_code_for(literal), REASON_CODES)

    def test_domain_prefixed_and_suffixed_literals_are_recognised(self) -> None:
        for domain in ("railway", "map", "web"):
            self.assertEqual(
                "collector_not_configured",
                reason_code_for(f"{domain}_collector_not_configured"),
            )
        self.assertEqual(
            "collector_error", reason_code_for("collector_error:TimeoutError")
        )

    def test_unregistered_literals_degrade_to_collector_error(self) -> None:
        """归错比丢掉好：原文仍能在 detail 里看到，静默丢弃就查不出来了。"""

        self.assertEqual("collector_error", reason_code_for("brand_new_stage"))
        self.assertEqual("no_source_found", reason_code_for(None))
        self.assertEqual("no_source_found", reason_code_for("  "))

    def test_internal_contract_violation_builds_a_diagnostic_event(self) -> None:
        event = internal_contract_violation_event(
            domain="map",
            field_ref="evidence.map",
            raw_reason="route_matrix_input_validation",
            data_type="route_duration",
        )
        self.assertEqual(
            "evidence.internal_contract_violation", event["event_type"]
        )
        # 排查通道保留原始 stage 名；展示通道（next_action.detail）不含它。
        self.assertEqual("route_matrix_input_validation", event["raw_reason"])


class ProjectionCase(unittest.TestCase):
    def test_sourced_within_tolerance_is_verified(self) -> None:
        verdict = project_domain({"railway": _item()}, "railway", now=NOW)
        self.assertEqual("verified", verdict.token)
        self.assertIsNone(verdict.next_action)
        self.assertTrue(is_supported(verdict))

    def test_sourced_beyond_tolerance_is_stale_and_blocking(self) -> None:
        old = (NOW - timedelta(hours=9)).isoformat()
        verdict = project_domain(
            {
                "railway": _item(
                    value={"departure_at": "x", "retrieved_at": old},
                    sources=[{"provider": "12306", "retrieved_at": old}],
                )
            },
            "railway",
            now=NOW,
        )
        self.assertEqual("sourced_stale", verdict.token)
        assert verdict.next_action is not None
        self.assertEqual("auto_refetch", verdict.next_action["kind"])
        # railway_schedule_fare 是 feasibility_critical 且 on_stale=auto_refetch
        self.assertTrue(verdict.next_action["blocking"])

    def test_missing_evidence_carries_the_translated_reason(self) -> None:
        verdict = project_domain(
            {
                "railway": _item(
                    status="missing",
                    value=None,
                    missing_reason="rail_http",
                )
            },
            "railway",
            now=NOW,
        )
        self.assertEqual("unknown", verdict.token)
        assert verdict.next_action is not None
        self.assertEqual("collector_error", verdict.next_action["reason_code"])
        self.assertFalse(is_supported(verdict))

    def test_conflicting_evidence_offers_the_disagreeing_sources(self) -> None:
        verdict = project_domain(
            {
                "railway": _item(
                    status="conflicting",
                    conflict_details=["来源A说13:00", "来源B说13:40"],
                )
            },
            "railway",
            now=NOW,
        )
        self.assertEqual("conflicting", verdict.token)
        assert verdict.next_action is not None
        self.assertEqual("user_choice", verdict.next_action["kind"])
        self.assertEqual(2, len(verdict.next_action["options"]))

    def test_absent_domain_is_unknown(self) -> None:
        verdict = project_domain({}, "web", now=NOW)
        self.assertEqual("unknown", verdict.token)
        self.assertFalse(is_supported(verdict))

    def test_map_domain_switches_data_type_on_resolved_routes(self) -> None:
        """有 local_transit 时是 route_duration（6h），否则是 poi_coordinate（30d）。"""

        stamp = (NOW - timedelta(hours=9)).isoformat()
        without_routes = project_domain(
            {
                "map": _item(
                    domain="map",
                    value={"destination": {"name": "乙地"}, "retrieved_at": stamp},
                    sources=[{"provider": "amap", "retrieved_at": stamp}],
                )
            },
            "map",
            now=NOW,
        )
        with_routes = project_domain(
            {
                "map": _item(
                    domain="map",
                    value={"local_transit": [{"route_id": "r1"}], "retrieved_at": stamp},
                    sources=[{"provider": "amap", "retrieved_at": stamp}],
                )
            },
            "map",
            now=NOW,
        )
        self.assertEqual("verified", without_routes.token)
        self.assertEqual("sourced_stale", with_routes.token)

    def test_verdict_payload_omits_next_action_when_verified(self) -> None:
        verified = verdict_payload(
            project_domain({"railway": _item()}, "railway", now=NOW)
        )
        self.assertEqual({"token"}, set(verified))
        unknown = verdict_payload(project_domain({}, "railway", now=NOW))
        self.assertEqual({"token", "next_action"}, set(unknown))


if __name__ == "__main__":
    unittest.main()
