"""I5: freshness 必须由读取时刻决定。

契约：docs/contracts/invariants.md I5
预期转绿：P3

采集器一律注入 no-op：P5 落地 auto_refetch 后，第二次读取会触发重采并
替换证据，两次读取观察的就不是同一份数据了。no-op 采集器让两次读取观察
同一份证据，这样「结构稳定 / freshness 变化」才是被测的性质本身。
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider import trip_query as trip_query_module
from trip_decider import trip_read_model

from tests.invariant_support import drive_offline_run


def _structural_part(payload: object) -> object:
    """剔除展示态与 next_action 后的结构部分。"""

    if isinstance(payload, dict):
        return {
            key: _structural_part(value)
            for key, value in sorted(payload.items())
            if key not in {"token", "next_action", "freshness"}
        }
    if isinstance(payload, list):
        return [_structural_part(item) for item in payload]
    return payload


def _accepts_now(function: object) -> bool:
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False
    return any(name in parameters for name in ("now", "clock", "read_at"))


class FreshnessIsReadTimeCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        _application, self.query, self.run_id = drive_offline_run(
            Path(self._temporary.name) / "sessions"
        )

    def test_i5_structural_part_is_byte_stable_across_reads(self) -> None:
        """结构部分必须逐字节稳定。这一半现在就应当成立。"""

        first = _structural_part(self.query.trip(self.run_id))
        second = _structural_part(self.query.trip(self.run_id))
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True),
            json.dumps(second, ensure_ascii=False, sort_keys=True),
            "同一个 run 连读两次，结构部分不一致",
        )

    def test_i5_read_layer_accepts_an_injected_read_time(self) -> None:
        """freshness 由 now 决定，因此读取层必须有 now 注入点。"""

        candidates = {
            "TripQueryService.trip": trip_query_module.TripQueryService.trip,
            "TripQueryService.candidates": (
                trip_query_module.TripQueryService.candidates
            ),
            "TripQueryService.__init__": (
                trip_query_module.TripQueryService.__init__
            ),
            "_presentation_contract": trip_read_model._presentation_contract,
            "_map_payload_contract": trip_read_model._map_payload_contract,
        }
        accepting = sorted(
            name for name, function in candidates.items() if _accepts_now(function)
        )
        self.assertNotEqual(
            [],
            accepting,
            "阻塞于 P3：读取层没有任何 now/clock 注入点。已检查 "
            + "、".join(sorted(candidates))
            + "。EvidenceBroker 已支持注入（evidence_broker.py:131-134），"
            "读取层没有同等能力，因此 freshness 无法按读取时刻计算。",
        )

    def test_i5_freshness_differs_across_a_tolerance_boundary(self) -> None:
        """跨越容忍窗的两次读取必须产出不同的 freshness 分量。"""

        payload = self.query.trip(self.run_id)
        presentation = payload["presentation"]
        nodes = presentation.get("evidence_statuses")
        self.assertIsInstance(nodes, list)
        assert isinstance(nodes, list)
        carriers = [node for node in nodes if isinstance(node, dict) and "token" in node]
        self.assertNotEqual(
            [],
            carriers,
            "读取层不产出 token，无法比较两次读取的 freshness 分量。"
            "本条与 test_i5_read_layer_accepts_an_injected_read_time "
            "一并阻塞于 P3。",
        )


if __name__ == "__main__":
    unittest.main()
