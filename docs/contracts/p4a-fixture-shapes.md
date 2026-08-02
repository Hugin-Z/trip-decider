# P4-a fixture 形状不一致清单

> 状态：P4-a 产出，**P4-b 的输入**。
> 建立日期：2026-08-02
> 依据：`persistence-v2.md` §10（fixture 重写原则）。
> 用途：收编手工证据构造时逐条记录的形状差异。P4-b 改 facts 形状时，这份清单决定要改哪些地方。

---

## 0. 清点结果

全仓 **59 处**手工证据构造，落在 **9 种不同的键集合**上。

| 处数 | 键集合 | 判断 |
|---|---|---|
| 27 | `domain / evidence_id / sources / status / value` | **缺 `missing_reason`、`conflict_details`**。生产端 `EvidenceItem.to_dict()` 恒写这两个键（值为 `None` / `[]`） |
| 16 | `domain / evidence_id / missing_reason / status / value` | **缺 `sources`、`conflict_details`** |
| 6 | `domain / sources / status / value` | **缺 `evidence_id`**——读取层用它做 `fact_id` 的前身 |
| 3 | `domain / status` | **只有两个键**。既无 `value` 也无 `sources`，生产端不可能产生 |
| 2 | `conflict_details / domain / evidence_id / status / value` | 缺 `sources`、`missing_reason` |
| 2 | `domain / evidence_id / missing_reason / sources / status / value` | 缺 `conflict_details` |
| 1 | 七键全 | **唯一与生产端一致的形状** |
| 1 | `conflict_details / domain / evidence_id / missing_reason / sources / value` | **缺 `status`**——P3a 撞到过的那一类 |
| 1 | `domain / value` | 缺五个键 |

**59 处里只有 1 处与生产端形状一致。**

## 0.1 按文件分布

| 文件 | `EvidenceItem(...)` | 手工 dict |
|---|---|---|
| `test_planning_input_compiler.py` | 17 | 1 |
| `test_product_web.py` | 13 | 12 |
| `test_evidence_broker.py` | 4 | — |
| `test_invariant_i7_*.py` | 4 | — |
| `test_mcp_adapter.py` | 3 | — |
| `test_invariant_i4_*.py` | 2 | — |
| `test_evidence_projection.py` | — | 1 |
| `test_invariant_i2_token_matches_support.py` | — | 1 |
| `test_trip_application.py` | 1 | — |

---

## 1. 逐条不一致与它在 P4-b 的后果

### 1.1 缺 `missing_reason`（27 + 2 + 1 = 30 处）

**现状**：`status == "sourced"` 的证据不写 `missing_reason`。生产端写 `None`。

**P4-b 后果**：**无**。facts 形状里 `reason` 只在 `support == unknown` 时存在，本来就是可选。这一类不一致在 v2 自动消失。

### 1.2 缺 `conflict_details`（27 + 16 + 2 = 45 处）

**现状**：非 conflicting 的证据不写该键。生产端写 `[]`。

**P4-b 后果**：**无**，同 §1.1。

### 1.3 缺 `evidence_id`（6 + 1 = 7 处）

**现状**：直接省略。

**P4-b 后果**：**有**。v2 的 `fact_id` 是引用结构的基石（`persistence-v2.md` §5）——PlanVersion 与候选卡都靠它指向事实。没有 `evidence_id` 的 fixture 在 v2 里无法参与引用解析，会全部落到 R2 的「引用解析失败」分支。

**这 7 处必须在 P4-b 之前补齐。**

### 1.4 缺 `status`（1 处）

**现状**：`tests/test_product_web.py` 的地图证据 fixture。P3a 已修过一次同类问题。

**P4-b 后果**：**有**。v2 保留 item 级 `status` 作为派生便捷字段（§1.3），且由 I10 守它等于 facts 聚合。缺 `status` 的 fixture 会让 I10 无从比较。

### 1.5 「只有 `domain` + `status`」（3 处）与「只有 `domain` + `value`」（1 处）

**现状**：极简 stub，用于只关心某一个字段的断言。

**P4-b 后果**：**有，且最麻烦**。它们连 `value` 都没有，v2 的 facts 形状要求每个 fact 携带 `support` / `data_type` / `retrieved_at`——这些 stub 无法机械转换，必须逐个看它在测什么、重新按工厂声明。

**4 处需要人看，不能批量替换。**

### 1.6 `retrieved_at` 的位置分歧

**现状**：至少三种放法——`value.retrieved_at`、`value.snapshot.retrieved_at`、`sources[].retrieved_at`。生产端三种都用（不同 provider 不同），读取层的 `_retrieved_at` 按优先级依次找（`evidence_projection.py`）。

**P4-b 后果**：**有**。归一规则已定，见 `persistence-v2.md` §1.3.1——fact 级权威且必带，source 级保留表示该来源的采集时刻，其余放法全部废除。

---

## 2. 共享工厂的现状与边界

`tests/evidence_factory.py` 已建立，是全仓唯一证据构造入口。

| 项 | 状态 |
|---|---|
| 产出形状 | **v1**（七键齐全，与 `EvidenceItem.to_dict()` 一致） |
| 支持的 state | `sourced` / `estimated` / `conflicting` / `unknown` / `confirmed_absent` |
| 已收编 | `tests/characterization_support.py`（表征 fixture，验证 diff = 0） |
| **未收编** | 上表 59 处中的其余部分 |

**P4-b 改 facts 形状时只改工厂一处**——这是建它的全部理由。未收编的构造点在 P4-b 会逐个撞上形状变化，收编越早撞得越少。

---

## 3. 给 P4-b 的行动清单

| 优先级 | 动作 | 处数 |
|---|---|---|
| **必做** | 补 `evidence_id`（§1.3） | 7 |
| **必做** | 补 `status`（§1.4） | 1 |
| **必做** | 人工重写极简 stub（§1.5） | 4 |
| **必做** | 定 `retrieved_at` 归一规则（§1.6） | 全部 |
| 建议 | 其余构造点收编到工厂 | 47 |
| 自动消失 | 缺 `missing_reason` / `conflict_details`（§1.1、§1.2） | — |
