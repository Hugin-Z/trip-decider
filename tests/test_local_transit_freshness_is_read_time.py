"""本地交通的可采集性判定：freshness 是 now 的函数（I5）。

`_needs_local_transit` / `_can_collect_local_transit` 曾读
`value["freshness"]["status"] == "STALE"`——与 `guided_discovery:357` 一字不差，
同一个 I5 违反的第二、第三次出现。批次 1 已迁前者，本文件守后两处。

断言结构复制自 `test_guided_discovery_freshness_is_read_time.py`，包括第三条
对照组：**采集时刻不随 now 变**。没有它，前两条可以靠「把两个字段都接到 now」
作弊通过。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from trip_decider import agent_actions
from trip_decider.agent_actions import _can_collect_local_transit, _read_token
from trip_decider.evidence_core import FRESHNESS_STALE, token_freshness
from trip_decider.evidence_projection import item_retrieved_at
from trip_decider.travel_agent import EvidenceItem, EvidenceStatus

COLLECTED_AT = "2026-08-02T10:00:00+00:00"
READ_FRESH = datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc)  # +1h，窗内
READ_STALE = READ_FRESH + timedelta(days=30)


def _map_evidence() -> EvidenceItem:
    """一份固定的落盘地图证据。两次读取拿到的是同一个对象。"""

    return EvidenceItem(
        evidence_id="map-live-query",
        domain="map",
        status=EvidenceStatus.SOURCED,
        value={
            "destination": {"name": "目的地", "adcode": "330100"},
            "local_transit_outcome": "AVAILABLE",
            "local_transit_input_signature": ["住宿片区", "景点甲"],
            "local_transit": [
                {"route_id": "r1", "duration_seconds": 1200},
            ],
        },
        sources=({"provider": "controlled-map", "retrieved_at": COLLECTED_AT},),
    )


class LocalTransitFreshnessIsReadTimeCase(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(agent_actions.reset_read_clock)

    def _token_at(self, now: datetime) -> str:
        agent_actions.set_read_clock(lambda: now)
        return _read_token(_map_evidence())

    def test_same_bytes_two_clocks_two_verdicts(self) -> None:
        fresh = self._token_at(READ_FRESH)
        stale = self._token_at(READ_STALE)

        self.assertEqual("verified", fresh, "采集后 1 小时读取，应为 verified")
        self.assertEqual(
            "sourced_stale",
            stale,
            "采集后 30 天读取应为 sourced_stale；仍是 verified 说明 freshness "
            "又变回了写盘时冻结的判断（I5）",
        )
        self.assertNotEqual(
            fresh,
            stale,
            "同一份落盘、两个 now 给出同一个 freshness 结论——I5 被破坏",
        )

    def test_collectability_follows_the_read_clock(self) -> None:
        """判定本身要跟着走，不只是 token 跟着走。

        签名一致且证据不陈旧时不必重采；同一份证据在 30 天后读，它陈旧了，
        重采就该重新成为选项。
        """

        state = agent_actions._LoopState(
            evidence={"map": _map_evidence(), "web": _web_evidence()}
        )

        agent_actions.set_read_clock(lambda: READ_FRESH)
        self.assertFalse(
            _can_collect_local_transit(state),
            "签名一致且证据新鲜，不该再采一次",
        )

        agent_actions.set_read_clock(lambda: READ_STALE)
        self.assertTrue(
            _can_collect_local_transit(state),
            "同一份证据 30 天后读已经陈旧，重采应重新成为选项",
        )

    def test_collected_at_does_not_move_with_the_read_clock(self) -> None:
        """对照组：采集时刻是写盘属性，不能跟着 now 走。

        没有这一条，上面两条可以靠「把两个字段都接到 now」作弊通过。
        """

        stamp = item_retrieved_at(_map_evidence().to_dict())
        agent_actions.set_read_clock(lambda: READ_STALE)
        self.assertEqual(
            stamp,
            item_retrieved_at(_map_evidence().to_dict()),
            "采集时刻随读取时刻变了——那不是采集时刻",
        )
        self.assertEqual(COLLECTED_AT, stamp)

    def test_stale_verdict_comes_from_the_kernel(self) -> None:
        """陈旧判定走内核的 token 分解，不再有第二处 STALE 字面量。"""

        self.assertEqual(
            FRESHNESS_STALE,
            token_freshness(self._token_at(READ_STALE)),
        )


def _web_evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="web-live-profile",
        domain="web",
        status=EvidenceStatus.SOURCED,
        value={
            "hotel_area": {"name": "住宿片区", "route_query_name": "住宿片区"},
            "attractions": [{"name": "景点甲", "route_query_name": "景点甲"}],
        },
        sources=({"provider": "controlled-web", "retrieved_at": COLLECTED_AT},),
    )


if __name__ == "__main__":
    unittest.main()
