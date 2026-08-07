# 不变式契约

> 状态：生效。本文件列出必须始终成立、且必须由测试机械核对的性质。
> 建立日期：2026-08-02（P0 阶段产出）
> 前置阅读：`docs/contracts/evidence-axes.md`、`docs/contracts/freshness-policy.md`、`docs/audit/handover-baseline.md`。
> 证据规则：涉及现有代码的陈述给出 `文件:行号`。不确定的标注【待验证】。
> 当前通过状态以 `tests/invariant_ledger.json` 和实际测试结果为准。
> 下文的“建立时基线”保留不变式立项时的反例，不表示当前仍然失败。

---

## 0. 收录标准

**无法写成测试的性质不得写进本文件。** 一条不变式进入本文件需要同时满足：

1. 陈述是关于程序可观测输出的，不是关于意图或风格的。
2. 存在一个判定程序，对任意给定的仓库状态返回「成立 / 不成立」，不需要人工判断。
3. 已指定承载该判定程序的测试文件名。

`PLAN.md` v3 §4 的冻结不变式之所以失效，正是因为它不满足第 2 条：「展示状态不得高于证据实际支持的状态」在只有一个枚举的模型里无法机械比较。两轴模型把它变成了两个分量的精确相等（I2），从而可测。

本文件中「债务编号」一列指向 `docs/audit/handover-baseline.md` 的债务清单编号（B / H / M / L 系列）。

---

## I1 持久化文件中不得出现展示状态字段

### 陈述

写入 `runtime/` 的任何 `.json` / `.jsonl` 文件，在任意嵌套深度上：

- 键名不得属于**禁用键名集合**；
- 值不得属于**禁用取值集合**。

**禁用键名集合**（初始值，随契约演进，必须显式维护）：
`display_status`、`display_rule`、`evidence_status`、`schedule_status`、`snapshot_status`、`fare_status`、`timing_status`、`freshness.status`、`freshness.expires_at`、`expires_at`、`displayable`、`planning_state`。

**禁用取值集合**（初始值）：
`verified`、`sourced_stale`、`sourced_undated`、`estimated_stale`、`estimated_undated`、`LIVE`、`STALE`、`MISSING`、`DISPLAYABLE_CONDITIONAL_ITINERARY`、`SUPPLEMENTING_DATA`、`sourced_live_snapshot`、`sourced_stale_snapshot`。

**允许出现的例外**（白名单，必须逐项列出理由）：

| 键 | 理由 |
|---|---|
| `support` | 可持久化轴，`evidence-axes.md` §1 |
| `retrieved_at` | freshness 的唯一持久化输入 |
| `effective_at` | 业务生效时刻，与 freshness 轴无关 |
| `data_type` | freshness 计算的必需输入 |
| `refresh_failure`、`local_transit_refresh_failure` | **采集元数据，非展示态**。记录「某时刻试过刷新、没成功」这一发生过的事实，写入后不再变化，与 `support` 同性质。它是 freshness 封顶规则的输入（`evidence-axes.md` §3.4），不是「现在该怎么显示」的结论 |
| `error_detail` | **失败时刻的事实，非展示态**（P5 轮 2 新增，`run.json` 顶层）。只存逃出来的异常类名，写入后不再变化，与 `refresh_failure` 同性质——记的是发生过什么，不是「现在该怎么显示」。它与 `error_code` 是两段式的两段：码保持有限可查表（`travel_agent.RUN_ERROR_CODES`），类型名放这里，两者都不参与展示判定。**为什么明明不在禁用键名集合里也要登记**：本表的既有条目（`support` / `retrieved_at` / `data_type`）同样不在禁用集合里——本表登记的是「看着像展示态、实际不是」的键，作用是让下一个人不必重新论证一遍。不登记不会让 I1 变红，但会让这个判断只存在于某次 commit message 里 |

### 判定方法

递归遍历一个已完成 run 的目录下全部 `.json` 与 `.jsonl` 文件，收集所有 `(键路径, 键名, 标量值)` 三元组，对照上述两个集合与白名单。命中任一即失败，失败信息必须打印命中的键路径以便定位。

判定程序必须对**新写入的文件**生效，因此测试需自己跑一次完整 run 并检查其产出目录，而不是检查仓库里已有的历史 run。

### 建立时基线（已修复）

实测 `runtime/sessions/f4d3aec8-cf6f-49fd-9e09-ff55e4d267c7/plan-version.json`（129,188 字节）中的命中：`timing_status: "estimated"` ×71、`timing_status: "sourced_stale_snapshot"` ×6、`schedule_status: "STALE"` ×6、`snapshot_status: "STALE"` ×6、`evidence_status: "LIVE"` ×5、`schedule_status: "LIVE"` ×5、`display_status: "DISPLAYABLE_CONDITIONAL_ITINERARY"` ×1。写入方为 `travel_agent.py:941-989`。

### 对应测试文件

`tests/test_invariant_i1_no_persisted_display_status.py`

### 债务编号

新增（基线报告未单列此项）。最接近的既有条目是 M6（四套状态词表并存）；H1（PlanVersion 格式回归）是同一处代码的另一个后果。

---

## I2 对外返回值中，展示状态不得高于其依赖证据的实际支持状态

### 陈述

对外返回的每一个展示 token，必须满足：

- `token_support(token) == 该事实依赖证据集合按 evidence-axes.md §2.4 聚合规则算出的 support`
- `token_freshness(token) == 按 evidence-axes.md §3.2 用读取时刻 now 算出的 freshness`（`conflicting` / `unknown` 时该分量为 `null`，此时不比较）

使用精确相等而非偏序「不高于」，因为精确相等是更强的条件，且不需要定义一个有争议的全序。

### 判定方法

参数化测试，两层：

1. **单事实层**：构造 `support × freshness` 的 4×3 = 12 种组合的证据 fixture，对每个对外读取入口断言返回 token 等于 `evidence-axes.md` §4.1 表中的对应格。
2. **聚合层**：构造多输入派生事实，覆盖聚合规则的四条分支（任一 conflicting / 任一 unknown / 有推算或任一 estimated / 全 sourced），断言聚合后的 token。

**必须包含的反例**：一条 `support == unknown`、`value` 缺失但证据条目存在的输入。这正是立项时缺陷的形状——当时读模型在此情形下返回 `"LIVE"`，实测：

```
railway 证据存在但 status=missing  -> [('武汉','LIVE'), ('上饶','LIVE')]
railway 证据完全缺席               -> [('武汉','MISSING'), ('上饶','MISSING')]
railway snapshot UNKNOWN           -> [('武汉','LIVE'), ('上饶','LIVE')]
```

### 建立时基线（已修复）

见上。方向与不变式相反：采集失败显示为可用，完全没采集反而显示为缺失。

### 边界：I2 核对一致性，不核对声明本身的真伪

**2026-08-02 增补。** I2 断言的是「token 与**声明的** support / 算出的 freshness 精确相等」。它**不**断言那个声明本身是对的——若某条证据被生产端错标为 `sourced`（实际应为 `estimated`），I2 依然通过。

这不是漏洞，是分工：I2 守的是「读取层不得篡改或上调证据的自述」，而「证据的自述对不对」是生产端的责任，由别的机制守。

已知的两类落在 I2 边界之外的问题，各自的守卫：

| 问题 | 守卫 |
|---|---|
| 缓存降级值仍在容忍窗内，被判 `fresh` | `evidence-axes.md` §3.4 的刷新失败封顶，由 `resolve_freshness` 的单测覆盖（`tests/test_evidence_core.py` 的 `RefreshFailureCase`） |
| 高德路径规划时长被标 `sourced`，应为 `estimated` | `support-reclassification.md` §1；P3b 的重分类，由 I7 的 `estimated` 分支覆盖 |

写测试时不要试图用 I2 去抓这两类问题——I2 抓不到它们，硬凑只会让 I2 的语义变糊。

### 对应测试文件

`tests/test_invariant_i2_token_matches_support.py`（读取层）、`tests/test_invariant_i2_kernel_token_matches_support.py`（内核）

### 债务编号

B2（缺失/未知证据被展示为 LIVE，违反冻结 invariant）；相关 M6。

---

## I3 每个非 sourced 的 support 态必须携带 next_action，且 UI 必须渲染

拆为两条独立可测的子不变式。

### I3a 结构侧

**陈述**：对外返回的每个事实，`token == verified` 时必须**不带** `next_action`；`token != verified` 时必须带 `next_action`，且其全部必需字段存在、取值落在 `evidence-axes.md` §5.2 定义的域内。

双向约束是必要的：只要求「非 verified 时有」，UI 就无法用它的存在与否做渲染分支。

**判定方法**：遍历每个 MCP tool 与每个 HTTP 读取端点的返回值，递归找出所有带 token 的事实节点，逐个断言上述双向条件；对 `next_action` 的每个枚举字段断言取值 ∈ 域；对 `kind == auto_refetch` 断言 `retry_after_at` 存在且可解析；对 `kind == user_choice` 断言 `options` 非空且每项字段完整。

**建立时基线（已修复）**。当时无 `next_action` 结构。最接近的信息载体是 `evidence_missing`（中文自由文本列表）与 `roundtrip_transport.missing_reason`，且 `evidence_statuses` 中没有原因字段。当前结构由 I3a 对应测试守卫。

**对应测试文件**：`tests/test_invariant_i3a_next_action_required.py`

### I3b UI 侧

**陈述**：面向用户的渲染层，对任一携带 `next_action` 的事实，其渲染输出必须包含该 `next_action.detail` 的文本。

**判定方法**：**采用弱形式**（裁决 4，2026-08-02）。静态断言渲染源码中存在对 `next_action` 与 `detail` 的引用，且该引用位于事实卡片的渲染路径上。仓库已有同类静态断言的先例（`test_mcp_adapter.py:379-393` 对 `app_html` 做 `index()` 与 `assertIn` 检查）。

裁决理由：`requirements.lock`（44 行）中不存在任何浏览器驱动或 DOM 实现，为一条不变式引入浏览器依赖不划算。

**已知覆盖缺口**：弱形式能抓住「字段被完全忽略」这一立项时的失败模式，抓不住「引用了但渲染在不可见位置」。接受该缺口。

**建立时基线（已修复）**。当时 MCP App 候选卡未渲染
`evidence_statuses` 与 `next_action`。当前 MCP App 和 Web 都由 I3b 的静态守卫核对。

**对应测试文件**：`tests/test_invariant_i3b_ui_renders_next_action.py`

### 债务编号

B1（五态在产品路径不存在）、M2（STALE 不暴露刷新信号）、M3（`evidence_statuses` 与 `roundtrip_transport` 字段不对称）、基线报告 §3.4「丢失 3」（UI 不渲染证据状态）。

---

## I4 `stale_allowed == False` 的 data_type 不得以缓存值参与可行性判定

### 陈述

对任一 `data_type` 满足 `freshness-policy.md` 表中 `stale_allowed == False`：若本 run 的实采未成功，则该事实必须以 `support == unknown` 进入下游，且不得有任何缓存值出现在可行性判定点（`freshness-policy.md` §3.1 所列三处）的输入闭包中。依赖该事实的可行性结论不得为无条件可行。

### 判定方法

对每个 `stale_allowed == False` 的 data_type（按 `freshness-policy.md` §2.2 表，**当前仅 `hotel_price`**；`seat_availability` 已按裁决 2 删除）构造场景：缓存中存在一条该 data_type 的有效记录，本 run 的实采返回失败。然后断言三件事：

1. 缓存层不返回该记录；
2. 该事实在读取层的 token 为 `unknown`，且 `next_action.blocking == true`；
3. 依赖它的候选 `feasibility_status` 不等于 `CONDITIONALLY_FEASIBLE`，且计划的 `planning_state` 不等于 `PLAN_READY`。

三条必须全测。只测第 1 条不足以证明不变式贯穿到判定层。

### 已作废的优先级重估（2026-08-04，第五次实测后）

> **2026-08-05 更正：** 更大样本确认高德 POI 的 `business.cost`（旧响应为
> `biz_ext.cost`）在约六成住宿 POI 中可得。下面十条样本恰好全缺，因而把
> “该批次未返回”误写成了“字段不存在”。本段只保留为历史记录，不再是裁决。

hotel_price 五次实测五次被宿主点名「无可靠数据源」，因此实查了一次高德 POI 的
可得性，看够不够支撑「价格区间」这个粒度。

**结论：不够。数据源侧一个价格字段都没有。** I4 维持登记。

实查（婺源 adcode 361130，`/v5/place/text` 取 10 家住宿，`show_fields` 把
business / indoor / navi / photos / children 全要上）：

| 查什么 | 结果 |
|---|---|
| `business` 的全部非空键 | `keytag` / `rating` / `rectag` / `tel` / `business_area` |
| 整份响应里 `cost` | 0 次 |
| 整份响应里 `price` | 0 次 |
| 整份响应里 `avg_price` | 0 次 |
| 整份响应里 `均价` | 0 次 |

唯一沾边的是 `rating`（3.2–4.9），那是**评分不是价格**，两者之间没有任何可推
导的关系——拿评分折算房价正是「不猜」要防的那种编造。

所以这不是「精度不够」而是「字段不存在」：给 I4 解冻需要**另接一个数据源**
（订房平台一类），属新增外部依赖，不在当前冻结范围内。

**给冻结决策的量级估计**（若将来要做）：新数据源的接入本身不大，难的是它带来的
连锁——新 data_type 的 freshness 策略、证据门、`stale_allowed` 判定、以及
hotel_price 一旦可得，`I4` 的第 2、3 条断言才第一次有机会跑起来。建议不要在
冻结前塞。

### 当前状态：已收尾（2026-08-05）

高德 POI 明确返回的住宿参考价现在产出字段级
`support=estimated` / `data_type=hotel_price`；字段缺席产出 `unknown`，绝不从
评分、星级或地区均价推导。该字段不是实时可订价格，零容忍与禁止缓存复用策略
保持不变。I4 的登记红项已删除。

#### 历史阻塞说明（已失效）

立项时 `stale_after_failure()` 的缓存层行为已正确，但当时的测试只覆盖第 1 条；
`hotel_price` 尚无生产者，第 2、3 条在 P5 落地前无法构造。该阻塞已于
2026-08-05 随 `hotel_price` 字段级生产者解除。

### 对应测试文件

`tests/test_invariant_i4_non_stale_types_blocked.py`

### 债务编号

M4（跨字段一致性无校验，且外部可注入）；相关 M2。

---

## I5 freshness 必须由读取时刻决定

### 增列理由

I1 只禁止写入展示状态字段，但可以被绕过：不写 `status` 而写 `expires_at`，或写一个名字不在禁用集合里的等价字段。I5 从行为侧封住这个口子——如果 freshness 真的是读时算的，那么同一份文件在不同时刻读取必然产生不同结果。这是「不可持久化」唯一的可机械核对表述。

### 陈述

给定同一个已完成 run 的持久化目录，用两个不同的读取时刻 `t1` 与 `t2` 读取（`t2 - t1` 跨过至少一个 data_type 的 `tolerance_seconds`）：

- 返回值的**结构部分**必须逐字节相同；
- 返回值中**至少一个事实的 token 的 freshness 分量**必须不同。

「结构部分」指剔除全部 token 与 `next_action` 后的剩余内容。

### 判定方法

注入可控时钟（`EvidenceBroker` 已支持注入 `clock`，`evidence_broker.py:131-134`；读取层需要同等能力）。用同一 run 目录读两次，对剔除 token 与 `next_action` 后的结果做规范化 JSON 序列化后比较字节相等；对完整结果断言至少一处 freshness 分量不同。

### 建立时基线（已修复）

当时展示态在写入时冻结（见 I1 的建立时数据），读取时刻不影响输出。

### 对应测试文件

`tests/test_invariant_i5_freshness_is_read_time.py`

### 债务编号

新增（源自背景决定 2 与 3）。相关 H1。

---

## I6 展示 token 只能由单一实现产生

### 增列理由

基线报告 §3.3 实测：状态映射当时散落在至少 5 处独立实现，M6 记录了由此产生的四套并行词表。两轴模型若允许多实现，会退化回同一状态。这条不变式是防止重演的机械手段。

### 陈述

`src/` 下除唯一的 token 计算模块外，任何文件不得出现展示 token 字面量（取值集合同 I1 的禁用取值集合中的 token 部分），也不得出现 support→token 或 freshness→token 的映射表。

### 判定方法

静态扫描 `src/` 全部 `.py` 与前端资源文件，搜索 token 字面量，白名单为唯一的 token 计算模块与唯一的渲染层常量表。命中白名单外的位置即失败，失败信息打印文件与行号。

前端资源（`mcp_app_workspace_v1.html`、`web/app.js`）允许出现 token 字面量用于**样式映射**，但不得出现任何由 support 或 freshness 推导 token 的逻辑。这一区分靠白名单显式声明，不靠扫描器判断。

### 建立时基线（已修复）

见上述 5 处实现。

### 对应测试文件

`tests/test_invariant_i6_single_token_implementation.py`

### 债务编号

M6（四套状态词表并存）；基线报告 §3.3。

---

## I7 `conflicting` 与 `unknown` 不得静默进入硬约束判定

### 增列理由

这是 `PLAN.md` v3:74 的执行红线，v4 保留。立项时它既没有实现也无法检验：`EvidenceStatus.CONFLICTING` 会被折叠成 `MISSING`，`conflict_details` 完全丢失。红线必须要么可测，要么删除；v4 选择保留，因此给出下述判定方法。

### 陈述

对每个可行性判定点（`freshness-policy.md` §3.1 所列三处），若其输入闭包中存在 `support ∈ {conflicting, unknown}` 的事实，则：

1. 输出不得是无条件可行结论（候选不得为 `FEASIBLE`；计划不得为 `PLAN_READY` 且 `conditional_blockers` 为空）；
2. 输出必须携带一个指向该事实的条件或 blocker；
3. 该事实在对外返回值中的 token 必须原样为 `conflicting` 或 `unknown`，不得被折叠为另一个。
4. **（准入过滤形态，2026-08-04 扩充）** 若该判定点是**准入过滤**——即它的输出不是「给这个对象什么结论」而是「这个对象还进不进结果集」——则被过滤掉的对象必须进入**显式退回区**，且退回项携带**原样 token + `reason` + `next_action`**；退回区必须在对外返回值中可见。

第 3 条是关键：它禁止「用降级掩盖不确定」这一当前实际发生的做法。

第 4 条防的是同一件事的另一个入口。**两者的共同敌人是信息消失**：候选卡上把 `unknown` 显示成可用，与候选集里悄悄少了一个城市，是同一种病——前者掩盖不确定，后者让不确定连同对象一起消失，而后者更难发现，因为**没有东西可看**。

**这是扩充覆盖面，不是放宽既有断言。** 前三条一字未改，且改造后必须仍然会红（见判定方法的 D6 要求）。扩充的理由：能力 A 引入了「准入过滤」这一**新的判定形态**——I7 原文只覆盖「判定点消费证据并产出结论」的形态，其中对象始终在结果集里，所以「不静默」等价于「token 不折叠」。过滤形态下对象会离开结果集，此时「不静默」的正确表达是**退回区可见且可追问**。

**裁决出处：Hugin 确认，2026-08-04。**

**扩展分支（裁决 5，2026-08-02）**：`support == estimated` **可以**参与可行性判定，但不得产出无条件可行结论——即 `estimated` 输入必须至少产生一个 conditional。该分支归入 I7，不新开不变式。

与上述三条的关系：`estimated` 只受第 1 条约束（不得无条件可行），不受第 2、3 条约束以外的额外限制——它必须携带 conditional，且其 token 必须原样是 `estimated` 系列之一，不得被上调为 `verified`（后者已由 I2 覆盖）。

### 判定方法

对每个判定点，分别注入 `support == conflicting`、`support == unknown`、`support == estimated` 的输入（三者分开测，不合并），断言：

- `conflicting` / `unknown`：上述三条全部成立。`conflicting` 的用例必须同时断言 `conflict_details` 在返回值中可见。
- `estimated`：第 1 条成立（不得无条件可行），且输出至少携带一个指向该事实的 conditional。
- **准入过滤形态（第 4 条）**：构造一个 railway 为 `unknown` 的候选放进池子，断言它**出现在 `rejected_candidates` 而不是消失**，且其 token 原样为 `unknown`、带 `reason` 与 `next_action`。

**D6 双向要求**（这条扩充能否被信任的前提）：

| 注入 | 必须响的断言 |
|---|---|
| 去掉退回区（被过滤项直接消失） | **新的第 4 条** |
| 折叠 token（把 `unknown` 显示成别的） | **老的第 3 条**，且在退回项上同样成立 |

老四条用例改造后若有任何一条变成恒真，说明扩充把它们架空了——那不是扩充，是放宽。

### 建立时基线（已修复）

`conflicting` 被折叠为 `MISSING`，第 3 条直接失败。第 1、2 条在 `unknown` 输入下部分成立（`guided_discovery.py:520-536` 的 `rail_sourced` 判据会使 `feasibility_status` 落到 `UNKNOWN`），但无测试覆盖。

### 对应测试文件

`tests/test_invariant_i7_conflicting_unknown_never_silent.py`

### 债务编号

M1（`CONFLICTING` 证据被折叠为 `MISSING`，`conflict_details` 完全丢弃）；`PLAN.md` v3:74。

---

## I8 每个 data_type 必须在策略表中登记，且每条登记必须有生产者或被显式标记为预留

### 增列理由

freshness 无法对未登记的 data_type 计算，静默默认会让新数据源以未定义的新鲜度语义进入决策。反向的问题同样实在：本次核对发现 8 个已登记 data_type 中有 4 个从未被任何生产者使用（`freshness-policy.md` §1），它们的配置从未被执行过，因而其取值从未被验证过——这类「看起来配好了」的条目比缺配置更危险。

### 陈述

策略表指 `freshness-policy.md` §2.2 的权威登记表，**不是** `evidence_broker.py` 的 `FRESHNESS_POLICIES` 字典——后者是待迁移的现状（`freshness-policy.md` §1）。

- **正向**：`src/` 中任何构造证据的位置所产出的 `data_type` 字面量，必须属于策略表的键集合。
- **反向**：策略表中 `status == active` 的每个键，必须至少有一个 `src/` 中的生产者。
- **补偿**：`status == planned` 的每个键必须携带非空的 `planned_for`；`status == reserved` 的每个键必须**没有**生产者（否则它应当是 `active`）。

**2026-08-02 修订说明**：反向规则原表述为「必须至少有一个生产者，或被显式标记为 `reserved`」。裁决 2 要求 `hotel_price` 保留为活跃契约项但它确实无生产者，两者不可兼得，故引入第三态 `planned` 与上述补偿规则。修订理由与替代方案见 `freshness-policy.md` §2.1.1。**该修订需 Hugin 复核。**

### 判定方法

静态扫描 `src/` 收集所有传入证据构造路径的 `data_type` 字面量，得到集合 P；解析 `freshness-policy.md` §2.2 得到键集合 K 及各键的 `status`。断言：

1. `P ⊆ K`
2. `{k ∈ K : status(k) == active} ⊆ P`
3. `∀ k ∈ K : status(k) == planned → planned_for(k) 非空`
4. `∀ k ∈ K : status(k) == reserved → k ∉ P`

`evidence_broker.py:79-80` 的 `EvidenceQuery.__post_init__` 已在运行时实施了正向约束的一半（只覆盖走缓存的路径）。I8 把它扩展到静态与双向。

### 当前状态：成立（P1 转绿）

按裁决 2 处理登记表后四条规则全部满足：`P = {railway_schedule_fare, destination_profile, route_duration, poi_coordinate}`，四者均为 `active`；`hotel_price` 为 `planned` 且 `planned_for = P5`；`opening_hours` 与 `ticket_price` 为 `reserved` 且无生产者；`seat_availability` 已从表中删除。

### 对应测试文件

`tests/test_invariant_i8_data_type_registry_closed.py`

### 债务编号

新增（本次 P0 核对发现）。

---

## I9 不得存在城市专属逻辑

### 增列理由

`PLAN.md` v3 架构红线 1「不得存在任何城市专属的代码或配置」在 v4 §3.1 被拆分，裁决 1（2026-08-02）采纳拆分：

- **「不得有城市专属逻辑」保留为红线**，可机械扫描，白名单为 `tests/` 与 `fixtures/`。这一条成为 I9。
- **「中文词表 / 行政区后缀」降级为非红线**，不属于违规。因此 `guided_discovery.py:715,723-736` 与 `travel_agent.py:55-61` 不在 I9 的判定范围内。

红线若不可机械核对就不是红线——v3 §4 的冻结不变式已经演示过这一点。

### 陈述

`src/` 下的任何文件不得包含**具体地名字面量**。判定范围限于地名，不含语言相关的通用词表（行政区后缀、意图标记词、分词词表）。

白名单：`tests/`、`fixtures/`、`examples/`、`docs/`、`schemas/`、`plans/`。这些目录允许出现地名。

### 判定方法

静态扫描 `src/` 下全部文件（`.py` / `.json` / `.html` / `.js` / `.css`），搜索**地名字面量集合**。命中即失败，失败信息打印文件、行号与命中的地名。

**地名字面量集合**由测试显式维护，P1 种子清单来自两处实测：当时位于 `src/trip_decider/destination_catalog.json`（P5 轮 1 已移到 `examples/destination_catalog.json`）的 28 个 `name` 字段取值，以及 `PRODUCT.md:22,50-56` 自述的已验证链路涉及的地名。该清单是本不变式的一部分，新增地名后必须同步扩充——清单不完备会导致漏判，但不会导致误判。

清单的出处随文件搬走了，清单本身**不跟着搬**：它是扫描器的判据，与被扫的数据在哪无关。种子来自哪份文件是历史事实，记在这里是为了让下一个人能复核清单是怎么来的。

### 当前状态：成立（P5 轮 1 转绿）

转绿动作是**移目录，不是放宽判定**：`destination_catalog.json` 整档移到 `examples/`（白名单目录），`src/` 下不得出现地名字面量这一条原样保留，扫描范围、种子清单、白名单三者都没动。

移动前实测该文件在 `src/` 下**零读取点**——唯一读者 `destination_discovery.py` 早已删除，`pyproject.toml` 的 `package-data` 也只收 `*.html`，它从来没被打进包。因此没有读取路径需要同步。

转绿后的负向验证：向 `src/trip_decider/trip_query.py` 注入一个地名，扫描器如实报出文件、行号与命中的地名（D6）。绿是因为 `src/` 里确实没有了，不是因为扫描器瞎了。

### 对应测试文件

`tests/test_invariant_i9_no_city_specific_logic.py`

### 债务编号

基线报告 §4「`PLAN.md:35`（架构红线 1）」行。

---

## I10 持久化证据的 item 级 `status` 必须等于其 facts 聚合

### 增列理由

`persistence-v2.md` §1.3 把 support 从 item 级改为字段级，但保留 item 级
`status` 作为派生的便捷字段——29 处闸门刚在 P3b 统一到 `EvidenceStatus.is_usable`，
直接删掉会把它们全部推倒重来。保留一个派生字段就必须守它不漂移。

### 陈述

任何持久化证据对象的 item 级 `status`，必须等于其 `facts[]` 按
`evidence-axes.md` §2.4 聚合规则算出的结果。

### 判定方法

扫描一个已完成 run 目录下全部证据对象，逐条用 `facts[]` 重算聚合并与 `status`
比较。不等即失败。

**实现约束（裁决 13.3）**：重算**必须调用内核的 `aggregate_support`**，不许写入侧
自己实现一份聚合——否则这条不变式守的就不是「不漂移」，而是「两份实现恰好一致」。

写入侧 import 内核算 support **不违反 I6**：I6 管的是 token，support 聚合不是 token。

### 建立时状态：未生效

字段级 facts 形状属 P4-b，本批只收录文档。

### 对应测试文件

`tests/test_invariant_i10_item_status_matches_facts.py`（随 P4-b 落地）

### 债务编号

P3a 问题 4（域级粒度掩盖字段级差异）。

---

## I11 import 不得产生磁盘副作用

### 增列理由

基线报告 M8：`travel_agent.py` 在模块尾部构造 `DEFAULT_AGENT_STORE`，于是任何
`import trip_decider.travel_agent` 都会 `mkdir` 加全量读盘。本次核对自己就撞到过
这个副作用（接手基线报告 §0 记录了它在只读摸底期间新建了一个 session 目录）。

### 陈述

`import trip_decider.<任一模块>` 不得创建或读取 `runtime/` 下任何路径。

### 判定方法

子进程中 patch `Path.mkdir` / `Path.open` / `Path.read_text` 记录被触碰的路径，
逐个 import 全部产品模块，断言没有任何 `runtime/` 路径被触碰。

用子进程而不是同进程：同进程里模块可能已被别的测试导入过，副作用发生在
patch 之前就看不见了。

### 当前状态：成立（P4-a 转绿）

默认 store / broker / 应用服务 / 查询服务 / 服务组合全部改为显式工厂
（`default_agent_store` 等），首次调用时才构造。

### 对应测试文件

`tests/test_invariant_i11_import_has_no_disk_side_effect.py`

### 债务编号

M8（模块级 I/O 副作用与脆弱的路径假设）。

---

## I12 通过证据校验的提交，规划器消费不得抛异常

### 增列理由

首次真实宿主实测（Claude Desktop MCP，2026-08-03）的 P0：宿主按 `railway_manual`
动作声明的 `required_fields`（`outbound` / `return` / `fare` / `source`）手工提交
铁路证据，四层校验（status / evidence_id / domain / sources）全过，事件流写下
「12306 查询取得有效证据」，随后 `make_rail_event` 抛 `KeyError: 'origin_station'`，
run 落 `PLANNER_ACTION_FAILED` 且不再派发动作。

宿主把声明要的四个键全给了，仍然过不了消费——**声明的表与消费的表不是同一张**
（D2 的变体）。这类缺陷的可观测症状最坏：门口说「有效」，屋里崩在一个与病因隔着
整条链路的位置，错误码 `PLANNER_ACTION_FAILED` 指向规划器而真正的病因在提交形状。

### 陈述

凡通过 evidence 校验被接受（`submit_evidence` 返回而未抛异常）的证据提交，
规划器消费它时不得抛异常。校验通过是消费成功的**充分条件**。

**2026-08-04 扩展到全部可提交域。** 原条只落了 railway。第三次实测在 map 域
撞出同一形状：宿主提交「线路」措辞的班车证据（`line` / `board_at` /
`alight_at` / `fare`，无 `from` / `to` / `duration_seconds`），而 map 域
**根本没有提交门**——提交被静默接受、事件流写下「取得有效证据」，编译器随后
产出 0 个事件加一个 `MAP_INPUT_UNAVAILABLE`，需求仍缺、动作重派，宿主眼中
就是「反复被拒」且拿不到任何说明，最终只能手排时间轴。

「消费失败」不限于抛异常：**产出 0 个事件加一个 blocker，与抛异常是同一件事的
两种表现**——都是「门放行了、屋里没成」。判定按后果，不按异常类型。

覆盖状态：railway ✅（`_validate_railway_value`）、web ✅（`_validate_web_value`）、
map ✅（`_validate_map_value`，2026-08-04 补）。新增可提交域**必须同时补门**，
由 `test_invariant_i12_all_domains.py` 的矩阵守。

### 覆盖面：四段，不是两头（2026-08-05 第三次翻车后重画）

同一扇门翻了三次，每次都在上一次没画到的那一段：

| 轮次 | 症状 | 漏掉的那段 |
|---|---|---|
| 一 | railway 证据过门后 Planner KeyError | 消费 |
| 二 | map 域根本没有门，形状不合的静默通过、死在编译器 | 提交 |
| 三 | 门收下了、事实也解析了，返回体却报 `accepted: false` | **入库与解析之间的回报** |

第三次尤其说明问题：只测两头（提交拒不拒、编译崩不崩）**看不见它**——两头都
是绿的，宿主却连交三轮拿不到一个字段名，最后止损。

**所以覆盖面定义为四段，任何一段不接都必须红：**

1. **提交**——不合契约要在门口被拒，且报错**点名**缺哪个键；
2. **入库**——收下的要真的出现在 `current_run_evidence` 里；
3. **解析**——入库的要产出字段级 facts（条数 > 0），投影能重建业务字段，
   且**返回体回报的条数与实际落盘条数相等**（这一条专防第三次那种「说的和
   做的不一样」）；
4. **消费**——编译器读得动，不抛异常、不产 0 事件加 blocker。

矩阵的夹具用**宿主实测的真实提交形状**，不用自造的理想形状：三轮事故的三份
提交都已入 `HOST_ROUND_SIX_SUBMISSIONS` 与 `HOST_SHUTTLE_SUBMISSION`。
理想形状测不出宿主会怎么写。

推论：校验必须吃**与规划器同一个视图**。字段级投影（`usable_fact_values`）会把
support 不可用的字段整个丢掉，在投影之前的原始 mapping 上校验，会放行一份投影后
缺键的证据——门就又比消费松了。

### 判定方法

三条，都在对应测试文件里：

1. **组合穷举**：必填字段的每一个子集各提交一次，断言结局只有「门拦下」或
   「规划器跑通」两种，不存在「门放行 + 规划器抛异常」。
2. **边界形状**：方向整体缺席 / 空对象 / 非映射 / 两向皆无 / 已核实无直达 /
   完整，各一例。
3. **结构守卫**：AST 扫 `make_rail_event` 里所有 `train["..."]` 下标，断言键集合
   等于登记常量 `RAIL_EVENT_REQUIRED_TRAIN_FIELDS`。新增直取字段而忘了同步常量
   即转红——靠人记得同步两张表正是事故本身（D20）。

第 3 条是本条不变式**能长期成立**的关键。1、2 只证明当下一致，3 证明将来不漂移。

### 恢复路径也在范围内

提交门只管新提交。门落地之前写进盘里的证据恢复回来时不会再过门，因此消费侧另有
一层：`_compile_railway` 发现某方向缺可排程字段时退回**既有的**判定点
`RAILWAY_{方向}_MISSING`（该方向排不出车次事件），不崩、也不给缺失字段编默认值——
车站名编不出来。

### 当前状态：成立（P5 轮 3 转绿）

三个消费点共用一份常量 `itinerary_planner.RAIL_EVENT_REQUIRED_TRAIN_FIELDS`：
提交门、手工动作的 `required_fields`、编译器的方向可排程判定。

### 对应测试文件

`tests/test_invariant_i12_validated_evidence_never_crashes_planner.py`
（端到端链路另见 `tests/test_user_supply_railway_end_to_end.py`）

### 债务编号

宿主实测 P0-1（user_supply 铁路证据端到端）。

---

## I13 单次 MCP 工具调用的墙钟时间有上界

### 增列理由

第二次真实宿主实测（Claude Desktop MCP，2026-08-04）的 P0：宿主主动选用了本服务、
intent 一次填对、零试错——然后**卡死 4 分钟**，超时放弃，回退去 web search。
宿主侧原文：「No result received from the Claude Desktop app after waiting 4
minutes. The local MCP server providing this tool may be unresponsive, crashed,
or not running.」

归因（本轮实测复现）：`select_trip_candidate` 之后的动作循环停在
`web` 动作——那是只有外部才能做的 `codex_web_research`。循环**算出**了
「走不动了，要外部补证据」，但这个结论只有后台线程那一支会落到 run 状态上；
`execute_trip` 的同步支算出同一个结论后直接丢掉。于是 run 永远停在 `RUNNING`，
宿主每次 `advance_trip_task` 都拿到 `checkpoint=RUNNING`，一直到自己超时。

单次调用**都在 10 秒内返回**——没有任何一次调用「慢」。坏的是**总时长无界**：
没有任何一次调用能让宿主离终点更近。所以上界不能只盯单次耗时，还要有
「循环必须能到达检查点」这一条，否则单次达标、整体照样死。

### 陈述

1. **单次上界**：任何 MCP 工具调用的墙钟时间不得超过
   `mcp_adapter.MCP_CALL_BUDGET_SECONDS`（当前 45 秒；宿主超时线是 60 秒级，
   留出传输与序列化余量）。采集慢不是豁免理由——慢采集必须在后台线程里跑，
   本次调用只负责踢一脚并在 `wait_seconds` 内观察。
2. **可终止**：动作循环算出 `NEED_USER_INPUT` 之后，run 必须落到一个宿主
   认得的检查点状态。同步支与后台支**共用同一个落状态入口**
   （`TripApplicationService.settle_action_loop`）——两处实现、只有一处生效，
   正是本次事故的形状（D19）。

### 判定方法

`tests/test_invariant_i13_mcp_calls_are_bounded.py`：

1. **sleep 注入**：把采集器换成 sleep 25 秒的假采集器，逐个调用全部 10 个工具，
   断言每次都在 `MCP_CALL_BUDGET_SECONDS` 内返回。负向验证：把同步推进预算
   调回 30 秒，`advance_trip_task` 应当超标。
2. **可终止**：外部动作待补时，`advance_trip_task` 必须在有限次内到达
   非 `RUNNING` 的检查点，不得无限返回 `RUNNING`。
3. **单一落状态入口**：AST 扫 `trip_application`，断言 `store.block(` 的调用
   只出现在登记的入口里，防止再长出第二处只落一半的实现。

### 当前状态：成立

### 未覆盖

`MCP_CALL_BUDGET_SECONDS` 是**上界不是目标**。正常调用都在 1 秒内，唯一会主动
等待的是 `advance_trip_task`（等到 `wait_seconds`，≤30）。本不变式不管「快不快」，
只管「会不会把宿主拖到超时」。

---

## 附：不变式与阶段闸门的对应

| 不变式 | 预期转绿阶段 | 依据 |
|---|---|---|
| I8 | P1 | 纯静态检查，不依赖实现改造 |
| I2、I3a（内核范围） | P2 | 证据内核建成后在内核范围内即可成立 |
| I5、I6、I3b、I2 / I3a（读取层范围） | P3a | I6 需扫描整个 `src/`，P2 阶段旧的并行实现仍在，不可能绿；I5 需读真实 run 目录并跨两个读取时刻，超出纯函数内核范围。二者均待读取层接管后成立。I2 在 P3a 允许有豁免项（3 处高德时长），见 `PLAN.md` v4 §12 的 P3a 闸门 3 |
| I7、I2（无豁免） | P3b | 需要 29 处 `sourced` 硬闸门四态化，重分类才能生效 |
| I11 | P4-a | 默认实例改惰性工厂，不依赖落盘契约变更 |
| I1、I10 | P4-b/c | 需要落盘契约变更（字段级 facts + 删展示态） |
| I4、I9 | P5 | I4 需要 `hotel_price` 生产者落地；I9 需要候选生成脱离硬编码目的地 |
| I12 | P5 轮 3 | 增列于首次真实宿主实测之后，落地即绿——它守的东西在实测前没有任何守卫 |
| I13 | P5 轮 5 | 增列于第二次真实宿主实测之后，落地即绿。同上：卡死 4 分钟这件事此前没有任何守卫，因为每一次单独调用看起来都正常 |

**2026-08-02 修订（A1）**：原表把 I5、I6 列为「P2 → P3」，与 `PLAN.md` v4 §12 的 P2 闸门第 3 条一并修正——P2 只转绿 I2 与 I3a，且只在内核范围。

**2026-08-02 修订（P2 裁决）**：原 P3 拆为 P3a（读取层接管，不做重分类）/ P3b（29 闸门四态化，重分类生效）。I7 相应由 P5 前移到 P3b——它依赖的是闸门四态化，不是刷新分层。

各阶段闸门的完整定义见 `PLAN.md` v4 §12。

---

## 未决问题

| # | 问题 | 状态 |
|---|---|---|
| 1 | I3b 采用强形式还是弱形式 | **已决**（裁决 4，2026-08-02）：弱形式。理由见 I3b |
| 2 | I1 禁用键名集合是否完备（当前从一个 run 目录实测归纳，可能漏掉未出现过的字段） | 【待验证】P4 前需对全部历史 session 目录做一次全量归纳 |
| 3 | I6 白名单中「唯一渲染层常量表」的边界（三个宿主面是否各自持有一份） | 未定，取决于宿主面收敛决策 |
| 4 | I8 反向规则的 `planned` 修订 | **已落地**：`hotel_price` 已转 `active`，现行登记见 `freshness-policy.md` §2.2 |
| 5 | I9 地名字面量集合的维护方式（手工清单 vs 从数据文件推导） | 未定。手工清单会漏，从数据文件推导在数据文件本身即违规时会自指 |

---

## I14 MCP 工具处理函数内不得出现同步网络实采

### 增列理由

I13 立了「单次调用有上界」，第四次实测 `verify_itinerary` 仍然 4 分钟无响应——
而 I13 当时是**绿的**。归因是 I13 的守卫按清单逐条核对，`verify_itinerary` 在
同一轮新增却没进清单（同一个坑上一轮刚在 next_call 守卫上踩过）。

本轮把 I13 改成扫描式之后，它仍然只在**跑得到那条分支**时才看得见问题：需要一个
能触发实采的场景、一个能把实采变慢的注入点。I14 换一个角度——不问「跑起来多快」，
问「结构上会不会慢」。

两条一起才够：I13 抓「跑起来慢」，I14 抓「结构上就会慢」。

### 陈述

从任一 MCP 工具处理函数（`mcp_server.py` 中被 `@server.tool(...)` 装饰的函数）
出发，其**同步**调用闭包内不得出现网络实采原语。

「同步」的界定：传给已登记异步边界（`start_background`、`_spawn`、
`_spawn_action_loop`）的实参子树**不计入**——那些在别的线程里跑。异步边界必须在
调用点一望即知，名字里要带 background / spawn。

「提到即算数」：把采集器当值传递（如 `client_factory=_RailClient` 这样的形参
默认值）与直接调用它同罪。`verify_railway_assertions` 的网络入口正是这个形状，
只看调用名根本发现不了。

### 判定方法

AST 静态扫描 `src/trip_decider/`，按模块导入表解析普通调用、按名字解析属性调用，
BFS 找从工具处理函数到网络原语的路径。

**「网络原语」不是手写名单（R4，2026-08-04 加固）。** 原先是一份写死的函数名
清单——采集器改个名字就漏。现在两步派生：

1. **认模块**：哪些模块真的发请求（出现 `urlopen` / `build_opener` / `socket`）。
   两种写法都要认——AMap 那边是 `urlopen`，12306 那边把 opener 存在实例上，
   之后写成 `self._opener.open(...)`，没有 `urlopen` 这个名字可抓。
2. **认可调用**：采集器模块内**在模块内部能走到网络调用**的顶层函数与类，
   加上别处 `from X import y as z` 给它们起的别名。

只取「真能走到网络的」而不是「模块里所有函数」：`intercity_rail.rail_snapshot_metadata`
只是格式化元数据，一个请求都不发，按模块整体染色会把每个工具都标红（实测如此）。
**判定过宽和过窄一样没用——前者让人学会忽略它。**

负向验证（D6）：把采集器入口改名为一个完全不同的名字，扫描仍然认出它。

**已知局限**（登记而非隐瞒）：名字级匹配，不做别名与动态分派分析；`_TOO_GENERIC`
里的高频名（`start` / `collect` / `run` 等）被跳过以避免假路径，代价是会漏掉真的
经由它们的链路。漏掉的部分由 I13 的计时兜底。

判定文件自带**反向自检**：断言扫描器确实能在已知的采集入口上报出网络。没有这一
条，「全绿」可能只是因为扫描什么都看不见——这一条在开发中真的红过一次，正是它
逼出了「提到即算数」的判据。

### 例外登记

例外写在 `_REGISTERED_EXPOSURES` 里，**每条都要有另一个用例钉住它的理由**。
只写一句话的豁免等于没有豁免。当前一条：

| 例外 | 理由 | 钉住它的用例 |
|---|---|---|
| 读取期重采（`_refetcher_for` → `live_refetcher`） | 确实是同步实采，但 MCP 这条路上被构造期开关关掉（`TripQueryService(live_refetch=False)`）；只有 product_web 会打开。静态扫描看不见运行期开关 | `ReadTimeRefetchIsOffForMCPCase` |

### 当前状态：成立

`verify_itinerary` 已改为「收活即回执 + 后台实采 + `read_verification` 轮询」。

### 对应测试文件

`tests/test_invariant_i14_no_sync_collection_in_tools.py`

---

## I15 跨调用可变状态必须声明并发策略

### 增列理由

外部审计（Codex release gate）在核验登记处判出一条 HIGH 竞态。根因不是「某一行
写错了」，而是**没有任何地方说过这份状态由谁写、谁读、拿什么保护**。没有声明，
下一个改它的人只能靠通读全文推断，而推断会错。

### 陈述

模块级可变容器（`dict` / `list` / `set` 字面量，或 `dict()` / `list()` /
`set()` / `defaultdict` / `deque` 赋给模块变量）中，**在运行期真的被改过的**
那些，必须在紧邻上方的注释里声明并发策略。

声明格式：以 `并发：` 开头的一行，且必须落到三种保证之一——「只读」/「锁」/
「单线程」。只写「并发：安全」不算：那是三种**不同的**保证，混着说等于没说。

### 判定方法

AST 扫描模块级可变容器，交叉全仓的变更行为扫描（下标赋值 / `del` / 增广赋值 /
`append` `update` `pop` 等变更方法），只对**真被改过的**要求声明。

**为什么不要求全部声明**：全仓 39 个模块级容器里 37 个是词表、策略表和
`__all__`，从导入到进程结束一字不变。要求它们各写一行「并发：只读」，产出的是
37 行样板，而样板会被连同真正要紧的那两行一起略过。「只读」由扫描自己证明，
不劳人声明——人会写错，也会在改了它之后忘了改声明。

变更扫描按**名字**匹配、不做作用域分析，因此偏严（同名局部变量的变更会被算
进来）。偏严的代价是多写一行声明，偏松的代价是漏掉一个竞态。

### 当前状态：成立

全仓命中一处：`agent_actions._STATES`（动作循环的内存缓存），已声明由 `_LOCK`
保护，并写明「不得在持锁期间做网络 I/O」。

核验登记处的条目表是**实例属性**，模块级扫描看不到它，由本文件的
`test_the_registry_state_is_declared_under_a_lock` 单独钉住。

### 对应测试文件

`tests/test_invariant_i15_shared_state_declares_concurrency.py`

