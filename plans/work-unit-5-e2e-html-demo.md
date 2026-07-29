# WU5-E2E · End-to-End Orchestration + HTML Result MVP Plan

Plan version: v0.1
Status: PENDING_HUGIN_APPROVAL
Decision: ORCHESTRATE_EXISTING_STAGES_AND_RENDER
## 1. 目标与实测基线

本单元只把已批准的 Recovery、Evidence Runtime、Coarse Planner 顺序编排，并把其已证明结果渲染成静态、可审计、不可发布的单文件 HTML。
不新增规划、证据、identity、推荐、路线或自然语言生成逻辑。

2026-07-29 实测：

```text
branch/HEAD: main / e008d9e6fbdd81f7642f32bd0d6488a61bb6d539
worktree/remotes/stashes: clean / 0 / 0
tests/schemas: 204 passed / 11
fixtures/documents/dirty cases: 7/40/7
outputs/network/LLM/temporary residue: 4 / 0 / 0 / 0
```

handbook local/origin 均为
`6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`，ahead/behind `0/0`；
八个必注入文件已从 `origin/main` 重读，handbook 工作树干净。
## 2. 既有接口与输出合同

机械审计确认正式签名为：

```python
run_wu2_recovery(replay_root: Path, output_root: Path)
run_evidence_runtime(recovery_root: Path, output_root: Path)
run_coarse_planner(
    recovery_root: Path,
    evidence_root: Path,
    planning_input_root: Path,
    output_root: Path,
)
```

三者均返回 `ValidationResult[Summary]`，成功要求 `problems=()` 且 value 非空。
Recovery summary 实际含 run ID、四个路径、candidate/seed counts、
network attempts 与 output hashes。
Evidence summary 实际含 run ID、三路径、candidate complete/incomplete、
eligible/blocked、generation allowed、network attempts 与 output hashes。
Planner summary 实际含 run ID、四路径、planning status、draft/day/eligible/
required/scheduled/blocked counts、network/LLM calls 与 output hashes。

真实输出字段已在系统临时目录零网络运行中读取：
plan payload 含 status、days、conditions、evaluations 与 refs；
violations payload 含 status、conditions、violations、proofs；
planning gate 含 blocker、scheduled/unscheduled refs、publishable 与 no-plan reason；
planning run summary 含 input artifacts/file hashes、counts、paths 与 output hashes。
本单元只消费这些命名字段，不扫描目录、不选择 latest、不猜兼容字段。

冻结输入 hash：

```text
recovery.py: C0E098DD4AB997727A0EFBCCC9C396AC480DEEB3477DBF4CDCB5E31A34E0D8BA
evidence_runtime.py: 626D052F068537D050D350E8404948286670405D0B75C2E793CAA71656C89C04
coarse_planner.py: 8098F75190E279419D704E9135B896DE84D88691D4B2A942142671C870E25D8C
WU4 test input: 1A9A090F32E9C785F36034A23B66D76F0173EDA95069882F514E3AFCE4C289E4
PLAN.md: 563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456
```
## 3. 公共接口与严格调用链

新增 `E2EDemoSummary` 与唯一 library 入口：

```python
run_e2e_demo(
    anchor_root: Path,
    planning_input_root: Path,
    output_root: Path,
) -> ValidationResult[E2EDemoSummary]
```

固定顺序为 Recovery → Evidence Runtime → Coarse Planner → renderer。
Recovery 写 staging/recovery；Evidence 只读该目录并写 staging/evidence；
Planner 只读上述两目录及显式 planning input，并写 staging/planning。
每个正式入口恰好调用一次，不使用 fake summary，不复制其验证或业务判断。
任一 stage 返回 problems 时立即停止，后续 stage 与 renderer 均不运行。
上游问题保留原 error code/pointer/rule/message，但 artifact path 安全规范为
`input/anchor/...`、`input/planning/...` 或 stage 相对路径，绝不返回绝对路径。

`E2EDemoSummary` 固定返回 run ID、顶层 summary/report paths、planning status、
draft/publishable/generation flags、scheduled/blocked counts、network/LLM counts
及五个顶层输出 hash；不创建新的 artifact 或随机业务身份。
## 4. 目录级事务与 Windows 裁定

output parent 必须是已存在、非 symlink 的普通目录。
Windows 实测 `os.replace(staging_dir, missing_target)` 成功，
而替换已存在空目录得到 `PermissionError`。
为保证一次目录安装且不删除调用者对象，冻结 `output_root` 必须不存在；
已存在的空或非空 root 均确定性硬失败，任何已有文件都不覆盖。

使用 `tempfile.mkdtemp` 在 output parent 创建随机、同卷 staging directory。
随机 staging 名不得进入任何输出字节、run ID、HTML 或 summary。
所有 stage、HTML 与顶层 summary 先写 staging，并逐项回读验证。
准备完成后只调用一次 `os.replace(staging_root, output_root)`。
失败时 finally 只删除本次创建的 staging；安装后复核失败则只删除
前置已证明不存在、由本次新装入的 output root。
不得在仓库创建 runtime、临时 Python 或 staging 文件。
两个不同 parent 下的 clean runs 必须具有完全相同的相对文件集合和字节。
## 5. 固定输出与顶层 summary

成功输出严格为 recovery 四文件、evidence 三文件、planning 四文件、
`report/index.html` 与顶层 `run-summary.json`，不复制 stage output。
顶层 control document 使用 `schema_version=wu5-e2e-demo-run/1.0`。
顶层 `run_id` 直接复用 Planner run ID，不另建 UUID。
input.anchor 复制 Recovery summary 的 fixture identity 与 hashes；
input.planning 复制 Planner summary 的 input artifact IDs 与 file hashes。
stages 按 recovery/evidence/planning 固定顺序保存各 stage run ID、
summary 相对路径及该 summary 实际字节 SHA256。
result 保存 planning status、draft created、publishable、
generation allowed input、scheduled count 与 blocked count。
report 只保存 `report/index.html` 与实际 SHA256。
network attempts 与 LLM calls 必须分别为零；summary 不保存自身 hash。
所有路径使用 POSIX 风格相对路径，禁止绝对路径、坐标、raw body 或 secret。
## 6. HTML 信息架构与安全

HTML 为 UTF-8 无 BOM 单文件，只有内联 CSS，无 JS、外链、CDN 或网络资源。
模板和 section 顺序固定；所有 artifact 字符串经
`html.escape(value, quote=True)`，不得直接拼接未转义内容。
固定五区为状态、日程草案、待确认/未匹配、证据状态、尚未验证条件；
底部再显示固定顺序审计字段与相对 artifact links。

状态区明文显示“条件化粗计划”“不可直接发布”
及“未进行路线、营业时间或时长验证”，并显示
`publishable: false`、`generation_allowed_input: false`。
日程严格按 plan days/activity 顺序，以 candidate ref 查 candidates label；
当前显示第 1 天江岭、第 2 天李坑及“具体时刻：尚未安排”。
不得出现推荐、最佳、上午、时长、距离、交通、排序或优化措辞。

blocker 严格按 planning gate 顺序渲染。
篁岭显示 ambiguous 文案及全部 alternative refs，不选择其中任何一个；
庆源显示 unmatched、空 refs 与“未创建占位地点”。
证据区从 evidence facts 读取并显示真实 support/display statuses；
当前全部为 unknown，并附固定能力边界文案，不声明已核实、官方或实时。
conditions 按 Planner 原数组顺序显示原 `condition_id` 与转义后的 description；
不翻译、合并、重排或从文本推导新结论。
审计区仅显示 plan/evidence artifact ID、candidate/fact/scheduled/blocked counts
与复用的 run ID；链接只指向固定相对文件。
## 7. no_plan_found 页面

当 plan status 为 `no_plan_found` 时不渲染空日程卡片。
页面显示“当前粗分配器未找到计划”、planning gate 的原 no-plan reason、
全部 `unscheduled_eligible_candidate_refs` 及可解析 label。
同时保留全部 blocker，并明确“这不等于已证明不可行”与 publishable=false。
不得显示无法旅行、行程不可行、约束无解、proof 或虚假部分分配。
status 与 gate/summary 不一致、ref 无法解析或必填字段缺失均硬失败并 rollback。
## 8. CLI 与错误输出

同一模块用标准库 `argparse` 提供三个必填路径参数及 `main()`。
成功 exit 0，stdout 仅一行：
`status=... scheduled=... blocked=... publishable=false report=report/index.html`。
失败 stdout 为空，stderr 为稳定七字段 JSON Lines `ValidationProblem`。
artifact/stage validation 返回 exit 2，路径/读取/解析返回 exit 4，
内部、renderer、transaction 或未分类错误返回 exit 5。
错误不得含绝对路径、输入值、第三方异常原文、坐标或 secret。
## 9. Fixture-first 与 Red → Green

`tests/test_wu5_e2e_demo.py` 恰好六例；使用已提交真实 anchor，
planning inputs 在系统 temp 由既有独立手写 builder 产生，不新增 fixture。
expected 文案、DOM section、相对路径和字段由测试独立冻结，
HTML parser 只检查结构，不生成 expected。

- E2E01：真实两日链路生成 13 个固定文件及成功顶层 summary。
- E2E02：日程显示江岭/李坑与未排时刻，且无禁止能力声明。
- E2E03：篁岭全部 alternatives 与庆源 unmatched 完整，无选择/placeholder。
- E2E04：unknown Evidence、两个 false flag 与全部原 Planner conditions。
- E2E05：一日 no-plan 显示 reason/required refs 且明确未证明不可行。
- E2E06：三个 stage 各一次、双 root 字节一致、nonempty 拒绝、失败 rollback、
  network/LLM 为零且无临时残留。

C2/C3 使用逐字符相同命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu5_e2e_demo -v
```

C2 必须为 6 tests、0 pass、0 failure、6 个显式 `NotImplementedError`；
C3 必须 6/6 green，二者 network/LLM 均为零。
完整回归必须 210/210、11 Schema、7/40/7、零 network/LLM/residue。
## 10. Verification entry

verifier 先锁定获批 Plan、三个 runtime、WU4 input builder、anchor 四文件、
11 Schema、PLAN.md 与历史文件 hashes，再检查五路径 scope 与 commit prefix。
它在系统 temp 使用既有手写 builder 创建显式两日 planning inputs，
并实际执行 `python -m trip_decider.e2e_demo`，不从测试输出生成 expected。
它验证 CLI exit/stdout/stderr、13 文件、相对路径、hash、HTML 必需/禁止文本、
双 root 字节一致、no-plan、rollback、secret/fallback 与零网络/LLM/residue。
## 11. Scope、commit 与完成判定

唯一五路径：

```text
plans/work-unit-5-e2e-html-demo.md
src/trip_decider/e2e_demo.py
tests/test_wu5_e2e_demo.py
scripts/verify_wu5_e2e_demo.ps1
docs/reviews/work-unit-5-e2e-html-demo-review.md
```

禁止修改 Schema、fixtures、validators、existing tests、三个 runtime、
Resume/FER/adapters、dependencies、pyproject、PLAN.md、handbook 与历史 verifier。
线性 commit 固定为 C0 Plan、C1 interface、C2 red tests、C3 implementation、
C4 verifier、C5 Review，消息逐字符采用批准提示中的六条；不改写历史。

完成判定共 16 条：1 基线/handbook；2 Plan hash；3 三 stage 各一次；
4 fail-fast/rollback；5 同父目录一次安装；6 固定 13 文件；
7 顶层 summary 可回读；8 HTML 转义/离线；9 五区与审计链接；
10 blockers 完整；11 unknown/false 不提升；12 no-plan 不冒充 infeasible；
13 CLI 安全；14 Red/Green；15 210 与 7/40/7；16 scope/hash/Review 可复核。
## 12. Blocking

立即停止：需要修改既有 runtime/Schema/validator/fixture/dependency/第六路径；
需要复制 stage 判断、重推 Planner、选择 identity、调用网络/LLM；
无法安全转义或安全规范错误路径；Windows 目录事务无法维持一次安装与 rollback；
或实际输出字段不能支持规定页面而不虚构数据。

批准前不执行 C0—C5、不提交、不创建实现、测试、verifier 或 Review。
等待：`批准执行 Work Unit 5 End-to-End HTML Demo`。
