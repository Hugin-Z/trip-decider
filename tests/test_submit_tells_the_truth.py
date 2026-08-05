"""三层撒谎：返回体、事件流、missing 视图，说的必须是同一件事。

**事故**（Claude Desktop 第六次实测，2026-08-05）。宿主连交三轮证据，三轮
`accepted: false`、零字段级报错，最后止损。它自己给出的观察极准：

1. `accepted: false` 但证据**实际入库**——blockers 的 evidence_refs 从
   `map-live-query` 变成了 `map-user-supply-…`，事件流还发了 `support: sourced`；
2. 工具描述承诺「拒收报错逐个点名缺键」「missing 视图给 required_fields」，
   两者都没兑现，missing 只回 blockers；
3. map 域 blocker 的 `data_type` 是 `poi_coordinate`，宿主据此猜「系统要的是
   坐标」，而它提交的是班车时刻。

**决定性测试先行**（宿主的根因假设是「user_supply 没接 fact extraction」）：
把一次 live-query 成功的内部结构原样包成 user_supply 提交，两侧解析结果**逐条
相等**（15 条 facts、2 段 local_transit）。**假设证伪**——管线是共用的。

真因是三处各自独立的「说谎」：

* `submit_run_evidence` 忘了传 `accepted=True`，而它默认 False——一次成功的
  提交对外报「未接受」，且没有任何理由字段可看（本文件第一组）；
* 事件流在事实进入可读结构**之前**就宣布 `support: sourced`（第二组）；
* `missing` 视图从不带 `required_fields`，尽管描述明写它会带（第三组）。

`poi_coordinate` 是**freshness 策略的键，不是 schema 提示**：map 域解析过路线
时是 `route_duration`，否则是 `poi_coordinate`。宿主把它读成「要交坐标」完全
合理——因为没有任何地方说过它不是。这一条由第三组（公布 schema）覆盖。
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from trip_decider.agent_actions import (
    _DOMAINS,
    execute_registered_action,
    pending_action_schemas,
    submit_evidence,
)
from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.evidence_projection import usable_fact_values
from trip_decider.mcp_adapter import TripMCPAdapter
from trip_decider.travel_agent import InMemoryAgentStore
from trip_decider.trip_application import (
    ApplicationOutcome,
    TripApplicationService,
)
from trip_decider.trip_query import TripQueryService

from tests.invariant_support import (
    controlled_map,
    controlled_railway,
    controlled_web,
    noop_collector,
)

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


class _Harness(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        root = Path(self._temporary.name) / "sessions"
        self.store = InMemoryAgentStore(root)

        class _NoBackground(TripApplicationService):
            @staticmethod
            def _spawn(*, target: object, args: object, name: str) -> None:
                del target, args, name

        self.application = _NoBackground(
            store=self.store,
            evidence_broker=EvidenceBroker(root.parent / "cache"),
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

    def _submit_map(self) -> dict[str, object]:
        live = controlled_map()
        return self.adapter.submit_trip_evidence(
            self.run_id,
            {
                "action_id": "map",
                "value": dict(live.value),
                "sources": [dict(source) for source in live.sources],
            },
        )


class NoHalfAcceptanceCase(_Harness):
    """入库了就说入库了。「半接受」是本轮事故的第一因。"""

    def test_a_stored_submission_reports_accepted_true(self) -> None:
        response = self._submit_map()

        self.assertIs(
            True,
            response["accepted"],
            "证据已入库却报 accepted=false——宿主会以为自己没交上",
        )

    def test_the_response_says_how_many_facts_were_parsed(self) -> None:
        """布尔不够。数字才说得清「进去了多少」。"""

        response = self._submit_map()

        self.assertGreater(
            response.get("parsed_facts_count", 0),
            0,
            "没有回报解析出的事实条数，宿主无从判断解析是否真的发生",
        )

    def test_user_supply_parses_exactly_like_live_query(self) -> None:
        """决定性测试：同一份内容，两条路解析结果必须相等。

        宿主的根因假设是「user_supply 没接 extractor」。这一条把它钉死。
        """

        live = controlled_map()
        self._submit_map()

        stored = self.application.current_run_evidence(self.run_id)["map"]
        stored_facts = stored.get("value", {}).get("facts") or []

        self.assertEqual(
            len(live.facts),
            len(stored_facts),
            "同一份内容经 user_supply 之后事实条数变了",
        )
        self.assertEqual(
            len(usable_fact_values(live.facts).get("local_transit") or []),
            len(usable_fact_values(stored_facts).get("local_transit") or []),
        )

    def test_published_local_transit_example_completes_the_full_chain(
        self,
    ) -> None:
        """决定性测试 v2：外部方只照 missing 公布的形状回喂。

        v1 把 live-query 的内部对象交给 user_supply，只证明两条入口共用
        extractor；这条不读任何内部 value 结构，只消费 pending_action 的
        ``submit_action_id`` 与 ``example``，再看字段级事实与 read model。
        """

        for item in (controlled_railway(), controlled_web()):
            self.adapter.submit_trip_evidence(
                self.run_id,
                {
                    "action_id": item.domain,
                    "value": dict(item.value),
                    "sources": [dict(source) for source in item.sources],
                },
            )
        self.adapter.submit_trip_evidence(
            self.run_id,
            {
                "action_id": "map",
                "status": "missing",
                "missing_reason": "宿主地图查询没有返回路线",
            },
        )
        execute_registered_action(self.run_id, "planner", store=self.store)

        missing = self.adapter.read_trip(self.run_id, view="missing")
        action = next(
            item
            for item in missing["pending_actions"]
            if item["action_id"] == "local_transit_manual"
        )
        before = self.adapter.read_trip(self.run_id)["presentation"][
            "planning_draft"
        ]["collected_information"]["local_transit_count"]

        # 旧说明书只公布一个 JSON 字符串。外部方没有内部结构可参考，只能把
        # example 原值作为工具 schema 所说的 value 提交；修复后的完整 example
        # 则应当能够不加解释地原样提交。
        example = action["example"]
        submission = (
            dict(example)
            if isinstance(example, dict)
            else {
                "action_id": action["submit_action_id"],
                "value": example,
                "sources": [
                    {
                        "provider": "external-host",
                        "retrieved_at": "2026-08-05T13:30:00+08:00",
                    }
                ],
            }
        )
        response = self.adapter.submit_trip_evidence(
            self.run_id,
            submission,
        )

        self.assertGreater(
            response["parsed_facts_count"],
            0,
            "missing 公布的 example 被 accepted，却没有解析出字段级事实",
        )
        execute_registered_action(self.run_id, "planner", store=self.store)
        after = self.adapter.read_trip(self.run_id)["presentation"][
            "planning_draft"
        ]["collected_information"]["local_transit_count"]
        self.assertGreater(
            after,
            before,
            "照 example 提交后，collected_information.local_transit_count 没增长",
        )

    def test_published_accommodation_example_completes_the_full_chain(
        self,
    ) -> None:
        rail = controlled_railway()
        self.adapter.submit_trip_evidence(
            self.run_id,
            {
                "action_id": "railway",
                "value": dict(rail.value),
                "sources": [dict(source) for source in rail.sources],
            },
        )
        for action_id in ("web", "map"):
            self.adapter.submit_trip_evidence(
                self.run_id,
                {
                    "action_id": action_id,
                    "status": "missing",
                    "missing_reason": f"{action_id} 查询没有返回结果",
                },
            )
        execute_registered_action(self.run_id, "planner", store=self.store)

        action = next(
            item
            for item in self.adapter.read_trip(
                self.run_id,
                view="missing",
            )["pending_actions"]
            if item["action_id"] == "accommodation_base_manual"
        )
        before = self.adapter.read_trip(self.run_id)["presentation"][
            "planning_draft"
        ]["collected_information"]["accommodation_base"]
        response = self.adapter.submit_trip_evidence(
            self.run_id,
            deepcopy(action["example"]),
        )

        self.assertGreater(response["parsed_facts_count"], 0)
        execute_registered_action(self.run_id, "planner", store=self.store)
        after = self.adapter.read_trip(self.run_id)["presentation"][
            "planning_draft"
        ]["collected_information"]["accommodation_base"]
        self.assertFalse(before)
        self.assertTrue(
            after,
            "照住宿 example 提交后，collected_information.accommodation_base 未增长",
        )

    def test_published_attraction_example_completes_the_full_chain(
        self,
    ) -> None:
        """外部方只读 attraction pending schema 也能补进景点事实。"""

        rail = controlled_railway()
        self.adapter.submit_trip_evidence(
            self.run_id,
            {
                "action_id": "railway",
                "value": dict(rail.value),
                "sources": [dict(source) for source in rail.sources],
            },
        )
        for action_id in ("web", "map"):
            self.adapter.submit_trip_evidence(
                self.run_id,
                {
                    "action_id": action_id,
                    "status": "missing",
                    "missing_reason": f"{action_id} 查询没有返回结果",
                },
            )
        execute_registered_action(self.run_id, "planner", store=self.store)

        action = next(
            item
            for item in self.adapter.read_trip(
                self.run_id,
                view="missing",
            )["pending_actions"]
            if item["submit_action_id"] == "web"
        )
        before = self.adapter.read_trip(self.run_id)["presentation"][
            "planning_draft"
        ]["collected_information"]["attraction_count"]
        response = self.adapter.submit_trip_evidence(
            self.run_id,
            deepcopy(action["example"]),
        )

        self.assertGreater(response["parsed_facts_count"], 0)
        execute_registered_action(self.run_id, "planner", store=self.store)
        after = self.adapter.read_trip(self.run_id)["presentation"][
            "planning_draft"
        ]["collected_information"]["attraction_count"]
        self.assertEqual(0, before)
        self.assertGreater(
            after,
            before,
            "照 attraction example 提交后，attraction_count 仍为 0",
        )

    def test_every_published_user_supply_example_is_directly_replayable(
        self,
    ) -> None:
        """扫描式契约：missing 公布多少 example，机器就原样吃多少。"""

        for action_id in _DOMAINS:
            self.adapter.submit_trip_evidence(
                self.run_id,
                {
                    "action_id": action_id,
                    "status": "missing",
                    "missing_reason": f"{action_id} 查询没有返回结果",
                },
            )
        execute_registered_action(self.run_id, "planner", store=self.store)
        pending = self.adapter.read_trip(
            self.run_id,
            view="missing",
        )["pending_actions"]
        documented = list(pending)
        self.assertTrue(documented, "pending_actions 没有可回喂的证据动作")

        for action in documented:
            with self.subTest(action_id=action["action_id"]):
                self.assertTrue(
                    action.get("required_fields"),
                    "gate 依赖动作必须公布非空 required_fields",
                )
                self.assertIn(
                    "example",
                    action,
                    "公布 required_fields 的动作必须同时给完整 example",
                )
                example = action["example"]
                self.assertIsInstance(
                    example,
                    dict,
                    "example 必须是结构化提交记录，不得是待二次解析的字符串",
                )
                self.assertEqual("example.value", action.get("field_scope"))
                self.assertEqual(
                    action["submit_action_id"],
                    example.get("action_id"),
                    "公布动作与可回喂 example 的 action_id 必须一致",
                )
                response = self.adapter.submit_trip_evidence(
                    self.run_id,
                    deepcopy(example),
                )
                self.assertGreater(
                    response["parsed_facts_count"],
                    0,
                    "pending_action.example 原样回喂没有产生事实",
                )

    def test_every_submission_gate_has_a_nonempty_published_schema(self) -> None:
        """按真实 gate 清单反推，不等某个域先在宿主里撞红。"""

        schemas = pending_action_schemas(
            [
                {
                    "action_id": domain,
                    "submit_action_id": domain,
                    "title": f"{domain} gate probe",
                }
                for domain in _DOMAINS
            ]
        )
        self.assertEqual(set(_DOMAINS), {
            schema["submit_action_id"] for schema in schemas
        })
        for schema in schemas:
            with self.subTest(domain=schema["submit_action_id"]):
                self.assertTrue(schema.get("required_fields"))
                self.assertIsInstance(schema.get("example"), dict)
                self.assertTrue(schema["example"])
                self.assertEqual(
                    schema["submit_action_id"],
                    schema["example"].get("action_id"),
                )

    def test_a_negative_acceptance_must_carry_a_reason(self) -> None:
        """D20：收活的命令报 accepted=False 而不给理由，在形状上不可能。"""

        with self.assertRaises(ValueError):
            ApplicationOutcome(
                "run-1",
                accepted=False,
                parsed_facts_count=0,  # 标明这是一条收活的命令
            )

    def test_a_reasoned_rejection_is_allowed(self) -> None:
        outcome = ApplicationOutcome(
            "run-1",
            accepted=False,
            parsed_facts_count=0,
            rejection_reason="local_transit[0] 缺 duration_seconds",
            missing_keys=("local_transit[].duration_seconds",),
        )

        self.assertEqual(
            "local_transit[0] 缺 duration_seconds",
            outcome.rejection_reason,
        )


class EventsAndStateAgreeCase(_Harness):
    """事件说 sourced、状态说 unknown，必有一个在撒谎。

    这是本轮事故里最难自查的一层：宿主看到事件流写着 `support: sourced`，
    于是相信证据已被采纳，而 `collected_information` 的对应计数是 0。两边都
    「有道理」，合起来无法同时为真。
    """

    def _sourced_events(self) -> list[dict[str, object]]:
        run = self.store.get_run(self.run_id)
        return [
            dict(event.details or {})
            for event in self.store.events_after(run.session_id, 0)
            if str((event.details or {}).get("support")) == "sourced"
        ]

    def test_a_sourced_event_implies_readable_facts(self) -> None:
        self._submit_map()

        events = self._sourced_events()
        self.assertTrue(events, "提交成功却没有任何 sourced 事件")

        stored = self.application.current_run_evidence(self.run_id)["map"]
        facts = stored.get("value", {}).get("facts") or []
        self.assertGreater(
            len(facts),
            0,
            "事件流宣布 support=sourced，但 planner 可读结构里一条事实都没有"
            "——两者必有一个在撒谎",
        )

    def test_every_sourced_domain_is_actually_readable(self) -> None:
        """逐域核对，不是只看总数。"""

        for item in (controlled_railway(), controlled_web(), controlled_map()):
            submit_evidence(
                self.run_id,
                {**item.to_dict(), "action_id": item.domain},
                store=self.store,
            )

        evidence = self.application.current_run_evidence(self.run_id)
        for domain in ("railway", "web", "map"):
            with self.subTest(domain=domain):
                stored = evidence.get(domain)
                self.assertIsNotNone(stored, f"{domain} 域没入库")
                facts = stored.get("value", {}).get("facts") or []
                self.assertGreater(
                    len(facts),
                    0,
                    f"{domain} 域声称 sourced 却解析出 0 条事实",
                )

    def test_zero_fact_record_does_not_emit_a_sourced_event(self) -> None:
        response = self.adapter.submit_trip_evidence(
            self.run_id,
            {
                "action_id": "map",
                "value": {},
                "sources": [
                    {
                        "provider": "empty-map-result",
                        "retrieved_at": "2026-08-05T13:30:00+08:00",
                    }
                ],
            },
        )

        self.assertTrue(response["accepted"])
        self.assertEqual(0, response["parsed_facts_count"])
        self.assertEqual(
            [],
            [
                event
                for event in self._sourced_events()
                if event.get("tool") == "map"
            ],
            "记录被接受不等于解析出了 sourced 字段；0 facts 不得发 sourced",
        )


class MissingViewKeepsItsPromiseCase(_Harness):
    """描述里承诺的字段，missing 返回体必须在场。

    系统要求证据却不公布证据 schema，是这个产品的自我违背——它整套价值就建立在
    「说得出出处」上，却在最需要说清的地方沉默。
    """

    def _promised_keys(self) -> set[str]:
        """从工具描述里抽出它承诺 missing 会给的字段名。"""

        import asyncio

        from trip_decider.mcp_server import build_mcp_server

        server = build_mcp_server(self.adapter)
        tools = {
            tool.name: (tool.description or "")
            for tool in asyncio.run(server.list_tools())
        }
        blob = " ".join(tools.values())
        promised = set()
        for key in ("required_fields", "optional_fields"):
            if key in blob:
                promised.add(key)
        return promised

    def test_the_view_delivers_every_field_the_description_promises(
        self,
    ) -> None:
        import json

        promised = self._promised_keys()
        self.assertTrue(
            promised,
            "描述里没有任何字段承诺——这条用例失去意义，请检查是不是描述被改空了",
        )

        view = self.adapter.read_trip(self.run_id, view="missing")
        blob = json.dumps(view, ensure_ascii=False)

        absent = sorted(key for key in promised if key not in blob)
        self.assertEqual(
            [],
            absent,
            f"描述承诺 missing 会给 {sorted(promised)}，实际返回体里没有 "
            f"{absent}。宿主照着描述去查，什么也查不到",
        )

    def test_pending_actions_name_their_required_fields(self) -> None:
        view = self.adapter.read_trip(self.run_id, view="missing")
        pending = view.get("pending_actions")

        self.assertIsInstance(pending, list)
        for action in pending:
            with self.subTest(action=action.get("action_id")):
                self.assertIn("required_fields", action)
                self.assertIn("submit_action_id", action)


if __name__ == "__main__":
    unittest.main()
