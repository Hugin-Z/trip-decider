"""`user_input` 证据是 intent 的投影，读时重建必须稳定。

裁决（2026-08-03，`persistence-v2.md` §2.1.1）：`user_input` 域不落盘，读取时
从 `run.intent` 重建。理由——它**本来就不是采集来的证据**，`_planner_handler`
一直是现造这一条，没有任何采集器产出过它。不落盘顺带消灭第四份副本。

**稳定性是这条裁决能成立的前提。** PlanVersion 里的事件用 `fact_id`
（`<evidence_id>#<field>`）指向行程窗事实；重建若给出不同的 id，每次读取都会
把这些引用打断一次，而引用解析失败在 R2 下会产出 `unknown` + `next_action`
——表现出来是「计划莫名其妙缺输入」，查起来完全看不出根因是重建不稳定。

D13：内部寻址方式（证据从哪来）变了，对外形状（fact_id）不该跟着变。
"""

from __future__ import annotations

import unittest

from trip_decider.evidence_core import fact_id
from trip_decider.evidence_projection import item_facts
from trip_decider.travel_agent import (
    USER_INPUT_EVIDENCE_ID,
    TravelIntent,
    user_input_evidence,
)

from tests.invariant_support import offline_intent


def _intent() -> TravelIntent:
    return TravelIntent.from_mapping(offline_intent())


class UserInputRebuildCase(unittest.TestCase):
    def test_two_rebuilds_of_one_intent_give_the_same_fact_ids(self) -> None:
        """同一 intent 两次重建 → 同一批 fact_id。"""

        first = user_input_evidence(_intent()).to_dict()
        second = user_input_evidence(_intent()).to_dict()

        self.assertEqual(
            first["evidence_id"],
            second["evidence_id"],
        )
        first_ids = sorted(str(f["fact_id"]) for f in item_facts(first))
        second_ids = sorted(str(f["fact_id"]) for f in item_facts(second))
        self.assertEqual(
            first_ids,
            second_ids,
            "两次重建给出不同的 fact_id——事件的 fact_refs 会在每次读取时"
            "被打断一次，表现为「计划莫名其妙缺输入」",
        )
        self.assertNotEqual([], first_ids, "重建没有产出任何 fact")

    def test_the_evidence_id_is_a_fixed_literal_not_a_uuid(self) -> None:
        """id 必须是固定字面量。

        其它域的证据用 uuid 无妨——它们是采集产物，一次采集一个身份。
        本域是**投影**：同一个 intent 投影出的东西必须是同一个身份，否则
        「重建」就变成了「每次造一个新的」。
        """

        self.assertEqual(
            USER_INPUT_EVIDENCE_ID,
            user_input_evidence(_intent()).evidence_id,
        )
        self.assertNotIn("-", USER_INPUT_EVIDENCE_ID.replace("-", "", 2))

    def test_fact_ids_follow_the_single_generation_rule(self) -> None:
        """重建产物的 fact_id 必须由 `evidence_core.fact_id` 生成。

        全仓唯一的生成规则。两侧各拼一套会让引用在读取时对不上，而对不上只
        表现为「引用解析失败」，看不出是规则不一致造成的。
        """

        facts = item_facts(user_input_evidence(_intent()).to_dict())
        for fact in facts:
            with self.subTest(field=fact.get("field")):
                self.assertEqual(
                    fact_id(USER_INPUT_EVIDENCE_ID, str(fact["field"])),
                    str(fact["fact_id"]),
                )

    def test_a_different_intent_gives_the_same_ids_but_different_values(
        self,
    ) -> None:
        """身份稳定不等于内容冻结。

        换一个 intent，fact_id 仍是那一批（字段名没变），但值必须跟着变——
        否则重建就成了返回一个常量，稳定得毫无用处。
        """

        base = offline_intent()
        other = {**base, "travelers": int(base.get("travelers") or 1) + 3}

        first = user_input_evidence(TravelIntent.from_mapping(base)).to_dict()
        second = user_input_evidence(TravelIntent.from_mapping(other)).to_dict()

        self.assertEqual(
            sorted(str(f["fact_id"]) for f in item_facts(first)),
            sorted(str(f["fact_id"]) for f in item_facts(second)),
        )
        self.assertNotEqual(
            first["value"],
            second["value"],
            "换了 intent 而重建结果不变——它返回的是常量，不是投影",
        )


if __name__ == "__main__":
    unittest.main()
