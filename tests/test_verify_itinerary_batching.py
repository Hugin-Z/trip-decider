"""verify_itinerary 分批：收下活立刻回执，实采在后台，宿主轮询取增量。

**事故**（Claude Desktop 第四次实测，2026-08-04）：`verify_itinerary` 首次被真
宿主调用即 4 分钟无响应，宿主回退 web search。

**实测归因**（本轮，真 12306）：

* 1 条断言 8.0 秒（几乎全是 12306 会话初始化），4 条 14.3 秒——每多一条约 2 秒；
* 真正的风险不是条数而是**放大**：单次请求超时 15 秒 × 重试 1 次 = 一条最坏
  31 秒。12306 稍有不畅，几条就能堆到分钟级。

**宿主报的「进程级挂死、后续调用陪葬」没有复现。** 并发实测：verify 跑满 21.7
秒期间，`read_trip` 十二次全部 0.00–0.02 秒返回。MCP SDK 把同步 handler 丢到
工作线程，一个慢调用不阻塞别的调用。「后续全挂」更可能是**宿主侧串行等待**
——它在等这一次调用的结果，自然发不出下一个。对用户的观感一样，但病因不同，
所以修法是让这次调用**立刻返回**，而不是去解一个并不存在的锁。

夹具用宿主那份行程的真实断言（第四/五张图），核验结果留档在
`docs/field-reports/verify-2026-08-04-third-party-vs-12306.md`。
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest import mock

from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.itinerary_verification import verify_checkable_incrementally
from trip_decider.mcp_adapter import TripMCPAdapter, TripMCPError
from trip_decider.travel_agent import InMemoryAgentStore
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService
from trip_decider.verification_registry import (
    VerificationCapacityError,
    VerificationRegistry,
)

from tests.invariant_support import noop_collector

#: 宿主第四次实测那份行程的车次断言。**真实车次号与时刻，未脱敏**——它是对账
#: 素材，改了就失去意义。核验结果见 field-reports。
HOST_ITINERARY_ASSERTIONS = [
    {
        "train_code": "G1521",
        "origin_station": "武汉",
        "destination_station": "上饶",
        "departure_at": "2026-08-11T08:05",
        "arrival_at": "2026-08-11T11:46",
        "price_cny": 340.0,
    },
    {
        "train_code": "G1992",
        "origin_station": "上饶",
        "destination_station": "武汉",
        "departure_at": "2026-08-14T15:35",
        "arrival_at": "2026-08-14T19:12",
        "price_cny": 340.0,
    },
    {
        "train_code": "G4392",
        "origin_station": "上饶",
        "destination_station": "婺源",
        "departure_at": "2026-08-12T09:12",
        "arrival_at": "2026-08-12T09:36",
        "price_cny": 29.5,
    },
]

_RELEASE = threading.Event()


def _slow_collect(report: object) -> None:
    """假实采：睡到用例结束才醒。

    **必须注入**——不注入的话这些用例会起真线程去打 12306：慢、依赖网络、
    还会把线程漏进后续用例。测试自己制造不确定性，比它守的东西还坏。
    """

    _RELEASE.wait(timeout=20.0)


def _adapter() -> tuple[TripMCPAdapter, TemporaryDirectory]:
    temporary = TemporaryDirectory()
    root = Path(temporary.name) / "sessions"
    store = InMemoryAgentStore(root)
    application = TripApplicationService(
        store=store,
        evidence_broker=EvidenceBroker(root.parent / "cache"),
        railway_collector=noop_collector,
        map_collector=noop_collector,
        web_collector=noop_collector,
    )
    query = TripQueryService(store=store, application_service=application)
    return TripMCPAdapter(application, query), temporary


class ImmediateReceiptCase(unittest.TestCase):
    """第一次调用必须秒回，哪怕实采要跑很久。"""

    def setUp(self) -> None:
        _RELEASE.clear()
        self.addCleanup(_RELEASE.set)
        self.adapter, temporary = _adapter()
        self.addCleanup(temporary.cleanup)
        patch = mock.patch(
            "trip_decider.mcp_adapter.verify_checkable_incrementally",
            lambda checkable, **kwargs: _slow_collect(None),
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_call_returns_immediately_with_a_verify_id(self) -> None:
        started = time.monotonic()
        response = self.adapter.verify_itinerary(
            [dict(item) for item in HOST_ITINERARY_ASSERTIONS]
        )
        elapsed = time.monotonic() - started

        self.assertLess(
            elapsed,
            2.0,
            f"verify_itinerary 花了 {elapsed:.1f} 秒——它应当只收活不干活",
        )
        self.assertTrue(str(response["verify_id"]).startswith("verify-"))
        self.assertEqual(3, response["total"])

    def test_shape_problems_come_back_in_the_first_response(self) -> None:
        """形状问题不消耗网络，第一次就该给——这是「首批可秒回」的实质。"""

        response = self.adapter.verify_itinerary(
            [
                {"origin_station": "甲站"},  # 缺 train_code 等
                dict(HOST_ITINERARY_ASSERTIONS[0]),
            ]
        )
        findings = response["findings"]

        self.assertTrue(findings, "首批一条都没给")
        self.assertEqual(1, findings[0]["index"])
        self.assertEqual("unknown", findings[0]["verdict"])
        self.assertIn("missing_fields", str(findings[0]["reason"]))

    def test_running_response_tells_the_host_to_poll(self) -> None:
        response = self.adapter.verify_itinerary(
            [dict(item) for item in HOST_ITINERARY_ASSERTIONS]
        )

        self.assertEqual("RUNNING", response["status"])
        option = response["next_call"]["options"][0]
        self.assertEqual("read_verification", option["entrypoint"])
        self.assertEqual(
            response["verify_id"],
            option["arguments"]["verify_id"],
        )

    def test_summary_counts_only_what_was_actually_checked(self) -> None:
        """未核的不算成有据。总评要跟着进度走，不能一上来就说「3 条有据」。"""

        response = self.adapter.verify_itinerary(
            [dict(item) for item in HOST_ITINERARY_ASSERTIONS]
        )

        self.assertEqual(0, response["summary"]["sourced"])
        self.assertEqual(3, response["pending"])

    def test_identical_request_reuses_the_running_verification(self) -> None:
        first = self.adapter.verify_itinerary(
            [dict(item) for item in HOST_ITINERARY_ASSERTIONS]
        )
        second = self.adapter.verify_itinerary(
            [dict(item) for item in HOST_ITINERARY_ASSERTIONS]
        )

        self.assertEqual(first["verify_id"], second["verify_id"])


class PollingCase(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter, temporary = _adapter()
        self.addCleanup(temporary.cleanup)

    def test_unknown_verify_id_says_so_with_a_next_step(self) -> None:
        with self.assertRaises(TripMCPError) as caught:
            self.adapter.read_verification("verify-nope")

        self.assertIn("不存在", str(caught.exception))
        self.assertTrue(caught.exception.next_call)

    def test_findings_accumulate_until_complete(self) -> None:
        """用同步 spawn 把后台跑完，断言增量确实攒齐并转 COMPLETE。"""

        registry = VerificationRegistry(spawn=lambda worker, name: worker())
        self.adapter._verifications = registry

        response = self.adapter.verify_itinerary(
            [
                {"origin_station": "甲站"},
                {"origin_station": "乙站"},
            ]
        )

        # R3：对外的完成态词是 `completed`（登记处内部用 COMPLETE）。
        self.assertEqual("completed", response["status"])
        self.assertEqual(2, response["checked"])
        self.assertEqual(0, response["pending"])
        self.assertEqual([], response["next_call"]["options"])

    def test_read_returns_the_same_view_shape_as_the_first_call(self) -> None:
        registry = VerificationRegistry(spawn=lambda worker, name: worker())
        self.adapter._verifications = registry
        started = self.adapter.verify_itinerary([{"origin_station": "甲站"}])

        fetched = self.adapter.read_verification(str(started["verify_id"]))

        self.assertEqual(started["verify_id"], fetched["verify_id"])
        self.assertEqual(started["findings"], fetched["findings"])
        self.assertIn("scope_note", fetched)


class BackgroundFailureIsVisibleCase(unittest.TestCase):
    """后台炸了要能看见，不能停在「永远 RUNNING」。"""

    def test_collector_exception_surfaces_as_failed(self) -> None:
        registry = VerificationRegistry(spawn=lambda worker, name: worker())

        def explode(report: object) -> None:
            raise RuntimeError("12306 会话建不起来")

        snapshot = registry.start_background(
            total=1,
            immediate=[],
            collect=explode,
        )

        self.assertEqual("FAILED", snapshot["status"])
        self.assertIn("12306 会话建不起来", str(snapshot["error"]))


class TrulyIncrementalCollectionCase(unittest.TestCase):
    """第二条卡住时，第一条必须已经交给登记处。"""

    def test_one_finding_is_reported_before_the_next_query_finishes(self) -> None:
        second_query_started = threading.Event()
        release_second = threading.Event()
        self.addCleanup(release_second.set)

        class _GatedRail:
            def __init__(self) -> None:
                self.queries = 0

            def initialize_web_session(self) -> None:
                return None

            def station_codes(self):
                return (
                    {"甲站": "AAA", "乙站": "BBB"},
                    {"AAA": "甲站", "BBB": "乙站"},
                )

            def query_direct(self, **kwargs: object) -> list:
                self.queries += 1
                if self.queries == 2:
                    second_query_started.set()
                    release_second.wait(timeout=5.0)
                return []

            def close(self) -> None:
                return None

        checkable = [
            (
                index,
                {
                    "train_code": f"G{index}",
                    "origin_station": "甲站",
                    "destination_station": "乙站",
                    "departure_at": f"2026-08-{10 + index:02d}T08:00",
                },
            )
            for index in (1, 2)
        ]
        reports: list[dict[str, object]] = []
        thread = threading.Thread(
            target=lambda: verify_checkable_incrementally(
                checkable,
                report=lambda finding: reports.append(dict(finding)),
                client_factory=_GatedRail,
            ),
            daemon=True,
        )
        thread.start()

        self.assertTrue(second_query_started.wait(timeout=5.0))
        self.assertEqual(
            [1],
            [finding["index"] for finding in reports],
            "第二条还没查完时，第一条没有逐条上报",
        )
        release_second.set()
        thread.join(timeout=5.0)
        self.assertEqual([1, 2], [finding["index"] for finding in reports])


class VerificationRegistryBoundedCase(unittest.TestCase):
    def test_running_entries_never_exceed_the_hard_cap(self) -> None:
        registry = VerificationRegistry(spawn=lambda worker, name: None)
        for index in range(32):
            registry.start_background(
                total=1,
                immediate=[],
                collect=lambda report: None,
                dedupe_key=f"request-{index}",
            )

        with self.assertRaises(VerificationCapacityError):
            registry.start_background(
                total=1,
                immediate=[],
                collect=lambda report: None,
                dedupe_key="request-over-cap",
            )

    def test_duplicate_key_spawns_only_one_worker(self) -> None:
        spawned: list[str] = []
        registry = VerificationRegistry(
            spawn=lambda worker, name: spawned.append(name)
        )

        first = registry.start_background(
            total=1,
            immediate=[],
            collect=lambda report: None,
            dedupe_key="same",
        )
        second = registry.start_background(
            total=1,
            immediate=[],
            collect=lambda report: None,
            dedupe_key="same",
        )

        self.assertEqual(first["verify_id"], second["verify_id"])
        self.assertEqual(1, len(spawned))

    def test_read_enforces_retention_without_a_new_start(self) -> None:
        now = [10.0]
        registry = VerificationRegistry(
            spawn=lambda worker, name: None,
            clock=lambda: now[0],
        )
        started = registry.start_background(
            total=1,
            immediate=[],
            collect=lambda report: None,
        )
        now[0] += 3601.0

        self.assertIsNone(registry.read(str(started["verify_id"])))


if __name__ == "__main__":
    unittest.main()
