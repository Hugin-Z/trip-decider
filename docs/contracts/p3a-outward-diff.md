# P3a 对外契约 diff 报告

> 状态：P3a 已完成的对外契约迁移记录，不是当前待办。
> 建立日期：2026-08-02
> 范围：读取层接管 token 计算所引起的对外返回值变化。落盘内容逐字节不变（那是 P4）；可行性判定的输入与输出不变（那是 P3b）。
> 变化依据分三类：**不变式要求** / **顺带清理** / **其他**。

---

## 0. 一句话摘要

所有携带证据状态的对外字段，从「一个三态字符串」改为「`token` + 可选 `next_action`」。旧字段 `evidence_status` / `status` **直接删除，不做双写**——理由见 §1。

受影响的对外面：**MCP tool 4 个**、**HTTP 端点 3 个**。未受影响的 MCP tool 6 个、HTTP 端点其余部分，字段逐字节不变。

---

## 1. 旧字段的处置方案：直接删除，不双写

**决定：删除 `evidence_status` 与 `evidence_statuses[].status`，不保留一个阶段的双写。**

三条理由：

1. **双写会让 I6 无法转绿。** 双写意味着读取层继续产出 `LIVE` / `STALE` / `MISSING` 字面量，而 I6 的判定就是扫描这些字面量。P3a 的头号闸门是 I6 全仓绿，双写与它直接冲突。
2. **旧字段是错的，不是旧的。** 基线报告 B2 实测确认：`trip_read_model.py:231-238` 在证据条目存在但采集失败时返回 `LIVE`，在证据完全缺席时返回 `MISSING`——方向是反的。保留它一个阶段，等于让每一个还在读它的消费者继续错一个阶段。这与「保留一个过时但正确的字段」性质不同。
3. **消费者全部在仓库内。** 三个宿主面（MCP App、web/app.js、Codex 桥）加测试，没有仓库外的客户端需要迁移窗口。双写要付出的兼容成本没有对应的收益方。

代价：任何仓库外的既有集成会在升级时看到字段消失。当前不存在这样的集成（基线报告 §1.3 列出的三个宿主面都在仓库内）。

---

## 2. MCP tool 逐字段

### 2.1 `read_trip(view="overview")` / `create_trip_task` / `confirm_trip_intent` / `select_trip_candidate` / `submit_trip_evidence`

共用 `TripQueryService.trip()` 的 `presentation` 结构。

**`presentation.evidence_statuses[]`**（4 项：railway / attraction / local_transit / accommodation）

| 字段 | 变化前 | 变化后 | 依据 |
|---|---|---|---|
| `domain` | `"railway"` 等 | 不变 | — |
| `label` | `"跨城铁路"` 等 | 不变 | — |
| `count` | int | 不变 | — |
| `retrieved_at` | ISO-8601 或 null | 不变 | — |
| `status` | `"LIVE"` / `"STALE"` / `"MISSING"` | **删除** | 不变式要求（I2、I6） |
| `token` | — | **新增**，8 取值之一 | 不变式要求（I2） |
| `next_action` | — | **新增**，`token != "verified"` 时存在 | 不变式要求（I3a） |

**取值来源的变化（重要）**：`status` 此前由**计划事件里落盘的展示态**推导——`event.snapshot_status == "STALE"`、`event.schedule_status == "STALE"`（旧 `trip_read_model.py:824-845`）。`token` 现在由证据的 `support` 与读取时刻算出的 `freshness` 合取。两者在以下情形会给出不同结论：

| 情形 | 旧 `status` | 新 `token` | 说明 |
|---|---|---|---|
| 证据采集失败（`status: "missing"`）但条目存在 | `LIVE` | `unknown` | **修正 B2**。旧行为把失败说成可用 |
| 证据完全缺席 | `MISSING` | `unknown` | 语义合并：两者对用户都是「没有结论」 |
| 计划事件带 `snapshot_status: "STALE"`，但证据 `retrieved_at` 在容忍窗内 | `STALE` | `verified` | 见 §5 新问题 1 |
| 该域没有任何计划事件 | `MISSING` | `unknown` + `reason_code: no_source_found` | 现在带原因 |

**`presentation.detailed_itinerary_ready`**

| 变化前 | 变化后 | 依据 |
|---|---|---|
| 条件含 `railway_status in {"LIVE","STALE"}` 且 `accommodation_status in {"LIVE","STALE"}` | 条件含 `is_supported(railway_verdict)` 且 `is_supported(accommodation_verdict)`，即两域的 `support == sourced` | 顺带清理 |

语义等价（旧的两个可用态合起来正是「有来源」），但因为取值来源变了（见上表），在证据缺席而计划事件存在的场景下结果会从 `true` 变 `false`。**这不是可行性判定点**（`freshness-policy.md` §3.1 的三处不含它），因此不违反 P3a 的硬边界，但它会改变 UI 是否展示详细行程。

### 2.2 `read_trip(view="map")`

**`markers[]`**

| 字段 | 变化前 | 变化后 | 依据 |
|---|---|---|---|
| `marker_id` / `name` / `display_name` / `kind` / `event_id` / `day` / `position` / `retrieved_at` | | 不变 | — |
| `evidence_status` | `"LIVE"` / `"STALE"` / `"MISSING"` | **删除** | 不变式要求（I2、I6） |
| `token` | — | **新增** | 不变式要求（I2） |
| `next_action` | — | **新增**，非 verified 时存在 | 不变式要求（I3a） |

**`route_polylines[]`**：同上，`evidence_status` → `token` + `next_action`。其余字段（`route_id` / `geometry_status` / `polyline` / `distance_meters` / `duration_seconds` / `transport_mode` / `route_kind` / `from_marker_id` / `to_marker_id`）不变。

**额外变化**：本地路线段的定级此前会读段上的 `route.schedule_status`（落盘的展示态，旧 `trip_read_model.py:563-570`），现在一律跟随 map 域的判定。**依据：不变式要求（I1 的清理对象不得被读取层消费）**。后果：同一次 map 采集里的各段不再有各自不同的展示态。

**`markers[].token` 的合并规则**：一个地点被多条线索命中时，已有支撑的不被无支撑的覆盖（旧规则是 `MISSING` 不覆盖非 `MISSING`，语义相同）。

### 2.3 `read_trip(view="plan")` 的 `planning_handoff.railway`

| 字段 | 变化前 | 变化后 | 依据 |
|---|---|---|---|
| `status` | 直接透传落盘的 `value.snapshot.status`，缺失时 `"MISSING"` | **删除** | 不变式要求（I2）——透传落盘展示态正是 I2 禁止的 |
| `token` | — | **新增** | 不变式要求 |
| `next_action` | — | **新增**，非 verified 时存在 | 不变式要求（I3a） |
| `retrieved_at` / `outbound` / `return` 等 | | 不变 | — |

### 2.4 `show_trip_candidates` / `read_trip(view="candidates")`

**本阶段无变化。** 候选卡的 `evidence_statuses[]` 由 `guided_discovery._coarse_option` 产出并落盘（`run.json` 的 `result.options`），读取层原样透传。给它加 `token` 需要改生产端，落在 P3b。

已在 `invariant_ledger.json` 登记：`test_i3a_candidate_view_evidence_carries_next_action`，`expected_green_at = P3b`。

### 2.5 未受影响的 MCP tool

`advance_trip_task`、`show_trip_plan`、`revise_trip_plan`、`audit_trip_plan`、`read_trip(view="missing")`、`read_trip(view="audit")` 的返回结构逐字段不变。`show_trip_plan` 内嵌的 `trip` 字段随 §2.1 一同变化。

---

## 3. HTTP 端点逐字段

| 端点 | 变化 | 依据 |
|---|---|---|
| `GET /api/trips/{run_id}` | 同 §2.1 + §2.2（同一个 `presentation`） | 不变式要求 |
| `GET /api/trips/{run_id}/map` | 同 §2.2 | 不变式要求 |
| SSE `/api/trips/{run_id}/events` | 推送的 payload 同 §2.1 | 不变式要求 |
| 其余（`/api/trips` 列表、`/execute`、`/revisions`、`/actions/{id}/retry`、`select_hotel`） | 不变 | — |

---

## 4. 前端渲染变化

| 位置 | 变化 | 依据 |
|---|---|---|
| `mcp_app_workspace_v1.html` | **新增**证据面板与事实卡片：每条事实渲染 token 中文标签 + `next_action.detail`（+ `user_choice` 时的候选列表）。此前完全不渲染 `evidence_statuses`（基线 §3.4 丢失 3） | 不变式要求（I3b） |
| `web/app.js` | 证据列表改渲染 token 标签，并在每条事实下渲染 `next_action.detail`；`blocking` 与非 `blocking` 视觉区分 | 不变式要求（I3b） |
| `web/app.js` 路线样式 | `route.evidence_status === "STALE"` → `isStaleToken(route.token)` | 顺带清理（字段改名的必然结果） |
| `web/styles.css` / MCP App 内联样式 | 新增 `.evidence-next-action` / `.next-action` 等类 | 顺带清理 |
| `web/index.html` | 输入框 placeholder 里的「武汉」改为「某地」 | 其他（I9 的 P1 新发现，属占位默认值） |

`next_action.detail` **渲染在事实卡片内部**，不在全局提示区——它说的是这一条事实缺什么，挪到全局会失去指向。

---

## 5. 本阶段发现的新问题

### 问题 1（需 Hugin 裁决）：缓存降级值现在可能渲染为 `verified`

`evidence_broker._stale_projection`（`evidence_broker.py:359-443`）在实采失败后返回缓存值，并把 `snapshot.status` 改写为 `STALE`、把余票等字段抹成 `UNKNOWN`。但它保留的 `retrieved_at` 是**原始采集时刻**，且按设计必然在 `stale_ttl` 窗内。

新模型下 freshness 只由 `retrieved_at` 与容忍窗决定（§3.2），因此这样一条「实采失败、退回 6 小时内缓存」的证据会被判为 `fresh`，token 为 `verified`——**比旧行为（显示 STALE）更乐观**。

这不是实现偏差，是契约直接推出的结论：数据确实是 6 小时前从 12306 采到的，容忍窗确实是 6 小时。但「我们试过刷新、失败了」这个事实在新模型里没有落点，而它对用户是有意义的。

I2 抓不到这个问题——I2 核对的是 token 与**声明的** support 是否一致，不核对声明的 support 本身对不对。

三个可选方向（本文件不代为裁决）：把「刷新失败」表达为 support 侧的降级；表达为一个独立的 `next_action`；或接受现状并认为 `verified` 是诚实的。

### 问题 2：域级粒度掩盖字段级差异

`_stale_projection` 把余票、票价等字段抹成 `UNKNOWN`，但域级 token 仍是 `sourced` 系列。两轴模型本身是字段级的（`PLAN.md` v3:62 起即如此），当前投影是域级的——一个域内「时刻可靠、余票未知」表达不出来。

字段级投影需要证据落盘时携带字段级 `support`，属 P4 的 schema 工作。

### 问题 3：`blocking` 的不对称已生效，需实测确认可接受

按 §5.2.1 裁决实现后，`estimated + stale + critical` 不阻断，而 `sourced + stale + critical`（`on_stale=auto_refetch`）阻断。契约已记录理由（推算值没有「重查变精确」的路径），但这条要到 P3b 闸门四态化、`estimated` 真正出现在产品路径上，才会有实际样本可看。

### 问题 4：测试 fixture 与生产形状的差距

本阶段有 3 个既有测试因 fixture 不完整而红：缺 `status` 字段、缺 `retrieved_at`、把证据传成 `evidence=` 关键字而非 `result.context.evidence`。生产侧三者都正确（`EvidenceItem.to_dict()` 恒写 `status`；`dynamic_discovery.py:378` 恒写 `value.retrieved_at`）。

这说明既有测试的 fixture 是按「读取层当时读什么」写的，不是按「生产端实际落什么」写的。P4 动落盘契约时会再撞一次，值得先统一到一份共享 fixture。
