"""I12：凡通过 evidence 校验的提交，Planner 消费不得抛异常。

契约：docs/contracts/invariants.md I12
预期转绿：P5（本轮落地）

这条不变式来自宿主实测的 P0：四层校验全过、事件流写下「取得有效证据」，
Planner 随即 `KeyError: 'origin_station'`。**「过了门死在屋里」** 的一般形式是
校验声称的字段集与消费实际取的字段集是两张表（D2 的变体）。

I12 把它固定成一条可核对的性质：门是消费的充分条件。要么门收紧到消费的真实
需求，要么消费能吃下门放行的任何形状——两者取其一即可，但**不许都不做**。

三条断言分别守三件事：

1. **组合穷举**：必填字段的每一个子集，要么被门拦下，要么规划器跑通。不许
   出现「门放行 + 规划器抛异常」。
2. **边界形状**：方向整体缺席 / 空对象 / 非映射 / 已核实无直达，各一例。
3. **结构守卫**：消费端直取的键集合必须等于登记常量。新加一个 `train[...]`
   而忘了登记，这条会红——靠人记得同步两张表正是事故本身（D20）。
"""

from __future__ import annotations

import ast
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider.agent_actions import (
    execute_registered_action,
    submit_evidence,
)
from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.itinerary_planner import RAIL_EVENT_REQUIRED_TRAIN_FIELDS
from trip_decider.travel_agent import InMemoryAgentStore, TravelAgentError
from trip_decider.trip_application import TripApplicationService

from tests.evidence_factory import railway_value
from tests.invariant_support import (
    SRC_ROOT,
    controlled_map,
    controlled_web,
    noop_collector,
)

PLANNER_MODULE = SRC_ROOT / "trip_decider" / "itinerary_planner.py"


class _NoBackgroundApplication(TripApplicationService):
    @staticmethod
    def _spawn(*, target: object, args: object, name: str) -> None:
        del target, args, name


_INTENT = {
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
    "themes": ["自然"],
}


def _submission(value: object) -> dict[str, object]:
    return {
        "action_id": "railway",
        "evidence_id": "railway-user-supply",
        "domain": "railway",
        "status": "sourced",
        "value": value,
        "sources": [
            {
                "provider": "中国铁路12306",
                "retrieved_at": "2026-08-03T10:20:00+08:00",
            }
        ],
    }


def _subscripted_train_fields(function_name: str) -> set[str]:
    """AST 取出 ``make_rail_event`` 里所有 ``train["..."]`` 的键。

    选 AST 而不是命名约定，理由与 ``invariant_support.scan_decision_points``
    相同：读的是真代码，跟着重构走；漏登记会红，那正是希望的行为。
    只收下标取值（``train[...]``），不收 ``train.get(...)``——后者缺席可容忍，
    本来就不是必填。
    """

    tree = ast.parse(PLANNER_MODULE.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Subscript)
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "train"
                and isinstance(inner.slice, ast.Constant)
                and isinstance(inner.slice.value, str)
            ):
                found.add(inner.slice.value)
    return found


class ValidatedEvidenceNeverCrashesPlannerCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self._root = Path(self._temporary.name)

    def _drive(self, value: object) -> tuple[str, Exception | None]:
        """提交一份铁路 value，返回 ``(结局, 门口拒绝的异常)``。

        结局取值：``rejected``（门拦下）/ ``planned``（规划器跑通）。
        规划器抛异常时本方法直接让它逃逸——那正是 I12 要抓的东西。
        """

        root = self._root / f"sessions-{id(value)}-{len(str(value))}"
        store = InMemoryAgentStore(root)
        application = _NoBackgroundApplication(
            store=store,
            evidence_broker=EvidenceBroker(root.parent / "cache"),
            railway_collector=noop_collector,
            map_collector=noop_collector,
            web_collector=noop_collector,
        )
        run = application.create_trip(_INTENT)
        application.confirm_trip(run.run_id)
        application.execute_trip(run.run_id)

        try:
            submit_evidence(run.run_id, _submission(value), store=store)
        except TravelAgentError as error:
            return "rejected", error

        submit_evidence(
            run.run_id,
            {**controlled_web().to_dict(), "action_id": "web"},
            store=store,
        )
        submit_evidence(
            run.run_id,
            {**controlled_map().to_dict(), "action_id": "map"},
            store=store,
        )
        # 直接调 handler：execute_registered_action 会把异常吞成
        # PLANNER_ACTION_FAILED，那正是事故里掩盖归因的那一层。这里要原样的栈。
        from trip_decider.agent_actions import _TOOL_REGISTRY, _state

        current = store.get_run(run.run_id)
        _TOOL_REGISTRY["planner"]["handler"](
            current.intent,
            _state(run.run_id, store),
        )
        return "planned", None

    # -- 1. 必填字段的每一个子集 -------------------------------------------

    def test_i12_every_required_field_subset_is_gated_or_planned(self) -> None:
        """去程字段的 32 个子集逐个过：门拦下或规划器跑通，二选一。"""

        fields = tuple(RAIL_EVENT_REQUIRED_TRAIN_FIELDS)
        complete = railway_value()
        crashes: list[str] = []
        for size in range(len(fields) + 1):
            for kept in combinations(fields, size):
                outbound = {
                    key: value
                    for key, value in complete["outbound"].items()
                    if key in kept or key not in fields
                }
                value = {
                    "outbound": outbound,
                    "return": dict(complete["return"]),
                }
                try:
                    self._drive(value)
                except TravelAgentError:
                    raise
                except Exception as error:  # noqa: BLE001 — 正是要抓的那类
                    crashes.append(
                        f"保留 {sorted(kept)} 时 Planner 抛 "
                        f"{type(error).__name__}: {error}"
                    )
        self.assertEqual(
            [],
            crashes,
            "以下提交通过了 evidence 校验，Planner 消费却抛异常——"
            "校验通过不等于消费必成功（I12）：\n  " + "\n  ".join(crashes),
        )

    # -- 2. 边界形状 --------------------------------------------------------

    def test_i12_boundary_shapes_are_gated_or_planned(self) -> None:
        complete = railway_value()
        shapes: dict[str, object] = {
            "去程整体缺席": {"return": dict(complete["return"])},
            "去程空对象": {
                "outbound": {},
                "return": dict(complete["return"]),
            },
            "去程非映射": {
                "outbound": "G1234",
                "return": dict(complete["return"]),
            },
            "两个方向都缺席": {"roundtrip_fare_cny": 800.0},
            "已核实无直达": {
                "kind": "confirmed_absent",
                "scope": {
                    "origin": "甲站",
                    "destination": "乙站",
                    "window": "2026-08-04~2026-08-07",
                },
                "retrieved_at": "2026-08-02T18:00:00+08:00",
            },
            "完整": {
                "outbound": dict(complete["outbound"]),
                "return": dict(complete["return"]),
            },
        }
        crashes: list[str] = []
        for label, value in shapes.items():
            try:
                self._drive(value)
            except TravelAgentError:
                raise
            except Exception as error:  # noqa: BLE001
                crashes.append(f"{label}：{type(error).__name__}: {error}")
        self.assertEqual(
            [],
            crashes,
            "以下边界形状过了门却让 Planner 抛异常（I12）：\n  "
            + "\n  ".join(crashes),
        )

    # -- 3. 门之前写下的盘上证据 -------------------------------------------

    def test_i12_legacy_on_disk_evidence_degrades_instead_of_crashing(
        self,
    ) -> None:
        """绕过提交门，直接喂编译器——模拟门落地之前写进盘里的证据。

        提交门只管**新**提交。历史 run 目录里躺着的铁路证据是门之前写的，恢复
        回来时不会再过一次门（`_load_loop_state` 直接反序列化）。那些证据要是
        缺可排程字段，编译器仍会崩——I12 就只在新提交上成立，在恢复路径上不
        成立。这条用例守的是后一半。

        期望的降级是**已有的**判定点 `RAILWAY_{}_MISSING`（该方向排不出车次
        事件），不是新造一个码，也不是给缺失字段编一个默认值——车站名编不出来。
        """

        from trip_decider.planning_input_compiler import PlanningInputCompiler
        from trip_decider.travel_agent import (
            DestinationContext,
            EvidenceItem,
            EvidenceStatus,
            TravelIntent,
        )

        intent = TravelIntent.from_mapping(_INTENT)
        complete = railway_value()
        crippled = {
            key: value
            for key, value in complete["outbound"].items()
            if key != "origin_station"
        }
        context = DestinationContext(
            context_id="context-legacy",
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
                    evidence_id="railway-legacy",
                    domain="railway",
                    status=EvidenceStatus.SOURCED,
                    value={
                        **complete,
                        "outbound": crippled,
                    },
                    sources=(
                        {
                            "provider": "中国铁路12306",
                            "retrieved_at": "2026-08-02T18:00:00+08:00",
                        },
                    ),
                ),
            ),
            built_at="2026-08-02T18:30:00+08:00",
        )

        from datetime import datetime, timezone

        compiled = PlanningInputCompiler().compile(
            context,
            now=datetime(2026, 8, 2, 11, 0, tzinfo=timezone.utc),
        )

        codes = {
            str(blocker.get("blocker_id") or blocker.get("code"))
            for blocker in compiled["conditional_blockers"]
        }
        self.assertIn(
            "RAILWAY_OUTBOUND_MISSING",
            codes,
            f"缺字段的方向没有退回既有的 blocker，而是别的处置：{sorted(codes)}",
        )
        self.assertEqual(
            [],
            [
                event
                for day in compiled["days"]
                for event in day["events"]
                if event.get("event_id") == "rail-outbound"
            ],
            "去程缺起点站却仍然排出了车次事件——那是编了一个站名出来",
        )

    # -- 4. 结构守卫：两张表由同一个常量派生 -------------------------------

    def test_i12_consumption_keys_match_the_registered_constant(self) -> None:
        """`make_rail_event` 直取的键必须等于登记常量。

        这条守的是**将来**：新加一个 `train["..."]` 而忘了同步常量，门就又
        比消费松了，I12 重新破。靠人记得同步两张表正是事故本身（D20）。
        """

        indexed = _subscripted_train_fields("make_rail_event")
        registered = set(RAIL_EVENT_REQUIRED_TRAIN_FIELDS)
        self.assertEqual(
            registered,
            indexed,
            "消费端直取的键与登记常量不一致："
            f"只在代码里的 {sorted(indexed - registered)}，"
            f"只在常量里的 {sorted(registered - indexed)}",
        )


if __name__ == "__main__":
    unittest.main()
