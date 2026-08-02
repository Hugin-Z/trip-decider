# D2 清点：`sourced` → `estimated` 重分类清单

> 状态：P1 产出。这是**现状清单**，归类由 `docs/contracts/evidence-axes.md` §2.2 的判定顺序决定，不由现状定义。
> 建立日期：2026-08-02
> 关闭的未决项：`evidence-axes.md` §7 问题 2、`freshness-policy.md` §6 问题 3。
> 证据规则：每条给出 `文件:行号`。

---

## 0. 清点范围与方法

清点 `src/trip_decider/` 下全部 `EvidenceItem(...)` 构造出口（21 处），按 `evidence-axes.md` §2.2 的五序判定逐个定档。判定的关键一条是序 3 与序 4 的分界：

> **序 3 `estimated`**：值由推算产生（`api_estimate` / `model_estimate` / `rule_derived`）。
> **序 4 `sourced`**：值是某个来源字段的**直接读出**，未经跨字段推算。

「直接读出」指值在来源响应中以该字段形式出现。供应商返回的推算量（路径规划时长）不算直接读出。

可行性判定点按 `freshness-policy.md` §3.1 编号：**判定点 1**（候选 `feasibility_status`，`guided_discovery.py:520-536`）、**判定点 2**（`planning_state`，`planning_input_compiler.py:216-227`）、**判定点 3**（17 处 `_blocker()`）。

---

## 1. 需要重分类的出口（3 处）

| # | 出口 | 现状 | 应归 | 经过判定点 | 会改变什么 |
|---|---|---|---|---|---|
| R1 | `agent_actions.py:951` — 地图证据合并路线规划结果 | `SOURCED` | **`estimated`** | 判定点 2、3 | `value.local_transit[]` 的 `duration_seconds` 是高德路径规划的推算量（`data_type == route_duration`）。重分类后 `planning_input_compiler.py:429` 的 `status != "sourced"` 早退会命中，景点与路线不再进入规划输入，`LOCAL_TRANSIT_EVIDENCE_MISSING` / `LOCAL_TRANSIT_DURATION_MISSING` 两个 blocker 被触发 |
| R2 | `agent_actions.py:909` — 路线刷新失败后保留的地图证据 | `SOURCED` | **`estimated`** | 判定点 2、3 | 同 R1。该出口另带 `local_transit_refresh_failure`，在新模型下应转为 `next_action`，见 §3 |
| R3 | `agent_actions.py:1305` — 地图证据合并 | `SOURCED` | **随输入聚合** | 判定点 2、3 | 按 `evidence-axes.md` §2.4，只要任一输入为 `estimated` 则结果为 `estimated`。由于其输入包含 R1/R2 的产物，实际结果恒为 `estimated` |

**这三处是同一件事的三个出口**：高德路径规划时长在当前实现里被标为 `sourced`。`PLAN.md` v4 §6 已把「点对点时间矩阵」的预期 support 写为 `estimated`，本清单确认代码与之不符。

---

## 2. 保持 `sourced` 的出口（8 处）

| 出口 | 判定依据 |
|---|---|
| `destination_runtime.py:89` — 12306 铁路证据 | 车次、时刻、票价均为 12306 响应的直接读出（`intercity_rail.py:586-600` 逐字段读出）。序 4 命中 |
| `destination_runtime.py:153` — 高德行政区证据 | 行政区名称与编码是直接读出。序 4 命中 |
| `dynamic_discovery.py:436` — 高德 POI 实时检索 | POI 名称、坐标、类别均为直接读出（`data_type == poi_coordinate`）。序 4 命中 |
| `agent_actions.py:964` — 已确认的用户意图 | `user_supplied` 按 §2.2 归 `sourced`。序 4 命中 |
| `travel_agent.py:1698` — 用户提交的证据 | 同上 |
| `agent_actions.py:1190` — 刷新失败后保留的铁路证据 | **support 不变，变的是 freshness。** 这一处当前的写法在新模型下是对的：支持程度不因时间流逝而改变 |
| `agent_actions.py:1250` — 刷新失败后保留的画像证据 | 同上。注意它把 `hotel_price_status` 改写为 `UNKNOWN`——这是字段级降级，见 §3 |
| `evidence_broker.py:437` — `_stale_projection` | **support 保留自缓存记录，只改 freshness。** 这是当前实现里唯一已经符合两轴分离原则的地方 |

---

## 3. 需要字段级拆分的出口（2 处）

以下出口的 `EvidenceItem` 整体是 `sourced`，但其 `value` 内部有 support 不同的字段。两轴模型是**字段级**的（`PLAN.md` v3:62 起即如此，v4 保留），因此 item 级的单一 support 表达不了它们。

| 出口 | 情况 |
|---|---|
| `intercity_rail.py:601-603` | `roundtrip_duration_seconds = outbound.duration_seconds + inbound.duration_seconds`。两个加数是直接读出（`sourced`），和是推算步骤的产物。按 §2.4「发生了任何推算步骤 → `estimated`」，该字段应为 `estimated`，而同一 `EvidenceItem` 中的车次与时刻仍是 `sourced` |
| `agent_actions.py:1246-1250` | `hotel_price_status` 被改写为 `UNKNOWN`，`hotel_candidates[].*price*` 被置空，但 item 级 status 仍是 `SOURCED`。即同一 item 内已有 `sourced` 与 `unknown` 两种支持程度并存 |

`roundtrip_duration_seconds` 一条值得单独看：把两个已核实时长相加判为 `estimated`，直觉上偏严。但契约 §2.4 的措辞是明确的，而放宽它需要定义「什么算无损推算」——那是一条新规则，不在本清单的授权范围内。**列为待裁决第 1 项。**

---

## 4. `itinerary_planner.py:160-170` 的 `"support": "estimated"` 不是证据 support

关闭 `freshness-policy.md` §6 问题 3。

```
contract = {key: {"value": ..., "origin": "user_supplied"|"planner_default",
                  "support": "estimated", "editable": True} ...}
```

判定：**不同义。** 三条理由：

1. 它描述的是规划器默认参数（用餐窗口、节奏设置），不是外部世界的事实，因此不是证据。
2. 它的取值是硬编码常量，不由任何判定输入决定——不满足 `evidence-axes.md` §2.1「只允许使用四项输入」。
3. 它与 `origin` 字段并列，`origin` 已承载了「来自用户还是来自默认值」，`support` 在此处是冗余标注。

处置建议：P3 收敛 token 实现时，该字段应改名（例如表达为「这是默认值而非用户设定」），以免与证据 support 撞名。**建议不等于方案**，改名与否由 P3 决定。

---

## 5. 最重要的发现：重分类不是标签变更，是行为变更

`src/` 中存在 **29 处 `sourced` 硬闸门**——形如 `status != "sourced"` 早退或 `is EvidenceStatus.SOURCED` 准入：

| 模块 | 闸门数 |
|---|---|
| `agent_actions.py` | 16 |
| `planning_input_compiler.py` | 7 |
| `guided_discovery.py` | 4 |
| `evidence_broker.py` | 2 |

其中直接决定可行性的有：

- `guided_discovery.py:521` — `rail_sourced` 判据，决定候选 `feasibility_status`（判定点 1）
- `planning_input_compiler.py:269` — 铁路证据准入（判定点 3）
- `planning_input_compiler.py:429` — 景点/路线证据准入（判定点 3）
- `planning_input_compiler.py:1160,1234,1244,1258,1267` — 画像与地图证据准入

**这些闸门当前的语义是「二值」：sourced 就用，非 sourced 就跳过。** 引入 `estimated` 之后，每一个闸门都必须重新回答「estimated 算不算数」——裁决 5 已给出总原则（可以参与判定，但必须产生 conditional），但**该原则在 29 个闸门上的具体落法尚未确定**。

这意味着 §1 的三处重分类不能孤立执行：只改 support 值而不动闸门，效果等同于把地图证据整体废弃（29 个闸门会一致地把它当作不可用），候选与计划会大面积退化为 `UNKNOWN`。

---

## 6. 待裁决

| # | 问题 | 为什么现有契约不够 |
|---|---|---|
| 1 | 两个 `sourced` 值相加得到的和，是 `sourced` 还是 `estimated` | §2.4 措辞「发生了任何推算步骤 → estimated」把无损算术也划进了 estimated。放宽它需要定义「无损推算」，那是一条新规则 |
| 2 | 字段级 support 在 `EvidenceItem` 上如何表达 | 当前 `EvidenceItem.status`（`travel_agent.py:462`）是 item 级单值，§3 的两处已经出现了同 item 内多 support 并存的事实 |
| 3 | 29 个 `sourced` 硬闸门对 `estimated` 的逐个态度 | 裁决 5 给了总原则，没给逐点落法。这是 P3/P5 的输入，不是本清单能定的 |
