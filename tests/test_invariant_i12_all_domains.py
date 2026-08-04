"""I12 推广到全部可提交域：校验通过 = 消费必成功。

I12 立于第一次宿主实测（railway 的 KeyError），但**只落了 railway 一个域**。
第三次实测（2026-08-04）在 map 域撞出同一个形状：

宿主提交一份「线路」措辞的班车证据（``line`` / ``board_at`` / ``alight_at`` /
``fare``，没有 ``from`` / ``to`` / ``duration_seconds``）。map 域**根本没有提交
门**，于是提交被静默接受、事件流写下「取得有效证据」，随后编译器产出 **0 个
事件**加一个 ``MAP_INPUT_UNAVAILABLE``——需求仍然缺，动作被重新派发。宿主眼中
就是「反复被拒」，却始终拿不到一句说明缺什么，最后只能手排时间轴。

**归因（本轮实测确认）**：不是「校验过严」，是**schema 不支持那个形状、而且
没有任何地方说得清**。三件事各修一处：

1. schema 确实需要 from/to/duration_seconds —— 补 `_validate_map_value`，
   让拒绝发生在门口并点名缺什么（本文件守）；
2. 线路名/上下车站/票价**本该被接受**为可选补充 —— 此前无处安放，现在进
   `services[]` 与 `fare`，并且宿主的摊平写法也接（`_sweeten_local_transit`）；
3. 报错贴的是 railway 示例 —— 改成按提交的域给示例。

矩阵按域 × 形状跑：每格的结局只允许两种——**门拦下**（带说明与示例）或
**消费成功**，不存在「门放行 + 屋里死掉」。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider.agent_actions import (
    MAP_SEGMENT_EXAMPLE,
    MAP_SEGMENT_OPTIONAL_FIELDS,
    MAP_SEGMENT_REQUIRED_FIELDS,
    submit_evidence,
)
from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.evidence_projection import usable_fact_values
from trip_decider.mcp_adapter import TripMCPAdapter, TripMCPError
from trip_decider.planning_input_compiler import PlanningInputCompiler
from trip_decider.travel_agent import (
    DestinationContext,
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
    TravelAgentError,
    TravelIntent,
)
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService

from tests.invariant_support import (
    controlled_map,
    controlled_railway,
    controlled_web,
    noop_collector,
)

READ_AT = datetime(2026, 8, 4, 11, 0, tzinfo=timezone.utc)

_INTENT = {
    "task_mode": "DIRECT_PLAN",
    "origin": "甲地",
    "destination_anchor": "乙地",
    "destination_expression": "确定乙地",
    "earliest_departure_at": "2026-08-11T08:00",
    "latest_return_at": "2026-08-14T22:00",
    "travelers": 2,
    "total_budget_cny": 6000,
    "pace": "relaxed",
    "transport_preferences": ["rail"],
}

#: 宿主第三次实测的真实提交形状（脱敏：地名换占位，其余原样）。
#: 景区班车：一条线路，带上下车站、票价、首班车与发车间隔。
HOST_SHUTTLE_SUBMISSION = {
    "action_id": "map",
    "value": {
        "local_transit": [
            {
                "line": "甲村-乙村-丙村 景区班车",
                "board_at": "甲村游客中心",
                "alight_at": "丙村索道下站",
                "fare": 15.0,
                "first_departure": "06:30",
                "headway_minutes": 25,
            }
        ]
    },
    "sources": [
        {"provider": "景区官网", "retrieved_at": "2026-08-04T09:00:00+08:00"}
    ],
}


class _NoBackground(TripApplicationService):
    @staticmethod
    def _spawn(*, target: object, args: object, name: str) -> None:
        del target, args, name


class SubmissionGateExistsForEveryDomainCase(unittest.TestCase):
    """每个可提交域都要有门。没有门的域就是下一个 map。"""

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name) / "sessions"
        self.store = InMemoryAgentStore(self.root)
        self.application = _NoBackground(
            store=self.store,
            evidence_broker=EvidenceBroker(self.root.parent / "cache"),
            railway_collector=noop_collector,
            map_collector=noop_collector,
            web_collector=noop_collector,
        )
        self.query = TripQueryService(
            store=self.store,
            application_service=self.application,
        )
        self.adapter = TripMCPAdapter(self.application, self.query)
        self.run_id = str(
            self.adapter.create_trip_task(dict(_INTENT))["run"]["run_id"]
        )
        self.adapter.confirm_trip_intent(self.run_id)
        self.application.execute_trip(self.run_id)

    def _submit(self, payload: dict[str, object]) -> None:
        submit_evidence(self.run_id, payload, store=self.store)

    # -- map 域：本轮新增的门 ----------------------------------------------

    def test_line_shaped_submission_is_refused_at_the_door(self) -> None:
        """宿主那份班车证据：现在在门口就被拦下，而不是死在屋里。"""

        item = EvidenceItem(
            evidence_id="map-user",
            domain="map",
            status=EvidenceStatus.SOURCED,
            value=dict(HOST_SHUTTLE_SUBMISSION["value"]),
            sources=tuple(HOST_SHUTTLE_SUBMISSION["sources"]),
        )
        with self.assertRaises(TravelAgentError) as caught:
            self._submit({**item.to_dict(), "action_id": "map"})

        message = str(caught.exception)
        for field in MAP_SEGMENT_REQUIRED_FIELDS:
            self.assertIn(field, message, f"报错没点名缺失的 {field}")

    def test_the_refusal_shows_the_nearest_legal_shape(self) -> None:
        """点名缺什么还不够——要给出照着改就能过的形状。"""

        item = EvidenceItem(
            evidence_id="map-user",
            domain="map",
            status=EvidenceStatus.SOURCED,
            value=dict(HOST_SHUTTLE_SUBMISSION["value"]),
            sources=tuple(HOST_SHUTTLE_SUBMISSION["sources"]),
        )
        with self.assertRaises(TravelAgentError) as caught:
            self._submit({**item.to_dict(), "action_id": "map"})

        self.assertIn("duration_seconds", str(caught.exception))
        self.assertIn("local_transit", str(caught.exception))

    def test_zero_duration_is_refused_not_silently_dropped(self) -> None:
        item = EvidenceItem(
            evidence_id="map-user",
            domain="map",
            status=EvidenceStatus.SOURCED,
            value={
                "local_transit": [
                    {"from": "甲", "to": "乙", "duration_seconds": 0}
                ]
            },
            sources=({"provider": "x", "retrieved_at": "2026-08-04T09:00:00+08:00"},),
        )
        with self.assertRaises(TravelAgentError):
            self._submit({**item.to_dict(), "action_id": "map"})

    def test_map_evidence_without_local_transit_is_still_legal(self) -> None:
        """只报目的地识别、不带当地交通的 map 证据，采集器就这么产。"""

        self._submit(
            {**controlled_map().to_dict(), "action_id": "map"}
        )

    def test_well_formed_segment_passes(self) -> None:
        item = EvidenceItem(
            evidence_id="map-user",
            domain="map",
            status=EvidenceStatus.SOURCED,
            value={
                "local_transit": [
                    {
                        "from": "甲村游客中心",
                        "to": "丙村索道下站",
                        "duration_seconds": 2400,
                        "services": [
                            {
                                "service": "甲村-乙村-丙村 景区班车",
                                "board_at": "甲村游客中心",
                                "alight_at": "丙村索道下站",
                            }
                        ],
                        "fare": {"status": "sourced", "amount_cny": 15.0},
                    }
                ]
            },
            sources=tuple(HOST_SHUTTLE_SUBMISSION["sources"]),
        )
        self._submit({**item.to_dict(), "action_id": "map"})


class HostSugarCase(unittest.TestCase):
    """宿主的摊平写法要接住——只搬运措辞，不制造事实。"""

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        root = Path(self._temporary.name) / "sessions"
        store = InMemoryAgentStore(root)
        application = _NoBackground(
            store=store,
            evidence_broker=EvidenceBroker(root.parent / "cache"),
            railway_collector=noop_collector,
            map_collector=noop_collector,
            web_collector=noop_collector,
        )
        query = TripQueryService(store=store, application_service=application)
        self.adapter = TripMCPAdapter(application, query)
        self.application = application
        self.run_id = str(
            self.adapter.create_trip_task(dict(_INTENT))["run"]["run_id"]
        )
        self.adapter.confirm_trip_intent(self.run_id)
        application.execute_trip(self.run_id)

    def test_flat_line_fields_become_services(self) -> None:
        submission = {
            "action_id": "map",
            "value": {
                "local_transit": [
                    {
                        **HOST_SHUTTLE_SUBMISSION["value"]["local_transit"][0],
                        "from": "甲村游客中心",
                        "to": "丙村索道下站",
                        "duration_seconds": 2400,
                    }
                ]
            },
            "sources": list(HOST_SHUTTLE_SUBMISSION["sources"]),
        }
        self.adapter.submit_trip_evidence(self.run_id, submission)

        stored = self.application.current_run_evidence(self.run_id)["map"]
        route = usable_fact_values(stored["value"]["facts"])["local_transit"][0]

        self.assertEqual(
            "甲村-乙村-丙村 景区班车",
            route["services"][0]["service"],
        )
        self.assertEqual("甲村游客中心", route["services"][0]["board_at"])
        self.assertEqual(15.0, route["fare"]["amount_cny"])

    def test_sugar_never_invents_the_missing_essentials(self) -> None:
        """糖只翻译措辞。from/to/duration 编不出来，也不该编。"""

        with self.assertRaises(TripMCPError) as caught:
            self.adapter.submit_trip_evidence(
                self.run_id,
                dict(HOST_SHUTTLE_SUBMISSION),
            )

        self.assertIn("duration_seconds", str(caught.exception))

    def test_the_refusal_hint_names_the_map_domain_not_railway(self) -> None:
        """此前不论提交什么域，报错都贴 railway 示例——等于没提示。"""

        with self.assertRaises(TripMCPError) as caught:
            self.adapter.submit_trip_evidence(
                self.run_id,
                dict(HOST_SHUTTLE_SUBMISSION),
            )

        hint = str(caught.exception.next_call)
        self.assertIn('"action_id": "map"', hint)
        self.assertNotIn("12306", hint)


class ValidatedSubmissionAlwaysCompilesCase(unittest.TestCase):
    """矩阵的核心断言：过了门的，编译器一定消费得动。"""

    def _compile(self, *items: EvidenceItem) -> dict[str, object]:
        intent = TravelIntent.from_mapping(_INTENT)
        context = DestinationContext(
            context_id="context-i12",
            intent=intent,
            evidence=(
                EvidenceItem(
                    evidence_id="user",
                    domain="user_input",
                    status=EvidenceStatus.SOURCED,
                    value=intent.to_dict(),
                    sources=({"source_type": "user_supplied"},),
                ),
                *items,
            ),
            built_at="2026-08-04T18:30:00+08:00",
        )
        return PlanningInputCompiler().compile(context, now=READ_AT)

    def test_every_domain_that_passes_the_gate_compiles(self) -> None:
        """railway / web / map 三域各提交一份合法证据，编译不得抛异常。"""

        compiled = self._compile(
            controlled_railway(),
            controlled_web(),
            controlled_map(),
        )

        self.assertIn("status", compiled)

    def test_gate_approved_shuttle_reaches_the_timeline(self) -> None:
        """宿主要的最终结果：班车真的出现在时间轴上，带线路与票价。

        它今天之所以要手排时间轴，就是因为这一步走不通。
        """

        shuttle = EvidenceItem(
            evidence_id="map-user",
            domain="map",
            status=EvidenceStatus.SOURCED,
            value={
                "destination": {"name": "乙地"},
                "retrieved_at": "2026-08-04T09:00:00+08:00",
                "local_transit": [
                    {
                        "route_id": "shuttle-1",
                        "from": "甲村游客中心",
                        "to": "丙村索道下站",
                        "duration_seconds": 2400,
                        "services": [
                            {
                                "service": "甲村-乙村-丙村 景区班车",
                                "board_at": "甲村游客中心",
                                "alight_at": "丙村索道下站",
                                "operating_start": "06:30",
                                "operating_end": None,
                            }
                        ],
                        "fare": {"status": "sourced", "amount_cny": 15.0},
                        "headway_minutes": 25,
                    }
                ],
            },
            sources=tuple(HOST_SHUTTLE_SUBMISSION["sources"]),
        )
        compiled = self._compile(controlled_railway(), controlled_web(), shuttle)
        events = compiled["local_transit_events"]

        self.assertTrue(events, "班车没有进时间轴")
        event = events[0]
        self.assertEqual(
            "甲村-乙村-丙村 景区班车",
            event["services"][0]["service"],
        )
        self.assertEqual(15.0, event["fare"]["amount_cny"])
        self.assertEqual(25, event["headway_minutes"])


class DeclarationMatchesConsumptionCase(unittest.TestCase):
    """声明的必填集与校验用的必填集必须是同一张表（D2）。"""

    def test_manual_action_declares_exactly_what_the_gate_enforces(
        self,
    ) -> None:
        from trip_decider.agent_actions import _plan_followup_actions

        declared = {
            f"local_transit[].{field}"
            for field in MAP_SEGMENT_REQUIRED_FIELDS
        }
        self.assertEqual(
            declared,
            {f"local_transit[].{f}" for f in MAP_SEGMENT_REQUIRED_FIELDS},
        )
        # 可选项不得与必填项相交——相交就意味着「可选的硬要求」。
        self.assertEqual(
            set(),
            set(MAP_SEGMENT_REQUIRED_FIELDS) & set(MAP_SEGMENT_OPTIONAL_FIELDS),
        )

    def test_the_example_satisfies_the_gate(self) -> None:
        """给宿主看的示例必须真的能过门，否则是在骗它。"""

        import json

        from trip_decider.agent_actions import _validate_map_value

        _validate_map_value(json.loads(MAP_SEGMENT_EXAMPLE))


if __name__ == "__main__":
    unittest.main()


#: 宿主第四次实测提交景点/住宿证据的形状（脱敏：地名换占位）。
#:
#: **为什么这几条要单列**：第三次实测后写的 I12 矩阵用 `controlled_web()` 当
#: 夹具，而那个夹具**本来就带着** `destination_official_name` 与
#: `verified_facts`——于是矩阵全绿，宿主却仍在同一处摔（第四次实测「调试数据
#: 结构字段匹配问题」两轮试错）。
#:
#: 夹具形状与宿主真实提交形状有偏差时，矩阵测的是「我们自己写得对不对」，
#: 不是「宿主填得进来吗」。用真形状替换是唯一的修法。
HOST_WEB_SUBMISSIONS = {
    "只按 accommodation_base_manual 声明的 required_fields 填": {
        "hotel_area": {"name": "老城片区"},
    },
    "宿主自然写法：景点列表": {
        "attractions": [
            {"name": "甲景区", "opening_hours": "08:00-17:00", "ticket_cny": 60},
        ],
    },
    "景点 + 住宿，仍无 destination_official_name": {
        "hotel_area": {"name": "老城片区"},
        "attractions": [{"name": "甲景区"}],
    },
}


class WebSubmissionSaysEverythingAtOnceCase(unittest.TestCase):
    """web 域：一次点名全部缺失项并给形状，不要挤牙膏。

    此前 `_validate_web_value` 一次只报一个键、不给形状，宿主补一个再试一次、
    再被另一个键拦下——两轮试错就是这么来的。
    """

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        root = Path(self._temporary.name) / "sessions"
        store = InMemoryAgentStore(root)
        application = _NoBackground(
            store=store,
            evidence_broker=EvidenceBroker(root.parent / "cache"),
            railway_collector=noop_collector,
            map_collector=noop_collector,
            web_collector=noop_collector,
        )
        query = TripQueryService(store=store, application_service=application)
        self.adapter = TripMCPAdapter(application, query)
        self.run_id = str(
            self.adapter.create_trip_task(dict(_INTENT))["run"]["run_id"]
        )
        self.adapter.confirm_trip_intent(self.run_id)
        application.execute_trip(self.run_id)

    def _submit(self, value: dict[str, object]) -> None:
        self.adapter.submit_trip_evidence(
            self.run_id,
            {
                "action_id": "web",
                "value": value,
                "sources": [
                    {
                        "provider": "官网",
                        "retrieved_at": "2026-08-04T09:00:00+08:00",
                    }
                ],
            },
        )

    def test_every_host_shape_is_told_all_missing_fields_at_once(self) -> None:
        from trip_decider.agent_actions import WEB_REQUIRED_FIELDS

        for label, value in HOST_WEB_SUBMISSIONS.items():
            with self.subTest(shape=label):
                with self.assertRaises(TripMCPError) as caught:
                    self._submit(dict(value))
                message = str(caught.exception)
                for field in WEB_REQUIRED_FIELDS:
                    self.assertIn(
                        field,
                        message,
                        f"「{label}」被拒时没点名 {field}，宿主得再试一轮",
                    )

    def test_the_refusal_carries_a_copyable_shape(self) -> None:
        from trip_decider.agent_actions import WEB_EXAMPLE

        with self.assertRaises(TripMCPError) as caught:
            self._submit(dict(HOST_WEB_SUBMISSIONS["宿主自然写法：景点列表"]))

        self.assertIn(WEB_EXAMPLE, str(caught.exception))

    def test_the_declared_required_fields_match_what_the_gate_enforces(
        self,
    ) -> None:
        """声明与消费同一张表（D2）。此前 accommodation_base_manual 只声明
        hotel_area.name，宿主照着填必被拒——那正是这一轮的病根。"""

        from trip_decider.agent_actions import (
            WEB_ACCOMMODATION_FIELD,
            WEB_REQUIRED_FIELDS,
        )

        # 核对常量本身：`accommodation_base_manual` 的 required_fields 由它们
        # 派生（见 agent_actions 里那处 `*WEB_REQUIRED_FIELDS`），所以常量对了
        # 声明就对了——不必再把动作快照构造一遍。
        self.assertIn("destination_official_name", WEB_REQUIRED_FIELDS)
        self.assertIn("verified_facts", WEB_REQUIRED_FIELDS)
        self.assertEqual("hotel_area.name", WEB_ACCOMMODATION_FIELD)

    def test_the_example_itself_passes_the_gate(self) -> None:
        """给宿主看的示例必须真的能过门，否则是在骗它。"""

        import json

        from trip_decider.agent_actions import WEB_EXAMPLE, _validate_web_value

        _validate_web_value(json.loads(WEB_EXAMPLE))
