# WU4-UC · Unscheduled Activity Contract Remediation Plan

Plan version: v0.1
Status: PENDING_HUGIN_APPROVAL
Decision: DISCRIMINATED_DAY_ASSIGNED_UNSCHEDULED

## 1. 目标与基线

本单元只扩展公共 activity 合同，使明确归属某个计划日、但没有具体
起止时刻的活动可被诚实表示；不实现 Planner，也不生成行程。

2026-07-29 实测基线：

```text
branch/HEAD: main / 1d5bf5ddf84634a5ba62a00a5e2f32d92c33886e
worktree/remotes/stashes: clean / 0 / 0
tests/schemas: 192 passed / 11
fixtures/documents/dirty cases: 7/40/7
```

当前 blocker 为 `PLAN_SCHEMA_CANNOT_EXPRESS_UNSCHEDULED_ACTIVITY`。
省略 start/end 有两个 required 错误；使用 null 有两个 type 错误；
填入无事实依据的时刻虽通过 Schema，但违反 R10。

## 2. 实际合同结构

`common.schema.json#/$defs/activity` 当前为 object，必填
`activity_id`、`candidate_ref`、`start_at`、`end_at`、
`constraint_refs`、`evidence_fact_refs`。

`start_at`、`end_at` 都引用带 offset 的 `date_time`；
activity 使用 `additionalProperties: false`。

activity 只经 `common#/$defs/day.properties.activities.items` 使用。
day 必填 `day_id`、`date`、`activities`、`legs`，所以数组中的 activity
天然由父 day 的稳定 ID 与 date 明确归属计划日，不需要新增 day 字段。

`plan.schema.json` 的 `payload.days[]` 复用 `common#/$defs/day`；
`previous-plan.schema.json` 的 `snapshot.days[]` 也复用同一定义。
因此只改 common 即同时扩展两类文档，不修改两个引用方。

冻结 hash：common
`83FE17127A545D168A16F58911564E53D2E17AFF826B6D34437D873ECF8E75BE`；
plan `81EEB5899C33F19DC6FA059C7D447D747E72E355F3084D925FD9410272389BD3`；
previous-plan
`59692D17EB79C7EA2D4A2E2866898DD97A0E49B97834EC8AFC5EAB46A80BEDAC`。

## 3. 时间顺序事实勘误

只读源码和测试未发现 `start_at < end_at` 的业务检查。
现有 validator 验证 date-time format、ID 和跨工件引用，但不比较时刻。

本单元保留现有 date-time 格式约束，不新增或宣称不存在的顺序能力。
若审批要求本单元补时间顺序检查，则必须停止：这需要修改已排除的
validator，并应进入独立合同/业务验证工作单元。

## 4. 互斥合同

activity 顶层继续保持 object、现有 properties 与
`additionalProperties: false`。公共 required 改为 `activity_id`、
`candidate_ref`、`constraint_refs`、`evidence_fact_refs`。

新增可选属性 `timing_status`，enum 仅为 `timed` 与
`day_assigned_unscheduled`。

再用互斥 `oneOf` 冻结两个分支。

### 4.1 Timed 分支

要求同时存在 `start_at` 与 `end_at`。
`timing_status` 缺省或精确等于 `timed`。

旧 timed activity 不需要新增字段，原字节结构继续有效。
显式 `timing_status: timed` 也合法，但不能替代两个时刻。
start/end 继续引用原 `date_time`，null、空字符串继续非法。

### 4.2 Day-assigned unscheduled 分支

要求 `timing_status: day_assigned_unscheduled`。

同时通过 Schema 的 `not`/`required` 组合禁止出现 `start_at` 或
`end_at`。不能使用 null、空字符串、午夜或其他占位值。

该 activity 必须位于 day.activities 中；测试不把孤立 activity
验证成功当作 day assignment 证据。

语义仅为“活动已分配至父 day，但具体时刻尚未安排”。它不表示全天、
时间灵活、营业无限制、时间已验证或当天可行。

### 4.3 必须拒绝

以下不能命中任一分支：无 start/end 且无 status；只有一个时刻；
`timed` 缺任一时刻；unscheduled 与任一/全部时刻混用；start/end 为
null 或空字符串；以及未知 `timing_status`。

## 5. 向后兼容

不修改 Schema `$id`、版本或文件数量。全部现有 timed Plan 与
previous-plan snapshot 继续经相同 `$defs/day` 和 `$defs/activity`。

不迁移 fixture，不重算既有 artifact payload，不放宽引用、ID、
date-time format 或 additionalProperties。现有 192 tests 必须全绿。

Plan/previous-plan 若因 common 扩展而失效，立即停止；不修引用方、
validator、fixture 或既有测试。

## 6. Fixture-first 测试

新增 `tests/test_wu4_unscheduled_activity_contract.py`，恰好六项；
输入为测试内手写的确定性 Schema 文档，expected 按本 Plan 写定，
不读取 Schema 分支生成 expected，也不新增仓库 fixture。

1. UC01：legacy timed（无 timing_status）及显式 timed 均有效。
2. UC02：父 day 内显式 unscheduled、无 start/end，修复后有效。
3. UC03：完整 conditionally_feasible Plan 可含上述 activity。
4. UC04：无两种 timing mode 的 day activity 仍无效。
5. UC05：only-start、only-end 和 mixed variants 全部无效。
6. UC06：null、空字符串及默认占位 variants 全部无效。

UC02 直接验证包含 `date` 的 day wrapper；UC03 再验证正式 Plan
envelope，避免把孤立 activity 误报为已具备 day 归属。

## 7. Red → Green

唯一 targeted 命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu4_unscheduled_activity_contract -v
```

C1 Red 必须精确为 `6 tests / 4 passed / 2 failures / 0 errors`，
且 failures 仅为 UC02、UC03。

两个失败只能来自旧 common 仍要求 start/end。import、dependency、
path、syntax、malformed input 与意外异常必须为 0；否则不进入 C2。

C2 只改 common，并以逐字符相同命令得到 `6/6`。
完整回归必须为 `192 existing + 6 new = 198/198`；
Schema/fixture 统计保持 `11` 与 `7/40/7`，network/residue 为 `0/0`。

## 8. Verification

`scripts/verify_wu4_unscheduled_activity_contract.ps1` 独立检查：

- 项目 `.venv`、lock 与 `pip check`；
- 获批 Plan hash、五路径 Scope、精确 commit prefix；
- common 的 C2 实际 hash与其余 10 个 Schema 冻结 hash；
- 6 个 targeted tests 和完整 198-test suite；
- 全部既有 fixture 及 7/40/7；
- legacy/explicit timed、unscheduled 与互斥负例；
- Schema 数量 11、network/residue 0。

历史 verifier 的旧 common hash 是历史快照，不修改或绕过。

## 9. Scope

唯一五路径：`plans/work-unit-4-unscheduled-activity-contract.md`、
`schemas/common.schema.json`、
`tests/test_wu4_unscheduled_activity_contract.py`、
`scripts/verify_wu4_unscheduled_activity_contract.ps1`、
`docs/reviews/work-unit-4-unscheduled-activity-contract-review.md`。

禁止修改 plan/previous-plan/fixture-case Schema、validators、fixtures、
existing tests、dependencies、`PLAN.md`、handbook、WU2/WU3 模块。
禁止第六路径、Planner、网络、LLM、默认时间与 fixture 迁移。

## 10. Commit 序列

1. C0 `docs: record unscheduled activity contract plan` — Plan only。
2. C1 `test: expose unscheduled activity contract gap` — 新测试 only。
3. C2 `feat: allow day-assigned unscheduled activities` — common only。
4. C3 `chore: add unscheduled activity contract verification` — script only。
5. C4 `docs: prepare unscheduled activity contract review` — Review only。

不 amend、squash、reset 或 rebase；C1 有效 Red 必须保留。

## 11. 完成判定（12 条）

1. 获批 Plan hash 不变。
2. 起点 HEAD、branch、worktree、remote、stash 准确。
3. 最终仅五路径变化。
4. legacy timed 无迁移且继续有效。
5. 显式 day-assigned unscheduled 有效。
6. unscheduled 由父 day 明确归属。
7. start/end 仍拒绝 null 与空字符串。
8. partial、mixed 与未知 mode 均硬失败。
9. conditionally_feasible Plan 可包含 unscheduled activity。
10. 现有 fixture 与 192 tests 保持通过。
11. 完整回归 198/198，Schema/fixture 为 11 与 7/40/7。
12. Review 记录 diff、Red/Green、兼容性、Scope、边界并停止。

## 12. Blocking

立即停止：

- activity 不能只凭现有父 day 获得明确归属；
- 互斥分支无法只改 common 实现；
- 需要新增 day identity 或第六路径；
- 需要修改 plan/previous-plan Schema、validator 或 Schema 版本；
- 需要迁移 fixture，或 legacy timed artifact 失效；
- C1 不是精确 4 pass / 2 failures；
- C2 需要改测试；
- 要求本单元新增 start/end 顺序业务检查；
- 需要 Planner、网络或 LLM。

批准前不进入 Execute、不修改合同/测试、不 commit。
等待：`批准执行 Work Unit 4 Unscheduled Activity Contract Remediation`。
