# Work Unit 0 Review

Review 状态：`APPROVED`

Reviewer: Hugin
Approval result: APPROVED
Approval time: 2026-07-26T16:36:34.8523409+08:00
Approved scope: Work Unit 0 Plan v0.2, C0—C4
Approved HEAD before closure: 1970bde731a05628d7fb638eab434ed5d768b592

范围：获批 Plan v0.2 的 C0—C4。本文记录的是可独立复核的仓库、handbook、prior-art、契约和 scope 证据；不声明 Hugin 已验收，也不开始 WU1。

## 1. 结论

WU0 已建立可审计 Git 基线、最小仓库元文件、handbook 上下文留痕、三项 D0 prior-art、一套文档级架构/工件/fixture 契约和本 Review。三项研究对象均已通过一手来源完成核验，没有对象级 blocking；存在的许可限制已明确记录，没有推断“可自由复用”。

本工作单元没有业务代码、Schema、fixture、测试、validator、CLI、config、adapter、planner、HTML、依赖安装或真实 API 调用。因此：

- 测试 case：`0`；pass `0`；fail `0`；按批准 scope 不适用
- Schema validation：`0` 次；实际 Schema `0` 个；按批准 scope 不适用
- fixture fail→pass：`0` 组；实际 fixture `0` 个；WU0 只冻结 specification，不冒充已经 fixture-first

## 2. 冻结输入与 hash

| 对象 | C0/批准时 SHA256 | Review SHA256 | 结果 |
|---|---|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` | 一致；未修改、未改名 |
| `plans/work-unit-0-bootstrap-d0.md` | `4C7FE14CD5D2CE0CC8E8D624D93C24338EAF61A9DBC0778D101AB3565602DE3B` | `4C7FE14CD5D2CE0CC8E8D624D93C24338EAF61A9DBC0778D101AB3565602DE3B` | 一致；执行期间未修改 |

## 3. Handbook 前后对账

固定路径：`<handbook>`

| 项目 | Plan/C0 前 | C4 Review | 结果 |
|---|---|---|---|
| 本地 HEAD | `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b` | `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b` | 一致 |
| `origin/main` | `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b` | `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b` | 一致 |
| ahead/behind | `0/0` | `0/0` | 一致 |
| `git status --short` | `0` 行 | `0` 行 | clean |
| fetch | exit `0` | exit `0` | 成功 |
| `origin/main` 注入 | 24 个路径 | 24 个路径，失败 0 | 可追溯 |

实际注入路径及每条规则的工程影响见 `docs/handbook-context.md`。只使用 `git show origin/main:<path>`，没有 pull/merge/rebase/reset/checkout/switch/stash/clean/commit，也没有修改 handbook 文件。

## 4. Git 证据

分支：`main`；线性历史。

```text
60c07180c3e659e0980e5cc04d47537bb15fc0e5  chore: establish WU0 repository baseline
e29b7636fe3a5e745580395290c9dc20460e0a33  chore: bootstrap minimal trip-decider repository
b96c2474d7b4a56e673298f23506bcdf71445799  docs: record handbook context and D0 prior art
2fc9810c93508df87b4ad300d8cfa2b09085c337  docs: freeze initial architecture and artifact contracts
HEAD                                      docs: prepare WU0 review evidence
```

根 commit `60c0718` 的实测 stat：

```text
PLAN.md                           |  180 +++++++
plans/work-unit-0-bootstrap-d0.md | 1017 +++++++++++++++++++++++++++++++++++++
2 files changed, 1197 insertions(+)
```

最终 `git diff --stat 60c0718..HEAD` 应为 8 个白名单新增文件、`884` 行新增、0 行删除；C4 提交后以 Git 输出为准。完整 `git diff 60c0718..HEAD` 在 C4 后实际执行并检查，正文不复制整个 diff。

各 commit 单一职责对账：

| Commit | 文件 | 实测职责 |
|---|---|---|
| C0 | `PLAN.md`、获批 Plan | 仅建立冻结基线 |
| C1 | `.gitignore`、`.gitattributes`、`README.md` | 仅仓库元文件和诚实状态说明 |
| C2 | handbook context、prior-art | 仅上下文追踪与一手研究 |
| C3 | architecture、artifact contracts | 仅文档级架构、十项契约、fixture specification |
| C4 | 本 Review | 仅汇总复核证据 |

## 5. Scope 与文件清单

C4 后预期/验证值：

- tracked 文件：`10`
- C0 基线文件：`2`
- WU0 新增白名单文件：`8`
- 白名单外 tracked：`0`
- untracked：`0`
- 禁止目录 `.venv/src/schemas/fixtures/tests/scripts/examples`：`0`
- dependency/lock 文件：`0`
- 实际 `*.schema.json`：`0`
- 实际 fixture 文件：`0`
- 实际 test 文件：`0`
- 实际 `*.py/*.js/*.ts/*.tsx/*.ps1` 业务/校验代码：`0`

最终 tracked 清单：

```text
.gitattributes
.gitignore
PLAN.md
README.md
docs/architecture.md
docs/artifact-contracts.md
docs/handbook-context.md
docs/prior-art.md
docs/reviews/work-unit-0-review.md
plans/work-unit-0-bootstrap-d0.md
```

保护项：

- `PLAN.md`：未修改
- 获批 Plan：未修改
- handbook：未修改
- 用户系统配置：未修改
- 其他项目仓库：未修改
- 未创建远端、未 push、未创建 PR

## 6. D0 prior-art 证据

C1 至 C2 的 Git 提交边界间隔为 8 分 24 秒；该数据不是精确工时统计，仅用于证明未出现跨日失控执行。

| 对象 | 身份/正式来源 | 代码与数据 | license 结论 | 状态 |
|---|---|---|---|---|
| ChinaTravel | ICLR 2026；arXiv v5；官方 LAMDA-NeSy repo | repo、HF dataset、Google/NJU 数据入口均打开 | 论文写 CC-BY-NC 4.0，HF metadata 写 CC-BY-NC-SA 4.0，二者冲突；代码 repo 无可识别 LICENSE | 已核验，有已知复用限制 |
| Hao et al. | NAACL 2025 long paper，ACL Anthology DOI `10.18653/v1/2025.naacl-long.176` | 作者 repo 可访问，UnsatChristmas/脚本存在；主 TravelPlanner 数据需另取 | 作者 repo 无可识别 LICENSE | 已核验，有已知复用限制 |
| ItiNera | EMNLP 2024 Industry Track，ACL Anthology | 官方 repo 与上海演示数据可访问 | GPL-3.0；README 另要求商业使用联系作者 | 已核验，有已知复用限制 |

关键交叉核验：

- ChinaTravel 的六类环境约束与七个 DSL 概念簇是不同口径，没有混写。
- Hao 正式主结果是 Claude-3 test `93.9%`；`97.0%` 是 Appendix Table 8 的 GPT-4 `Ours+JSON` test，不是同一配置。
- Hao 确实调用 Z3 `get_unsat_core`；LLM 修复 prompt 的“minimal change”不是经过最小化证明的最小冲突/最小放松。
- ItiNera 明确把候选池、偏好检索、空间簇筛选与层次 TSP 排序分阶段。
- prior-art 文档有 `9` 个来源 ID、`10` 个 URL；白名单外来源 URL `0`。

完整 URL、版本、locator、retrieved_at 和访问结果见 `docs/prior-art.md` §7。未使用博客、媒体、搜索摘要或 AI 记忆作为结论来源。

## 7. 契约验证证据

C3 实测：

- A—H 阶段行：`8`
- 工件章节：`10`
- 生产者定义：`10`
- 消费者定义：`10`
- 硬失败边界：`10`
- fixture specification：`6`
- 必查术语缺失：`0`
- 规划核心中的婺源/上饶/三清山名称匹配：`0`

四项专门修正均已冻结：

1. candidates/evidence 阶段不可变与 recommendation 条件字段；
2. estimated fact 与 plan status 的保守边界分离；
3. Evidence Source 的判别联合；
4. constraint origin refs 的判别联合。

v3.1 六项语义均进入契约：证据正交化、四态可行性、城市无关 planner 边界、request/parse/constraints 权威分离、previous plan + deterministic diff、状态误标 invariant 验收。

## 8. 实际验证命令与结果

| 命令/检查 | exit/result |
|---|---|
| `git init -b main`、C0 add/commit/verify | exit `0` |
| C1 文件白名单、hash、secret assignment、`git diff --check` | exit `0` |
| handbook `fetch`、HEAD/origin/ahead-behind/status、24 路径 `git show` | exit `0`；读取失败 `0` |
| GitHub repository API 的 3 个 repo/license/root listing | HTTP 可访问；ChinaTravel/Hao license null，ItiNera GPL-3.0 |
| C2 固定七节、source ID、URL host、hash、handbook 对账、`git diff --check` | exit `0`；失败计数均 `0` |
| C3 artifacts/producers/consumers/hard-fail/fixture/stage/terms/city grep、`git diff --check` | exit `0`；失败计数均 `0` |
| `git ls-files`、untracked、白名单、禁止目录/依赖/Schema/fixture/test/code 扫描 | exit `0`；白名单外均 `0` |
| tracked 与全历史 secret regex 扫描 | exit `0`；匹配均 `0` |
| 高德 endpoint 或 `key=` query 扫描 | exit `0`；匹配 `0` |
| 在 `git ls-files` 得到的 0 个代码文件上扫描 `infer_`、`guess_`、`silent_fallback` | 代码匹配 `0`；文档中的同名文字仅为禁用规则/审计标签 |
| `Get-FileHash` 对比两份冻结输入 | exit `0`；一致 |
| `git show --root --stat 60c0718`、`git diff --stat/numstat/diff 60c0718..HEAD` | exit `0`；最终结果在 C4 后复跑 |
| C4 后最终审计脚本 | 首次误用 PowerShell 7 三元语法，在 Windows PowerShell 5.1 解析阶段 exit `1`、无写操作；兼容改写后完整复跑 exit `0` |

注：一次初始 PowerShell `Get-ChildItem -Include` 统计因参数匹配语义不适合此处而产生假计数，未作为完成证据。最终文件类型计数使用 `git ls-files` 和 `rg --files --hidden -g '!.git/**'` 复核，Schema/code 都为 `0`；这是 R10 下保留并纠正测量错误，而不是静默选择有利数字。

## 9. R10 自检

| 检查项 | 结论与证据 |
|---|---|
| silent fallback | 无代码；可疑函数名扫描 0；文档明确缺字段/hash/来源时硬失败 |
| 虚假默认值 | 没有 validator 或运行时 default；契约明确 Schema default 不自动注入 |
| `infer_*`/`guess_*`/`silent_fallback` | 实际代码文件 0，因此逻辑匹配 0；文档只记录禁用规则和本审计项 |
| 声明超过实现 | README 与两份契约均标 `DOCUMENT_CONTRACT_ONLY`；Review 明列 0 Schema/fixture/test/code |
| prior-art 二手来源 | 10 URL 均为允许的一手来源域名；locator/retrieved_at/license 有登记 |
| fixture 自指 | 实际 fixture 0；spec 要求 expected 人工按冻结规范写定 |
| “无解”过度宣称 | 无运行输出；文档明确 `no_plan_found` 只能写“尚不能证明无解” |
| LLM 作为证据来源 | 契约禁止 LLM 进入 `sources`；只允许进入 parser/producer provenance |
| estimated 冒充 verified | 确定性映射与保守边界已冻结；没有实际 fact 可误标 |
| commit message 与 diff | C0—C4 各自只含计划文件集合；消息与职责逐项一致 |
| secrets 进入 Git | tracked/history 扫描 0；高德 key 当前仅检测 configured=false，未读取或输出值 |
| 示例冒充运行 | prior-art/契约没有示例运行输出；所有数字来自命令或一手论文并带 locator |

## 10. 12 条完成判定

1. ✓ 已完成 — handbook 已 fetch；local/origin HEAD、0/0、fetch exit 0 已留痕。
2. ✓ 已完成 — 8 个强制文件和 16 个相关项目文件均从 `origin/main` 读取；24/24，失败 0。
3. ✓ 已完成 — `PLAN.md` 前后 SHA256 完全一致，未改名。
4. ✓ 已完成 — ChinaTravel、Hao、ItiNera 均有一手来源结论；无对象级 blocking。
5. ✓ 已完成 — prior-art 无二手来源/搜索摘要/AI 记忆冒充原文；URL 与 locator 可回读。
6. ✓ 已完成 — 目录职责、依赖方向、adapter 边界和城市无关规划核心已冻结。
7. ✓ 已完成 — 十项工件均定义生产者、消费者、顺序/不可变关系、字段、hash/provenance 和硬失败。
8. ✓ 已完成 — candidate/evidence、estimated、Evidence Source、constraint origin refs 四项修正已进入文档。
9. ✓ 已完成 — WU1 的 actual Schema、领域 ID、六 fixture、有效 red、测试骨架、strict validator 和依赖选型范围清楚。
10. ✓ 已完成 — 依赖、`.venv`、lock、Schema、fixture、test、CLI、config、业务代码计数均为 0。
11. ✓ 已完成 — 未调用高德；endpoint/key query 扫描 0；没有假 key、示例输出或搜索摘要制造完成证据。
12. ✓ 已完成 — handbook 未修改；未 push；未开始 WU1；C0、diff、hash、来源与 Review 可独立复核。

完成计数：`12/12`；已知限制不是未完成项：三项 prior-art 的 artifact license 边界已明确，其中 ChinaTravel 两处官方 dataset license metadata 冲突，相关代码/数据不会在未澄清前复用。

## 11. Blocking、限制与延后

- blocking：无。
- non-blocking：ChinaTravel dataset license metadata 冲突；ChinaTravel/Hao 代码仓库无可识别 license；ItiNera 为 GPL-3.0 且 README 有商业联系说明。
- deferred-to-WU1+：实际 Schema、validator、fixture/test、依赖选型、adapter、evidence 映射、proof、planner、replan、renderer 和真实江西验收。
- deferred-to-v1：完整目的地发现、可达圈、目的地粗可行性和未知答案的发现能力验证。
- handbook-candidate：正交证据映射、no-plan/proven-unsat 边界、旧计划确定性 diff、adapter/planner 城市边界。

## 12. 明确未做

- 未修改 `PLAN.md` 或获批 Plan
- 未修改 handbook
- 未安装依赖
- 未创建业务代码、Schema、fixture、测试、CLI 或 config
- 未调用高德真实接口
- 未提交或输出 secret
- 未 push、未创建远端或 PR
- 未开始 WU1

READY_FOR_HUGIN_REVIEW
