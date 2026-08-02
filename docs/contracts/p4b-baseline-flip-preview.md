# 表征基线翻面预告

> 状态：P4-b2 产出，**翻面执行时的核对物**。
> 建立日期：2026-08-02
> 依据：`evidence-axes.md` §3.2（freshness 由读取时刻决定）、`invariants.md` I5。
> 用途：`planning_input_compiler` 的铁路分支从读落盘 `snapshot.status` 改为读取时 token
> 时，整份表征基线会一次性翻面。本文预先写死每个场景的预期增量——翻面时拿实际结果
> 对这份预告，**diff 为零才算翻面正确**。把重刷从一次信任动作变成一次核对动作。

---

## 0. 为什么会翻面

表征夹具的采集时刻是固定字面量，铁路域容差 6 小时：

| 夹具 | domain | `retrieved_at` | 落盘 `snapshot.status` | 读取时 token |
|---|---|---|---|---|
| `controlled_railway` | railway | `2026-08-01T09:00:00+08:00` | `LIVE` | `sourced_stale` |
| `controlled_map` | map | 同上 | 无该键 | `sourced_stale` |
| `controlled_web` | web | 同上 | 无该键 | `sourced_stale` |

**落盘说 LIVE，读取时说 stale。** 这就是 I5 违反的实证：同一份字节，写盘时冻结的判断
与读取时刻算出的判断不一致，而现在的规划器信前者。

夹具时间戳不改。表征夹具的职责是钉住一个已知输入、比对输出漂移，时间戳是输入的一部分；
做成相对 `now` 的活值等于让基线自己会动，那它就不再是基线。

## 0.1 翻面波及范围仅限铁路分支

三个域的 token 都是 `sourced_stale`，但**只有铁路分支会变**：

* `map` / `web` 的编译分支走 `_is_usable()`，判据是 support 轴，与 freshness 无关——
  stale 的 sourced 证据仍然可用，这是两轴正交的正确结果。
* 候选卡上的 `evidence_statuses` token **早已是读取时算的**（P3a 起），基线里已经是
  `sourced_stale`，不在本次翻面范围内。

因此下表只列铁路增量。若翻面后出现任何非铁路的 diff，**那不是预期变化，是改坏了**。

## 0.2 分支语义对照（旧 `snapshot.status` → 新 token 条件）

| 旧分支 | 旧条件 | 新条件 |
|---|---|---|
| `RAILWAY_SNAPSHOT_UNKNOWN` | `snapshot` 不是 Mapping | `token_support(token) == "unknown"` |
| `RAILWAY_SNAPSHOT_STALE` + `RAILWAY_AVAILABILITY_UNKNOWN` | `status == "STALE"` | `token_freshness(token) == "stale"` |
| 余票抹成 `"UNKNOWN"` | `status in {"STALE","UNKNOWN"}` | **无需新条件**，字段级 support 已接住 |
| `fare.status = "stale"` | `status == "STALE"` | `token_freshness(token) == "stale"` |
| `event["schedule_status"] = snapshot_status` | 无条件盖写 | **删除**，改挂 `fact_refs` |

`LIVE` 无对应分支——旧代码里它只是三个 `if` 都不进，新语义下 `freshness == "fresh"` 同样不进。

---

## 1. 逐场景预期增量

判据：铁路证据通过 `_is_usable()` 且读取时 `freshness == stale` 的场景，新增两条 blocker。
未通过 `_is_usable()` 的场景在到达 snapshot 分支前就 return，**不受影响**。

| # | 场景 | 铁路 support | 现有 `rail_event_count` | 预期增量 | 触发 fact |
|---|---|---|---|---|---|
| 1 | `all_sourced` | sourced | 2 | **+`RAILWAY_SNAPSHOT_STALE`**<br>**+`RAILWAY_AVAILABILITY_UNKNOWN`** | `controlled-railway#snapshot.outbound.*` |
| 2 | `all_estimated` | estimated | 2 | 同上 | 同上 |
| 3 | `map_unknown` | sourced | 2 | 同上 | 同上 |
| 4 | `map_conflicting` | sourced | 2 | 同上 | 同上 |
| 5 | `map_estimated` | sourced | 2 | 同上 | 同上 |
| 6 | `web_unknown` | sourced | 2 | 同上 | 同上 |
| 7 | `railway_estimated` | estimated | 2 | 同上 | 同上 |
| 8 | `railway_unknown` | unknown | 0 | **无变化**——`_is_usable` 挡在前面 | — |
| 9 | `railway_conflicting` | conflicting | 0 | **无变化**——同上 | — |
| 10 | `all_unknown` | unknown | 0 | **无变化**——同上 | — |
| 11 | `railway_confirmed_absent` | sourced | 0 | **无变化**——确认否定分支先 return | — |
| 12 | `full_run_until_plan_installed` | sourced | — | 见 §2 | — |

**七个场景各 +2 条 blocker，四个场景零变化。** 任何第三种结果都是异常。

### 1.1 同时预期的字段变化（场景 1-7）

* 每个 rail event 的 `schedule_status` 键**消失**（盖写取消）。
* 每个 rail event 的 `fare.status` 变为 `"stale"`。
* 每个 rail event 新增 `fact_refs`。
* `second_class_availability` 仍为 `"UNKNOWN"`——该值现在由字段级 support 兜底产生，
  不再由 `snapshot_status` 分支产生。**值不变，来源变了**，这一条在表征上看不出差别，
  必须靠显式测试守（见 §3）。

## 2. `full_run_until_plan_installed` 是本次翻面的高危项

该场景断言完整 run 走到计划安装：`run_status=COMPLETED`、`plan_version_written=True`、
`plans/plan-0001.json` 存在。

新增的两条 blocker 若被计入安装闸门，这三项会翻成 `RUNNING` / `False` / 不存在——
**与 P4-a 事故、与批次 3 首次尝试的失败形状完全一致**。

翻面时必须分清两种情况：

* **预期**：blocker 是 conditional 类，不挡安装 → 三项不变，只有 blockers 列表变长。
* **异常**：安装被挡 → 说明 `RAILWAY_SNAPSHOT_STALE` 被归成了硬 blocker。那不是翻面
  的正确结果，是分类错了。stale 的铁路数据应当**降级呈现**而非阻断——它有来源、可回读，
  只是过了容差窗（`evidence-axes.md` §3.3）。

翻面前先确认这两条 blocker 落在 `conditional_blockers` 而非 `blockers`。

## 3. 翻面后必须补的显式测试

`second_class_availability` 的兜底路径现在已经工作（`.get(..., "UNKNOWN")` 的默认值），
但**兜底工作和被测试是两回事**。写哨兵 → 推导 → 消费三段链路要有端到端断言：

1. **写哨兵侧**：`_stale_projection` 把余票写成字面量 `"UNKNOWN"`。
2. **推导侧**：`derive_facts` 把该叶子转成字段级 `support=unknown` 且丢弃旧值。
3. **消费侧**：`usable_fact_values` 不提供该字段，事件上的余票为 `"UNKNOWN"`，
   **且同一条证据的车次时刻仍为 `sourced`**——最后半句是关键，它证明的是字段级
   support 确实做到了 item 级做不到的事。

安排在 `agent_actions` 陈旧投影子批完成后。

## 4. 核对流程

1. 换条件表达式（按 §0.2 对照表逐值换，不许"大概等价"）。
2. 跑 `diff(load_baseline(), capture())`。
3. 拿实际 diff 对本文 §1 的表：**每一条实际变化都要能在表里找到对应行，表里每一行都要
   在实际 diff 里出现**。双向核对，缺一不可。
4. 先确认 §2 的三项未翻。
5. 全部对上后才 `save_baseline`。任何一条对不上，停下来查，不要重刷。
