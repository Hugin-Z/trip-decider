# P4-c 前置清单

> 状态：P4-b3 收口产出，**P4-c 的输入**。
> 建立日期：2026-08-02
> 依据：`persistence-v2.md` §5 / §8 / §14，对着规格重盘 c 段。
> 用途：标明 P4-b2/b3 几轮吃掉或改变形状的部分，逐条给剩余量级、依赖顺序、可复用基建。

---

## 0. 一句话现状

写入侧展示态已清零（I1 写入侧 476 → 4），**落盘形状仍是 v1**——`facts` 未落盘，
`derive_facts` 仍在承担全部字段级 support。P4-c 要做的是形状迁移 + 读取侧准入重建，
两件事共享同一套基建。

## 0.1 已有基建（各条目标注复用哪一个）

| 基建 | commit | 提供什么 |
|---|---|---|
| `derive_facts` / `EvidenceItem.facts` / `item_facts` | `df95f3e` `1be1a9e` | v1 裸 value → 字段级 facts，双读 |
| `usable_fact_values` | `1be1a9e` | 按 support 过滤并重建嵌套形状 |
| `recovery_safe`（内核） | `b226a60` `fbf8572` | 剥读取层投影，恢复数据只留事实/结构/引用 |
| `project_domain` / `token_*` | P3a | 读取时刻定级，唯一 token 实现 |
| `p4b-plan-readiness-sample.json` | `7f4aeeb` | 安装闸门读时重算的真实输入样例 |
| `recomputed_planning_state` | `a7b2045` | 读取时重算 planning_state，已接线 |
| `CHAR_NOW` / `STALE_NOW` / `set_read_clock` | `6f9a9f7` | 钉死读取时刻，表征与单测通用 |

---

## 1. 历史存量删除 — **时序条件已满足**

**前置确认结论：可以删。**

规格要求「v2 首次写盘前删除」。实测当前新 run 落盘的 `evidence/current.json`，
`value` 顶层键为 `destination / local_transit / retrieved_at`，**无 `facts` 键**——
仍是 v1 形状。因此 v2 首次写盘尚未发生，**时序窗口仍然开着，没有错过**。

| 项 | 值 |
|---|---|
| 存量 | `runtime/sessions/**` 522 个文件，I1 命中 4314 处 |
| 构成 | `timing_status` 3095、`evidence_status` 436、`schedule_status` 410、`snapshot_status` 232 |
| 量级 | 小（删目录 + 确认无测试依赖真实 runtime） |
| 依赖 | **必须排在第 6 条之前**——一旦生产点切 v2，窗口关闭，就得写迁移脚本 |

删除后 I1 的历史存量数归零，两个数合并为一个。

## 2. `candidates()` 引用化 + 事件流数据源解耦 — **I1 最后 4 处压在这里**

P4-b3 发现的架构耦合：`events.jsonl` 名义上是 append-only 的「发生过什么」，
实际上是 [trip_query.py:161-177](../../src/trip_decider/trip_query.py#L161-L177) 的降级数据源
——`run.result` 不再是比较阶段时，`candidates()` 从事件流重建候选卡。

因此事件明细里的 `evidence_statuses[].token` 剥不掉：剥了 I1 绿，I3a 红。
（基线报告 M7 提过 `candidates()` 被迫走事件重建分支，当时归因于 stage 不写；
现在看那个分支本身就是问题的一半。）

| 项 | 内容 |
|---|---|
| 动作 | 事件只存 `evidence_id` / `fact_refs` + 结构；`candidates()` 解析引用后经 `evidence_projection` 重算 token |
| 量级 | 中。判定逻辑已存在，要做的是接线 + 事件载荷瘦身 |
| 复用 | `recovery_safe`（剥投影）、`project_domain`（重算）、`fact_refs` 形状（`make_rail_event` 已有先例） |
| 闸门 | I1 写入侧转绿、I3a 保持绿（两者同时才算对——只满足其一就是本轮回退过的那个陷阱） |
| 在位标注 | `trip_application.py` 的 `TODO(P4-c)` |

## 3. `_current_plan_payload` 准入重写 + 「已写入 / 当前可用」拆词

P4-b3 已把两处写入闸门按 §6.2 改成只验结构（`persist_plan_version`、`_current_plan_payload`），
**准入语义的重建留在这里**。

| 项 | 内容 |
|---|---|
| 动作 | 拆两个词：「已写入」= 结构完整（写入侧，已完成）；「当前可用」= 读取时重算（`recomputed_planning_state`，已存在）。`_current_plan_payload` 接后者 |
| 量级 | 小。判定与接线都已存在，是把 §6.2 的另一半补上 |
| 复用 | `recomputed_planning_state`、`p4b-plan-readiness-sample.json`（第一个真实输入样例） |
| 依赖 | 与第 2 条共享 `fact_refs → evidence_projection → token` 基建，**同批做**，拆开等于同一件事改两遍 |

## 4. PlanVersion 引用化

| 项 | 内容 |
|---|---|
| 动作 | 计划事件不再内联证据值，改挂 `fact_refs`；落盘只有 structure + refs |
| 现状 | `make_rail_event` 已挂 `fact_refs`（`1eda5ea`），本地交通事件已挂（`e901c69`）——**部分完成** |
| 剩余 | 景点/住宿事件、`context.evidence` 的内联值 |
| 量级 | 中 |
| 复用 | `fact_id` / `split_fact_id`（内核）、已有的两个先例 |

## 5. blocker 家族改名 — **已完成（第 5 批，2026-08-03）**

规格 §7 写的是 21 → 11。P3b 之后新增过 blocker（`RAILWAY_SNAPSHOT_STALE` /
`RAILWAY_AVAILABILITY_UNKNOWN` 等），**21 这个数已过时**。

| 项 | 内容 |
|---|---|
| 前置 | 先普查当前 blocker_id 全集，重出映射表，再动手 |
| 量级 | 小（普查）+ 中（改名波及断言） |
| 教训 | 「按 N 处改」的指令普查先行——这是 P4-b2 立的默认动作 |
| 实测 | 17 处调用点 / 17 种 id，非规格写的 21；普查另抓到规格漏登的两族 |
| 结果 | 终态 12 种，执行清单见 `persistence-v2.md` §7.4 |

## 6. 生产点切 v2 形状（facts 落盘）

**这是 b2/b3 都没做的一块，不在任何一轮的显式范围里，需在 P4-c 补上。**

| 项 | 内容 |
|---|---|
| 现状 | 落盘仍是 v1 裸 value，`facts` 全部靠 `derive_facts` 推导 |
| 动作 | 写入侧产出 `facts` 数组；双读的「直读」分支开始生效 |
| 依赖 | **必须排在第 1 条之后**（历史存量删除的时序窗口） |
| 连带 | `trip_application:317` 的 deepcopy 白名单条件（「生产点切换后验证搬运物形状」）到此才能兑现 |
| 量级 | 中 |

## 7. action-loop 去重

| 项 | 内容 |
|---|---|
| 动作 | 只存 `action_status` + 引用，`fallback_result` 不再整份快照 |
| 现状 | `recovery_safe` 已剥掉投影键（`b226a60`），但整份 result 仍在里面 |
| 量级 | 小 |
| 闸门 | 崩溃恢复用例——去重后仍能恢复 |

## 8. 双读机制删除

| 项 | 内容 |
|---|---|
| 时机 | 第 1 条（删历史）+ 第 6 条（切 v2）都完成之后 |
| 现状 | `derive_facts` 有 4 类调用方（见 §9），全部依赖 v1 形状 |
| 量级 | 小（删推导分支 + `item_facts` 的回落） |

---

## 9. 双读存活清单（`derive_facts` 调用方）

| 调用方 | 用途 | v2 切换后 |
|---|---|---|
| `EvidenceItem.facts`（`travel_agent`） | 对象形态的字段级读取 | 走「直读」分支，推导不再触发 |
| `evidence_projection.item_facts` | dict 形态（读取层主入口） | 同上 |
| `tests/test_evidence_facts_derivation.py` | 9 种键集合的推导覆盖 | 历史数据删除前保留 |
| 历史数据回读 | `runtime/sessions/**` 的 v1 形状 | **删历史后即无调用方** |

**结论：删除时机取决于第 1 条与第 6 条，本轮不动。**

## 10. 建议执行顺序

```
1. 历史存量删除（窗口还开着，先关掉这个风险）
2. blocker 普查（纯读，可并行）
3. candidates() 引用化 + _current_plan_payload 准入重写（同批，共享基建）
   → I1 写入侧转绿
4. PlanVersion 引用化剩余部分
5. 生产点切 v2 → trip_application:317 白名单兑现
6. action-loop 去重
7. 双读删除 + blocker 改名
```

第 3 步是关键路径：I1 转绿压在它上面，而它又是后续引用化的基建验证。
