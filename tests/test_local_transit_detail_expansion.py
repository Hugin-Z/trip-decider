"""当地交通展开：行程要说「乘什么、在哪换、多少钱」，不能只给一个时长。

用户实测点名（Hugin，2026-08-03）：行程只给时长估算，不给具体乘车信息。

归因**不是数据源缺口**。`simple_live._transit_route_value` 一直在解析高德公交
路线规划 2.0 的 `segments[].bus.buslines[]`，线路名、上下车站、运营时刻、
`cost.transit_fee`、`walking_distance` 全都采到了。丢失点是一处归一化：
`agent_actions._normalize_local_transit` 只把时长/距离/票价/polyline 抄进
`local_transit`，其余原地丢弃——于是后面每一层都无从显示。

`itinerary_planner.make_transit_event` 甚至早就写好了渲染 `services` /
`board_at` / `alight_at` / `operating` 的分支，但从来没有任何调用点（本轮清点：
0 处），是一段一直没接上的能力。

覆盖范围与缺口登记在 `docs/contracts/local-transit-coverage.md`。
"""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from trip_decider.agent_actions import _normalize_local_transit
from trip_decider.evidence_projection import usable_fact_values
from trip_decider.planning_input_compiler import PlanningInputCompiler
from trip_decider.travel_agent import (
    DestinationContext,
    EvidenceItem,
    EvidenceStatus,
    TravelIntent,
)

READ_AT = datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc)


def collector_segment(**overrides: object) -> dict[str, object]:
    """`estimate_live_public_transport_segments` 的真实产出形状。"""

    primary = {
        "mode": "public_transit",
        "support": "api_estimate",
        "duration_seconds": 1800,
        "distance_meters": 12000,
        "walking_distance_meters": 640,
        "fare_cny": 4.0,
        "services": [
            {
                "service": "机场巴士2号线",
                "board_at": "乙站南广场",
                "alight_at": "中心广场",
                "operating_start": "06:30",
                "operating_end": "21:00",
            },
            {
                "service": "3路",
                "board_at": "中心广场东",
                "alight_at": "住宿片区东",
                "operating_start": "05:50",
                "operating_end": "22:30",
            },
        ],
        "polyline": [[117.8, 29.2], [117.9, 29.3]],
        "source": "高德公交路线规划2.0",
    }
    primary.update(overrides)
    return {
        "status": "AVAILABLE",
        "segments": [
            {
                "from": "乙站",
                "to": "住宿片区",
                "status": "AVAILABLE",
                "primary": primary,
                "alternatives": [],
                "reason": None,
            }
        ],
    }


def _intent() -> TravelIntent:
    return TravelIntent.from_mapping(
        {
            "task_mode": "DIRECT_PLAN",
            "origin": "甲地",
            "destination_anchor": "乙地",
            "destination_expression": "确定乙地",
            "earliest_departure_at": "2026-08-04T12:00",
            "latest_return_at": "2026-08-07T22:00",
            "travelers": 2,
            "total_budget_cny": 6000,
            "pace": "relaxed",
            "transport_preferences": ["rail"],
        }
    )


class NormalizationKeepsRidingDetailCase(unittest.TestCase):
    """第一层：归一化不许再把已采到的乘车信息扔掉。"""

    def test_services_survive_normalization(self) -> None:
        route = _normalize_local_transit(collector_segment())[0]

        self.assertEqual(
            ["机场巴士2号线", "3路"],
            [service["service"] for service in route["services"]],
        )
        self.assertEqual("乙站南广场", route["services"][0]["board_at"])
        self.assertEqual("住宿片区东", route["services"][1]["alight_at"])
        self.assertEqual(640, route["walking_distance_meters"])
        self.assertEqual(4.0, route["fare"]["amount_cny"])

    def test_service_without_identity_is_dropped_not_blanked(self) -> None:
        """线路名/上车站/下车站缺一，这一段说不出话，不留空行。"""

        segment = collector_segment(
            services=[
                {"service": "3路", "board_at": "中心广场"},  # 缺 alight_at
                {
                    "service": "5路",
                    "board_at": "中心广场东",
                    "alight_at": "住宿片区东",
                },
            ]
        )
        route = _normalize_local_transit(segment)[0]

        self.assertEqual(
            ["5路"],
            [service["service"] for service in route["services"]],
        )

    def test_missing_operating_hours_do_not_drop_the_line(self) -> None:
        """运营时刻缺失是常事（高德不总返回），不能因此丢掉整条线路。"""

        segment = collector_segment(
            services=[
                {
                    "service": "3路",
                    "board_at": "甲站",
                    "alight_at": "乙站",
                    "operating_start": None,
                    "operating_end": None,
                }
            ]
        )
        route = _normalize_local_transit(segment)[0]

        self.assertEqual(1, len(route["services"]))
        self.assertIsNone(route["services"][0]["operating_start"])

    def test_no_services_when_the_collector_returned_none(self) -> None:
        """驾车兜底那一支没有 services，给空列表而不是编一个。"""

        segment = collector_segment()
        segment["segments"][0]["primary"].pop("services")
        route = _normalize_local_transit(segment)[0]

        self.assertEqual([], route["services"])


class ProjectionKeepsRidingDetailCase(unittest.TestCase):
    """第二层：字段级投影往返之后乘车信息还在。"""

    def _evidence(self) -> EvidenceItem:
        return EvidenceItem(
            evidence_id="map-live",
            domain="map",
            status=EvidenceStatus.SOURCED,
            value={
                "destination": {"name": "乙地"},
                "retrieved_at": "2026-08-02T18:00:00+08:00",
                "local_transit": _normalize_local_transit(collector_segment()),
            },
            sources=(
                {
                    "provider": "amap",
                    "retrieved_at": "2026-08-02T18:00:00+08:00",
                },
            ),
        )

    def test_services_round_trip_through_facts(self) -> None:
        rebuilt = usable_fact_values(self._evidence().facts)
        services = rebuilt["local_transit"][0]["services"]

        self.assertEqual(
            ["机场巴士2号线", "3路"],
            [service["service"] for service in services],
        )

    def test_each_service_field_becomes_its_own_fact(self) -> None:
        """字段级 support 的好处：运营时刻未知不会拖累线路名。"""

        fields = {
            str(fact.get("field"))
            for fact in self._evidence().facts
        }

        self.assertIn("local_transit[0].services[0].service", fields)
        self.assertIn("local_transit[0].services[1].board_at", fields)
        self.assertIn("local_transit[0].walking_distance_meters", fields)


class CompiledEventCarriesRidingDetailCase(unittest.TestCase):
    """第三层：事件 detail 上真的有，读取层/界面才可能显示。"""

    def _transit_event(self, segment: dict[str, object]) -> dict[str, object]:
        intent = _intent()
        context = DestinationContext(
            context_id="context-transit",
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
                    evidence_id="map-live",
                    domain="map",
                    status=EvidenceStatus.SOURCED,
                    value={
                        "destination": {"name": "乙地"},
                        "retrieved_at": "2026-08-02T18:00:00+08:00",
                        "local_transit": _normalize_local_transit(segment),
                    },
                    sources=(
                        {
                            "provider": "amap",
                            "retrieved_at": "2026-08-02T18:00:00+08:00",
                        },
                    ),
                ),
            ),
            built_at="2026-08-02T18:30:00+08:00",
        )
        compiled = PlanningInputCompiler().compile(context, now=READ_AT)
        events = compiled["local_transit_events"]
        self.assertTrue(events, "没有编译出当地交通事件")
        return events[0]

    def test_event_names_the_lines_and_stops(self) -> None:
        event = self._transit_event(collector_segment())

        self.assertEqual(
            ["机场巴士2号线", "3路"],
            [service["service"] for service in event["services"]],
        )
        self.assertEqual("乙站南广场", event["services"][0]["board_at"])
        self.assertEqual(640, event["walking_distance_meters"])
        self.assertEqual(4.0, event["fare"]["amount_cny"])

    def test_transfer_points_are_derived_from_adjacent_services(self) -> None:
        """换乘点由相邻两段推出，不另存一份（D19）。"""

        event = self._transit_event(collector_segment())
        transfers = event["transfers"]

        self.assertEqual(1, len(transfers))
        self.assertEqual("中心广场", transfers[0]["alight_at"])
        self.assertEqual("中心广场东", transfers[0]["board_at"])
        self.assertFalse(
            transfers[0]["same_stop"],
            "下车站与上车站不同名，应标为需要走出站换乘",
        )

    def test_same_stop_transfer_is_marked_as_such(self) -> None:
        segment = collector_segment(
            services=[
                {
                    "service": "3路",
                    "board_at": "甲站",
                    "alight_at": "中心广场",
                },
                {
                    "service": "5路",
                    "board_at": "中心广场",
                    "alight_at": "乙站",
                },
            ]
        )
        event = self._transit_event(segment)

        self.assertTrue(event["transfers"][0]["same_stop"])

    def test_single_line_route_has_no_transfers(self) -> None:
        segment = collector_segment(
            services=[
                {
                    "service": "3路",
                    "board_at": "甲站",
                    "alight_at": "乙站",
                }
            ]
        )
        event = self._transit_event(segment)

        self.assertEqual([], event["transfers"])


if __name__ == "__main__":
    unittest.main()
