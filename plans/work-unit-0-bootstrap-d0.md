# trip-decider · Work Unit 0 Plan：仓库 bootstrap、D0 prior-art 与文档级工程契约

> Plan Version: `v0.2`
>
> Status: `PENDING_HUGIN_APPROVAL`
>
> 计划日期：2026-07-26（Asia/Shanghai）
>
> 修订记录：v0.2 按 Hugin 审核意见收缩 WU0；Schema、fixture、validator、CLI、配置实现、依赖安装与 red→green 全部回归 WU1。
>
> 执行授权：只有收到 Hugin 对本版本的语义明确授权后才进入 Execute。
>
> 本计划的产品 Source of Truth：根目录冻结文件 `PLAN.md`（逻辑名 `plan.md`），SHA256 `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456`。
>
> 本计划只定义 WU0；WU1—WU8 仍须分别走 Plan → 批准 → Execute → Review → 验收。

## 0. 冲突与裁定

下表只处理冻结产品定义与实施语义之间的表面冲突，不重新设计产品。

| 编号 | 表面冲突或歧义 | 裁定 | 依据与影响 |
|---|---|---|---|
| D-01 | `PLAN.md` §4 把 `verified/sourced/estimated/conflicting/unknown` 写成单一证据状态；v3.1 要求内部正交化 | 外部仍显示五态，内部拆成 `support_status`、`derivation`、`freshness`、`sources`，由版本化纯函数确定性映射 | v3.1 是工程语义勘误；避免把“支持程度、产生方式、冲突、时效”混成一个枚举 |
| D-02 | `PLAN.md` §5、§7 写“无解/最小冲突集”；启发式未找到方案不能证明无解 | 领域状态固定为 `feasible/conditionally_feasible/proven_infeasible/no_plan_found`；未经真正最小化验证只输出 `candidate_conflict_set` | v3.1 与 R10 优先；用户文案不得把 `no_plan_found` 写成“不可能” |
| D-03 | `PLAN.md` §3 禁止任何城市专属代码或配置；v3.1 允许地区/来源适配器 | `planner/constraints/evidence/domain` 不得感知城市名；`adapters` 可按供应商、来源类型、适用地区注册，但必须输出统一 Evidence Contract | 保留城市无关规划逻辑，同时允许现实数据采集 |
| D-04 | `PLAN.md` §7 只有 `request.yaml` 与 `constraints.yaml`；v3.1 增加解析留痕和权威边界 | 新增 `constraint-parse.json`；`request.yaml` 保存原始请求且求解器不可改，`constraints.yaml` 是求解唯一 SSOT，用户修改不得被重解析覆盖 | 防止原始请求、推断结果、用户最终约束互相覆盖 |
| D-05 | `PLAN.md` §7 只说“最小改变”；v3.1 要求旧计划基准和确定性代价 | 新增 `previous-plan.json` 与 `plan-diff.json`；变更权重配置化、可测试、可回读约束 ID | WU0 冻结契约，WU6 实现 |
| D-06 | `PLAN.md` §9 把“verified 后现实为错”直接视作 invariant 失败；v3.1 区分来源变化、过期、采集/标准化错误和状态误标 | 硬 invariant 只认“展示状态高于实际证据支持”；现实偏差按五类归因，只有 `状态误标` 直接违反 invariant | 保持实旅验收诚实，不承诺现实永不临时变化 |
| D-07 | `PLAN.md` §6 写“LLM + web 搜索补”，容易让 LLM 被误记为来源 | LLM 只生成检索词、抽取、标准化和表达理由；来源只能回指实际网页、公告、API 响应或允许的直接观测；LLM 标识只进处理 provenance，不进 `sources` | v3.1 与 R10 |
| D-08 | 产品“能力 A”指目的地发现，而管线 `[A]` 指需求澄清 | 文档中始终写“能力 A（目的地发现）”或“管线 A（需求约束化）”，不使用无上下文的“A” | 防止接口和里程碑误读 |
| D-09 | `feasible` 的定义允许地图/API 估算参与，而 v0.1 曾把任何关键 `estimated` 自动降为 `conditionally_feasible` | `unknown/conflicting` 影响硬约束时必须 conditional；`estimated` 本身不自动决定计划状态。估算必须带方法、不确定性/缓冲和保守边界；保守边界下仍满足硬约束可标 feasible，否则 conditional。事实仍显示 estimated | 区分“值怎样产生”与“在保守边界下结构是否可行”，避免真实地图路时让所有计划永久 conditional |
| D-10 | 当前磁盘文件名是 `PLAN.md`，提示词多处写 `plan.md` | Windows 上两者解析到同一文件；执行、hash 与保护清单使用实际字面 `PLAN.md`，报告同时注明其逻辑名 | 不做大小写重命名，不制造无意义 diff |

当前没有需要重新裁定产品定位的冲突。若 Execute 发现新冲突，立即停止，不在 WU0 内自行改计划。

## 1. 任务目标

WU0 只负责：

- 建立本地 Git 仓库基线和 `main` 线性分支，不创建远端、不 push；
- 将 `PLAN.md` 与获批的 WU0 Plan 原字节纳入版本控制；
- 创建最小仓库元文件；
- 从 handbook 固定路径的 `origin/main` 加载规则，并创建精简留痕；
- 在半天硬限时内完成 ChinaTravel、Hao et al.、ItiNera 的一手来源研究；
- 冻结最小目录职责与城市无关边界；
- 冻结十项阶段工件的文档级契约草案、provenance/hash 规则和硬失败边界；
- 冻结 v3.1 六项实施勘误对应的领域契约；
- 冻结 fixture specification、有效 red 定义和后续工作单元归属；
- 明确 WU1 的 Schema、领域模型、fixture-first 测试骨架与严格 validator 实施范围；
- 记录 secrets、未来依赖与 Windows 兼容策略，但不安装依赖、不实现配置；
- 产出可独立复核的 WU0 Review 证据；
- 为 WU1 及后续工作单元提供稳定、可回放、可独立复核的输入。

WU0 不负责：

- 高德真实 API 接入或任何真实 HTTP 调用；
- 真实 POI 抓取、路径矩阵、开放时间或班车信息采集；
- 江西行程求解、基地选择、分天、排序、约束放松算法；
- 完整证据自动定级和依赖传播；
- HTML 行程卡生成；
- 能力 A（目的地发现）的实现；
- Web UI、小程序、账号、多用户、分享、OTA、订票、酒店/机票比价；
- 数据库、消息队列、容器编排、云服务、向量数据库或多 Agent 框架。
- 实际 JSON Schema 文件、六组 `case.json` 或任何 fixture 文件；
- 测试代码、schema/fixture validator、CLI 或 config 实现；
- `.venv`、PyYAML/jsonschema 安装或 `requirements.lock`；
- 任何业务或契约代码的运行；
- 以缺模块/import 失败制造 red，或宣称 fixture-first 已在 WU0 落地。

## 2. 输入与基线

### 2.1 命令实测事实

本节数字均来自 2026-07-26 的命令输出，不是估算。

| 项目 | 实测值 |
|---|---|
| 当前工作目录 | `<repo>` |
| Git 仓库 | 否；`git rev-parse --show-toplevel` 未得到仓库根 |
| 当前文件清单（写本计划前） | 仅 `PLAN.md`，1 个文件，9914 bytes |
| `PLAN.md` SHA256 | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| 操作系统 | Microsoft Windows 11 专业版，版本 `10.0.26200`，Build `26200` |
| PowerShell | `5.1.26100.8875` |
| Python | `3.11.9` |
| pip | `24.0`，由 Python 3.11 环境提供 |
| uv | `NOT_AVAILABLE` |
| Poetry | `NOT_AVAILABLE` |
| Git | `2.53.0.windows.1` |
| handbook 固定路径 | `<handbook>` |
| handbook 是否为 Git 工作树 | 是 |
| handbook 当前分支 | `main` |
| handbook fetch | `git fetch origin --prune` exit code 0 |
| handbook 本地 HEAD（fetch 前后相同） | `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b` |
| handbook `origin/main` | `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b` |
| HEAD 相对 `origin/main` | ahead `0` / behind `0` |
| handbook 工作树 | `CLEAN` |
| 网络 | `github.com:443=True` 且 handbook fetch 成功；这只证明 GitHub HTTPS，不代表三家论文站点均可访问 |
| 高德 key | 环境变量名中未发现 `AMAP` 或 `GAODE`；未读取任何环境变量值 |
| 当前敏感信息 | 未发现高德 key；仍须保护未来 key、`.env`、真实旅行请求、真实 anchor、原始 API 响应、可能带凭据的 URL/日志 |

如果 WU0 获批，第一项执行动作是 `git init` 并建立 `main`；Plan 阶段不得初始化。

### 2.2 实际加载的 handbook 文件

所有内容均通过 `git -C $Handbook show origin/main:<path>` 读取，未从本地工作树内容推断。共实际加载 24 个文件：

1. `STATE.md`
2. `INDEX.md`
3. `SUMMARY.md`
4. `tools/context-injection.md`
5. `principles/r10-honesty.rule.md`
6. `principles/per-protocol.rule.md`
7. `principles/scope-control.rule.md`
8. `principles/fixture-first.rule.md`
9. `projects/INDEX.md`
10. `projects/solution-drafter/MEMORY.md`
11. `projects/solution-drafter/LESSONS.md`
12. `projects/solution-drafter/STATE.md`
13. `projects/agentic-kb-lite/MEMORY.md`
14. `projects/agentic-kb-lite/LESSONS.md`
15. `projects/agentic-kb-lite/STATE.md`
16. `projects/tender-writer/MEMORY.md`
17. `projects/tender-writer/LESSONS.md`
18. `projects/tender-writer/STATE.md`
19. `projects/cim-link-engine/MEMORY.md`
20. `projects/cim-link-engine/LESSONS.md`
21. `projects/cim-link-engine/STATE.md`
22. `projects/jiangli/MEMORY.md`
23. `projects/jiangli/LESSONS.md`
24. `projects/jiangli/STATE.md`

未加载 ISC 求职叙事、项目 META 和与本项目无直接关系的项目卡片。

### 2.3 冻结方案审读摘要

| 项目 | `PLAN.md` 冻结内容 |
|---|---|
| v0 做什么 | 主攻行程结构决策：目的地已定后选择住宿片区、分天、天内排序、时间可行性、淘汰理由、证据状态、约束修改后局部重排；管线 A、C—H 在相应 WU 实现 |
| v0 不做什么 | 完整目的地发现、Web UI、多用户/账号/分享、自创完整 benchmark；长期不做 OTA、订票订酒店、酒店/机票比价、长篇攻略 |
| v1 提前冻结 | 能力 A（目的地发现）的输入可为空目的地、目的地候选/粗可行性/粗计划引用、稳定 destination ID、下游按统一候选与约束引用消费；v1 不得迫使 C—H 重构 |
| A—H 管线 | A 需求澄清与约束化；B 目的地候选池（v0 pass-through）；C POI 候选；D 证据；E 约束与冲突；F 基地/分天/排序；G 单文件 HTML；H 修改约束后最小改变重排 |
| 工件契约 | 原冻结方案有 `request.yaml/constraints.yaml/candidates.json/evidence.json/plan.json/violations.json/trip-card.html`；v3.1 增加 `constraint-parse.json/previous-plan.json/plan-diff.json` |
| 证据 invariant | 任何事实的展示状态不得高于证据实际支持状态；`unknown/conflicting` 不得静默支撑硬决策；v3.1 将硬违规精确为“状态误标” |
| 三层约束 | 环境可行性、用户硬约束、软偏好；推荐只进候选池，入选由约束、证据和结构决策决定 |
| 数据源与风险 | 高德 POI/路径、网页/官方信息、班车非结构化来源、住宿 POI 密度；高德配额/商用条款、班车可获得率、时效与冲突是风险；LLM 不是事实来源 |
| 时间线 | 2026-07-27 D0；D1-2 高德与真实 fixture；D3-5 约束/求解；D6-7 行程卡；D8-9 江西实跑与重排；D10（2026-08-05）定稿上路 |
| 真实旅行验收 | 8 月 5 日前产出并至少部分实走；零证据状态误标；记录现实证实/证伪；至少一次真实约束修改重跑；观察是否会主动再打开、愿意分享、同行者能否看懂 |
| 开放问题 | 高德配额/商用条款；ChinaTravel 数据集和 DSL 可用性；Hao 成绩 `97%` 与 `93.9%` 口径；乡镇班车信息可获得率 |

### 2.4 当前不得提交的内容

- 任意真实 API key、token、cookie、账号、Authorization header；
- `.env`、PowerShell profile、系统/用户配置；
- 未脱敏真实旅行者姓名、联系方式、证件、订单、精确住址；
- 未获授权的真实 anchor、原始 API 全量响应、带个人轨迹的日志；
- handbook 本地未提交内容或其完整复制；
- 搜索摘要、AI 记忆或示例输出伪装成已核验事实。

## 3. Handbook 影响摘要

### 3.1 四条核心规则的落地

| 规则 | trip-decider 的具体落地 |
|---|---|
| R10 | Schema 缺字段、类型错、hash/provenance 断裂时 exit 非零；不制造默认事实；LLM 只产语义结构，不作为证据；所有数量/hash/test 由命令产生；文案与四种可行性状态严格对齐；无真实 API/算法就不声明已实现 |
| PER | WU0 只按本计划执行；获批后一次性完成 C0—C4，末尾整体 Review；不在中间逐 commit 请审；WU1 不自动开始 |
| Scope | 执行文件白名单、保护清单、最大新增文件数和 12 条完成判定均在本计划锁定；计划外文件、产品冲突、真实 anchor 缺失或外部条件阻塞时停下 |
| Fixture-first | WU0 只冻结六项 fixture specification 与有效 red 标准，不创建 fixture/test；WU1 先创建可加载的接口、Schema、结构 fixture 和测试骨架，再以具体行为断言失败或明确 `NotImplementedError` 形成 red；WU3—WU6 在各自业务实现前重复行为级 red→green |

### 3.2 复用的项目模式

- solution-drafter：阶段间文件契约、上游产物必须被下游真实消费、契约兑现审计、“声明 > 实现”扫描、缺事实时显式缺失；
- tender-writer：脚本只做确定性处理、LLM 负责语义产出、anchor + generator 反自指、文案与控制流对账、敏感信息从源头不入 Git；
- cim-link-engine：replay-based eval、PASS/WARN/FAIL 类结论都要回归、current state 与 run history 分离、evidence/why/provenance 一等化、验收包是产品接口；
- agentic-kb-lite：依赖从简、结构化强断言、确定性变换可用合成输入和人工 expected、判不准不做、真实使用前不扩张 Web UI/向量库；
- jiangli：先闭环再扩功能、GIS 计算层与表达层分离、规范/来源口径与算法口径不互相冒名、真实数据不入 Git、优化实现与文档必须同步。

### 3.3 明确不复用

- 不复用 tender-writer 的 docx、Part 模型、投标合规状态机或开源发布流程；
- 不复用 agentic-kb-lite 的四级检索降级、向量/知识库问题域和“失败时保留 STUB”语义；trip-decider 的 schema/约束破坏必须硬失败；
- 不复用 cim-link-engine 的 UI、CIM 实体模型、回写流程或数据库；
- 不复用 jiangli 的 Vue/FastAPI/Tauri/SQLite、DEAP NSGA-II、栅格流水线；仅复用多目标决策的可解释边界和“算法实现 ≠ 领域事实”的教训；
- 不复用 solution-drafter 的文档生成五阶段和素材占位格式；
- 不引入 LangGraph、CrewAI、多 Agent、RAG、向量数据库、数据库、前端框架或云基础设施。

## 4. WU0 Scope

### 4.1 允许的动作

- 在当前目录执行 `git init`，创建/切换为 `main`，用包含冻结方案和获批 Plan 的首个 commit 建立可复核基线；
- 将 `PLAN.md` 与获批后的本计划按原字节加入版本控制，不修改内容；
- 按实际需要创建下列白名单内文件，新增文件最多 8 个；
- 只访问 prior-art 一手来源；不得调用高德；
- 严格按 C0—C4 commit 序列提交，不 push；
- 只执行 Git、PowerShell、文件 hash、文本/链接核验等文档与仓库验证命令。

### 4.2 新增文件白名单（最大 8 个）

以下是最大允许范围，不是为了凑数而必须创建满额。某个白名单文件经执行确认不需要时可以不创建；只有需要新增白名单外文件才触发 Plan 变更。

1. `.gitignore`
2. `.gitattributes`
3. `README.md`
4. `docs/handbook-context.md`
5. `docs/prior-art.md`
6. `docs/architecture.md`
7. `docs/artifact-contracts.md`
8. `docs/reviews/work-unit-0-review.md`

### 4.3 明确禁止修改

- `PLAN.md` 的任何字节、文件名或时间线内容；
- 本计划获批后的字节；若需调整，停止并重新走 Plan 审核；
- `<handbook>` 下任何工作树文件或禁止的 Git 操作；
- 用户 PowerShell profile、系统/用户环境配置、凭据存储；
- 当前工作区外任何项目仓库；
- 高德、GitHub 或其他远端服务状态；
- WU1+ 业务实现、v1 能力 A 实现和任何 UI；
- `src/`、`schemas/`、`fixtures/`、`tests/`、`scripts/`、`examples/` 下任何文件；
- `.env.example`、`pyproject.toml`、`requirements.lock`、`.venv`、Python 包或依赖。

### 4.4 数量边界

- Plan 阶段只新增本计划 1 个文件；
- WU0 Execute 最多新增 8 个白名单文件，实际未需要的可不创建；
- WU0 将 2 个既有文件（`PLAN.md`、本计划）原字节纳入 Git；
- 若 8 个白名单文件均创建，WU0 Review 时最多有 10 个 tracked files；这个数量只用于 scope 对账，不作为完成价值；
- WU0 完成判定固定为 12 条。

任何新增白名单外文件、修改保护文件或扩大 WU0 职责的情况，都视为计划变更并停下；少建白名单文件本身不构成失败，但不得缺失完成判定要求的实际产物。

## 5. 建议仓库结构

下列是供 WU1+ 使用的目标职责图。WU0 只在 `docs/architecture.md` 中冻结它，不创建 `src/schemas/fixtures/tests/scripts/examples` 目录。

```text
trip-decider/
├─ PLAN.md                         # 冻结产品定义，只读
├─ plans/                          # PER 工作单元计划
├─ src/trip_decider/
│  ├─ domain/                      # 城市无关实体、枚举、稳定 ID；WU1+
│  ├─ evidence/                    # 正交证据模型、外显映射、依赖传播；WU3+
│  ├─ constraints/                 # 约束规范化、证明规则、环境检查；WU4+
│  ├─ planner/                     # 基地、分天、天内排序、重排目标；WU5-6
│  ├─ adapters/                    # 供应商/来源/地区适用性适配器；WU2-3
│  ├─ pipeline/                    # A—H 文件交接与 run orchestration
│  ├─ rendering/                   # 单文件 HTML 渲染；WU7
│  ├─ schema_validation.py         # WU1 严格契约校验
│  ├─ fixture_validation.py        # WU1 fixture manifest 校验
│  ├─ config.py                    # 首次由实际 adapter 需要时实现
│  └─ cli.py                       # 首次由实际运行入口需要时实现
├─ schemas/                        # 工件 JSON Schema 与 HTML contract
├─ fixtures/                       # 可回放 case；每例自带来源/边界 README
├─ tests/                          # 一个 case 验一个行为，强字段断言
├─ docs/                           # handbook、prior-art、架构、契约、Review
├─ scripts/                        # 可独立复核的 PowerShell 验证入口
└─ examples/                       # 未来脱敏示例，不放真实旅行数据
```

依赖方向：

```text
adapters -> 统一 domain/evidence contract
pipeline -> adapters + constraints + planner + rendering
planner/constraints -> domain + evidence（不得反向依赖 adapters）
rendering -> plan/evidence/violations（不得产生新事实）
```

`planner/constraints/evidence/domain` 禁止出现具体城市名称、城市特例或按城市放宽约束。`adapters` 可以声明适用地区，但不能改变证据定级或求解规则。

## 6. 工件契约草案

### 6.1 通用 envelope、hash 与失败规则

WU0 只把下列内容写入 `docs/artifact-contracts.md`，不创建实际 Schema。WU1 计划将所有 YAML/JSON 工件 Schema 初始版本设为 `0.1.0`，Schema 自身使用 JSON Schema Draft 2020-12。顶层通用字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `schema_version` | 是 | 工件 schema 语义版本；未知 major 版本硬失败 |
| `artifact_id` | 是 | 稳定、全局唯一的工件 ID；不得用文件名冒充 |
| `artifact_type` | 是 | 固定枚举，如 `request`、`plan` |
| `created_at` | 是 | 带 offset 的 RFC 3339 时间；不接受本地无时区时间 |
| `producer` | 是 | `{name, version, run_id}`；用户直接创建时 `name=user` |
| `provenance` | 是 | `{parent_artifact_ids, input_hashes, pipeline_stage}` |
| `integrity` | 是 | `{payload_sha256, canonicalization}`；hash 对象排除自身 `integrity.payload_sha256`，避免自引用 |
| `payload` | 是 | 各工件业务内容 |

共同规则：

- `input_hashes` 记录消费者实际读取的上游文件 bytes SHA256；缺上游或 hash 不符即硬失败；
- `payload_sha256` 对解析后、键排序、UTF-8、无无意义空白的 canonical payload 计算；整个文件 SHA256 由 run/review 外部记录；
- 禁止遇到缺字段时填“合理默认事实”；Schema default 只作说明，不由 validator 自动注入；
- 未知字段默认拒绝（`additionalProperties: false`）；确需扩展必须升 schema；
- Schema 错误退出码固定为非零，并输出工件路径、JSON Pointer、规则和实际类型，不输出 secret；
- YAML 只允许 safe load；禁止自定义对象 tag；
- 模型名/调用信息可以记录在 `producer` 或 parse provenance，但永远不能进入 `sources`；
- WU1 validator 未来只证明结构契约，不证明业务可行、证据真实性或算法正确。

事实、用户输入、模型推断与算法估计的归属：

- 用户原话与显式结构：只在 `request.yaml` 作为 user input；
- LLM/语义解析结果：只在 `constraint-parse.json`，带解析器版本、定位和 `explicit/inferred`；
- 求解权威约束：只在 `constraints.yaml`；
- 外部事实：只在 `evidence.json`，必须回读来源/采集/标准化；
- 算法估计：`evidence.json.derivation` 标 `api_estimate/rule_derived/model_estimate`；
- 算法结果：`plan.json/violations.json/plan-diff.json`，必须回指约束与 evidence fact ID。

### 6.2 `request.yaml`

- Schema：`schemas/request.schema.json`，`schema_version: 0.1.0`。
- 生产者：用户/CLI intake；消费者：约束解析器、管线 B pass-through。
- 权威边界：保存原始请求，不由求解器修改；重解析生成新 artifact，不覆盖旧版本。
- `payload` 必填字段：
  - `request_id`
  - `natural_language`
  - `explicit.origin`
  - `explicit.travel_window.start/end/timezone`
  - `explicit.party.count`
  - `explicit.transport_modes`
  - `explicit.destination.selection_mode`
  - `explicit.preferences_raw`
  - `user_input_refs`
- 可选字段：
  - `explicit.destination.destination_id/name/admin_codes/geometry_hint`
  - `explicit.budget`
  - `explicit.mobility`
  - `explicit.must_visit/excluded`
  - `clarifications`
  - `locale`
- v0：`selection_mode=user_supplied` 且 destination 必填。
- 为 v1 能力 A 冻结：`selection_mode=discovery_required` 时 destination 可空；保留出发地、门到门时间窗、预算、偏好、交通方式和稳定 request ID，不在下游增加 v1 特例。
- Schema 错误：缺原文、时区、目的地模式或用户显式结构类型错时硬失败。

### 6.3 `constraint-parse.json`

- Schema：`schemas/constraint-parse.schema.json`。
- 生产者：版本化语义解析器（可由 LLM 执行语义工作）；消费者：人工确认流程、`constraints.yaml` 生成器。
- 必填字段：
  - `payload.request_id`
  - `payload.request_artifact_id`
  - `payload.request_payload_sha256`
  - `payload.parser.{name,version,kind}`
  - `payload.parsed_constraints[]`
  - `payload.parse_notes`
  - `payload.needs_confirmation`
  - `payload.output_payload_sha256`
- 每个 `parsed_constraints[]` 必填：
  - `parse_item_id`
  - `constraint_id`
  - `user_quote`
  - `user_quote_locator`
  - `classification: explicit|inferred`
  - `layer: hard|soft|environment`
  - `category`
  - `normalized_expression`
  - `default_source`（没有默认则 `null`）
  - `explanation`
  - `needs_confirmation`
- 可选：`confidence_note`（不得伪装成概率）、`model_execution`、`ambiguities`。
- 模型输出不是事实来源；`model_execution` 只说明处理 provenance。
- 任一 inferred 约束没有解释/定位、hash 对不上或 parser 版本缺失时硬失败。

### 6.4 `constraints.yaml`

- Schema：`schemas/constraints.schema.json`。
- 生产者：约束规范化器、用户直接编辑；消费者：环境检查、冲突证明、planner；是求解唯一 SSOT。
- 必填字段：
  - `payload.constraint_set_id`
  - `payload.request_ref`
  - `payload.parse_ref`
  - `payload.revision`
  - `payload.constraints[]`
  - `payload.user_edit_policy`
- 每个约束必填：
  - `constraint_id`（跨重排稳定）
  - `layer: hard|soft|environment`
  - `category`
  - `operator`
  - `target_refs`
  - `value`
  - `unit`（不适用时显式 `null`）
  - `origin.kind: explicit|inferred|default|user_edited`
  - `origin.refs[]`
  - `enabled`
- `origin.refs[]` 按 kind 使用判别联合：
  - `explicit`：必须引用 parse item ID 和用户原话 locator；
  - `inferred`：必须引用 parse item ID、解析解释和 `needs_confirmation`；
  - `default`：必须引用版本化默认规则 ID 与版本；
  - `user_edited`：必须引用编辑事件；由原约束修改时还要保留 `supersedes_constraint_id` 和原始 parse refs。
- 软偏好额外字段：`weight`、`direction`；硬约束不得被 weight 降级。
- 可选：`valid_for_days`、`notes`。
- 用户修改后提升 `revision`；重解析只能产 proposal，不能自动覆盖。
- 缺稳定 ID、非法 layer、任一 origin 缺对应 refs、单位不匹配时硬失败。

### 6.5 `candidates.json`

- Schema：`schemas/candidates.schema.json`。
- 生产者：管线 B/C、未来基地候选生成器；消费者：证据采集、约束检查、planner。
- 必填字段：
  - `payload.candidate_set_id`
  - `payload.request_ref`
  - `payload.generation_stage`
  - `payload.candidates[]`
  - `payload.rejected_inputs[]`
- 每个候选必填：
  - `candidate_id`
  - `candidate_type: destination|poi|base_area`
  - `name`
  - `parent_candidate_id`（顶层 destination 为 `null`）
  - `source_refs`
  - `generation_reason`
  - `status: active|rejected|unresolved`
  - `location` 或 `location_unresolved` 二选一
- 初始 C 阶段不要求 evidence：`evidence_fact_refs` 可为空或省略，不能因 D 阶段尚未产出而硬失败。
- 按 `generation_stage` 的条件化规则：
  - `poi_discovery`：稳定 candidate ID、名称、位置或待解析位置、`source_refs` 必填；evidence refs 可空；
  - `destination_pass_through`：必须回指用户给定目的地和 `request.yaml` 的用户输入 locator；
  - `destination_recommendation`：仅 v1 中真正标记为推荐给用户的 destination，才强制 `rough_feasibility_ref` 与 `coarse_plan_ref`。
- 可选：`provider_ids`、`categories`、`evidence_fact_refs`、`rough_feasibility_ref`、`coarse_plan_ref`、`applicable_area`。
- 阶段不可变：D 阶段生成独立 `evidence.json`，不得反向修改旧 `candidates.json` 补 evidence refs；后续 plan/evaluation 同时引用 candidate ID 和 evidence fact ID。
- v1 能力 A 冻结：destination 与 POI 共用稳定候选 envelope；只有进入用户推荐结果的 destination 才要求门到门粗可行性和至少一份粗计划；WU0 不实现候选生成或“神秘匹配分”。
- 候选无稳定 ID、位置/待解析位置或来源引用，或 v0 destination pass-through 缺用户请求引用时硬失败。

### 6.6 `evidence.json`

- Schema：`schemas/evidence.schema.json`。
- 生产者：adapters、标准化器、证据映射器；消费者：约束检查、planner、rendering。
- 必填字段：
  - `payload.evidence_set_id`
  - `payload.facts[]`
  - `payload.mapping_rule_version`
- 每个 fact 必填：
  - `fact_id`
  - `subject_ref`
  - `field_path`
  - `value`
  - `unit`
  - `support_status: verified|sourced|conflicting|unknown`
  - `derivation: direct_observation|official_report|api_estimate|rule_derived|model_estimate|user_supplied`
  - `freshness.{retrieved_at,effective_at,expires_at,status}`
  - `sources[]`
  - `normalization.{raw_value,normalized_value,rule_id}`
  - `display_status`
  - `display_status_rule_id`
  - `conflict_source_refs`
- `sources[]` 使用 `source_type` 判别联合，不要求所有来源伪造网页字段：
  - `webpage|official_notice`：`source_id/url/publisher/retrieved_at/excerpt/locator` 必填；`title` 按页面是否提供记录；`published_at` 必须显式为时间或 `null`，为 null 时附 `published_at_absence_reason`，不得推断日期；
  - `api_response`：`source_id/provider/operation/retrieved_at/request_fingerprint/response_locator` 必填；不得强制 `published_at/excerpt/title`，不得保存含 key 的完整 URL；
  - `direct_observation`：`source_id/observer_type/observed_at/observation/location_ref` 必填；不得伪造 URL、publisher 或网页 title。
- `user_supplied`：用户内容通过 `user_input_refs` 或 provenance 回读，`derivation=user_supplied`；不为满足 source schema 伪造外部 source。没有外部证据时不得标 verified。
- `derived`：规则派生值以 `derivation_detail.{rule_id,input_fact_ids}` 回读，不用 LLM、函数名或代码模块名冒充事实来源。
- 所有 source 变体必须可追溯、不含 secret、按 `source_type` 结构校验，缺失不适用字段时不填虚假占位。
- API 路径时间：`derivation=api_estimate`；住宿 POI 密度：`derivation=rule_derived`。当估算影响硬约束时还必须有：
  - `estimate.method`
  - `estimate.value`
  - `estimate.uncertainty_or_buffer`
  - `estimate.conservative_bound`
- 外部五态确定性映射草案（WU3 必须测试）：
  1. 存在同等级未解决冲突或 `support_status=conflicting` → `conflicting`；
  2. 值缺失、关键来源缺失或 `support_status=unknown` → `unknown`；
  3. `derivation` 为 `api_estimate/rule_derived/model_estimate` → `estimated`；
  4. `support_status=verified` 且 freshness=`current`、权威来源可回读、无同等级冲突、derivation 允许直接/官方观测 → `verified`；
  5. 其他有可回读来源的情况，包括 stale/unknown freshness 导致的降级 → `sourced`；
  6. 仅 `user_supplied` 且没有外部证据的现实事实，保守显示 `unknown` 并另显“用户提供”；用户偏好/选择属于约束，不套事实状态。
- 任一存储的 `display_status` 不等于映射函数重算结果即硬失败。
- `display_status=estimated` 不自动决定 `plan_status`；计划状态还要读取 constraint evaluation 中的保守边界判定。

### 6.7 `previous-plan.json`

- Schema：`schemas/previous-plan.schema.json`。
- 生产者：重排入口对旧 `plan.json` 的不可变快照；消费者：WU6 重排目标与 diff。
- 必填字段：
  - `payload.previous_plan_id`
  - `payload.previous_plan_artifact_id`
  - `payload.previous_plan_payload_sha256`
  - `payload.baseline_constraint_set_id`
  - `payload.snapshot`
  - `payload.snapshot_created_at`
- 可选：`payload.user_locked_entities`、`payload.baseline_notes`。
- `snapshot` 至少保存基地、日期、活动、时段、相对顺序和删除状态；不能只存指向可变文件的路径。
- replan 模式缺旧计划、hash 不符或 snapshot 不完整时硬失败，不退化成全新规划并伪称“最小改变”。

### 6.8 `plan.json`

- Schema：`schemas/plan.schema.json`。
- 生产者：planner；消费者：rendering、重排 snapshot、plan diff、验收记录。
- 必填字段：
  - `payload.plan_id`
  - `payload.request_ref`
  - `payload.constraint_set_ref`
  - `payload.candidate_set_ref`
  - `payload.evidence_set_ref`
  - `payload.plan_status`
  - `payload.conditions[]`
  - `payload.base_selections[]`
  - `payload.days[]`
  - `payload.excluded_candidates[]`
  - `payload.constraint_evaluations[]`
  - `payload.objective_breakdown`
- 每个 day/activity/leg 使用稳定 ID；活动含候选引用、start/end/duration、evidence refs；交通段含 mode、from/to、duration、derivation fact ref、buffer。
- `excluded_candidates[]` 必须有 reason、constraint refs、evidence refs；不得只写“未推荐”。
- 可选：`previous_plan_ref`、`solver_trace_summary`、`display_notes`。
- `plan_status` 与 `violations.json` 必须一致；硬约束依赖 unresolved unknown/conflicting 时不得写 feasible。关键 estimated 若没有不确定性处理、或保守区间可能跨越硬边界，也不得写 feasible；若保守边界下仍满足硬约束，可以 feasible，但相应事实仍显示 estimated。

### 6.9 `plan-diff.json`

- Schema：`schemas/plan-diff.schema.json`。
- 生产者：WU6 diff 引擎；消费者：rendering、Review、用户解释。
- 必填字段：
  - `payload.previous_plan_id`
  - `payload.new_plan_id`
  - `payload.change_score`
  - `payload.weights`
  - `payload.changes[]`
  - `payload.unchanged_summary`
- 每个 change 必填：
  - `type`
  - `entity_id`
  - `from`
  - `to`
  - `cost`
  - `reason`
  - `constraint_refs`
- 默认代价冻结为配置初值：保持活动/日期/相对顺序 0；同日换序 1；同日换时段 2；换天 3；换基地 5；删除 6；新增活动的代价必须在 config 中显式定义，不能临时猜。
- `change_score` 必须等于逐项成本的确定性合计；不等即硬失败。

### 6.10 `violations.json`

- Schema：`schemas/violations.schema.json`。
- 生产者：约束检查器、planner；消费者：rendering、Review、重排解释。
- 必填字段：
  - `payload.plan_id`
  - `payload.plan_status`
  - `payload.violations[]`
  - `payload.conditions[]`
  - `payload.candidate_conflict_sets[]`
  - `payload.proofs[]`
- 每个 violation 必填：
  - `violation_id`
  - `kind`
  - `severity`
  - `constraint_refs`
  - `evidence_fact_refs`
  - `proof_status: proven|candidate|uncertain`
  - `reason`
  - `user_message`
- 真正最小化验证完成前不得出现字段名或文案 `minimal_conflict_set`；只用 `candidate_conflict_set`。
- `proven_infeasible` 必须至少有一条可回放 proof rule 和输入下界；否则硬失败。

### 6.11 `trip-card.html`

- Contract：`schemas/trip-card.contract.md`；不是 JSON Schema，不在 WU0 生成实际卡片。
- 生产者：WU7 renderer；消费者：浏览器、用户、同行者、验收记录。
- 必填机器可读元数据：
  - `<meta name="trip-decider-schema-version">`
  - `<meta name="trip-decider-plan-id">`
  - `<meta name="trip-decider-plan-payload-sha256">`
  - `<script type="application/json" id="trip-decider-manifest">`
- manifest 必填：artifact ID、producer/run、plan/evidence/violations refs 和 hashes、generated_at。
- 必填用户区块：总体状态、条件与风险、住宿基地理由、分天时间轴、交通与缓冲、证据标签、淘汰名单及理由、变更摘要（重排时）。
- HTML 只能渲染上游事实和决策，不得补写新开放时间、交通时间或“推荐理由事实”。
- 缺引用、hash、关键区块或出现未转义内容时构建硬失败。

### 6.12 v1 能力 A 提前冻结的最小字段

只冻结接口，不实现目的地发现：

- `request.destination.selection_mode` 允许 `user_supplied|discovery_required`；
- destination 使用与 POI 一致的稳定 `candidate_id`、位置/待解析位置和 `source_refs`；初始候选不强制 evidence refs；
- `candidates.json` 支持 `candidate_type=destination`、`rough_feasibility_ref`、`coarse_plan_ref`；后两者只对 v1 真正输出给用户的推荐 destination 必填；
- 所有约束按稳定 target ref 绑定，不能把城市名作为主键；
- `plan.json` 始终引用 destination candidate ID；
- v1 粗计划必须作为独立工件引用，不把能力 A 的内部评分字段泄漏给 C—H；
- WU0 不定义完整 DSL、不定义目的地神秘匹配分、不实现可达圈。

## 7. 可行性状态和冲突模型

### 7.1 状态切换

| 条件 | 状态 | 允许的用户文案 |
|---|---|---|
| 找到满足全部硬约束与环境要求的结构；关键依赖无 unresolved `unknown/conflicting`；所有关键估算在可回读保守边界下仍满足硬约束 | `feasible` | “已找到满足当前硬约束的方案；其中估算事实及缓冲如下。” |
| 找到结构方案，但硬约束依赖 unresolved `unknown/conflicting`，或关键估算无不确定性处理/可能跨越硬边界 | `conditionally_feasible` | “已找到结构方案，但需满足/核验以下条件。” |
| 确定性规则或完备检查给出可回放证明 | `proven_infeasible` | “已证明当前这组约束不可同时满足，依据如下。” |
| 有界启发式搜索未找到方案，且没有证明 | `no_plan_found` | “当前算法未找到满足条件的方案，尚不能证明无解。” |

状态优先级不是简单严重度覆盖：

1. 先运行可证明矛盾检查；成功才可进入 `proven_infeasible`；
2. 无证明时运行启发式；
3. 找到结构后，先传播 unknown/conflicting，再检验 estimate 的不确定性/缓冲/保守边界，决定 feasible/conditional；
4. 没找到且无证明只能 `no_plan_found`；
5. 新 evidence 只能通过重跑改变状态，不能在渲染层提升状态。

### 7.2 v0 可证明冲突

- 同一稳定 POI ID 同时位于 enabled `must_visit` 与 `excluded`；
- 必去活动最短时长下界之和大于总可用时间；
- 最早可达下界晚于有明确有效来源的闭馆时间；
- 某日交通时间下界 + 活动时间下界大于该日时间窗；
- “不换酒店”与明确基地—必去点通勤上限之间存在可穷举证明；
- 互斥时间窗对同一人/活动产生确定性重叠。

证明必须记录规则 ID、约束 ID、输入事实 ID、原始/标准化值、单位和计算过程。含 unknown/conflicting 的输入不能用于 `proven_infeasible`。

### 7.3 `violations.json` 表示

- `proof_status=proven`：只用于上述确定性证明；
- `proof_status=candidate`：算法识别出的疑似冲突；
- `proof_status=uncertain`：依赖 unknown/conflicting/estimated；
- `candidate_conflict_sets[]` 带成员约束、识别算法、是否尝试最小化、限制说明；
- 只有真正逐项移除并验证“任一真子集不再冲突”后，未来版本才可另加最小冲突语义；WU0/WU4 默认不声明。

### 7.4 证据传播

- 约束 evaluation 必须列 `dependency_fact_refs`；
- 任一硬判断依赖 unresolved `conflicting` → 不能 feasible，输出冲突来源；
- 任一硬判断依赖 unresolved `unknown` → 不能 feasible，输出待补事实；
- 任一硬判断依赖 `estimated` → 必须输出估计方法、不确定性/缓冲和保守边界；边界下仍满足硬约束可 feasible，可能跨界或未处理不确定性则 conditional；
- 软偏好可使用 estimated 排序，但必须保留标签，不能提升成硬否决；
- 渲染只消费 evaluation 结果，不自行猜测传播；同时展示 plan status 与 fact display status，二者不得互相覆盖。

示例：地图方法给出 60 分钟，规则加入 40 分钟缓冲，`conservative_bound=100 分钟`；若按 100 分钟仍能在闭馆前 60 分钟到达，结构状态可以 feasible，但交通事实继续显示 estimated。

## 8. Fixture 策略

WU0 只在本计划和 `docs/artifact-contracts.md` 冻结以下六项 fixture specification，不创建目录、fixture、Schema 或测试。它们规划为“合成确定性契约 fixture”，来源是冻结 `PLAN.md` + v3.1 规范，expected 由人工按 spec 写定；不声称是真实旅行、真实检索或真实地理事实。WU1 才创建 Schema、结构 fixture 与测试骨架；WU3—WU6 在各自业务实现前把对应行为 fixture 置红。任何江西真实 fixture 只在 WU8 用用户真实请求与一手/API 数据建立。

### 8.1 `fixture_01_feasible`

- 类型：合成确定性 fixture。
- 来源：四态状态定义与约束模型；使用虚构稳定 ID，不使用真实城市/POI。
- 输入工件：最小 `request/constraints/candidates/evidence` 片段；无 unknown/conflicting；交通时间为 estimated，但具备可回读方法、40 分钟缓冲和在保守上界下仍满足硬约束的证明。
- 预期输出：`plan_status=feasible`，无 hard violation。
- 具体断言：
  1. 必去 activity ID 出现在计划且只出现一次；
  2. activity 时间落在约束窗内；
  3. `violations` 为空且 `conditions` 为空；
  4. 每个活动/交通段含 constraint/evidence refs；
  5. plan status 为 feasible，同时交通事实仍显示 estimated；
  6. 状态文案展示估算与缓冲，不含“条件不足”或“无解”。
- 不覆盖：候选检索、真实路线、全局最优。
- fail 时机：WU1 先完成可加载的结构契约；WU5 在 planner 实现前以具体状态/时间窗/引用断言失败或明确 `NotImplementedError` 置红。
- 所属实现 WU：WU5。

### 8.2 `fixture_02_direct_conflict`

- 类型：合成确定性 fixture。
- 来源：v3.1 明列可证明矛盾。
- 输入：同一 `candidate_id` 同时进入 enabled must_visit 与 excluded。
- 预期：`proven_infeasible`，proof rule 精确回指两个约束 ID。
- 具体断言：
  1. 状态恰为 `proven_infeasible`；
  2. proof rule ID 固定；
  3. constraint refs 集合等于这两个 ID；
  4. 不生成 plan days；
  5. 不使用 `candidate_conflict_set` 冒充 proof。
- 不覆盖：语义同义词识别、最小化算法。
- fail 时机：WU4 在冲突规则实现前以具体 proof/status 断言失败或明确 `NotImplementedError` 置红。
- 所属 WU：WU4。

### 8.3 `fixture_03_uncertain_dependency`

- 类型：合成确定性 fixture。
- 来源：证据 invariant 与 unknown/conflicting 传播规则。
- 输入：结构可排，但交通为 `api_estimate`、开放状态为 `unknown`。
- 预期：`conditionally_feasible`，列出两个条件，绝不写 feasible。
- 具体断言：
  1. plan status 恰为 conditional；
  2. 条件分别回指交通 fact 和开放 fact；
  3. 交通外显为 estimated；
  4. 开放状态外显为 unknown；
  5. 用户文案包含核验条件但不含“已确认可行”。
- 不覆盖：真实 API 准确率、网页时效。
- fail 时机：WU3/WU4 在传播实现前以具体 status/dependency refs 断言失败或明确 `NotImplementedError` 置红。
- 所属 WU：WU3、WU4。

### 8.4 `fixture_04_replan_stability`

- 类型：合成确定性 fixture。
- 来源：v3.1 旧计划基准和变更代价。
- 输入：`previous-plan` 中两个活动同日有序；新约束只要求其中一个改时段。
- 预期：未受影响活动/日期/相对顺序保留；单项成本按权重计算。
- 具体断言：
  1. previous/new plan ID 均正确；
  2. 只出现预期 change entity；
  3. change type 与成本匹配；
  4. `change_score=sum(cost)`；
  5. reason 回指触发约束 ID；
  6. unchanged summary 精确列保留项。
- 不覆盖：全局最优权重、用户对权重的主观偏好。
- fail 时机：WU6 在 diff/目标函数实现前以具体 change/cost/constraint refs 断言失败或明确 `NotImplementedError` 置红。
- 所属 WU：WU6。

### 8.5 `fixture_05_evidence_state_mapping`

- 类型：合成确定性 truth table。
- 来源：v3.1 正交证据字段与本计划 §6.6 映射。
- 输入：verified/current/official、stale、api estimate、rule derived、conflict、unknown、user supplied 无外证等独立行。
- 预期：每行一个固定外显五态。
- 具体断言：
  1. verified 仅在所有高等级条件满足时出现；
  2. stale verified 降为 sourced；
  3. api/rule estimate 显为 estimated；
  4. conflict 优先于 estimate；
  5. unknown 不被默认值提升；
  6. LLM 不在 sources；
  7. user supplied 无外证不显示 verified。
- 不覆盖：来源权威性自动判定、真实网页抽取。
- fail 时机：WU3 在映射函数实现前以 truth-table 的精确状态断言失败或明确 `NotImplementedError` 置红。
- 所属 WU：WU3。

### 8.6 `fixture_06_no_plan_found_not_infeasible`

- 类型：合成确定性控制流 fixture。
- 来源：v3.1 启发式边界。
- 输入：有界启发式在指定搜索预算内返回空，但不存在任何 direct proof。
- 预期：`no_plan_found`，仅给 candidate conflict，不出现“无解/不可能”。
- 具体断言：
  1. 状态恰为 `no_plan_found`；
  2. proofs 为空；
  3. candidate conflict 标 `candidate`；
  4. 用户文案明确“尚不能证明无解”；
  5. 文案不含四个禁用过度声明。
- 不覆盖：完备求解器、真正无解证明。
- fail 时机：WU4/WU5 在状态控制实现前以具体 status/proof/message 断言失败或明确 `NotImplementedError` 置红。
- 所属 WU：WU4、WU5。

### 8.7 fail→pass 留痕

- WU0 没有 red→green，也不得宣称 fixture-first 已落地。
- WU1 创建 Schema、结构 fixture、可导入接口与测试骨架后，合格 red 只能来自：
  - 针对已加载输入的具体行为/字段断言失败；或
  - 已存在、可导入接口明确抛出 `NotImplementedError`。
- 下列一律不是合格 red：模块不存在、import 失败、路径错误、依赖未安装、malformed JSON/YAML、测试发现器未找到 case、fixture 自身不符合格式。
- WU1 的结构校验转绿只证明 Schema/fixture/validator 契约，不证明 WU3—WU6 的 evidence、约束、planner 或重排能力。
- WU3—WU6 分别在业务实现前运行对应行为 fixture，保存命令、commit、exit code、精确失败断言；实现后用同一输入和断言转绿。

### 8.8 WU1 实施清单（仅冻结范围）

WU1 的新 Plan 至少覆盖：

- 十项工件的实际 JSON Schema/HTML contract，以及共享 envelope/source/origin 判别联合；
- 稳定 artifact/candidate/constraint/fact/activity ID 的领域类型；
- 六项 fixture 的目录、README、输入与人工 expected；结构 fixture 与未来行为 fixture 分层；
- Schema/fixture strict validator：缺字段、类型错、非法 union、hash/provenance 断裂硬失败，不注入默认事实；
- 可导入的最小接口占位，使初始 red 来自具体断言或 `NotImplementedError`，不是 import/路径/依赖失败；
- clean/dirty 配对、强字段断言、来源/覆盖/不覆盖声明；
- YAML/Schema/测试依赖的选型、license、Windows 实测和锁定；
- 明确禁止在 WU1 实现 evidence 映射、约束证明、planner、重排或 HTML 渲染。

## 9. D0 prior-art 研究计划

### 9.1 时间盒

硬上限 240 分钟，超时即停：

- 20 分钟：用正式引用链消歧三项对象并登记候选一手来源；
- 65 分钟：ChinaTravel；
- 65 分钟：Hao et al.；
- 65 分钟：ItiNera；
- 25 分钟：交叉对照、license/可下载性核对和落盘。

不得因“差一点”延长。未完成项明确 blocking/unknown，不凭记忆补。

### 9.2 允许来源

- 正式论文 PDF/出版社页；
- ACL Anthology、OpenReview、正式会议官方 proceedings；
- 作者、实验室或项目官方仓库；
- 官方数据集页面；
- 官方竞赛文档。

禁止把博客、媒体、搜索摘要、二手综述、AI 回答当结论来源。搜索结果只能用于定位，结论必须打开原文并记录 locator。

### 9.3 固定核对矩阵

ChinaTravel：

- 六类约束分类原文和定义；
- DSL 的实际结构、输入/输出、是否适合只复用概念；
- 数据集、代码、下载入口是否真实可用；
- license 是否明确、是否允许本地研究/衍生 fixture；
- 哪些是在封闭数据/固定候选池沙盒中成立。

Hao et al.：

- 先用正式引用链确认“本项目所指 Hao”是哪篇，不按姓名猜；
- 正式发表版任务、数据、指标、baseline、成绩表 locator；
- `97%` 与 `93.9%` 分别来自哪个版本、split、指标或报告口径；
- 是否真正实现 unsat core、最小冲突、约束放松，还是只生成解释/建议；
- 代码/数据/license 可获得性。

ItiNera：

- 零起点候选池如何建立；
- POI selection 与空间优化是否分阶段；
- 路线/时间/偏好目标和约束如何表达；
- 候选池与优化器的输入契约；
- 代码、数据、license；
- 哪些结论依赖封闭 POI 数据、离线 benchmark 或已知候选，不适用于真实 Web 时效环境。

### 9.4 产出

`docs/prior-art.md` 固定七节：

1. 现有方法已解决
2. 可直接复用
3. 真实旅行仍未解决
4. 对 trip-decider 的具体影响
5. 不应重复实现的内容
6. 本项目仍需验证的假设
7. 一手来源清单

每条结论带一手来源 URL、版本/发表信息、页码/章节/表格 locator、retrieved_at。下载/代码/license 的“可用”必须实际打开入口；404、权限、未声明 license 都按事实写，不推断。

### 9.5 网络阻塞规则

当前只验证 GitHub HTTPS 可用，尚未验证论文站点。若 Execute 时一手来源无法访问：

- `docs/prior-art.md` 对该对象标 `BLOCKED`，列实际 URL、命令/访问结果与未核实问题；
- 可以完成 handbook、契约、fixture 和校验部分；
- completion #5 只在“三项均有结论或明确 blocking”时满足；
- 若 license 或正式成绩无法核实，不写“可复用/已确认”；
- 不使用搜索摘要替代原文。

## 10. 依赖策略

WU0 是仓库、研究和文档契约工作单元，不创建 `.venv`、不调用 pip、不开依赖解析、不生成 lock。只使用当前已有的 Git、PowerShell 和只读网络访问。下表是 WU1+ 的评估输入，不是 WU0 安装授权；具体包、版本和 license 必须在对应工作单元 Plan 重新批准。

| 能力 | WU0 决策 | 后续候选/标准库替代 | 许可与 Windows 待核 | 后续引入时机 |
|---|---|---|---|---:|---|
| YAML | 不安装 | WU1 评估 PyYAML；标准库无 YAML | 选定版本 license、Python 3.11/Windows 支持须实测 | WU1 Schema/validator |
| JSON Schema / Pydantic | 不安装、不选型落地 | WU1 优先比较 `jsonschema` 与 Pydantic，避免重复模型 | 选定版本官方 metadata/LICENSE 须核 | WU1 |
| HTTP 客户端 | 不安装 | WU2 比较 stdlib `urllib` 与 `httpx` | 高德条款和包 license 一并核 | WU2 |
| HTML 模板 | 不安装 | WU7 比较标准库与 Jinja2 | 选定版本再核 | WU7 |
| 测试框架 | 不创建测试 | WU1 比较标准库 `unittest` 与最小第三方方案 | Windows 实跑决定 | WU1 |
| 时间计算 | 只写契约 | `datetime/zoneinfo`；Windows IANA 数据可能需 `tzdata` | 不提前声明支持 | WU1/WU4 |
| 地理计算 | 只写边界 | WU5 首选 `math` 明确公式；真实路时来自 adapter | 不因未来可能需要引库 | WU5 |
| CLI | 不实现 | 后续优先标准库 `argparse` | 无第三方依赖优先 | WU1 或实际首次需要时 |
| 配置 | 不实现 | 后续优先 `os.environ` | 不自动修改用户环境 | WU2 |

WU0 Review 必须确认：无 `.venv`、无新增依赖文件、无 pip install 记录、无文档把“契约已冻结”写成“Schema/validator 已实现”。

## 11. Secrets 策略

### 11.1 文件与变量

- 高德环境变量唯一规范名：`TRIP_DECIDER_AMAP_API_KEY`；
- WU0 只让 `.gitignore` 忽略 `.env`、`.env.*`、`.venv/`、cache、logs、runtime、真实/private fixtures、raw API payload；
- WU0 不创建 `.env.example`、不实现配置加载、不修改系统/用户环境；
- `.env.example` 与实际配置加载回到首次需要真实 adapter 的 WU2，届时空值模板不得放示例假 key；
- README 只声明“WU0 不需要 key”，不提供会回显 key 的命令。

### 11.2 日志与错误

- 日志只允许输出 `amap_key_configured=true|false`，不输出全值、前后缀、长度或 hash；
- 异常不得包含请求 URL query、header、环境变量内容；
- 未来 HTTP adapter 统一在请求前脱敏；录制 fixture 删除 key、Authorization、cookie、个人标识；
- secrets 扫描既检查 tracked 文件，也检查 Git diff/历史。

### 11.3 缺 key 行为

- WU2 真实 API 命令缺 key时硬失败，绝不拿假 key 请求后返回空列表；
- 集成测试无 key时必须明确标记 skip，或使用已脱敏录制 fixture；单元/CI 不依赖真实 key；
- WU0 没有 config/CLI/integration test，不创建 adapter、不调用高德，当前缺 key不是 WU0 blocking。

## 12. WU0 Commit 序列

执行保持在 `main` 线性历史，共 C0—C4。WU0 不创建 `test` 或 `feat` commit。

### C0 — baseline

- Commit message：`chore: establish WU0 repository baseline`
- 修改文件：原字节跟踪 `PLAN.md` 和获批的本计划。
- 单一职责：初始化 Git、建立 `main`，把产品 Source of Truth 与批准范围固化为首个可审计基线。
- 前置条件：收到 Hugin 对 v0.2 的执行授权；确认当前仍非 Git 仓库，且只有这两个文件。
- 验证命令：
  - `git branch --show-current`
  - `Get-FileHash .\PLAN.md -Algorithm SHA256`
  - `Get-FileHash .\plans\work-unit-0-bootstrap-d0.md -Algorithm SHA256`
  - `git show --root --stat --oneline HEAD`
  - `git status --short`
- 完成判定：main 上首个 commit 只含两个原字节文件，hash 与批准时一致。
- 取代空 commit 的实际价值：C0 本身就是有意义的根基线；Review 用 `git show --root C0` 审 C0，用 `git diff C0..HEAD` 审后续工作，无需为制造比较点增加空历史。

### C1 — bootstrap

- Commit message：`chore: bootstrap minimal trip-decider repository`
- 修改文件：`.gitignore`、`.gitattributes`、`README.md`。
- 单一职责：最小仓库元文件、保护规则和诚实的项目状态说明。
- 前置条件：C0。
- 验证命令：
  - `Get-FileHash .\PLAN.md -Algorithm SHA256`
  - 检查 `.gitignore` 覆盖 secret、环境、cache、真实/private fixture；
  - 检查 README 明确 WU0 仅文档契约、无业务实现；
  - `git status --short`
  - secret assignment 扫描。
- 完成判定：该 commit 只新增 3 个元文件；无依赖、Python 包或空业务目录。

### C2 — handbook 与 D0 docs

- Commit message：`docs: record handbook context and D0 prior art`
- 修改文件：`docs/handbook-context.md`、`docs/prior-art.md`。
- 单一职责：可追溯上下文和半天 prior-art 结论。
- 前置条件：C1；再次记录 handbook HEAD/status；D0 240 分钟计时开始。
- 验证命令：
  - handbook `rev-parse HEAD/origin/main`、ahead/behind、status；
  - 一手来源 URL/locator/license 字段完整性检查；
  - 二手来源域名/无 locator 扫描；
  - `Get-FileHash .\PLAN.md`。
- 完成判定：handbook-context 只摘要不复制规则；三项对象均有结论或明确 blocking；未超时。

### C3 — contracts

- Commit message：`docs: freeze initial architecture and artifact contracts`
- 修改文件：`docs/architecture.md`、`docs/artifact-contracts.md`。
- 单一职责：目录职责、十项文档级工件契约、fixture specification、v1 能力 A 接口和 v3.1 语义冻结。
- 前置条件：C2；不需要真实 API/key。
- 验证命令：
  - 十项 artifact 名称、生产者、消费者和阶段关系逐项核对；
  - candidate/evidence 阶段不可变与条件字段 grep；
  - estimated 保守边界、source_type 多态、constraint origin refs grep；
  - WU1 Schema/fixture/validator 实施清单核对；
  - 城市名不得出现在规划核心规则示例。
- 完成判定：2 个文档完整吸收四项契约修正和 WU1 实施边界；没有实际 Schema、fixture 或代码。

### C4 — review prep

- Commit message：`docs: prepare WU0 review evidence`
- 修改文件：`docs/reviews/work-unit-0-review.md`。
- 单一职责：汇总可独立复核的 Git、hash、scope、来源和 12 条完成判定证据；状态只写 `READY_FOR_HUGIN_REVIEW/BLOCKED/INCOMPLETE`。
- 前置条件：C3 所有计划内验证完成。
- 验证命令：
  - `git status --short`
  - `git log --oneline --decorate --reverse`
  - `git show --root --stat --oneline <C0>`
  - `git diff --stat <C0>..HEAD`
  - `git diff <C0>..HEAD`
  - tracked/untracked 文件清单和白名单对账；
  - `.venv/src/schemas/fixtures/tests/scripts/examples` 不存在性检查；
  - `PLAN.md` 与 handbook HEAD/status 前后对账；
  - prior-art 一手来源与 secret 扫描。
- 完成判定：Review 材料数字都能回到命令输出；不声明 Hugin 已验收；不开始 WU1。

## 13. 完成判定

WU0 只按以下 12 条对照；它们代表 WU0 的实际价值，不以创建满白名单或文件数量制造完成感。

1. handbook 已实际执行远端 fetch，并留痕本地 HEAD、`origin/main` HEAD、ahead/behind 和 fetch exit code；
2. 8 个强制注入文件与本计划列出的相关项目记忆均从 `origin/main` 实际读取，`docs/handbook-context.md` 可追溯；
3. `PLAN.md` 基线与 Review SHA256 一致，未修改、未改名；
4. ChinaTravel、Hao et al.、ItiNera 三项均有一手来源结论或有访问证据的明确 blocking；
5. `docs/prior-art.md` 没有使用二手来源、搜索摘要或 AI 记忆冒充已核实原文；
6. 目录职责、依赖方向、adapter 边界和城市无关规划核心已在文档中冻结；
7. 十项工件在文档层完成生产者、消费者、阶段顺序、不可变关系、字段类别、hash/provenance 与硬失败边界定义；
8. candidate/evidence 循环、estimated 计划状态、Evidence Source 多态、constraint origin refs 四项修正已落入文档；
9. WU1 的实际 Schema、领域模型、六项 fixture、有效 red、测试骨架、strict validator 和依赖选型范围清楚；
10. WU0 未安装依赖、未创建 `.venv`、lock、Schema、fixture、测试、CLI、config 或业务代码；
11. WU0 未调用高德，也未用假 key、示例输出或搜索摘要制造完成证据；
12. handbook 未修改，未 push、未开始 WU1；Review 能从 C0 根 commit、后续 diff、hash 与来源记录独立复核。

## 14. 风险与延后事项

### 14.1 blocking

当前 Plan 阶段没有已发生的 blocking。

Execute 中下列情况转为 blocking 并停下：

- ChinaTravel/Hao/ItiNera 身份无法从正式引用链消歧；
- 正式论文、代码/数据入口或 license 无法访问，且继续会迫使凭记忆下结论；
- 需要新增 §4.2 白名单外文件、修改本计划/`PLAN.md`/handbook 或引入任何依赖；
- 文档级 fixture specification 继续设计需要真实地理/语义 anchor，而用户/一手数据尚未提供；
- secrets 可能进入 tracked 文件或历史。

### 14.2 non-blocking

- 当前不是 Git 仓库：C0/C1 已规划；
- 当前没有高德 key：WU0 不调用高德，WU2 前再处理；
- uv/Poetry 不可用：WU0 不安装依赖，不受影响；
- 只验证 GitHub 网络，论文站点未知：D0 按访问事实处理；
- 时间线紧：不以扩 WU0 换“完成感”，严格 240 分钟 D0 和 12 条验收；
- `PLAN.md` 大小写与提示词不同：按实际文件保护，不重命名。

### 14.3 deferred-to-WU1+

- WU1：实际 JSON Schema、领域模型、稳定 ID、六项结构 fixture、有效 red 的测试骨架、strict schema/fixture validator、依赖选型与锁定；结构绿不得冒充业务绿；
- WU2：`.env.example`、config/CLI 的首次真实需要、高德 key、条款/配额核验、POI/路径 adapter、脱敏录制 fixture；
- WU3：证据采集、权威性规则、五态映射实现和依赖传播；
- WU4：约束解析、环境检查、proof rules、四态可行性；
- WU5：基地选择、贪心分天、天内局部优化；
- WU6：previous-plan、配置化变更代价、plan diff；
- WU7：单文件 HTML 行程卡；
- WU8：用户真实江西请求、真实 anchor、旅行前验收与实旅记录。

### 14.4 deferred-to-v1

- 能力 A 的可达圈、目的地候选生成、目的地级粗可行性；
- 答案未知的真实目的地发现 fixture；
- 2—3 个差异化目的地方案；
- 消费级交互、小程序及其主体/备案评估。

### 14.5 handbook-candidate

只有 WU8 真实验证后才考虑回写候选，不在本项目自动修改 handbook：

- “证据支持 × 产生方式 × 时效 × 冲突”正交模型在真实旅行中的有效性；
- `no_plan_found` 与 `proven_infeasible` 的用户理解差异；
- previous-plan 确定性变更代价是否真的减少用户重排负担；
- 真实 Web 时效环境下 replay fixture 与 live anchor 的双层评估方法；
- 旅行规划中“规范/官方事实、API 估计、用户提供事实”的责任边界。

## 审批门

本文件修订并完成只读复核后停止。只有 Hugin 对 Plan v0.2 给出语义明确的执行授权，才允许执行 C0—C4。授权前不初始化 Git、不安装依赖、不创建本计划以外文件、不 commit。
