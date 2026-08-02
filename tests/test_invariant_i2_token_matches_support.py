"""I2: 对外返回值中展示状态不得高于其依赖证据的实际支持状态。

契约：docs/contracts/invariants.md I2
阶段：P3a 转绿（读取层范围，estimated 三格豁免至 P3b）。
内核范围见 tests/test_invariant_i2_kernel_token_matches_support.py。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from trip_decider.evidence_core import token_freshness, token_support
from trip_decider.trip_read_model import _map_payload_contract

from tests.invariant_support import TOKEN_TABLE

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
TOLERANCE = 21600  # railway_schedule_fare, freshness-policy.md §2.2
LEDGER_PATH = Path(__file__).with_name("invariant_ledger.json")


def _i2_exempt_supports() -> frozenset[str]:
    """读取 ledger 中 I2 豁免掉的 support 取值。"""

    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    values: set[str] = set()
    for entry in ledger.get("exemptions", []):
        if isinstance(entry, dict) and entry.get("invariant") == "I2":
            values.update(entry.get("supports", []))
    return frozenset(values)


def _run_with_railway_evidence(evidence: list[dict[str, object]]) -> dict[str, object]:
    """一个只有跨城铁路一段的最小计划，用于观察读取层的展示态。"""

    return {
        "status": "COMPLETED",
        "intent": {"task_mode": "DIRECT_PLAN"},
        "result": {
            "plan": {
                "days": [
                    {
                        "day": 1,
                        "date": "2026-08-04",
                        "events": [
                            {
                                "event_id": "rail-outbound",
                                "type": "transit",
                                "from": "甲站",
                                "to": "乙站",
                                "from_location": {
                                    "longitude": 114.3,
                                    "latitude": 30.6,
                                },
                                "to_location": {
                                    "longitude": 117.9,
                                    "latitude": 28.4,
                                },
                            }
                        ],
                    }
                ],
                "display_requirements": {},
            },
            "context": {"evidence": evidence},
        },
    }


def _railway_evidence(
    *,
    support: str,
    retrieved_at: str | None,
) -> list[dict[str, object]]:
    """按持久化形状构造一条铁路证据。

    形状必须是 ``EvidenceItem.to_dict()`` 的形状（travel_agent.py:513-522），
    因为读取层看到的就是这个——P3a 不碰持久化，因此测试也不能用一个想象中的
    形状去喂读取层。

    展示 token 不出现在本函数里：它必须由读取层从两轴算出。
    """

    item: dict[str, object] = {
        "evidence_id": "fact-railway",
        "domain": "railway",
        "value": {"departure_at": "2026-08-04T13:00", "retrieved_at": retrieved_at},
        "sources": [
            {"provider": "controlled-rail", "retrieved_at": retrieved_at}
        ],
        "missing_reason": None,
        "conflict_details": [],
    }
    if support == "unknown":
        item["status"] = "missing"
        item["value"] = None
        item["missing_reason"] = "collector_error"
    elif support == "conflicting":
        item["status"] = "conflicting"
        item["conflict_details"] = ["来源A说13:00", "来源B说13:40"]
    elif support == "estimated":
        # P3b 起持久化枚举有了 estimated，这三格不再需要豁免。
        item["status"] = "estimated"
    else:
        item["status"] = "sourced"
    return [item]


# undated 用「有值但不可用」的时间戳构造，不能用缺失的时间戳——缺失会让
# §2.2 序 4 不成立而落到序 5 兜底，产出 unknown 而非 sourced_undated。
_RETRIEVED_AT = {
    "fresh": (NOW - timedelta(seconds=TOLERANCE - 60)).isoformat(),
    "stale": (NOW - timedelta(seconds=TOLERANCE + 60)).isoformat(),
    "undated": "2026-08-02T12:00:00",
}


class TokenMatchesSupportCase(unittest.TestCase):
    def test_i2_read_model_token_matches_both_axes(self) -> None:
        """读取层的 token 必须精确等于两轴合取的结果。

        P3b 起 12 格全部可达——持久化枚举加入 estimated 后，读取层拿得到
        这种输入，P3a 登记的 I2 豁免随之清零。
        """

        exempt = _i2_exempt_supports()
        self.assertEqual(
            frozenset(),
            exempt,
            "I2 不应再有豁免：estimated 已随枚举扩展进入读取层可达范围",
        )
        checked = 0
        for (support, freshness), expected in sorted(TOKEN_TABLE.items()):
            if support in exempt:
                continue
            with self.subTest(support=support, freshness=freshness):
                payload = _map_payload_contract(
                    _run_with_railway_evidence(
                        _railway_evidence(
                            support=support,
                            retrieved_at=_RETRIEVED_AT[freshness],
                        )
                    ),
                    plan_version=None,
                    now=NOW,
                )
                markers = payload["markers"]
                self.assertTrue(markers, "读取层没有产出任何 marker")
                token = markers[0].get("token")
                self.assertEqual(expected, token)
                self.assertEqual(support, token_support(str(token)))
                decomposed = token_freshness(str(token))
                if decomposed is not None:
                    self.assertEqual(freshness, decomposed)
                checked += 1
        self.assertEqual(
            12,
            checked,
            "12 格全部可达，应当逐格核对",
        )

    def test_i2_unusable_evidence_is_never_displayed_as_available(self) -> None:
        """基线报告 §3.4 的具体缺陷：采集失败曾被展示为可用。"""

        payload = _map_payload_contract(
            _run_with_railway_evidence(
                _railway_evidence(support="unknown", retrieved_at=None)
            ),
            plan_version=None,
            now=NOW,
        )
        tokens = sorted(
            {str(marker.get("token")) for marker in payload["markers"]}
        )
        self.assertEqual(
            ["unknown"],
            tokens,
            "采集失败的证据没有被判为 unknown",
        )

    def test_i2_absent_evidence_and_failed_evidence_are_distinguishable(
        self,
    ) -> None:
        """证据缺席与采集失败必须可区分，且失败不得比缺席显得更可用。"""

        failed = _map_payload_contract(
            _run_with_railway_evidence(
                _railway_evidence(support="unknown", retrieved_at=None)
            ),
            plan_version=None,
            now=NOW,
        )
        absent = _map_payload_contract(
            _run_with_railway_evidence([]),
            plan_version=None,
            now=NOW,
        )
        failed_status = str(failed["markers"][0].get("token"))
        absent_status = str(absent["markers"][0].get("token"))
        self.assertEqual(
            failed_status,
            absent_status,
            "采集失败与证据缺席产出了不同的展示态，且失败的一侧更乐观："
            f"失败={failed_status!r} / 缺席={absent_status!r}",
        )


if __name__ == "__main__":
    unittest.main()
