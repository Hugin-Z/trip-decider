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

* ~~每个 rail event 的 `schedule_status` 键消失（盖写取消）。~~
* ~~每个 rail event 的 `fare.status` 变为 `"stale"`。~~
* ~~每个 rail event 新增 `fact_refs`。~~

上面三条**已在 `1eda5ea` 提前完成**（`timing_status` 退役连带删掉了盖写与
`fare.status`，并挂上了 `fact_refs`），翻面时不应再出现。留删除线而非直接抹去：
核对时若这三项又冒出来，说明退役被回滚了。
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

---

# 5. 补录：翻面范围冻结（`_status` 全仓普查后）

> 补录日期：2026-08-02。依据：全仓 `*_status` 普查（34 处读取点）。
> **本节冻结翻面范围。补录完成后再发现新判定点，属流程失败。**

§1 的表是只按 `planning_input_compiler:323` 一处写的。普查查出同类判定点共 **6 组**，
分属三个模块。逐组的旧判据、新判据与预期增量如下。

## 5.1 已完成、无需补录

| 项 | 结论 |
|---|---|
| `timing_status` 退役 | 已于 `1eda5ea` 完成。表征 **零 diff**——原因见 §6 盲区说明 |

## 5.2 换 token 条件即可覆盖（4 组）

| # | 位置 | 旧判据 | 新判据 | 预期增量 |
|---|---|---|---|---|
| A | `planning_input_compiler:304` | `snapshot.status == "STALE"` | `token_freshness == "stale"` | §1 表：7 场景各 +2 blocker |
| B | `planning_input_compiler:445` | `value.snapshot_status` 盖到事件 | 删除盖写，挂 `fact_refs` | 事件少一字段，**表征看不见**，靠单测守 |
| C | `agent_actions:1727` / `:1749` | `value["freshness"]["status"] == "STALE"` | `token_freshness == "stale"` | 本地交通可采集性判定，见 §5.4 |
| D | `trip_read_model:925` | `web_value["hotel_price_status"] == "UNKNOWN"` | **字段级 support**，非 token | `price_filter_status` 的产出条件换源，值域不变 |

### 5.2.1 C 组与 `guided_discovery:357` 同源

`agent_actions:1727` / `:1749` 读的是 `evidence.value["freshness"]["status"]`——与批次 1
已迁的 `guided_discovery:357` **一字不差**，同一个 I5 违反的第二、第三次出现。

验收可直接复用 `tests/test_guided_discovery_freshness_is_read_time.py` 的三条断言结构：
同一份落盘、两个 `now`、结论必须不同，外加 `collected_at` 不随 `now` 变的对照组。
对照组不可省——没有它，"把两个字段都接到 now"能作弊通过。

### 5.2.2 D 组为什么不走 token

房价字段的 support 是 `unknown` 时，它根本走不到 freshness 那一步——token 是给
"有值、需评估新鲜度"的字段用的。support 轴够用时不要拉 freshness 入伙。

## 5.3 需要裁决：`local_transit_result_status` 可能不是展示态

涉及 `agent_actions:1338` / `:1479` / `:1720` 与 `evidence_broker:343`，共 4 处。

它被 `_is_non_fact_key` 按 `_status` 后缀剪掉，因此走 facts 的消费点读不到它。但它的
取值域是 **`AVAILABLE` / `PARTIAL` / `FAILED`**——那不是 support 轴、不是 freshness 轴，
是**采集结果**。按 `evidence-axes.md` §3.4 与 `persistence-v2.md` §1.4，采集元数据
（`refresh_failure` 那一类）是**可以持久化**的，它不是展示态。

若判定为采集元数据，正确处置不是"换 token 条件"，而是：

1. 从 `_is_non_fact_key` 的 `_status` 后缀规则里豁免它（后缀匹配太粗，误伤了采集元数据）；
2. 四处消费点保持读取，但改从证据的采集元数据区读，不再从 facts 找；
3. 更好的做法是改名去掉 `_status` 后缀（例如 `local_transit_collection_outcome`），
   让机械规则不必开特例——**后缀规则开特例是 M1 的复发路径**。

**这一组在裁决前不动，也不计入 §1 的预期增量。** 若裁决为采集元数据，翻面时它零变化。

## 5.4 高危复核项

C 组改动落在 `_needs_local_transit` / `_can_collect_local_transit`——它们决定要不要再采一次
本地交通。判据从"落盘说陈旧"换成"读取时算出陈旧"后，**采集次数可能变化**：夹具采集于
一天前，读取时恒为 stale，可能触发本不该发生的重采。

翻面时必须确认 `network_calls` 与 `run_status` 不变。这两项若动，不是预期变化。

## 5.5 冻结后的翻面清单

| 组 | 处数 | 预期 |
|---|---|---|
| A | 1 | 7 场景各 +2 blocker（§1 表） |
| B | 1 | 事件少一字段，表征零变化 |
| C | 2 | 见 §5.4，`network_calls` 须不变 |
| D | 1 | 值域不变，产出条件换源 |
| §5.3 | 4 | **待裁决**，暂定零变化 |

---

# 6. 盲区说明：三层守卫各管各的

`timing_status` 退役删掉了每个铁路事件的四个字段，**表征 diff 为零**。原因不是没变，是
表征快照记录的是 `blockers` / `rail_event_count` / `missing_requirements` 这类**判定结果**，
不逐字段记事件内容。

同一个盲区已经出现三次，三个面：

| 现象 | 例子 |
|---|---|
| 值不变、来源变了 | 余票 `"UNKNOWN"` 改由字段级 support 产生，字面量相同 |
| 字段消失、表征看不见 | `timing_status` 等四字段被删 |
| 断言靠巧合成立 | 用 `snapshot_status` 当铁路事件筛选器，"恰好对"是因为恰好只有去返程带它 |

三者是同一个主题：**守卫的语义和守卫的机制没对齐**。结论：

> **表征守判定结果，单测守数据形状，不变式守契约性质。三层各管各的，哪层缺位哪层的变化就静默。**

翻面时凡是预期"表征会响"而实际没响的，先问是不是落进了单测或不变式的辖区，不要当成
"没变"。
