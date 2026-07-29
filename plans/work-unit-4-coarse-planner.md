# WU4-CP · Constraint Projection + Coarse Plan MVP Plan

Plan version: v0.1
Status: PENDING_HUGIN_APPROVAL
Decision: PARTIAL_CONDITIONAL_PLAN_WITH_BLOCKERS

## 1. 目标与实测基线

本单元消费已完成的 DOR、Evidence Runtime 与显式结构化约束，
生成确定性、可审计、不可发布的条件化粗计划。

2026-07-29 实测：

```text
branch/HEAD: main / e3660ee4fb93e27b27e7486b8bc1b1c75a67da21
worktree/remotes/stashes: clean / 0 / 0
tests/schemas: 198 passed / 11
fixtures/documents/dirty cases: 7/40/7
network attempts/temporary residue: 0 / 0
```
handbook local/origin 均为
`6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`，ahead/behind `0/0`；
必注入八个文件已从 `origin/main` 重读，handbook 工作树干净。

## 2. 现有合同审计与裁定

`request.payload.explicit.travel_window` 必填 `start/end/timezone`；
`must_visit`、`excluded` 是可选字符串数组，但 request 不是 solver SSOT。
`constraint-parse.payload` 通过 `request_ref` 回指 request；每个
`parsed_constraints[].constraint_id` 必须解析到 constraints 中的定义。
`constraints.payload` 通过 `request_ref`、`parse_ref` 回指两项上游；
每项约束实际字段为 `constraint_id/layer/category/operator/target_refs/
value/unit/origin/enabled`。`constraints_are_solver_ssot=true` 且
`request_auto_overwrite=false`，所以日期和选择只从 enabled constraints 读取。
`plan.payload.plan_status` 的实际枚举含 `conditionally_feasible` 与
`no_plan_found`。后者强制 `days=[]`、`proof_refs=[]`，并不允许省略
plan artifact；post-plan violations 又强制 `plan_ref`。
day 必填 `day_id/date/activities/legs`；activity 用 `candidate_ref`，
本单元采用 `timing_status=day_assigned_unscheduled` 且不得出现
`start_at/end_at`；`legs=[]` 合法。
Violations 可用 `conditions[]` 表达缺失依赖，用 `violations[]` 表达
capacity 结果；但它没有保存 blocked seed 及全部 alternative candidate refs
的字段。identity 详情因此只进入 planning gate；不创建
`candidate_conflict_sets`，unknown/ambiguity 不冒充约束冲突。
冻结 Schema 数为 11；其中 common hash 为
`A9134A705C67CF955228A28844AA2C5C42812AA2E0167E1256DB72F0ACAC36D7`，
plan 为 `81EEB5899C33F19DC6FA059C7D447D747E72E355F3084D925FD9410272389BD3`，
violations 为
`C117415030993C24649B17837EC2A35C69A2F1CEC7D923742ABD383BA85B394F`。

## 3. 精确输入与引用闭包

公共接口冻结为：

```python
run_coarse_planner(
    recovery_root: Path,
    evidence_root: Path,
    planning_input_root: Path,
    output_root: Path,
) -> ValidationResult[CoarsePlannerSummary]
```

只读取 recovery 的 `candidates.json`、`seed-accounting.json`、
`record-local-facts.json`、`run-summary.json`；只读取 evidence 的
`evidence.json`、`evidence-gate.json`、`run-summary.json`；只读取
planning input 的 `request.yaml`、`constraint-parse.json`、
`constraints.yaml`。不递归、不搜索 latest、不猜替代文件。
每个固定路径必须是 UTF-8、非 symlink regular file；JSON/YAML 严格加载。
DOR/Evidence control document 的 exact keys、run ID、声明 hash、计数、
completion status 与 `network_attempts=0` 必须互相一致。
planning 三工件用 constraints root 做 CLOSED bundle 验证。
planning request 必须与 candidates 的 `request_ref` 精确匹配
artifact ID、type、schema version 与 payload hash；不得伪造新 request。
用户后续改日期必须体现为 constraints 的 `user_edited` 版本。

## 4. WU4 最小约束 profile

Schema 的 category/operator 是开放字符串；本节冻结 WU4 支持的唯一语义，
Schema 只验证结构，runtime 对 profile 做确定性硬检查。
旅行日约束唯一形态为 enabled hard constraint：
`category=time_window`、`operator=within`、target 为匹配 request ID 的
`request_scope/travel_window`、`unit=null`、value 精确为
`YYYY-MM-DD/YYYY-MM-DD`。两端均为 ISO date、start 不晚于 end，
按闭区间枚举 day；缺失或重复 time_window 硬失败。
must-visit 唯一形态为 enabled hard constraint：
`category=must_visit`、`operator=include`、target scope `must_visit`、
`unit=null`、value 为唯一非空字符串数组。字符串只能精确解析为现有
seed 或 candidate ID，数组顺序是 coarse allocation order。
excluded 唯一形态为 enabled hard constraint：
`category=excluded`、`operator=exclude`、target scope `excluded`、
`unit=null`、value 同样为唯一非空字符串数组。
三类 enabled constraint 的 origin 只允许 `explicit` 或 `user_edited`。
其他 enabled category/operator/target、`inferred/default`、未知引用、
多义引用或 must/excluded 同一引用全部硬失败；disabled 项不参与求解。
正式合同没有 locked-order scope/字段，本单元不实现用户锁定顺序。
不读取 natural language，不生成默认日数、时刻、时长、路线或偏好。

## 5. Candidate 准入、必需集合与排序

seed 只有同时满足 gate `generation_status=ELIGIBLE`、唯一 candidate ref、
对应 `candidate_results[].evidence_complete=true`、ref 在 candidates 和
evidence 中可解析、且未被 excluded 时，才能进入活动。
`BLOCKED_IDENTITY_AMBIGUOUS`、`BLOCKED_IDENTITY_UNMATCHED`、
`BLOCKED_EVIDENCE_INCOMPLETE` 均不得进入 activity。
blocked seed 的原顺序、identity status、全部 candidate refs、
generation status 与 block reasons 原样写入 planning gate。
存在 must-visit 时，required 集合只含该列表中可准入的 refs，顺序取
must-visit；其余 eligible refs 进入 `unselected_eligible_candidate_refs`。
不存在 must-visit 时，required 集合为全部可准入 refs，顺序严格取
seed-accounting。不得以 ID、label、category、坐标、距离或 provider 顺序重排。
excluded seed 映射到其全部真实 candidate refs，blocked alternatives 仍在
blocked record 中保留；不选择剩余 identity，不创建 placeholder。
Plan 的 `excluded_candidates[]` 只写实际 candidate refs、原因和约束 refs。

## 6. 分配与状态机

每个显式 day 最多一个 required candidate，按冻结顺序顺次分配。
可容纳分支输出全部显式日期；每个 activity 仅含稳定 ID、candidate ref、
相关 constraint refs、该 candidate 的 fact refs 和
`timing_status=day_assigned_unscheduled`；每个 day 的 `legs=[]`。
required count 大于零且 `day_count >= required_count` 时：
`plan_status=conditionally_feasible`、`draft_created=true`、
`publishable=false`。conditions 固定覆盖 route evidence、opening hours、
activity duration、specific times；有 blocked seeds 时再加 identity blocker。
缺失事实没有 fact ref，不虚假回指 candidate-local facts。
`required_count=0` 时输出 `no_plan_found`，reason 为
`NO_REQUIRED_ELIGIBLE_CANDIDATE`。`day_count < required_count` 时也输出
`no_plan_found`，reason 为
`INSUFFICIENT_DAY_CAPACITY_FOR_ONE_PER_DAY_ALLOCATOR`。
no-plan 的 `plan.json` 必须 `days=[]`、`proof_refs=[]`、无部分分配且 `draft_created=false`；
gate 保留全部 required refs 为 unscheduled。violations 使用
`kind=conditional` 并明确“当前粗分配器未找到计划，未证明不可行”；
不得产生 proof、`proven_infeasible` 或 silent drop。
`base_selections=[]`、`objective_breakdown.components=[]`，不暗示基地选择或
优化。constraint evaluations 只对三类支持约束给出
`satisfied/conditional/unsatisfied/not_evaluated`，不评价其他业务能力。

## 7. 四个固定输出

两个分支均原子安装且只安装：

```text
plan.json
violations.json
planning-gate.json
run-summary.json
```
plan/violations 是 schema `0.1.0` 正式 artifacts；violations 为
`evaluation_stage=post_plan`、状态与 plan 相同、`plan_ref` 精确，
`candidate_conflict_sets=[]`、`proofs=[]`。conditional 分支的
violations conditions 与 plan conditions 逐项相同。
planning gate 精确冻结 `schema_version/run_id/draft_created/publishable/
planning_status/generation_allowed_input/eligible_candidate_refs/
scheduled_candidate_refs/unscheduled_eligible_candidate_refs/
unselected_eligible_candidate_refs/excluded_candidate_refs/blocked_seeds/
unsatisfied_conditions/no_plan_reason`；`publishable` 永远为 false。
run summary 精确冻结 input artifact IDs 与 file hashes、day/eligible/
required/scheduled/blocked counts、四个 output paths、前三个输出 hashes、
plan/violations artifact IDs、network/LLM calls 为 0 与 completion status；
summary 不保存自身 hash。
run/artifact/entity IDs 来自现有 stable helpers 与 canonical payload hash。
`created_at` 取正式父 artifacts 中最新的已验证 timestamp，保证同输入确定；
两个 clean output roots 必须字节一致。非空 output root 硬失败；失败 rollback，
安装后重读并核验 bytes hash，不泄漏绝对路径、输入值或第三方异常。

## 8. Fixture-first 测试

`tests/test_wu4_coarse_planner.py` 恰好六例。DOR 与 Evidence 输入由真实
离线入口写入系统临时目录；planning 三工件由测试按上述 profile 独立手写，
expected 人工冻结，不新增 repository fixture、不由 planner 反喂 expected。

- CP01：显式两日得到江岭、李坑两个 unscheduled activity 和 conditional plan。
- CP02：篁岭/庆源不入活动，全部 alternatives、空 refs 与 reason 保留。
- CP03：输入 generation_allowed=false，仍有 draft，但 publishable=false。
- CP04：一日不足容纳两项时产出 no-plan plan，零 days/proofs、零 silent drop。
- CP05：无 start/end/legs/route/duration/opening/ranking/recommendation 字段或声明。
- CP06：双 root 字节一致；非空 root 不变；注入安装失败完整 rollback。

C2/C3 使用逐字符相同命令：
```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu4_coarse_planner -v
```
C2 必须为 6 tests、0 pass、0 failure、6 个显式 `NotImplementedError`、
零 import/path/dependency/network 错误；C3 必须 6/6 green。
完整入口目标为 204/204、11 Schema、fixtures/documents/dirty cases
`7/40/7`、network attempts 0、LLM calls 0、temporary residue 0。

## 9. Scope、commit 与验证

唯一五路径：

```text
plans/work-unit-4-coarse-planner.md
src/trip_decider/coarse_planner.py
tests/test_wu4_coarse_planner.py
scripts/verify_wu4_coarse_planner.ps1
docs/reviews/work-unit-4-coarse-planner-review.md
```
禁止修改 Schema、fixture、validator、existing tests、Recovery、Evidence
Runtime、Resume/FER、adapter、dependency、PLAN.md、handbook 与历史 verifier。
线性 commit：
```text
C0 docs: record WU4 coarse planner plan
C1 chore: add coarse planner interface
C2 test: add failing coarse planner cases
C3 feat: implement conditional coarse planner
C4 chore: add coarse planner verification entry
C5 docs: prepare WU4 coarse planner review
```
C0 只提交获批 Plan；C1 只提交可导入 stub；C2 只提交 tests；C3 只修改
coarse_planner.py；C4 只提交 verifier；C5 只提交 Review。C2 保留 red，
其余 commit 结束时既有 suite 必须 green；不改写历史。
verifier 固定检查 204 tests、11 Schema hash、7/40/7、四输出、CLOSED
plan/violations bundles、scope/commit prefix、fallback/secret 扫描、
network/LLM/residue 为零、Plan 与冻结输入 hash 未变。

## 10. 完成判定（18 条）

1. 基线与 handbook 对账留痕；2. 获批 Plan 字节未改；
3. 三 root 只消费固定文件；4. planning bundle CLOSED；
5. constraints 是唯一 solver SSOT；6. 未解析自然语言或生成默认；
7. 准入四条件全部执行；8. blocked refs/reasons 完整保留；
9. only must/seed ordering；10. 一日最多一个 unscheduled activity；
11. conditional conditions 完整且 publishable=false；
12. no-plan 有合法 plan、零 days/proofs、无过度声明；
13. 四输出及两个正式 CLOSED bundle 通过；14. IDs/hash/provenance 可回读；
15. C2 red 与同命令 C3 green；16. 204 与 7/40/7 全绿；
17. 五路径 scope、secret/fallback/network/residue 门通过；
18. Review 可用 Git/hash/命令证据独立复核。

## 11. Blocking

立即停止：现有 Schema/validator 无法通过上述 CLOSED bundles；需要第六路径、
Schema/validator/WU3/DOR 修改；需要猜日期、时刻、时长、路线、营业时间、
identity 或 locked order；需要 LLM/网络；需要把 no-plan 写成 infeasible；
或任何输入无法在不打印原值的情况下确定性拒绝。

批准前不执行 C0—C5、不提交、不创建实现、测试、verifier 或 Review。
等待：`批准执行 Work Unit 4 Coarse Planner`。
