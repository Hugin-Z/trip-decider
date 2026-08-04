"""``run.error_code`` 的取值域守卫（P5 轮 2 收敛）。

收敛前这个字段**没有取值域**：两个写入口收任意字符串，九个生产点里六个用
f-string 拼码，其中四个把异常类名插进去——取值域是「能逃出那四个 try 的每一个
异常类名」，穷举不了。后果实测得到：前端 4 键的查表漏掉 ``WEB_ACTION_STALLED``
与四个 ``*_EVIDENCE_BLOCKED``，全部静默落到「新版本未能完成」。

本文件守三件事，各对一条纪律：

* **有限性**（D20）——校验在仅有的两个写入口，绕过它得改那个函数，不是靠九个
  调用点自律；
* **生产点与消费点同表**（D2/D3）——前端的比较键集必须与 ``RUN_ERROR_CODES``
  逐字相等，比较字面量算消费点；
* **编程错误不穿业务外衣**（D12）——非业务异常归 ``INTERNAL_ERROR``，
  类型名进 ``error_detail`` 而不是进码。
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

from trip_decider.travel_agent import (
    RUN_ERROR_CODES,
    InMemoryAgentStore,
    RunStatus,
    TravelAgentError,
    confirm_intent,
    create_run,
    run_error_code,
)

from tests.invariant_support import WEB_APP_JS, offline_intent


#: 前端对它做前缀匹配而不是整键匹配，因此不出现在键表里。理由见 app.js 注释：
#: 盘上还有收敛前的 ``INTERNAL_ERROR_NAMEERROR`` 这类旧码。
_PREFIX_MATCHED = frozenset(
    {"INTERNAL_ERROR", "INTERNAL_ERROR_WORKER_LOST"}
)


def _app_js_reason_keys() -> set[str]:
    """抽出 app.js 里 ``const reasons = {...}`` 的键集。"""

    source = WEB_APP_JS.read_text(encoding="utf-8")
    block = re.search(
        r"const reasons = \{(.*?)\n    \};",
        source,
        re.DOTALL,
    )
    if block is None:
        raise AssertionError(
            "app.js 里找不到 `const reasons = {...}` 块——"
            "前端的错误码查表被改了形状，本守卫失去了核对对象"
        )
    return set(re.findall(r"^\s*([A-Z][A-Z_]+):", block.group(1), re.M))


def _blocked_run(store: InMemoryAgentStore) -> str:
    run = create_run(offline_intent(), store=store)
    confirm_intent(run.run_id, store=store)
    return run.run_id


class RunErrorCodeVocabularyCase(unittest.TestCase):
    def test_write_entries_reject_an_unregistered_code(self) -> None:
        """D20 负向验证：未注册的码在两个写入口都必须抛，不静默放行。

        没有这一条，「取值域有限」就只是一句自称——它恰好是收敛前的实情。
        """

        store = InMemoryAgentStore()
        for code in (
            "RAILWAY_EVIDENCE_BLOCKED",  # 收敛前的旧名
            "WEB_EVIDENCE_REQUIRED",  # 收敛前的旧名
            "EXECUTOR_NAMEERROR",  # 型名拼进码里的老写法
            "INTERNAL_ERROR_NAMEERROR",  # 同上
            "TOTALLY_MADE_UP",
        ):
            with self.subTest(code=code, entry="fail"):
                run_id = _blocked_run(store)
                with self.assertRaises(TravelAgentError) as caught:
                    store.fail(run_id, code)
                self.assertIn(code, str(caught.exception))
            with self.subTest(code=code, entry="block"):
                run_id = _blocked_run(store)
                store.start(run_id)
                with self.assertRaises(TravelAgentError):
                    store.block(run_id, {"action_loop_status": "BLOCKED"}, code)

    def test_registered_codes_pass_both_entries(self) -> None:
        """正向对照：注册过的码必须走得通。

        只证明「未注册的会抛」不够——那可能是把所有码都拒了换来的绿。
        """

        store = InMemoryAgentStore()
        for code in sorted(RUN_ERROR_CODES):
            with self.subTest(code=code):
                run_id = _blocked_run(store)
                store.start(run_id)
                run = store.block(
                    run_id,
                    {"action_loop_status": "BLOCKED"},
                    code,
                    error_detail="SomeError",
                )
                self.assertIs(run.status, RunStatus.BLOCKED)
                self.assertEqual(run.error_code, code)
                self.assertEqual(run.error_detail, "SomeError")

    def test_front_end_key_table_equals_the_registry(self) -> None:
        """D2/D3：生产点与消费点同表核对，比较字面量算消费点。

        这一条机械化的正是那次事故的形状——取值域变更分两次扫描完成，漏的那边
        不会报错，只会安静地不成立。前端漏一个键不崩不报，只是永远显示兜底文案。
        """

        self.assertEqual(
            sorted(RUN_ERROR_CODES - _PREFIX_MATCHED),
            sorted(_app_js_reason_keys()),
            "app.js 的错误码查表与 travel_agent.RUN_ERROR_CODES 不一致："
            "多出的键是死分支，缺少的键会静默落到兜底文案",
        )

    def test_no_registered_code_carries_an_exception_type_name(self) -> None:
        """两段式的核心：码里不许再出现型名。

        判据用真实异常类名而不是「码里有没有下划线」——后者会把
        ``RAILWAY_ACTION_FAILED`` 也判成违规。
        """

        type_names = {
            name.upper()
            for name in (
                "NameError",
                "AttributeError",
                "TypeError",
                "ImportError",
                "TravelAgentError",
                "ValueError",
                "RuntimeError",
            )
        }
        offenders = [
            code
            for code in RUN_ERROR_CODES
            if any(name in code for name in type_names)
        ]
        self.assertEqual(
            [],
            offenders,
            "异常类名回到了 error_code 本体里，取值域重新变成无界",
        )


class D12SplitCase(unittest.TestCase):
    """``run_error_code`` 的分流：编程错误与业务失败必须分得开。"""

    def test_non_business_errors_become_internal_error(self) -> None:
        for error in (
            NameError("undefined_helper"),
            AttributeError("no such attribute"),
            TypeError("bad operand"),
            ImportError("no module"),
        ):
            with self.subTest(error=type(error).__name__):
                code, detail = run_error_code(error, "RUN_EXECUTION_FAILED")
                self.assertEqual("INTERNAL_ERROR", code)
                self.assertEqual(type(error).__name__, detail)

    def test_business_failures_keep_the_caller_code(self) -> None:
        code, detail = run_error_code(
            TravelAgentError("rail_http"),
            "RUN_EXECUTION_FAILED",
        )
        self.assertEqual("RUN_EXECUTION_FAILED", code)
        self.assertEqual("TravelAgentError", detail)

    def test_every_business_code_it_can_return_is_registered(self) -> None:
        """分流函数的第二个实参必须是注册过的码。

        它绕不过写入口的校验，但在这里失败比在运行时失败早一步——三个调用点
        各写死一个字面量，写错了要到那条失败路径真的走到才发现。
        """

        for business_code in (
            "RUN_EXECUTION_FAILED",
            "REVISION_EXECUTION_FAILED",
            "ACTION_LOOP_FAILED",
        ):
            with self.subTest(code=business_code):
                self.assertIn(business_code, RUN_ERROR_CODES)


if __name__ == "__main__":
    unittest.main()
