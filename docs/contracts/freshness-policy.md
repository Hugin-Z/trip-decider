# 新鲜度策略契约

> 状态：生效。本文件是 freshness 轴容忍窗与超窗处理档位的权威定义。
> 建立日期：2026-08-02（P0 阶段产出）
> 前置阅读：`docs/contracts/evidence-axes.md`（两轴模型）、`docs/audit/handover-baseline.md` §3.4 与 §5.3。
> 证据规则：涉及现有代码的陈述给出 `文件:行号`。不确定的标注【待验证】。

---

## 1. 现状：当前实际配置

以下表格逐字读自 `src/trip_decider/evidence_broker.py:38-61` 的 `FRESHNESS_POLICIES`，并补上一列实测的可达性。

| data_type | `stale_ttl_seconds` | 折算 | `stale_allowed` | 产品路径是否实际产出该 data_type |
|---|---|---|---|---|
| `seat_availability` | 0 | — | `False` | **否** |
| `hotel_price` | 0 | — | `False` | **否** |
| `railway_schedule_fare` | 21600 | 6 小时 | `True` | 是 — `evidence_broker.py:299`（`domain == "railway"`） |
| `route_duration` | 21600 | 6 小时 | `True` | 是 — `evidence_broker.py:317`（`domain == "map"` 且 `route_inputs is not None`） |
| `poi_coordinate` | 2592000 | 30 天 | `True` | 是 — `evidence_broker.py:317`（`domain == "map"` 且 `route_inputs is None`） |
| `opening_hours` | 86400 | 24 小时 | `True` | **否** |
| `ticket_price` | 86400 | 24 小时 | `True` | **否** |
| `destination_profile` | 86400 | 24 小时 | `True` | 是 — `evidence_broker.py:302`（`domain == "web"`） |

**可达性的核对方法与结果**：`data_type` 只能由 `query_for_intent_domain()`（`evidence_broker.py:285-336`）赋值，该函数只产出 4 个值（`railway_schedule_fare` / `destination_profile` / `route_duration` / `poi_coordinate`）。`grep '"seat_availability"' src/` 与 `grep '"ticket_price"' src/` 在 `src/` 下均无命中；`"hotel_price"` 在 `src/` 下唯一命中是 `dynamic_discovery.py:416` 的 `"field": "hotel_price"`——那是一个字段名，不是 data_type；`"opening_hours"` 在 `src/` 下的命中（`itinerary_planner.py:592`、`planning_input_compiler.py:604` 等）同样都是字段名。

**结论**：8 个已登记的 data_type 中有 4 个没有生产者。它们的策略配置从未被执行过，因此其取值也从未被验证过。背景决定 4「影响可行性的字段自动重查」在这 4 项上目前无处落地。

**注**：上表描述的是 `src/` 中的**当前**状态，与 §2.2 的目标策略表不同。P1 阶段不修改 `src/`，因此本表在 P5 之前保持不变，仅作为迁移起点。`seat_availability` 已被裁决删除（见 §2.2 注 1），删除动作在 P5 执行。

### 1.1 现状的结构性问题

`stale_ttl_seconds` 一个数字同时承担了两个不同职责：

| 职责 | 使用位置 | 语义 |
|---|---|---|
| 缓存复用上限 | `evidence_broker.py:203-205`：`age > record.stale_ttl_seconds → return None` | 超过多久后，缓存值连作为降级值都不可用 |
| 展示容忍窗 | `evidence_broker.py:367-370`：`expires_at = collected_at + stale_ttl_seconds` | 超过多久后，该值应被标注为陈旧 |

这两件事在语义上不同：一个值可以「已经该标注为陈旧了，但作为降级值仍比没有强」。用一个数字表达两者，等于强制两个阈值相等。新策略把它们拆开。

另有一项与两轴模型直接冲突：`expires_at` 被 `_stale_projection()` 写进证据 value 并随之落盘，属于把容忍窗冻进文件，见 `evidence-axes.md` §3.3。

---

## 2. 新策略配置表

每个 data_type 有六个策略维度：

| 维度 | 含义 | 谁使用 |
|---|---|---|
| `status` | 该登记项的生命周期状态，见 §2.1.1 | I8 的核对程序 |
| `tolerance_seconds` | freshness 判 `fresh` / `stale` 的窗口 | 读取层（每次读取） |
| `max_reuse_seconds` | 缓存值可作为降级值被复用的上限，超过即视为不存在 | 缓存层 |
| `stale_allowed` | 是否允许该类型的陈旧值以任何形式参与输出 | 缓存层 + 可行性判定层 |
| `on_stale` | 超出 `tolerance_seconds` 后的处理档位 | 读取层 |
| `feasibility_critical` | 该类型是否影响可行性判定，判定准则见 §3 | 读取层 + 刷新调度 |

约束：`tolerance_seconds <= max_reuse_seconds`。`stale_allowed == False` 时两者必须同为 0。

### 2.1.1 `status` 取值域

| status | 含义 | I8 反向规则如何处理 |
|---|---|---|
| `active` | 契约要求该类型参与决策，且 `src/` 中已有生产者 | 必须有生产者，否则失败 |
| `planned` | 契约要求该类型参与决策，但生产者尚未实现 | 豁免生产者检查，**但必须携带 `planned_for` 阶段标记** |
| `reserved` | 已登记但当前不要求参与决策 | 豁免生产者检查 |

`planned` 是 2026-08-02 新增的第三态。引入原因：裁决 2 要求 `hotel_price` 保留为契约上的活跃项（价格区间是预算硬约束的必需输入），但它在 `src/` 中确实没有生产者。若归入 `active` 则 I8 反向规则永远失败；若归入 `reserved` 则与「活跃」的裁决语义矛盾。

**补偿控制**：`planned` 项必须携带 `planned_for`（目标阶段），且该阶段闸门必须包含「本阶段的 `planned` 项已转为 `active` 或降为 `reserved`」这一条。没有这条补偿，`planned` 会退化成一个永久豁免的垃圾桶——那正是 I8 反向规则本来要防的事。

**此项为对 `invariants.md` I8 的契约修订，需 Hugin 复核。** 若不接受 `planned`，替代处置是把 `hotel_price` 归入 `reserved` 并接受它暂不参与预算硬约束。

### 2.1 处理档位定义

| 档位 | 行为 | `next_action.kind` | `blocking` |
|---|---|---|---|
| `auto_refetch` | 系统自动发起重查。重查完成前，该事实以 `sourced_stale` 呈现且不得作为无条件可行的依据 | `auto_refetch` | `true` |
| `flag_for_confirmation` | 不重查，仅标注。事实继续参与输出，展示为陈旧态 | `user_confirm` | `false` |
| `block` | 不使用任何缓存值。该事实直接判为 `unknown`，阻断依赖它的可行性结论 | `user_supply` 或 `auto_refetch` | `true` |

`block` 与 `stale_allowed == False` 是同一件事的两个视角：策略层禁止复用，读取层因此拿不到值。

### 2.2 目标配置（权威登记表）

**本表是 data_type 登记的唯一权威来源。** `invariants.md` I8 的核对程序机械解析本表，因此格式受约束：每个数据行以 `` |`<data_type>`| `` 开头，前六个数据列的取值全部用反引号包裹，第七列 `feasibility_critical` 取 `是` / `否`。新增行必须遵守同一格式。

| data_type | status | tolerance_seconds | max_reuse_seconds | stale_allowed | on_stale | feasibility_critical | planned_for |
|---|---|---|---|---|---|---|---|
| `hotel_price` | `planned` | `0` | `0` | `False` | `block` | 是 | P5 |
| `railway_schedule_fare` | `active` | `21600` | `21600` | `True` | `auto_refetch` | 是 | — |
| `route_duration` | `active` | `21600` | `86400` | `True` | `auto_refetch` | 是 | — |
| `poi_coordinate` | `active` | `2592000` | `15552000` | `True` | `flag_for_confirmation` | 否 | — |
| `destination_profile` | `active` | `86400` | `604800` | `True` | `flag_for_confirmation` | 否 | — |
| `opening_hours` | `reserved` | `86400` | `604800` | `True` | `auto_refetch` | 是 | — |
| `ticket_price` | `reserved` | `86400` | `2592000` | `True` | `flag_for_confirmation` | 否 | — |

秒数折算：`21600` = 6 小时；`86400` = 24 小时；`604800` = 7 天；`2592000` = 30 天；`15552000` = 180 天。

**注 1：`seat_availability` 已删除。** 裁决依据：余票属订票域，`PLAN.md` v4 §2 明确「不做订票」。它不再是本产品的 data_type，不出现在本表中。`src/trip_decider/evidence_broker.py:39-41` 中的登记与 `tests/test_evidence_broker.py:35` 中的断言在 P5 一并移除。

**注 2：`hotel_price` 为 `planned`。** 裁决依据：不做订房与比价，但价格区间是预算硬约束的必需输入，因此它必须留在契约里并保持 `feasibility_critical`。当前无生产者，`planned_for = P5`。

**注 3：`opening_hours` 与 `ticket_price` 为 `reserved`。** 二者当前无生产者，且不在任何已裁决的近期范围内。转为 `active` 需要先有生产者。`opening_hours` 的 `feasibility_critical` 保留为「是」——景点开放时间直接决定活动能否排入某一天，一旦有生产者档位即生效。

**制定依据**

- 全部 `tolerance_seconds` 保持现有 `stale_ttl_seconds` 的取值。现状的数值没有已知的错误证据，本阶段不改动；改动需要真实运行数据支撑，属 P5 之后。
- `max_reuse_seconds` 是新维度。取值原则：坐标类事实变化极慢，复用窗可远大于容忍窗；价格类事实的陈旧值有误导性，复用窗不放宽。5 项新引入数值按裁决 6 执行，**标记为可调**——它们没有实测支撑，P5 拿到真实运行数据后应复核。
- `poi_coordinate` 定为非 critical：坐标用于渲染与距离估算，坐标陈旧不会翻转可行性结论。但它是 `route_duration` 的输入，若坐标本身 `unknown`，`route_duration` 会按聚合规则（`evidence-axes.md` §2.4）继承 `unknown` 并因此阻断——阻断由 `route_duration` 承担，不由坐标承担。

### 2.3 未登记 data_type 的默认值

新增 data_type 若未在本表登记，读取层必须拒绝，不得使用默认值。理由：静默默认会让新数据源以未定义的新鲜度语义进入决策。`evidence_broker.py:79-80` 的 `EvidenceQuery.__post_init__` 已对走缓存的路径实施了这一约束（`data_type not in FRESHNESS_POLICIES` 直接报错），新策略把它扩展到全部读取路径。可机械核对形式见 `invariants.md` I8。

---

## 3. 「影响可行性」的判定准则

背景决定 4 把刷新分成两档，档位取决于该字段是否影响可行性。这个判断必须是可机械套用的，否则新增 data_type 时会退化成逐条拍脑袋。

### 3.1 准则（规范定义）

> 一个 data_type 是 `feasibility_critical`，当且仅当：它产出的任一字段，出现在**至少一个可行性判定点**的输入闭包中。

**可行性判定点**指其输出会改变以下三者之一的代码位置：

| # | 输出 | 载体 |
|---|---|---|
| 1 | 候选的 `feasibility_status` | `guided_discovery._coarse_option` 中对 `feasibility_status` 的赋值 |
| 2 | 计划的 `planning_state` | `planning_input_compiler.compile` 中对 `planning_state` 的赋值 |
| 3 | `conditional_blockers` 中任一 blocker 的存在与否 | `planning_input_compiler` 中的 `_blocker(...)` 调用，逐条见 §3.1.1 |
| 4 | **候选进不进结果集**（准入过滤，能力 A v0 新增） | `reachability` 中的 `Reachability(...)` 构造，逐条见 §3.1.1 |

**第 4 类是新形态。** 前三类的输出都是「给这个对象什么结论」，对象始终在结果集里；第 4 类的输出是「这个对象还在不在」。它同样改变可行性结论——一个被过滤掉的目的地，其可行性对用户而言就是「不可行」——因此必须登记，否则 §3.2 的闭包分析会漏掉整条准入路径。对应的「不静默」要求见 `invariants.md` I7 第 4 条。

**清单以「函数名 + blocker_id」为键，行号只作参考、不作判据。** 上一版把 16 个行号写进契约，一次重构之后**无一命中**、处数也从 17 变成 18——行号是最先过期的那种数字（D1）。函数名与 blocker_id 跟着语义走，重构时要么不变，要么变了就是真的换了语义。

判定点清单本身是本契约的一部分。**新增可行性判定点必须同步更新本节**——这一条现在由 `tests/test_feasibility_decision_points.py` 机械核对，清单与代码不一致即红。

### 3.1.1 判定点登记表（权威）

本表被 `tests/invariant_support.parse_decision_point_registry()` 机械解析，
格式受约束：每个数据行以 `` |`<函数名>`| `` 开头，第二列是反引号包裹的
`blocker_id`（f-string 拼接的部分写成 `{}`），第三列是语义描述。

| 函数 | blocker_id | 语义 |
|---|---|---|
| `_coarse_option` | `feasibility_status` | 候选粗可行性结论本身（判定点 1，非 blocker） |
| `compile` | `planning_state` | 计划准入结论本身（判定点 2，非 blocker） |
| `compile` | `HARD_CONSTRAINT_CONFLICT_{}` | 硬约束冲突逐条转 blocker |
| `_compile_railway` | `RAILWAY_INPUT_UNAVAILABLE` | 铁路输入不能据以推进（不可用 / 无 facts / unknown / 过期四支） |
| `_compile_railway` | `RAILWAY_NO_DIRECT_TRAIN` | 已核实该窗内无直达车（确定结论，非「没查到」） |
| `_compile_railway` | `RAILWAY_SEAT_NOT_GUARANTEED` | 余票不保证，指向余票字段本身 |
| `_compile_railway` | `RAILWAY_{}_MISSING` | 该方向排不出车次事件 |
| `_compile_local_transit` | `MAP_INPUT_UNAVAILABLE` | 当地交通输入不能据以推进 |
| `_compile_local_transit` | `LOCAL_TRANSIT_DURATION_MISSING` | 该段路线没有可用时长 |
| `_compile_attractions` | `WEB_INPUT_UNAVAILABLE` | 景点输入不能据以推进 |
| `_compile_attractions` | `ATTRACTION_RETAINED_UNSCHEDULED` | 景点保留但排不进时间轴 |
| `_compile_attractions` | `ATTRACTION_TRANSIT_MISSING` | 景点缺进出交通衔接 |
| `_compile_defaults` | `HOTEL_SELECTION_MISSING` | 未选住宿，用片区兜底 |
| `_compile_defaults` | `HOTEL_DETAIL_PENDING` | 已有片区但未定具体酒店 |
| `_record_evidence_blockers` | `{}_INPUT_UNAVAILABLE` | 按域补记的输入不可用（与上面三处同 id，由 `_unique_blockers` 收敛） |
| `assess_reachability` | `railway_not_collected` | 该域根本没采（判定点 4） |
| `assess_reachability` | `railway_support_{}` | 车次证据的 support 不可准入（unknown / conflicting） |
| `assess_reachability` | `railway_duration_unavailable` | 有车次但拿不到往返时长，算不出净可玩时长 |
| `assess_reachability` | `net_playable_below_threshold` | 净可玩时长低于阈值（裁决 5） |
| `assess_reachability` | `admitted` | 准入结论本身（判定点 4，非 blocker） |

**为什么不钉调用点处数**：同一个 `(函数, blocker_id)` 目前对应 1–4 个调用点
（`_compile_railway` 的 `RAILWAY_INPUT_UNAVAILABLE` 有 4 支）。同一函数里为同一个
blocker 多开一个分支，不改变「可能出现哪些可行性结论、从哪来」，那正是本节要
登记的东西；把处数钉死只会让每次分支重构都产生一次假红，然后被人改数字了事
——那就退回成一个没人看的计数。

### 3.2 机械核对程序

```
输入：一个 data_type D
1. 枚举 D 产出的 value 中被下游读取的字段名集合 F（从该 provider 的出口函数返回体读出）
2. 对 §3.1 表中每个判定点 P：
   a. 计算 P 的输入闭包（P 直接读取的字段，加上这些字段的传递依赖）
   b. 若 F ∩ closure(P) ≠ ∅ → 返回 True
3. 全部判定点不命中 → 返回 False
```

### 3.3 快速判据（与 §3.2 一致，用于人工预判）

若无法立即做闭包分析，用以下充分条件预判，结论需事后用 §3.2 验证：

- 该字段参与任何**数值不等式比较**（时间窗、预算上限、开放时间区间、体力上限）→ `critical`。
- 该字段只参与**展示、排序或标注** → 非 `critical`。

### 3.4 兜底规则

无法判定时默认 `feasibility_critical = True`。理由：误判为 critical 的代价是多做一次重查；误判为非 critical 的代价是让陈旧数据静默支撑一个「可行」结论——后者正是本产品要消灭的失败模式（`PLAN.md` v3:74，v4 保留为红线）。

---

## 4. PlanVersion 的性质变更

### 4.1 现状

`travel_agent.py:941-989` 的 `persist_plan_version()` 把整个 plan 深拷贝落盘（`:976` `deepcopy(dict(plan))`）。实测 `runtime/sessions/f4d3aec8-.../plan-version.json`（129,188 字节）中包含的展示态字段：

| 字段 | 取值 | 出现次数 |
|---|---|---|
| `timing_status` | `estimated` | 71 |
| `support` | `estimated` | 14 |
| `timing_status` | `sourced_stale_snapshot` | 6 |
| `schedule_status` | `STALE` | 6 |
| `snapshot_status` | `STALE` | 6 |
| `evidence_status` | `LIVE` | 5 |
| `schedule_status` | `LIVE` | 5 |
| `display_status` | `DISPLAYABLE_CONDITIONAL_ITINERARY` | 1 |

也就是说，当前的 PlanVersion 是**某一时刻全部展示判断的冻结快照**。这份文件在 2026-08-01 写入，此后无论过多久读取，里面的 `LIVE` 都还是 `LIVE`。

### 4.2 新性质

**PlanVersion = 行程结构 + 对事实的引用。不含任何展示态，不含任何 freshness 派生值。**

| 允许持久化 | 禁止持久化 |
|---|---|
| 天数、每天的活动序列、活动间的先后关系 | 任何 token（`verified` / `sourced_stale` / …） |
| 每个活动引用的 `fact_id` 集合 | 任何 `*_status` 展示字段（`evidence_status` / `schedule_status` / `snapshot_status` / `timing_status` / `display_status`） |
| 时长分配、预算分摊等结构性决策 | `freshness.status`、`freshness.expires_at` |
| 用户显式做出的选择（锁定的活动、必去项） | `displayable`、`planning_state`（见 §4.4） |
| `support`（可持久化轴，`evidence-axes.md` §1） | `next_action`（读时产出） |

`support` 是唯一允许出现在持久化文件里的证据状态维度。上表中现存的 `"support": "estimated"` ×14 因此可以保留——但它当前来自 `itinerary_planner.py:160-170` 的规划器默认值契约，与两轴的 support 是否同义【待验证】。

### 4.3 对读取路径的要求

| # | 要求 | 理由 |
|---|---|---|
| R1 | 读 PlanVersion 时必须把全部 `fact_id` 引用解析到当前证据，重算 support 聚合与 freshness，再渲染 | 结构是冻结的，事实不是 |
| R2 | 引用解析失败（证据不存在、或超出该 data_type 的 `max_reuse_seconds`）必须产出 `unknown` + `next_action`，**不得回落到任何文件内的旧值** | 否则 §4.1 的冻结快照问题会以另一种形式复现 |
| R3 | 同一个 PlanVersion 在不同时刻读取，**结构部分必须逐字节稳定，展示部分允许变化** | 这是「结构冻结、事实重算」的可测形式，见 `invariants.md` I5 |
| R4 | token 计算必须由唯一实现完成，读取路径不得自带映射 | 见 `invariants.md` I6 |
| R5 | 读取层必须能报告「这个 PlanVersion 现在还成不成立」，且该结论每次读取重算 | 取代 §4.4 的持久化 `planning_state` |

### 4.4 与现有安装闸门的冲突

`b120894` 建立的 PlanVersion 安装闸门依赖三个持久化字段：

- 写入侧：`travel_agent.py:954-968` 校验 `planning_state ∈ {PARTIAL_READY, PLAN_READY}`、`plan.artifact_kind == "PlanVersion"`、`plan.displayable is True`。
- 读取侧：`trip_query.py:311-318` 用同样三项作为准入硬条件。

`planning_state` 与 `displayable` 都是「当前证据够不够展示」的判断结果，属于展示态派生物。按硬规则它们不得落盘，这意味着 b120894 建立的闸门机制整体需要重做为读时重算（R5）。

同一处还有一个独立缺陷：基线报告 H1 记录，该格式变更没有版本号也没有迁移，导致此前所有 run 的 PlanVersion 被判为不存在。P4 处理落盘契约时必须同时给出版本标记方案，否则会第二次制造同类问题。

---

## 5. 与刷新调度的关系

背景决定 4 的分层刷新在本契约中的落点：

| 情形 | 档位 | 谁触发 |
|---|---|---|
| `feasibility_critical == True` 且 `freshness == stale` | `auto_refetch` | 系统 |
| `feasibility_critical == False` 且 `freshness == stale` | `flag_for_confirmation` | 无（仅标注） |
| `stale_allowed == False` 且缓存中有值 | `block` | 系统必须实采，实采失败即 `unknown` |

现状与之的差距：

- STALE 只在实采失败后产生（`evidence_broker.py:177-206` 的 `stale_after_failure()`，且 `:186-189` 断言必须先有一次失败的实采）。这一点与新策略一致，不需改动。
- 但**没有任何主动重查触发器**。当前 STALE 一旦产生就一直是 STALE，直到下一次有人手动重跑。MCP 面甚至没有重试入口（基线报告 H4：`retry_action` 只存在于 HTTP 面 `product_web.py:536-549`）。`auto_refetch` 档位在 P5 之前无处落地。
- `_stale_projection()` 返回的 `EvidenceItem` 未传 `missing_reason`（`evidence_broker.py:437-443`），导致陈旧证据对外的 `missing_reason` 恒为 `null`（基线报告 §5.3 实证）。新模型下这个信息应进入 `next_action.reason_code = beyond_tolerance_window`。

### 5.1 触发时机：读取时同步重查（2026-08-03 裁决）

§6 未决 4 的三选一，取第一个。理由：

- **本地单进程产品没有可靠的「之后」。** 异步排队与「仅在下次推进时」都要求一个「之后会发生」的承诺，而用户关掉进程就没有之后了——那两档会退化成「永远不重查」，比不做还糟，因为它们看起来像做了。
- **与整个模型同构。** freshness 读时算，重查读时触发；`retry_after_at` 从「调度器预计下次跑的时刻」改为**节流阀**语义（见下），防读取风暴。
- **实现面最小。** 判定已收敛到唯一漏斗（`evidence_projection.project_domain` 是 `evaluate_fact` 的唯一调用者）。

执行约束：

| 项 | 规定 |
|---|---|
| 触发条件 | `freshness == stale` ∧ `feasibility_critical` ∧ `on_stale == auto_refetch` |
| 节流 | `next_action.retry_after_at` **此刻之前不再触发重查**。语义变更见 `evidence-axes.md` §5.2 |
| 预算 | 单次读取的重查总预算有超时上限；超预算按现有 stale 降级，**不阻塞读取** |
| 失败 | 走 `stale_after_failure` 既有兜底。它**不是触发器**（入口即断言实采已失败），是触发后失败路径的承接 |
| 成功 | 新证据入 store，freshness 重算，token 相应变化 |

### 5.2 落点归因：判定点唯一，替换点不唯一（2026-08-03 实测）

**实现未落地，原因记录在此。** P5 轮 1 的结论「落点已收敛到唯一漏斗
`project_domain`」**仍然成立，但只覆盖判定**：`evaluate_fact` 至今只有
`project_domain` 一个调用者，「这份证据算不算 stale」确实只有一处答案。

轮 2 实施时查出**上一轮没问的第二个问题**：那个漏斗是不是**动手**的可行位置。
不是。`project_domain` 的调用方拿同一份 evidence mapping 做的事远不止取 token：

| 调用点 | token 之后还用同一份 evidence 做什么 |
|---|---|
| `planning_input_compiler.py:380` → `:416` | `usable_fact_values(item_facts(evidence))` 建全部车次事件、票价、`fact_refs` |
| `trip_read_model.py:255` | verdict 与 `evidence_value(domain)` 各读各的 |
| `trip_query.py:285` | 只覆盖候选条目的 `token` / `next_action`，其余字段原样保留 |

若在 `project_domain` 内部重采，**token 反映新数据而下游全部字段仍是旧的**——
计划会一边宣称 `verified` 一边用过期车次拼出来。那比不重查更坏：I5 与 R2 要防的
正是「结论与它所依据的数据不同步」。

因此重采必须发生在**证据被任何消费方读到之前**，一次替换整份证据，而不是在取
token 的那一瞬间。这是「第二个触发点」，触及停点规则，故停下报。

### 5.2.1 读取入口清单（**契约**，2026-08-03 收敛后）

**新增读取入口必须同步本表**，同 §3.1 判定点清单的先例。入口 4 已按裁决收敛掉
（它不是入口，是读取层的活干在了错误的层，见 §5.3 的作废记录）。

| # | 入口 | 证据容器 | 解析步装载点 |
|---|---|---|---|
| 1 | `TripQueryService.trip()` | `run.result["context"]["evidence"]` | 经 `plan_verdict_from_result` |
| 2 | `TripQueryService.candidates()` | `evidence/guided-comparison.json` | `_with_recomputed_tokens` |
| 3 | `TripQueryService.plan_readiness()` | `run.result["context"]["evidence"]` | `plan_verdict_from_result` |

`agent_actions.get_next_actions()` 经 `plan_verdict_from_result` 拿结论，**不碰
证据容器**，因此不是入口。`map_payload()` / `missing_information()` 委托给
`trip()`。

**逻辑一份、装载点两个**：容器有两种是落盘历史造成的事实（容器统一记 P5 后
待办），重采与替换的逻辑只写在 `evidence_projection.resolve_stale_evidence`
一处，两个装载点各自只负责容器形状与写回位置（D5/D20）。

### 5.2.2 已实现与未实现（2026-08-03）

**已实现**：解析步本体、触发判定（仍走 `project_domain`）、节流、预算、
失败降级、两个装载点、全套守卫（原子性 / 两条 D6 / 不对称 / 一致性）。

**写回已决并落地（2026-08-03 裁决）**：解析步返回「重采结果 + **待写回标记**」，
读取层**不落盘**，写回由 `TripApplicationService.record_refetched_evidence`
执行——它走的就是动作循环一直在用的 `state.evidence` + `_persist_loop_state`，
不是新开的通道。理由：读取层写盘会破它的只读契约，也会让两次读取产生不同的
文件内容（I5）；写入则本就该经唯一协调者（`record_result` 先例）。

**成功与失败都写回**：失败写 `refresh_failure.attempted_at`，节流的状态就存在
它上面——不写回则节流永远空转，一个挂掉的数据源会被每次页面刷新反复捶打。

仍未接生产采集器：`TripQueryService(refetcher=...)` 默认 `None`，产品路径当前
不会真的重采。这一条与下面的副本问题绑在一起，一并裁决。原先记录的契约冲突
（已由上述裁决解决，保留为归因）：

- 解析步的替换是**内存内**的，读完即弃。下次读取拿到的还是旧证据，于是**每次
  读取都会重采一遍**；
- 要跨读取生效（以及让节流真正工作——节流状态存在持久化的
  `refresh_failure.attempted_at` 上），重采结果必须**落盘**；
- 而 `evidence_projection` 的模块契约是「只读不写」，读取层写盘还会让两次读取
  产生不同的事件数，直接违反 I5 的「结构逐字节稳定」。

三个选项：(a) 重采后由**应用层**（非读取层）落盘，读取层只返回「该落什么」；
(b) 接受内存内语义，节流改用进程内缓存（进程重启即失效）；(c) 把重采移出读取
路径，回到排队模型——那等于推翻 §5.1 的裁决。**建议 (a)**：它保住读取层只读，
也保住 I5，代价是应用层要多一个「读取产生的证据更新」入口。

### 5.2.3 证据有三份副本，写回只对一份生效（**停点，待裁决**）

实现写回时实测发现的，**与「容器有两种」的既有认知冲突**：证据在盘上是**三份**
独立副本，同 `evidence_id`、不同文件、不同对象。

| | 容器 | 谁写 | 谁读 |
|---|---|---|---|
| A | `run.result["context"]["evidence"]` | planner 动作产出 result 时**快照一次** | `plan_readiness`、`get_next_actions`（经 `plan_verdict_from_result`） |
| B | `evidence/current.json` | 动作循环每次 `_persist_loop_state` | `current_run_evidence` → `trip()` |
| C | `evidence/guided-comparison.json` | 比较阶段 | `candidates()` |

**本轮的写回走 B。** 因此 `trip()` 的重采跨读取生效、节流真工作（已验），
而 `plan_readiness` 读的是 A——一份**在 planner 时刻冻结的快照**，写回对它无效，
每次读取都会重采一遍。

这正是 D19 的形状：同一份数据落多处，而没有任何地方写着谁是权威、写入顺序、
不一致时怎么办。A 与 B 目前靠「都从同一个 `state.evidence` 写出」保持一致，
那是运气不是保证——一旦有一条写入路径只更新其中一份（本轮的写回就是），
两份立刻分叉。

**三个方案，待裁决**：

1. **A 收敛进 B**（建议）：`plan_verdict_from_result` 的证据来源改为读 B，
   `result["context"]` 不再携带证据副本、只留 intent 与结构。与 P4「不冻结读时
   状态」同向，也消灭这份副本。代价：动了 `result.context` 的落盘形状，牵动
   `persistence-v2.md` §2.1 与表征。
2. **写回同时更新 A 和 B**：改动最小，但把「两份可以不一致」固化成设计，D19
   明确反对。
3. **声明 A 为编译输入的权威**、B 只服务展示：需要写清两者何时允许不同，
   且 `plan_readiness` 的重采仍然无处落盘。

**按停点规则停在这里**：修复面牵动落盘契约与表征，超出单点。

### 5.3 读取入口普查（2026-08-03 实测，作废记录）

**本节保留为「为什么入口不是两个」的论证。** 结论已并入 §5.2.1。

§5.2 末尾原本提议「在读取层入口（`candidates` / `plan_readiness`）加解析步」。
轮 3 开工前按要求做入口普查，**那个提议是错的：入口不是两个，是四个。**
提议因此作废，清单先记在这里，等落点方案定了再契约化。

| # | 入口 | 证据来源 | 消费方式 |
|---|---|---|---|
| 1 | `TripQueryService.trip()`（`trip_query.py:103`） | `current_run_evidence()` | → `_presentation_contract`（`trip_read_model.py:753/763`）与 `_map_payload_contract`（`:255`）。**这是主读面**，HTTP `GET /api/trips/{id}` 走它 |
| 2 | `TripQueryService.candidates()`（`:163`） | **`evidence/guided-comparison.json`**，与其余三个入口不同源 | → `_with_recomputed_tokens`（`:285`） |
| 3 | `TripQueryService.plan_readiness()`（`:293`） | `run.result["context"]` | → `PlanningInputCompiler.compile`（`planning_input_compiler.py:380`） |
| 4 | `agent_actions.get_next_actions()`（`:433`） | `run.result["context"]` | → `_result_is_displayable` → `recomputed_planning_state`（`:1836`）→ 同一个 compile |

`map_payload()` / `missing_information()` 委托给 `trip()`，不是独立入口；
`product_web` 虽然 import 了读模型的几个函数，实际不调用，也不是入口。

两条会影响方案的性质：

- **入口 2 与其余三个不同源。** 候选卡读的是比较阶段单独落的
  `guided-comparison.json`，不是 `run.result` 里的 context。一个「整份替换」
  的解析步得覆盖两种证据容器，不是一种。
- **入口 4 在 `agent_actions` 里，不在读取层。** 它是动作循环的快照接口，
  却在内部按读取时刻重算 planning_state。要么解析步也进那里（那就不止一处
  落点），要么承认它是一条不吃 auto_refetch 的读路径——那样同一份证据在
  `plan_readiness` 与 `get_next_actions` 会给出不同结论，比不做更糟。

**命令路径另记**：`trip_application.select_hotel`（`:322`）也直读证据业务字段
（`hotel_candidates`），但它吃的是 `destination_profile`
（`feasibility_critical == 否`，`on_stale == flag_for_confirmation`），
不在 auto_refetch 的触发条件内，本轮不牵动。

---

## 6. 未决问题

| # | 问题 | 状态 |
|---|---|---|
| 1 | §2.2 中 5 项 `max_reuse_seconds` 的具体取值 | **已决**（裁决 6，2026-08-02）：按建议值执行，标记为可调，P5 拿到真实运行数据后复核 |
| 2 | 4 个无生产者的 data_type 是保留还是删除 | **已决**（裁决 2，2026-08-02）：`seat_availability` 删除（属订票域）；`hotel_price` 保留且为 `planned`（价格区间是预算硬约束输入）；`opening_hours` 与 `ticket_price` 标记 `reserved` |
| 3 | `itinerary_planner.py:160-170` 的 `"support": "estimated"` 与两轴 support 是否同义 | **已核对**（P1，见 `docs/contracts/support-reclassification.md` §4）：不同义，是规划器默认值的自描述字段，与证据 support 无关 |
| 4 | `auto_refetch` 的触发时机（读取时同步重查 / 异步排队 / 仅在下次推进时） | **已决**（裁决，2026-08-03）：**读取时同步重查**。理由见 §5.1。**实现未落地**，落点归因见 §5.2 |
| 5 | PlanVersion 落盘契约的版本标记方案 | 未定，P4 决定 |
| 6 | `status` 三态（含新增的 `planned`）与 I8 反向规则的修订 | **待 Hugin 复核**，见 §2.1.1。这是 P1 为解决裁决 2 与 I8 的冲突所做的契约修订 |
