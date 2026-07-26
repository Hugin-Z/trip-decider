# trip-decider v0 initial architecture

状态：`DOCUMENT_CONTRACT_ONLY`

本文冻结 WU1+ 的目录职责、依赖方向、A—H 文件交接和城市无关边界。WU0 没有创建这些目录、安装依赖或实现 Schema、validator、adapter、planner、CLI、测试与渲染器。

## A—H 管线与文件交接

| 阶段 | v0 职责 | 读取 | 产出 |
|---|---|---|---|
| A 需求澄清与约束化 | 保存原始请求，显式解析，生成用户可编辑的求解权威约束 | 用户输入 | `request.yaml` → `constraint-parse.json` → `constraints.yaml` |
| B 可达目的地候选池 | v0 只对用户给定目的地做 pass-through；冻结 v1 能力 A 接口 | `request.yaml`、`constraints.yaml` | `candidates.json` 的 destination 候选 |
| C POI/基地候选池 | 零起点检索与用户指定点双入口；不写城市特例 | constraints、destination candidate、adapter 输出 | 新的、不可变 `candidates.json` |
| D 字段级证据 | 从 Web/公告/API/直接观测采集并标准化；正交定级；依赖传播 | candidates、adapter 原始结果 | 独立 `evidence.json` |
| E 约束形式化与冲突检查 | 三层约束、环境检查、确定性 proof 与候选冲突区分 | constraints、candidates、evidence | `violations.json` |
| F 结构求解 | 枚举基地、贪心分天、天内局部优化；可解释优先 | constraints、candidates、evidence、violations | `plan.json` 与更新后的 `violations.json` |
| G 行程卡 | 只渲染上游事实、条件、淘汰理由和证据标签 | plan、evidence、violations、可选 plan diff | `trip-card.html` |
| H 局部重排 | 以旧计划不可变快照为基准，最小变更作为确定性目标 | edited constraints、`previous-plan.json`、candidates、evidence | 新 `plan.json`、`plan-diff.json`、`violations.json` |

阶段间只通过版本化工件交接。每个消费者记录实际读取的上游 artifact ID、payload hash 和文件 bytes hash；缺失、版本不兼容或 hash 不符必须硬失败。渲染层不得提升状态或补造事实。

## 目标目录与职责

以下是目标结构，不代表 WU0 已创建：

```text
trip-decider/
├─ PLAN.md
├─ plans/
├─ src/trip_decider/
│  ├─ domain/
│  ├─ evidence/
│  ├─ constraints/
│  ├─ planner/
│  ├─ adapters/
│  ├─ pipeline/
│  ├─ rendering/
│  ├─ schema_validation.py
│  ├─ fixture_validation.py
│  ├─ config.py
│  └─ cli.py
├─ schemas/
├─ fixtures/
├─ tests/
├─ docs/
├─ scripts/
└─ examples/
```

- `domain/`：城市无关实体、稳定 ID、枚举、工件引用和值对象。
- `evidence/`：support、derivation、freshness、source conflict 的正交模型；外显五态映射和依赖传播。
- `constraints/`：约束规范化、三层分类、环境检查、确定性 proof 规则；不执行语义猜测。
- `planner/`：基地枚举、分天、天内排序和重排代价；只能消费统一 domain/evidence/constraints。
- `adapters/`：供应商、来源类型、解析器和适用地区；输出统一 Evidence Contract。
- `pipeline/`：A—H orchestration、文件 hash/版本检查和 run provenance；不得掩盖阶段失败。
- `rendering/`：单文件 HTML；只表达上游工件，不生成新事实或决策。
- `schema_validation.py`：WU1 的 strict structural validator；不证明业务正确性。
- `fixture_validation.py`：WU1 的 fixture manifest/source/coverage validator。
- `config.py`：首次由真实 adapter 需要时实现；WU0/WU1 不提前创建。
- `cli.py`：首次有实际运行入口时实现；WU0 不创建。
- `schemas/`：十项工件的 JSON Schema Draft 2020-12 和 HTML contract。
- `fixtures/`：可回放 case；每例声明来源、覆盖范围、不覆盖范围和人工 expected。
- `tests/`：一个 case 一个行为，使用具体字段断言。
- `scripts/`：可独立复核的命令入口，不承载业务语义。
- `examples/`：未来脱敏示例；不保存真实旅行数据或 secret。

## 依赖方向

```text
adapters ──> domain + evidence contracts
constraints ──> domain + evidence
planner ──> domain + evidence + constraints
rendering ──> plan + evidence + violations + plan-diff
pipeline ──> adapters + constraints + planner + rendering
```

禁止反向依赖：

- `domain/evidence/constraints/planner` 不得依赖任何具体 adapter。
- `planner/constraints/evidence/domain` 不得出现具体城市名称、城市分支或按城市放宽硬约束。
- adapter 可以声明 provider、source type 和适用地区，但不能改变证据定级映射、约束层级或求解状态定义。
- rendering 不得成为事实采集、约束传播或重新求解的隐式阶段。

## 四项关键契约修正

1. Candidate/Evidence 阶段不可变：C 产出的候选不依赖尚不存在的 D 阶段 evidence。D 生成独立 evidence artifact，不回写旧 candidates；计划同时引用 candidate ID 和 fact ID。
2. Estimated 不等于 conditional：事实显示 `estimated`；计划是否 conditional 取决于估计是否有不确定性/缓冲，以及保守边界是否仍满足硬约束。
3. Evidence Source 是判别联合：webpage/official notice、API response、direct observation 和 user supplied 按实际来源保存各自字段，不伪造 URL、publisher、excerpt 或 published_at。
4. Constraint origin refs 是判别联合：explicit、inferred、default、user edited 各自必须有对应 parse/default/edit 追踪；重解析不得覆盖用户编辑后的 `constraints.yaml`。

## 可行性和证明边界

- `feasible`：找到满足硬约束与环境要求的结构；关键依赖没有 unresolved unknown/conflicting；关键估算在可回读保守边界下仍满足硬约束。
- `conditionally_feasible`：结构存在，但依赖 unresolved unknown/conflicting，或估计无不确定性处理/可能跨越硬边界。
- `proven_infeasible`：确定性规则或完备检查给出可回放证明。
- `no_plan_found`：有界启发式没有找到计划且没有证明；用户文案必须说明“尚不能证明无解”。

只有真正做过最小化验证才能声明 minimal conflict；v0 默认仅输出 `candidate_conflict_set`。

## Secrets 与配置边界

- 高德 key 的唯一环境变量名为 `TRIP_DECIDER_AMAP_API_KEY`。
- adapter 日志未来只允许输出 `amap_key_configured=true|false`，不得输出值、长度、hash、URL query 或 header。
- 缺 key 的真实 API 命令必须硬失败；集成测试明确 skip 或使用脱敏录制 fixture；CI 不依赖真实 key。
- WU0 不创建 `.env.example`、config、adapter 或录制数据，不调用高德，也不修改用户环境。

## 明确不引入

当前架构不需要 LangGraph、CrewAI、多 Agent 框架、数据库、消息队列、前端框架、容器编排、云服务或向量数据库。任何后续依赖只能在对应工作单元 Plan 中按实际需要、license、Windows 兼容和锁版本重新批准。
