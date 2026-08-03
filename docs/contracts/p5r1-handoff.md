# P5 轮 1 交接：error_code 普查、四件裁决、auto_refetch 落点

**本文件是轮 2 作业单的前置阅读第 3 项。** 轮 1 的普查结论与 Hugin 的四件裁决
记在这里，轮 2 按此执行，不必重做普查。

轮 1 已落地的两件在 git 里（`35370e6` 悬空引用、`8c4c217` I9 转绿），本文件
不复述——只记**没落地、留给轮 2 的部分**，以及普查过程中查清、写在代码里看不出
来的事实。

---

## 1. 轮 1 结果速览

| 项 | 状态 |
|---|---|
| 悬空引用归因 + 修复 | 已落地（`35370e6`） |
| I9 转绿 | 已落地（`8c4c217`），ledger 只剩 I4 |
| error_code 词表治理 | **停在普查**，按停点规则报，未动代码 |
| 套件 | 221 tests / 1 失败（I4） |

停的理由：作业单说「四前缀全量普查」，普查结果是 **9 个族、其中 4 个取值域
无界**，取值域与消费面双双超预期。三条超预期见 §2.3。

---

## 2. `run.error_code` 普查表

### 2.1 字段本身没有取值域约束

`run.error_code` 的全部写入口只有两个：

- `InMemoryAgentStore.fail(run_id, error_code)`（`travel_agent.py:1245`）
- `InMemoryAgentStore.block(run_id, result, reason_code)`（`travel_agent.py:1260`）

两者都收**任意字符串**，不校验。这一点决定了收敛的落法（见 §4.3）。

### 2.2 生产点 × 消费点（D2 同表）

| # | 生产点 | 产出 | 值数 | app.js 覆盖 |
|---|---|---|---|---|
| P1 | `agent_actions.py:2043` | `f"{domain.upper()}_ACTION_STALLED"` | 4 | 仅 RAILWAY / MAP |
| P2 | `agent_actions.py:2045` | `f"{domain.upper()}_EVIDENCE_BLOCKED"` | 4 | **0/4** |
| P3 | `travel_agent.py:2024` | `f"EXECUTOR_{型名}"` | **无界** | 无 |
| P4 | `travel_agent.py:2275` | `f"REVISION_EXECUTOR_{型名}"` | **无界** | 无 |
| P5 | `trip_application.py:878` | `f"INTERNAL_ERROR_{型名}"` | **无界** | 无 |
| P6 | `trip_application.py:880` | `f"ACTION_LOOP_{型名}"` | **无界** | 无 |
| P7 | `trip_application.py:801` | `"GUIDED_COMPARISON_UNAVAILABLE"` | 1 | 无 |
| P8 | `trip_application.py:838` | `"WEB_EVIDENCE_REQUIRED"` | 1 | 有 |
| P9 | `trip_application.py:840` | `"USER_INPUT_REQUIRED"` | 1 | 有 |

P1/P2 的 `domain` 来自 `_TOOL_REGISTRY`，**含 `planner`**（不只 railway/web/map），
故各 4 值。`PLANNER_ACTION_STALLED` 经 `agent_actions.py:397-424` 的单动作分支
可达——批量分支（`:343`）才过滤成三域。

**消费点（D3，全部比较面）**：

| # | 位置 | 形态 |
|---|---|---|
| C1 | `web/app.js:1749-1757` | 唯一真比较：4 键查表 + 兜底 `"新版本未能完成"` |
| C2 | `agent_actions.py:472` | 原样透传给 MCP 快照的 `reason`，不比较 |
| C3 | `travel_agent.py:1842-1844` | 反序列化，不比较 |
| C4 | `tests/test_product_web.py:286` | 钉住 `RAILWAY_ACTION_STALLED` |
| C5 | `tests/test_mcp_adapter.py:264` | 钉住 `WEB_EVIDENCE_REQUIRED` |

### 2.3 三条超预期（停点依据）

**① 作业单点名的两个前缀，`src/` 里根本没有生产点。**
`RAILWAY_ACTION_STALLED` / `MAP_ACTION_STALLED` 只以模板
`f"{domain.upper()}_ACTION_STALLED"` 存在。全仓 grep 这两个字面量**只命中
app.js 和测试**。照字面量改名会改掉消费点、静默漏掉生产者——D2/D3 那次事故的
形状，方向反了。**改名清单不能从字面量出发建，必须从模板的实参域出发。**

**② 四族取值域无界。** 型名插值意味着取值域是「能逃出那四个 `try` 的每一个
异常类名」，grep 穷举不了。

**③ 消费面的 D3 缺口就在作业单点名的那张表里。** `WEB_ACTION_STALLED` 是
`RAILWAY_/MAP_ACTION_STALLED` 的直系同胞，可产出但不在 map 里，静默落到
「新版本未能完成」。4 个 `*_EVIDENCE_BLOCKED` 同样全部落空。

### 2.4 附带发现：D12 只落地了四分之一

「编程错误 vs 业务失败」的区分**只编码在四族里的一族**——`INTERNAL_ERROR_` vs
`ACTION_LOOP_`（`trip_application.py:858-881`）分了，`EXECUTOR_`（P3）与
`REVISION_EXECUTOR_`（P4）两族**完全不分**。D12 写的就是这件事，落地只落了一处。

---

## 3. 四件裁决（2026-08-03，Hugin）

### 裁决 1：改名范围

**批**：`{DOMAIN}_EVIDENCE_BLOCKED` → `{DOMAIN}_ACTION_FAILED`；
`WEB_EVIDENCE_REQUIRED` → `CODEX_ACTION_REQUIRED`。
**`_ACTION_STALLED` 不动。**

理由：前两条名实不符——一个复述证据状态，一个连触发条件都对不上
（`WEB_EVIDENCE_REQUIRED` 的判据是 `action_type.startswith("codex")`，
**根本不看 domain**）。第三条「低收益可不动」成立：「停滞」与「超时」的语义差
不值一次全量同步的风险，**D1 的反面教训就是为小收益动大面**。

### 裁决 2：无界四族收敛为两段式

不做穷举词表——型名的取值域本来就穷举不了。改为
**有限前缀 + 自由后缀**：前缀是有限词表（表达「哪一类为什么停」），
型名**降级为 detail 或结构化字段，不再参与 `error_code` 本体**。

`EXECUTOR_` / `REVISION_EXECUTOR_` 两族按 D12 补上区分（§2.4 的落地缺口，
同批做）：非业务异常归入 `INTERNAL_ERROR_` 前缀（**已有，复用**），
业务失败用有限前缀。

做完之后 `error_code` 的前缀集有限、可查表，型名信息不丢（挪进 detail），
app.js 的查表渲染才有可能完备。

### 裁决 3：app.js 补键，不做结构化渲染改造

结构化渲染是对的方向但错的时机——它是前端改造，P5 代码轨的收口目标是
ledger 全绿和 auto_refetch，**别在这里开新战线**。

前缀收敛后键集有限，补齐 + 一个**显式的 `INTERNAL_ERROR_` 前缀匹配兜底**
（「系统内部错误，详情见记录」之类）即可，不再用「新版本未能完成」这种
误导性叙述。**结构化渲染记入 P5 后待办。**

### 裁决 4：auto_refetch 触发时机 = 读取时同步重查

`freshness-policy.md` §6 #4 的三选一，点名第一个。理由：

- **(a)** 异步排队和「下次推进时」都需要一个「之后会发生」的承诺，而本地单进程
  产品没有可靠的「之后」——用户关掉就没有之后了；
- **(b)** 读时同步与整个模型同构：freshness 读时算，重查读时触发，
  `retry_after_at` 做节流阀防读取风暴；
- **(c)** 落点已收敛到唯一漏斗（`project_domain`），同步重查的实现面最小。

执行约束：带超时上限（单次读取的重查总预算，超了按现有 stale 降级）；
失败走 `stale_after_failure` 既有兜底——**它不是触发器，但它是触发后失败路径的
现成承接**（分工见 §5.2）。

---

## 4. 改名与收敛的终态提议（待轮 2 执行）

### 4.1 逐条判定（命名原则：表达「动作为什么停」，不复述证据状态）

| 现名 | 判定 | 终态 | 理由 |
|---|---|---|---|
| `{DOMAIN}_EVIDENCE_BLOCKED` | 复述证据状态 | `{DOMAIN}_ACTION_FAILED` | 触发点是 `execute_registered_action` 捕获异常（`:639`）——动作失败了 |
| `WEB_EVIDENCE_REQUIRED` | 复述证据状态 + 名不副实 | `CODEX_ACTION_REQUIRED` | 判据只看 `action_type` 前缀，与 web 域无关 |
| `{DOMAIN}_ACTION_STALLED` | 略不准，**不动** | 原样 | 裁决 1 |
| `INTERNAL_ERROR_*` | 正确 | 保留为前缀 | D12「如实记类型」 |
| `USER_INPUT_REQUIRED` / `GUIDED_COMPARISON_UNAVAILABLE` | 正确 | 原样 | 都在说动作为什么停 |
| `EXECUTOR_{型名}` / `REVISION_EXECUTOR_{型名}` / `ACTION_LOOP_{型名}` | 无界 | 拆前缀 + detail | 裁决 2 |

### 4.2 前缀集收敛后的预期形状（供轮 2 核对，非最终）

有限前缀候选：`{railway,web,map,planner}_ACTION_STALLED`、
`{railway,web,map,planner}_ACTION_FAILED`、`CODEX_ACTION_REQUIRED`、
`USER_INPUT_REQUIRED`、`GUIDED_COMPARISON_UNAVAILABLE`、`INTERNAL_ERROR_*`，
外加 `EXECUTOR_/REVISION_EXECUTOR_/ACTION_LOOP_` 三族拆分后的业务失败前缀
（**命名待轮 2 提议先报后改**）。

### 4.3 收敛的机械保证点在哪（D20）

**不要靠 9 个调用点自律。** `error_code` 只有两个写入口
（`fail()` / `block()`，§2.1），**把前缀校验放在这两个函数里**，
不合法前缀直接报错。这样「前缀集有限」由数据形状保证而不是由纪律保证——
D20 说的正是这件事：能由形状保证的约束，不要写成一句「调用方不得……」。

---

## 5. auto_refetch 落点清单

### 5.1 引用解析处（读时惰性方案的落点）

| # | 落点 | 现状 |
|---|---|---|
| 1 | `trip_query._with_recomputed_tokens`（`trip_query.py:240-291`） | `candidates()` 的解析处。按 `destination_id`/`domain` 查 `guided-comparison.json`，调 `project_domain(..., now=read_at)` |
| 2 | `trip_query.plan_readiness`（`trip_query.py:293-347`） | 整份 context 重编译；内部解析在 `planning_input_compiler.py:371` 的 `project_domain(..., now=now)` |
| 3 | **`evidence_projection.project_domain`** | **两条路径的唯一漏斗**，freshness/stale 实际在这里判 |

落点 3 是唯一真正的收敛点——1 和 2 都从它拿结论。裁决 4 的实现落在这里。

### 5.2 `stale_after_failure` 的分工（查清了，注释里要写明）

**它不是重查触发器。** 入口就断言「实采已失败」
（`_is_usable_live(query, live_failure)` 为真则 raise，`evidence_broker.py:186-189`），
是失败后的兜底。`freshness-policy.md` §5 明写「**没有任何主动重查触发器**」。

复用面：生产 4 处（`agent_actions.py:718`、`guided_discovery.py:355/383/435`），
测试 6 处（`test_evidence_broker.py` 5 处、`test_invariant_i4` 1 处）。

另两条约束：
- broker **拒绝服务本 run 自己的缓存**（`record.run_id == run_id → None`），
  跨 run 复用才走缓存；
- `on_stale` 目前**只**用于算 `blocking`（`evidence_core.py:1052`），
  不触发任何东西。内核侧已就位：`next_action.kind == auto_refetch` 与
  `retry_after_at` 都已实现，缺的只是触发器。

---

## 6. 轮 2 开工前的三条结构事实

这三条是普查时查清的，代码里看不出来，会直接影响落地方式。

### 6.1 `AgentRun` 没有 detail 字段——裁决 2 需要新增持久化字段

`AgentRun`（`travel_agent.py:788-800`）只有 `error_code: str | None` 一个槽，
`to_dict()`（`:817-835`）写 12 个键，就是 `run.json` 的全部顶层字段。

因此「型名降入 detail」**要新增一个落盘字段**，连带同步
`persistence-v2.md` §2.1 的顶层字段清单（`:137` 那行）。

### 6.2 新字段不会绊倒 I1，但理由要显式写

I1 的判定是**禁用键名集合 + 禁用取值集合**的黑名单匹配
（`invariants.md` I1 §判定方法），不是白名单穷举——新键不在禁用集合里就不会命中。

语义上也站得住：它记录的是「这次停下来时逃出来的异常是哪一类」，
**采集时刻的事实，写入后不再变化**，与 `refresh_failure` 同性质
（`evidence-axes.md` §3.4 的论证可直接复用）。但按 I1 白名单的要求，
**理由必须逐项写进白名单表**，不能默认它没事。

### 6.3 已知不对称的用例化前提

`evidence-axes.md:351` 的不对称（`estimated+stale+critical` 不阻断而
`sourced+stale+critical` 阻断）目前是**契约注记，不是可观测行为**——
`requires_conditional` 由内核产出但消费在 P3b 的闸门里。
auto_refetch 落地后它才成为可观测的行为分叉，那时才钉得住用例。
轮 2 作业单要求的「两态各一例」以此为前提。

---

## 7. 记入 P5 后待办

- app.js 的**结构化渲染改造**（裁决 3 明确推迟，不是取消）。
- `{DOMAIN}_ACTION_STALLED` → `_TIMED_OUT` 的精度改名（裁决 1 判为低收益，
  若将来有一次同域的全量同步顺带做）。

按 D15，这两条推迟项必须在认领它们的那一阶段清单里**点名出现**，
不许靠「反正写在这里」兜底。
