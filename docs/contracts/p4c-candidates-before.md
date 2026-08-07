# `candidates()` 事件流重建：改造前快照

> 状态：P4-c 第 3 批的**历史 before 快照**，迁移已完成。
> 建立日期：2026-08-03（HEAD `0fbdfa1`）
> 依据：`persistence-v2.md` §5.2（候选卡引用化）、基线报告 M7。

---

## 1. 两条读取路径

[`trip_query.candidates()`](../../src/trip_decider/trip_query.py#L161) 有两条分支：

| 分支 | 触发条件 | 数据源 |
|---|---|---|
| **直读** | `run.result.stage in {"open_discovery", "guided_discovery"}` | `result.options`，比较阶段刚写下的内存产物 |
| **事件流重建** | 以上不成立——即 `result` 已被后续阶段覆盖 | `events.jsonl` 里 `*.candidate.completed` 事件的 `details.option` |

**重建分支是降级数据源。** `events.jsonl` 名义上是 append-only 的「发生过什么」，
实际兼任读模型的备用存储。基线报告 M7 记过 `candidates()` 被迫走这条分支，当时
归因于 stage 不写；现在看，**那条分支本身就是问题的一半**。

## 2. 事件载荷的当前形状

一次真实 run 的 `*.candidate.completed` 事件，`details.option` 的键：

```
budget_headroom_after_known_transport_cny, coarse_plan_status,
destination_anchor, destination_id, evidence_missing, evidence_statuses,
feasibility_status, gateway_checked, local_transport_difficulty, name,
physical_intensity, playable_time_seconds, region_label,
roundtrip_transport, themes
```

`evidence_statuses[0]` 实测：

```json
{
  "collected_at": "2026-08-01T09:00:00+08:00",
  "domain": "railway",
  "from_cache": false,
  "timed_out": false,
  "token": "verified"
}
```

## 3. I1 最后 4 处：逐处消费方

`token` 是读取时刻算出的展示态，写进事件即冻结。四处命中全部出自这一个字段
（三个域各一 + 一次事件重复）。

| 环节 | 位置 | 行为 |
|---|---|---|
| **产出** | `guided_discovery` 的候选卡构造 | `token: checks[domain].display_status` |
| **发射** | `trip_application._candidate_comparison_background` 的 `progress` 回调 | 整个 option 塞进 `details` |
| **落盘** | `events.jsonl` | append-only，无覆写 |
| **消费** | `trip_query.candidates()` 重建分支 | `deepcopy(dict(option))` 整体取回，token 原样返回给 UI |

**剥不掉的原因**：消费方直接把事件里的 option 当候选卡返回。剥掉 `token`，
I3a（每个证据节点都要带 token）立刻转红——这是 P4-b3 回退过的那次。

## 4. 改造需要的三步

1. **产出侧**：候选卡的 `evidence_statuses` 改带 `evidence_id` / `fact_refs`，
   不带 `token`（`persistence-v2.md` §5.2）。
2. **消费侧**：`candidates()` 重建分支解析引用 → 经 `evidence_projection.project_domain`
   按**读取时刻**重算 token。
3. **发射侧**：`recovery_safe` 重新落到 `progress` 回调——b3 那次因为耦合未解而回退，
   现在第 2 步解了耦合，可以落了。

三步必须同批：只做 1 会让 UI 拿不到 token，只做 3 会让重建分支拿不到数据。

## 5. 改造后应当成立的判据

* `events.jsonl` 的 `details.option.evidence_statuses[]` **无 `token` 键**；
* `candidates()` 两条分支给出的 token **相同**（同一份证据、同一个 `now`）；
* 换一个 `now`，重建分支的 token **会变**（它是读取时刻的函数，I5）；
* I1 写入侧 4 → 0；
* I3a 保持绿——两者同时成立才算对，只满足其一就是 b3 回退过的那个陷阱。
