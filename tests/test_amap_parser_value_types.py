"""AMap 解析器的值类型必须真的可构造。

**事故**：`c7cbd50`「extract the AMap parsers and finish the amputation」把 7 个
值类从 `live_place_resolution` 搬进 `amap_parsers`，commit message 写着
「bodies, signatures and docstrings unchanged」——但**每一个 `@dataclass(frozen=True)`
装饰器都掉了**。掉了之后这些类退化成只有类型注解的空类，
`ParsedAmapDistrict(name=..., adcode=..., level=...)` 直接
`TypeError: ParsedAmapDistrict() takes no arguments`。

后果：**整条高德解析路径从 2026-08-02 起就是死的**，而套件 250 条全绿。原因是
这条路径一条测试都没有——单测用的是受控证据与夹具，没有任何用例真的调用过
解析器。P5 轮 5 第一次拿真实数据跑冒烟，第一个调用就撞上了它。

这正是「产品可用 ≠ 功能存在」那句话的实证，也是 D7 的一个新样本：三层守卫里
**没有任何一层**负责「这个模块 import 得进来、类构造得出来」。不变式守契约性质、
单测守数据形状、表征守判定结果——都不守「代码根本跑不跑得起来」。

本文件补的就是那一层：对每个值类做一次真实构造。它挡不住所有重构事故，但能
挡住「装饰器掉了」这一类——而这一类已经真的发生过一次。
"""

from __future__ import annotations

import dataclasses
import unittest

from trip_decider import amap_parsers


#: 搬迁前在 `live_place_resolution` 里带 `@dataclass(frozen=True)` 的全部值类。
#: 名单来自 `git show c7cbd50^:src/trip_decider/live_place_resolution.py`。
_FROZEN_VALUE_TYPES = (
    "LivePlaceResolutionSummary",
    "ParsedAmapDistrict",
    "ParsedAmapPoi",
    "ParsedAmapDistrictResponse",
    "ParsedAmapPoiResponse",
    "PolicyBoundAmapObservation",
    "AmapCandidateProjection",
)


class AmapParserValueTypesCase(unittest.TestCase):
    def test_every_value_type_is_a_frozen_dataclass(self) -> None:
        """判据用 `dataclasses.is_dataclass` 而不是「源码里有没有那行字」。

        扫源码文本只能证明装饰器写着，证明不了它生效——而这次的故障恰恰是
        「类还在、字段注解还在、只是不是 dataclass 了」。
        """

        for name in _FROZEN_VALUE_TYPES:
            with self.subTest(value_type=name):
                target = getattr(amap_parsers, name, None)
                self.assertIsNotNone(
                    target,
                    f"{name} 从 amap_parsers 消失了",
                )
                self.assertTrue(
                    dataclasses.is_dataclass(target),
                    f"{name} 不是 dataclass——装饰器掉了，"
                    f"它现在构造不出来（c7cbd50 的原始事故）",
                )
                self.assertTrue(
                    target.__dataclass_params__.frozen,
                    f"{name} 不是 frozen——搬迁前它是 "
                    "@dataclass(frozen=True)，可变性是语义变更不是搬家",
                )

    def test_the_district_type_actually_constructs(self) -> None:
        """一次真实构造。

        `is_dataclass` 已经能抓这次的故障，但它证明的是「有 __init__」，
        不是「按这些字段名构造得出来」。字段改名同样会让解析器崩，而那不是
        装饰器问题——多这一条，判据才覆盖到调用点真正依赖的东西。
        """

        parsed = amap_parsers.ParsedAmapDistrict(
            name="婺源县",
            adcode="361130",
            level="district",
        )
        self.assertEqual("婺源县", parsed.name)
        self.assertEqual("361130", parsed.adcode)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            parsed.name = "别的地方"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
