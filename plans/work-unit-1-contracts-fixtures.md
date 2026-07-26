# Work Unit 1 Plan：工件契约、严格验证与 fixture 骨架

Plan 版本：v0.5
状态：`PENDING_HUGIN_APPROVAL`
适用工作单元：WU1
前置验收：WU0 已由 Hugin 批准，关闭 commit 为 `21d8508a8f96472ecc4d7f798cdd6af3d7f54f68`
计划基线时间：2026-07-26（Asia/Shanghai）

> 本文件仅是 PER 的 Plan。未收到语义明确的“批准执行 Work Unit 1”前，不得创建本计划白名单中的其他文件，不得安装依赖，不得运行实现性脚本，不得提交本计划，也不得进入 Execute。

## 1. 任务目标

WU1 只负责把 WU0 冻结的文档级契约变成可独立验证的结构契约，为 WU2—WU8 提供稳定输入：

1. 为九个机器工件建立 Draft 2020-12 JSON Schema，为 `trip-card.html` 建立非渲染的 HTML 交付契约。
2. 冻结通用工件 envelope、稳定 ID、工件引用、hash、provenance、事实来源、用户输入、模型推断与算法估计的结构边界。
3. 建立严格 JSON/YAML 加载与 Schema 验证入口；字段缺失、类型错误、未知字段、未知 major、格式校验器缺失、hash 不符或引用破坏必须硬失败。
4. 建立 fixture manifest 验证器和六个 fixture 目录；清楚区分 WU1 可验证的“结构层”与后续工作单元才验证的“行为层”。
5. 用可解析但违反契约的输入完成真实 red → green；红灯不得依赖缺文件、缺模块、语法错误或未安装依赖。
6. 建立单一、可独立运行的 WU1 验证入口，并记录依赖、许可证、Windows 兼容性与可重放锁定方法。

WU1 只证明：

- 工件与 fixture 的结构符合冻结契约；
- 跨文件的 hash、引用和稳定 ID 可被确定性验证；
- 错误通过稳定的机器可读对象和退出码暴露；
- 未知或破坏的输入不会被 silent fallback 接受。

WU1 不证明、也不得在文档中暗示已经实现：

- 自然语言约束解析；
- 高德、Web、官方来源或真实 POI 接入；
- 证据自动定级、冲突消解或依赖传播；
- 约束可行性判断、证明正确性或冲突集最小化；
- 基地选择、分天、排序、路径优化或计划生成；
- 重排代价计算或“最小改变”优化；
- HTML 生成、CSS、浏览器展示或真实江西行程；
- v1 目的地发现能力 A；
- 数据库、Web UI、服务端 API 或多 Agent 编排。

## 2. 输入、基线与重新注入的 handbook

### 2.1 项目输入

以下文件必须在 Execute 开始前再次读取。这里的 SHA256 均由 PowerShell `Get-FileHash -Algorithm SHA256` 产生；任何一个 hash 变化都属于 Plan 基线变化，必须停止并请求重新裁定。

| 输入 | SHA256 |
|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `plans/work-unit-0-bootstrap-d0.md` | `4C7FE14CD5D2CE0CC8E8D624D93C24338EAF61A9DBC0778D101AB3565602DE3B` |
| `docs/architecture.md` | `CA5B6F7D345E11623C94C13CDD73C0E774282AFD88F9E2E036035ED2396BB6F4` |
| `docs/artifact-contracts.md` | `695C0AC6738B71852DC60ADAFD2A98B974C5EC65BB744D19B0E22EC3550497BF` |
| `docs/prior-art.md` | `C1195E816DB5F21FE83B4208B6258BA9F138C9AB9404373A132CE75C457893E7` |
| `docs/handbook-context.md` | `1933DBA1B3697A394EDCC0238B60A032A18EA10B920F8C4358169490492115EB` |
| `docs/reviews/work-unit-0-review.md` | `D93373ECC7398DEE95FFCC04E0143DE80612B4FE948FD36282FA98F793477128` |

实测执行基线：

- 项目分支：`main`
- WU1 Plan 前项目 HEAD：`21d8508a8f96472ecc4d7f798cdd6af3d7f54f68`
- 项目工作树：干净
- 操作系统：Microsoft Windows NT `10.0.26200.0`，64 位
- PowerShell：`5.1.26100.8875`
- Python：`3.11.9`
- pip：`24.0`
- Git：`2.53.0.windows.1`
- uv：不可用
- Poetry：不可用
- 项目 `.venv`：不存在

全局环境中包的存在只用于环境观察，绝不作为依赖锁定依据：已观察到 PyYAML `6.0.3`、jsonschema `4.26.0` 和 referencing `0.37.0` 可导入。

### 2.2 Handbook 重新注入

Handbook 固定路径：

```text
<handbook>
```

Execute 的 C0 前必须只读执行 fetch 对账，并从 `origin/main` 重新读取：

```text
STATE.md
INDEX.md
SUMMARY.md
tools/context-injection.md
principles/r10-honesty.rule.md
principles/per-protocol.rule.md
principles/scope-control.rule.md
principles/fixture-first.rule.md
```

Plan 阶段实测：

- handbook 本地 HEAD：`6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`
- handbook `origin/main`：`6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`
- ahead/behind：`0/0`
- handbook 工作树：干净
- 八个必注入文件：`8/8` 已从 `origin/main` 实际读取

若 Execute 时 `origin/main`、输入 hash 或规则语义发生变化，不得自行兼容；停止 WU1 并报告。

### 2.3 四条规则对 WU1 的约束

- R10：加载、schema、format、hash、引用或 fixture expectation 不成立时硬失败；不得猜测字段、自动补默认值或把 warning 当 pass；错误对象不回显潜在 secret。
- PER：本计划获批后才能 Execute；所有批准 commit 完成后统一 Review；不得自动进入 WU2。
- Scope：只触碰 §3 白名单；发现需要修改冻结输入、Plan、handbook 或白名单外文件时停止。
- Fixture-first：测试 commit 必须先于对应实现 commit；红灯来自真实契约缺口，不能来自 import 失败、缺文件、畸形 JSON/YAML 或依赖未安装。

### 2.4 Hugin 批准的 WU1 实施勘误

WU0 文档草案中的 `constraint-parse.payload.output_payload_sha256` 在 WU1 不实现。本 Plan v0.5 对这一字段的裁定优先于 WU0 文档草案，且只修正该自引用字段；不得借此修改任何 WU0 文件或其他产品契约。

原因：

- 如果它表示当前 constraint-parse payload hash，字段位于被 hash 的 payload 内，形成自引用；
- 如果它表示未来 `constraints.yaml` hash，parse producer 无法在用户确认或编辑前稳定确定；
- 同一 artifact 不能同时有两个含义重叠的 payload hash 权威字段。

权威链固定为：

```text
request artifact
  ↓ constraint-parse.payload.request_ref
constraint-parse artifact
  ↓ constraints.payload.parse_ref
constraints artifact
```

- `request_ref` 是完整 artifact reference，证明 parser 实际读取的 request payload；
- constraint-parse 自身完整性只由 envelope `integrity.payload_sha256` 表达；
- `parse_ref` 是完整 artifact reference，携带 constraint-parse 的 payload hash；
- 上游 parse artifact 不得预存未来 constraints artifact 的 hash。

## 3. Scope 与精确文件白名单

### 3.1 允许创建或修改的 36 个路径

下表是 Execute 的完整写入白名单。除序号 1 的获批 Plan 外，共 35 个实现、fixture、验证和 Review 路径。

| # | 路径 | 现在需要它的原因 |
|---:|---|---|
| 1 | `plans/work-unit-1-contracts-fixtures.md` | C0 记录获批 Plan；提交后成为 WU1 不可变基线 |
| 2 | `pyproject.toml` | 冻结 Python 目标、直接依赖和包发现配置 |
| 3 | `requirements.lock` | 记录干净 `.venv` 中解析出的精确传递版本 |
| 4 | `src/trip_decider/__init__.py` | 建立最小可导入包边界，不暴露业务能力 |
| 5 | `src/trip_decider/schema_validation.py` | 严格工件加载、Schema、hash 与引用验证 |
| 6 | `src/trip_decider/fixture_validation.py` | fixture manifest、内嵌字节、clean/dirty 验证 |
| 7 | `schemas/common.schema.json` | 通用 envelope、ID、hash、来源、origin 和引用定义 |
| 8 | `schemas/fixture-case.schema.json` | fixture manifest 结构和期望错误结构 |
| 9 | `schemas/request.schema.json` | `request.yaml` 结构契约 |
| 10 | `schemas/constraint-parse.schema.json` | `constraint-parse.json` 结构契约 |
| 11 | `schemas/constraints.schema.json` | `constraints.yaml` 结构契约 |
| 12 | `schemas/candidates.schema.json` | `candidates.json` 结构契约 |
| 13 | `schemas/evidence.schema.json` | `evidence.json` 正交证据结构契约 |
| 14 | `schemas/previous-plan.schema.json` | `previous-plan.json` 快照契约 |
| 15 | `schemas/plan.schema.json` | `plan.json` 结构与四态契约 |
| 16 | `schemas/plan-diff.schema.json` | `plan-diff.json` 变更记录契约 |
| 17 | `schemas/violations.schema.json` | `violations.json` 证明与候选冲突结构 |
| 18 | `schemas/trip-card.contract.md` | 只冻结 `trip-card.html` 交付边界，不实现 HTML |
| 19 | `fixtures/README.md` | 统一说明 fixture 来源、结构层和行为层 |
| 20 | `fixtures/fixture_01_feasible/README.md` | 可行结构 fixture 的范围与非范围 |
| 21 | `fixtures/fixture_01_feasible/case.json` | 可行结构 clean/dirty manifest |
| 22 | `fixtures/fixture_02_direct_conflict/README.md` | 直接矛盾 fixture 的范围与非范围 |
| 23 | `fixtures/fixture_02_direct_conflict/case.json` | 证明存在性 clean/dirty manifest |
| 24 | `fixtures/fixture_03_uncertain_dependency/README.md` | 不确定依赖 fixture 的范围与非范围 |
| 25 | `fixtures/fixture_03_uncertain_dependency/case.json` | 条件可行 clean/dirty manifest |
| 26 | `fixtures/fixture_04_replan_stability/README.md` | 重排稳定性 fixture 的范围与非范围 |
| 27 | `fixtures/fixture_04_replan_stability/case.json` | previous plan/diff clean/dirty manifest |
| 28 | `fixtures/fixture_05_evidence_state_mapping/README.md` | 证据正交映射 fixture 的范围与非范围 |
| 29 | `fixtures/fixture_05_evidence_state_mapping/case.json` | 来源联合类型 clean/dirty manifest |
| 30 | `fixtures/fixture_06_no_plan_found_not_infeasible/README.md` | “没找到”边界 fixture 的范围与非范围 |
| 31 | `fixtures/fixture_06_no_plan_found_not_infeasible/case.json` | no-plan-found clean/dirty manifest |
| 32 | `tests/__init__.py` | 标准库 unittest 发现入口 |
| 33 | `tests/test_schema_validation.py` | 先红后绿的 schema/工件验证测试 |
| 34 | `tests/test_fixture_validation.py` | 先红后绿的 manifest/fixture 验证测试 |
| 35 | `scripts/verify_wu1.ps1` | C7 才创建的 Windows 最终完整验证入口 |
| 36 | `docs/reviews/work-unit-1-review.md` | C8 记录实际 Git、red/green、hash、scope 和判定证据 |

### 3.2 明确保护和禁止

不得修改：

- `PLAN.md`；
- `plans/work-unit-0-bootstrap-d0.md`；
- WU0 产出的所有 `docs/` 文件，唯独允许新增 WU1 Review；
- handbook 仓库任何内容；
- `.gitignore`、`.env.example` 及其他 WU0 文件；
- 用户全局 Python、pip、PowerShell 或 Git 配置；
- 其他项目仓库与系统目录。

不得新增白名单外的快照、缓存、coverage、临时证据或工具配置。运行产生的 `.venv/`、`__pycache__/` 等必须已由 WU0 忽略，且不得进入 Git。

若实际实现需要第 37 个路径、需要修改本 Plan、冻结输入或保护文件，立即停止整个 WU1。

## 4. 依赖决策与可重放环境

### 4.1 选择

| 能力 | 决策 | 版本/来源 | 许可证与兼容性 | 为什么现在 |
|---|---|---|---|---|
| YAML | 采用 PyYAML | 执行目标 `6.0.3` | MIT；Python ≥3.8；有 CPython 3.11 Windows x64 wheel | 两个 YAML 工件必须安全解析并验证 |
| JSON Schema | 采用 `jsonschema[format-nongpl]` | 执行目标 `4.26.0` | MIT；Python ≥3.10；支持 Draft 2020-12；传递许可证仍逐项审计 | 需要标准 Schema 和显式 format checker |
| 领域模型 | 不采用 Pydantic | 对比稳定版 `2.13.4` | MIT；Python ≥3.9 | 手写 JSON Schema 已是 SSOT；Pydantic 会造成第二事实源和漂移 |
| 测试 | 标准库 `unittest` | Python `3.11.*` | Python 标准库 | 不为 WU1 引入 pytest |
| CLI | 标准库 `argparse` | Python `3.11.*` | Python 标准库 | 足够提供稳定命令和退出码 |
| hash/时间/路径/JSON | 标准库 | Python `3.11.*` | Python 标准库 | 无需第三方依赖 |

不引入 HTTP、HTML 模板、地理计算、数据库、前端、Agent、工作流、日志或 CLI 框架。WU1 不需要它们。

### 4.2 安全加载

- YAML 只用 `yaml.SafeLoader`；不得用默认或 unsafe loader。
- 在构造 Python 对象前用 SafeLoader composition 节点检查重复 key 和非字符串 mapping key。
- JSON 用 `object_pairs_hook` 拒绝重复 key，用 `parse_constant` 拒绝 `NaN`、`Infinity` 和 `-Infinity`。
- 输入按严格 UTF-8 解码；BOM、非法字节、非文件、安全路径逃逸都硬失败。
- 验证器不得替用户补字段、强制转换类型、猜测单位或吞掉未知字段。

### 4.3 锁定和许可证门槛

Execute 时：

1. 用 Python 3.11 在仓库内创建全新 `.venv`；创建前解析绝对路径并确认目标严格位于项目根目录下。
2. 仅从 `pyproject.toml` 安装直接依赖；不得读取或冻结全局 site-packages。
3. 在干净 `.venv` 中解析精确版本并机械生成 `requirements.lock`。
4. 为每一个直接和传递依赖记录包名、版本、许可证来源；许可证缺失、无法核实或与项目不兼容时停止 WU1。
5. 删除并重建同一路径的干净 `.venv`，仅从 lock 安装，再运行相同验证命令。
6. `requirements.lock` 必须可审阅且不得包含本机绝对路径、凭据或私有 index URL。

允许的网络用途只有从公开 Python 包索引安装已批准依赖和核验其官方 metadata/license。不得调用高德、Web 数据源或旅游 API。

## 5. 工件 Schema 总体规则

### 5.1 Schema 元数据和解析

- 所有 JSON Schema 使用 `"$schema": "https://json-schema.org/draft/2020-12/schema"`。
- 每个 Schema 有唯一、稳定的 `$id`；使用保留示例域，不暗示线上服务，例如 `https://trip-decider.example/schemas/0.1.0/plan.schema.json`。
- 验证器预加载本地 registry；禁止在验证过程中远程解析 `$ref`。
- 工件 `schema_version` 使用 SemVer 字符串；WU1 支持 major `0`，未知 major 硬失败。
- 对象默认 `additionalProperties: false`；组合结构在需要处使用 `unevaluatedProperties: false` 避免 `allOf` 漏洞。
- null 与 missing 不等价：可空字段显式使用包含 `null` 的类型联合；可选字段不进入 `required`；不得用 default 模糊二者。
- 时间字段同时要求 JSON Schema `date-time` format 和以 `Z` 或显式 `±HH:MM` 结尾的 offset 约束。
- `jsonschema` 的 format 校验默认不会自动启用，因此必须显式配置 Draft 2020-12 FormatChecker；date-time checker 缺失或启动自检失败时以内部错误退出，绝不能视为通过。
- SHA256 使用 64 位小写十六进制规范形式；不接受大写、前缀或缩写。

### 5.2 通用 envelope

九个机器工件均具备：

```yaml
schema_version:
artifact_id:
artifact_type:
created_at:
producer:
provenance:
integrity:
payload:
```

最低结构：

- `schema_version`：契约版本，不等同于 parser/planner 版本。
- `artifact_id`：小写 UUID URN，例如 `urn:uuid:<uuid>`，禁止用文件名代替。
- `artifact_type`：与具体 Schema `const` 一致。
- `created_at`：带 offset 的 RFC3339 时间。
- `producer`：`name`、`version`、`run_id`；用户直接创建时 `name=user`；组件名称不是事实来源。
- `provenance`：`parent_artifact_ids`、`input_hashes`、`pipeline_stage`；不得把 LLM 写入 `sources`。
- `integrity`：`payload_sha256`、`canonicalization`，明确只覆盖 canonical payload bytes，不自包含整个 envelope。
- `payload`：具体工件内容。

canonical payload hash 的序列化规则在执行中固定为 UTF-8、无 BOM、JSON key 按 Unicode code point 排序、紧凑分隔符、禁止 NaN/Infinity。YAML 工件先严格解析为数据结构，再按同一 canonical JSON 规则计算 payload hash。验证器只检查已给 hash，不自动修复。

所有机器工件每个 payload 只有 envelope `integrity.payload_sha256` 这一份自身完整性权威 hash。具体 payload 不得再声明覆盖自身的 hash 字段；`constraint-parse.output_payload_sha256` 必须由闭合 Schema 拒绝。

### 5.3 稳定 ID 和引用

- 领域实体 ID 采用 `<kind>_<lowercase-uuid>`；允许前缀在 common Schema 中闭集定义，例如 `request`、`constraint`、`candidate`、`fact`、`plan`、`base_selection`、`day`、`activity`、`leg`、`violation`、`proof`、`change`、`run`、`case`。

#### Artifact ID

- 每个工件 envelope 的 `artifact_id` 是一个 artifact definition，在一个验证 bundle 内必须唯一。
- artifact reference 中任意次数重复出现同一个 `artifact_id` 都是合法引用，不算重复定义。
- artifact reference 至少包含 `artifact_id`、`artifact_type`、`schema_version`、`payload_sha256`，并全部 `required`、`additionalProperties: false`。
- 在 `CLOSED` bundle 中，artifact reference 必须解析到恰好一个 ID、类型、major 和 payload hash 均兼容的 artifact definition。

#### Entity definition ID

validator 只从下表显式维护的 definition paths 收集实体定义。路径是相对于对应 artifact 根的固定 JSON Pointer pattern；`[*]` 只表示遍历已声明数组，不是对任意字符串的正则扫描。

| Definition kind | Artifact type | Definition path |
|---|---|---|
| request | `request` | `/payload/request_id` |
| parse item | `constraint-parse` | `/payload/parsed_constraints[*]/parse_item_id` |
| constraint set | `constraints` | `/payload/constraint_set_id` |
| constraint | `constraints` | `/payload/constraints[*]/constraint_id` |
| candidate set | `candidates` | `/payload/candidate_set_id` |
| candidate | `candidates` | `/payload/candidates[*]/candidate_id` |
| evidence set | `evidence` | `/payload/evidence_set_id` |
| evidence fact | `evidence` | `/payload/facts[*]/fact_id` |
| plan | `plan` | `/payload/plan_id` |
| base selection | `plan` | `/payload/base_selections[*]/base_selection_id` |
| day | `plan` | `/payload/days[*]/day_id` |
| activity | `plan` | `/payload/days[*]/activities[*]/activity_id` |
| leg | `plan` | `/payload/days[*]/legs[*]/leg_id` |
| violation | `violations` | `/payload/violations[*]/violation_id` |
| proof | `violations` | `/payload/proofs[*]/proof_id` |
| change | `plan-diff` | `/payload/changes[*]/change_id` |

没有出现在该表中的 ID 形字段不是 bundle 级 entity definition。尤其是 `constraint-parse.payload.parsed_constraints[*].constraint_id` 是对最终 constraint definition 的 entity reference，不能作为第二个 constraint definition。Evidence `source_id` 使用下文的 fact-local scope，也不进入该表。

#### 四类 reference

每个不属于 definition path、但带 ref、refs、id 或 locator 语义的字段必须由下文显式 reference-path registry 分类，禁止按字段后缀、UUID 格式或字符串内容推断。

1. `artifact`：指向另一阶段工件的 envelope，只能解析到 artifact definition。
2. `entity`：指向 definition-path registry 中的领域实体，只能解析到兼容 entity kind。
3. `provenance`：用户输入、provider、检索结果、网页或响应位置，只做自身 Schema 校验，不进入 artifact/entity resolver，也不要求 bundle 中存在实体目标。
4. `local_scoped`：只在明确父作用域中解析；WU1 的初始实例是 Evidence fact 内部的 source ID。

`candidates.payload.candidates[*].source_refs[*]` 明确属于 `provenance`。它可以表达用户指定位置、provider/item ID、检索结果 locator、网页发现位置或上游候选生成记录；它不是 `evidence.json` 的 source ID 引用。D 阶段不得因把它解释成 evidence reference 而回写旧 candidates。

#### Reference-path registry

每条 registry 项冻结 `artifact_type`、`json_pointer_pattern`、`reference_category`、`expected_kind`、`closed_bundle_required` 和 artifact-only handling。下表是 WU1 初始完整 registry；具体 Schema 中的联合分支仍须保持同一分类。

| Artifact type | JSON Pointer pattern | Category | Expected kind | Closed required | ARTIFACT_ONLY handling |
|---|---|---|---|---:|---|
| `constraint-parse` | `/payload/request_ref` | artifact | artifact:`request` | true | 不解析跨工件目标 |
| `constraints` | `/payload/request_ref` | artifact | artifact:`request` | true | 不解析跨工件目标 |
| `constraints` | `/payload/parse_ref` | artifact | artifact:`constraint-parse` | true | 不解析跨工件目标 |
| `candidates` | `/payload/request_ref` | artifact | artifact:`request` | true | 不解析跨工件目标 |
| `plan` | `/payload/request_ref` | artifact | artifact:`request` | true | 不解析跨工件目标 |
| `plan` | `/payload/constraint_set_ref` | artifact | artifact:`constraints` | true | 不解析跨工件目标 |
| `plan` | `/payload/candidate_set_ref` | artifact | artifact:`candidates` | true | 不解析跨工件目标 |
| `plan` | `/payload/evidence_set_ref` | artifact | artifact:`evidence` | true | 不解析跨工件目标 |
| `plan` | `/payload/previous_plan_ref` | artifact | artifact:`previous-plan` | true when present | 不解析跨工件目标 |
| `previous-plan` | `/payload/previous_plan_artifact_ref` | artifact | artifact:`plan` | false | 自足 snapshot 的历史完整性 locator；目标存在时校验 |
| `violations` | `/payload/request_ref` | artifact | artifact:`request` | true when `pre_plan` | 不解析跨工件目标 |
| `violations` | `/payload/constraint_set_ref` | artifact | artifact:`constraints` | true when `pre_plan` | 不解析跨工件目标 |
| `violations` | `/payload/candidate_set_ref` | artifact | artifact:`candidates` | true when `pre_plan` | 不解析跨工件目标 |
| `violations` | `/payload/evidence_set_ref` | artifact | artifact:`evidence` | true when `pre_plan` | 不解析跨工件目标 |
| `violations` | `/payload/plan_ref` | artifact | artifact:`plan` | true when `post_plan` | 不解析跨工件目标 |
| `constraint-parse` | `/payload/parsed_constraints[*]/constraint_id` | entity | constraint | true | 目标未提供时不执行跨工件检查 |
| `constraints` | `/payload/constraints[*]/target_refs[*]/request_id` | entity | request | true when `target_type=request_scope` | 目标未提供时延后 |
| `constraints` | `/payload/constraints[*]/target_refs[*]/entity_id` | entity | sibling `entity_kind` | true when `target_type=entity` | 仅解析本工件已有兼容定义，否则延后 |
| `constraints` | `/payload/constraints[*]/origin/refs[*]/parse_item_id` | entity | parse item | true when origin is explicit/inferred | 目标未提供时延后 |
| `constraints` | `/payload/constraints[*]/supersedes_constraint_id` | entity | constraint | true when present | 当前工件内必须解析 |
| `candidates` | `/payload/candidates[*]/parent_candidate_id` | entity | candidate | true when non-null | 当前工件内必须解析 |
| `candidates` | `/payload/candidates[*]/evidence_fact_refs[*]` | entity | evidence fact | true when present | 目标未提供时延后 |
| `evidence` | `/payload/facts[*]/subject/entity_id` | entity | candidate | true when `subject_type=entity` | 目标未提供时延后 |
| `evidence` | `/payload/facts[*]/subject/from_candidate_ref` | entity | candidate | true when `subject_type=relation` | 目标未提供时延后 |
| `evidence` | `/payload/facts[*]/subject/to_candidate_ref` | entity | candidate | true when `subject_type=relation` | 目标未提供时延后 |
| `evidence` | `/payload/facts[*]/derivation_detail/input_fact_ids[*]` | entity | evidence fact | true when present | 当前工件内必须解析 |
| `plan` | `/payload/conditions[*]/constraint_refs[*]` | entity | constraint | true | 目标未提供时延后 |
| `plan` | `/payload/conditions[*]/evidence_fact_refs[*]` | entity | evidence fact | true | 目标未提供时延后 |
| `plan` | `/payload/base_selections[*]/candidate_ref` | entity | candidate | true | 目标未提供时延后 |
| `plan` | `/payload/base_selections[*]/constraint_refs[*]` | entity | constraint | true | 目标未提供时延后 |
| `plan` | `/payload/base_selections[*]/evidence_fact_refs[*]` | entity | evidence fact | true | 目标未提供时延后 |
| `plan` | `/payload/days[*]/activities[*]/candidate_ref` | entity | candidate | true | 目标未提供时延后 |
| `plan` | `/payload/days[*]/activities[*]/constraint_refs[*]` | entity | constraint | true | 目标未提供时延后 |
| `plan` | `/payload/days[*]/activities[*]/evidence_fact_refs[*]` | entity | evidence fact | true | 目标未提供时延后 |
| `plan` | `/payload/days[*]/legs[*]/derivation_fact_ref` | entity | evidence fact | true | 目标未提供时延后 |
| `plan` | `/payload/excluded_candidates[*]/candidate_ref` | entity | candidate | true | 目标未提供时延后 |
| `plan` | `/payload/excluded_candidates[*]/constraint_refs[*]` | entity | constraint | true | 目标未提供时延后 |
| `plan` | `/payload/excluded_candidates[*]/evidence_fact_refs[*]` | entity | evidence fact | true | 目标未提供时延后 |
| `plan` | `/payload/constraint_evaluations[*]/constraint_ref` | entity | constraint | true | 目标未提供时延后 |
| `plan` | `/payload/proof_refs[*]` | entity | proof | true when present | 目标未提供时延后 |
| `violations` | `/payload/violations[*]/constraint_refs[*]` | entity | constraint | true | 目标未提供时延后 |
| `violations` | `/payload/violations[*]/evidence_fact_refs[*]` | entity | evidence fact | true | 目标未提供时延后 |
| `violations` | `/payload/violations[*]/proof_refs[*]` | entity | proof | true when present | 当前工件内必须解析 |
| `violations` | `/payload/conditions[*]/constraint_refs[*]` | entity | constraint | true | 目标未提供时延后 |
| `violations` | `/payload/conditions[*]/evidence_fact_refs[*]` | entity | evidence fact | true | 目标未提供时延后 |
| `violations` | `/payload/candidate_conflict_sets[*]/constraint_refs[*]` | entity | constraint | true | 目标未提供时延后 |
| `violations` | `/payload/candidate_conflict_sets[*]/evidence_fact_refs[*]` | entity | evidence fact | true | 目标未提供时延后 |
| `violations` | `/payload/proofs[*]/constraint_refs[*]` | entity | constraint | true | 目标未提供时延后 |
| `violations` | `/payload/proofs[*]/input_fact_ids[*]` | entity | evidence fact | true | 目标未提供时延后 |
| `previous-plan` | `/payload/baseline_constraint_set_id` | entity | constraint set | true | 目标未提供时延后 |
| `plan-diff` | `/payload/previous_plan_id` | local_scoped | previous plan version identity | true | 必须匹配一个 previous-plan snapshot |
| `plan-diff` | `/payload/new_plan_id` | entity | plan | true | 目标未提供时延后 |
| `plan-diff` | `/payload/changes[*]/entity/entity_id` | local_scoped | sibling `entity_kind` in selected plan version | true | 按显式 `resolution_scope` 解析 |
| `plan-diff` | `/payload/changes[*]/constraint_refs[*]` | entity | constraint | true | 目标未提供时延后 |
| `*` | `/producer/run_id` | provenance | producer run locator | false | 只做 Schema |
| `*` | `/provenance/parent_artifact_ids[*]` | provenance | lineage locator | false | 只做 Schema |
| `request` | `/payload/user_input_refs[*]` | provenance | user input locator | false | 只做 Schema |
| `constraint-parse` | `/payload/parsed_constraints[*]/user_quote_locator` | provenance | request text locator | false | 只做 Schema |
| `candidates` | `/payload/candidates[*]/source_refs[*]` | provenance | candidate discovery locator | false | 只做 Schema |
| `candidates` | `/payload/rejected_inputs[*]/locator` | provenance | candidate input locator | false | 只做 Schema |
| `evidence` | `/payload/facts[*]/sources[*]/locator` | provenance | source locator | false | 只做 Schema |
| `evidence` | `/payload/facts[*]/sources[*]/response_locator` | provenance | API response locator | false | 只做 Schema |
| `evidence` | `/payload/facts[*]/sources[*]/request_fingerprint` | provenance | request fingerprint | false | 只做 Schema |
| `evidence` | `/payload/facts[*]/sources[*]/location_ref` | provenance | observation location locator | false | 只做 Schema |
| `evidence` | `/payload/facts[*]/conflict_source_refs[*]` | local_scoped | evidence source in current fact | false | 必须在当前 fact 解析 |

同一字段不得同时注册成两类。Schema 分支不存在的 path 不产生引用；nullable path 为 null 时不解析。registry 是显式代码常量并由 C3 测试覆盖，validator 不得扫描目录、字段名或任意字符串补充 registry。

#### Evidence source 的局部作用域

- Evidence source 的 scope key 是 `(fact_id, source_id)`，不是 bundle 级 entity ID。
- 同一 fact 的 `sources[]` 中两个相同 `source_id` 以 `DUPLICATE_LOCAL_SOURCE_ID` 硬失败。
- 不同 fact 可以复用相同 `source_id`；相同官方页面或 API response 可以支撑多个 fact。
- `conflict_source_refs` 只能解析当前 fact 的 `sources[]`；目标不存在时以 `UNRESOLVED_LOCAL_SOURCE_REFERENCE` 硬失败。
- resolver 不得跨 fact 猜测同名 source，也不得要求 candidate provenance `source_refs` 解析到 Evidence source。

#### Previous-plan snapshot 的局部定义与 plan-version 引用

Previous-plan snapshot 中以下路径是 artifact-local definitions，不进入 bundle 级 entity definition-path registry：

| Local kind | Previous-plan local definition path |
|---|---|
| previous plan version identity | `/payload/previous_plan_id` |
| base selection | `/payload/snapshot/base_selections[*]/base_selection_id` |
| day | `/payload/snapshot/days[*]/day_id` |
| activity | `/payload/snapshot/days[*]/activities[*]/activity_id` |
| leg | `/payload/snapshot/days[*]/legs[*]/leg_id` |

局部 scope key 固定为：

```text
(previous_plan_artifact_ref.artifact_id, entity_kind, entity_id)
```

其中 `previous_plan_artifact_ref.artifact_id` 是 WU0 字段 `previous_plan_artifact_id` 的结构化表示。相同 ID 在 previous snapshot local scope 与 new `plan.json` definition 中同时存在是合法版本延续，不构成 `DUPLICATE_DEFINITION_ID`。

`plan-diff.payload.changes[*].entity` 是闭合对象：

```yaml
entity_kind:
entity_id:
resolution_scope:
```

- `entity_kind`：`base_selection|day|activity|leg`；
- `resolution_scope`：`previous|new|either`，必须由 producer 显式写出；
- `previous`：只在匹配 `previous_plan_id` 的 previous-plan snapshot local definitions 中解析；
- `new`：只在匹配 `new_plan_id` 的 new plan definitions 中解析；
- `either`：允许一侧或两侧存在，但两侧都不存在时失败；
- delete 通常使用 previous、add 通常使用 new、move/update 可以使用 either，但 WU1 不根据 change type 猜 scope；
- 单一被选侧出现多个兼容 local definitions，或无法唯一确定 previous/new version artifact 时使用 `AMBIGUOUS_PLAN_VERSION_ENTITY`；
- 所需侧没有目标时使用 `UNRESOLVED_PLAN_VERSION_ENTITY`。

#### 确定性错误规则

- 同一 artifact 内同一 ID 在 definition paths 中定义两次：所有模式均以 `DUPLICATE_DEFINITION_ID` 硬失败；`CLOSED` bundle 中跨 artifact 的同 kind 或不同 kind 重复定义也硬失败；
- 同一个 ID 在任意数量的 reference fields 中重复：合法；
- reference 没有目标：以 `UNRESOLVED_REFERENCE` 硬失败；
- reference 的目标 kind 与字段声明不兼容：以 `REFERENCE_KIND_MISMATCH` 硬失败；
- 同一 ID 同时被定义为两个不同 kind：以 `DUPLICATE_DEFINITION_ID` 硬失败，并在稳定 `expected` 中写明预期 kind；
- bundle 内两个 artifact envelope 定义相同 `artifact_id`：以 `DUPLICATE_ARTIFACT_ID` 硬失败；
- 同一 fact 内 source ID 重复或本地 source reference 缺失：分别使用 `DUPLICATE_LOCAL_SOURCE_ID`、`UNRESOLVED_LOCAL_SOURCE_REFERENCE`；
- plan-version scoped entity 无目标或不唯一：分别使用 `UNRESOLVED_PLAN_VERSION_ENTITY`、`AMBIGUOUS_PLAN_VERSION_ENTITY`。

重复定义先产生对应 duplicate 错误，reference validator 不得从多个目标中猜一个继续。不存在 duplicate 且 closure 为 `CLOSED` 时，每个 `closed_bundle_required` reference 必须恰好解析到一个兼容定义。八个错误码在 WU1 冻结，不得由第三方库 message 动态替代。

### 5.4 事实来源联合类型

`source` 是带 `source_type` discriminator 的闭合联合类型，按照 WU0 冻结字段实现：

- `webpage|official_notice`：`source_id`、`url`、`publisher`、`retrieved_at`、`excerpt`、`locator` 必填；`published_at` 为带 offset 时间或显式 null，null 时带 absence reason；
- `api_response`：`source_id`、`provider`、`operation`、`retrieved_at`、`request_fingerprint`、`response_locator` 必填；不保存含 key 的完整 URL；
- `direct_observation`：`source_id`、`observer_type`、`observed_at`、`observation`、`location_ref` 必填；不伪造网页字段。

来源不得出现 `llm`、`model` 或无法回读的“knowledge”。用户事实走 `derivation: user_supplied` 和 user input provenance，不伪装成外部 source。所有分支都必须具备稳定 `source_id` 和可审计 locator/hash；不适用字段不得塞入错误分支。

### 5.5 origin 联合类型

约束和用户可编辑值的 `origin` 是闭合联合类型：

- `explicit`：回指 request 中的用户原话 locator；
- `inferred`：回指 `constraint-parse.json` 中的 parse item 与 parser 版本；
- `default`：回指命名规则、规则版本和说明；
- `user_edited`：回指被替换值、编辑时间和编辑 provenance。

该结构只证明来源链完整，不证明语义解析正确。

### 5.6 Constraint target 判别联合

`constraints.payload.constraints[*].target_refs[*]` 是 `target_type` 判别的闭合联合，不能用未来实体占位，也不能扫描 ID 猜分支。

`request_scope` 分支：

```yaml
target_type: request_scope
request_id:
scope_kind:
```

- `scope_kind` 是闭合枚举：`trip|travel_window|party|budget|transport|mobility|destination|must_visit|excluded|day_template`；
- `request_id` 按 §5.3 registry 解析到 request entity definition；
- 旅行级约束在尚无 plan/day/activity 时使用该分支，不得伪造未来 ID；
- `CLOSED` bundle 中 request definition 必须存在。

`entity` 分支：

```yaml
target_type: entity
entity_kind:
entity_id:
```

- `entity_kind` 是闭合枚举：`candidate|plan|day|activity|leg|base_selection`；
- `entity_id` 按 sibling `entity_kind` 解析到兼容 definition；
- replan 约束可以引用旧计划中的 activity/day/base selection；该约束解析/确认 bundle 在新 plan 产生前使用原旧 plan artifact 作为唯一 plan-entity definition 来源，不从 previous snapshot 或未来 new plan 猜版本；
- WU1 只验证 branch、kind 和 reference，不判断约束业务含义。

### 5.7 Evidence subject 判别联合

每个 Evidence fact 的 `subject` 是闭合联合；不再假设所有事实只能挂在单一 candidate 上。

`entity` 分支：

```yaml
subject_type: entity
entity_kind: candidate
entity_id:
```

v0 用于 destination、POI、base-area candidate 及候选自身的开放时间、位置和属性。

`relation` 分支：

```yaml
subject_type: relation
relation_type:
from_candidate_ref:
to_candidate_ref:
mode:
```

- `relation_type`：`route|transfer|service_between`；
- `from_candidate_ref` 与 `to_candidate_ref` 都解析到 candidate definitions，且都必填；
- `mode` 是结构枚举：`driving|walking|transit|cycling|shuttle|rail|other`；
- 路时、距离、换乘和两点间服务使用 relation，不强行挂到一个 candidate；
- relation 是 fact 内部值对象，不创建全局 route entity；
- from/to 有方向，反向 relation 不自动等价；
- WU1 只验证结构和引用，不验证现实路线真实性。

### 5.8 Violations evaluation stage

`violations.json` 增加必填 `evaluation_stage: pre_plan|post_plan`，以 Schema 条件分支冻结 E 阶段与 F 阶段边界。

`pre_plan`：

- 只允许 `plan_status=proven_infeasible`；
- `proofs` 至少一项，且 proof 结构完整；
- `plan_ref` 禁止出现；
- `request_ref`、`constraint_set_ref`、`candidate_set_ref`、`evidence_set_ref` 必填且是完整 artifact references；
- 不允许 `no_plan_found`，也不得用普通 `candidate_conflict_set` 冒充 pre-plan proof；
- 没有确定性 proof 时应继续进入 planner，最终由 `post_plan` violations 表达结果。

`post_plan`：

- `plan_ref` 必填并解析到 plan artifact；
- 可使用四种 plan status；
- `plan_status` 必须与引用 plan payload 的结构状态相等，这是跨工件确定性一致性检查，不证明业务结论正确；
- renderer 只消费 post-plan violations。

裸 `plan_id` 不再作为 violations 权威字段。若未来为展示保留派生 plan ID，必须从 `plan_ref` 确定性生成并校验相等，不能成为第二事实源。

### 5.9 Candidates 完整快照语义

- 阶段 B 和 C 各自产出的 `candidates.json` 都是该阶段的完整、不可变快照，不是 delta。
- C 阶段快照包含当前仍需引用的 destination、base-area 和 POI candidate definitions。
- 非 null `parent_candidate_id` 必须在当前 candidates artifact 内解析；历史 artifact 中存在不算满足。
- planner 的 `CLOSED` bundle 只索引 root 闭包明确要求的 candidate snapshot：plan 使用自身 `candidate_set_ref`，pre-plan violations 使用自身 ref，post-plan violations 跟随 plan ref 后使用 plan 的 ref。
- evidence root 没有 candidate artifact ref 时，只允许恰好一个 snapshot 满足全部 subject refs；多个可满足 snapshot 是不唯一错误。
- 历史 candidate artifacts 只进入 provenance，不得作为 root CLOSED documents 中的额外 artifact 静默存在。
- D 阶段生成新的 `evidence.json`，不得回写旧 candidate artifact 补 `evidence_fact_refs`。

## 6. 十个工件的字段级边界

每个机器工件都使用 §5 envelope、provenance、payload hash 和硬失败规则。下表只列各自 payload 必填核心；未列出的可选字段必须在具体 Schema 中显式声明，不能靠开放对象扩展。

| 工件 | 生产者 → 消费者 | payload 必填 | 可选边界与 WU1 不验证内容 |
|---|---|---|---|
| `request.yaml` | 用户/intake → 约束解析/阶段 B pass-through | `request_id`、`natural_language`、`explicit.origin`、`explicit.travel_window.{start,end,timezone}`、`explicit.party.count`、`explicit.transport_modes`、`explicit.destination.selection_mode`、`explicit.preferences_raw`、`user_input_refs` | destination、budget、mobility、must/excluded、clarifications、locale；不可由 solver 改写 |
| `constraint-parse.json` | 版本化语义解析器 → 用户确认/constraints 生成器 | `request_id`、`request_ref`、`parser.{name,version,kind}`、`parsed_constraints`、`parse_notes`、`needs_confirmation` | 自身完整性只由 envelope `integrity.payload_sha256` 表达；`output_payload_sha256` 是闭合对象中的非法未知字段；每项含 parse/constraint ID、原话/locator、分类、layer、normalized expression、说明和 confirmation |
| `constraints.yaml` | 规范化器/用户编辑 → 环境检查/proof/planner | `constraint_set_id`、`request_ref`、`parse_ref`、`revision`、`constraints`、`user_edit_policy` | 每项含稳定 ID、layer、category、operator、request-scope/entity target 联合、value/unit、`origin.kind`/refs、enabled；它是求解阶段唯一约束 SSOT |
| `candidates.json` | 阶段 B/C/未来基地候选器 → 证据/约束检查/planner | `candidate_set_id`、`request_ref`、`generation_stage`、`candidates`、`rejected_inputs` | 每个 artifact 是完整不可变快照，parent 当前快照内闭合；`poi_discovery`、`destination_pass_through`、`destination_recommendation` 用条件 Schema 区分 |
| `evidence.json` | adapters/标准化/证据映射 → 约束检查/planner/renderer | `evidence_set_id`、`facts`、`mapping_rule_version` | 每个 fact 含 entity/relation subject 联合、field/value/unit、support、derivation、freshness、sources、normalization、display status/rule 和 conflict refs；WU1 不验证路线真实性或五态业务映射 |
| `previous-plan.json` | 已确认旧计划快照 → WU6 重排/diff | `previous_plan_id`、`previous_plan_artifact_ref`、`baseline_constraint_set_id`、`snapshot`、`snapshot_created_at` | snapshot 内 base-selection/day/activity/leg 是 plan-version local definitions；WU1 验证局部唯一和解析，不计算变更代价 |
| `plan.json` | planner → renderer/重排/验收 | `plan_id`、`request_ref`、`constraint_set_ref`、`candidate_set_ref`、`evidence_set_ref`、`plan_status`、`conditions`、`base_selections`、`days`、`excluded_candidates`、`constraint_evaluations`、`objective_breakdown` | 每个 base selection 必有 `base_selection_id`；四态同文档结构条件由 Schema 约束；WU1 不证明行程可行 |
| `plan-diff.json` | WU6 deterministic diff → renderer/review/解释 | `previous_plan_id`、`new_plan_id`、`change_score`、`weights`、`changes`、`unchanged_summary` | change 含 type、结构化 entity(kind/id/resolution_scope)、from/to/cost/reason/constraint_refs；WU1 验证 previous/new/either 解析，不验证成本求和和最优性 |
| `violations.json` | constraint checker/planner → renderer/review/解释 | `evaluation_stage`、`plan_status`、按 stage 条件化的 artifact refs、`violations`、`conditions`、`candidate_conflict_sets`、`proofs` | pre-plan 只表达有 proof 的 proven-infeasible；post-plan 必须引用 plan 且可表达四态；WU1 不验证证明推理正确 |
| `trip-card.html` | WU7 renderer → 人类旅行者 | 文档契约要求工件 metadata、状态、条件、证据回读、每日安排、淘汰项、变更摘要和机器工件引用 | WU1 仅写 `trip-card.contract.md`，不创建 HTML、模板、CSS 或 renderer |

所有 artifact reference 都必须带 artifact type、schema version 和 payload hash；entity、provenance 与 local-scoped reference 按 §5.3 各自结构验证，不强行伪造 artifact hash。`request.yaml` 与 `constraints.yaml` 不可混为同一权威层。v1 能力 A 现在只冻结 `generation_stage`、候选稳定 ID、位置/待解析位置、provenance `source_refs`、候选生成 reason，以及仅对真正 destination recommendation 强制的粗可行性/粗计划 refs；不包含搜索、推荐或排序实现。

## 7. Schema、跨工件验证与业务规则的边界

### 7.1 JSON Schema 能验证

- required、type、enum、const、pattern、format；
- 闭合对象和联合类型分支；
- 同一文档中的 if/then、contains、minItems 和依赖字段存在性；
- constraint target 的 `request_scope|entity` 分支、闭合 scope/entity kind；
- Evidence subject 的 `entity|relation` 分支、relation 必需端点和结构 mode；
- plan-diff entity 的 `base_selection|day|activity|leg` 与 `previous|new|either` 枚举；
- violations 的 `pre_plan|post_plan` 条件字段、plan status、proof 和 plan ref presence；
- `generation_stage` 与 `poi_discovery|destination_pass_through|destination_recommendation` 条件字段的结构匹配；
- estimate derivation 出现时 `estimate` 结构存在；
- `proven_infeasible` 出现时至少存在一个 proof reference；
- `conditionally_feasible` 出现时至少存在一个明确 condition；
- `feasible` 不携带未满足 condition；
- `no_plan_found` 不携带“已证明无解”的 proof 结构。

父级条件不能可靠地由 item 子 Schema 反查，因此 candidate stage 的条件必须在包含 items 的父级使用 `if/then` 专门化，不能把跨层判断写成无效的 item 条件。

### 7.2 WU1 确定性跨工件验证器能验证

`validate_artifact` 与 `validate_bundle` 是两个不同强度的入口：

#### 单工件验证

`validate_artifact` 只验证：

- 严格 JSON/YAML/UTF-8 加载；
- Schema、format 和 schema major；
- canonical payload hash；
- 当前 artifact definition 及其 definition paths 的局部唯一性；
- candidate parent、derivation input fact、proof、Evidence local source 和 previous-plan snapshot local definitions 等明确要求在同一 artifact 内闭合的结构引用；
- provenance locator 的自身 Schema。

它不得因未来阶段的 artifact/entity 尚未存在而失败，也不得搜索磁盘补目标。跨工件 reference 在单工件验证中属于“本入口不执行”，不是 warning、成功 fallback 或已验证 closed。

#### Bundle 验证

`validate_bundle` 必须由调用者显式传入 §10.1 的 `BundleClosure` 和 `root_artifact_id`。处理顺序固定：

1. 独立验证所有 documents；
2. 建立 artifact definition index；任何重复 artifact ID 先报 `DUPLICATE_ARTIFACT_ID`；
3. `root_artifact_id` 必须恰好命中一个 definition，否则报 `UNRESOLVED_BUNDLE_ROOT`；
4. 按 closure 模式继续。

- `ARTIFACT_ONLY`：对每个 artifact 执行独立验证、记录 root 和所有已验证 artifact IDs；entity definition 唯一性只在各自 artifact 内执行。未来阶段目标缺失不产生 problem，也不产生 warning；不得声称 documents 已形成 closed closure。
- `CLOSED`：root 是本次阶段输出或验证主工件。从 root 开始，只沿显式 registry 的 artifact/entity/local-scoped references 做确定性可达闭包；在单工件检查之外验证闭包内 entity definition 唯一性，所有 `closed_bundle_required` references 必须恰好解析到兼容 definition。

CLOSED 的闭包计算使用确定性 fixpoint：

1. reachable 初始只含 root；
2. 加入 reachable artifacts 的必需 artifact-reference 目标；
3. 为解析 reachable artifacts 的 required entity/local-scoped references，加入恰好拥有兼容 definition 的 artifact；
4. 重复 2—3 直到不再新增；
5. 任一 required reference 缺失、kind 不兼容或不唯一时使用既有稳定错误码硬失败；
6. `documents - reachable` 非空时，每个额外 artifact 以 `UNEXPECTED_BUNDLE_ARTIFACT` 硬失败。

“额外 artifact”只能根据上述可达结果判断：root 自身、被 root 直接/间接引用的 artifact、或解析 root 所需 entity/local reference 的 artifact 才属于闭包。不得用文件名、artifact type、created_at、所谓“最新”或目录位置判断，也不得静默忽略历史 snapshot、旧 candidate artifact 或其他 plan。

两种模式都验证 Schema registry、本地 `$ref`、严格加载、payload hash、单工件 definition 唯一性、局部 source scope、fixture 内嵌 bytes/hash、安全相对路径及 dirty expected error。两种模式都不允许默认或推断 root/closure、扫描目录补文件或通过 warning 降级。

`constraint-parse.payload.parsed_constraints[*].constraint_id` 在 `validate_artifact`/`ARTIFACT_ONLY` 中不因 `constraints.yaml` 尚未提供而失败；在包含 request、constraint-parse 和 constraints 完整闭包的 `CLOSED` 中，必须解析到恰好一个 `/payload/constraints[*]/constraint_id` definition。

此外，`CLOSED` 执行以下确定性结构检查：

- request-scope target 的 request ID 与 entity target 的 sibling kind 引用；
- relation subject 两个有方向的 candidate endpoint；
- plan-diff entity 按显式 previous/new/either scope 解析，previous snapshot local definition 与 new plan definition 不互相造成 global duplicate；
- pre-plan violations 的四个输入 artifact refs，或 post-plan violations 的 plan ref；
- post-plan `plan_status` 与被引用 plan payload 的结构值相等；
- planner bundle 只含 root 引用链明确指定的 candidate snapshot，且其 parent refs 在同一 snapshot 内闭合。

#### Root-specific CLOSED 语义

- Root 为 `plan`：其 `candidate_set_ref` 唯一决定 candidate snapshot；其他 candidate artifacts 是额外 artifacts。
- Root 为 post-plan `violations`：先跟随 `plan_ref`，再由 plan 的 `candidate_set_ref` 决定 snapshot。
- Root 为 pre-plan `violations`：`request_ref`、`constraint_set_ref`、`candidate_set_ref`、`evidence_set_ref` 共同定义闭包。
- Root 为 `plan-diff`：`previous_plan_id` 必须匹配一个 previous-plan snapshot version identity，`new_plan_id` 匹配一个 new plan definition；changes 按显式 previous/new/either 解析。
- Root 为 `evidence`：entity/relation subjects 所需 candidate definitions 必须由 documents 中唯一可满足这些 refs 的 candidate snapshot 提供；多个 snapshot 都能满足时硬失败，不选择 created_at 最新者。
- Root 为 `constraint-parse`：跟随 `request_ref`，并因 stable constraint ID 被注册为 closed-required 而提供最终 constraints definitions；parser 刚产出、尚未生成 constraints 时只能使用 `ARTIFACT_ONLY`，不得提前宣称 CLOSED。
- Root 为 `constraints`：跟随 `request_ref`、`parse_ref` 及实际 entity targets；尚不存在的未来 target 不得出现在声称 CLOSED 的 bundle，除非兼容 definition 已实际提供。

### 7.3 WU1 明确不验证的业务语义

- 证据是否真的支持事实、外部五态映射是否保守；
- freshness 是否符合现实来源有效期；
- API estimate 的保守边是否满足通勤硬约束；
- `change_score` 是否等于配置权重总和、是否为最小改变；
- `plan.json` 和 `violations.json` 的业务结论是否正确；WU1 只检查 post-plan status 字段结构相等，不证明该状态成立；
- proof 是否构成完备证明、candidate conflict set 是否合理；
- 计划是否现实可走、路线是否最优或 HTML 是否正确渲染。

这些分别延后至 WU3、WU4、WU5、WU6、WU7 和 WU8。不得把 Schema 通过描述成业务验收通过。

## 8. 四态可行性与冲突结构

Schema 中冻结：

| 状态 | 结构门槛 | 面向用户的允许表达 |
|---|---|---|
| `feasible` | 已有 plan days；conditions 为空；不能携带 unresolved critical fact 声明 | “已找到满足已知硬约束的方案” |
| `conditionally_feasible` | 已有结构方案；conditions 至少一项，每项回指 fact/constraint | “方案在以下条件成立时可行” |
| `proven_infeasible` | 至少一个确定性 proof；proof 有规则 ID、输入 refs、边界值和可复算结果 | “以下确定性冲突已被证明” |
| `no_plan_found` | 无已接受方案；不得附带 proven-infeasible proof | “当前算法未找到满足条件的方案，不代表无解” |

`unknown/conflicting` 只能通过 fact reference 进入 condition 或 violation，不得在 Schema 默认消失。WU1 只验证引用和结构，不计算传播结果。

v0 可在后续 WU4 证明的类型先冻结枚举：must/excluded 同一实体、活动时长下界超总时间、最早到达晚于明确闭馆、交通与活动下界超日窗、不换酒店与确定通勤上限矛盾。其他非完备启发式结果只能使用 `candidate_conflict_set`；未完成真正最小化时禁止 `minimal_conflict_set` 字段。

## 9. Fixture 设计

### 9.1 Manifest 和精确字节

每个 `case.json` 是 fixture manifest，不额外创建白名单外工件文件。它内嵌：

```text
case_id
case_version
fixture_type
bundle_closure
root_artifact_id
source
coverage
non_coverage
documents[]
dirty_cases[]
behavior_expected
```

`bundle_closure` 是必填枚举 `artifact_only|closed`；`root_artifact_id` 是必填 artifact ID。`validate_fixture_manifest` 必须将两者逐项显式传给 `validate_bundle`，不得使用 documents 第一项、文件名或 artifact type 推断。root 必须与 `documents[]` 中恰好一个真实 envelope artifact ID 相等。

六个 C7 正式 fixture 全部固定为 `closed`，其 documents 只需构成 root 实际引用所需的最小完整闭包，不机械包含全部九个机器工件。C5/C6 的人工最小 manifest 必须分别覆盖 `artifact_only` 与 `closed`，以及 root 存在、缺失、非法和顺序无关。

`documents[]` 至少包含：

- `relative_path`
- `media_type`
- `content_utf8`
- `file_sha256`
- `expected_schema_id`

内嵌文本固定 UTF-8、无 BOM、LF。`file_sha256` 必须由命令从精确 bytes 计算，不得手写或由被测验证器反喂 expected。fixture validator 在内存中解析这些 bytes，不向工作树生成临时工件。

`dirty_cases[]` 是对 clean 文档的确定性 mutation：

```text
dirty_case_id
target_document
operation
json_pointer
value（按 operation 可选）
expected_error
```

`expected_error` 预注册 `error_code`、`json_pointer`、`schema_rule`。dirty case 必须从合法 clean 输入经单一 mutation 产生；每 case 只验证一个独立结构行为。畸形 JSON/YAML、import 失败、路径缺失或未装依赖都不能作为 red。

`behavior_expected` 保留后续 WU3—WU6 的人工 spec，但 WU1 将其作为不透明、只做外壳验证的数据，不执行也不宣称行为通过。

### 9.2 六个 fixture

| Fixture | Root artifact type | 类型与来源 | WU1 clean 预期 | 单一 dirty 断言 | 行为层延后 |
|---|---|---|---|---|---|
| `fixture_01_feasible` | post-plan `violations` | 合成确定性；WU0 契约 | request-scope constraint；relation route estimate；plan/violations 闭包合法 | `api_estimate` 删除 estimate 后 schema error | WU4/WU5 才判断真实可行 |
| `fixture_02_direct_conflict` | pre-plan `violations` | 合成确定性；直接矛盾 spec | `proven_infeasible` 带 proof、四个输入 refs、无 plan ref | 删除 proof 后必须拒绝 | WU4 才复算证明 |
| `fixture_03_uncertain_dependency` | post-plan `violations` | 合成确定性；证据条件 spec | conditional plan、conditions、plan ref 完整 | 删除 conditions 后必须拒绝 | WU3/WU4 才传播 unknown/conflicting |
| `fixture_04_replan_stability` | `plan-diff` | 合成确定性；v3.1 diff spec | previous snapshot、new plan 与显式 version scope 完整 | 删除 `resolution_scope` 后必须拒绝 | WU6 才计算 score 和稳定性 |
| `fixture_05_evidence_state_mapping` | `evidence` | 合成确定性；正交证据 spec | entity subject 与 source/derivation/freshness 分离；candidate snapshot 唯一 | model 作为 source discriminator 时拒绝 | WU3 才测试确定性五态映射 |
| `fixture_06_no_plan_found_not_infeasible` | post-plan `violations` | 合成确定性；状态边界 spec | no-plan-found、plan ref 完整且无 proven proof | 删除 `plan_ref` 后必须拒绝 | WU4/WU5 才验证算法未找到与无解区别 |

每个 case 的 `root_artifact_id` 必须等于上表 root 类型文档的实际 envelope ID，不得只写类型名。每个 README 必须写明 root、来源、为什么允许合成、最小闭包、覆盖/不覆盖、`bundle_closure: closed`、clean/dirty 和行为层分界。江西真实 fixture 不在 WU1 创建，不能由 AI 捏造。

## 10. 验证接口、错误对象和退出码

### 10.1 最小公开 Python 接口

C1 在两个 validation 模块中创建以下可导入接口；函数名、输入类别和成功/失败边界在本 Plan 冻结，不冻结内部类层次或算法：

```python
# src/trip_decider/schema_validation.py
load_document(
    path: pathlib.Path,
    *,
    expected_artifact_type: str | None = None,
) -> ValidationResult[LoadedDocument]

validate_schema_registry(
    schema_paths: collections.abc.Sequence[pathlib.Path],
) -> ValidationResult[SchemaRegistry]

validate_artifact(
    document: LoadedDocument,
    registry: SchemaRegistry,
) -> ValidationResult[ValidatedArtifact]

validate_bundle(
    documents: collections.abc.Sequence[LoadedDocument],
    registry: SchemaRegistry,
    *,
    closure: BundleClosure,
    root_artifact_id: str,
) -> ValidationResult[ValidatedBundle]

# src/trip_decider/fixture_validation.py
validate_fixture_manifest(
    manifest: collections.abc.Mapping[str, object],
    registry: SchemaRegistry,
) -> ValidationResult[ValidatedFixtureManifest]

validate_fixture_directory(
    root: pathlib.Path,
    registry: SchemaRegistry,
) -> ValidationResult[FixtureDirectorySummary]
```

`BundleClosure` 是公开输入语义，至少冻结两个值：

```python
BundleClosure.ARTIFACT_ONLY
BundleClosure.CLOSED
```

具体实现可采用 Enum、Literal 或不可变值对象，但调用者必须显式传入 `closure` 和 `root_artifact_id`，两者都没有默认值。`validate_fixture_manifest` 从 manifest 的两个必填字段确定性读取并逐项传入。

`ValidatedBundle` 至少记录：

```text
closure
root_artifact_id
validated_artifact_ids
resolved_artifact_ids
```

`validated_artifact_ids` 是所有已完成单工件验证的 documents；`resolved_artifact_ids` 在 CLOSED 中是 root 可达闭包，在 ARTIFACT_ONLY 中不得被描述为完整闭包。

稳定返回边界：

- `ValidationResult[T]` 暴露 `value: T | None` 与按稳定顺序排列的 `problems: tuple[ValidationProblem, ...]`；`problems` 为空才是成功。
- `ValidationProblem` 正是 §10.3 的七字段机器问题对象；不得额外携带原始异常、输入值或 secret。
- `load_document` 的路径、读取、UTF-8 和 parse 失败返回输入问题；artifact type、Schema、hash、引用、manifest 或 fixture 违规返回对应结构问题。
- `validate_schema_registry` 的非法 Schema 或重复 `$id` 返回结构问题；必要 FormatChecker 未注册、registry 自身不一致等执行前提破坏抛出项目自有 `ValidatorInternalError`。
- `validate_artifact` 执行 §7.2 的单工件边界；没有未来阶段目标不属于该入口的结构错误。
- `validate_bundle` 不得默认 closure/root、选择第一个 document、按 artifact type 或 created_at 猜 root/最新版本、搜索磁盘补目标，或把一个模式的结果冒充另一个模式。
- `ARTIFACT_ONLY` 中未解析的未来引用表示“本模式不执行跨工件闭包检查”，不进入 `problems`，也不产生 warning 成功通道；返回值必须明确记录实际 closure。
- `CLOSED` 中任何 required reference 未解析、重复或 kind 不兼容都进入 `problems`；任何 root 不可达额外 artifact 也必须失败，不得忽略。
- `CLOSED` 的 plan-version resolver 必须接收 manifest/bundle 中明确的 previous-plan 与 new-plan 文档关系；不得从 change type、文件名或 ID 相似度猜 previous/new/either。
- `CLOSED` 的 candidate resolver 只索引本次求解指定的一个最新完整 snapshot；历史 candidate artifacts 只作为 provenance。
- 只有验证器内部不变量、必要能力缺失或不可安全归类的第三方故障可以抛 `ValidatorInternalError`；异常 message 必须由项目固定模板生成。
- 第三方 `jsonschema`、PyYAML、I/O 或解析异常不得直接穿透为公共异常或直接复制进问题对象。
- C1 的六个函数均可导入并明确抛 `NotImplementedError`，只用于有效 red 前的接口态。
- C4 完成后，前四个 schema/artifact 接口不得再有 `NotImplementedError`；后两个 fixture 接口保持 C1 的显式 red 状态。
- C6 完成后，六个公开接口均不得存在可达的 `NotImplementedError`；C7 不再修改接口或实现。

### 10.2 最终完整验证入口（C7 起）

独立复核入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu1.ps1
```

`verify_wu1.ps1` 由 C7 与六个正式 fixture 同时创建。C1—C6 不运行、也不以该完整脚本制造 red/green 证据。

脚本必须：

1. 使用项目 `.venv` 中的 Python，不回退到全局 Python；
2. 确认解释器路径严格位于项目 `.venv`；
3. 校验 lock 安装状态；
4. 校验所有 Schema metadata/registry；
5. 运行标准库 unittest discovery；
6. 对六个 fixture 运行显式 closure/root、root 可达闭包和 clean/dirty manifest 验证；
7. 执行 scope、可疑 fallback、secret、冻结 hash 检查；
8. 任一步失败即非零退出，不隐藏失败。

该脚本在 C7 首次运行且必须 green；C8 使用完全相同命令再次运行并记录 Review 证据。

### 10.3 错误输出

机器错误以 JSON Lines 写入 stderr，按 `artifact_path`、`json_pointer`、`error_code` 确定性排序。每条对象字段固定为：

```json
{
  "error_code": "",
  "artifact_path": "",
  "json_pointer": "",
  "schema_rule": "",
  "expected": "",
  "actual_type": "",
  "message": ""
}
```

约束：

- 七个字段全部存在；无关值使用稳定空字符串，不省略字段。
- `actual_type` 只输出安全类型名，不输出实际值。
- `message` 使用项目自有稳定模板，不原样回显第三方异常或输入内容。
- JSON pointer 按 RFC 6901 转义；根使用空字符串。
- 多错误的排序和首个退出码确定性固定；不得依赖 dict、文件系统或库的偶然顺序。

稳定退出码：

| 退出码 | 含义 |
|---:|---|
| 0 | 全部验证通过 |
| 2 | 工件/Schema/版本/hash/引用结构违规 |
| 3 | fixture manifest、mutation 或预期错误不一致 |
| 4 | 输入读取、路径、UTF-8、JSON/YAML 解析错误 |
| 5 | 验证器内部错误、Schema registry 错误或必要 format checker 缺失 |

warning 不能替代失败；验证器不提供 `--lenient`、自动修复或 fallback 模式。

`DUPLICATE_DEFINITION_ID`、`UNRESOLVED_REFERENCE`、`REFERENCE_KIND_MISMATCH`、`DUPLICATE_ARTIFACT_ID`、`DUPLICATE_LOCAL_SOURCE_ID`、`UNRESOLVED_LOCAL_SOURCE_REFERENCE`、`UNRESOLVED_PLAN_VERSION_ENTITY`、`AMBIGUOUS_PLAN_VERSION_ENTITY`、`UNRESOLVED_BUNDLE_ROOT`、`UNEXPECTED_BUNDLE_ARTIFACT` 是退出码 2 下的稳定 `error_code`。它们的含义按 §5.3/§7.2 冻结，不能合并成模糊的 `invalid data`。

## 11. Red → Green 纪律

两组真实 red/green：

### 11.1 Schema red/green

- C2 先提供可解析、可加载、明确标注为接口态的 Schema 壳，不宣称契约完整。
- C3 添加对 required、未知字段、format、major、hash、引用、联合分支和条件结构的具体测试。
- C3 的引用与闭包测试至少逐项覆盖：

  1. 同一 candidate ID 作为多个 entity reference 重复出现，验证为合法；
  2. 同一 candidate ID 在 definition paths 定义两次，得到 `DUPLICATE_DEFINITION_ID`；
  3. `ARTIFACT_ONLY` 下缺少未来阶段 entity，不因未解析而失败且无 warning；
  4. `CLOSED` 下同一缺失 entity 得到 `UNRESOLVED_REFERENCE`；
  5. candidate `source_refs` 只走 provenance Schema，不进入 entity resolver；
  6. 同一 source ID 在同一 fact 内重复，得到 `DUPLICATE_LOCAL_SOURCE_ID`；
  7. 同一 source ID 在两个不同 fact 内出现，验证为合法；
  8. `conflict_source_refs` 只解析当前 fact，跨 fact 同名或缺失得到 `UNRESOLVED_LOCAL_SOURCE_REFERENCE`；
  9. constraint-parse 的 constraint ID 在 `CLOSED` request/parse/constraints bundle 中解析到 constraints definition，且不构成重复定义；
  10. provenance locator 在 bundle 中没有同名 entity 时仍按自身 Schema 合法。

v0.4 再预注册 23 个不重复的领域契约 case，使本节明确列出的最小 case 总数为 33。分类如下：

- Constraint target，2 个：
  - `CT-01`：request-scope target 在无 plan/day/activity 的 `CLOSED` bundle 中解析到 request；
  - `CT-02`：entity target 按 sibling `entity_kind` 解析到兼容旧计划或候选实体。
- Evidence subject，5 个：
  - `ES-01`：candidate entity subject 合法；
  - `ES-02`：relation subject 的两个 candidate endpoint 都存在时合法；
  - `ES-03`：relation 缺 from 或 to 时 Schema 失败；
  - `ES-04`：`CLOSED` 中任一 endpoint 缺失时得到 `UNRESOLVED_REFERENCE`；
  - `ES-05`：`ARTIFACT_ONLY` 未提供外部 candidates artifact 时不执行闭包检查。
- Plan-version entity resolution，7 个：
  - `PV-01`：plan base selection 有正式 `base_selection_id` definition；
  - `PV-02`：previous-only 删除目标解析到 snapshot local definition；
  - `PV-03`：new-only 新增目标解析到 new plan definition；
  - `PV-04`：previous 目标不存在时得到 `UNRESOLVED_PLAN_VERSION_ENTITY`；
  - `PV-05`：new 目标不存在时得到同一稳定错误；
  - `PV-06`：either 两侧都不存在时失败；
  - `PV-07`：previous snapshot 与 new plan 同 ID 合法，不触发 global duplicate。
- Violations stage，6 个：
  - `VS-01`：pre-plan proven-infeasible、有 proof、无 plan ref 合法；
  - `VS-02`：pre-plan 无 proof 时 Schema 失败；
  - `VS-03`：pre-plan 使用 no-plan-found 时 Schema 失败；
  - `VS-04`：post-plan 缺 plan ref 时 Schema 失败；
  - `VS-05`：post-plan plan ref 在 `CLOSED` 中缺目标时失败；
  - `VS-06`：post-plan plan ref 的类型/hash 匹配且 status 结构一致时合法。
- Candidates snapshot，4 项覆盖、净新增 3 个 case：
  - `CS-01`：parent candidate 在当前 snapshot 中存在时合法；
  - `CS-02`：parent 只存在于未提供的历史 artifact 时失败；
  - 同一 snapshot 重复 candidate definition 由基础 case 2 覆盖，不新增 case；
  - `CS-03`：planner `CLOSED` bundle 只索引 root 引用链明确指定的 candidate snapshot。

v0.5 再增加 14 个不重复 case，与上述 33 个并存，使 §11.1 最小明确 case 总数为 47：

- Constraint-parse hash authority，4 个：
  - `HASH-01`：payload 没有 `output_payload_sha256` 时合法；
  - `HASH-02`：出现 `output_payload_sha256` 时因闭合对象未知字段失败；
  - `HASH-03`：envelope `integrity.payload_sha256` 不匹配仍以既有 integrity 错误硬失败；
  - `HASH-04`：constraints `parse_ref.payload_sha256` 解析到 constraint-parse envelope hash。
- Explicit bundle root，10 个：
  - `ROOT-01`：root artifact 存在且唯一时合法；
  - `ROOT-02`：root 不存在时得到 `UNRESOLVED_BUNDLE_ROOT`；
  - `ROOT-03`：root ID 对应重复 artifact 时先得到 `DUPLICATE_ARTIFACT_ID`；
  - `ROOT-04`：CLOSED 中存在 root 不可达 artifact 时得到 `UNEXPECTED_BUNDLE_ARTIFACT`；
  - `ROOT-05`：ARTIFACT_ONLY 记录 root，但不要求引用闭包；
  - `ROOT-06`：post-plan violations root 只使用其 plan ref 最终指定的 candidate snapshot；
  - `ROOT-07`：额外历史 candidate snapshot 不能被静默忽略；
  - `ROOT-08`：plan-diff root 确定 previous snapshot 与 new plan version；
  - `ROOT-09`：fixture manifest 缺 `root_artifact_id` 时 Schema 失败；
  - `ROOT-10`：fixture manifest 改变 documents 顺序不改变 root，validator 不选择第一项。

- C3 红灯必须因为 importable validator 接口显式未实现或接口 Schema 错误接受合法 dirty case；不能因为文件/模块/依赖缺失。
- C3 运行且只以以下命令记录 schema red：

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.test_schema_validation -v
  ```

- 记录命令、exit code、失败 test ID 和错误摘要。
- C4 只实现使 C3 预注册行为通过的严格 validator/Schema，不顺便增加业务规则。
- C4 使用逐字符相同的上述命令得到 schema green；记录实际 case 数和 pass/fail。
- C3/C4 不调用 `verify_wu1.ps1`，不读取尚未创建的正式 fixture。

### 11.2 Fixture red/green

- C5 添加 manifest、精确 bytes/hash、安全相对路径、single mutation 和 expected error 匹配测试。
- C5 测试使用测试代码中人工写定的最小 manifest，或 `tempfile.TemporaryDirectory` 创建的临时测试树；临时文件不得写入 Git 工作树，也不得依赖 C7 才创建的六个正式 fixture。
- C5/C6 的最小 manifest 同时覆盖 `bundle_closure: artifact_only|closed` 和显式 `root_artifact_id`，并断言两个值逐项传入 `validate_bundle`；缺字段、非法枚举、root 不存在或 documents 顺序推断均失败。
- C5 运行且只以以下命令记录 fixture-validator red：

  ```powershell
  .\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation -v
  ```

- C5 必须显示既有 schema tests 继续 green，新增 fixture tests 只因 importable fixture 接口显式未实现或具体断言失败而 red。
- C6 使用逐字符相同的上述命令全部转 green；此时六个公开接口均不得留下可达的 `NotImplementedError`。
- C5/C6 不调用 `verify_wu1.ps1`，不要求正式 fixture 目录存在。
- C7 才加入六个 `bundle_closure: closed` 正式 fixture spec 和完整验证入口；它只增加数据与脚本，不新增 validator 行为。
- C7 运行完整脚本并必须 green。若正式 fixture 暴露实现、Schema 或既有测试缺口，立即停止并报告 Plan 需要调整；不得在 C7 顺手修改 validator、Schema 或测试。

禁止：

- 用被测函数输出生成 expected；
- 只断言 `is not None`、`len > 0`、包含某字符串或退出码非零；
- 让一个 dirty case 同时破坏多个独立规则；
- 修改测试来迎合实现；
- 把 fixture behavior_expected 当作 WU1 已验证行为。

## 12. Commit 序列

获批后在线性 `main` 现状上执行，不创建远端、不 push。每个 commit 前后运行该阶段规定命令；C3 和 C5 的预期红灯是唯一允许提交时测试非绿的中间态，并须在下一实现 commit 转绿。

### C0 — `docs: record approved Work Unit 1 plan`

- 文件：仅 `plans/work-unit-1-contracts-fixtures.md`
- 职责：记录获批 Plan 原文及 hash，作为执行基线
- 前置：收到语义明确批准；输入/handbook hash 不变
- 验证：`git diff --check`、Plan 状态/章节/36 文件/20 条判定计数、保护文件 hash
- 完成：仅 Plan 被提交；之后禁止修改

### C1 — `chore: add WU1 dependency and importable validation interfaces`

- 文件：`pyproject.toml`、`requirements.lock`、`src/trip_decider/__init__.py`、`src/trip_decider/schema_validation.py`、`src/trip_decider/fixture_validation.py`
- 职责：建立最小依赖、干净环境、公开 `BundleClosure` 语义和 §10.1 六个稳定、可导入、显式未实现的公开接口；不创建最终验证脚本
- 前置：C0；许可证逐项核实
- 验证：干净 `.venv` 生成 lock、删除重建后 lock replay；两个模块、`BundleClosure` 及六个函数可导入；接口调用显式 `NotImplementedError`；无全局 freeze
- 完成：环境可重放，尚无契约通过声明

### C2 — `chore: add loadable schema contract interfaces`

- 文件：`schemas/common.schema.json`、`schemas/fixture-case.schema.json`、九个工件 Schema、`schemas/trip-card.contract.md`
- 职责：让全部 Schema 路径、Draft metadata、唯一 `$id`、本地 `$ref`、四个领域判别联合，以及 fixture manifest 的必填 closure/root 可加载；constraint-parse 不含自引用 output hash；接口壳保持最小且标注未完成
- 前置：C1
- 验证：JSON 可解析、Draft 2020-12 schema check、`$id` 唯一、无远程 ref 获取
- 完成：所有接口可加载，不把 permissive 壳描述为已冻结业务契约

### C3 — `test: add failing artifact schema contract cases`

- 文件：`tests/__init__.py`、`tests/test_schema_validation.py`
- 职责：先固定 strict parsing、单一 envelope hash、显式 bundle root、root 可达闭包、constraint target、Evidence subject、plan-version、violations stage、candidate snapshot、reference registry、closure 和错误模型
- 前置：C2；所有被测路径与依赖存在
- 验证：运行 `.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation -v`，预期非零；基础加载测试通过，预注册 contract tests 因公开接口 `NotImplementedError` 或具体契约缺口失败
- 完成：保留可复核 red 证据；失败不是语法/import/缺依赖

### C4 — `feat: implement strict artifact schema validation`

- 文件：`src/trip_decider/schema_validation.py`、C2 的 Schema 文件
- 职责：仅实现 C3 所需的结构、单一 hash 权威、显式 root、CLOSED 可达/额外 artifact、definition/reference registry、fact-local/plan-version scope、pre/post-plan、candidate snapshot 和机器错误验证
- 前置：C3 red 证据
- 验证：运行逐字符相同的 `.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation -v` 转 green；格式检查器启动自检；dirty 输入得到精确错误
- 完成：C3 全部通过；前四个公开接口无 `NotImplementedError`；无业务判断

### C5 — `test: add failing fixture validation cases`

- 文件：`tests/test_fixture_validation.py`
- 职责：用代码内最小 manifest 或 `tempfile.TemporaryDirectory` 先固定自动发现、必填 closure/root、逐项参数传递、manifest、bytes/hash、安全路径、single mutation 和 expected error matching，不依赖正式 fixture
- 前置：C4 全绿；fixture validation 接口可导入
- 验证：运行 `.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation -v`，预期非零；既有 schema tests 保持 green，新增 fixture tests 因公开接口 `NotImplementedError` 或具体断言失败
- 完成：保留第二组可复核 red 证据

### C6 — `feat: implement strict fixture validation`

- 文件：`src/trip_decider/fixture_validation.py`
- 职责：仅实现 C5 的确定性 fixture 验证，包括 closure/root 原样传给 `validate_bundle`
- 前置：C5 red 证据
- 验证：运行逐字符相同的 `.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation -v` 转 green；manifest/bytes/hash/path/mutation/expectation 的具体断言通过
- 完成：C5 全部通过；六个公开接口均无可达 `NotImplementedError`；不执行 behavior layer

### C7 — `test: add six structured fixtures and full verification entry`

- 文件：`fixtures/README.md`、六个 fixture 的 12 个 README/case 路径、`scripts/verify_wu1.ps1`
- 职责：只落下六套显式 root、`bundle_closure: closed`、各自最小 root 可达闭包的人工 spec、clean/dirty 对、行为预期和最终入口；不新增 validator 行为
- 前置：C6 全绿
- 验证：首次运行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu1.ps1` 并必须 green；准确报告 fixture、document、dirty case 和 unittest case 数
- 完成：六个 fixture 均被自动发现且结构通过；C7 diff 未修改 validator 源码、既有 Schema 或测试；行为层仍明确未执行
- 停止条件：正式 fixture 暴露任何实现/Schema/测试缺口时停止并报告，不得在 C7 修补

### C8 — `docs: prepare Work Unit 1 review evidence`

- 文件：仅 `docs/reviews/work-unit-1-review.md`
- 职责：汇总 Git、依赖/license、red/green、测试、hash、scope、R10 与完成判定
- 前置：C7 全绿
- 验证：再次运行逐字符相同的 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu1.ps1` 并通过；Git diff/文件计数/secret scan/冻结 hash/handbook 状态可复核
- 完成：Review 给出且只给出 `READY_FOR_HUGIN_REVIEW`、`BLOCKED` 或 `INCOMPLETE`
- 禁止：C8 不得修改实现、Schema、fixture 或测试

不得 squash、改写已记录 red commit、混合测试与实现职责，或在 C8 后开始 WU2。

## 13. 验证命令计划

Execute 中以实际环境为准记录每条 exit code，至少运行：

C3 与 C4 的唯一 red/green 命令（两阶段逐字符相同）：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation -v
```

C5 与 C6 的唯一 red/green 命令（两阶段逐字符相同）：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation -v
```

C7 首次、C8 再次使用的完整验证命令（逐字符相同）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu1.ps1
```

`verify_wu1.ps1` 内部从 C7 起运行完整 unittest discovery 和六个正式 fixture；C1—C6 不得调用它。C5/C6 的 fixture tests 只使用测试代码内的最小 manifest 或系统临时目录。

各 commit 的 Git 检查和 C8 Review 证据：

```powershell
git status --short
git diff --check
git log --oneline --decorate <WU1起点>..HEAD
git diff --stat <WU1起点>..HEAD
git diff <WU1起点>..HEAD

Get-FileHash .\PLAN.md -Algorithm SHA256
Get-FileHash .\plans\work-unit-0-bootstrap-d0.md -Algorithm SHA256
Get-FileHash .\plans\work-unit-1-contracts-fixtures.md -Algorithm SHA256

git -C '<handbook>' rev-parse HEAD
git -C '<handbook>' rev-parse origin/main
git -C '<handbook>' status --short
```

还须以脚本或命令产生：

- direct/transitive dependency 数量和许可证清单；
- Schema 文件数、唯一 `$id` 数和本地 refs 数；
- unittest 实际 case 数、pass/fail；
- fixture 目录、document、clean 和 dirty case 数；
- Git tracked 文件数和白名单外变更数；
- suspicious name、silent fallback、secret pattern 命中数；
- `PLAN.md`、WU0 Plan、handbook HEAD/工作树前后对比。

所有数字进入 Review 时必须来自命令输出，不得从本文估算。

## 14. 预注册的 20 条完成判定

Review 必须逐条使用 `✓ 已完成`、`⚠ 已知限制` 或 `✗ 未完成` 对照，不能增删或合并：

1. 获批 WU1 Plan 由 C0 单独提交，Plan hash 留痕且 C0 后未修改。
2. Python 目标、直接依赖版本、官方许可证、Windows/Python 3.11 兼容性均被实际核实。
3. lock 从干净项目 `.venv` 产生并在重建环境中重放成功，未使用全局 `pip freeze`。
4. 九个机器工件 Schema 和一个 trip-card 契约全部存在；constraint-parse 只使用 envelope payload hash，`output_payload_sha256` 被闭合 Schema 拒绝。
5. 通用 envelope、canonical payload hash、unknown-major 和 hash mismatch 硬失败已实现；request→parse→constraints 只通过完整 request/parse artifact refs 追踪。
6. source 闭合联合类型已实现；LLM 不能作为事实来源，candidate `source_refs` 只作为 provenance，Evidence source ID 按 `(fact_id, source_id)` 局部唯一且不伪装成全局 entity。
7. origin 闭合联合及 constraint target 的 `request_scope|entity` 联合已实现；scope/entity kind 闭合，旅行级约束不伪造未来 plan entity。
8. Evidence `entity|relation` subject、candidate generation/完整不可变快照、estimate、proof presence 和四态 plan status 的结构条件已实现。
9. 严格 JSON/YAML/UTF-8/format 验证、稳定错误对象和退出码已实现；`ARTIFACT_ONLY` 的未执行检查不产生 warning，`CLOSED` 的未解析引用不能通过。
10. plan-version resolution 已实现；`validate_bundle` 要求显式 closure/root，ARTIFACT_ONLY 记录 root，CLOSED 只接受 root 可达闭包并拒绝额外 artifact，十个稳定引用/root 错误码按 §5.3/§7.2 输出。
11. violations stage、post-plan status 一致性、`BundleClosure`、完整 root-aware `validate_bundle` 与 `ValidatedBundle` 字段均已实现；C6 green 后六个公开接口无可达 `NotImplementedError`。
12. 六个 fixture 及 README/case 均声明 `bundle_closure: closed` 和固定 root、提供 case 所需最小 root 可达闭包；完整入口在 C7 同时创建且未修改 validator、既有 Schema 或测试。
13. 每个 fixture 至少一组 clean/dirty 结构对，dirty case 命中预注册 code/pointer/rule。
14. behavior_expected 已与结构 expected 分开保存，WU1 未执行或宣称后续业务行为通过。
15. Schema tests 使用固定命令取得有效 red/green；至少执行 §11.1 的 47 个明确 case，覆盖单一 hash 权威、显式 root、额外 artifact、两种 closure 及原领域契约，且未调用完整脚本。
16. Fixture tests 使用固定命令和代码内/临时 manifest 取得有效 red/green；两种 closure、显式 root、root 缺失及 documents 顺序无关均覆盖，既有 schema tests 未回归。
17. 测试包含多个具体字段/错误断言，无泛化 `is not None`、`len > 0` 或自指 expected，最终全部通过。
18. silent fallback、可疑猜测逻辑、warning-as-pass 和 secret 扫描均为零命中；若有允许命中则逐项人工解释，不能把它计为零。
19. 没有业务规划/API/HTML/v1 实现；`PLAN.md`、WU0 Plan、handbook HEAD 与工作树均保持不变。
20. 完整 `verify_wu1.ps1` 只在六个显式 root 的 `closed` fixture 存在后于 C7 首次运行并 green，C8 同命令复核；Review 可独立复核、最终工作树干净、未 push、未自动进入 WU2。

任何一条为 `✗` 时不得声明 WU1 完成。任何关键依赖、红绿证据或冻结输入项为 `⚠` 时，Review 最终状态不得使用 `READY_FOR_HUGIN_REVIEW`，除非 Hugin 在执行前另有书面裁定。

## 15. 风险、停止条件与延后事项

### 15.1 Blocking / 立即停止整个 WU1

- Hugin 未明确批准本 Plan，或批准附带的修改未反映到新 Plan；
- 任一输入 hash、handbook `origin/main` 或已批准 Plan hash 改变；
- 需要修改 36 路径白名单外文件、保护文件、handbook 或用户配置；
- 依赖/传递依赖 license 无法核实、不兼容，或公开安装源不可达且无批准内替代；
- Python 3.11/PowerShell 5.1 下工具链不可用且需要换依赖或改范围；
- 正确实现需要引入新依赖、改工件产品语义或扩展 Schema SSOT；
- format checker 无法实际执行而继续会 silent pass；
- fixture 需要真实语义/检索 anchor，继续会迫使 AI 捏造；
- 输入或日志可能泄露 key、token、私有 index URL 或用户秘密；
- red 只能通过缺文件、畸形输入或自指 expected 制造；
- C4/C6 green 后对应公开接口仍有可达 `NotImplementedError`；
- `output_payload_sha256` 无法删除或只能通过猜测 hash 覆盖范围定义；
- `validate_bundle` 需要默认/推断 root 或 closure、选择首个 document，或 reference path 无法唯一分类；
- CLOSED 必须静默忽略 root 不可达额外 artifact 才能通过；
- root 无法唯一决定 candidate snapshot 或 previous/new plan-version 关系；
- constraint target 需要伪造未来 plan entity、relation subject 需要新增全局 route entity，或 pre/post-plan 不能用条件 Schema 明确表达；
- plan-diff 无法仅凭显式 previous/new/either 与指定 version artifacts 唯一解析，或 planner closure 需要同时索引多个 candidate snapshots；
- C7 正式 fixture 暴露需要修改 validator、既有 Schema 或测试的缺口。

### 15.2 Non-blocking

- uv 和 Poetry 不可用：本 Plan 使用标准 `venv`/pip。
- 全局包版本与 lock 不同：全局环境不参与执行。
- PowerShell 为 5.1：脚本只使用 5.1 兼容语法。
- WU1 不验证业务语义：这是明确边界，不是缺陷。

### 15.3 Deferred-to-WU2+

- WU2：高德 POI/路径 adapter 与真实 API/录制 fixture；
- WU3：证据采集、正交状态映射、freshness 与依赖传播；
- WU4：约束解析、环境检查、四态判定和证明复算；
- WU5：基地、分天与天内排序；
- WU6：previous plan、配置化变更代价和 plan diff；
- WU7：单文件 HTML 行程卡；
- WU8：江西真实 anchor、旅行前和现实旅行验收。

### 15.4 Deferred-to-v1

- 从模糊意图发现目的地、候选检索与推荐；
- 完整目的地发现 benchmark。

### 15.5 Handbook candidate

- 将“格式校验器缺失必须内部硬失败”的 JSON Schema 实践沉淀为 R10 例子；
- 将 manifest 内嵌精确 bytes、clean/dirty mutation 和行为层分离沉淀为 fixture-first 模式；
- 将 Schema、确定性跨工件验证和业务语义三层边界沉淀为阶段间契约模式。

## 16. Review 交付

C0—C8 全部结束后进入一次 WU1 Review，至少报告：

1. WU1 起点、HEAD、线性 commit 列表、diff/stat 和工作树；
2. 36 路径白名单对照和白名单外变更数；
3. 七个项目输入 hash 前后对照；
4. handbook 本地/远端 HEAD、ahead/behind、工作树和 8/8 注入证据；
5. 依赖、精确版本、direct/transitive 数量、许可证与 clean-lock replay；
6. Schema 数、`$id`、definition/reference registry、constraint-parse 单一 hash 权威、Draft、format checker 和 unknown-major 证据；
7. schema red → green 的相同命令、exit code、失败/通过 case 数，以及 §11.1 至少 47 项明确测试；
8. fixture red → green 的相同命令、exit code、失败/通过 case 数，以及两种 closure 与显式 root 参数传递；
9. 六个 `closed` fixture 的固定 root、root 可达最小闭包、领域结构、clean/dirty 和行为层未执行声明；
10. 稳定错误对象、十个引用/root 错误码、hash/ref/fact-local/plan-version/root/额外 artifact 验证证据；
11. R10、silent fallback、可疑逻辑、secret、scope 和无业务实现扫描；
12. §14 二十条完成判定逐条状态，以及唯一最终状态。

最终状态只允许：

```text
READY_FOR_HUGIN_REVIEW
BLOCKED
INCOMPLETE
```

Review 后停止。不得 push，不得开始 WU2，也不得提前创建 WU2 Plan。
