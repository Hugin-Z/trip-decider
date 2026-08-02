# 表征基线翻面预告 v2

> 状态：P4-b2 产出，**翻面执行时的核对物**。取代 v1
> （`p4b-baseline-flip-preview.md`，已作废，正文保留不改）。
> 建立日期：2026-08-02
> 依据：`evidence-axes.md` §3.2、`invariants.md` I5。
> 前置：固定读取时刻已贯通（`6f9a9f7`）。

---

## 0. v1 为什么作废

v1 §0 的 token 表量的是 `tests/invariant_support.py` 的 `controlled_railway()`
（`retrieved_at = 2026-08-01T09:00+08:00`，一天前），而表征的 12 个场景实际用的是
`tests/characterization_support.py` 的 `evidence()`
（`retrieved_at = FRESH_AT = 2026-08-02T18:00+08:00`）。

**两个不同的夹具。** v1 据此推出的「7 场景各 +2 blocker」在真实夹具下不可达：读取时
token 是 `verified`，`token_freshness != stale`，那两条 blocker 永远不会产生。

改造做完跑核对，14 条失配一条没变——这就是负向验证的价值。v1 的预测从未被
「预测对象真的会用这个夹具」验证过。**v2 的每一行都标注它量的是哪个夹具、哪个 now。**

失配三分法据此补第三类：*在 preview 找到出处 / 改造错误 / **基准前提错误***。

## 0.1 v2 的测量条件

| 项 | 取值 |
|---|---|
| 夹具 | `tests/characterization_support.py` 的 `evidence(domain, state)` |
| 采集时刻 | `FRESH_AT = 2026-08-02T18:00:00+08:00`（= 10:00 UTC） |
| 读取时刻 A | `CHAR_NOW = 2026-08-02T11:00:00Z`（FRESH_AT +1h，全部 data_type 窗内） |
| 读取时刻 B | `STALE_NOW = 2026-08-02T17:00:00Z`（FRESH_AT +7h，超铁路 6h 容差） |
| 表征字段 | `decision_point_2_3_planning`（@CHAR_NOW）、`stale_read_planning`（@STALE_NOW） |

## 0.2 分支语义对照

**沿用 v1 §0.2，逐值不变。** v1 错的是 §0 的测量前提，不是映射表。

---

## 1. 实测 token 表

夹具 `characterization_support.evidence("railway", <state>)`，两个 now 各测一次：

| 场景 | 铁路 support | @CHAR_NOW | @STALE_NOW |
|---|---|---|---|
| `all_sourced` | sourced | `verified` | **`sourced_stale`** |
| `map_unknown` | sourced | `verified` | **`sourced_stale`** |
| `map_conflicting` | sourced | `verified` | **`sourced_stale`** |
| `web_unknown` | sourced | `verified` | **`sourced_stale`** |
| `map_estimated` | sourced | `verified` | **`sourced_stale`** |
| `railway_estimated` | estimated | `estimated` | **`estimated_stale`** |
| `all_estimated` | estimated | `estimated` | **`estimated_stale`** |
| `railway_confirmed_absent` | confirmed_absent | `verified` | `sourced_stale` |
| `railway_unknown` | unknown | `unknown` | `unknown` |
| `railway_conflicting` | conflicting | `conflicting` | `conflicting` |
| `all_unknown` | unknown | `unknown` | `unknown` |

## 2. 预期增量

### 2.1 `decision_point_2_3_planning`（@CHAR_NOW）：**零变化**

CHAR_NOW 下没有任何场景的铁路 token 是 stale，`token_freshness == stale` 恒不成立，
两条 blocker 不产生。

**如实写零。** 这一格若出现任何 diff，是改造错误——A 组不该在新鲜证据上产 blocker。

### 2.2 `stale_read_planning`（@STALE_NOW）：**7 场景各 +2**

| 场景 | 预期增量 |
|---|---|
| `all_sourced` | +`RAILWAY_SNAPSHOT_STALE`、+`RAILWAY_AVAILABILITY_UNKNOWN` |
| `map_unknown` | 同上 |
| `map_conflicting` | 同上 |
| `web_unknown` | 同上 |
| `map_estimated` | 同上 |
| `railway_estimated` | 同上 |
| `all_estimated` | 同上 |

### 2.3 阴性对照：4 场景两格皆零变化

| 场景 | 挡在哪里 |
|---|---|
| `railway_unknown` | `_is_usable()` —— support 轴不可用，到不了 snapshot 分支 |
| `railway_conflicting` | 同上 |
| `all_unknown` | 同上 |
| `railway_confirmed_absent` | 确认否定分支先 return —— 它 @STALE_NOW 的 token 确实是 `sourced_stale`，但「已核实无直达车」是确定结论，与新鲜度无关 |

`railway_confirmed_absent` 是最有价值的一条阴性对照：它**有** stale token 却**不该**产
stale blocker。只按 token 判而漏了分支顺序的改法会在这里露馅。

### 2.4 v1 §1.1 三行（已由 `1eda5ea` 提前完成）

`schedule_status` / `fare.status` / `timing_status` 作为回滚哨兵沿用，不该重现。

## 3. 高危项

`full_run_until_plan_installed` 走 `CHAR_NOW`（`set_read_clock` 注入），铁路证据新鲜，
因此**预期零变化**：`run_status=COMPLETED`、`plan_version_written=True`、`plans` 目录非空。

它若翻了，不是「stale 数据阻断安装」（CHAR_NOW 下根本没有 stale），而是改造把新鲜证据
也拦了——纯粹的改造错误。

判据仍在：两条新增 blocker 必须落 `conditional_blockers`。`stale_read_planning` 的
`blockers` 字段取自 `conditional_blockers`，因此 §2.2 的 7 条兑现即证明落点正确。

## 4. 核对流程

1. 按 v1 §0.2 对照表逐值换条件。
2. `python -m tests.flip_check`。
3. 四项全满足：双向零失配 / 阴性对照静默 / 回滚哨兵静默 / 高危三字段不翻。
4. 失配按三分法归因。第三类（基准前提错误）的处置：回退改造、保全现场、停下报告
   ——先例见 v1 的作废过程。
5. 全部对上后才 `--save`。
