# P3b 表征测试差异日志

> 用途：`p3b-gate-inventory.md` §9 要求的迁移守卫审计轨迹。
> 规则：每批改造后跑一次 `tests/characterization_support.capture()`，逐条对照清单的「预期影响」列。
> **预期内的差异逐条确认后更新快照；预期外的差异就是事故。**

场景固定 11 条，覆盖四态 + `confirmed_absent`，输出三个可行性判定点。

---

## 批次 1 · 枚举扩展（`EvidenceStatus` 四态 + `is_usable` + `_stale_projection` 保留 support）

**diff：9 条，全部为 3 个 estimated 场景由「不可构造」变为可构造。**

8 个既有场景**逐字节相同**——批次 1 是纯扩展，不改行为，符合清单 §7 批次 1 的设计（「此批不改任何闸门，行为应完全不变——可作为一次纯扩展验证」）。

**判定：预期内，已确认。**

---

## 批次 2 · `agent_actions` 16 处 + `evidence_broker` 2 处改为 `is_usable`（甲）

**diff：2 条。**

| 路径 | 改造前 | 改造后 |
|---|---|---|
| `railway_estimated` / `playable_time_seconds` | `273600.0` | `null` |
| `all_estimated` / `playable_time_seconds` | `273600.0` | `null` |

**成因**：`evidence_broker.py:343`（`_is_usable_live`，清单 §3.6）改为 `is_usable` 后，`estimated` 不再被判为「本次实采不可用」，于是 `stale_after_failure` 按其前置断言拒绝执行（`evidence_broker.py:186-189`：「stale lookup requires an unusable live result」）。原路径下 `estimated` 被当成失败的实采，走到缓存查找，未命中后原证据被保留，`_coarse_option` 仍从它的 `value` 里读出了 `roundtrip_duration_seconds`。

**方向判断：变好。** 改造前的 `273600.0` 是**从一条系统同时标为 `MISSING` 的证据里算出来的**——候选卡说「没有铁路证据」，却给出了一个由该证据推算的可玩时长。改造后两者一致。

**8 个既有场景仍逐字节相同。**

**判定：预期内（清单 §3.6 的直接后果），已确认。** 注：estimated 场景整体仍不正确（`feasibility_status` 仍为 `UNKNOWN`），那是批次 4 的 `guided_discovery:314 :521 :597` 负责。

---

## 批次 3 · 3 处高德时长构造点改 `ESTIMATED` + 合并按 §2.4 聚合

**diff：0 条。**

**成因**：表征 fixture 直接注入证据（`characterization_support.evidence()`），不经过 `_map_handler` / `_merge_sourced_evidence` 这两个采集侧构造点，因此构造点的改动在本 fixture 上不可见。

**覆盖判断：等效覆盖，不补场景。** fixture 已有 `map_estimated` 场景直接注入 estimated 的 map 证据——即「map 变成 estimated 之后会怎样」已被覆盖；「map 会不会变成 estimated」是构造点的单元事实，由 `tests/test_agent_actions_reclassification.py` 单独守。

**判定：预期内（覆盖边界已说明），已确认。**

---

## 批次 4 · `guided_discovery` 4 处 + `planning_input_compiler` 7 处

**diff：91 条，分布在全部 11 个场景。** 逐类归并如下。

### 4.1 字段改名（全部 11 场景）

`evidence_statuses[].status` → `.token`；`roundtrip_transport.status` → `.token`。取值域从 `LIVE/STALE/MISSING` 三值换成 §4.1 的 8 token。

**判定：预期内**（清单 §3.4，I2/I6 要求）。已计入 `p3a-outward-diff.md` 的同类变更。

### 4.2 `next_action` 首次出现在候选卡（全部 11 场景）

`has_next_action` 从 `[]` 变为非空。

**判定：预期内**（清单 §3.4，I3a 候选卡一条由此转绿）。

### 4.3 `conflict_details` 首次可见（`railway_conflicting`）

`conflict_details_visible` 从 `False` 变 `True`。

**判定：预期内**（清单 §3.4，基线报告 M1，I7 第 3 条）。

### 4.4 `confirmed_absent` 走出独立分支（`railway_confirmed_absent`）

| 项 | 改造前 | 改造后 |
|---|---|---|
| `feasibility_status` | `UNKNOWN` | **`INFEASIBLE_NO_TRANSPORT`** |
| blockers | `RAILWAY_SNAPSHOT_UNKNOWN` | **`RAILWAY_NO_DIRECT_TRAIN`** |
| `blocker_fact_refs` | `[]` | `['railway-absent']` |

**判定：预期内**（清单 §2.1、§3.3，丙型）。这是「确认没有」不再被说成「不知道」的落点。

### 4.5 `_compile_railway` 不再静默跳过（`railway_unknown` / `railway_conflicting` / `all_unknown`）

新增 `RAILWAY_EVIDENCE_MISSING` blocker，携带 `fact_id`。

**判定：预期内**（清单 §2.1，「此前静默通过的现在会阻断」）。**这是本次对规划结果影响最大的一条。**

### 4.6 `estimated` 参与判定并携带 conditional（3 个 estimated 场景）

| 项 | 改造前 | 改造后 |
|---|---|---|
| `feasibility_status` | `UNKNOWN` | `CONDITIONALLY_FEASIBLE` |
| `planning_state` | `COLLECTING_EVIDENCE` | `PLAN_READY` |
| `conditions` | `[]` | `['往返交通时长为推算值，实际耗时可能不同']` |

**判定：预期内**（裁决 5，清单 §3.3）。

### 4.7 预期外差异：**0 条**

91 条全部归入 4.1–4.6 六类，每类都能在清单的「预期影响」列找到对应条目。

---

## 批次 5 · `schema_version` 最小打标

**diff：0 条**（打标只加字段，不改任何判定）。

`run.json` 已带 `schema_version: 2`；`evidence/current.json` 与 `evidence/guided-comparison.json` 走另一条写入路径，未被覆盖——见本轮报告的遗留项。

---

## 总结

| 批次 | diff 条数 | 预期外 |
|---|---|---|
| 1 枚举扩展 | 9（全为新场景变为可构造） | 0 |
| 2 `agent_actions` + `evidence_broker` 甲型 | 2 | 0 |
| 3 重分类构造点 | 0（fixture 不覆盖，已说明等效覆盖） | 0 |
| 4 `guided_discovery` + `planning_input_compiler` | 91（六类） | 0 |
| 5 `schema_version` | 0 | 0 |

**全程预期外差异 0 条。**
