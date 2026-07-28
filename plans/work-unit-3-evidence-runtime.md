# WU3-ER · Evidence Runtime MVP Plan

Plan version: v0.1  
Status: PENDING_HUGIN_APPROVAL  
Decision: CANDIDATE_LOCAL_EVIDENCE_ONLY

## 1. 目标与基线

WU3-ER 只消费已批准的 WU2R-DOR 离线输出，生成候选级
Evidence artifact、确定性 Evidence gate 和运行摘要。

本单元回答：当前候选记录与 identity accounting 是否足以进入后续处理；
若不足，哪个显式门阻断？

2026-07-28 实测：

```text
branch/HEAD: main / a1a79665d7eaba1cd3f1224b88c8c316e4d86051
worktree/remotes/stashes: clean / 0 / 0
tests/schemas: 186 passed / 11
fixtures/documents/dirty cases: 7/40/7
network attempts/temporary residue: 0/0
```

WU2R-FER、WU2R Resume、WU2R-DOR 已批准；旧 WU2/WU2R 的
`BLOCKED` 历史不改写、不恢复。

handbook 从固定路径 `<handbook>` 的
`origin/main` 读取；local/origin 均为
`6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`，ahead/behind `0/0`。
执行规则为 R10 硬失败、PER 审批、精确 Scope、fixture-first。

## 2. 冻结输入与可表达性

| 输入 | SHA256 |
|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `common.schema.json` | `83FE17127A545D168A16F58911564E53D2E17AFF826B6D34437D873ECF8E75BE` |
| `candidates.schema.json` | `3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2` |
| `evidence.schema.json` | `54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B` |
| `recovery.py` | `C0E098DD4AB997727A0EFBCCC9C396AC480DEEB3477DBF4CDCB5E31A34E0D8BA` |
| `schema_validation.py` | `2061084E8AC27DF4C08F63DC264A2612685980D966AA5291A46660BE3F1CC017` |
DOR Plan/Review 与 anchor case/replay 的完整 hash 由 C4 从实际文件机械读取。

当前 Evidence Schema 可表达 candidate subject、任意 JSON value，以及
support/derivation/freshness/display、normalization 和 local source refs，
所以不存在 Schema 可表达性 blocker。

DOR 四输出没有保留 `api_response` source 所需的
`operation/retrieved_at/request_fingerprint` 完整组合。禁止把 snapshot
hash 冒充 request fingerprint、把 artifact 时间冒充采集时间，或构造
未访问网页 source。

本 MVP 保守映射：

映射为 `support_status=unknown`、`derivation=rule_derived`、
freshness 三个时间均 null 且 status unknown、空 sources、
`display_status=unknown`、空 conflict refs。

`source_reference` 是可回读的 candidate-local locator 事实，不冒充
Evidence `api_response` source。若要求输出 `sourced/verified` 或非空
结构化 sources，必须另建 provenance contract remediation。

## 3. Evidence 边界

每个 Candidate 恰好生成 `provider_identity`、`provider_category`、
`location`、`source_reference` 四类事实，并按此顺序输出。

映射规则：

- provider identity 为 `name/record_type/record_id` 闭合对象；
- provider category、location、source refs 为原值的深拷贝；
- `unit` 为 null，original/normalized value 语义等价；
- normalization rule 为 `candidate-local-copy-v1`；
- display rule 为 `unknown-without-structured-source-v1`；
- derivation input fact refs 为空；
- facts 按 `(candidate_id, frozen_field_order)` 排序。

fact、evidence-set、run、artifact ID 复用现有稳定 identifier/hash helper，
不复制 ID 算法。

Evidence envelope 使用 Candidate 的冻结 replay 时间；producer 为
`trip-decider-evidence-runtime/0.1.0`；parent 只引用当前 Candidate；
input hashes 为 DOR 四个文件实际 byte SHA256；pipeline stage 为
`wu3-candidate-local-evidence`；payload hash 复用 canonical helper。

不得生成 label preference、identity correctness、推荐、热度、排名、
route feasibility、itinerary quality 或城市专属字段。

## 4. Ambiguity 边界

`matched/ambiguous/unmatched` 唯一来源仍为 `seed-accounting.json`。
Evidence 不增加 ambiguity 字段，不把 alternatives 塞入 fact value，
不把 ambiguity 伪装成 relation。

Gate 原序保留 seed 与全部 refs：

- matched 恰好一个已解析 ref；
- ambiguous 至少两个不同且已解析 ref；
- unmatched 零 ref；
- 其他组合是输入契约错误，不是 gate 结果。

不得按 label、category、数组位置、first、nearest、popularity 或 LLM
选择 identity。

## 5. Completeness slots

`required_slots` 固定为上述四类事实。

满足条件：

1. provider name/type/ID 均为非空字符串；
2. categories 至少一个闭合条目；
3. location 是含有限坐标与显式 CRS 的 coordinates；
4. Candidate 和 location 各有至少一个合法 source locator；
5. Candidate 与 record-local fact 的四类值精确一致；
6. Candidate 与 fact 一一对应，无重复、缺失或额外项。

`evidence_complete` 仅表示结构与引用完整，不表示权威、时效、现实存在、
用户意图或可行性已验证。缺 slot 时保留 Candidate，输出 false 及排序后的
`missing_slots`；不得补默认 provider、CRS、category、location 或 source。

## 6. Gate 规则

candidate result：

```text
candidate_ref, evidence_complete, required_slots, satisfied_slots,
missing_slots, fact_refs, support_ceiling, hard_conflict
```

`support_ceiling` 固定为 `unknown`，避免被误读为已核实。

seed result：

```text
seed, identity_status, candidate_refs, generation_status, block_reasons
```

确定性优先级：

1. ambiguous → `BLOCKED_IDENTITY_AMBIGUOUS`；
2. unmatched → `BLOCKED_IDENTITY_UNMATCHED`；
3. matched 且 Candidate 不完整 → `BLOCKED_EVIDENCE_INCOMPLETE`；
4. matched、唯一 ref、完整、refs 全解析且无 conflict → `ELIGIBLE`。

`generation_allowed` 仅在非空 seed 列表全部 `ELIGIBLE` 时为 true。
`ELIGIBLE` 只允许把记录交给后续阶段；不提升 unknown，不授权硬事实、
推荐或可行性结论。当前 anchor 含 ambiguous/unmatched，整体必须 false。

hard conflict 指所需 fact 为 `conflicting` 或有 conflict refs；
本 MVP 不执行 conflict resolution。

## 7. 接口、输入与输出

```python
run_evidence_runtime(
    recovery_root: Path,
    output_root: Path,
) -> ValidationResult[EvidenceRuntimeSummary]
```

`recovery_root` 固定读取 `candidates.json`、`seed-accounting.json`、
`record-local-facts.json`、`run-summary.json`，不扫描或补找 fixture。

严格 UTF-8/JSON 读取复用现有 loader。Candidate 与生成 Evidence 复用
现有 Schema registry/validator；subject、locator、跨文档一致性由 runtime
业务门检查，不创建第二套 Schema validator。

输出恰好为 `evidence.json`、`evidence-gate.json`、`run-summary.json`。

Gate 与 summary 是 runtime control documents，不注册新 artifact。
summary 记录 DOR byte identity、Candidate/Evidence ID/hash、candidate 与
seed counts、network attempts、Evidence/Gate file hashes 和 completion。
summary 不嵌入自身 hash，避免自引用。

JSON 为 UTF-8 无 BOM、sorted keys、紧凑 separators、末尾 LF。
双 clean roots 字节一致；非空 output root 硬失败；三文件使用 exclusive
temp、fsync、replace，失败 rollback，安装后重读 bytes/hash。

继续使用七字段 `ValidationProblem`。Schema/load 问题原样传播；
runtime 稳定码为 `EVIDENCE_RUNTIME_INPUT_INVALID`、
`EVIDENCE_RUNTIME_REFERENCE_INVALID`、`EVIDENCE_RUNTIME_OUTPUT_ROOT_INVALID`、
`EVIDENCE_RUNTIME_OUTPUT_HASH_MISMATCH`、`EVIDENCE_RUNTIME_NETWORK_ATTEMPTED`。

错误不得泄漏实际输入值、第三方异常或 secret。

## 8. Fixture-first 与 Red → Green

只新增 `tests/test_wu3_evidence_runtime.py`，恰好六个 test：

1. ER01：7 candidates × 4 facts，Evidence Schema/integrity green；
2. ER02：28 subjects 全解析，source-reference 精确回读 Candidate；
3. ER03：江岭、李坑两个 matched seed 精确为 ELIGIBLE；
4. ER04：篁岭保持 ambiguous、两个 refs 原序保留并阻断；
5. ER05：庆源保持 unmatched、零 refs、无 placeholder；
6. ER06：双 root byte-identical、network 0、rollback、非空 root 不覆盖。

测试通过真实 DOR 离线入口在系统临时目录生成输入；existing anchor 不改。
expected IDs、seed、counts、status、字段值独立写定，不用被测函数生成。

C1 只提供 types、稳定签名和显式 `NotImplementedError` stub。
Red/Green 使用逐字符相同命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu3_evidence_runtime -v
```

Red：`6 tests / 0 pass / 0 failures / 6 NotImplementedError`；其他错误和
network 为 0。Green：`6/6`，failures/errors/network 为 0。

完整入口目标：

```text
existing/WU3/total: 186/6/192 passed
fixtures/documents/dirty cases: 7/40/7
network attempts/temporary residue: 0/0
```

## 9. Scope 与 commits

唯一五路径白名单：

```text
plans/work-unit-3-evidence-runtime.md
src/trip_decider/evidence_runtime.py
tests/test_wu3_evidence_runtime.py
scripts/verify_wu3_evidence_runtime.ps1
docs/reviews/work-unit-3-evidence-runtime-review.md
```

C3 只能修改 runtime。禁止修改 schemas、fixtures、recovery、Resume/FER、
adapters、validators、dependencies、existing tests、`PLAN.md`、handbook。
禁止网络、LLM、identity selection、planner、route、推荐和 WU4/WU5。

| Commit | Message | 职责 |
|---|---|---|
| C0 | `docs: record WU3 evidence runtime plan` | 获批 Plan 原文 |
| C1 | `chore: add Evidence Runtime interface` | types、错误码、stub |
| C2 | `test: add failing Evidence Runtime cases` | 六个有效 red |
| C3 | `feat: implement candidate Evidence Runtime` | runtime only |
| C4 | `chore: add Evidence Runtime verification entry` | 192/scope/hash/scans |
| C5 | `docs: prepare WU3 evidence runtime review` | 独立 Review |

不 amend/squash 有效 red；除 C2 外每个 commit 完成时必须 green。

## 10. 完成判定（16 条）

1. Plan 获批字节/hash 不变；
2. baseline、handbook、冻结输入 hash 对账；
3. 五路径无越界；
4. Evidence 恰好四类 candidate-local facts；
5. subjects/refs 全解析到当前 Candidate；
6. support/display 不高于 unknown；
7. ambiguity 只来自 seed accounting；
8. gate 按固定优先级输出；
9. 当前 anchor 全局 generation_allowed false；
10. Evidence Schema/integrity/hash green；
11. Red 精确六个 NotImplementedError；
12. Green 同命令 6/6；
13. 完整回归 192/192；
14. fixtures 保持 7/40/7；
15. network/residue 0，atomic/no-overwrite/determinism 通过；
16. Review 可独立复核 Git、hash、R10、scope 与全部判定。

## 11. Blocking

立即停止：

- Evidence Schema hash/语义变化或拒绝上述 unknown facts；
- 要求无完整 source metadata 的事实标 sourced/verified；
- 需要修改 Recovery、Resume、FER、adapter、validator、Schema 或 fixture；
- 需要新数据、网络、LLM、identity 选择或城市特例；
- C2 不是精确六个 NotImplementedError；
- C3 需要修改测试或白名单外路径；
- atomic、determinism 或既有 186 tests 无法保持；
- 发现 secret、未授权数据或能力过度声明。

低风险的测试文字、expected 顺序、hash literal、PowerShell 编码或命令
格式勘误，可独立 commit 并在 Review 记录；业务 expected、公开接口或
正式 artifact 语义变化必须停止。

批准前不进入 Execute，不创建实现，不 commit，不开始后续工作单元。
