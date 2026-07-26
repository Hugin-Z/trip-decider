# trip-decider artifact contracts v0.1 draft

状态：`DOCUMENT_CONTRACT_ONLY`

本文冻结工件的文档级字段、权威边界、阶段关系、provenance、硬失败条件、fixture specification 和 WU1 实施范围。没有任何实际 Schema、validator、fixture、测试或业务逻辑已经实现。

## 1. 通用 envelope 与硬失败

WU1 计划将 YAML/JSON 工件初始 `schema_version` 设为 `0.1.0`，Schema 自身使用 JSON Schema Draft 2020-12。所有工件共享：

| 字段 | 必填 | 语义 |
|---|---:|---|
| `schema_version` | 是 | 工件 schema 语义版本；未知 major 硬失败 |
| `artifact_id` | 是 | 稳定、全局唯一，不得用文件名冒充 |
| `artifact_type` | 是 | 固定类型枚举 |
| `created_at` | 是 | 带 offset 的 RFC 3339 时间 |
| `producer` | 是 | `{name, version, run_id}`；用户直接创建时 `name=user` |
| `provenance` | 是 | `{parent_artifact_ids, input_hashes, pipeline_stage}` |
| `integrity` | 是 | `{payload_sha256, canonicalization}` |
| `payload` | 是 | 工件业务内容 |

共同规则：

- `input_hashes` 记录消费者实际读取的上游文件 bytes SHA256；缺文件或 hash 不符硬失败。
- `payload_sha256` 对解析后键排序、UTF-8、无无意义空白的 canonical payload 计算，并排除自身字段以避免自引用；整个文件 SHA256 由 run/review 另行记录。
- 未知字段默认拒绝；validator 不注入 Schema default，不补“合理事实”。
- YAML 只能 safe load，禁止自定义 object tag。
- 错误必须非零退出，并给出工件路径、JSON Pointer、规则和实际类型；不得打印 secret。
- 模型执行信息可进入 producer/parse provenance，但绝不能进入 Evidence `sources`。
- WU1 validator 只证明结构契约，不证明事实、业务可行性或算法正确。

字段归属：

- 用户原话与显式结构：`request.yaml`
- 模型/语义解析：`constraint-parse.json`
- 求解唯一权威约束：`constraints.yaml`
- 外部事实与算法估计：`evidence.json`
- 算法结果：`plan.json`、`violations.json`、`plan-diff.json`

## 2. 十项工件

### 2.1 `request.yaml`

- Schema/版本：`schemas/request.schema.json`，`0.1.0`
- 生产者：用户或 intake
- 消费者：约束解析器、阶段 B pass-through
- 权威边界：不可由 solver 修改；重解析生成新 artifact，不覆盖旧请求
- 必填：
  - `request_id`
  - `natural_language`
  - `explicit.origin`
  - `explicit.travel_window.{start,end,timezone}`
  - `explicit.party.count`
  - `explicit.transport_modes`
  - `explicit.destination.selection_mode`
  - `explicit.preferences_raw`
  - `user_input_refs`
- 可选：destination 的 `destination_id/name/admin_codes/geometry_hint`、budget、mobility、must_visit、excluded、clarifications、locale
- v0：`selection_mode=user_supplied` 且 destination 必填
- v1 能力 A：允许 `selection_mode=discovery_required` 且 destination 暂空；继续保留稳定 request ID、出发地、门到门时间窗、预算、偏好和交通方式
- 硬失败：缺原文、时区、destination mode，或显式结构类型错误

### 2.2 `constraint-parse.json`

- Schema：`schemas/constraint-parse.schema.json`
- 生产者：版本化语义解析器；LLM 可以执行显式语义工作
- 消费者：人工确认、constraints 生成器
- 必填：
  - `request_id`
  - `request_artifact_id`
  - `request_payload_sha256`
  - `parser.{name,version,kind}`
  - `parsed_constraints[]`
  - `parse_notes`
  - `needs_confirmation`
  - `output_payload_sha256`
- 每项 parse 必填：`parse_item_id`、稳定 `constraint_id`、`user_quote`、`user_quote_locator`、`classification: explicit|inferred`、`layer: hard|soft|environment`、`category`、`normalized_expression`、`default_source`（可为 null）、`explanation`、`needs_confirmation`
- 可选：`confidence_note`（不得伪装成概率）、`model_execution`、`ambiguities`
- 硬失败：inferred 无解释/原话定位、hash 不符、parser 版本缺失

### 2.3 `constraints.yaml`

- Schema：`schemas/constraints.schema.json`
- 生产者：规范化器或用户直接编辑
- 消费者：环境检查、proof 规则、planner
- 权威边界：求解阶段唯一 SSOT；重解析只能产生 proposal，不能覆盖用户修改
- 必填：
  - `constraint_set_id`
  - `request_ref`
  - `parse_ref`
  - `revision`
  - `constraints[]`
  - `user_edit_policy`
- 每个约束必填：`constraint_id`、`layer`、`category`、`operator`、`target_refs`、`value`、`unit`（不适用显式 null）、`origin.kind`、`origin.refs[]`、`enabled`
- origin 判别联合：
  - `explicit`：parse item ID + 用户原话 locator
  - `inferred`：parse item ID + explanation + needs_confirmation
  - `default`：版本化 default rule ID + version
  - `user_edited`：edit event；修改旧约束时另保留 `supersedes_constraint_id` 与原 parse refs
- soft 额外必填：`weight`、`direction`；hard 不得以 weight 降级
- 可选：`valid_for_days`、`notes`
- 硬失败：稳定 ID 缺失、layer 非法、origin refs 不匹配、单位不一致

### 2.4 `candidates.json`

- Schema：`schemas/candidates.schema.json`
- 生产者：阶段 B/C、未来基地候选器
- 消费者：证据采集、约束检查、planner
- 必填：`candidate_set_id`、`request_ref`、`generation_stage`、`candidates[]`、`rejected_inputs[]`
- 每个候选必填：`candidate_id`、`candidate_type: destination|poi|base_area`、`name`、`parent_candidate_id`（顶层为 null）、`source_refs`、`generation_reason`、`status: active|rejected|unresolved`，以及 `location|location_unresolved` 二选一
- 条件字段：
  - `poi_discovery`：稳定 ID、名称、位置/待解析位置、source refs 必填；evidence refs 可空
  - `destination_pass_through`：必须回指用户给定 destination 和 request locator
  - `destination_recommendation`：仅 v1 真正展示给用户的 destination 强制 `rough_feasibility_ref`、`coarse_plan_ref`
- 可选：`provider_ids`、`categories`、`evidence_fact_refs`、粗可行性/粗计划引用、`applicable_area`
- 阶段不可变：D 新建 `evidence.json`，不得回写旧 candidates；下游同时引用 candidate ID 与 fact ID
- 硬失败：稳定 ID、位置/待解析位置或来源缺失；v0 pass-through 缺 request 引用

### 2.5 `evidence.json`

- Schema：`schemas/evidence.schema.json`
- 生产者：adapters、标准化器、证据映射器
- 消费者：约束检查、planner、renderer
- 必填：`evidence_set_id`、`facts[]`、`mapping_rule_version`
- 每个 fact 必填：
  - `fact_id`
  - `subject_ref`
  - `field_path`
  - `value`
  - `unit`
  - `support_status: verified|sourced|conflicting|unknown`
  - `derivation: direct_observation|official_report|api_estimate|rule_derived|model_estimate|user_supplied`
  - `freshness.{retrieved_at,effective_at,expires_at,status: current|stale|unknown}`
  - `sources[]`
  - `normalization.{raw_value,normalized_value,rule_id}`
  - `display_status`
  - `display_status_rule_id`
  - `conflict_source_refs`
- source 判别联合：
  - `webpage|official_notice`：`source_id,url,publisher,retrieved_at,excerpt,locator` 必填；`published_at` 是时间或 null，null 时需 absence reason
  - `api_response`：`source_id,provider,operation,retrieved_at,request_fingerprint,response_locator` 必填；不强制网页字段，不保存含 key 的完整 URL
  - `direct_observation`：`source_id,observer_type,observed_at,observation,location_ref` 必填；不伪造 URL/publisher/title
- `user_supplied`：通过 user refs/provenance 回读，不为满足 source schema 伪造外部来源；无外证的现实事实不能 verified
- derived 值：`derivation_detail.{rule_id,input_fact_ids}` 回读；LLM、函数或模块名不是事实来源
- 关键估计另需：`estimate.{method,value,uncertainty_or_buffer,conservative_bound}`
- 外显五态确定性映射，优先级固定：
  1. unresolved 同等级冲突或 support=conflicting → `conflicting`
  2. 值/关键来源缺失或 support=unknown → `unknown`
  3. derivation 为 api/rule/model estimate → `estimated`
  4. verified + current + 权威来源可回读 + 无同等级冲突 + direct/official derivation → `verified`
  5. 其他有可回读来源，包括 stale/unknown freshness 降级 → `sourced`
  6. 仅 user supplied 且无外证的现实事实 → `unknown`，另显“用户提供”
- API 路时必须 `api_estimate`；住宿 POI 密度必须 `rule_derived`
- 硬失败：存储的 display status 与映射重算不一致；source 变体字段不符；source 含 secret
- invariant：任何事实的展示状态不得高于证据实际支持能力；真实旅行的来源变化/过期、采集/标准化错误需分类，只有状态误标直接违反 invariant

### 2.6 `previous-plan.json`

- Schema：`schemas/previous-plan.schema.json`
- 生产者：重排入口对旧 plan 的不可变快照
- 消费者：WU6 重排目标与 diff
- 必填：`previous_plan_id`、`previous_plan_artifact_id`、`previous_plan_payload_sha256`、`baseline_constraint_set_id`、`snapshot`、`snapshot_created_at`
- snapshot 至少保存基地、日期、活动、时段、相对顺序和删除状态
- 可选：`user_locked_entities`、`baseline_notes`
- 硬失败：replan 缺旧计划、hash 不符、snapshot 不完整；不得退化成全新规划并宣称最小改变

### 2.7 `plan.json`

- Schema：`schemas/plan.schema.json`
- 生产者：planner
- 消费者：renderer、重排 snapshot/diff、验收
- 必填：`plan_id`、request/constraint/candidate/evidence refs、`plan_status`、`conditions[]`、`base_selections[]`、`days[]`、`excluded_candidates[]`、`constraint_evaluations[]`、`objective_breakdown`
- day/activity/leg 使用稳定 ID；activity 包含 candidate ref、start/end/duration、evidence refs；leg 包含 mode、from/to、duration、derivation fact ref、buffer
- 淘汰项必含 reason、constraint refs、evidence refs
- 可选：`previous_plan_ref`、`solver_trace_summary`、`display_notes`
- 硬失败：plan status 与 violations 不一致；关键 hard 依赖 unresolved unknown/conflicting 却标 feasible；关键 estimated 未处理不确定性或保守边界可能跨越 hard 却标 feasible
- estimated 边界：若保守边界下仍满足 hard，plan 可 feasible，但 fact 仍显示 estimated

### 2.8 `plan-diff.json`

- Schema：`schemas/plan-diff.schema.json`
- 生产者：WU6 deterministic diff
- 消费者：renderer、Review、用户解释
- 必填：`previous_plan_id`、`new_plan_id`、`change_score`、`weights`、`changes[]`、`unchanged_summary`
- 每项 change 必填：`type`、`entity_id`、`from`、`to`、`cost`、`reason`、`constraint_refs`
- 默认配置初值：保持活动/日期/相对顺序 0；同日换序 1；同日换时段 2；换天 3；换基地 5；删除 6；新增必须在 config 显式定义
- 硬失败：`change_score != sum(changes.cost)`，或 change 无触发 constraint ref

### 2.9 `violations.json`

- Schema：`schemas/violations.schema.json`
- 生产者：约束检查器、planner
- 消费者：renderer、Review、重排解释
- 必填：`plan_id`、`plan_status`、`violations[]`、`conditions[]`、`candidate_conflict_sets[]`、`proofs[]`
- violation 必填：`violation_id`、`kind`、`severity`、constraint refs、evidence fact refs、`proof_status: proven|candidate|uncertain`、`reason`、`user_message`
- `proven_infeasible` 至少有一个可回放 proof rule、输入下界、单位和计算过程；含 unknown/conflicting 的输入不能参与 proof
- 最小化未验证前字段和文案只能叫 `candidate_conflict_set`，不得叫 minimal conflict set
- 硬失败：proven status 无 proof；plan/violations status 不一致；候选冲突被写成证明

### 2.10 `trip-card.html`

- Contract：`schemas/trip-card.contract.md`；不是 JSON Schema
- 生产者：WU7 renderer
- 消费者：浏览器、用户、同行者、验收记录
- 必填 meta：schema version、plan ID、plan payload SHA256
- 必填 manifest：artifact ID、producer/run、plan/evidence/violations refs + hashes、generated_at
- 必填用户区块：总体状态、条件/风险、住宿基地理由、分天时间轴、交通/缓冲、证据标签、淘汰理由；replan 时另有变更摘要
- renderer 只能表达上游事实和决策，不能补写开放时间、交通时长或“推荐理由事实”
- 硬失败：引用/hash/关键区块缺失，或内容未转义

## 3. v1 能力 A 的最小冻结接口

- `request.destination.selection_mode`：`user_supplied|discovery_required`
- destination 与 POI 共用稳定 candidate envelope、位置/待解析位置和 source refs；初始候选不强制 evidence refs
- `candidate_type=destination`；只有 v1 真正展示的推荐 destination 强制粗可行性与独立粗计划引用
- 约束 target 绑定稳定 ref，不以城市名作主键
- plan 始终引用 destination candidate ID
- v1 内部评分不泄漏给 C—H；v0 不定义完整 DSL、神秘匹配分或可达圈实现

## 4. 可行性状态、用户语言与证据传播

| 状态 | 切换条件 | 允许用户文案 |
|---|---|---|
| `feasible` | 结构满足所有 hard/environment；无 unresolved unknown/conflicting；关键估算在保守边界下仍满足 | “已找到满足当前硬约束的方案；其中估算事实及缓冲如下。” |
| `conditionally_feasible` | 有结构，但 hard 依赖 unknown/conflicting，或估计未处理不确定性/可能跨界 | “已找到结构方案，但需满足/核验以下条件。” |
| `proven_infeasible` | 确定性规则或完备检查产生可回放 proof | “已证明当前这组约束不可同时满足，依据如下。” |
| `no_plan_found` | 有界启发式无结果且无 proof | “当前算法未找到满足条件的方案，尚不能证明无解。” |

执行顺序：先 proof，再启发式；有结构则传播 unknown/conflicting 并检查估计保守边界；无结构且无 proof 只能 `no_plan_found`。新 evidence 只能通过重跑改变状态，renderer 不能升级状态。

v0 可证明冲突：

- 同一稳定 POI 同时在 enabled must_visit 与 excluded
- 必去活动最短时长下界和超过总时间
- 最早可达下界晚于有有效来源的闭馆时间
- 交通下界 + 活动下界超过某日时间窗
- 不换酒店与基地—必去点通勤上限存在可穷举矛盾
- 同一人/活动的互斥时间窗确定重叠

传播规则：

- hard 依赖 unresolved conflicting/unknown → 不能 feasible，并列来源/待补事实
- hard 依赖 estimated → 必须列方法、buffer/uncertainty、保守边界；保守边界满足可 feasible，否则 conditional
- soft 可用 estimated 排序但保留标签，不能升级为 hard veto
- fact display status 与 plan status 同时展示，不能互相覆盖

## 5. 六项 fixture specification

这些全部是由冻结 `PLAN.md` 与 v3.1 人工写定 expected 的合成确定性 fixture，不是真实旅行、检索或地理 anchor。江西真实 fixture 只在 WU8 以用户资料和一手/API 数据建立。

### `fixture_01_feasible`

- 输入：最小 request/constraints/candidates/evidence；无 unknown/conflicting；estimated 路时有 buffer 和满足 hard 的保守上界
- 预期：feasible、无 hard violation；必去活动唯一且在窗内；activity/leg 有 constraint/evidence refs；fact 仍 estimated；文案展示估算与缓冲
- 不覆盖：检索、真实路线、全局最优
- red/实现：WU5，具体字段断言或已存在接口的 `NotImplementedError`

### `fixture_02_direct_conflict`

- 输入：同一 candidate ID 同时在 enabled must_visit/excluded
- 预期：proven_infeasible；固定 proof rule；refs 恰为两个 constraint ID；无 plan days；不以 candidate conflict 冒充 proof
- 不覆盖：同义词、最小化
- red/实现：WU4

### `fixture_03_uncertain_dependency`

- 输入：结构可排；路时 api estimate；开放状态 unknown
- 预期：conditionally_feasible；两个条件各回指 fact；外显 estimated/unknown；文案不含“已确认可行”
- 不覆盖：真实 API 准确率、网页时效
- red/实现：WU3/WU4

### `fixture_04_replan_stability`

- 输入：旧计划两个同日有序活动；新约束只改一个时段
- 预期：只出现一个 change；type/cost 正确；score 为成本和；reason 回指约束；unchanged summary 精确
- 不覆盖：权重全局最优或主观偏好
- red/实现：WU6

### `fixture_05_evidence_state_mapping`

- 输入：verified/current/official、stale、api estimate、rule derived、conflict、unknown、user supplied 无外证的 truth table
- 预期：verified 门槛完整；stale→sourced；estimate→estimated；conflict 优先；unknown 不升级；LLM 不在 sources；user supplied 无外证不 verified
- 不覆盖：自动判定来源权威、真实网页抽取
- red/实现：WU3

### `fixture_06_no_plan_found_not_infeasible`

- 输入：有界启发式在预算内返回空；无 direct proof
- 预期：no_plan_found；proofs 空；candidate conflict 标 candidate；文案写“尚不能证明无解”，不写无解/不可能/已证明冲突/没有任何可行方案
- 不覆盖：完备 solver 或真正无解证明
- red/实现：WU4/WU5

有效 red 只能是对已加载、结构有效输入的具体字段/行为断言失败，或已存在可导入接口明确抛出 `NotImplementedError`。模块不存在、import/路径失败、依赖缺失、malformed fixture、0 cases 都不是有效 red。WU1 的结构转绿不代表 WU3—WU6 业务能力已实现。

## 6. WU1 实施清单与禁止项

WU1 的新 Plan 至少覆盖：

- 十项实际 JSON Schema/HTML contract，以及共享 envelope/source/origin 判别联合
- 稳定 artifact/candidate/constraint/fact/activity ID 类型
- 六项 fixture 的 README、输入、人工 expected；结构 fixture 与未来行为 fixture 分层
- strict validator：缺字段、类型错、非法 union、hash/provenance 断裂硬失败，不注入默认
- 可导入最小接口，使 red 来自具体断言或 `NotImplementedError`
- clean/dirty 配对、强字段断言、来源/覆盖/不覆盖声明
- YAML/Schema/test 依赖选型、license、Windows 实测和锁定

WU1 禁止实现 evidence 映射、约束 proof、planner、replan、HTML renderer、真实 POI/API 或江西行程。每一项业务能力仍需在其工作单元先 red 后 green。
