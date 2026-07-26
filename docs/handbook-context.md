# Handbook context for trip-decider WU0

本文只记录本工作单元实际注入的 handbook 上下文及其工程影响，不复制规则原文。

## 版本与读取基线

- 固定路径：`<handbook>`
- 检查时间：`2026-07-26T14:24:02.4937048+08:00`
- `git fetch origin --prune` exit code：`0`
- 本地 `HEAD`：`6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`
- `origin/main`：`6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`
- `HEAD...origin/main` ahead/behind：`0/0`
- handbook 工作树：clean（`git status --short` 为 `0` 行）
- 读取方式：只用 `git show origin/main:<path>`；未从本地工作树注入规则
- 实际读取：`24` 个路径，失败 `0`

## 实际加载的文件

强制上下文：

- `STATE.md`
- `INDEX.md`
- `SUMMARY.md`
- `tools/context-injection.md`
- `principles/r10-honesty.rule.md`
- `principles/per-protocol.rule.md`
- `principles/scope-control.rule.md`
- `principles/fixture-first.rule.md`

项目索引与直接相关记忆：

- `projects/INDEX.md`
- `projects/solution-drafter/MEMORY.md`
- `projects/solution-drafter/LESSONS.md`
- `projects/solution-drafter/STATE.md`
- `projects/agentic-kb-lite/MEMORY.md`
- `projects/agentic-kb-lite/LESSONS.md`
- `projects/agentic-kb-lite/STATE.md`
- `projects/tender-writer/MEMORY.md`
- `projects/tender-writer/LESSONS.md`
- `projects/tender-writer/STATE.md`
- `projects/cim-link-engine/MEMORY.md`
- `projects/cim-link-engine/LESSONS.md`
- `projects/cim-link-engine/STATE.md`
- `projects/jiangli/MEMORY.md`
- `projects/jiangli/LESSONS.md`
- `projects/jiangli/STATE.md`

## 核心规则对 trip-decider 的影响

| 规则 | 本项目的具体约束 |
|---|---|
| R10 | Schema 缺字段、类型不符、hash/provenance 断裂时必须硬失败；不得补造事实或 silent fallback；LLM 只能产出可审计的语义结构，不能成为事实来源；数量、hash、case 和状态必须来自命令；`no_plan_found` 不得表述成数学无解。 |
| PER | 每个工作单元必须完成 Plan、获批、Execute、整体 Review、验收；WU0 只执行获批的 C0—C4，Review 后停下，不自动创建或开始 WU1。 |
| Scope | 以批准 Plan 的文件白名单、保护清单、最大文件数和 12 条完成判定为执行边界；计划外文件、依赖、secret 风险或产品级冲突必须停止，不“顺便”处理。 |
| Fixture-first | WU0 只冻结 fixture specification 和有效 red 标准，不创建测试或 fixture；WU1+ 必须先提交人工 expected 的失败 fixture，再提交实现，并保留可复核的 fail→pass 证据。 |

## 复用的项目模式

- `solution-drafter`：阶段间文件契约；上游产物必须被下游真实消费；契约兑现审计；显式记录缺失事实；扫描“声明大于实现”。
- `tender-writer`：脚本只做确定性变换，语义工作显式交给模型；真实 anchor 与 generator 分离以防自指；文案与控制流对账；敏感信息从源头不进入 Git。
- `cim-link-engine`：replay-based eval；PASS/WARN/FAIL 均须回归；current state 与 run history 分离；evidence、why、provenance 是一等数据；验收包可独立复核。
- `agentic-kb-lite`：依赖从简；结构化强断言；确定性变换可使用合成输入和人工写定 expected；判不准则不做；真实使用前不扩 Web UI 或向量库。
- `jiangli`：GIS 计算层与表达层分离；来源口径与算法口径不互相冒名；真实数据不进入 Git；多目标优化的实现、解释和文档必须同步。

## 明确不适用的模式

- 不复用 `tender-writer` 的 docx/Part 模型、投标合规状态机或开源发布流程。
- 不复用 `agentic-kb-lite` 的多级检索降级、向量知识库或失败后保留 STUB 的语义；trip-decider 的契约破坏必须硬失败。
- 不复用 `cim-link-engine` 的 UI、CIM 实体模型、回写流程或数据库。
- 不复用 `jiangli` 的 Vue、FastAPI、Tauri、SQLite、DEAP NSGA-II 或栅格流水线；仅采用“算法结论不等于领域事实”的边界。
- 不复用 `solution-drafter` 的文档生成阶段和素材占位格式。
- WU0 不引入 LangGraph、CrewAI、多 Agent、RAG、向量数据库、数据库、前端框架或云基础设施。

## 可能回写 handbook 的候选经验

- 证据展示状态应由 support、derivation、freshness、source conflict 等正交字段确定性映射，避免单枚举同时承担来源、推导和时效语义。
- 启发式“未找到计划”与完备证明“无解”必须在领域状态和用户文案中分开。
- 重排稳定性需要旧计划工件和确定性变更代价，不能只依赖模型生成“尽量少改”的解释。
- 城市无关应约束 planner/constraints/domain；地区或供应商差异应留在统一 Evidence Contract 的 adapter。
