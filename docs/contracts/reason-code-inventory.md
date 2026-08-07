# D1 清点：`unknown` 的 reason 现状字面量映射

> 状态：P1 的**历史清点与迁移记录**；现行取值域由
> `docs/contracts/evidence-axes.md` §5.2 和 `evidence_core.py` 定义。
> 建立日期：2026-08-02
> 关闭的未决项：`evidence-axes.md` §7 问题 1。
> 证据规则：每条给出 `文件:行号`。无法归入现有取值域的**列为待裁决，不新增取值域**。

---

## 0. 清点范围与方法

在 `src/trip_decider/` 下清点所有产出 `missing_reason` 或其等价物的位置，共五类载体：

| 载体 | 位置 | 条数 |
|---|---|---|
| 直接字面量 `missing_reason=".."` | 5 个模块 | 11 处 / 9 个不同字面量 |
| `guided_discovery._missing_check()` 的 reason 实参 | `guided_discovery.py:222,276,358,409` | 4 个 |
| `destination_runtime` 的兜底字面量 | `destination_runtime.py:82-83,127-128` | 2 个 |
| `_RailFailure.stage` → `missing_reason` | `intercity_rail.py`，经 `destination_runtime.py:118` 传递 | 8 个 |
| `_LiveFailure.stage` → `missing_reason` | `simple_live.py`，经 `destination_runtime.py:118` 传递 | 21 个 |

**合计 44 个不同的现状字面量。** `evidence-axes.md` §5.2 定义的 `reason_code` 取值域有 10 个值，其中 5 个对应 `support == unknown`。

---

## 1. 可直接归入现有取值域（36 个）

### 1.1 → `collector_not_configured`

| 现状字面量 | 位置 |
|---|---|
| `collector_not_configured` | `guided_discovery.py:222` |
| `{domain}_collector_not_configured` | `travel_agent.py:1723`（f-string，实际产出 `railway_/map_/web_collector_not_configured` 三个变体） |
| `amap_web_service_key_not_configured` | `simple_live.py:336,441,651` |
| `credential`（`_LiveFailure.stage`） | `simple_live.py:156` 一带 |

`{domain}_` 前缀在新模型下应移入 `next_action.field_ref`，不进 `reason_code`——域信息已经由 `field_ref` 携带，重复编码会让取值域随域数量膨胀。

### 1.2 → `collector_timeout`

| 现状字面量 | 位置 |
|---|---|
| `collector_timeout` | `guided_discovery.py:409` |

### 1.3 → `collector_error`

| 现状字面量 | 位置 |
|---|---|
| `collector_error:<ExceptionType>` | `guided_discovery.py:358` |
| `live_search_failed` | `dynamic_discovery.py:470` |
| `rail_http` / `rail_transport` / `rail_session_initialize` / `rail_session_parse` / `rail_station_parse` / `rail_schedule_parse` / `rail_price_parse` / `rail_response_window` | `intercity_rail.py`（8 个 stage 全部） |
| `district_parse` / `poi_parse` / `poi_location_parse` / `route_transit_parse` / `poi_projection` / `output_install` / `output_prepare` / `plan_build` | `simple_live.py`（8 个 stage） |

`collector_error:<ExceptionType>` 的异常类型后缀在新模型下应移入 `next_action.detail`，`reason_code` 保持为不带载荷的枚举值。同理，上表 16 个 stage 名在归入 `collector_error` 后应保留在 `detail` 里——它们是有用的诊断信息，只是不该充当枚举。

### 1.4 → `no_source_found`

| 现状字面量 | 位置 |
|---|---|
| `live_destination_profile_unavailable` | `dynamic_discovery.py:345` |
| `no_live_attraction_candidates` | `dynamic_discovery.py:434` |
| `exact_station_identity_not_found` | `intercity_rail.py:500` |
| `exact_destination_district_not_found` | `simple_live.py:387` |
| `railway_data_unavailable` | `destination_runtime.py:82-83`（兜底） |
| `map_data_unavailable` | `destination_runtime.py:127-128`（兜底） |
| `district_resolution` / `poi_selection` / `transfer_place_resolution` | `simple_live.py`（3 个 stage） |
| `district_observation_policy` / `poi_observation_policy` | `simple_live.py`（2 个 stage） |

后两项的归类有保留：观察策略不匹配（`bind_amap_observation_policy` 拒绝了响应）严格说不是「没找到来源」，而是「找到了但不接受」。归入 `no_source_found` 是当前取值域下最接近的选择，代价是丢失了「拒绝原因」这一层。若 P2 发现该区分对用户行动有影响，应作为待裁决第 5 项提出。

---

## 2. 待裁决（8 个）——现有取值域不够用

以下字面量无法归入任何已定义的 `reason_code`。**本文件不新增取值域**，逐条说明为什么现有取值不够。

### 2.1 `cancelled_by_user`

- 位置：`guided_discovery.py:276`
- 为什么不够：这不是采集失败，是用户主动中止。现有 5 个 unknown 类 `reason_code` 全部描述「系统尝试了但没拿到」；用户取消是「系统没有尝试，因为用户不要了」。
- 后果：错归入 `collector_error` 会让 UI 提示「采集出错，正在重试」，而用户明确要求停止。这是会直接误导用户的一类错归。

### 2.2 `destination_anchor_not_supplied`

- 位置：`dynamic_discovery.py:308`
- 为什么不够：这是**输入前置条件不满足**，不是证据状态。系统没有目的地，因此根本没有可采集的对象。
- 后果：把它表达成 `unknown` 证据，等于宣称「我查了目的地画像但没查到」，而实际上用户还没说要去哪。`next_action` 也不同——应指向意图澄清，不指向证据采集。

### 2.3 `direct_train_not_found_in_window`

- 位置：`intercity_rail.py:539`
- 为什么不够：**这是一个确定的负结果，不是不确定。** 12306 查询成功返回，结论是「该时间窗内没有直达车」。按 `evidence-axes.md` §2.2 的判定顺序，序 1（`value` 缺失）不该命中——值存在，值是「无」。
- 这是本次清点中最重要的一条：`support == unknown` 与「已核实为没有」在当前模型里无法区分，而两者对用户的含义完全相反（前者「我不知道」，后者「我确认没有，请改换乘或改日期」）。
- 后果：把确定的负结果标成 unknown，会让系统在本该给出明确结论时说「我没底」——正好是产品差异化主张（`PLAN.md` v4 §1）的反面。

### 2.4–2.8 输入校验类 stage（5 个）

- 位置：`simple_live.py` 的 `input_validation`、`map_point_input_validation`、`route_matrix_input_validation`、`public_route_matrix_input_validation`、`public_route_points_input_validation`、`transfer_input_validation`、`route_input`（7 个 stage，归为一类）
- 为什么不够：与 2.2 同源——调用方传了不合法的参数，属于程序缺陷或前置条件缺失，不是外部世界的信息缺失。
- 后果：这类失败被表达成 `unknown` 证据后，会以「这块我没底」的形态呈现给用户，而真实原因是代码传错了参数。这会把 bug 伪装成数据不足。

---

## 3. 清点结论

| 项 | 数量 |
|---|---|
| 现状不同字面量 | 44 |
| 可归入现有 `reason_code` | 36 |
| 待裁决 | 8（合并为 4 类语义） |
| 现有 unknown 类 `reason_code` 中未被任何现状字面量使用 | 1（`classification_failed`，序 5 兜底，当前无对应实现） |

**四类待裁决语义**：

1. 用户主动中止（`cancelled_by_user`）
2. 输入前置条件不满足（`destination_anchor_not_supplied` + 7 个输入校验 stage）
3. **确定的负结果**（`direct_train_not_found_in_window`）
4. 观察策略拒绝（§1.4 末尾的保留意见）

第 3 类不是「reason_code 不够」，而是**两轴模型本身缺一个表达**：「已核实为不存在」目前只能落进 `unknown`。这需要 Hugin 裁决——它可能意味着 `support` 轴需要区分「无值」与「值为空集」，也可能意味着这应当由 `value` 而非 `support` 承载。本文件不提方案。

> **§2 的裁决结果见 §4。** 第 3 类已于 2026-08-02 裁决，由 `evidence-axes.md` §2.2.1 的 `confirmed_absent` 解决——由 `value` 承载，不动 support 四态。其余三类的归并方案见下。

---

## 4. 归并方案（已批准）

> 建立日期：2026-08-02（P2 阶段产出）
> 状态：**2026-08-02 裁决批准，正式生效。** 内核（`src/trip_decider/evidence_core.py`）已按本节实现。

### 4.0 结论概览

| 类 | 现状字面量 | 方案 | 信息是否有损 |
|---|---|---|---|
| 1 | `cancelled_by_user` | **新增** `cancelled_by_user` | 无损 |
| 2a | `destination_anchor_not_supplied` | **新增** `input_precondition_unmet` | 无损 |
| 2b | 7 个 `*_input_validation` / `route_input` stage | **新增** `internal_contract_violation` | **有损**（7 → 1，stage 名降级进 `detail`） |
| 3 | `direct_train_not_found_in_window` | **不需要 reason_code**。由 `confirmed_absent` 解决 | 无损，且修正方向性错误 |
| 4 | `district_observation_policy` / `poi_observation_policy` | **新增** `source_rejected_by_policy` | 无损 |

`reason_code` 取值域由 10 个扩到 **14 个**。

### 4.1 第 1 类：用户主动中止 → 新增 `cancelled_by_user`

- **方案**：新增取值，名字沿用现状字面量。
- **依据**：现有 5 个 unknown 类 `reason_code`（`no_source_found` / `collector_not_configured` / `collector_timeout` / `collector_error` / `classification_failed`）全部描述「系统尝试了但没拿到」。用户取消是「系统没有尝试，因为用户不要了」。归入其中任何一个，UI 都会提示「正在重试」，而用户刚刚明确要求停止——这是会直接对抗用户意图的错归。
- **伴随取值**：`actor = user`，`kind = user_confirm`（问是否继续），`blocking` 随 `data_type` 的 `feasibility_critical`。
- **信息有损？** 无损。一对一。

### 4.2 第 2a 类：用户可补的前置条件 → 新增 `input_precondition_unmet`

- **方案**：新增取值。
- **依据**：`destination_anchor_not_supplied` 是「用户还没说要去哪」。把它表达成 `unknown` 证据等于宣称「我查了目的地画像但没查到」，而实际上根本没有可查的对象。
- **伴随取值**：`actor = user`，`kind = user_supply`（请用户补），`blocking = true`。
- **信息有损？** 无损。

### 4.3 第 2b 类：代码传错参数 → 新增 `internal_contract_violation`

- **方案**：新增取值，7 个 stage 合并为 1 个。
- **依据**：`input_validation` / `map_point_input_validation` / `route_matrix_input_validation` / `public_route_matrix_input_validation` / `public_route_points_input_validation` / `transfer_input_validation` / `route_input` 全部是调用方传了不合法参数，属于程序缺陷。
- **与 4.2 拆开的理由**：两者都是「输入不满足」，但**对用户的行动指引完全相反**——4.2 用户能补，4.3 用户什么也做不了。合并成一个取值会让 UI 无法分支，那正是 `reason_code` 存在的意义。
- **伴随取值**：`actor = system`，`kind = accept_as_is`（用户无可行动），`blocking = true`（缺陷不得静默放行）。
- **信息有损？** **有损**。7 个 stage 名合并为 1 个取值，「具体是哪个参数不合法」只能进 `detail`。**判断：可接受**——这 7 者对用户的行动指引完全相同（都是「报 bug」），区分它们属于诊断信息，`detail` 是它正确的位置。同样的取舍已经应用在 §1.3 的 16 个 stage 上。

### 4.4 第 4 类：观察策略拒绝 → 新增 `source_rejected_by_policy`

- **方案**：新增取值，解除 §1.4 末尾的保留意见。
- **依据**：`district_observation_policy` / `poi_observation_policy` 是「找到了来源，但 `bind_amap_observation_policy` 拒绝了响应」。与 `no_source_found`（没找到）的用户行动不同：前者可能需要放宽策略或换 provider，后者需要补数据或换查询词。
- **伴随取值**：`actor = system`，`kind = auto_refetch`（换策略或换 provider 重试），`blocking` 随 `feasibility_critical`。
- **信息有损？** 无损。这两个 stage 归入同一取值是恰当的——拒绝的主体相同（观察策略），拒绝的具体条款进 `detail`。

### 4.5 未被使用的取值

`classification_failed`（序 5 兜底）在 44 个现状字面量中无对应实现。**保留**——它是判定顺序的兜底分支，正因为「不该发生」才需要有一个明确的落点。内核在序 1–4 全不命中时产出它，若线上出现即说明判定输入有未预期的形状。

### 4.6 归并后的完整取值域（14 个）

| reason_code | 对应 support/freshness | 来源 |
|---|---|---|
| `no_source_found` | unknown | P0 |
| `collector_not_configured` | unknown | P0 |
| `collector_timeout` | unknown | P0 |
| `collector_error` | unknown | P0 |
| `classification_failed` | unknown | P0 |
| `cancelled_by_user` | unknown | **P2 新增** |
| `input_precondition_unmet` | unknown | **P2 新增** |
| `internal_contract_violation` | unknown | **P2 新增** |
| `source_rejected_by_policy` | unknown | **P2 新增** |
| `sources_disagree` | conflicting | P0 |
| `derived_by_rule` | estimated | P0 |
| `derived_by_provider_estimate` | estimated | P0 |
| `beyond_tolerance_window` | stale | P0 |
| `retrieved_at_absent` | undated | P0 |

四个新增值全部属于 unknown 类。这不是巧合——`support == unknown` 是「系统没有结论」的总类，而「为什么没有结论」的原因空间本来就比其他三态大得多。
