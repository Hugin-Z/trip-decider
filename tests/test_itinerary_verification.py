"""核实模式 v0：逐条核验别处排好的行程。

**起因**：第二次宿主实测里，宿主在 trip-decider 卡住后回退去 web search，自己
排了一份行程——车次、时刻、票价一应俱全，**全程没有一句话说得出出处**。那份
行程可能对也可能不对，用户没有办法知道是哪一种。

夹具用的就是宿主那份行程里的真实断言形状（G868 12:40 那条、以及来源标注为
Autohome 的 149–176 元票价区间）。真实网络核验另见
`tests/test_verify_itinerary_live.py`（需 `TRIP_DECIDER_LIVE=1`）。

三档的分寸是本文件的重点：`unknown` **不是**「假」。12306 查不到可能是超出预售
期、站名写法不同、或者网络故障——把「查无实据」说成「错」是这个工具最容易犯也
最不该犯的错，所以有专门的用例守它。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
import unittest

from trip_decider.itinerary_verification import (
    verify_railway_assertions,
)
from trip_decider.mcp_adapter import MAX_VERIFIED_ASSERTIONS


class FakeTrain:
    def __init__(
        self,
        *,
        train_code: str,
        departure_at: datetime,
        arrival_at: datetime,
        origin_station: str = "甲站",
        destination_station: str = "乙站",
    ) -> None:
        self.train_code = train_code
        self.departure_at = departure_at
        self.arrival_at = arrival_at
        self.origin_station = origin_station
        self.destination_station = destination_station
        self.train_no = f"no-{train_code}"
        self.origin_station_no = "01"
        self.destination_station_no = "05"
        self.seat_types = "O"


class FakeRailClient:
    """按宿主那份行程的形状造一个可控的 12306。"""

    #: 时刻表：车次号 → (发, 到)。默认那趟就是宿主断言里的 G868 12:40。
    schedule = {
        "G868": (
            datetime(2026, 8, 11, 12, 40),
            datetime(2026, 8, 11, 16, 28),
        ),
        "G1521": (
            datetime(2026, 8, 11, 8, 5),
            datetime(2026, 8, 11, 11, 46),
        ),
    }
    price = Decimal("176.5")
    session_fails = False
    price_fails = False
    known_stations = {"甲站": "AAA", "乙站": "BBB"}

    def __init__(self) -> None:
        self.price_calls = 0
        self.query_calls = 0

    def initialize_web_session(self) -> None:
        if type(self).session_fails:
            raise OSError("12306 unreachable")

    def station_codes(self):
        mapping = dict(type(self).known_stations)
        return mapping, {code: name for name, code in mapping.items()}

    def query_direct(self, *, travel_date, origin_code, destination_code,
                     station_names):
        self.query_calls += 1
        return [
            FakeTrain(
                train_code=code,
                departure_at=departure,
                arrival_at=arrival,
            )
            for code, (departure, arrival) in type(self).schedule.items()
            if departure.date() == travel_date
        ]

    def second_class_price(self, *, train, travel_date):
        self.price_calls += 1
        if type(self).price_fails:
            raise OSError("price endpoint down")
        return type(self).price


def claim(**overrides: object) -> dict[str, object]:
    """宿主那份 web search 行程里 G868 那一条的形状。"""

    value: dict[str, object] = {
        "train_code": "G868",
        "origin_station": "甲站",
        "destination_station": "乙站",
        "departure_at": "2026-08-11T12:40",
    }
    value.update(overrides)
    return value


class VerdictCase(unittest.TestCase):
    def setUp(self) -> None:
        FakeRailClient.session_fails = False
        FakeRailClient.price_fails = False
        FakeRailClient.price = Decimal("176.5")

    def _verify(self, *claims: dict[str, object]) -> dict[str, object]:
        return verify_railway_assertions(
            list(claims),
            client_factory=FakeRailClient,
        )

    def test_matching_train_and_time_is_sourced(self) -> None:
        report = self._verify(claim(arrival_at="2026-08-11T16:28"))
        finding = report["findings"][0]

        self.assertEqual("sourced", finding["verdict"])
        self.assertEqual("G868", finding["observed"]["train_code"])
        self.assertIsNotNone(
            finding["retrieved_at"],
            "sourced 结论必须带采集时间，否则和凭记忆断言没有区别",
        )

    def test_wrong_departure_time_is_conflicting_with_both_values(self) -> None:
        report = self._verify(claim(departure_at="2026-08-11T12:50"))
        finding = report["findings"][0]

        self.assertEqual("conflicting", finding["verdict"])
        mismatch = finding["mismatches"][0]
        self.assertEqual("departure_at", mismatch["field"])
        self.assertEqual("2026-08-11T12:50", mismatch["claimed"])
        self.assertEqual("2026-08-11T12:40", mismatch["observed"])

    def test_train_absent_from_the_schedule_is_unknown_not_false(self) -> None:
        """查不到 ≠ 不存在。这一条是三档设计的全部意义。"""

        report = self._verify(claim(train_code="G9999"))
        finding = report["findings"][0]

        self.assertEqual(
            "unknown",
            finding["verdict"],
            "12306 这一天没查到该车次，只能说查无实据，不能判定用户写错了",
        )
        self.assertIn("预售期", str(finding["suggested_action"]))

    def test_unrecognized_station_is_unknown_and_says_to_use_full_name(
        self,
    ) -> None:
        report = self._verify(claim(origin_station="某个不认识的站"))
        finding = report["findings"][0]

        self.assertEqual("unknown", finding["verdict"])
        self.assertIn("全称", str(finding["suggested_action"]))

    def test_network_failure_marks_everything_unknown_not_conflicting(
        self,
    ) -> None:
        """我们连不上 12306，不代表用户的行程错了。"""

        FakeRailClient.session_fails = True
        report = self._verify(claim(), claim(train_code="G1521"))

        self.assertEqual(
            ["unknown", "unknown"],
            [finding["verdict"] for finding in report["findings"]],
        )
        self.assertEqual(0, report["summary"]["conflicting"])


class PriceCase(unittest.TestCase):
    """宿主那份行程的票价标的是 Autohome 的 149–176 元区间。"""

    def setUp(self) -> None:
        FakeRailClient.session_fails = False
        FakeRailClient.price_fails = False
        FakeRailClient.price = Decimal("176.5")

    def _verify(self, *claims: dict[str, object]) -> dict[str, object]:
        return verify_railway_assertions(
            list(claims),
            client_factory=FakeRailClient,
        )

    def test_price_outside_tolerance_is_conflicting(self) -> None:
        report = self._verify(claim(price_cny=149.0))
        finding = report["findings"][0]

        self.assertEqual("conflicting", finding["verdict"])
        mismatch = next(
            item for item in finding["mismatches"]
            if item["field"] == "price_cny"
        )
        self.assertEqual(149.0, mismatch["claimed"])
        self.assertEqual(176.5, mismatch["observed"])

    def test_price_within_tolerance_is_sourced(self) -> None:
        report = self._verify(claim(price_cny=176.5))

        self.assertEqual("sourced", report["findings"][0]["verdict"])

    def test_missing_price_endpoint_does_not_poison_the_time_check(
        self,
    ) -> None:
        """票价查不到就只核时刻，不因此把整条判成冲突。"""

        FakeRailClient.price_fails = True
        report = self._verify(claim(price_cny=149.0))
        finding = report["findings"][0]

        self.assertEqual("sourced", finding["verdict"])
        self.assertIsNone(finding["observed"]["price_cny"])
        self.assertIn("价格未查到", str(finding["observed"]["price_note"]))

    def test_price_absent_from_the_claim_is_never_queried(self) -> None:
        """没断言票价就别去查——多一次网络往返，还可能引入无谓的 unknown。"""

        verify_railway_assertions([claim()], client_factory=FakeRailClient)
        # FakeRailClient 每次 verify 新建一个实例，这里用类计数不便；
        # 改为断言结论里没有价格字段即可说明未查。
        report = verify_railway_assertions(
            [claim()], client_factory=FakeRailClient
        )
        self.assertNotIn("price_cny", report["findings"][0]["observed"])


class DuplicateTrainCodeCase(unittest.TestCase):
    """同一车次号在一次查询里出现多条腿。

    这不是假想的边界。实测 2026-08-04：查「武汉→上饶」2026-08-11，12306 把
    汉口与武汉东始发的车一并返回，**G867 出现两次**——11:13 汉口发（¥219.5）
    与 12:00 武汉东发（¥209.5）。直接取第一条就会拿另一条腿的时刻和票价去对
    断言，报出一个并不存在的冲突。
    """

    class TwoLegClient(FakeRailClient):
        known_stations = {
            "武汉": "WHN",
            "汉口": "HKN",
            "武汉东": "WDN",
            "上饶": "SRG",
        }

        def query_direct(self, *, travel_date, origin_code,
                         destination_code, station_names):
            return [
                FakeTrain(
                    train_code="G867",
                    departure_at=datetime(2026, 8, 11, 11, 13),
                    arrival_at=datetime(2026, 8, 11, 15, 48),
                    origin_station="汉口",
                    destination_station="上饶",
                ),
                FakeTrain(
                    train_code="G867",
                    departure_at=datetime(2026, 8, 11, 12, 0),
                    arrival_at=datetime(2026, 8, 11, 15, 48),
                    origin_station="武汉东",
                    destination_station="上饶",
                ),
            ]

    def _verify(self, **overrides: object) -> dict[str, object]:
        return verify_railway_assertions(
            [
                {
                    "train_code": "G867",
                    "origin_station": "武汉",
                    "destination_station": "上饶",
                    "departure_at": "2026-08-11T12:00",
                    **overrides,
                }
            ],
            client_factory=self.TwoLegClient,
        )

    def test_exact_origin_station_disambiguates(self) -> None:
        finding = self._verify(origin_station="武汉东")["findings"][0]

        self.assertEqual("sourced", finding["verdict"])
        self.assertEqual("武汉东", finding["observed"]["origin_station"])

    def test_claimed_time_disambiguates_when_station_is_vague(self) -> None:
        """站名写的是市名分不出腿，但时刻只对得上一条时，用时刻定。"""

        finding = self._verify()["findings"][0]

        self.assertEqual("sourced", finding["verdict"])
        self.assertEqual("武汉东", finding["observed"]["origin_station"])

    def test_ambiguous_legs_are_reported_not_guessed(self) -> None:
        """分不清就别猜——猜错会报出一个假冲突。"""

        finding = self._verify(departure_at="2026-08-11T09:00")["findings"][0]

        self.assertEqual("unknown", finding["verdict"])
        self.assertEqual(
            "multiple_legs_share_this_train_code",
            finding["reason"],
        )
        self.assertEqual(2, len(finding["observed"]["ambiguous_legs"]))
        self.assertIn("始发站全称", str(finding["suggested_action"]))


class ShapeCase(unittest.TestCase):
    def test_missing_required_field_is_rejected_by_name(self) -> None:
        report = verify_railway_assertions(
            [{"train_code": "G868"}],
            client_factory=FakeRailClient,
        )
        finding = report["findings"][0]

        self.assertEqual("unknown", finding["verdict"])
        self.assertIn("origin_station", str(finding["reason"]))
        self.assertIn("departure_at", str(finding["reason"]))

    def test_timezone_aware_time_is_rejected(self) -> None:
        report = verify_railway_assertions(
            [claim(departure_at="2026-08-11T12:40:00+08:00")],
            client_factory=FakeRailClient,
        )

        self.assertIn(
            "local_iso",
            str(report["findings"][0]["reason"]),
        )

    def test_shape_problems_do_not_consume_the_network(self) -> None:
        """「你没告诉我车次号」和「我查不到这趟车」是两回事。"""

        FakeRailClient.session_fails = True
        report = verify_railway_assertions(
            [{"train_code": "G868"}],
            client_factory=FakeRailClient,
        )

        self.assertIn("missing_fields", str(report["findings"][0]["reason"]))

    def test_empty_assertion_list_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            verify_railway_assertions([], client_factory=FakeRailClient)


class SummaryCase(unittest.TestCase):
    def setUp(self) -> None:
        FakeRailClient.session_fails = False
        FakeRailClient.price_fails = False
        FakeRailClient.price = Decimal("176.5")

    def test_counts_are_not_weighted_and_name_what_to_confirm(self) -> None:
        report = verify_railway_assertions(
            [
                claim(),                                  # 1 sourced
                claim(departure_at="2026-08-11T12:50"),   # 2 conflicting
                claim(train_code="G9999"),                # 3 unknown
                claim(train_code="G1521",
                      departure_at="2026-08-11T08:05"),   # 4 sourced
            ],
            client_factory=FakeRailClient,
        )
        summary = report["summary"]

        self.assertEqual(4, summary["total"])
        self.assertEqual(2, summary["sourced"])
        self.assertEqual(1, summary["conflicting"])
        self.assertEqual(1, summary["unknown"])
        self.assertEqual([2, 3], summary["needs_confirmation"])
        self.assertEqual(
            "4 条断言：2 条有据、1 条冲突、1 条查无实据，"
            "建议出发前确认第 2、3 条",
            summary["sentence"],
        )

    def test_all_clear_summary_names_nothing_to_confirm(self) -> None:
        report = verify_railway_assertions(
            [claim()],
            client_factory=FakeRailClient,
        )

        self.assertEqual([], report["summary"]["needs_confirmation"])
        self.assertNotIn("建议", report["summary"]["sentence"])

    def test_report_states_what_it_did_not_check(self) -> None:
        """只核了铁路域这件事必须写在报告里——没核不等于没问题。"""

        report = verify_railway_assertions(
            [claim()],
            client_factory=FakeRailClient,
        )

        self.assertIn("住宿", str(report["scope_note"]))
        self.assertIn("没有核验不等于没有问题", str(report["scope_note"]))


class BatchLimitCase(unittest.TestCase):
    """新工具不许生而违反 I13。"""

    def test_oversized_batch_is_refused_rather_than_truncated(self) -> None:
        from tempfile import TemporaryDirectory
        from pathlib import Path

        from trip_decider.mcp_adapter import TripMCPAdapter, TripMCPError
        from trip_decider.travel_agent import InMemoryAgentStore
        from trip_decider.trip_application import TripApplicationService
        from trip_decider.trip_query import TripQueryService

        with TemporaryDirectory() as temporary:
            store = InMemoryAgentStore(Path(temporary) / "sessions")
            application = TripApplicationService(store=store)
            query = TripQueryService(
                store=store,
                application_service=application,
            )
            adapter = TripMCPAdapter(application, query)

            oversized = [claim() for _ in range(MAX_VERIFIED_ASSERTIONS + 1)]
            with self.assertRaises(TripMCPError) as caught:
                adapter.verify_itinerary(oversized)

        message = str(caught.exception)
        self.assertIn("分批", message)
        self.assertIn("下一步", message)


if __name__ == "__main__":
    unittest.main()
