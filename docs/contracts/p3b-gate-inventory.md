# P3b 闸门改造清单：29 处 `sourced` 硬闸门

> 状态：P3b 已完成的闸门迁移清单，不是当前待办。
> 建立日期：2026-08-02
> 对象：`docs/contracts/support-reclassification.md` §5 清点出的 29 处 `sourced` 硬闸门。
> 边界：本文件是清单，不是改动。除 P3a 问题 1 的前置修正外，本步骤不改任何闸门代码。

---

## 0. 怎么读这份清单

每个闸门给出六项：位置与现状语义、所属判定点、改造后语义（四型之一）、选型依据、对规划结果的预期影响、重分类联动。

**四型定义**：

| 型 | 含义 | 主导目标 |
|---|---|---|
| **甲** 四态放行 | `estimated` 照常参与，产出 conditional | 让推算值不再被当作不可用 |
| **乙** 四态收紧 | `unknown` / `conflicting` 阻断且必须可见 | 让「没结论」与「结论打架」不再静默消失 |
| **丙** `confirmed_absent` 特判 | 确认的否定走独立分支，不与 `unknown` 混 | 让「确认没有」不再被说成「不知道」 |
| **丁** 维持二值 | 该点天然只关心 `sourced` | 不改 |

**四型标的是主导目标，不是排他的。** 绝大多数点在改造后都要同时具备四态感知——例如一个标为「甲」的点通常也要拒绝 `conflicting`。标注选择的是**这一点改造的重心在哪、不改会漏掉什么**。每条的「选型依据」说明这个重心。

**判定点编号**（`freshness-policy.md` §3.1）：

| # | 输出 | 位置 |
|---|---|---|
| 判定点 1 | 候选 `feasibility_status` | `guided_discovery.py:520-536` |
| 判定点 2 | 计划 `planning_state` | `planning_input_compiler.py:216-227` |
| 判定点 3 | `conditional_blockers` 中任一 blocker 的存在与否 | `planning_input_compiler.py` 的 17 处 `_blocker(...)` |

不属于任何判定点的闸门也必须改——它们决定**证据能否走到判定点**，一个在采集调度上被判为不可用的推算值，根本到不了判定点。

---

## 1. `agent_actions.py`（16 处）

这 16 处**没有一处属于三个可行性判定点**。它们全部是**动作循环的调度与证据装配**：决定还要不要跑某个 collector、能不能复用已有证据、两条证据能不能合并。它们存在的理由是「避免重复采集」和「保证降级底座有值」。

它们仍然必须改：一个被调度层判为不可用的 `estimated` 值会被无限重采，永远走不到判定点。

### 1.1 `agent_actions.py:128`（`start_action_loop`）

- **现状语义**：初始证据若 `SOURCED` 则标记该 domain 已完成并复用；否则该 domain 重新排入采集队列。
- **判定点**：不属于。动作循环调度。
- **改造后（甲）**：`sourced` 与 `estimated` 均视为已完成；`unknown` 重采；`conflicting` **不重采**，转为待用户裁决（重采不会消解分歧）。
- **选型依据**：重心是让推算值算作「采到了」。`conflicting` 的处理是附带的，但必须一起做——现状把它当 `unknown` 重采，是徒劳的重试。
- **预期影响**：重分类后 map 域不再被反复采集。此前 `conflicting` 会触发无意义重采，改造后停止。
- **重分类联动**：**拦截**。3 处高德时长重分类为 `estimated` 后，若不改此点，map 域会在每轮循环里重采。

### 1.2 `agent_actions.py:472`（`get_next_actions`）

- **现状语义**：`map` 证据非 `SOURCED` 时把 map 动作重新排进待办列表。
- **判定点**：不属于。动作调度。
- **改造后（甲）**：`estimated` 不再触发重排；`unknown` 触发；`conflicting` 转裁决动作而非采集动作。
- **选型依据**：与 §1.1 同源，是同一个调度决策的另一处表达。两点必须同时改，否则一处认为完成、另一处仍在排队。
- **预期影响**：`action_loop.actions` 的长度会变——此前含 map 的轮次，重分类后不再含。
- **重分类联动**：**拦截**。

### 1.3 `agent_actions.py:711`（`submit_evidence`）

- **现状语义**：提交的证据若 `SOURCED` 则并入 `last_sourced_evidence` 并尝试与既有证据合并。
- **判定点**：不属于。证据入库。
- **改造后（甲）**：`estimated` 同样入库并可合并；合并结果的 support 按 `evidence-axes.md` §2.4 聚合。
- **选型依据**：入库是「这条证据可用」的记录，与它是读出还是推算无关。
- **预期影响**：`submit_trip_evidence` 提交推算类证据后不再被丢弃。
- **附带**：`last_sourced_evidence` 这个名字改造后名实不符，应改为 `last_usable_evidence`。改名会波及 §1.1、§1.3、§1.9。

### 1.4 `agent_actions.py:829`（`_map_handler`）

- **现状语义**：已有 map 证据且 `SOURCED` 则复用，否则重新采集行政区。
- **判定点**：不属于。采集短路。
- **改造后（甲）**：`estimated` 也可复用。
- **选型依据**：复用条件是「有可用值」，不是「值怎么来的」。
- **预期影响**：减少一次高德调用。
- **重分类联动**：**拦截**。

### 1.5 `agent_actions.py:836`（`_map_handler`）

- **现状语义**：district 证据 `SOURCED` 且 value 含 `local_transit` 列表时直接返回，不再解析路线。
- **判定点**：不属于。采集短路。
- **改造后（甲）**：同上。
- **选型依据**：同上。
- **重分类联动**：**拦截**，且是最直接的一处——`local_transit` 正是路径规划时长的载体。

### 1.6 `agent_actions.py:846`（`_map_handler`）

- **现状语义**：district 非 `SOURCED`、或 web 未提供路线输入时，直接返回不做路线解析。
- **判定点**：不属于。采集前置条件。
- **改造后（甲）**：`estimated` 的 district 同样可作为路线解析的起点；`unknown` 仍然拦截（没有行政区就无从规划路线）。
- **选型依据**：这是**甲与乙的分界示例**——放行 `estimated`，保留对 `unknown` 的拦截，两半都要做。

### 1.7 `agent_actions.py:1151`（`_stale_railway_evidence`）

- **现状语义**：`previous` 非 `SOURCED` 则抛 `TravelAgentError`——降级必须有一个有值的底座。
- **判定点**：不属于。降级前置条件。
- **改造后（甲）**：接受 `{sourced, estimated}`，拒绝 `{unknown, conflicting}`。降级后的 support **保持原值**，不得提升为 `sourced`。
- **选型依据**：底座要求「有单一可用值」。`estimated` 满足；`conflicting` 有多个值，降级会掩盖分歧；`unknown` 无值。
- **预期影响**：推算类铁路证据刷新失败后可以降级保留，此前会直接抛错中断动作循环。

### 1.8 `agent_actions.py:1204`（`_stale_generic_evidence`）

- 与 §1.7 完全同构，作用于非铁路域。**改造后（甲）**，依据同上。
- **重分类联动**：**拦截**。map 域降级走这条路径。

### 1.9 `agent_actions.py:1264` 与 `:1265`（`_merge_sourced_evidence`）

两个闸门（`previous` 与 `current` 各一），一并处理。

- **现状语义**：两边都必须 `SOURCED` 且同域，否则抛错。
- **判定点**：不属于。证据装配。
- **改造后（甲）**：接受 `{sourced, estimated}` 的任意组合，**合并结果的 support 按 §2.4 聚合**（任一输入 `estimated` → 结果 `estimated`）。`conflicting` 仍拒绝。
- **选型依据**：**这是 29 处里唯一需要引入聚合规则的点。** 其余 28 处都是「这条证据能不能用」的一元判断，这里是「两条证据合成一条」，必须走 §2.4。
- **预期影响**：map 域的行政区证据（`sourced`）与路线证据（`estimated`）合并后，整体降为 `estimated`——这会向下游传播，是重分类影响面最大的一跳。
- **附带**：函数名 `_merge_sourced_evidence` 改造后名实不符。

### 1.10 `agent_actions.py:1430`（`_is_usable_action_evidence`）

- **现状语义**：非 `SOURCED` 直接判不可用；随后对 `action_id == "map" and data_type == "route_duration"` 另做内容检查。
- **判定点**：不直接属于，但它决定动作是否算完成，**间接决定 `planning_state`（判定点 2）**。
- **改造后（甲）**：`estimated` 判为可用。
- **选型依据**：这是全仓**唯一显式按 `data_type == "route_duration"` 分支的闸门**（`agent_actions.py:1432`），也就是说它已经知道自己在处理路径规划时长。重分类后这条证据变 `estimated`，若不改，第一行就把它拦死，后面那段专门为它写的内容检查永远走不到。
- **预期影响**：`action_status` 中 map 从 `blocked` 变 `completed`。
- **重分类联动**：**最强拦截点**。29 处中影响最直接的一处。

### 1.11 `agent_actions.py:1449`（`_web_route_inputs`）

- **现状语义**：web 证据非 `SOURCED` 时返回 `None`，导致不发起路线规划。
- **判定点**：不属于。采集前置条件。
- **改造后（甲）**：`estimated` 的 web 画像同样可提供路线输入。
- **选型依据**：路线输入是「住宿基地名 + 景点名列表」，是直接读出的字符串；即使整条 web 证据因别的字段被判 `estimated`，这几个名字仍然可用。**这暴露了域级粒度的代价**——见 §5.2。

### 1.12 `agent_actions.py:1503`（`_web_route_points`）

- 与 §1.11 同构，取的是坐标而非名称。**改造后（甲）**，依据同上。

### 1.13 `agent_actions.py:1536`（`_web_route_segments`）

- **现状语义**：web 证据 `SOURCED` 才读取 `route_segments`。
- **判定点**：不属于。
- **改造后（甲）**：同 §1.11。

### 1.14 `agent_actions.py:1660`（`_needs_local_transit`）

- **现状语义**：map 证据非 `SOURCED` 时判定「仍需采集当地交通」。
- **判定点**：不属于。调度。
- **改造后（甲）**：`estimated` 判为已采集。
- **重分类联动**：**拦截**。不改会导致当地交通被无限重采。

### 1.15 `agent_actions.py:1695`（`_can_collect_local_transit`）

- **现状语义**：map 证据非 `SOURCED` 时判定「无法采集当地交通」。
- **判定点**：不属于。调度。
- **改造后（甲）**：同上。
- **注意**：`:1660` 与 `:1695` 一个说「需要采」一个说「能不能采」。重分类后若只改一处，会出现「需要采但不能采」的死锁——两点必须同时改。

---

## 2. `planning_input_compiler.py`（7 处）

这 7 处**全部或间接属于判定点 2 / 3**。它们是 29 处里唯一直接决定 `planning_state` 与 `conditional_blockers` 的一组，也是 I7 最相关的一组。

### 2.1 `planning_input_compiler.py:269`（`_compile_railway`）

- **现状语义**：铁路证据为 `None` 或非 `sourced` 时**直接 `return`**——不产出任何 blocker。
- **判定点**：**判定点 3**（其后紧跟 `_blocker("RAILWAY_EVIDENCE_MISSING")` 等四处调用）。
- **改造后（丙）**：三分支。
  1. `confirmed_absent` → 产出**新 blocker** `RAILWAY_NO_DIRECT_TRAIN`，语义是「已核实该时间窗内没有直达车」，附 `scope`；
  2. `unknown` / `conflicting` → 产出 `RAILWAY_EVIDENCE_MISSING`，**不得静默 return**。该 blocker **携带 `fact_id` 引用**，消费方顺着引用读 token 得知是「没结论」还是「结论打架」；
  3. `estimated` → 正常编译，附 conditional。

  **裁决 8.2 修正**：原提案的 `RAILWAY_EVIDENCE_CONFLICTING` 已驳回——它复述了 `token == conflicting`，属于结论层重新编码证据词表。改为 blocker 引用 `fact_id`，见 `evidence-axes.md` §5.5。
- **选型依据**：选丙而非乙，是因为这一点是 `confirmed_absent` 整个概念的**来源**（`intercity_rail.py:539` 的 `direct_train_not_found_in_window`，见 `reason-code-inventory.md` §2.3）。若它继续把「确认没有直达车」和「没查到」混为一谈，`confirmed_absent` 在产品路径上就没有落点。
- **预期影响**：**此前静默通过的现在会阻断。** 现状下一条 `unknown` 的铁路证据会让 `_compile_railway` 悄悄返回，计划照常编译，用户看不到任何提示。改造后必然产出 blocker。这是 29 处中对规划结果影响最大的一处。
- **重分类联动**：不拦截高德时长（铁路域）。

### 2.2 `planning_input_compiler.py:429`（`_compile_attractions`）

- **现状语义**：遍历 `(map_item, web_item)`，非 `sourced` 的来源 `continue` 跳过。
- **判定点**：**判定点 3**（`ATTRACTION_EVIDENCE_MISSING`）。
- **改造后（乙）**：`estimated` 参与并给景点打 conditional 标记；`unknown` / `conflicting` 不再静默 `continue`，必须记录「哪个来源为什么没贡献景点」。
- **选型依据**：重心是 `continue` 的静默性。两个来源都不可用时，现状只会产出一个笼统的 `ATTRACTION_EVIDENCE_MISSING`，用户无从知道是地图没查到还是网页没查到。
- **预期影响**：景点列表可能变长（`estimated` 来源被纳入），blocker 描述变具体。
- **重分类联动**：**拦截**。`map_item` 重分类后会被 `continue` 掉，导致景点数量下降，进而可能跌破 `detailed_itinerary_ready` 的「≥3 个景点」门槛。

### 2.3 `planning_input_compiler.py:1160`（`_compiled_map_points`）

- **现状语义**：web 证据非 `sourced` 时只返回地图来源的点。
- **判定点**：不直接属于（供给 `map_points`，供渲染与距离估算）。
- **改造后（甲）**：`estimated` 的 web 点同样纳入。
- **选型依据**：坐标是直接读出的，不因整条证据被判 `estimated` 而失效。同 §1.11 的粒度问题。

### 2.4 `planning_input_compiler.py:1234`（`_value_list`）

- **现状语义**：通用取值工具。证据非 `sourced` 时返回**空列表**。
- **判定点**：**间接属于判定点 3**——它被 `_compile_attractions`、`_compiled_map_points`、`_hotel_area` 等多处调用，每个调用方的 blocker 判断都依赖它的返回。
- **改造后（乙）**：返回值需能区分「该来源没有这个键」与「该来源不可用」。空列表把两者合成了一个。
- **选型依据**：**这是 29 处里最难改的一处**，理由见 §4。重心是「静默丢弃」：返回空列表后，调用方无法知道是真的没有还是不让用。
- **预期影响**：所有调用方的 blocker 判断都会变得更具体，但**每个调用方都要跟着改**。
- **重分类联动**：**拦截**，且是扇出最广的一处。

### 2.5 `planning_input_compiler.py:1244`（`_hotel_area`）

- **现状语义**：证据非 `sourced` 时返回 `None`，导致住宿基地未确定。
- **判定点**：**判定点 3**（`HOTEL_SELECTION_MISSING`，`:682`）。
- **改造后（乙）**：`estimated` 的住宿片区可用并附 conditional；`unknown` / `conflicting` 保持阻断但要携带具体原因。
- **选型依据**：重心是 `None` 的歧义——`None` 既表示「证据不可用」也表示「证据里没有 hotel_area 字段」。

### 2.6 `planning_input_compiler.py:1258`（`_destination_resolved`，map 分支）

- **现状语义**：map 证据 `sourced` 且 value 含可辨识的 destination 字段时，判定目的地已解析。
- **判定点**：**判定点 2**（经 `display_requirements.destination_resolved` 进入 `planning_state`）。
- **改造后（丙）**：`confirmed_absent` 走独立分支——「已核实该目的地不存在」应产出与「没查到」不同的结论与提示（前者要用户换目的地，后者要重查）。`estimated` 视为已解析并附 conditional。
- **选型依据**：目的地身份是整条规划的根。把「这个地方不存在」说成「我没查到」，会让用户反复重试一个注定失败的查询。
- **预期影响**：`planning_state` 的取值分布会变——此前落 `COLLECTING_EVIDENCE` 的一部分会变成明确的阻断。

### 2.7 `planning_input_compiler.py:1267`（`_destination_resolved`，web 分支）

- 与 §2.6 同构，取 `destination_official_name`。**改造后（丙）**，依据同上。两分支必须同时改，否则一个说已解析、另一个说确认不存在。

---

## 3. `guided_discovery.py`（4 处）与 `evidence_broker.py`（2 处）

### 3.1 `guided_discovery.py:199`（`build_guided_comparison`）

- **现状语义**：外部注入的证据 `SOURCED` 才复用，并标 `from_cache=True`。
- **判定点**：不属于。证据复用。
- **改造后（甲）**：`estimated` 同样可复用。
- **重分类联动**：**拦截**。

### 3.2 `guided_discovery.py:314`（`emit_ready_options`）

- **现状语义**：`SOURCED` 才发布到 `EvidenceBroker` 缓存。
- **判定点**：不属于。缓存发布。
- **改造后（甲）**：`estimated` 可发布，**但缓存记录必须携带 support**，复用时保持原值。
- **选型依据**：见 §3.6 关于 `_stale_projection` 的联动——若发布时不带 support，复用时会被硬编码提升为 `sourced`。

### 3.3 `guided_discovery.py:521`（`_coarse_option` 的 `rail_sourced`）

- **现状语义**：`rail_sourced = 铁路证据 SOURCED 且 duration 与 known_cost 均非 None`，直接决定候选 `feasibility_status`。
- **判定点**：**判定点 1。这是三个判定点里唯一在本模块的一处。**
- **改造后（丙）**：四分支加否定特判。
  1. `sourced` → `CONDITIONALLY_FEASIBLE`（不变）；
  2. `estimated` → `CONDITIONALLY_FEASIBLE` **且必须携带一个 conditional**（裁决 5 的直接落点）；
  3. `confirmed_absent` → 新结论 `INFEASIBLE_NO_TRANSPORT`，语义是「已核实没有直达车」，与「不知道有没有车」区分；
  4. `unknown` / `conflicting` → `UNKNOWN` 并携带可见原因（I7 第 2、3 条）。
- **选型依据**：选丙是因为第 3 分支——「确认没车」是一个**确定的可行性结论**，把它归入 `UNKNOWN` 等于在本可以给答案时说没底，正是产品差异化主张的反面。
- **预期影响**：**此前只有两种结果（`CONDITIONALLY_FEASIBLE` / `UNKNOWN`），改造后有四种。** 这是候选比较对用户信息量的主要提升点。
- **重分类联动**：不直接拦截高德时长（铁路域），但 `playable_time_seconds` 由往返时长算出，按 §2.4 会聚合为 `estimated`，走第 2 分支。

### 3.4 `guided_discovery.py:597`（`_check_from_evidence`）

- **现状语义**：`SOURCED → "LIVE"`，其余一律 `→ "MISSING"`。
- **判定点**：**判定点 1 的展示侧**（产出候选卡的 `evidence_statuses[].status`）。
- **改造后（乙）**：改为调用 `evidence_core`，产出 token 与 `next_action`。`conflicting` 必须原样呈现且 `conflict_details` 可见。
- **选型依据**：这是 **I7 第 3 条的直接违反点**——`else` 分支把 `CONFLICTING` 折叠成 `MISSING`（基线报告 M1）。同时它是 P3a I6 豁免的一部分（写入侧）。
- **预期影响**：候选卡的 `evidence_statuses` 从三态变八 token，并首次携带 `next_action`。这会让 `test_i3a_candidate_view_evidence_carries_next_action` 转绿。

### 3.5 `evidence_broker.py:154`（`publish`）

- **现状语义**：非 `SOURCED` 的证据不入跨 run 缓存。
- **判定点**：不属于。缓存准入。
- **改造后（丁，维持二值）**：**这是 29 处里唯一建议维持二值的点**，但需 Hugin 裁决。
- **选型依据**：broker 的契约是「跨 run 复用**实采**证据」（`evidence_broker.py:1-7` 的模块 docstring），并有 `_validate_sources` 拒绝 fixture/catalog 材料。把推算值缓存下来、在另一个 run 里作为降级值replay，等于让估算误差跨 run 累积——第二个 run 会拿到第一个 run 的推算结果，却无从判断它推算时的输入还成不成立。
- **反方意见（供裁决）**：若维持二值，重分类后 `route_duration` 将永远无法进入缓存，`stale_after_failure` 对 map 域完全失效，等于取消了当地交通的降级能力。
- **预期影响（若维持）**：map 域失去跨 run 降级；（若改甲）需同时改 §3.6。

### 3.6 `evidence_broker.py:343`（`_is_usable_live`）

- **现状语义**：非 `SOURCED` 判为「本次实采不可用」，从而允许调用 `stale_after_failure` 走缓存降级。
- **判定点**：不属于，但决定是否触发降级。
- **改造后（甲）**：`estimated` 的实采结果是可用的，不应触发降级。
- **选型依据**：不改会导致重分类后每次 map 采集都被判为失败，进而每次都走缓存降级——一个成功的采集被当成失败。
- **重分类联动**：**拦截**。此处已有 `query.data_type == "route_duration"` 的专门分支（`evidence_broker.py:348`），与 §1.10 一样是为高德时长写的。

**关联但不在 29 之列**：`evidence_broker.py:437-443` 的 `_stale_projection` 返回时**硬编码 `EvidenceStatus.SOURCED`**。它是构造点不是闸门，因此不在本清单编号内，但重分类后必须一并改为保留原 support——否则一个 `estimated` 值经过一次缓存降级就被提升成 `sourced`，直接违反 I2。

---

## 4. 汇总视图一：四型分布

| 型 | 数量 | 名单 |
|---|---|---|
| **甲** 四态放行 | **21** | `agent_actions` 全部 16 处（`:128 :472 :711 :829 :836 :846 :1151 :1204 :1264 :1265 :1430 :1449 :1503 :1536 :1660 :1695`）、`planning_input_compiler:1160`、`guided_discovery:199 :314`、`evidence_broker:154 :343` |
| **乙** 四态收紧 | **4** | `planning_input_compiler:429 :1234 :1244`、`guided_discovery:597` |
| **丙** `confirmed_absent` 特判 | **4** | `planning_input_compiler:269 :1258 :1267`、`guided_discovery:521` |
| **丁** 维持二值 | **0** | 无。`evidence_broker:154` 原提案为丁，裁决 8.1 改为甲 |

### 4.1 分布本身说明了什么

**「丁」是 0 处**（原提案 1 处，裁决 8.1 驳回）。 29 个闸门里没有一个是因为 `sourced` 这个态本身特殊才写成二值的——它们写成二值，是因为**当时只有三态可用**，而三态里只有 `sourced` 表示「有可用值」。

换句话说：这 29 处不是 29 个设计决策，是同一个缺失（枚举里没有 `estimated`）在 29 个地方的表现。这也解释了为什么其中 20 处是「甲」——它们要的从来就是「有没有可用值」，只是当时没有别的说法。

### 4.2 三个判定点的覆盖

| 判定点 | 被几处闸门直接决定 | 位置 |
|---|---|---|
| 判定点 1（候选可行性） | 2 | `guided_discovery:521`（结论）、`:597`（展示） |
| 判定点 2（`planning_state`） | 2 直接 + 1 间接 | `planning_input_compiler:1258 :1267`；`agent_actions:1430` 经 `action_status` 间接 |
| 判定点 3（blockers） | 4 直接 + 1 间接 | `planning_input_compiler:269 :429 :1244`；`:1234` 经多个调用方间接 |
| 不属于任何判定点 | 20 | `agent_actions` 全部 16 处 + `guided_discovery:199 :314` + `evidence_broker:154 :343` |

20 处不属于判定点的闸门在采集与装配层。它们不产出结论，但决定证据能否走到产出结论的地方。

---

## 5. 汇总视图二：`EvidenceStatus` 加 `estimated` 的波及面

**这是 P3b 的明示范围。** 枚举扩展会同时改变内存结构、序列化结果与落盘内容，逐层列出。

### 5.1 枚举与构造点

| 层 | 位置 | 变化 |
|---|---|---|
| 枚举定义 | `travel_agent.py:128-131` | 三值 → 四值，新增 `ESTIMATED = "estimated"` |
| 反序列化 | `travel_agent.py:468-511`（`EvidenceItem.from_mapping`） | 接受的 `status` 取值域扩大。**这是外部注入面**——`submit_trip_evidence` 经此进入，MCP 客户端从此可以提交 `estimated` 证据 |
| 构造点 | 21 处 `EvidenceItem(...)`（`support-reclassification.md` §0 清点） | 其中 **3 处需改为 `ESTIMATED`**：`agent_actions.py:909 :951 :1305`（高德路径规划时长）。其余 18 处不变 |
| 降级构造 | `evidence_broker.py:437-443`（`_stale_projection`） | 硬编码 `SOURCED` → 改为保留原 support。**不改则 estimated 经一次降级被提升为 sourced，违反 I2** |

### 5.2 序列化与落盘

| 项 | 变化 |
|---|---|
| `EvidenceItem.to_dict()` | `travel_agent.py:515` 的 `"status": self.status.value` 会写出 `"estimated"` |
| 落盘文件 | `run.json` 的 `result.context.evidence[].status`、`evidence.json`、`guided-evidence.json` 的同名字段，取值域从 3 值变 4 值 |
| **I1 是否允许** | **允许**。`support` 是可持久化轴（`evidence-axes.md` §1），`status` 字段承载的正是 support。它不在 I1 的禁用键名集合里 |
| **版本标记** | **必须加**。历史 run 的 `status` 取值域是 3 值，新 run 是 4 值。按 `PLAN.md` v4 §7 约束 3（落盘契约变更必须携带版本标记），这次变更需要版本号。基线报告 H1 记录过一次无版本变更的后果 |

### 5.3 读取层联动

`evidence_projection._fact_from_item` 当前把 `status == "sourced"` 一律映射到 `derivation="direct_observation"`（P3a 的豁免）。枚举扩展后：

- `status == "estimated"` → `derivation="api_estimate"`，走 §2.2 序 3；
- P3a 登记的 I2 豁免（`invariant_ledger.json`，`expires_at_phase = P3b`）随之清零。

### 5.4 不在本次范围

`itinerary_planner.py:160-170` 的 `"support": "estimated"` 是规划器默认参数的自描述字段，与证据 support 不同义（`support-reclassification.md` §4）。它不随本次枚举扩展变化，但**同名会造成混淆**，建议同期改名。

---

## 6. 汇总视图三：I7 四条登记测试 ← 闸门映射

`invariant_ledger.json` 中 I7 的 4 条登记，各自由哪些闸门的改造转绿：

| 登记测试 | 当前失败断言 | 由哪些闸门转绿 | 说明 |
|---|---|---|---|
| `test_i7_conflicting_evidence_stays_conflicting` | `assertEqual('conflicting', 'MISSING')` | **`guided_discovery:597`**（乙） | 单点。`else` 分支折叠 `CONFLICTING` |
| `test_i7_conflict_details_survive_to_the_caller` | `assertIn(冲突描述, 候选卡)` | **`guided_discovery:597`**（乙）+ `_coarse_option` 返回体扩字段（`:548-590`，不是闸门） | 需要闸门改造**加**返回体加字段。返回体那一半不在 29 之列 |
| `test_i7_unknown_evidence_stays_unknown` | `assertEqual('unknown', 'MISSING')` | **`guided_discovery:597`**（乙） | 与第 1 条同一处改造，一并转绿 |
| `test_i7_estimated_input_produces_at_least_one_conditional` | `assertTrue(hasattr(EvidenceStatus, 'ESTIMATED'))` | **`travel_agent.py:128-131` 枚举扩展**（§5.1）+ **`guided_discovery:521`**（丙） | 断言分两段：枚举扩展让测试能构造输入，`:521` 让输入产出 conditional |

**结论**：I7 的 4 条中有 3 条由 `guided_discovery:597` 一处改造转绿，第 4 条需要枚举扩展加 `:521`。也就是说 **I7 的转绿只依赖 29 处中的 2 处**，其余 27 处的改造由 I2 豁免清零（`estimated` 在读取层可达）来验证，不由 I7 验证。

这是个值得注意的覆盖缺口：**27 个闸门的改造没有直接的不变式守卫**。它们的正确性只能靠既有回归测试与 §7 的逐点预期影响核对。

---

## 7. 改造顺序建议

不是闸门本身的属性，但影响风险，列在此供裁决时参考。

| 批次 | 内容 | 理由 |
|---|---|---|
| 1 | `travel_agent.py:128-131` 枚举扩展 + `from_mapping` + `_stale_projection` 保留 support | 没有它其余全部无从构造。此批不改任何闸门，行为应完全不变——可作为一次纯扩展验证 |
| 2 | `agent_actions` 16 处（甲）+ `evidence_broker:343`（甲） | 全部在采集调度层，不触判定点，回归面可控 |
| 3 | 3 处高德时长构造点改 `ESTIMATED`；I2 豁免清零 | 重分类正式生效。批次 2 未完成前不能做，否则 map 域会被调度层拦死 |
| 4 | `planning_input_compiler` 7 处 + `guided_discovery` 4 处 | 直接改变规划结果，需要逐条比对预期影响 |
| 5 | `evidence_broker:154` 按裁决处理 | 取决于 §3.5 的裁决 |

---

## 8. 裁决（2026-08-02，已决）

### 8.1 `evidence_broker:154` → **四态放行（甲）**

原提案的「丁」被驳回。裁决理由：

- 「估算误差跨 run 累积」的担心不成立——缓存**不重新推算，只原样重放**。重放出来的值仍带 `estimated` 标签与陈旧的 `retrieved_at`，两轴模型本身已经把诚实性带上了。
- 维持二值的风险更大：map 域失去降级能力意味着 `route_duration` 一次实采失败就直接 `unknown` + `blocking`，而它是 `feasibility_critical`——高德抖一下，整个规划阻断。

**硬性前提**：`evidence_broker.py:437-443` 的 `_stale_projection` 硬编码 `SOURCED` 必须同步改为保留原 support。不改则 `estimated` 过一次缓存被提升成 `sourced`，本条裁决就变成 I2 漏洞。

**§4 的四型分布相应更新为：甲 21 / 乙 4 / 丙 4 / 丁 0。**

### 8.2 结论值：批两个，驳一个

| 结论值 | 裁决 | 理由 |
|---|---|---|
| `RAILWAY_NO_DIRECT_TRAIN` | **接受** | `confirmed_absent` 在规划结论层的表达，是产品在诚实说话 |
| `INFEASIBLE_NO_TRANSPORT` | **接受** | 同上 |
| `RAILWAY_EVIDENCE_CONFLICTING` | **驳回** | 它在结论层重新编码了 support 词表 |

**驳回理由**：「证据冲突」这个信息已经由该事实的 `token == conflicting` 加 `next_action(kind=user_choice)` 完整承载。再造一个结论层字面量，就是 I6 消灭掉的那种并行词表的第一块新砖。

**替代落法**：blocker 引用 `fact_id`，消费方顺着引用读 token，不新增字面量。

### 8.3 结论值原则（新增，已写入 `evidence-axes.md` §5.5）

> **规划结论值只允许表达规划层自己的结论（没有直达、无法成行），不允许复述证据层的状态。**

防的是「后面每个域都来铸一个 `*_EVIDENCE_CONFLICTING`」。证据状态的唯一表达是 token + `next_action`；规划结论要引用证据，走 `fact_id` 引用，不走字面量复制。

### 8.4 `schema_version` → **P3b 提前引入，最小形式**

裁决理由：H1 的教训就是「格式变了没打标」。明知道 P3b 会往盘上写出一个新枚举值还等 P4 打标，等于故意重演一次 H1。

**落法（最小，不做 P4 的完整落盘契约改造）**：

| 项 | 规定 |
|---|---|
| 受影响文件 | `run.json`、`evidence.json`、`guided-evidence.json` |
| 字段 | 顶层 `schema_version` |
| 本次取值 | `2` |
| 读取层 | 无该字段的文件按 `1` 处理 |
| 边界 | **只打标，不改落盘结构**。两阶段重叠止于此 |

---

## 9. 27 个无守卫闸门的表征测试（P3b 第二步前置）

§6 指出的缺口是真的：I7 只守 2 处，其余 27 处只有「既有回归 + 逐点预期影响核对」。**既有回归的 fixture 是按旧行为写的，它守不住「改造后行为符合清单预期」这件事。**

因此第二步动代码前先拉一层**表征测试**（characterization test）：

| 项 | 规定 |
|---|---|
| 输入 | 一个固定证据 fixture，覆盖四态 + `confirmed_absent` |
| 范围 | 跑完整规划链路，覆盖三个判定点 |
| 基线 | 改造前把当前输出快照下来，作为「改造前基线」 |
| 核对 | 改造后逐处对照本清单的「预期影响」列核对 diff |
| 判据 | **预期内的差异逐条确认后更新快照；预期外的差异就是事故** |

**性质**：这不是不变式，是一次性的**迁移守卫**。P3b 结束后可以降级为普通回归 fixture。

它与 `invariant_ledger.json` 的区别：登记管的是「哪条不变式还红着」，表征测试管的是「这次改造有没有改出计划外的东西」。两者都必须绿，但绿的含义不同。

