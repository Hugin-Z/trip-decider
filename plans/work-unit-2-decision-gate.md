# Work Unit 2 Decision Gate · Real-world Identity Boundary Decision

Plan version: v0.1

Status: PENDING_HUGIN_APPROVAL

Prepared on: 2026-07-28

Planned execution branch: `main`

Planned start HEAD:
`71eeed24bceaf7f5df9a29f0cb9749004cb83a05`

## 1. 任务目标与非目标

### 1.1 唯一目标

本工作单元只形成并审计一个真实世界 identity 边界裁定：

> 当一个冻结 acquisition recipe 对同一自然语言 seed 返回多个合法 OSM
> identity 时，adapter、candidate、evidence、constraint/planner 各层分别
> 应承担什么责任，以及 WU2 在什么条件下才允许进入恢复流程。

本 Plan 预注册的裁定是：

```text
Decision: MULTI_IDENTITY_CANDIDATE
```

含义：

- 一个合法 provider identity 对应一个独立 candidate；
- 同名 candidate 可以并存；
- adapter 不判断哪个 identity 才是用户真正想去的地点；
- evidence 分别陈述每个 candidate 的来源事实；
- identity resolution 只有在显式用户约束或足够证据支持时，才可由后续
  constraint/planning 流程采用；
- unresolved ambiguity 必须保持可见，不得由 first、nearest、popularity、
  LLM、人工常识或静默默认消除。

### 1.2 当前恢复裁定

本工作单元不授权直接恢复原 WU2 C5/C6：

```text
WU2_C5_C6_RESUME: NOT_AUTHORIZED_NOW
OLD_WU2_C5_C6_UNCHANGED: PROHIBITED
```

原因不是 acquisition 失败，而是原 WU2 Plan 的冻结边界与当前多 identity
事实不兼容：

```text
原 WU2 Plan:
identity 无法无歧义匹配
→ C5 不得创建

WU2A-Resume:
7 个结构合法 identity
→ 婺源县多个
→ 篁岭多个
→ 庆源未选择
```

Decision Gate 不改写旧 Plan，也不把新裁定追溯写成旧 WU2 已经满足。只有
本 Gate 通过 Review 后，才可另立一个新的 WU2 recovery Plan 请求执行授权。

### 1.3 不负责

WU2 Decision Gate 不负责：

- 新 OSM/Overpass 查询或任何新数据获取；
- OSM identity 的真实世界消歧；
- 选择某一个婺源县或篁岭记录；
- 创建或持久化 anchor、fixture、candidate、evidence 或 route；
- 修改 Schema、validator、adapter、pipeline、测试或 dependency；
- 实现 evidence mapping、constraint resolution 或 planner；
- 恢复 WU2 C5/C6；
- 开始 WU3、WU4 或 WU5；
- 修改、amend、reset、rebase、squash 任何历史 commit。

## 2. 输入、基线与 Source of Truth

### 2.1 Git 基线

Plan 阶段实测：

```text
repository: <repo>
branch: main
HEAD: 71eeed24bceaf7f5df9a29f0cb9749004cb83a05
worktree: clean
remote count: 0
stash count: 0
WU2 Review: absent
```

Execute 开始前必须逐项重验。任一不一致即停止，不进入 C0。

### 2.2 当前工作单元状态

本 Plan 接受 Hugin 给出的审核状态：

```text
WU0          APPROVED
WU1          APPROVED
WU1R         APPROVED
WU1C         APPROVED
WU2          BLOCKED
WU2A         INVESTIGATION_BLOCKED
WU2A-R       APPROVED
WU2A-Resume  APPROVED
```

`WU2 BLOCKED` 和 `WU2A INVESTIGATION_BLOCKED` 是已发生历史，不是失败，也
不会被 Gate 改写。

### 2.3 冻结输入

| Path | Bytes | SHA256 |
|---|---:|---|
| `PLAN.md` | 9914 | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `plans/work-unit-2-real-world-ingestion.md` | 32985 | `894D5844E140BF62EC1DB89B1BE318EB4945FF4A0BF8B139E9B82C0B4929BA2C` |
| `plans/work-unit-2-anchor-recovery.md` | 28097 | `432318A68D13774646CF3A1E5BE6057D5C92DE7CE600E06FA6CF52BD0CD92E90` |
| `plans/work-unit-2a-remediation.md` | 27513 | `FD0DA659873A275944DE7FCC9C1E4D1D27EE9BD7F61F40F4A3371493173008B9` |
| `plans/work-unit-2a-resume.md` | 30050 | `B363FA80F1E62168E7AF654DE1195A24812F890352FB6C15852D65C488EE9BDB` |
| `docs/wu2a-anchor-decision.md` | 11531 | `570649D6B7287B48F3C396E536AC05EF31D949FC7AF960EF2D3DFEB17D4A9F6D` |
| `docs/reviews/work-unit-2a-remediation-review.md` | 15905 | `DBA77226011F013D687FB3C6AF6085C692217167803E3280246EC70ABA93338F` |
| `docs/wu2a-resume-decision.md` | 23394 | `417F4E89A059CA99A5E96E960B839FA0297935F2438D76B100E7F8F30313B40A` |
| `docs/reviews/work-unit-2a-resume-review.md` | 14311 | `9CE29F71B065768B4BEE173144944A13003BC2838FCB42007ABCD8EAEEE4C64C` |
| `docs/real-world-contract-extension.md` | 14969 | `BD2280BFA2C51F2FEC8521F16BB7DE73667A39142FD89E04F6A515CB42B8963E` |
| `src/trip_decider/adapters/open_data_poi.py` | 9551 | `F39EBF86B682EDECF182F6148178AEBA434A287B34A270FE84D3FAEE8F80944B` |
| `schemas/candidates.schema.json` | 7786 | `3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2` |
| `schemas/evidence.schema.json` | 7479 | `54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B` |

这些输入在 Execute/Review 只读。Decision 与 Review 只能引用，不能修改。

### 2.4 Source of Truth 顺序

本 Gate 的裁定依据顺序：

1. 冻结 `PLAN.md` 的产品边界；
2. v3.1 工程勘误和 R10 诚实性；
3. 已批准 WU2/WU2A/WU2A-R/WU2A-Resume 历史事实；
4. 当前 Candidate/Evidence Schema 与 adapter 的实测结构能力；
5. 本 Gate 对职责边界的工程裁定。

产品定义仍以 `PLAN.md` 为准。Gate 不引入 destination discovery、推荐、
路线优化、Web UI 或 v1 能力。

## 3. Handbook 上下文

固定只读路径：

```text
<handbook>
```

Plan 阶段执行 fetch 后实测：

```text
local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree before/after fetch: clean
```

从 `origin/main` 实际重读：

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

对本 Gate 的具体影响：

- **R10：** 不把同名、category 或结构合法性升级为“真实地点已经识别”；
- **PER：** 本文件批准前不创建 decision，C0—C2 完成后只进入 Review；
- **Scope：** Execute 精确三路径，不用“只是文档”作为越界理由；
- **Fixture-first：** 本 Gate 不新增行为、代码或 fixture，因此不制造形式化
  red；Review 改用预注册文档 contract checks。未来任何 ambiguity mapping
  或 planner 行为必须另走 fixture-first。

Handbook 不修改。

## 4. Acquisition 事实与能力边界

### 4.1 已批准事实

必须原样保留：

```text
WU2A-Resume Decision:
APPROVED_ACQUISITION_RECIPE

WU2A-Resume Compatibility:
ADAPTER_COMPATIBLE_ONLY
```

实际 bounded group `WU2A-resume-001`：

```text
G0: 1 Geofabrik .poly GET
O1: 1 Overpass POST
O2: 1 Overpass POST
O3: 0
physical attempts: 3
retry relations: 0
```

O2 结构化 selection：

```text
selected OSM objects: 7
婺源县: multiple provider identities
篁岭: multiple provider identities
庆源: no selected identity
```

系统没有使用：

```text
first
nearest
popularity
fuzzy
manual coordinate
guessed ID
LLM judgment
```

### 4.2 事实不支持的声明

以上事实不能推出：

- 七个对象对应七个用户真正想去的景点；
- `tourism=attraction` 必然比 `place=hamlet` 更正确；
- 同名记录必然互相冲突或必然指向同一现实对象；
- 庆源在 OSM 中不存在；
- WU2 的约五目标和两条 route 已满足；
- planner 已经具备处理 ambiguity 的实现；
- acquisition recipe 已经成为 anchor 或 fixture。

## 5. Identity 问题定义

### 5.1 三种不同的“唯一”

本 Gate 区分：

1. **Provider identity uniqueness**

   ```text
   (provider name, record type, record id)
   ```

   当前 adapter 已机械保证每条输入 record identity 唯一，重复 identity 硬
   失败。

2. **Candidate identity uniqueness**

   每个 provider identity 生成独立稳定 `candidate_id`。同名不等于同一个
   candidate，也不构成 candidate ID 冲突。

3. **User-intent match uniqueness**

   “用户说的篁岭到底指哪一个 provider identity”是语义/业务问题。当前数据
   只证明多个合法 record 匹配冻结 predicate，未证明唯一 user-intent match。

Adapter 可以证明第 1 层并生成第 2 层；不得宣称完成第 3 层。

### 5.2 当前契约实测

`open_data_poi.py` 当前行为：

- 使用 `(type,id)` 检测 provider identity 重复；
- 为每条 record 生成稳定 `candidate_id`；
- 保留 provider `record_id`、`record_type`、categories 和 location；
- 对全部合法 elements 排序后全部输出；
- 没有 first/nearest/popularity/语义选择分支。

`candidates.schema.json` 当前行为：

- `payload.candidates` 是数组；
- `candidate_id` 必须稳定且唯一由 bundle 语义检查；
- `label` 只要求非空，不要求跨 candidate 唯一；
- provider metadata 已正交保存 `name/record_id/record_type/categories`；
- 没有 `ambiguity` 字段。

因此，多 identity candidate pool 已有结构承载能力；Gate 不需要修改
adapter 或 Candidate Schema。

## 6. 方案比较与裁定标准

### 6.1 方案 A：Adapter 阶段消歧

```text
OSM records
→ adapter 选择一个
→ one candidate
```

优点：

- 下游只见一个 candidate；
- fixture 和 route endpoint 表面更简单。

风险：

- adapter 必须把 category、距离、名字或排序升级为旅行语义；
- `tourism=attraction` 与 `place=hamlet` 的取舍不是结构验证；
- 无来源的选择会成为 silent fallback；
- 选择逻辑容易城市化、数据源化或 seed 特例化；
- 被丢弃 identity 与不确定性无法回读；
- 违反“数据采集层不承担旅行决策”。

### 6.2 方案 B：Candidate 保留多个 identity

```text
OSM records
→ one candidate per provider identity
→ candidate pool
→ evidence / explicit constraints
→ later planning decision or unresolved state
```

优点：

- provider 事实不丢失；
- adapter 只执行结构验证和确定性 normalization；
- ambiguity 可回读；
- 支持用户确认、官方证据或未来 constraint 逐步缩小；
- 符合 verification > generation 和 R10。

风险：

- 下游必须显式处理同名 candidate；
- route endpoint 不得继续按 label 查找；
- evidence/constraint/planner 的 ambiguity 语义需要单独契约与测试；
- 若 unresolved 状态传播不足，可能在下游重新出现 silent first。

### 6.3 裁定标准

方案必须同时满足：

1. 不把无来源语义写入 adapter；
2. 不丢弃合法 provider identity；
3. 每个事实可追溯到具体 candidate/provider record；
4. unresolved ambiguity 可显式传播；
5. route 和 planner 必须按稳定 candidate ref 消费；
6. 缺失 seed 不转成空成功或虚构 candidate；
7. 不需要在本 Gate 修改 Schema/adapter；
8. 不追溯改写 WU2 历史。

### 6.4 裁定

```text
Decision: MULTI_IDENTITY_CANDIDATE
Rejected: UNIQUE_IDENTITY_REQUIRED_AT_ADAPTER
```

选择方案 B。

`UNIQUE_IDENTITY_REQUIRED` 只在外部数据源或用户显式输入能提供可审计唯一性
证明时，才可作为某一次后续约束结果；它不是 adapter 的通用输入前提，也
不是本 Gate 的系统边界。

## 7. Candidate 模型影响

### 7.1 采用多个 candidate，不采用内嵌 alternatives

本 Gate 裁定保持：

```text
多个 candidate
```

而不是新增：

```json
{
  "ambiguity": {
    "status": "ambiguous",
    "alternatives": []
  }
}
```

理由：

- ambiguity 是一个 seed/context 与多个 candidate 之间的集合关系，不是某
  一个 candidate 的固有 provider 属性；
- 把完整 alternatives 复制到每个 candidate 会产生循环、重复和一致性问题；
- provider metadata 已足够唯一标识每个 record；
- 当前 Schema 没有 `ambiguity` 字段，Gate 无权新增；
- candidate 不能自称“我是正确对象的备选”，除非存在上游 intent/constraint
  上下文。

### 7.2 Candidate 层不变量

未来恢复单元必须保持：

- 一个 `(provider, record_type, record_id)` 对应一个 candidate；
- candidate ID 不由 label 单独生成；
- 同 label、多 identity 均保留；
- category、location、source ref 保持 record-local；
- 不为未命中的庆源创建 placeholder candidate；
- candidate 数量不等于目的地推荐数量；
- candidate pool 不承诺每个自然语言 seed 已唯一解析。

### 7.3 未匹配 seed

`庆源` 未选择必须表达为：

```text
unmatched input seed
```

而不是：

```text
OSM 中不存在庆源
```

未匹配 seed 的最终持久字段放在哪个 artifact，属于后续 recovery/WU3
contract Plan；在明确契约前不得塞进 `generation_reason` 或虚构 candidate。

## 8. Evidence 边界

### 8.1 Source facts 分候选记录

如果存在：

```text
candidate_A  label=篁岭  category=place=hamlet
candidate_B  label=篁岭  category=tourism=attraction
```

Evidence 应分别陈述：

```text
candidate_A has provider category place=hamlet
candidate_B has provider category tourism=attraction
```

每条事实：

- subject 指向一个稳定 candidate ID；
- source 指向对应 OSM provider record；
- original/normalized value 可回读；
- retrieval/freshness 与 support/derivation 正交；
- 不把 category 值映射为“更正确”“更值得去”或“用户真正想去”。

### 8.2 Ambiguity 是 rule-derived state，不是来源原话

“两个 exact-name candidate 对应同一个输入 seed”可以形成确定性的
rule-derived identity-match state，但必须明确：

- 输入是 seed fact 和多个 candidate label/provider facts；
- 输出是 `ambiguous`，不是 preferred identity；
- alternative refs 全量保留；
- rule ID/version 可回读；
- 不以 sourced/verified 冒充业务正确性。

概念语义目标：

```yaml
field: identity_match_status
value:
  seed: 篁岭
  status: ambiguous
  alternative_candidate_refs:
    - candidate_A
    - candidate_B
derivation: rule_derived
```

这只是 Gate 冻结的未来语义，不是当前 artifact，也不是 Schema 修改。

### 8.3 当前 Evidence Contract 的诚实边界

当前 `evidence.schema.json`：

- 支持 candidate entity subject；
- `field/value` 可承载记录级事实；
- relation subject 只允许 `route/transfer/service_between`；
- 没有已冻结的 N-way identity ambiguity relation；
- nested candidate refs 若只放进任意 `value`，当前 closure validator 不会自动
  赋予它们 reference semantics。

因此禁止：

- 把 identity ambiguity 伪装成 route/transfer/service relation；
- 仅靠任意 JSON value 就宣称 ambiguity contract 已实现；
- 在 Gate Review 中声称 WU3 已能传播 ambiguity。

WU3 Plan 必须为上述语义选择并测试明确承载方式。若需要 Schema、validator
或新 artifact，必须另立 contract remediation，不得在 WU2 recovery 中顺手
实现。

## 9. Constraint 与 Planner 边界

### 9.1 谁可以选择 candidate

Adapter 永远不选择“用户真正想去的 candidate”。

后续 constraint/planning 流程只有在以下任一依据存在时，才可以把 candidate
确定为 itinerary entity：

- 用户显式选择稳定 candidate ref；
- 用户约束能确定性排除其他 candidate；
- 官方或同等级来源提供可审计 identity 对应；
- 预注册规则基于已支持 evidence 给出确定性唯一结果。

不得使用：

- 数组第一项；
- 距离最近；
- category 优先级；
- popularity；
- 名字相似度；
- LLM 常识；
- 城市专属硬编码；
- “通常游客指的是……”。

### 9.2 Planner 的输出责任

未来 planner 可以选择“本行程使用哪个 candidate”，但不能把这一选择表述
为“真实世界 identity 已证明唯一”。

若关键 route/activity 仍依赖 unresolved identity：

- 不得输出无条件 `feasible`；
- 必须保留条件或请求确认；
- unknown/conflicting/ambiguous 依赖不得静默支撑硬决策；
- 未找到确定身份不等于 `proven_infeasible`；
- 不得删除 alternatives 后再生成看似确定的计划。

### 9.3 对后续工作单元的影响

**WU2：**

- POI adapter 的多 candidate 行为保持；
- 旧 C5/C6 不得原样恢复；
- route acquisition 必须使用显式 candidate refs，不能按 label 选点。

**WU3：**

- 每个 candidate 的 provider/source fact 独立定级；
- identity-match ambiguity 必须有显式 rule-derived contract；
- display status 不得高于来源支持；
- evidence 不做推荐或偏好选择。

**WU5：**

- planner 消费 candidate refs，而非自然语言 label；
- identity alternatives 在用户/证据未消歧时保持互斥候选；
- 选择理由必须回指约束/evidence；
- unresolved identity 必须进入条件、violations 或确认门；
- 不允许 planner 重新实现 silent first。

## 10. WU2 恢复条件

### 10.1 当前结论

```text
WU2_C5_C6_RESUME: NOT_AUTHORIZED_NOW
```

Gate 批准本身也不自动授权恢复。

### 10.2 为什么不能直接恢复旧 C5/C6

冻结 WU2 Plan 明确：

> If names or identities cannot be unambiguously matched, C5 is not created.

当前事实正是 identities 未唯一匹配。Decision Gate 不能修改或重新解释旧
Plan 字节。因此原 C5/C6 的执行许可已经用尽并保持 BLOCKED。

### 10.3 后续 recovery Plan 的强制前置条件

新的 WU2 recovery Plan 至少必须同时满足：

1. Hugin 已验收本 Gate；
2. 明确引用 `MULTI_IDENTITY_CANDIDATE`，不重写旧 WU2 历史；
3. 将 POI anchor 的接受对象改为“完整 provider identity candidate pool”，
   不再要求 adapter 先收敛成约五个唯一自然语言目标；
4. 将每个 supplied seed 的 matched/unmatched/ambiguous 结果显式记录；
5. 未匹配的庆源保持 unmatched，不创建假 record；
6. 每个 candidate 的 provider identity、category、location、source 和 hash
   可独立回读；
7. acquisition recipe 的再次执行获得新的明确授权；本 Gate 不提供调用预算；
8. route endpoint 只能引用已显式选定的 stable candidate IDs；
9. 若 route endpoint identity 未由用户或证据确定，route acquisition 必须
   保持 blocked，或在获批 recovery Plan 中与 POI anchor 拆分；
10. ambiguity 的 Evidence/constraint 承载方式在对应 WU3/contract Plan 中
    冻结并 fixture-first 验证；
11. 如需 Schema、validator、adapter 或 fixture policy 修改，先建立独立
    remediation，不在 recovery Execute 临时扩大；
12. recovery 仍按 PER 单独 Plan → approval → Execute → Review。

满足这些条件只意味着可以提交 recovery Plan 请求审核，不等于自动批准
任何数据调用、anchor 创建、route acquisition 或 WU2 状态变更。

### 10.4 被拒绝的恢复路径

```text
用 tourism=attraction 自动选篁岭
按 response 第一条选婺源县
删掉同名 place records
忽略庆源后把 7 条说成完整五目标
让 route adapter 接受 label 并自行找坐标
修改旧 WU2 Plan 使其看似从未要求唯一
```

以上路径均不允许。

## 11. Execute Scope

### 11.1 精确三路径白名单

若 Plan 获批，WU2 Decision Gate C0—C2 只允许创建：

```text
plans/work-unit-2-decision-gate.md
docs/wu2-identity-boundary-decision.md
docs/reviews/work-unit-2-decision-gate-review.md
```

预计最终变更文件数：

```text
3
```

Plan 阶段当前只创建第一项，不 commit。

### 11.2 明确保护

不得修改：

```text
PLAN.md
plans/work-unit-2-real-world-ingestion.md
plans/work-unit-2-anchor-recovery.md
plans/work-unit-2a-remediation.md
plans/work-unit-2a-resume.md
docs/wu2-source-decision.md
docs/wu2a-anchor-decision.md
docs/wu2a-resume-decision.md
docs/reviews/work-unit-2a-remediation-review.md
docs/reviews/work-unit-2a-resume-review.md
src/**
schemas/**
tests/**
fixtures/**
scripts/**
pyproject.toml
requirements.lock
handbook repository/**
```

不得创建：

- code、Schema、test、fixture、anchor；
- runtime 或 temp repository directory；
- WU2 recovery Plan；
- WU3/WU4/WU5 Plan；
- remote、branch 或 PR。

需要第四个 Git path 即停止。

## 12. Decision 文档契约

C1 的 `docs/wu2-identity-boundary-decision.md` 必须包含：

1. preserved historical states；
2. frozen input hashes；
3. acquisition fact boundary；
4. Adapter/Candidate/Evidence/Constraint/Planner responsibility matrix；
5. Option A/B comparison；
6. exact decision token；
7. candidate model ruling；
8. evidence semantic ruling and current-contract limitation；
9. WU2/WU3/WU5 impact；
10. exact recovery authorization token；
11. recovery prerequisites；
12. rejected fallbacks and non-capabilities。

固定机器可检索 token：

```text
Decision: MULTI_IDENTITY_CANDIDATE
Rejected: UNIQUE_IDENTITY_REQUIRED_AT_ADAPTER
WU2_C5_C6_RESUME: NOT_AUTHORIZED_NOW
OLD_WU2_C5_C6_UNCHANGED: PROHIBITED
```

C1 不得出现：

```text
WU2_C5_C6_RESUME: AUTHORIZED
WU2_C5_COMPATIBLE
identity resolved
route ready
anchor created
fixture created
```

这些禁句可以在明确的“禁止声明”代码块中被引用，但不得作为 status 或结论。

## 13. 验证策略

### 13.1 为什么不写 fixture

本 Gate 不新增可执行行为或数据变换，只冻结职责边界。为文档裁定伪造
candidate/evidence fixture 会违反当前 scope，也会让尚未实现的 ambiguity
contract 看似已完成。

因此：

- 本工作单元不新增 fixture/test；
- C1 采用预注册文档 contract checks；
- 后续实现 ambiguity mapping、route ref 或 planner behavior 时必须重新走
  fixture-first red→green。

### 13.2 C1 文档 contract checks

C1 完成后使用 PowerShell/`rg` 只读验证：

```text
G01 UTF-8 no BOM
G02 exactly one Decision: MULTI_IDENTITY_CANDIDATE
G03 exactly one Rejected: UNIQUE_IDENTITY_REQUIRED_AT_ADAPTER
G04 exactly one WU2_C5_C6_RESUME: NOT_AUTHORIZED_NOW
G05 exactly one OLD_WU2_C5_C6_UNCHANGED: PROHIBITED
G06 all frozen input hashes match
G07 all five responsibility layers are present
G08 Option A and Option B are both analyzed
G09 multiple-candidate/no-nested-alternatives ruling is explicit
G10 per-candidate evidence and rule-derived ambiguity boundary are explicit
G11 WU2/WU3/WU5 impacts are all present
G12 recovery prerequisites count is exactly 12
G13 prohibited data/API/code changes are explicitly zero
G14 document has no PENDING/placeholder conclusion
```

预期：

```text
checks: 14
passed: 14
failures: 0
errors: 0
network attempts: 0
```

数字由命令输出，不由报告估算。

### 13.3 C2 独立 Review

C2 必须独立复核：

```powershell
git status --short
git log --oneline --decorate <start>..HEAD
git diff --stat <start>..HEAD
git diff <start>..HEAD
git diff --check
git remote -v
git stash list
```

并重新运行 G01—G14。Review 还必须：

- 重算全部冻结输入 hash；
- 确认 11 Schema 与 adapter diff 为 0；
- 确认不存在新 fixture/anchor/runtime；
- 扫描 silent fallback、guess/infer、secret 和地图 endpoint；
- 确认 handbook local/origin/0/0/clean；
- 逐条对照 §15 的 16 条完成判定。

Review 最终状态只允许：

```text
READY_FOR_HUGIN_REVIEW
BLOCKED
INCOMPLETE
```

## 14. Commit 序列

### WU2-Gate-C0

```text
docs: record approved decision gate plan
```

唯一文件：

```text
plans/work-unit-2-decision-gate.md
```

前置条件：

- Hugin 明确批准本 Plan 的 path/version/SHA256；
- branch、HEAD、worktree、remote、stash 与冻结输入全部匹配；
- handbook fetch/recheck 成功。

验证：

- approved Plan SHA256 精确匹配；
- staged path 只有 Plan；
- `git diff --cached --check` 为 0；
- commit 后工作树干净。

### WU2-Gate-C1

```text
docs: record identity boundary decision
```

唯一文件：

```text
docs/wu2-identity-boundary-decision.md
```

职责：

- 写入本 Plan 冻结的裁定；
- 运行 G01—G14；
- 不修改 Plan 或任何冻结输入。

验证：

- G01—G14 为 14/14；
- decision token 与 restore token 唯一；
- staged path 只有 decision；
- commit 后工作树干净。

### WU2-Gate-C2

```text
docs: prepare decision gate review
```

唯一文件：

```text
docs/reviews/work-unit-2-decision-gate-review.md
```

职责：

- 独立复核 Git、hash、scope、handbook 和 G01—G14；
- 逐条对照 16 条完成判定；
- 记录旧 WU2 仍 BLOCKED；
- 给出唯一 Review 状态。

验证：

- staged path 只有 Review；
- 三路径白名单精确；
- dependency/code/Schema/test/fixture diff 为 0；
- commit 后工作树干净。

禁止 amend、squash、reset、rebase 或重写任何既有/WU2-Gate commit。

## 15. 完成判定

预注册恰好 16 条。Review 不得增删或省略：

1. Approved Plan 按获批 SHA256 原文提交，执行期未修改；
2. WU2/WU2A/WU2A-R/WU2A-Resume 历史状态和冻结文件保持不变；
3. Handbook fetch、八文件重读、local/origin `0/0` 和 clean 有证据；
4. Acquisition 的 7 selected/multiple 婺源县/multiple 篁岭/unmatched 庆源
   事实被准确保留，未升级为 identity truth；
5. Option A/B 均被比较，裁定标准完整；
6. 唯一 Decision 为 `MULTI_IDENTITY_CANDIDATE`；
7. Adapter 边界明确为结构验证和一 identity 一 candidate，不承担语义选择；
8. Candidate 边界明确采用多个 candidate，不新增内嵌 ambiguity alternatives；
9. Evidence 边界分别表达 record-local facts，并诚实声明当前 N-way ambiguity
   contract 未实现；
10. Constraint/Planner 只有在用户或证据支持时才可选择，未支持时保持显式
    unresolved；
11. WU2、WU3、WU5 影响分别说明，未宣称任一实现完成；
12. 恢复状态精确为 `NOT_AUTHORIZED_NOW`，12 个 recovery 前置条件完整；
13. 最终 diff 精确为三个白名单文档，code/Schema/adapter/test/fixture diff
    为 0；
14. 未调用地图 API、未获取新数据、未创建 anchor/fixture/runtime；
15. G01—G14 在 C1 和 C2 均为 14/14，所有数字来自命令；
16. 未恢复 WU2、未开始后续工作单元、未 push/remote/PR，Review 可独立复核。

任何 `✗` 都不得使用 `READY_FOR_HUGIN_REVIEW`。已知限制必须用 `⚠`，不得
改写为完成。

## 16. Blocking

Execute 中出现以下任一情况立即停止：

- baseline、approved Plan hash、冻结输入或 handbook 状态不匹配；
- 需要修改旧 WU2/WU2A/WU2A-R/WU2A-Resume 文档或历史；
- 需要修改 Candidate/Evidence Schema、validator、adapter、pipeline 或 test；
- 需要新增 ambiguity artifact、字段或 relation enum 才能写出本次裁定；
- 发现现有 adapter 实际会按 label 合并、排序后只取第一条或丢弃合法 identity；
- 需要调用 Overpass、OSM、Nominatim、OSRM、商业地图或任何新数据源；
- 需要判断哪个婺源县/篁岭是真正目标；
- 需要为庆源补 record、坐标、ID、category 或来源；
- 需要创建 anchor、fixture、candidate、evidence、route 或 runtime；
- 需要第四个 Git path；
- 需要创建 WU2 recovery Plan 或 WU3/WU5 Plan；
- 需要把 Gate decision 写成“WU2 已恢复”；
- 需要 amend/reset/rebase/squash；
- secret、raw response、坐标列表或未授权数据可能进入 Git；
- G01—G14 不能在纯文档范围内通过；
- 完成判定无法恰好逐条对照 16 条。

若发现当前 Evidence Contract 不足以实现 future ambiguity semantics，只在
Decision/Review 中记录为后续 contract remediation 条件；不得在 Gate 内修。

## 17. 延后事项与结束边界

### deferred-to-WU2-recovery

- 多 identity POI anchor 的实际 replay/capture；
- matched/unmatched/ambiguous seed ledger；
- route endpoint 的 stable candidate ref；
- POI anchor 与 route acquisition 是否拆分。

### deferred-to-WU3

- record-local evidence facts；
- `identity_match_status` 的正式语义、mapping rule 和传播；
- unknown/conflicting/ambiguous 的 display/decision dependency。

### deferred-to-WU5

- candidate alternatives 的互斥选择；
- 基于 constraint/evidence 的 candidate selection；
- unresolved identity 对 feasible/conditionally feasible/violations 的影响。

### 当前 Plan 阶段结束

本轮只创建：

```text
plans/work-unit-2-decision-gate.md
```

不 commit，不进入 C0，不创建 decision/review，不调用地图 API，不恢复 WU2，
不开始 WU3/WU5。

等待：

```text
批准执行 Work Unit 2 Decision Gate
```
