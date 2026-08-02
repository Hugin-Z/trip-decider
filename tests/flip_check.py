"""翻面双向核对器。

`p4b-baseline-flip-preview-v2.md` §4 的可执行形式。把重刷基线从一次信任动作
变成一次核对动作：预期写在 v2 里，这里只负责判决实际与预期是否一致。

v1 已作废——它量错了夹具，预测的增量在真实夹具下不可达。那次失配由本模块的
负向验证抓住，处置记录在 v2 §0。

**双向**，缺一不可：

* 实际 diff 的每一条，都要能在预期表里找到对应行——多出来的是「改坏了」；
* 预期表的每一行，都要在实际 diff 里出现——少掉的是「没改到」。

单向核对能被两种错误蒙混过去，这就是为什么要两个方向。

用法::

    python -m tests.flip_check          # 只判决，不写盘
    python -m tests.flip_check --save   # 零失配时才刷新基线

翻面完成后本模块降级为一次性记录，但执行时它是判决器：它说零失配才能 save。
"""

from __future__ import annotations

import sys

from tests.characterization_support import (
    capture,
    diff,
    load_baseline,
    save_baseline,
)

# 核对基准：v2（前置固定读取时刻 6f9a9f7）。
PREVIEW_BASELINE = "p4b-baseline-flip-preview-v2.md（v1 已作废）"

# v2 §2.2：7 个场景各 +2 条 blocker。
_STALE_BLOCKERS = ("RAILWAY_SNAPSHOT_STALE", "RAILWAY_AVAILABILITY_UNKNOWN")

# v2 §2.2：增量只出现在 stale_read_planning（@STALE_NOW）这一格。
GAIN_FIELD = "stale_read_planning"

# v2 §2.1：CHAR_NOW 下无一场景 token 为 stale，这一格必须零变化。
FRESH_FIELD = "decision_point_2_3_planning"

EXPECTED_GAIN = {
    "all_sourced": _STALE_BLOCKERS,
    "all_estimated": _STALE_BLOCKERS,
    "map_unknown": _STALE_BLOCKERS,
    "map_conflicting": _STALE_BLOCKERS,
    "map_estimated": _STALE_BLOCKERS,
    "web_unknown": _STALE_BLOCKERS,
    "railway_estimated": _STALE_BLOCKERS,
}

# v2 §2.3：四个场景两格皆零变化。railway_confirmed_absent 最有价值——它
# @STALE_NOW 的 token 确实是 sourced_stale，却不该产 stale blocker，因为确认否定
# 分支先 return。只按 token 判而漏了分支顺序的改法会在这里露馅。
EXPECTED_UNCHANGED = frozenset(
    {
        "railway_unknown",
        "railway_conflicting",
        "all_unknown",
        "railway_confirmed_absent",
    }
)

# v2 §2.4 的回滚哨兵三行：已由 timing_status 退役（1eda5ea）提前完成。它们**再次
# 出现**即意味着退役被回滚。
ROLLBACK_SENTINELS = ("schedule_status", "fare.status", "timing_status")

# v2 §3：完整 run 走 CHAR_NOW，证据新鲜，这三项预期零变化。翻了是改造把新鲜
# 证据也拦了——纯粹的改造错误。
CRITICAL_SCENARIO = "full_run_until_plan_installed"
CRITICAL_FIELDS = ("run_status", "plan_version_written", "plans_directory_count")


def _scenario_of(line: str) -> str:
    return line.strip().lstrip("/").split("/", 1)[0]


def check() -> list[str]:
    """返回失配列表。空列表 = 翻面正确。"""

    before, after = load_baseline(), capture()
    actual = diff(before, after)
    mismatches: list[str] = []

    touched: dict[str, list[str]] = {}
    for line in actual:
        if not line.startswith("/"):
            continue
        touched.setdefault(_scenario_of(line), []).append(line)

    # 方向一：实际 -> 预期。多出来的是改坏了。
    for scenario, lines in sorted(touched.items()):
        if scenario in EXPECTED_UNCHANGED:
            mismatches.append(
                f"[阴性对照被触动] {scenario} 预期零变化，实际有 {len(lines)} 条"
                " —— 改的位置不对"
            )
        elif scenario not in EXPECTED_GAIN and scenario != CRITICAL_SCENARIO:
            mismatches.append(
                f"[范围外场景] {scenario} 不在预期表里，实际有 {len(lines)} 条"
            )
        for line in lines:
            if FRESH_FIELD in line:
                mismatches.append(
                    f"[新鲜格被触动] {line.strip()[:70]}"
                    " —— CHAR_NOW 下无 stale token，A 组不该在新鲜证据上产 blocker"
                )

    # 方向二：预期 -> 实际。少掉的是没改到。
    for scenario, blockers in sorted(EXPECTED_GAIN.items()):
        body = "\n".join(
            line for line in touched.get(scenario, ()) if GAIN_FIELD in line
        )
        for blocker in blockers:
            if blocker not in body:
                mismatches.append(
                    f"[预期未兑现] {scenario}.{GAIN_FIELD} 应新增 {blocker}，实际未出现"
                )

    # 回滚探测器：§1.1 那三行不该再冒出来。
    joined = "\n".join(actual)
    for sentinel in ROLLBACK_SENTINELS:
        if sentinel in joined:
            mismatches.append(
                f"[退役被回滚] {sentinel} 重新出现在 diff 里 —— 1eda5ea 被撤销了？"
            )

    # §2 高危项：安装链路不许翻。
    critical = after.get(CRITICAL_SCENARIO, {})
    baseline_critical = before.get(CRITICAL_SCENARIO, {})
    for field in CRITICAL_FIELDS:
        if critical.get(field) != baseline_critical.get(field):
            mismatches.append(
                f"[高危项翻面] {CRITICAL_SCENARIO}.{field}: "
                f"{baseline_critical.get(field)!r} -> {critical.get(field)!r}"
                " —— stale 铁路数据该降级呈现而非阻断，这是分类错误"
            )
    return mismatches


def main(argv: list[str]) -> int:
    mismatches = check()
    print(f"preview 冻结版：{PREVIEW_BASELINE}")
    if mismatches:
        print(f"\n失配 {len(mismatches)} 条：")
        for item in mismatches:
            print(f"  {item}")
        print("\n不要重刷基线。先查失配。")
        return 1
    print("\n双向核对零失配。")
    if "--save" in argv:
        save_baseline(capture())
        print("基线已刷新。")
    else:
        print("加 --save 刷新基线。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
