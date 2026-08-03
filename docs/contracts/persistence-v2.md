# 落盘契约 v2 规格

> 状态：**已确认**（2026-08-02）。裁决见 §13，第二步实施按 §14 的顺序执行。
> 建立日期：2026-08-02
> 范围：`runtime/` 下全部产物。
> 前置：`evidence-axes.md`、`freshness-policy.md` §4、`invariants.md` I1/I5/I6、`p3b-gate-inventory.md` §8.3（结论值原则）。
> 边界：本文件是规格，不是改动。除 P3b 的 `schema_version` 尾巴外，本步骤不改代码。

---

## 0. 一句话

**v2 把落盘内容收敛为「事实 + 结构 + 引用」三类，删掉全部展示态。** 展示态一律读时由 `evidence_core` 计算——这是 I1 的定义，也是本次改造的唯一主线。

规模：一次全新 run 当前落盘 **476 处** I1 禁用字段（实测，分布见 §3）。v2 之后应为 0。

---

## 1. 通用规则

### 1.1 三类可落盘内容

| 类 | 判据 | 例 |
|---|---|---|
| **事实** | 采集当时确定、写入后不再变化 | `support`、`retrieved_at`、`sources[]`、`value`、`conflict_details[]`、`refresh_failure` |
| **结构** | 人或算法做出的决策，与证据新鲜度无关 | 天数、活动序列、时长分配、用户锁定项 |
| **引用** | 指向事实的标识符 | `fact_id`、`evidence_id` |

不属于这三类的一律不落盘。展示态（token、`*_status`、`displayable`、`planning_state`）是「读时由事实算出的结论」，不是事实本身。

### 1.2 `schema_version`

| 项 | 规定 |
|---|---|
| 位置 | 每个 JSON 文件的**顶层**；`events.jsonl` 每行一个 |
| v2 取值 | `2` |
| 无该字段 | 按 `1` 处理（`travel_agent.runtime_schema_version()`） |
| 打标点 | `travel_agent.stamp_schema_version()`，三个原子写函数统一走它 |

**已知冲突**：`evidence/namespace.json` 有一个**自己的** `schema_version: 1`，语义是「命名空间格式版本」，与本契约的运行时版本同名不同义。v2 必须改名其一。**建议**把命名空间的改为 `namespace_format_version`，因为运行时版本是跨文件统一概念，占用通名更合理。

### 1.3 字段级 `support`（P3a 问题 4 的落点）

**v1 的 `support` 是 item 级的**：`EvidenceItem.status` 一个值管整条证据。这表达不了「时刻可靠、余票未知」——`_stale_projection` 把余票抹成 `UNKNOWN` 但整条仍是 `sourced`。

**v2 改为字段级**：证据的 `value` 不再是裸 mapping，而是 `fact` 的集合，每个 fact 独立携带 `support` / `data_type` / `retrieved_at`。

```
{
  "evidence_id": "railway-live-query",
  "domain": "railway",
  "schema_version": 2,
  "facts": [
    {
      "fact_id": "fact_rail_outbound_departure_at",
      "field": "outbound.departure_at",
      "value": "2026-08-04T13:00",
      "support": "sourced",
      "data_type": "railway_schedule_fare",
      "retrieved_at": "2026-08-04T09:00:00+08:00",
      "sources": [{"provider": "中国铁路12306", "url": "...", "retrieved_at": "..."}]
    },
    {
      "fact_id": "fact_rail_outbound_availability",
      "field": "outbound.second_class_availability",
      "value": null,
      "support": "unknown",
      "reason": "refresh_failed",
      "data_type": "seat_availability_removed",
      "retrieved_at": "2026-08-04T09:00:00+08:00"
    }
  ],
  "refresh_failure": {"missing_reason": "rail_http", "attempted_at": "..."}
}
```

**item 级 `status` 的去留**：保留为**派生的便捷字段**，取值为全部 fact 按 `evidence-axes.md` §2.4 聚合的结果，且**必须可由 facts 重算**。理由：29 处闸门刚在 P3b 统一到 `EvidenceStatus.is_usable`，直接删掉会把它们全部推倒重来。v2 保留它但把权威性移到 facts——一致性由新不变式守（§11.4）。

**这是本规格里改动面最大的一项**，`value` 的形状变了，全部生产者与消费者都受影响。

### 1.3.1 `retrieved_at` 归一规则

**2026-08-02（P4-b）裁决。** v1 有三种放法——`value.retrieved_at`、
`value.snapshot.retrieved_at`、`sources[].retrieved_at`——读取端按优先级依次找
（`evidence_projection._retrieved_at`）。字段级 facts 之后必须归一，否则同一条
证据的不同字段拿到的采集时刻取决于查找顺序而不是事实。

| 层 | 规定 |
|---|---|
| **fact 级** `facts[].retrieved_at` | **权威，每个 fact 必带**。同一条证据的不同字段**可以**有不同采集时刻——这正是字段级的动机 |
| **source 级** `sources[].retrieved_at` | **保留**（`SourceRef` 本就有）。表示**该来源**的采集时刻；多来源时各自独立 |
| item 级 / `value` 内嵌的其他放法 | **全部废除**。读取端不再识别 `value.retrieved_at`、`value.snapshot.retrieved_at`、`value.freshness.retrieved_at` |

**fact 级与 source 级的关系**：一个 fact 由一个或多个 source 支撑。fact 的
`retrieved_at` 是该 fact 被确定下来的时刻；source 的是那次外部调用返回的时刻。
单来源时两者通常相等，多来源时 fact 级取哪一个由生产者决定并写死——读取端不
再推断。

**为什么不只留一层**：只留 fact 级会丢掉「这条来源是什么时候取的」，多来源冲突
时无法判断谁更新；只留 source 级则回到 v1 的查找顺序问题。两层各自回答不同的
问题，都要留。

### 1.4 `refresh_failure`

已由 P3b 前置修正转正为契约字段（`evidence-axes.md` §3.4），v2 规范其位置：

| 项 | 规定 |
|---|---|
| 位置 | 证据对象顶层，与 `facts` 同级。**不再放在 `value` 里** |
| 形状 | `{"missing_reason": <reason_code>, "attempted_at": <ISO-8601 或 null>}` |
| v1 的四种形状 | `value.refresh_failure`（两种）、`value.local_transit_refresh_failure`、事件 detail 里的字符串——全部归一到上面一种 |
| I1 白名单 | 保留（采集元数据，非展示态） |

#### 1.4.1 采集元数据清单

`refresh_failure` 不是唯一一个。同族字段一并登记——它们**可以持久化**，不受 I1 约束，
也不进 facts（不是关于世界的事实，是关于采集过程的记录）：

| 字段 | 取值域 | 说明 |
|---|---|---|
| `refresh_failure` | `{missing_reason, attempted_at}` | 刷新失败，封顶 freshness 为 stale（§3.4） |
| `local_transit_outcome` | `AVAILABLE` / `PARTIAL` / `FAILED` | 本地交通采集结果 |

`local_transit_outcome` 原名 `local_transit_result_status`。P4-b2 改名，因为
`_status` 后缀让 `_is_non_fact_key` 按**拼写**把它当展示态剪掉了——它的三个取值不属于
任何一个轴，是采集过程的记录。

**规则：采集元数据按名字登记在本表，不靠后缀匹配识别。** 后缀是拼写，分类是语义；
让机械规则去猜语义，猜错时的修法只有开特例，而特例是 M1「四套词表」的复发路径。

---

## 2. 逐文件 v2 规格

### 2.1 `run.json`

**v1 顶层**：`run_id / session_id / intent / status / created_at / confirmed_at / started_at / completed_at / parent_run_id / revision / error_code / result / schema_version`

**v2 变化**：

| 字段 | 处置 |
|---|---|
| 除 `result` 外全部顶层字段 | **保留**。它们是运行事实与结构 |
| `status`（`RunStatus`） | **保留**。这是运行生命周期状态，不是证据展示态——`AWAITING_CONFIRMATION/RUNNING/...` 与 token 无关 |
| `result.plan` | **改为引用形态**，见 §5.1 |
| `result.context.evidence[]` | **改为 §1.3 的 facts 形状** |
| `result.planning_state` | **删除**。读时重算，见 §6 |
| `result.planning_draft.display_status` / `displayable` | **删除** |
| `result.context.evidence` | **删除，改为 `evidence_refs`**（2026-08-03 裁决「A 收敛进 B」，**已落地**）。与 `plan-NNNN.json` 同形，两条写入路径共用 `travel_agent.trimmed_context`。证据的权威容器是 `evidence/current.json` |
| `error_detail` | **P5 轮 2 新增顶层字段**（`str \| None`）。只存逃出来的异常类名。与 `error_code` 是两段式的两段：码收敛为有限词表（`travel_agent.RUN_ERROR_CODES`，15 个取值），类型名挪到这里，取值域因此从「每个可能的异常类名」变回可穷举。I1 白名单已登记理由（失败时刻的事实，非展示态）。**读侧兼容**：旧文件无此键，缺省 `None`；旧 `error_code`（`EXECUTOR_TRAVELAGENTERROR` 之类）照常读回，不校验——校验只在写入口 `fail()` / `block()` |

### 2.1.1 A 收敛进 B 的改动面（**已完结**，2026-08-03 轮 9）

裁决：`run.result["context"]["evidence"]`（容器 A）删除，读取改经
`evidence/current.json`（容器 B）。理由见 `freshness-policy.md` §5.2.3——
A 与 B 目前靠「都从同一个 `state.evidence` 写出」保持一致，那是运气不是保证，
读时重采的写回已经是第一条只更新其中一份的路径（D19）。

**范围钉死**：只收 A。容器 C（`guided-comparison.json`）的独立性另有裁决，
容器统一是 P5 后待办，本次不动。

**写入点（3 处）** —— 都要改成写 `evidence_refs` 而非内联证据：

| 位置 | 说明 |
|---|---|
| `agent_actions._planner_handler`（`:1130`） | A 的源头，`context.to_dict()` 整份带证据落进 result |
| `itinerary_planner.revise_generic_plan`（`:2429`/`:2466`） | 重排路径把 `previous_result["context"]` 原样传下去 |
| `travel_agent` 的 revision executor（`:2306`） | 同上 |

**读取点（4 处）** —— 都要改成从 B 取证据：

| 位置 | 现状 | 切换后 |
|---|---|---|
| `planning_input_compiler.compile`（经 `plan_verdict_from_result`） | 读 `payload["evidence"]` | 由调用方注入 B |
| `trip_read_model._map_payload_contract`（`:225`） | 从 context 建 `evidence` | 加 evidence 参数 |
| `trip_read_model._presentation_contract`（`:738`） | **同时**有 `evidence=` 参数（B）与 context 派生的一份 | 删掉 context 派生那份 |
| `itinerary_planner.validate_destination_plan`（`:2298`/`:2353`，经 `revise_generic_plan`） | 读 context 内联证据 | 重排路径要能拿到 B |

**一个结构性缺口，必须先决**：**`user_input` 域只存在于 A，B 里没有。**
`state.evidence` 的键是动作域（railway / web / map），而编译器要
`evidence.get("user_input")` 来算 `plan_refs.intent_window` 与 `user_evidence`
（事件的 `fact_refs` / `evidence_dependencies` 都指它）。

建议：**读时从 `run.intent` 重建**。它本来就是 intent 的投影而不是采集来的证据
——`_planner_handler` 里就是 `EvidenceItem(evidence_id="confirmed-travel-intent",
domain="user_input", value=intent.to_dict())` 现造的。重建即可，顺带再消灭一份
副本。**此项待批**。

**完结记录（2026-08-03）**：读取侧 4 点、写入侧 3 点全部落地，`user_input`
改为从 `run.intent` 重建。守卫：`test_read_entrances_do_not_fork`（两面读同一份）、
`test_context_trimming_is_one_shape`（两处裁剪同形）、
`test_revision_chain_after_convergence`（A12 链路）、
`test_persisted_round_trip_keeps_verdicts`（往返对象改为容器 B，含恒真检查）。

**裁剪必须幂等**：重排链路会把上一版（已裁剪的）context 再传一遍，无条件覆盖
`evidence_refs` 会在第二次裁剪时把它清空。实现用 `setdefault`——这条是
`test_context_trimming_is_one_shape` 第一次跑就抓到的真 bug。

**表征实测：零 diff。** 与预期的「会响」不同，原因是 `result.context` 不在表征
快照的取值范围内——表征取的是判定结论（planning_state / blockers / token），
而收敛只改证据的存放位置，不改任何结论。这正是 D7 说的「先问这类变化归哪层管」：
形状变更归单测与往返守卫，不归表征。

**当前 I1 命中：150 处**（`timing_status`×110、`schedule_status`×14、`evidence_status`×9、`snapshot_status`×8、`planning_state`×3、值类若干）。

### 2.2 `action-loop.json`

**v1 顶层**：`action_status / result / fallback_result`

**v2 变化**：

| 字段 | 处置 |
|---|---|
| `action_status` | **保留**。`waiting/completed/blocked` 是动作调度状态，不是证据态 |
| `result` / `fallback_result` | 内部同 `run.json` 的 `result` 处置 |

**当前 I1 命中：155 处——最多的一个文件。** 因为它内嵌了完整的 `result`，与 `run.json` 高度重复。

**建议**：`action-loop.json` 只存 `action_status`，`result` 改为引用 `run.json`。这消除一份完整副本，同时把 155 处里的 152 处一次清掉。**待确认**：这改变了崩溃恢复的语义（当前两份独立，任一可单独重建）。

### 2.3 `plan-version.json` 与 `plans/plan-NNNN.json`

**v1 顶层**：`run_id / plan_version / planning_state / plan / context`

**v2 顶层**：

```
{
  "schema_version": 2,
  "run_id": "...",
  "plan_version": 9,
  "structure": { ... },          // 天数、活动序列、时长分配、锁定项
  "fact_refs": ["fact_...", ...] // 该 PlanVersion 依赖的全部事实
}
```

| 字段 | 处置 |
|---|---|
| `planning_state` | **删除**。读时重算（§6） |
| `plan.display_requirements` | **保留**（结构：用户要求展示什么） |
| `plan.days[].events[].timing_status` | **删除**（55 处/文件，最大单一来源） |
| `plan.days[].events[].snapshot_status` / `schedule_status` | **删除** |
| `plan.conditional_blockers` | **改名并引用**，见 §7 |
| `context.evidence` | **删除**。改为 `fact_refs`，读时解析 |

**当前 I1 命中：各 77 处**（两文件内容相同）。

### 2.4 `evidence/current.json`

**v1 顶层**：`run_id / current[] / last_sourced[] / schema_version`

**v2 变化**：

| 字段 | 处置 |
|---|---|
| `current[]` / `last_sourced[]` | 每项改为 §1.3 的 facts 形状 |
| `last_sourced` 键名 | **改名 `last_usable`**。P3b 已把判据从 `sourced` 改为 `is_usable`（含 `estimated`），键名名实不符 |

**当前 I1 命中：6 处**。

### 2.5 `evidence/guided-comparison.json`

**v1 顶层**：`version: 1 / destinations / schema_version`

**v2 变化**：

| 字段 | 处置 |
|---|---|
| `version: 1` | **删除**。与 `schema_version` 重复，是同一件事的两个字段 |
| `destinations{}` | 每个 domain 的证据改为 facts 形状 |

**当前 I1 命中：3 处**。

### 2.6 `events.jsonl`

**v1 每行**：`sequence / event_id / session_id / run_id / event_type / status / message / occurred_at / details`

**v2 变化**：

| 字段 | 处置 |
|---|---|
| 前 8 个字段 | **保留**。事件是已发生事实的记录 |
| `details.evidence_status` / `details.snapshot_status` | **删除**。改为 `details.fact_refs[]` |
| `details` 里的 token 值（实测 `verified`×4） | **删除** |

**当前 I1 命中：8 处**。

**注**：`events.jsonl` 是 append-only 的历史记录，删除历史行不可行。v2 只约束**新写入的行**；旧行由 `schema_version` 区分。

### 2.7 `session.json`

**v1 顶层**：`session_id / created_at / run_ids / current_run_id`

**v2 变化**：只加 `schema_version`。**当前 I1 命中 0 处**——它本来就只存结构。

### 2.8 `evidence/namespace.json`

**v2 变化**：把自有的 `schema_version` 改名 `namespace_format_version`（§1.2）。命中 0 处。

### 2.9 `evidence-cache/records.json`

**v1**：`schema_version: "1"`（注意是字符串）、records 里嵌 `EvidenceItem.to_dict()`。

**v2 变化**：

| 字段 | 处置 |
|---|---|
| `schema_version` | 改为整数 `2`，与其余文件统一类型 |
| `records[].evidence` | 改为 facts 形状 |
| `_stale_projection` 写入的 `value.freshness.status` / `expires_at` | **删除**（`evidence-axes.md` §3.3） |
| `value.refresh_failure` | **上移到证据顶层**（§1.4） |

---

## 3. 删除项总表：476 处如何清零

实测一次全新 run 的 I1 命中分布：

| 文件 | 命中 | 主要字段 |
|---|---|---|
| `action-loop.json` | 155 | `timing_status`×110、`schedule_status`×14、`evidence_status`×9、`snapshot_status`×8、`planning_state`×3 |
| `run.json` | 150 | 同上（内嵌同一份 result） |
| `plan-version.json` | 77 | `timing_status`×55、`schedule_status`×7、`evidence_status`×5、`snapshot_status`×4、`planning_state`×2 |
| `plans/plan-0001.json` | 77 | 同上 |
| `events.jsonl` | 8 | token 值×4、`evidence_status`×3 |
| `evidence/current.json` | 6 | `LIVE`×4、`evidence_status`×2 |
| `evidence/guided-comparison.json` | 3 | `LIVE`×2、`evidence_status`×1 |
| **合计** | **476** | |

### 3.1 按写入侧模块归因（I6 豁免的 7 个模块，48 处字面量）

P3b 后从 55 降至 **48 处**（`guided_discovery` 由 12 降至 5）。逐模块给出「落到哪个字段」与「v2 如何消失」：

| 模块 | 处数 | 字面量 | 落盘字段 | v2 如何消失 | 信息有损？ |
|---|---|---|---|---|---|
| `itinerary_planner.py` | 10 | `LIVE`×4 `STALE`×4 `sourced_live_snapshot`×1 `sourced_stale_snapshot`×1 | `plan.days[].events[].timing_status` | **删除**。事件改为携带 `fact_refs`，时刻可靠性读时由所引事实的 token 算出 | **无损**。`timing_status` 的四个取值全部可由 (support, freshness) 重算 |
| `agent_actions.py` | 10 | `STALE`×9 `LIVE`×1 | `value.snapshot.status`、`value.{outbound,return}.schedule_status` / `fare_status`、`hotel_price_status` | **删除**。`snapshot.retrieved_at` 保留为事实 | **部分有损**：`second_class_availability = "UNKNOWN"` 承载的是「该字段本身不可知」，v2 改由**字段级 support = unknown** 承载（§1.3）。这是字段级 support 的主要动机 |
| `intercity_rail.py` | 9 | `LIVE`×5 `STALE`×4 | `value.snapshot.status`、`snapshot.display` | **删除**。`snapshot.display`（人类可读文案）一并删除，改由 `next_action.detail` 读时生成 | **无损**。`availability_semantics` 承载的语义由字段级 support 表达 |
| `planning_input_compiler.py` | 7 | `STALE`×3 `LIVE`×2 `DISPLAYABLE_CONDITIONAL_ITINERARY`×1 `SUPPLEMENTING_DATA`×1 | `PlanningDraft.display_status`、`displayable` | **删除**。安装闸门改读时重算（§6） | **无损**。两个取值是 `planning_state` 的二值投影，可重算 |
| `evidence_broker.py` | 6 | `STALE`×6 | `_stale_projection` 写入的 `value.freshness.status`、各 `*_status` | **删除**。`refresh_failure` 上移顶层（§1.4）承担全部信息 | **无损** |
| `guided_discovery.py` | 5 | `MISSING`×4 `STALE`×1 | 候选卡 `evidence_statuses[].token`、`roundtrip_transport.token` | **删除**。候选卡改 `fact_id` 引用（§5.2） | **无损** |
| `dynamic_discovery.py` | 1 | `LIVE`×1 | `value.evidence_status` | **删除** | **无损** |

**唯一有损项是 `agent_actions` 的 availability 抹除**，迁移落点已明确：字段级 support。这也是 §1.3 必须做的原因——不做它，这条信息无处安放。

---

## 4. 新增项

| 新增 | 位置 | 来源 |
|---|---|---|
| `facts[].support` | 每个 fact | §1.3，P3a 问题 4 |
| `facts[].data_type` | 每个 fact | freshness 计算的必需输入；v1 只存在于 `EvidenceQuery`，不随事实落盘 |
| `facts[].retrieved_at` | 每个 fact | 字段级新鲜度。同一 domain 内不同字段可有不同采集时刻 |
| `facts[].reason` | `support == unknown` 时 | `evidence-axes.md` §2.3 |
| `facts[].conflict_details` / `conflict_source_refs` | `support == conflicting` 时 | 同上 |
| `refresh_failure` | 证据顶层 | §1.4 |
| `fact_refs[]` | PlanVersion、事件 details、blocker | §5 |
| `schema_version` | 每文件顶层 | §1.2 |

---

## 5. 引用结构

### 5.1 PlanVersion

权威定义是 `freshness-policy.md` §4.2 的允许/禁止表，本节只补落盘形状与读取契约。

**读取路径按 R1–R5**，其中 **R2 是硬要求**：

> 引用解析失败（事实不存在、或超出该 data_type 的 `max_reuse_seconds`）必须产出 `unknown` + `next_action`，**不得回落到任何文件内的旧值**。

落法：读取层解析 `fact_refs[]` 时，**PlanVersion 文件里根本没有可回落的值**——结构里只有引用，没有事实副本。R2 因此由数据形状保证，而不是靠代码自律。这是把 R2 做成结构约束而非纪律约束的关键。

**R3（结构逐字节稳定）** 由 §1.1 的三分类保证：结构部分不含任何随 `now` 变化的内容。

**R5（读时报告该 PlanVersion 现在还成不成立）** 由 §6 承担。

### 5.2 候选卡 options（P3b 遗留 2 的终局）

**v1**：`result.options[].evidence_statuses[].token` —— P3b 为让 I3a 转绿，在**写入时**算了 token 并落盘。这本身是 I1 违规，当时记为遗留。

**v2**：

```
"options": [
  {
    "destination_id": "...",
    "structure": { ...(seed 派生字段、结构性决策)... },
    "fact_refs": {
      "railway": ["fact_rail_..."],
      "map": ["fact_map_..."],
      "web": ["fact_web_..."]
    }
  }
]
```

`trip_query.candidates()` 读时解析 `fact_refs`，走 `evidence_projection` 算 token 与 `next_action`。`guided_discovery._coarse_option` 不再产出任何 token，`build_guided_comparison` 的 `clock` 参数随之可删（它是 P3b 为让写入时定级可测而加的）。

**这一步同时清掉 §3.1 里 `guided_discovery` 的 5 处字面量。**

---

## 6. 安装闸门读时重算方案

**v1 现状**：

| 侧 | 位置 | 依赖 |
|---|---|---|
| 写入 | `travel_agent.py:954-968` | 校验 `planning_state ∈ {PARTIAL_READY, PLAN_READY}`、`plan.artifact_kind == "PlanVersion"`、`plan.displayable is True` |
| 读取 | `trip_query.py:311-318` | 同样三项作为准入硬条件 |

三项全是展示态派生物，v2 全部不落盘，因此两侧都要改。

### 6.1 替代判定的输入

`planning_state` 的原始判据在 `planning_input_compiler.py:216-227`，输入是：

| 输入 | v2 来源 |
|---|---|
| 各域证据是否可用 | 解析 PlanVersion 的 `fact_refs`，走 `evidence_projection.project_domain` 得 token |
| 是否有阻断级 blocker | 读时重算：`next_action.blocking` 为真的事实数 > 0 |
| 结构完整性（天数、事件数） | PlanVersion 的 `structure`，本来就落盘 |

### 6.2 替代判定的位置

| 侧 | v2 方案 |
|---|---|
| **写入侧**（`travel_agent.py:954-968`） | **取消状态校验，改为结构校验**：只验 `structure` 完整（有 `plan_version`、`fact_refs` 非空、`structure.days` 非空）。「够不够格安装」不再是写入时的判断——写入时不知道读取时的 `now` |
| **读取侧**（`trip_query.py:311-318`） | **新增 `TripQueryService.plan_readiness(run_id, now)`**，返回 `(planning_state, blockers)`。`_current_plan_payload` 用它的返回值做准入 |

### 6.3 这个改动的副作用

**「已安装」不再是一个持久事实，而是一个读时结论。** 同一个 PlanVersion 在证据过期后会从 `PLAN_READY` 变成 `COLLECTING_EVIDENCE`——这正是两轴模型想要的（计划的成立性随证据新鲜度变化），但它改变了「安装」这个词的含义。

**建议**在 v2 里把词分开：**「已写入」**（结构落盘成功，永久事实）与 **「当前可用」**（读时结论）。`plan_version` 编号表示前者，`plan_readiness` 表示后者。

---

## 7. blocker 家族清理清单

**命名原则**（`p3b-gate-inventory.md` §8.3 / `evidence-axes.md` §5.5）：

> 表达规划层后果 + `fact_id` 引用，不复述证据状态。

**已于 P4-c 第 5 批执行。执行结果见 §7.4——本节 §7.1/§7.2/§7.3 是规格拟定时
的清单，其中的行号与 21 → 11 两组数字均出自 P3b 之前的普查，已过时**（P3b 之后
新增过 `RAILWAY_SNAPSHOT_STALE` / `RAILWAY_AVAILABILITY_UNKNOWN` 等，且原普查
漏了 `HARD_CONSTRAINT_CONFLICT_{n}` 与 `RAILWAY_{方向}_MISSING` 两族）。裁决理由
仍以本节为准，落地清单以 §7.4 为准。

### 7.1 动态族（`planning_input_compiler.py:1001-1012`）

| 旧名 | 触发条件 | v2 新名 | 引用 |
|---|---|---|---|
| `{DOMAIN}_OMITTED` | 该域证据不存在 | **删除**，并入下一行 | — |
| `{DOMAIN}_MISSING` | `status == "missing"` | **`{DOMAIN}_INPUT_UNAVAILABLE`** | `fact_refs: [该域全部 fact_id]` |
| `{DOMAIN}_CONFLICTING` | `status == "conflicting"` | **删除**，并入上一行 | 同上 |

三个合并为一个的理由：**规划层的后果是同一个**——「这个域没有可用输入，规划无法据此推进」。至于是没采到、采到了打架、还是压根没这个域，是**证据层的区分**，由消费方顺着 `fact_id` 读 token 得知。这正是原则要消灭的复述。

`{DOMAIN}` 取 `RAILWAY` / `MAP` / `WEB` 三值，因此实际是 3 个 blocker_id 取代 9 个。

### 7.2 静态 12 个

| 旧名 | v2 处置 | 新名 | 引用 |
|---|---|---|---|
| `RAILWAY_EVIDENCE_MISSING`（P3b 新增） | **改名** | `RAILWAY_INPUT_UNAVAILABLE` | 铁路域 fact_id |
| `RAILWAY_SNAPSHOT_UNKNOWN` | **删除**。复述证据态 | 并入 `RAILWAY_INPUT_UNAVAILABLE` | — |
| `RAILWAY_SNAPSHOT_STALE` | **删除**。复述 freshness | 并入 `RAILWAY_INPUT_UNAVAILABLE` | — |
| `RAILWAY_AVAILABILITY_UNKNOWN` | **改名** | `RAILWAY_SEAT_NOT_GUARANTEED` | 余票字段的 fact_id |
| `RAILWAY_NO_DIRECT_TRAIN`（P3b 新增） | **保留**。已符合原则 | 不变 | 已带 `fact_id` |
| `LOCAL_TRANSIT_EVIDENCE_MISSING` | **改名** | `MAP_INPUT_UNAVAILABLE`（并入动态族） | map 域 fact_id |
| `LOCAL_TRANSIT_DURATION_MISSING` | **保留**。表达规划后果（算不出通勤时间） | 不变 | 加 `fact_id` |
| `ATTRACTION_EVIDENCE_MISSING` | **改名** | `WEB_INPUT_UNAVAILABLE`（并入动态族） | web 域 fact_id |
| `ATTRACTION_TRANSIT_MISSING` | **保留**。规划后果 | 不变 | 加 `fact_id` |
| `ATTRACTION_RETAINED_UNSCHEDULED` | **保留**。纯规划结论 | 不变 | — |
| `HOTEL_SELECTION_MISSING` | **保留**。规划后果 | 不变 | 加 `fact_id` |
| `HOTEL_DETAIL_PENDING` | **保留**。规划后果 | 不变 | 加 `fact_id` |

### 7.3 净变化

| 项 | v1 | v2 |
|---|---|---|
| 动态族 | 9（3 域 × 3 态） | 3（3 域 × 1） |
| 静态 | 12 | 8 |
| **合计** | **21** | **11** |

删掉的 10 个全部是「复述证据状态」的那一类。**全部保留项都要加 `fact_id`**——引用是原则的另一半，只改名不加引用等于把信息丢了。

### 7.4 执行结果（P4-c 第 5 批，2026-08-03）

普查以 `_blocker(` 调用点为准，实测 17 处调用、17 种 `blocker_id`（含两处
`f"..."` 动态拼接）。**目标数字不预设，原则执行完剩几个就是几个。**

| 旧 `blocker_id` | 调用点 | 处置 | 新 `blocker_id` | 引用 |
|---|---|---|---|---|
| `HARD_CONSTRAINT_CONFLICT_{n}` | `:170` | 保留 | 不变 | — |
| `RAILWAY_EVIDENCE_MISSING` | `:294`、`:311` | 改名 | `RAILWAY_INPUT_UNAVAILABLE` | 铁路 |
| `RAILWAY_NO_DIRECT_TRAIN` | `:322` | 保留 | 不变 | 铁路（原有） |
| `RAILWAY_SNAPSHOT_UNKNOWN` | `:334` | 删，并入 | `RAILWAY_INPUT_UNAVAILABLE` | 铁路 |
| `RAILWAY_SNAPSHOT_STALE` | `:339` | 删，并入 | `RAILWAY_INPUT_UNAVAILABLE` | 铁路 |
| `RAILWAY_AVAILABILITY_UNKNOWN` | `:341` | 改名 | `RAILWAY_SEAT_NOT_GUARANTEED` | 铁路 |
| `RAILWAY_{OUTBOUND,RETURN}_MISSING` | `:356` | 保留 | 不变 | 铁路 |
| `LOCAL_TRANSIT_EVIDENCE_MISSING` | `:401` | 改名，并入动态族 | `MAP_INPUT_UNAVAILABLE` | map |
| `LOCAL_TRANSIT_DURATION_MISSING` | `:413` | 保留 | 不变 | map |
| `ATTRACTION_EVIDENCE_MISSING` | `:498` | 改名，并入动态族 | `WEB_INPUT_UNAVAILABLE` | web |
| `ATTRACTION_RETAINED_UNSCHEDULED` | `:570` | 保留 | 不变 | 景点来源 |
| `ATTRACTION_TRANSIT_MISSING` | `:640` | 保留 | 不变 | map |
| `HOTEL_SELECTION_MISSING` | `:739` | 保留 | 不变 | web |
| `HOTEL_DETAIL_PENDING` | `:744` | 保留 | 不变 | web |
| `{DOMAIN}_OMITTED` | `:1055` | 删，并入 | `{DOMAIN}_INPUT_UNAVAILABLE` | —（无证据可指） |
| `{DOMAIN}_MISSING` | `:1059` | 改名 | `{DOMAIN}_INPUT_UNAVAILABLE` | 该域 |
| `{DOMAIN}_CONFLICTING` | `:1066` | 删，并入 | `{DOMAIN}_INPUT_UNAVAILABLE` | 该域 |

**终态 12 种**（`RAILWAY_OUTBOUND_MISSING` 与 `RAILWAY_RETURN_MISSING` 算一族，
展开为 13 个字面量）：`HARD_CONSTRAINT_CONFLICT_{n}`、`RAILWAY_INPUT_UNAVAILABLE`、
`RAILWAY_NO_DIRECT_TRAIN`、`RAILWAY_SEAT_NOT_GUARANTEED`、
`RAILWAY_{方向}_MISSING`、`MAP_INPUT_UNAVAILABLE`、`LOCAL_TRANSIT_DURATION_MISSING`、
`WEB_INPUT_UNAVAILABLE`、`ATTRACTION_RETAINED_UNSCHEDULED`、
`ATTRACTION_TRANSIT_MISSING`、`HOTEL_SELECTION_MISSING`、`HOTEL_DETAIL_PENDING`。

两处与 §7.2 的差异，理由如下：

1. **`ATTRACTION_RETAINED_UNSCHEDULED` 加了引用**，§7.2 原写「—」。它虽是纯规划
   结论，但「哪个景点」这件事有确定来源（该景点所属的证据项），§7.3「全部保留项
   都要加 `fact_id`」优先。
2. **表外两族按同一原则现场归类**：`HARD_CONSTRAINT_CONFLICT_{n}` 的冲突来自
   `context.hard_constraint_conflicts`，不是证据项，无可指的事实，保留且不加引用
   （同 §7.2 对纯规划结论的处理）；`RAILWAY_{方向}_MISSING` 说的是「该方向排不出
   车次事件」，与 `LOCAL_TRANSIT_DURATION_MISSING` 同类——是规划后果，不是在复述
   某个 support 取值，故保留并补引用。

**引用粒度**：本轮补的 `fact_id` 一律是**该域证据的 `evidence_id`**，沿用 `:302`
与 `:325` 两处既有先例，不是 `evidence_core.fact_id()` 生成的
`<evidence_id>#<field>`。字段级引用属第 4 批（PlanVersion 引用化）的范围，本轮
不改引用形状。§7.2 中「余票字段的 fact_id」因此暂按域级引用落地。

**相邻词表**：`run.error_code` 不是 `blocker_id`，不在本节范围。本节写下时它被
记为「未改动」，**P5 轮 2 已按同一条命名原则收敛**——见 §2.1 的 `error_detail`
行与 `travel_agent.RUN_ERROR_CODES`。当时举的三个例子里，
`WEB_EVIDENCE_REQUIRED` 已改名 `CODEX_ACTION_REQUIRED`，
`*_ACTION_STALLED` 有意保留。

---

## 8. 历史 run 处置执行方案

**已裁决：不迁移。** 本节给出执行动作。

| 项 | 方案 |
|---|---|
| **范围** | `runtime/sessions/` 下全部 session 目录（基线报告实测 56 个，当前需重新计数） |
| **清理方式** | **整目录删除**，不做逐 run 判断 |
| **存档副本** | **不留**。理由：基线报告 H6 已实测确认这批数据**无法归因到任何 commit**（`catalog_seed_notice` 在 135 个 commit 中都不存在），留档也无法复现产生它们的代码，档案价值为零 |
| **例外** | `runtime/evidence-cache/records.json` 一并删除。它是跨 run 缓存，v1 形状，保留会让 v2 读取端撞上 v1 记录 |
| **执行时机** | v2 实施**之前**。先删后改，避免中途出现半 v1 半 v2 的目录 |
| **可重入** | 删除后首次运行会重建目录（`InMemoryAgentStore.__init__` 的 `mkdir`），无需手工创建 |

**README 声明文字**（建议原文）：

> **运行数据不向后兼容。** `runtime/` 下的运行记录采用 `schema_version` 标记格式版本。v2（2026-08-02，落盘契约移除全部展示状态字段）与 v1 不兼容，且不提供迁移——v1 时期的运行数据无法归因到确定的代码版本（见 `docs/audit/handover-baseline.md` H6），迁移它们没有可验证的正确性标准。升级到 v2 前请自行备份或直接删除 `runtime/`。

---

## 9. `DEFAULT_AGENT_STORE` 惰性化（基线 M8）

**现状**（`travel_agent.py:1661-1664`）：

```python
_DEFAULT_RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "runtime" / "sessions"
DEFAULT_AGENT_STORE = InMemoryAgentStore(_DEFAULT_RUNTIME_ROOT)
```

两个问题：**import 即 `mkdir` + 全量读盘**；`parents[2]` 假定源码在 `<repo>/src/trip_decider/`，装成 wheel 后指向 site-packages 的上两级。

引用点 26 处，全部是默认参数（`store: InMemoryAgentStore = DEFAULT_AGENT_STORE`）。

### 9.1 方案：显式工厂 + 哨兵默认值

```python
_DEFAULT_STORE: InMemoryAgentStore | None = None

def default_agent_store() -> InMemoryAgentStore:
    """返回进程级默认 store，首次调用时才建目录读盘。"""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = InMemoryAgentStore(default_runtime_root())
    return _DEFAULT_STORE

def default_runtime_root() -> Path:
    """runtime 根目录。环境变量优先，其次仓库相对路径。"""
    override = os.environ.get("TRIP_DECIDER_RUNTIME_ROOT")
    return Path(override) if override else Path.cwd() / "runtime" / "sessions"
```

26 个引用点改法：`store: InMemoryAgentStore | None = None`，函数体首行 `store = store or default_agent_store()`。

### 9.2 为什么不用模块级 `__getattr__` 懒加载

PEP 562 的 `module.__getattr__` 能让 `DEFAULT_AGENT_STORE` 保持字面不变而延迟构造。**不采用**，两个理由：

1. 默认参数在**函数定义时**求值，`def f(store=DEFAULT_AGENT_STORE)` 会在 import 该模块时触发 `__getattr__`——延迟不了。26 个引用点全是这种形态。
2. 它把「这里有 I/O」藏起来了。显式工厂让调用点看得见。

### 9.3 路径改为 `Path.cwd()` 的后果

`parents[2]` 换成 `cwd`，意味着**从不同目录启动会用不同的 runtime**。这是行为变化，需要：脚本入口（`scripts/run_product.ps1` 等）显式设置 `TRIP_DECIDER_RUNTIME_ROOT` 或声明工作目录。**待确认**：是否接受这个约束，替代方案是保留仓库相对路径但用 `importlib.resources` 定位。

### 9.4 验收

新增不变式候选（§11.5）：`import trip_decider.travel_agent` 后，`runtime/` 不得被创建或读取。可用 `unittest.mock.patch` 计数 `Path.mkdir` 断言。

---

## 10. fixture 重写原则

**原则（P3a 问题 5 的教训）**：

> 测试 fixture 一律按**生产端实际落盘形状**构造，不按「读取层当时读什么」构造。

P3a 实测撞过三次：fixture 缺 `status`、缺 `retrieved_at`、把证据传成 `evidence=` 关键字而非 `result.context.evidence`。生产侧三者都正确，是 fixture 落后于现实。

**落法**：建立**一份共享 fixture 工厂**，由它产出全部落盘形状；测试只声明「我要一条什么 support 的什么域证据」，形状由工厂负责。已有雏形：`tests/characterization_support.evidence()`。v2 实施时把它提升为全仓共享，并让它成为**唯一**的证据构造入口。

### 10.1 受影响的测试文件（17 个）

| 文件 | 受影响原因 |
|---|---|
| `tests/invariant_support.py` | 共享驱动与 `controlled_*` fixture，全部证据形状 |
| `tests/characterization_support.py` | 表征 fixture，五态构造 |
| `tests/test_product_web.py` | 手工 evidence dict 最多的一个（1,700+ 行） |
| `tests/test_planning_input_compiler.py` | `DestinationContext` + `EvidenceItem` 构造 |
| `tests/test_evidence_broker.py` | 缓存记录形状 |
| `tests/test_mcp_adapter.py` | `controlled_*` 三域证据 |
| `tests/test_itinerary_planner.py` | 计划事件的 `timing_status` |
| `tests/test_schema_validation.py` | 离线 artifact schema（另一条管线，见 §12.3） |
| `tests/test_wu2_adapters.py` | 离线管线 |
| `tests/test_evidence_projection.py` | 投影输入形状 |
| `tests/test_agent_actions_reclassification.py` | 构造点断言 |
| I1/I2/I3a/I3b/I4/I5/I7 的 7 个不变式测试 | 全部消费落盘形状 |

---

## 11. 三条不变式的转绿路径

### 11.1 I1 转绿靠哪些删除

| 删除项 | 清掉多少 |
|---|---|
| `plan.days[].events[].timing_status` | 110 + 55×2 = **220**（最大单项） |
| `action-loop.json` 的 `result` 副本（§2.2 建议） | **152** |
| `*.snapshot_status` / `schedule_status` / `fare_status` | 约 60 |
| `planning_state` / `displayable` / `display_status` | 约 12 |
| 各处 `evidence_status` 与 token 值 | 约 32 |

四项合计覆盖 476 处的全部。**I1 转绿的必要条件是 §1.3 的字段级 support 先落地**——否则 availability 那类信息无处安放，删除会变成丢信息。

### 11.2 I5 持久化侧转绿靠哪些改造

I5 要求「同一 run 两个读取时刻：结构逐字节相同，至少一处 freshness 分量不同」。

| 改造 | 作用 |
|---|---|
| PlanVersion 改为结构 + 引用（§5.1） | 结构部分不含任何随 `now` 变化的内容，前半条由数据形状保证 |
| 删除全部落盘展示态（§3） | 后半条：freshness 只能读时算，两次读取必然可能不同 |
| 安装闸门读时重算（§6） | `planning_state` 从落盘字段变为读时结论，是 I5 在最上层的体现 |

### 11.3 I6 写入侧 7 个模块如何清零

I6 当前的豁免是 48 处字面量分布在 7 个模块（`invariant_ledger.json`，`expires_at_phase = P4`）。

| 模块 | 清零动作 |
|---|---|
| `itinerary_planner` (10) | 事件不再写 `timing_status`，改写 `fact_refs` |
| `agent_actions` (10) | 不再改写 `*_status`，改写字段级 support |
| `intercity_rail` (9) | `rail_snapshot_metadata` 只保留 `retrieved_at`，删 `status` / `display` / `availability_semantics` |
| `planning_input_compiler` (7) | 不再产出 `display_status` / `displayable` |
| `evidence_broker` (6) | `_stale_projection` 不再改写 `*_status`，只写 `refresh_failure` |
| `guided_discovery` (5) | 候选卡改 `fact_id` 引用（§5.2） |
| `dynamic_discovery` (1) | 删 `value.evidence_status` |

清零后 I6 白名单只剩 `evidence_core` 与渲染层，豁免可从 ledger 移除。

### 11.4 新增不变式候选：facts 与 item 级 `status` 一致

§1.3 保留 item 级 `status` 作为便捷字段，需要一条不变式守它不漂移：

> **I10**：任何持久化证据的 item 级 `status`，必须等于其 `facts[]` 按 `evidence-axes.md` §2.4 聚合的结果。

判定：扫描 run 目录全部证据对象，逐条重算聚合并比较。可机械核对，符合 `invariants.md` §0 的收录标准。

### 11.5 新增不变式候选：import 无磁盘副作用

> **I11**：`import trip_decider.<任一模块>` 不得创建或读取 `runtime/` 下任何路径。

判定：子进程中 patch `Path.mkdir` / `Path.read_text` 计数，import 全部模块后断言计数为 0。


---

## 13. 裁决（2026-08-02，已决）

### 13.1 `action-loop` 去重：接受，附写入顺序约束

崩溃恢复语义变化可以接受，但新语义必须钉死：

| 项 | 规定 |
|---|---|
| 写入顺序 | **`run.json` 先落**，`action-loop.json` 后落 |
| 权威 | **`run.json` 为权威**。`action-loop.json` 只存 `action_status` + `plan_version` / 引用 |
| 恢复 | 以 `run.json` 为准。`action-loop.json` 缺失或落后时，从 `run.json` 重建 |
| 验收 | **必须有崩溃恢复用例**：模拟「`run.json` 已写、`action-loop.json` 未写」的中断点，断言可恢复 |

### 13.2 runtime root 改 env var + cwd：接受

`parents[2]` 在 wheel 场景本来就是错的，`cwd` 至少显式可控。

- 脚本入口**全部显式设置** `TRIP_DECIDER_RUNTIME_ROOT`
- README 记录该约定
- **不用 `importlib.resources`**——runtime 数据不该住在包目录里

### 13.3 I10、I11 收录：批准

进 `invariants.md`，测试文件名配齐。

**I10 的实现约束**：item 级 `status` 的聚合**必须调用内核的 `aggregate_support`**，不许写入侧自己实现一份聚合——否则 I10 守的就不是「不漂移」，而是「两份实现恰好一致」。

写入侧 import 内核算 support **不违反 I6**：I6 管的是 token，support 聚合不是 token。

### 13.4 I1 改字段路径白名单：批准

白名单本身是契约的一部分，落在本文件 §15；`invariants.md` 的 I1 指向它。

`RunStatus` 撞名那条观察成立——「目前没撞上纯属巧合」这种状态不能留。

### 13.5 D2 关闭：在线管线为主干，离线管线删除

**这条悬了六个阶段，本规格把它逼到了必须裁决的位置。** 裁决依据早已齐备：

1. 离线管线从产品入口不可达（基线报告 §2.5）
2. 其五态实现已被两轴模型取代（P0–P2）
3. 其唯一价值（四态判定参照）已在 P2 消费完毕
4. README 描述的架构对应的正是这条死支路（基线报告 §4）

**执行范围**：14 个不可达模块（13,347 行）、11 个 schema、约 140 个测试用例一并删除。`tests/test_schema_validation.py` 与 `tests/test_wu2_adapters.py` 随之删除，§10.1 的受影响测试文件降为 **15 个**。

**契约引用改写**：所有引用 `schemas/evidence.schema.json` 的地方改为引用 `evidence-axes.md` 自身——旧 schema 作为历史参照的职责已由该文件 §6.1 的映射表承接完毕。

### 13.6 细节项全批

`last_sourced` → `last_usable`、`version: 1` 删除、`namespace_format_version` 改名、`records.json` 的 `schema_version` 改整数。

---

## 14. 第二步执行顺序

| 序 | 内容 | 依赖理由 |
|---|---|---|
| 1 | 原子写合并为一份 + 共享 fixture 工厂建立 | 后面每一步都踩它们，先立 |
| 2 | 字段级 facts 形状 + I10 | I1 转绿的必要条件（availability 信息的落点），必须先于删除 |
| 3 | 写入侧删展示态（7 模块 48 处，I6 豁免清零） | 依赖 2 |
| 4 | PlanVersion 引用化 + 候选卡引用化 + 安装闸门读时重算 + blocker 清理 | 依赖 2、3 |
| 5 | `action-loop` 去重 + 崩溃恢复用例 | 依赖 4（引用形态定了才知道存什么） |
| 6 | 历史 run 删除 + README 声明 | 在 v2 首次写盘前执行（§8 的时序要求） |
| 7 | 截肢：14 个不可达模块 + 11 schema + 对应测试 + `DEFAULT_AGENT_STORE` 惰性化 + I11 | 放最后，**删除不阻塞任何前序** |
| 8 | I1（白名单版）、I5 持久化侧转绿，ledger 更新 | 收口 |

**表征测试机制照 P3b 复用**：步骤 3、4 动手前先快照当前落盘与对外返回，改造后 diff 对照规格逐类核对，预期外为零才过。

**闸门**：I1 绿、I5 全绿、I6 豁免清零、I10/I11 绿、全量回归无预期外失败、可达性脚本确认截肢后无孤儿模块、ledger 元测试绿（此时登记表应只剩 I4、I9 两条，属 P5）。

---

## 12. 规格过程中发现的新问题

### 12.1 三份原子写实现（已在 P3b 尾巴上撞到）

`travel_agent._atomic_json`、`agent_actions._atomic_runtime_json`、`trip_application._atomic_json` 是三份独立实现，格式还不一致（前两者 `separators=(",",":")` 紧凑，后者 `indent=2`）。P3b 的 `schema_version` 打标第一次只覆盖了一份，正是因为这个。

v2 应合并为一份。**这不是顺带清理**——三份实现意味着任何落盘契约变更都要改三处，而漏改不会立刻报错。

### 12.2 `action-loop.json` 与 `run.json` 内容重复

两个文件各 150+ 处 I1 命中，且**内容高度重复**（同一份 `result`）。476 处里有约 300 处是这份重复造成的。§2.2 的建议（action-loop 只存 `action_status`）能一次清掉一半，但改变崩溃恢复语义，需要裁决。

### 12.3 离线管线的 `schemas/*.json` 未纳入本规格

`schemas/evidence.schema.json` 等 11 个 schema 属于**离线 artifact 管线**（基线报告 §2.5，从产品入口不可达）。`evidence-axes.md` §6.2 已列出它们需要的变更（删 `expires_at` / `status`、加 `data_type`），但那条管线的去留是未决决策（基线 D2，`PLAN.md` v4 开放问题 2）。

**本规格不覆盖它们。** 若 D2 裁决保留离线管线，需要一份平行规格；若裁决删除，则 §10.1 里的 `test_schema_validation.py` / `test_wu2_adapters.py` 一并删除，17 个受影响测试文件降为 15 个。

### 12.4 `evidence/namespace.json` 的 `schema_version` 名字冲突

§1.2 已记录。它是**已经存在的**字段，v2 打标会与它撞名。当前实测该文件显示 `schema_version=1`，看起来像「v1 文件」，实际是「命名空间格式 1」——这个误读已经发生在我自己的核对脚本上。

### 12.5 `RunStatus` 与证据 token 的边界要写进 I1 的判定

`run.json` 的 `status` 字段取值是 `RUNNING` / `COMPLETED` 等，与证据展示态无关，**必须允许落盘**。但 I1 的禁用取值集合里有 `MISSING`，而 `RunStatus` 里没有同名值——目前没撞上，纯属巧合。

v2 应把 I1 的判定从「按字段名与取值黑名单」改进为「按字段路径白名单」，否则将来加一个叫 `STALE` 的运行状态就会误报。
