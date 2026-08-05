"""真实链路疲劳测试：让机器先撞 bug，宿主复测只验收体验。

**为什么要有它**（2026-08-05，第七次宿主复测之后立的规矩）：

七次人工复测，每次暴露一个挂点，边际效率在递减。剩下的缺陷有一个共同形状——
**只有真实网络加真实时序才触发**：12306 忽快忽慢、高德分页数不定、某一段没有
公交方案、某个候选查不到车次。单元测试用桩，表征用固定夹具，两者都够不到这类
问题；而每撞一次就要占用一次人工复测。

所以把「找 bug」从人工复测里拿出来交给机器：本脚本反复跑完整链路，任何一轮
**没有走到终态**（成功或明确失败）就算这一轮失败。人工复测从此只回答一个
问题——「这东西用起来什么感觉」。

**发布前置**：交给宿主复测之前，soak 必须连续全绿。

用法：

    python scripts/soak_full_loop.py --rounds 20
    python scripts/soak_full_loop.py --rounds 3 --interval 5   # 冒烟

配额预算（按 20 轮估）：

* 高德 Web 服务：每轮约 15–25 次（district 1 + POI 每个种子 1 + 公交每段 1，
  失败时多一次驾车兜底）。20 轮约 300–500 次，个人 key 日配额通常 5000，
  占比约一成；
* 12306：无 key，但对频次敏感。每轮一次会话初始化加数次时刻表查询。
  轮间默认隔 10 秒，20 轮约 3–4 分钟纯等待，用来避免被当成压测。

`--interval` 可调但**不建议低于 5 秒**：这不是压测工具，是可靠性回归。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import random
import statistics
import sys
import time
import traceback
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trip_decider.evidence_broker import EvidenceBroker  # noqa: E402
from trip_decider.agent_actions import MAP_SEGMENT_EXAMPLE  # noqa: E402
from trip_decider.mcp_adapter import (  # noqa: E402
    TripMCPAdapter,
    TripMCPError,
)
from trip_decider.travel_agent import InMemoryAgentStore  # noqa: E402
from trip_decider.trip_application import (  # noqa: E402
    TripApplicationService,
)
from trip_decider.trip_query import TripQueryService  # noqa: E402

#: 目的地种子池。抽样而不是固定一个——固定目的地只会反复验证同一条缓存路径。
#: 首跑教训：前六个种子里有四个不在候选池 / 查不到往返车次，于是「没有候选」
#: 占了失败的一半——那是**探针选错了目的地**，不是产品缺陷。改成从实际候选池
#: 里取，再配不同出发地，才测得到链路本身。
_SEEDS = [
    ("武汉", "婺源", "婺源那一带"),
    ("上海", "黄山", "黄山那一带"),
    ("南京", "婺源", "皖南赣东北方向"),
    ("杭州", "黄山", "徽州方向"),
]

#: 终态：走到这些就算这一轮有结论（成功或明确失败都算）。
_TERMINAL_CHECKPOINTS = {
    "PLAN_OR_PARTIAL_RESULT_READY",
    "NEED_USER_INPUT_OR_EVIDENCE",
    "AUDIT_READY",
}


@dataclass
class RoundResult:
    index: int
    seed: str
    reached_terminal: bool = False
    terminal: str | None = None
    error: str | None = None
    stages: dict[str, float] = field(default_factory=dict)
    events: dict[str, int] = field(default_factory=dict)
    total_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "seed": self.seed,
            "reached_terminal": self.reached_terminal,
            "terminal": self.terminal,
            "error": self.error,
            "stages": {k: round(v, 2) for k, v in self.stages.items()},
            "events": self.events,
            "total_seconds": round(self.total_seconds, 2),
        }


class _Soak:
    def __init__(self, runtime_root: Path, *, budget: float) -> None:
        self.store = InMemoryAgentStore(runtime_root)
        self.application = TripApplicationService(
            store=self.store,
            evidence_broker=EvidenceBroker(runtime_root.parent / "cache"),
        )
        self.query = TripQueryService(
            store=self.store, application_service=self.application
        )
        self.adapter = TripMCPAdapter(self.application, self.query)
        self.budget = budget

    @contextmanager
    def _stage(self, result: RoundResult, name: str):
        started = time.monotonic()
        try:
            yield
        finally:
            result.stages[name] = time.monotonic() - started

    def _count_events(self, run_id: str, result: RoundResult) -> None:
        run = self.store.get_run(run_id)
        counts: dict[str, int] = {}
        for event in self.store.events_after(run.session_id, 0):
            kind = event.event_type
            if kind in {
                "tool.timeout",
                "tool.failed",
                "evidence.parse_failed",
            } or kind.endswith(".timeout"):
                counts[kind] = counts.get(kind, 0) + 1
        result.events = counts

    def _poll(
        self,
        run_id: str,
        result: RoundResult,
        stage: str,
        *,
        accept: set[str],
    ) -> str | None:
        """反复 advance 直到到达 accept 里的检查点，或耗尽预算。"""

        deadline = time.monotonic() + self.budget
        last: str | None = None
        with self._stage(result, stage):
            while time.monotonic() < deadline:
                try:
                    view = self.adapter.advance_trip_task(
                        run_id, wait_seconds=10
                    )
                except TripMCPError as error:
                    result.error = f"{stage}: {error}"
                    return None
                last = str(view.get("checkpoint"))
                if last in accept:
                    return last
                time.sleep(1.0)
        result.error = (
            f"{stage}: 预算 {self.budget:.0f}s 内没走到 {sorted(accept)}，"
            f"最后停在 {last}"
        )
        return None

    def run_round(self, index: int, seed_index: int) -> RoundResult:
        origin, anchor, expression = _SEEDS[seed_index % len(_SEEDS)]
        result = RoundResult(index=index, seed=f"{origin}->{anchor}")
        started = time.monotonic()
        # 日期窗也参数化：不同窗口会命中不同的车次可用性
        offset = 6 + (index % 5) * 2
        nights = 2 + (index % 3)
        intent = {
            "origin": origin,
            "destination_anchor": anchor,
            "destination_expression": expression,
            "earliest_departure_at": _day(offset, "08:00"),
            "latest_return_at": _day(offset + nights, "20:00"),
            "travelers": 2,
            "total_budget_cny": 6000,
            "pace": "relaxed",
            "transport_preferences": ["rail"],
            "themes": ["自然"],
        }
        run_id = ""
        try:
            with self._stage(result, "create"):
                created = self.adapter.create_trip_task(intent)
                run_id = str(created["run"]["run_id"])
            with self._stage(result, "confirm"):
                self.adapter.confirm_trip_intent(run_id)

            checkpoint = self._poll(
                run_id,
                result,
                "compare",
                accept={"CANDIDATES_READY", *_TERMINAL_CHECKPOINTS},
            )
            if checkpoint is None:
                return self._finish(result, run_id, started)

            if checkpoint == "CANDIDATES_READY":
                with self._stage(result, "select"):
                    candidates = self.adapter.read_trip(
                        run_id, view="candidates"
                    )
                    chosen = _first_candidate(candidates)
                    if chosen is None:
                        # 「一个可行候选都没有」是**合法终态**——系统如实说
                        # 到不了，并给放松建议，那正是它该做的。首跑把它算成
                        # 失败，于是探针自己制造了一半的失败率。
                        result.terminal = "NO_FEASIBLE_CANDIDATE"
                        result.reached_terminal = True
                        return self._finish(result, run_id, started)
                    self.adapter.select_trip_candidate(run_id, chosen)

                checkpoint = self._poll(
                    run_id, result, "assemble", accept=_TERMINAL_CHECKPOINTS
                )
                if checkpoint is None:
                    return self._finish(result, run_id, started)

            # **必须推过装配段。** 第一版到 NEED_USER_INPUT_OR_EVIDENCE 就宣布
            # 成功——而那正是链路的一半：真正在第五、六、七次实测里挂掉的
            # 当地交通与行程装配全在它后面。停在这里的 soak 是在自欺。
            #
            # 这里做宿主该做的事：看 missing 给的 pending_actions，把能补的补上，
            # 继续推，直到行程可展示或确实推不动了。
            checkpoint = self._drive_to_plan(run_id, result, checkpoint)
            result.terminal = checkpoint
            result.reached_terminal = result.error is None

            with self._stage(result, "verify"):
                self._verify_probe(run_id, result)
        except Exception as error:  # noqa: BLE001
            result.error = (
                f"未捕获异常 {type(error).__name__}: {error}\n"
                + traceback.format_exc(limit=4)
            )
        return self._finish(result, run_id, started)

    def _drive_to_plan(
        self,
        run_id: str,
        result: RoundResult,
        checkpoint: str,
    ) -> str:
        """补证据 → 继续推，直到行程可展示或推不动。

        顺带把本轮新做的 `missing.pending_actions` 用起来：宿主该怎么知道要补
        什么，这里就怎么知道。它要是不管用，soak 立刻会红。
        """

        with self._stage(result, "supply_and_assemble"):
            for _ in range(6):
                if checkpoint == "PLAN_OR_PARTIAL_RESULT_READY":
                    return checkpoint
                missing = self.adapter.read_trip(run_id, view="missing")
                pending = missing.get("pending_actions") or []
                supplied = False
                for action in pending:
                    domain = str(action.get("submit_action_id") or "")
                    payload = _synthetic_evidence(action)
                    if payload is None:
                        continue
                    try:
                        response = self.adapter.submit_trip_evidence(
                            run_id, payload
                        )
                    except TripMCPError as error:
                        if "下一步" not in str(error):
                            result.error = (
                                f"supply: 拒绝但没给下一步：{error}"
                            )
                            return checkpoint
                        continue
                    if response.get("accepted") is not True:
                        result.error = (
                            f"supply: {domain} accepted="
                            f"{response.get('accepted')} "
                            f"reason={response.get('rejection_reason')}"
                        )
                        return checkpoint
                    supplied = True
                if not supplied:
                    # 没有能自动补的动作了（例如只剩 codex_web_research
                    # 这类必须外部完成的）——这是合法终态。
                    return checkpoint
                nxt = self._poll(
                    run_id,
                    result,
                    "reassemble",
                    accept={"PLAN_OR_PARTIAL_RESULT_READY",
                            *_TERMINAL_CHECKPOINTS},
                )
                if nxt is None:
                    return checkpoint
                checkpoint = nxt
        return checkpoint

    def _submit_probe(self, run_id: str, result: RoundResult) -> None:
        """原样采用公布的 map example，核对 accepted 与解析条数。"""

        try:
            payload = deepcopy(MAP_SEGMENT_EXAMPLE)
            payload["sources"] = [
                {"provider": "soak-probe", "retrieved_at": _now_iso()}
            ]
            response = self.adapter.submit_trip_evidence(
                run_id,
                payload,
            )
        except TripMCPError as error:
            # 被拒是允许的，但必须带理由（本轮新立的规矩）
            if "下一步" not in str(error):
                result.error = f"user_supply: 拒绝但没给下一步：{error}"
            return
        if response.get("accepted") is not True:
            result.error = (
                f"user_supply: accepted={response.get('accepted')} "
                f"reason={response.get('rejection_reason')}"
            )
        elif not response.get("parsed_facts_count"):
            result.error = "user_supply: accepted 但解析出 0 条事实"

    def _verify_probe(self, run_id: str, result: RoundResult) -> None:
        try:
            started = self.adapter.verify_itinerary(
                [
                    {
                        "train_code": "G1234",
                        "origin_station": "上海虹桥",
                        "destination_station": "杭州东",
                        "departure_at": _day(8, "09:00"),
                    }
                ]
            )
        except TripMCPError:
            return
        verify_id = str(started.get("verify_id") or "")
        if not verify_id:
            return
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            view = self.adapter.read_verification(verify_id)
            if str(view.get("status")) in {"completed", "failed"}:
                return
            time.sleep(2.0)
        result.error = "verify: 90 秒内没走到终态"

    def _finish(
        self, result: RoundResult, run_id: str, started: float
    ) -> RoundResult:
        result.total_seconds = time.monotonic() - started
        if run_id:
            try:
                self._count_events(run_id, result)
            except Exception:  # noqa: BLE001
                pass
        if result.error:
            result.reached_terminal = False
        return result


def _synthetic_evidence(
    action: Mapping[str, object],
) -> dict[str, Any] | None:
    """把 missing 公布的 example 原样变成宿主提交。

    **不是在造事实**——soak 要验的是链路走不走得通，不是数据对不对；这些提交
    只把来源标成 `soak-probe`、时间换成当前时刻。value 结构完全来自产品公布的
    example；说明书一旦与机器解析器分叉，soak 与元用例会同时红。
    """

    example = action.get("example")
    if not isinstance(example, Mapping):
        return None
    payload = deepcopy(dict(example))
    payload["sources"] = [
        {"provider": "soak-probe", "retrieved_at": _now_iso()}
    ]
    return payload


def _day(offset: int, clock: str) -> str:
    from datetime import date, timedelta

    return f"{(date.today() + timedelta(days=offset)).isoformat()}T{clock}"


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _first_candidate(view: object) -> str | None:
    raw = view
    if isinstance(view, dict):
        raw = view.get("candidates", view)
    options = raw if isinstance(raw, list) else (
        raw.get("options") if isinstance(raw, dict) else None
    )
    if not isinstance(options, list):
        return None
    for option in options:
        if isinstance(option, dict) and option.get("destination_id"):
            return str(option["destination_id"])
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument(
        "--stage-budget",
        type=float,
        default=180.0,
        help="单个阶段最多等多久（秒）。超过即判这一轮没走到终态。",
    )
    parser.add_argument("--report", type=Path, default=None)
    arguments = parser.parse_args()

    if not os.environ.get("AMAP_WEB_SERVICE_KEY"):
        print("需要 AMAP_WEB_SERVICE_KEY", file=sys.stderr)
        return 2

    from tempfile import TemporaryDirectory

    results: list[RoundResult] = []
    random.seed(20260805)
    with TemporaryDirectory() as temporary:
        soak = _Soak(
            Path(temporary) / "sessions", budget=arguments.stage_budget
        )
        for index in range(1, arguments.rounds + 1):
            result = soak.run_round(index, index - 1)
            results.append(result)
            flag = "OK " if result.reached_terminal else "FAIL"
            print(
                f"[{flag}] 第 {index:>2}/{arguments.rounds} 轮 "
                f"{result.seed:<12} {result.total_seconds:6.1f}s "
                f"终态={result.terminal or '-'} "
                f"{('| ' + result.error.splitlines()[0][:70]) if result.error else ''}",
                flush=True,
            )
            if index < arguments.rounds:
                time.sleep(arguments.interval)

    return _report(results, arguments.report)


def _report(results: list[RoundResult], path: Path | None) -> int:
    failed = [r for r in results if not r.reached_terminal]
    print("\n" + "=" * 62)
    print(f"疲劳报告：{len(results)} 轮，失败 {len(failed)} 轮 "
          f"（失败率 {len(failed) / max(1, len(results)) * 100:.0f}%）")
    totals = [r.total_seconds for r in results]
    if totals:
        ordered = sorted(totals)
        print(f"  整轮耗时 p50={statistics.median(ordered):.1f}s  "
              f"p90={ordered[int(len(ordered) * 0.9) - 1]:.1f}s  "
              f"max={ordered[-1]:.1f}s")
    stage_names = {name for r in results for name in r.stages}
    for name in sorted(stage_names):
        values = sorted(r.stages[name] for r in results if name in r.stages)
        if values:
            print(f"  {name:<12} p50={statistics.median(values):6.1f}s  "
                  f"max={values[-1]:6.1f}s")
    events: dict[str, int] = {}
    for r in results:
        for kind, count in r.events.items():
            events[kind] = events.get(kind, 0) + count
    print(f"  事件计数：{events or '无'}")
    if failed:
        print("\n  挂点分布：")
        buckets: dict[str, int] = {}
        for r in failed:
            key = (r.error or "?").split(":", 1)[0]
            buckets[key] = buckets.get(key, 0) + 1
        for key, count in sorted(buckets.items(), key=lambda kv: -kv[1]):
            print(f"    {key}: {count} 轮")
        print("\n  失败明细（前 5 条）：")
        for r in failed[:5]:
            print(f"    第 {r.index} 轮 {r.seed}: {(r.error or '')[:150]}")
    if path is not None:
        path.write_text(
            json.dumps([r.to_dict() for r in results], ensure_ascii=False,
                       indent=2),
            encoding="utf-8",
        )
        print(f"\n  明细已写入 {path}")
    print("=" * 62)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
