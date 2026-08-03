# 证据两轴模型契约

> 状态：生效。本文件是 support / freshness 两轴的权威定义。
> 建立日期：2026-08-02（P0 阶段产出）
> 取代：`PLAN.md` v3 §4 的五态模型、`schemas/evidence.schema.json` 的 `display_status` 五态枚举。
> 前置阅读：`docs/audit/handover-baseline.md`（接手基线报告），特别是 §3「五态证据模型专项核对」。
> 证据规则：涉及现有代码的陈述给出 `文件:行号`。不确定的标注【待验证】。

---

## 0. 这份文件解决什么问题

基线报告 §3.2 实测确认：仓库里同时存在四套互不兼容的证据状态词表，而 `PLAN.md` v3 §4 冻结的五态（`verified / sourced / estimated / conflicting / unknown`）在产品运行路径上一次都不出现。同时 §3.4 实测确认，`trip_read_model.py:231-238` 会把采集失败的证据渲染成 `LIVE`，方向与冻结不变式相反。

根因不是实现疏忽，是模型本身把两种正交的信息压进了一个枚举：

- 「这个值有多可靠」——由采集方式决定，采到即固定，不随时间变化。
- 「这个值还新不新」——由时间决定，同一份数据今天新鲜明天陈旧。

五态里 `verified` 同时编码了这两件事（"当前、明确、可回读"，见 `PLAN.md:66`），于是它既无法在写入时确定，也无法在读取时稳定。本文件把这两件事拆成两条正交轴。

---

## 1. 两轴总览

| 轴 | 名称 | 是否可持久化 | 何时确定 | 取值域 |
|---|---|---|---|---|
| 轴一 | `support` | **可持久化，写入即固定** | 证据采集完成时 | `sourced` / `estimated` / `conflicting` / `unknown` |
| 轴二 | `freshness` | **不可持久化** | 每次读取时按 `now` 现算 | `fresh` / `stale` / `undated` |

**硬规则（不可协商）**：任何持久化文件中不得出现展示状态字段。展示状态一律读时计算。该规则的可机械核对形式见 `docs/contracts/invariants.md` I1。

`support` 之所以可持久化：它只依赖采集当时的事实（来源是谁、值怎么来的、有没有冲突），这些在写入后不再变化。

`freshness` 之所以不可持久化：它是 `now` 的函数。任何把它写进文件的做法——包括写 `status`、也包括写 `expires_at`——都等于把某一时刻的判断冻结成永久事实。

---

## 2. support 轴

### 2.1 判定输入

判定 `support` 只允许使用以下四项输入，不得使用时间：

| 输入 | 含义 | 现有载体 |
|---|---|---|
| `sources[]` | 外部来源列表，每项含 `provider` / `url` / `scope` / `retrieved_at` | `travel_agent.py:464`（`EvidenceItem.sources`） |
| `derivation` | 值的产生方式 | `schemas/evidence.schema.json` 的 `derivation` 六值枚举 |
| `conflict_details[]` | 来源分歧的具体描述 | `travel_agent.py:466`（`EvidenceItem.conflict_details`） |
| `value` 是否承载结论 | 采集是否产出了结论。**有值**与**确认没有**都算结论，只有「不知道」不算 | `travel_agent.py:463`（`EvidenceItem.value`） |

### 2.2 各态的可操作定义

判定按下表顺序进行，**第一个命中的胜出**。顺序本身是规范的一部分，不得调整。

| 序 | support | 判定条件（全部满足） | 必需伴随字段 |
|---|---|---|---|
| 1 | `unknown` | 采集未产出结论。具体为：`value` 缺失、为 `null`、或该 `field` 在 `value` 中不存在 | `reason`（见 §2.3） |
| 2 | `conflicting` | 存在 ≥2 个来源对同一 `(subject, field)` 给出不可调和的值 | `conflict_details[]` 非空、`conflict_source_refs[]` ≥2 项 |
| 3 | `estimated` | 值由推算产生。`derivation` ∈ `{api_estimate, model_estimate, rule_derived}` | `derivation_detail.estimate`（`method` / `value` / `unit`） |
| 4 | `sourced` | 值是某个来源字段的直接读出，未经跨字段推算，**或是来源明确给出的负结果**（见 §2.2.1）。`derivation` ∈ `{direct_observation, official_report, user_supplied}`，且 `sources[]` 非空，且每个 source 携带 `retrieved_at` | `sources[]` 非空 |
| 5 | `unknown` | 兜底。以上四条均不命中 | `reason = "classification_failed"` |

**逐条说明**

- **`sourced` 的边界**：「直接读出」指值在来源响应中以该字段形式出现。12306 返回的列车时刻、票价属于此类（`intercity_rail.py:586-600` 逐字段读出）。高德路径规划返回的行程时长**不属于**此类——它是服务端的推算量，归 `estimated`。这一条会改变现有分类，见 §6.3。
- **序 1 的措辞是「未产出结论」而非「未产出可用值」**（2026-08-02 修正）：确认的否定是结论，不是 `unknown`。修正前的措辞会让「12306 查询成功、结论是窗口内没有直达车」落进序 1，把一个已核实的事实标成「我不知道」——正好是产品差异化主张（`PLAN.md` v4 §1）的反面。
- **`user_supplied` 归 `sourced`**：用户是一个来源。要求 `source.provider` 显式记为用户标识，`retrieved_at` 记为提交时刻。用户提供的值不因「来自用户」而降级，也不因此升级。
- **`estimated` 不区分推算主体**：无论是本地规则、供应商 API 还是模型推算，只要值不是直接读出，一律 `estimated`。区分留给 `derivation` 字段，不进入 support 轴。
- **`conflicting` 优先于 `estimated`**：两个来源分歧时，即使其中之一是推算值，结果仍是 `conflicting`。分歧本身是需要用户裁决的事实。
- **`unknown` 出现两次是有意的**：序 1 处理「没采到」，序 5 处理「采到了但归不了类」。两者的 `reason` 不同，next_action 也不同。

### 2.2.1 `confirmed_absent`：来源明确给出的负结果

**2026-08-02 增补，裁决依据：P1 清点意外发现 1（`docs/contracts/reason-code-inventory.md` §2.3）。**

有一类结论是「我查过了，确认没有」。例：`intercity_rail.py:539` 的 `direct_train_not_found_in_window`——12306 查询成功返回，结论是该时间窗内没有直达车。这既不是「有值」也不是「不知道」，而是**已核实的否定**。

**结构**：`value` 携带结构化否定语义，形状固定：

```
value = {
    "kind": "confirmed_absent",
    "scope": { ... }        // 该否定成立的查询范围，mapping，内容随 data_type 而异
}
```

约束：

| 项 | 要求 |
|---|---|
| `kind` | 字面量 `"confirmed_absent"`。这是下游机械区分「确认没有」与「有值」的唯一判据 |
| `scope` | 必需，非空 mapping。**否定必须有范围**——「没有直达车」只在给定的起讫点与时间窗内成立，脱离范围的否定是无意义的 |
| `sources[]` | 与序 4 的其余情形相同：非空，每项携带 `retrieved_at`。查询成功过才能得出否定 |
| support | **`sourced`**。它是一条被来源支持的事实 |
| token | 与其他 `sourced` 事实相同，按 §4.1 合取。fresh 时为 `verified` |
| `next_action` | 按 §5.1 双向约束——`verified` 时**必须缺席**。「确认没有直达车」不需要用户行动指引；需要的是规划层据此改换乘或改日期，那是规划决策不是证据行动 |

`scope` 的具体键名不由本文件规定，由各 data_type 的采集出口定义。唯一的跨类型约束是「非空」。

**为什么不新开一个 support 态**：`confirmed_absent` 描述的是 `value` 的形状，不是支持程度。它的支持程度就是 `sourced`——有来源、可回读、未经推算。新开 support 态会让四态变五态，而两轴模型的全部价值来自于「support 只回答一个问题」。

### 2.2.2 `confirmed_absent` 的聚合处理

**2026-08-02 裁决，正式生效。**

派生事实若有任一输入是 `confirmed_absent`，按以下规则处理：

| 层面 | 规则 |
|---|---|
| **support 聚合** | 无特殊规则。`confirmed_absent` 的 support 是 `sourced`，按 §2.4 四分支正常参与 |
| **value 传播** | **吸收**。任一输入是 `confirmed_absent` → 派生事实的 `value` 也必须是 `confirmed_absent` |
| **scope 合成** | 派生事实的否定范围**由缺席输入的 scope 决定，多个取并集**——不是全部输入的 scope |
| **禁止** | 不得从 `confirmed_absent` 输入产出数值 |

**scope 只取缺席输入的原因**（2026-08-02 修正）：派生事实否定的是什么，取决于哪些输入缺席，与在场输入的查询范围无关。例：往返时长由去程与回程算出，若回程确认没有直达车而去程正常，则「往返时长不存在」这个否定的范围是**回程的范围**——把去程的范围也并进去会让否定看起来比实际更宽，等于宣称去程也没有车。

**禁止产出数值的理由**：从「没有直达车」算不出「往返时长 = X」。任何试图产出数值的推算都是编造，而编造正是本产品要消灭的失败模式。

support 聚合与 value 传播分属两个层面——前者回答「这个结论多可靠」，后者回答「这个结论是什么」，因此 `confirmed_absent` 作为一个**正交的传播标志**存在，不进入 support 的四态。内核据此把聚合结果表达为三个分量：聚合后的 `support`、`confirmed_absent` 布尔标志、以及来自缺席输入的 `absent_scopes` 并集。

### 2.3 `unknown` 的 reason 取值域

`reason` 是枚举，不是自由文本。取值域与 `next_action.reason_code`（§5.2）共用同一张表。

P1 已完成清点：44 个现状字面量的完整映射见 `docs/contracts/reason-code-inventory.md`，取值域由 10 扩到 14（§4.6）。读取层从持久化 `missing_reason` 到 `reason_code` 的实际映射实现在 `src/trip_decider/evidence_projection.py`。

**`internal_contract_violation` 的额外要求**（2026-08-02 裁决）：该 reason 表示程序缺陷（调用方传了不合法参数），用户无可行动。它除了进 `next_action` 之外，**必须同时写入 run 的 events**，事件类型 `evidence.internal_contract_violation`，载荷含 `domain` / `field_ref` / `raw_reason`（原始 stage 名）/ `data_type`。

这是**排查通道，不是展示通道**：`next_action.detail` 面向用户（「系统内部参数不合法」），事件面向排查者（哪个 stage、哪个参数）。两者受众不同，不能合并。

事件必须在**采集时**写入，不得在读取时写入——读取路径写事件会让两次读取产生不同的事件数，直接违反 I5 的「结构逐字节稳定」。

### 2.4 派生事实的 support 聚合

一个事实若由多个证据推导得出（例：`playable_time_seconds` 由时间窗与往返时长算出，`guided_discovery.py:502-513`），其 support 按以下规则聚合，规则是全序的、可机械求值的：

```
若 任一输入 support == conflicting        → conflicting
否则 若 任一输入 support == unknown        → unknown
否则 若 发生了任何推算步骤，或任一输入 support == estimated → estimated
否则                                      → sourced
```

「发生了任何推算步骤」指该事实的值不是某个输入的原样透传。上式中 `conflicting` 优先于 `unknown`，因为「有数据但打架」需要的用户行动（裁决）与「没数据」（补充）不同，不能合并。

聚合结果必须携带全部输入的 `fact_id`（对应 `schemas/evidence.schema.json` 的 `derivation_detail.input_fact_ids`），否则 I2 无法核对。

`confirmed_absent` 输入的处理见 §2.2.2：support 按上式正常聚合，`confirmed_absent` 标志单独吸收传播。

**说明：`roundtrip_duration_seconds` 案例（偏严是有意的）**

`intercity_rail.py:601-603` 把去程与回程的 `duration_seconds` 相加得到 `roundtrip_duration_seconds`。两个加数都是 12306 的直接读出（`sourced`），和是一个推算步骤的产物。按上式第三分支，该字段应为 **`estimated`**。

P1 清点（`docs/contracts/support-reclassification.md` §3、§6 待裁决 1）提出这偏严，建议引入「无损推算」概念把纯算术排除在外。**本契约不引入该概念，偏严是有意的**，三条理由：

1. 「无损」需要定义，而任何定义都会成为下一个被绕过的口子。加法无损，那乘以固定系数呢？换算单位呢？取最大值呢？一旦开始区分就没有自然的停点。
2. 判定必须可机械求值（`invariants.md` §0 收录标准第 2 条）。「是否无损」不是可以从 `derivation` 字段读出的属性，只能靠人工标注，而人工标注正是五态模型失败的方式。
3. 代价可承受。`estimated` 不阻断决策——裁决 5 明确 `estimated` 可以参与可行性判定，只是必须产生一个 conditional。把一个精确的和标成 `estimated`，后果是多一句「该数值为推算」的提示，不是丢失可用性。

同一理由适用于所有「由 sourced 输入算出」的派生量。若将来发现该规则在实践中造成大量噪声，正确的应对是改进 `next_action.detail` 的措辞，不是给聚合规则开例外。

---

## 3. freshness 轴

### 3.1 判定输入

| 输入 | 来源 | 是否持久化 |
|---|---|---|
| `retrieved_at` | 证据采集时刻 | **是**。这是唯一被持久化的时间输入 |
| `data_type` | 该事实所属的数据类型 | **是** |
| `now` | 读取时刻 | 否 |
| `tolerance_seconds` | 该 `data_type` 的容忍窗 | 否。来自 `docs/contracts/freshness-policy.md` 的策略表，不进入数据文件 |

### 3.2 判定规则

```
若 retrieved_at 缺失或不可解析为带时区的时间戳  → undated
否则 若 now - retrieved_at < 0                  → undated
否则 若 now - retrieved_at <= tolerance_seconds → fresh
否则                                            → stale
```

`now - retrieved_at < 0` 判 `undated` 而非 `fresh`：未来时间戳是数据错误，不得被当作最新。现有代码在 broker 写入侧有一个宽松版本（`evidence_broker.py:157-158` 允许 5 分钟时钟偏移后才报错），读取侧目前无对应检查。

### 3.4 `refresh_failure`：刷新失败封顶

**2026-08-02 裁决（P3a 问题 1 的落法），正式生效。**

**问题**：`evidence_broker._stale_projection` 在实采失败后退回缓存值，保留的 `retrieved_at` 是**原始采集时刻**且按设计必然在容忍窗内。只按 §3.2 判定，这样一条「刚试过刷新、失败了」的证据会被判 `fresh` → token `verified`，比它实际的可信度高。

**落法**：`refresh_failure` 从待清理项**转正为契约字段**。

| 项 | 规定 |
|---|---|
| 性质 | **采集时刻的事实，可持久化**，与 `support` 同性质——「某时刻试过刷新、没成功」写入后不再变化 |
| 不是什么 | **不是展示态**。它不描述「现在该怎么显示」，只记录发生过什么 |
| I1 白名单 | 因此列入 I1 的允许键（`invariants.md` I1），理由：采集元数据，非展示态 |
| 载体 | `value.refresh_failure` / `value.local_transit_refresh_failure`，可选携带 `attempted_at` |

**判定规则（§3.2 的封顶补充）**：

```
存在晚于 retrieved_at 的刷新失败记录 → freshness 封顶为 stale（不得为 fresh）
```

细则：

- `attempted_at` **缺失时仍然封顶**。一条挂在该值上的刷新失败记录必然发生在该值采集之后——采集不到的东西谈不上刷新失败，顺序是结构性保证的。
- `attempted_at` 存在且**不晚于** `retrieved_at` 时**不封顶**。这种记录属于产出这份数据的那次采集本身，不是后续刷新。
- 封顶只能把 `fresh` 压到 `stale`，不会把 `stale` / `undated` 改成别的。

**输入仍然全部来自持久化数据 + `now`**，因此 freshness 依旧不可持久化，I5 不受影响。

**不看 `snapshot.attempted_at`**：`intercity_rail.py:484` 在每次采集**开始**时就写该字段，正常成功采集里它必然早于 `retrieved_at`。把它当刷新失败信号会在每次正常采集上误报。只有显式的 `refresh_failure` 记录才是信号。

**对应的 `reason_code`：`refresh_failed`**（第 15 个），与 `beyond_tolerance_window` 的行动指引明确区分：

| reason_code | 含义 | 对用户说什么 |
|---|---|---|
| `beyond_tolerance_window` | 太久没查了 | 「该数据已超出时效窗，正在重新查询。」——重查就能解决 |
| `refresh_failed` | 刚查过，没查成 | 「刚刚尝试刷新该数据但没有成功，数据源可能暂时异常；当前显示的是上一次采集的结果，稍后会再试。」——重查未必解决，问题在数据源 |

两者的 `kind` 同为 `auto_refetch`、`actor` 同为 `system`，区别在 `detail`——因为用户能做的事相同（等），需要知道的事不同（是我们懒得查，还是对方出问题了）。

### 3.3 为什么 `expires_at` 也不能落盘

`expires_at` 看起来是时刻不是状态，但它等于 `retrieved_at + tolerance_seconds`，即把策略表当时的取值冻进了文件。策略调整后，旧文件里的 `expires_at` 会与新策略矛盾，而读取层无从判断该信任哪个。

现状：`evidence_broker.py:367-376` 的 `_stale_projection()` 把 `expires_at` 写进 `normalized["freshness"]`，该 value 随 `EvidenceItem` 落盘。`schemas/evidence.schema.json` 中 `freshness` 对象把 `expires_at` 与 `status` 都列为 `required`。两处都需在 P4 移除，见 §6.2。

---

## 4. 合取规则：两轴 → 对外展示 token

### 4.1 token 取值域（8 个）

| support \ freshness | `fresh` | `stale` | `undated` |
|---|---|---|---|
| `sourced` | **`verified`** | `sourced_stale` | `sourced_undated` |
| `estimated` | `estimated` | `estimated_stale` | `estimated_undated` |
| `conflicting` | `conflicting` | `conflicting` | `conflicting` |
| `unknown` | `unknown` | `unknown` | `unknown` |

**`sourced_undated` / `estimated_undated` 的可达性**（2026-08-02，P2 实现时发现）

这两个 token 只能由**「有值但不可用」的 `retrieved_at`** 产生——无时区的时间戳、无法解析的字符串、或未来时刻。它们**不能**由缺失的 `retrieved_at` 产生：§2.2 序 4 要求「每个 source 携带 `retrieved_at`」，完全缺失会让序 4 不成立而落到序 5 兜底，结果是 `unknown` 而非 `sourced_undated`。

这是两条规则交互的结果，不是遗漏。语义上也说得通：**「来源没说什么时候采的」与「来源说了但说的话没法用」是两回事**——前者连来源完整性都不满足，后者有完整来源只是时间信息坏了。构造这两个 token 的测试必须用畸形时间戳，用 `None` 会得到 `unknown`。

### 4.2 规则说明

- **「已核实」= `verified` = `support:sourced` ∧ `freshness:fresh`**。这是唯一可以对用户说「这条我有把握」的组合。它由读取层计算，不落盘，也不再是任何枚举的成员。
- **freshness 只能下调，不能上调**。`estimated` 的事实无论多新鲜都不会变成 `verified`。这是冻结不变式（`PLAN.md` v3:72，v4 保留）的直接编码形式。
- **`conflicting` 与 `unknown` 吸收 freshness**。值不存在或存在争议时，「新不新」不改变用户该做什么，展示上不再细分。但 freshness 的实际取值仍需传给 `next_action`（§5），因为「陈旧的冲突」可能通过重查消解，「新鲜的冲突」不能。
- **token 的产生实现必须唯一**。基线报告 §3.3 记录了至少 5 处独立的状态映射实现，M6 记录了四套并行词表。两轴模型若允许多实现，会在三个月内退化回同一状态。可机械核对形式见 `invariants.md` I6。

### 4.3 token 的分解函数

为使 I2 可测，读取层必须同时暴露两个纯函数：

- `token_support(token) -> support`
- `token_freshness(token) -> freshness | null`（`conflicting` / `unknown` 返回 `null`）

I2 的断言形式因此是精确相等，而不是「不高于」的偏序比较——精确相等是更强的条件，且更容易写成测试。

---

## 5. `next_action` 结构定义

### 5.1 何时必须存在

| 条件 | `next_action` |
|---|---|
| token == `verified` | **必须缺席**。有把握的事实不产生噪声 |
| token != `verified` | **必须存在且字段完整** |

这条双向约束是 I3a 的内容。只要求「非 sourced 时必须有」而不要求「sourced 时必须没有」，会导致 UI 无法用它的存在与否做渲染分支。

### 5.2 字段定义

| 字段 | 必需 | 类型 | 取值域 |
|---|---|---|---|
| `kind` | 是 | enum | 见下表 |
| `field_ref` | 是 | string | 指向具体事实的 `fact_id`，或 `subject.field` 的规范化路径 |
| `data_type` | 是 | string | 必须是 `freshness-policy.md` 策略表中已登记的键 |
| `reason_code` | 是 | enum | 见下表 |
| `actor` | 是 | enum | `system` / `user` / `either` |
| `blocking` | 是 | bool | 该事实是否阻断可行性判定。取值规则见 §5.2.1 |
| `detail` | 是 | string | 面向用户的一句话，中文，不含内部标识符 |
| `retry_after_at` | 否 | ISO-8601 | 仅当 `kind == auto_refetch`。**节流阀：此刻之前不再触发重查**（2026-08-03 语义变更，见下） |
| `options[]` | 否 | list | 仅当 `kind == user_choice`。每项含 `option_id` / `label` / `source_ref` |

**`kind` 取值域**

| kind | 含义 | 典型触发 |
|---|---|---|
| `auto_refetch` | 系统会自动重查，用户无需操作 | `feasibility_critical` 的 data_type 超出容忍窗 |
| `user_confirm` | 请用户确认该事实是否仍成立 | 非 critical 的 data_type 超窗 |
| `user_choice` | 存在多个互斥候选，需用户选定 | `support == conflicting`；地点身份歧义 |
| `user_supply` | 请用户直接提供值 | `support == unknown` 且系统无采集途径 |
| `accept_as_is` | 无需行动，仅告知不确定性 | `support == estimated` 且 freshness == fresh |

**`reason_code` 取值域**

| reason_code | 对应 support/freshness |
|---|---|
| `no_source_found` | unknown |
| `collector_not_configured` | unknown |
| `collector_timeout` | unknown |
| `collector_error` | unknown |
| `classification_failed` | unknown |
| `sources_disagree` | conflicting |
| `derived_by_rule` | estimated |
| `derived_by_provider_estimate` | estimated |
| `beyond_tolerance_window` | stale |
| `retrieved_at_absent` | undated |
| `cancelled_by_user` | unknown |
| `input_precondition_unmet` | unknown |
| `internal_contract_violation` | unknown |
| `source_rejected_by_policy` | unknown |

后四个取值为 2026-08-02（P2）新增，方案与依据见 `docs/contracts/reason-code-inventory.md` §4。**2026-08-02 裁决，正式生效。**

当 support 与 freshness 同时非理想（例：`sourced_stale`），`reason_code` 取 freshness 侧的值，因为 support 侧本身不需要行动。

**`retry_after_at` 的语义变更（2026-08-03，随 auto_refetch 触发时机裁决）**

原义是「系统预计重查的最早时刻」——那是**排队模型**的说法，预设有一个调度器会在
那之后来跑。触发时机已裁决为**读取时同步重查**（`freshness-policy.md` §5.1），
没有调度器了，于是这个字段改任**节流阀**：

| | 旧义 | 新义 |
|---|---|---|
| 谁读它 | 调度器 | 每次读取时的重查判定 |
| 含义 | 我预计那时会去查 | **在此之前不要再查** |
| 缺席时 | 不知道什么时候查 | 不节流，本次读取可以查 |

字段形状不变（可选、ISO-8601、仅 `kind == auto_refetch`），因此
`evidence_core` 的既有校验不受影响。变的是读它的人该怎么理解它——**没有这条
记录，读时同步重查会在每次读取都打一次数据源**。

### 5.2.1 `blocking` 的取值规则

**2026-08-02 裁决，P3a 落地。** 此前 §5.2 只说「由 `feasibility_critical` 与当前 support 共同决定」，没说怎么决定，内核在 P2 只用了 `feasibility_critical` 一项。本节补齐。

**语义分工**：

| 概念 | 含义 |
|---|---|
| `blocking = true` | **不能支撑判定**。该事实不足以支持任何可行性结论，依赖它的判定必须停下来 |
| conditional | **能支撑但有条件**。判定可以继续，但结论必须携带一个条件说明 |

两者不是强弱之分，是种类之分。`blocking` 说「别往下走」，conditional 说「可以走，但要说清楚前提」。

**规则**（按顺序，第一个命中的胜出）：

| 序 | 条件 | `blocking` | 是否要求 conditional |
|---|---|---|---|
| 1 | `feasibility_critical == false` | **恒 `false`** | 否 |
| 2 | `support ∈ {unknown, conflicting}` | `true` | 否（已阻断，无需条件化） |
| 3 | `support == estimated` | `false` | **是**（裁决 5） |
| 4 | `support == sourced` 且 `freshness != fresh` | 由 `on_stale` 决定：`auto_refetch` / `block` → `true`；`flag_for_confirmation` → `false` | `flag_for_confirmation` 时是 |
| 5 | `support == sourced` 且 `freshness == fresh` | `false` | 否（此时 token 为 `verified`，根本没有 next_action） |

**已知的不对称（有意保留，记录在案）**：序 3 与序 4 相比，`estimated + stale + critical` 不阻断，而 `sourced + stale + critical`（`on_stale == auto_refetch`）阻断——支持程度更弱的一侧反而更宽松。

这不是笔误。理由：`sourced` 超窗意味着**曾经有过精确值、现在过期了**，重查能把它变回精确，因此在重查完成前停下来是对的；`estimated` 从来就不精确，没有任何重查能让它变精确，conditional 是它的永久正确形态，用 `blocking` 拦住它等于永久拦死一条本来可用的路径。

**裁决补注（2026-08-03）**：不对称维持有意保留。一句话的判据是——**承诺过的失效比从未承诺的模糊更需要拦**。`sourced` 对用户做过「这个值是准的」这一承诺，承诺一旦失效，继续拿它推进就是在替用户维持一个已经不成立的前提；`estimated` 从没做过那个承诺，用户对它的期待本来就是「大概」，把它拦死只会让一条本来能走、只是需要说清前提的路径永久走不通。

**用例化前提**：这条不对称目前只是契约注记，**还不是可观测行为**——`requires_conditional` 由内核产出，消费它的是 P3b 的闸门。auto_refetch 落地后，序 4 会真的触发重查而序 3 不会，行为分叉才出现在读取路径上，那时才钉得住用例。auto_refetch 的实现状态见 `freshness-policy.md` §5.2。

内核把序 3 的「要求 conditional」表达为 `FactVerdict.requires_conditional`。P3a 只产出该标志，**不消费**——消费它的是 P3b 的 29 个闸门改造。

### 5.3 举例

**例一：铁路时刻超出容忍窗，且影响可行性**

```
token: sourced_stale
next_action:
  kind: auto_refetch
  field_ref: fact_rail_outbound_departure_at
  data_type: railway_schedule_fare
  reason_code: beyond_tolerance_window
  actor: system
  blocking: true
  detail: 车次时刻采集于 6 小时前，正在重新查询；重查完成前不据此判定行程可行。
  retry_after_at: 2026-08-02T10:15:00+08:00
```

**例二：地图未能唯一确定目的地行政区**

```
token: unknown
next_action:
  kind: user_choice
  field_ref: fact_destination_district
  data_type: poi_coordinate
  reason_code: no_source_found
  actor: user
  blocking: true
  detail: 未能唯一确定目的地所在行政区，请从下列候选中选择。
  options:
    - {option_id: "361130", label: "江西省上饶市婺源县", source_ref: "source_amap_district"}
    - {option_id: "361102", label: "江西省上饶市广信区", source_ref: "source_amap_district"}
```

**例三：路径规划时长是推算量，但仍在容忍窗内**

```
token: estimated
next_action:
  kind: accept_as_is
  field_ref: fact_local_transit_duration
  data_type: route_duration
  reason_code: derived_by_provider_estimate
  actor: either
  blocking: false
  detail: 当地交通时长为地图服务推算值，实际耗时可能不同。
```

### 5.5 规划结论值不得复述证据状态

**2026-08-02 裁决，正式生效。**

> **规划结论值只允许表达规划层自己的结论（例：没有直达车、无法成行），不允许复述证据层的状态。**

具体禁止：不得新增形如 `*_EVIDENCE_CONFLICTING`、`*_EVIDENCE_MISSING`、`*_EVIDENCE_STALE` 的结论值或 blocker_id。

**理由**：证据状态已经由该事实的 `token` 加 `next_action` 完整承载。在结论层再铸一个字面量，等于开了第二套状态词表——正是 `invariants.md` I6 要消灭的东西。基线报告记录的四套并行词表就是这样一块砖一块砖砌起来的。

**引用而非复制**：结论需要指向某条证据时，blocker 携带 `fact_id`，消费方顺着引用读该事实的 token。这样证据状态永远只有一处定义。

**已按此裁决处置的例子**（`docs/contracts/p3b-gate-inventory.md` §8.2）：

| 提案的结论值 | 裁决 | 理由 |
|---|---|---|
| `RAILWAY_NO_DIRECT_TRAIN` | 接受 | 「没有直达车」是规划层的结论，不是证据状态 |
| `INFEASIBLE_NO_TRANSPORT` | 接受 | 同上 |
| `RAILWAY_EVIDENCE_CONFLICTING` | **驳回** | 复述了 `token == conflicting`，改为 blocker 引用 `fact_id` |

### 5.4 UI 侧要求

`next_action.detail` 必须被渲染。基线报告 §3.4「丢失 3」实测确认，当前 MCP App（`mcp_app_workspace_v1.html:212-268`）只渲染 `evidence_missing` 的中文自由文本列表，完全不引用 `evidence_statuses`。两轴模型若重蹈此路，模型的存在对用户不可见。可机械核对形式见 `invariants.md` I3b。

---

## 6. 相对旧五态模型的映射

对照对象：`schemas/evidence.schema.json` 的 `payload.facts[]` 字段集。

### 6.1 逐字段处置

| 旧字段 | 处置 | 说明 |
|---|---|---|
| `fact_id` | **保留** | 不变 |
| `subject` | **保留** | 不变（entity / relation 两种 oneOf 结构保留） |
| `field` | **保留** | 不变 |
| `value` | **保留** | 不变 |
| `unit` | **保留** | 不变 |
| `support_status`（`verified/sourced/conflicting/unknown`） | **保留字段名，改取值域** | 去掉 `verified`，加入 `estimated`。新取值域见 §1 |
| `derivation`（6 值） | **保留** | 它是 support 的判定输入之一，不是展示态 |
| `derivation_detail.input_fact_ids` | **保留** | §2.4 的聚合规则依赖它 |
| `derivation_detail.estimate` | **保留** | `support == estimated` 时必需 |
| `sources[]` | **保留** | `support == sourced` 的必要条件 |
| `conflict_source_refs[]` | **保留** | `support == conflicting` 的必要条件 |
| `normalization` | **保留** | 与两轴无关 |
| `freshness.retrieved_at` | **保留** | 唯一被持久化的时间输入 |
| `freshness.effective_at` | **保留** | 业务生效时刻（如票价从哪天起生效），与 freshness 轴无关，不参与判定 |
| `freshness.expires_at` | **废弃** | 理由见 §3.3 |
| `freshness.status`（`current/stale/unknown`） | **废弃** | 读时计算 |
| `display_status`（五态） | **废弃** | 由读时计算的 token 取代，不落盘 |
| `display_rule` | **废弃** | 规则版本由唯一的 token 计算实现携带，不逐条重复 |
| `mapping_rule_version` | **废弃** | 它是五态映射的版本号。是否需要一个等价的 support 判定规则版本号【待 Hugin 确认】 |
| — | **新增** `data_type` | freshness 计算的必需输入；当前只存在于 `EvidenceQuery`（`evidence_broker.py:74`），未随事实落盘 |
| — | **新增** `next_action` | 结构见 §5。仅在读取层产出，**不落盘** |

`freshness` 从一个四字段对象收缩为两个字段（`retrieved_at` / `effective_at`）后，是否仍保留 `freshness` 这个嵌套层级，属于 schema 形态问题，本文件不作规定。

### 6.2 需要同步变更的 schema 约束

- `freshness` 对象当前把 `retrieved_at` / `effective_at` / `expires_at` / `status` 四项全列为 `required`。删除后两项后 required 列表需相应收缩。
- `additionalProperties: false` 在 facts 项上生效，因此新增 `data_type` 必须显式加入 properties，否则现有 fixture 会失败。

**注意**：`schemas/` 目录在 P0 阶段不得修改。以上是 P4 的输入，不是本阶段的动作。

### 6.3 运行时枚举的映射（`travel_agent.py:128-131`）

> **终态已确定（P4-b3 收口，2026-08-02）。** 见 §6.3.1。以下映射表保留为
> 历史记录：它描述的是迁移**之前**的状态。

在线路径当时使用的是另一套三态枚举 `EvidenceStatus`：

| 旧 `EvidenceStatus` | 新 support | 备注 |
|---|---|---|
| `sourced` | `sourced` **或** `estimated` | **一对多，需要逐 provider 重新分类**。见下 |
| `missing` | `unknown` | 一对一 |
| `conflicting` | `conflicting` | 一对一 |
| — | `estimated` | 旧枚举**无对应值** |

`estimated` 在旧枚举中不存在，这意味着从三态到四态不是「加一个值」，而是要把当前被标为 `sourced` 的推算量重新分类。已识别的重分类候选：

- 高德路径规划返回的行程时长（`data_type: route_duration`）——服务端推算量，按 §2.2 应为 `estimated`。
- 规划器的默认停留时长与节奏参数（`itinerary_planner.py:160-170` 已自行标为 `"support": "estimated"`，但该字段不受 `EvidenceStatus` 约束，是一套独立的自由字段）。

完整的重分类清单【待验证：需在 P1 阶段逐个 provider 出口清点】。

### 6.3.1 终态：枚举保留为类型载体，词表只此一套

**该待办到此关闭。** 「退役 `EvidenceStatus`」不是终点，词表合一才是——两者
在 P4-b2 中期被混为一谈过，这里写清区别。

| 项 | 终态 |
|---|---|
| 枚举本身 | **保留**。`EvidenceItem.status` 是 §1.3 明文保留的 item 级便捷字段，由 I10 守它不与 facts 聚合漂移；枚举退化为它的类型载体，无危害 |
| 字面量 | **已归一到轴名**。P4-b3 把采集器协议的 `evidence_status: missing/sourced/conflicting` 改为 `support: unknown/sourced/conflicting`（26 处 + 7 处消费点），词表的第二套名字就此消失 |
| 映射实现 | **只此一份**：`evidence_core.support_from_legacy_name`。P4-b2 曾出现第二份（`item_facts` 内联），当场收敛 |
| 唯一出口 | `EvidenceStatus.support`（轴取值）与 `EvidenceStatus.is_usable`（`{sourced, estimated}`）。消费方不再直接读 `.value` |
| `estimated` 缺位 | 已补。枚举现为四态，§6.4 的重分类问题随之消解 |

**为什么不删枚举**：删它要给 `EvidenceItem.status` 换一个类型，收益是少一个名字，
代价是动一个受不变式守护的持久化字段。基线报告 M1 数的是「四套词表」不是「四个类型」
——词表已合一，类型载体留着不构成第二套词表。

### 6.4 这次映射会改变行为的地方

重分类会改变可行性判定的输入。`guided_discovery.py:520-524` 的 `rail_sourced` 判据只接受 `EvidenceStatus.SOURCED`；若某条证据从 `sourced` 重分类为 `estimated`，该判据当前会直接把它当作不可用。这不是可以顺带处理的细节，需要在 P3/P5 明确每个判定点对 `estimated` 的态度。本文件不规定该态度。

---

## 7. 未决问题

| # | 问题 | 状态 |
|---|---|---|
| 1 | `unknown` 的 `reason` 完整取值域 | **已清点**（P1）：`reason-code-inventory.md`，44 个现状字面量。归并方案见其 §4【待 Hugin 批准】，取值域由 10 扩到 14 |
| 2 | 从 `sourced` 重分类为 `estimated` 的完整清单 | **已清点**（P1）：`support-reclassification.md`，3 处需重分类。生效时机由 P3b 承担 |
| 3 | 是否需要 support 判定规则的版本号（替代 `mapping_rule_version`） | 【待 Hugin 确认】。内核已在 `SupportVerdict.rule` 上携带命中的判定序号，可作为版本号的载体 |
| 4 | `freshness` 嵌套层级在收缩为两字段后是否保留 | 未定，属 P4 schema 形态问题 |
| 5 | 各可行性判定点对 `support == estimated` 的接受与否 | **总原则已决**（裁决 5）：可参与判定但必须产生 conditional。29 个闸门的逐点落法由 P3b 前的改造清单承担 |
| 6 | `confirmed_absent` 的聚合处理（§2.2.2） | **已决**（2026-08-02）：正式生效，scope 只取缺席输入的并集 |
| 7 | `confirmed_absent.scope` 是否需要跨 data_type 的统一形状 | 未定。当前只约束「非空 mapping」，键名由各采集出口自定 |
