"""R2 核验不得抬升新鲜度；R3 轮询协议收口。

**R2**（外部审计 MEDIUM）：核验路径此前在**每条断言开始处理时**盖一个
`retrieved_at = now()`，然后不管这条是真去查了、还是复用了同一次查询的结果、
甚至根本没发出请求（站名不认识），都盖这个时刻。于是：

* 复用被说成重查——第 2 条断言复用第 1 条的时刻表，却报了一个更新的采集时刻；
* 没采到也盖时刻——「站名不认识」这一条一个字节都没取到，却看起来刚查过。

后果不是差几秒，而是**核验成了一个洗新鲜度的通道**：任何数据只要过一遍核验，
读出来都像是刚采的。I2 说「展示状态不得高于依赖证据的实际支持状态」，这是它在
verify 域的落法。

**R3**（外部审计 MEDIUM）：完成态的返回体要一眼可判——状态词固定、计数总评
完整、建议动作具体。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider.evidence_broker import FRESHNESS_POLICIES
from trip_decider.evidence_core import (
    SUPPORT_SOURCED,
    combine_token,
    resolve_freshness,
    token_support,
)
from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.itinerary_verification import (
    RAILWAY_DATA_TYPE,
    VerifiedFinding,
)
from trip_decider.mcp_adapter import TripMCPAdapter
from trip_decider.travel_agent import InMemoryAgentStore
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService
from trip_decider.verification_registry import VerificationRegistry

from tests.invariant_support import noop_collector

NOW = datetime(2026, 8, 4, 20, 0).astimezone()


def _finding(*, verdict: str, age_hours: float | None) -> VerifiedFinding:
    retrieved_at = (
        None
        if age_hours is None
        else (NOW - timedelta(hours=age_hours)).isoformat(timespec="seconds")
    )
    return VerifiedFinding(
        index=1,
        verdict=verdict,
        claim={"train_code": "G1"},
        observed=None,
        mismatches=(),
        reason=None,
        retrieved_at=retrieved_at,
        suggested_action=None,
    )


class VerificationDoesNotInflateFreshnessCase(unittest.TestCase):
    def test_seven_hour_old_data_reads_stale_not_verified(self) -> None:
        """R2 的 D6 判据：7 小时前的数据必须是 sourced_stale。"""

        token = _finding(verdict="sourced", age_hours=7).token(now=NOW)

        self.assertEqual("sourced_stale", token)
        self.assertNotEqual("verified", token)

    def test_fresh_data_still_reads_verified(self) -> None:
        """收紧不能收成一律 stale——那是另一个方向的谎。"""

        self.assertEqual(
            "verified",
            _finding(verdict="sourced", age_hours=0.5).token(now=NOW),
        )

    def test_the_token_matches_reading_the_same_timestamp_directly(
        self,
    ) -> None:
        """核验产出的 token 必须等于直读同一采集时刻算出的 token。

        这是 R2 的核心断言：核验不是一条能改变证据状态的捷径。
        """

        for age in (0.1, 3.0, 5.9, 6.1, 12.0, 48.0):
            with self.subTest(age_hours=age):
                finding = _finding(verdict="sourced", age_hours=age)
                expected = combine_token(
                    SUPPORT_SOURCED,
                    resolve_freshness(
                        finding.retrieved_at,
                        now=NOW,
                        tolerance_seconds=FRESHNESS_POLICIES[
                            RAILWAY_DATA_TYPE
                        ].stale_ttl_seconds,
                    ).value,
                )
                self.assertEqual(expected, finding.token(now=NOW))

    def test_nothing_fetched_means_no_retrieved_at(self) -> None:
        """一个字节都没取到就不能盖采集时刻。"""

        finding = _finding(verdict="unknown", age_hours=None)

        self.assertIsNone(finding.retrieved_at)
        self.assertEqual("unknown", finding.token(now=NOW))

    def test_token_support_agrees_with_the_verdict(self) -> None:
        for verdict in ("sourced", "conflicting", "unknown"):
            with self.subTest(verdict=verdict):
                token = _finding(verdict=verdict, age_hours=0.1).token(now=NOW)
                self.assertEqual(verdict, token_support(token))

    def test_the_token_is_in_the_serialised_finding(self) -> None:
        """算得对还不够，得真的出现在给宿主的结论里。"""

        payload = _finding(verdict="sourced", age_hours=7).to_dict(now=NOW)

        self.assertEqual("sourced_stale", payload["token"])

    def test_a_reused_schedule_reports_the_original_fetch_time(self) -> None:
        """同一次查询服务多条断言时，后来的不得盖一个更新的时刻。

        用双桩客户端：只允许查一次，两条断言共用。
        """

        from trip_decider.itinerary_verification import (
            verify_railway_assertions,
        )

        queries: list[object] = []

        class _OneShotRail:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.network_attempts = 0

            def initialize_web_session(self) -> None:
                return None

            def station_codes(self):
                return ({"甲站": "AAA", "乙站": "BBB"},
                        {"AAA": "甲站", "BBB": "乙站"})

            def query_direct(self, **kwargs: object) -> list:
                queries.append(kwargs)
                return []

            def close(self) -> None:
                return None

        claims = [
            {
                "train_code": f"G{index}",
                "origin_station": "甲站",
                "destination_station": "乙站",
                "departure_at": "2026-08-11T08:00",
            }
            for index in (1, 2)
        ]
        result = verify_railway_assertions(
            claims, client_factory=_OneShotRail
        )
        stamps = {
            finding["retrieved_at"] for finding in result["findings"]
        }

        self.assertEqual(1, len(queries), "同一线路同一天应当只查一次")
        self.assertEqual(
            1,
            len(stamps),
            f"复用同一次查询的断言报了不同的采集时刻：{stamps}",
        )


class CompletedPollingProtocolCase(unittest.TestCase):
    """R3：完成态一眼可判。"""

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        root = Path(self._temporary.name) / "sessions"
        store = InMemoryAgentStore(root)
        application = TripApplicationService(
            store=store,
            evidence_broker=EvidenceBroker(root.parent / "cache"),
            railway_collector=noop_collector,
            map_collector=noop_collector,
            web_collector=noop_collector,
        )
        query = TripQueryService(store=store, application_service=application)
        self.adapter = TripMCPAdapter(application, query)
        self.adapter._verifications = VerificationRegistry(
            spawn=lambda worker, name: worker()
        )

    def _completed(self) -> dict[str, object]:
        started = self.adapter.verify_itinerary(
            [{"origin_station": "甲站"}, {"origin_station": "乙站"}]
        )
        return self.adapter.read_verification(str(started["verify_id"]))

    def test_status_is_the_unambiguous_word_completed(self) -> None:
        view = self._completed()

        self.assertEqual("completed", view["status"])
        self.assertIs(True, view["complete"])

    def test_the_summary_is_present_and_complete(self) -> None:
        summary = self._completed()["summary"]

        for key in (
            "total",
            "sourced",
            "conflicting",
            "unknown",
            "needs_confirmation",
            "sentence",
        ):
            self.assertIn(key, summary)
        self.assertEqual(2, summary["total"])

    def test_nothing_is_left_pending(self) -> None:
        view = self._completed()

        self.assertEqual(0, view["pending"])
        self.assertEqual(view["total"], view["checked"])

    def test_the_next_step_names_what_to_do_about_the_findings(self) -> None:
        option = self._completed()["next_call"]["options"][0]

        self.assertEqual("done", option["kind"])
        self.assertIn("核验完成", option["detail"])
        # 两条都是形状问题 → unknown → 应当点名要确认
        self.assertIn("查无实据", option["detail"])

    def test_polling_again_after_completion_is_stable(self) -> None:
        """完成之后再取一次，增量为空、结论不变。"""

        started = self.adapter.verify_itinerary([{"origin_station": "甲站"}])
        verify_id = str(started["verify_id"])
        first = self.adapter.read_verification(verify_id)
        second = self.adapter.read_verification(verify_id)

        self.assertEqual(first["findings"], second["findings"])
        self.assertEqual(first["summary"], second["summary"])
        self.assertEqual("completed", second["status"])

    def test_failure_is_also_terminal_and_explains_itself(self) -> None:
        registry = VerificationRegistry(spawn=lambda worker, name: worker())
        self.adapter._verifications = registry

        def explode(report: object) -> None:
            raise RuntimeError("12306 会话建不起来")

        snapshot = registry.start_background(
            total=1, immediate=[], collect=explode
        )
        view = self.adapter.read_verification(str(snapshot["verify_id"]))

        self.assertEqual("failed", view["status"])
        self.assertIs(True, view["complete"])
        self.assertIn("12306 会话建不起来", view["next_call"]["options"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
