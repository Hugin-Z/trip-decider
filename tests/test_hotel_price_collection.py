"""AMap hotel POI reference prices become field-level estimated facts."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from trip_decider import dynamic_discovery, simple_live
from trip_decider.evidence_projection import usable_fact_values
from trip_decider.travel_agent import TravelIntent


STAMP = "2026-08-05T09:30:00+08:00"


def _poi(record_id: str, name: str, *, cost: object = None) -> dict[str, object]:
    value: dict[str, object] = {
        "id": record_id,
        "name": name,
        "location": "117.8000,29.2500",
        "type": "住宿服务;宾馆酒店",
        "typecode": "100100",
        "adname": "乙区",
    }
    if cost is not None:
        value["business"] = {"cost": cost, "rating": "4.8"}
    else:
        # rating is deliberately present: it must never be converted to price.
        value["business"] = {"rating": "4.8"}
    return value


def _intent() -> TravelIntent:
    return TravelIntent.from_mapping(
        {
            "task_mode": "DIRECT_PLAN",
            "origin": "甲地",
            "destination_anchor": "乙地",
            "destination_expression": "确定乙地",
            "earliest_departure_at": "2026-08-10T08:00",
            "latest_return_at": "2026-08-12T20:00",
            "travelers": 2,
            "total_budget_cny": 5000,
            "pace": "relaxed",
            "transport_preferences": ["rail"],
            "themes": ["自然"],
        }
    )


def _live_response(keyword: str, *_args: object, **_kwargs: object) -> dict[str, object]:
    if keyword == "酒店":
        places = [
            {
                "provider_record_id": "hotel-priced",
                "name": "参考价酒店",
                "category": "宾馆酒店",
                "district": "乙区",
                "address": "测试路1号",
                "location": {
                    "longitude": 117.8,
                    "latitude": 29.25,
                    "coordinate_system": "GCJ-02",
                },
                "reference_price_cny": 388.0,
            },
            {
                "provider_record_id": "hotel-undated",
                "name": "无价酒店",
                "category": "宾馆酒店",
                "district": "乙区",
                "address": "测试路2号",
                "location": {
                    "longitude": 117.81,
                    "latitude": 29.26,
                    "coordinate_system": "GCJ-02",
                },
                "reference_price_cny": None,
            },
        ]
    elif keyword.endswith("站") or keyword == "火车站":
        places = [
            {
                "provider_record_id": f"station-{keyword}",
                "name": f"{keyword.removesuffix('站')}站",
                "category": "火车站",
                "district": "乙区",
                "location": {
                    "longitude": 117.79,
                    "latitude": 29.24,
                    "coordinate_system": "GCJ-02",
                },
            }
        ]
    else:
        places = [
            {
                "provider_record_id": f"spot-{keyword}",
                "name": f"{keyword}甲",
                "category": "风景名胜",
                "district": "乙区",
                "location": {
                    "longitude": 117.82,
                    "latitude": 29.27,
                    "coordinate_system": "GCJ-02",
                },
            }
        ]
    return {
        "support": "sourced",
        "places": places,
        "retrieved_at": STAMP,
        "source": {
            "provider": "高德地图 Web 服务",
            "scope": "POI Search 2.0",
            "retrieved_at": STAMP,
        },
    }


class AmapReferencePriceParsingCase(unittest.TestCase):
    def test_search_projects_explicit_business_cost_only(self) -> None:
        body = json.dumps(
            {
                "status": "1",
                "infocode": "10000",
                "count": "2",
                "pois": [
                    _poi("priced", "有价酒店", cost="388"),
                    _poi("unpriced", "无价酒店"),
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        response = simple_live._Response(
            body=body,
            http_status=200,
            attempts=1,
            amap_status="1",
            amap_infocode="10000",
        )
        with patch.dict(os.environ, {"AMAP_WEB_SERVICE_KEY": "test-key"}), patch(
            "trip_decider.simple_live._http_get",
            return_value=response,
        ):
            result = simple_live.search_live_places(keyword="酒店")

        self.assertEqual(388.0, result["places"][0]["reference_price_cny"])
        self.assertIsNone(result["places"][1]["reference_price_cny"])

    def test_legacy_biz_ext_cost_is_supported_but_rating_is_not_a_price(self) -> None:
        parsed = simple_live.parse_amap_poi_response(
            {
                "status": "1",
                "infocode": "10000",
                "count": "2",
                "pois": [
                    {
                        **_poi("legacy", "旧响应酒店"),
                        "biz_ext": {"cost": 299},
                    },
                    _poi("rating-only", "只有评分"),
                ],
            }
        )

        self.assertFalse(parsed.problems)
        self.assertEqual(299.0, parsed.value.pois[0].reference_price_cny)
        self.assertIsNone(parsed.value.pois[1].reference_price_cny)

    def test_zero_cost_is_missing_not_a_free_hotel_claim(self) -> None:
        parsed = simple_live.parse_amap_poi_response(
            {
                "status": "1",
                "infocode": "10000",
                "count": "1",
                "pois": [_poi("zero", "零值酒店", cost="0.00")],
            }
        )

        self.assertFalse(parsed.problems)
        self.assertIsNone(parsed.value.pois[0].reference_price_cny)


class HotelPriceFactCase(unittest.TestCase):
    def test_profile_has_estimated_and_unknown_price_facts_side_by_side(self) -> None:
        with patch(
            "trip_decider.dynamic_discovery.search_live_places",
            side_effect=_live_response,
        ):
            evidence = dynamic_discovery.collect_live_destination_profile(_intent())

        price_facts = [
            fact
            for fact in evidence.facts
            if str(fact.get("field", "")).startswith("hotel_candidates[")
            and str(fact.get("field", "")).endswith("price.amount_cny")
        ]
        self.assertEqual(2, len(price_facts))
        self.assertEqual(
            ["estimated", "unknown"],
            [fact["support"] for fact in price_facts],
        )
        self.assertEqual(
            {"hotel_price"},
            {fact["data_type"] for fact in price_facts},
        )
        self.assertEqual(388.0, price_facts[0]["value"])
        self.assertIsNone(price_facts[1]["value"])
        rebuilt = usable_fact_values(evidence.facts)
        self.assertEqual(
            388.0,
            rebuilt["hotel_candidates"][0]["price"]["amount_cny"],
        )
        self.assertNotIn("price", rebuilt["hotel_candidates"][1])


if __name__ == "__main__":
    unittest.main()
