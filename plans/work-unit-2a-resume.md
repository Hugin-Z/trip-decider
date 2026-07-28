# Work Unit 2A Resume Plan

Plan version: v0.1
Status: PENDING_HUGIN_APPROVAL
Work unit: WU2A-Resume · Open Data Anchor Recovery Resume
Prepared: 2026-07-28
Execution approval required: `批准执行 Work Unit 2A Resume`

## 1. 当前状态与任务定位

### 1.1 历史状态

以下状态是本工作单元的冻结输入：

```text
WU0      APPROVED
WU1      APPROVED
WU1R     APPROVED
WU1C     APPROVED
WU2      BLOCKED
WU2A     INVESTIGATION_BLOCKED
WU2A-R   APPROVED
```

当前指令是 WU2A-R 获批的审批事实。仓库中的 WU2A-R Review 仍按历史
字节记录 `READY_FOR_HUGIN_REVIEW`；WU2A-Resume 不修改该 Review 来倒写
审批状态。

WU2A-Resume 是新的 PER 工作单元。它不会修改或重新解释：

- WU2 的五个既有 commit；
- WU2 `BLOCKED`；
- WU2A C0/C1；
- WU2A `INVESTIGATION_BLOCKED`；
- 旧失败 ledger；
- WU2 Review 不存在这一事实；
- WU2A-R 的六个实际 commit 和 Review。

旧调查是一次真实但证据捕获不完整的调查，不是测试失败。新运行不得覆盖、
删除或补写旧 attempt。

### 1.2 唯一目标

WU2A-Resume 只做一次新的、独立预算的受控开放数据调查：

```text
frozen WU2A query ladder
        +
approved WU2A-R harness
        ↓
attempt_group = WU2A-resume-001
        ↓
APPROVED_ACQUISITION_RECIPE
or bounded negative / blocked conclusion
```

成功标准不是找到五个景点，也不是恢复 WU2。成功标准是形成一份合法、
可追踪、可重放查询 recipe，且其已观察 response 满足冻结 adapter 输入边界。

### 1.3 明确不负责

本工作单元不负责：

- 修改 query ladder 之外的查询；
- 修改 acquisition harness；
- 修改 adapter、Schema、validator、source policy 或 dependency；
- 创建 anchor、fixture、candidate、evidence 或 route response；
- 调用 OSRM、Nominatim、商业地图、第二 Overpass 实例或网页爬虫；
- 恢复 WU2 C5/C6；
- 开始 WU3、推荐、规划、排序或路径优化；
- 证明 OSM 全局完整性或未来 response byte-identical。

## 2. 实测基线与冻结输入

### 2.1 Repository baseline

Plan 阶段实测：

```text
repository: <repo>
branch: main
HEAD: f4e778f7fe2fc92ac6698ee96c36447f3d24aab1
worktree: clean before this Plan
remote count: 0
stash count: 0
WU2 Review exists: false
```

当前完整非网络回归：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_harness -q
```

实测：

```text
Ran 143 tests
OK
exit code 0
```

### 2.2 必读上下文与 SHA256

| Path | Bytes | SHA256 |
|---|---:|---|
| `docs/wu2a-anchor-decision.md` | 11531 | `570649D6B7287B48F3C396E536AC05EF31D949FC7AF960EF2D3DFEB17D4A9F6D` |
| `docs/reviews/work-unit-2a-remediation-review.md` | 15905 | `DBA77226011F013D687FB3C6AF6085C692217167803E3280246EC70ABA93338F` |
| `plans/work-unit-2-anchor-recovery.md` | 28097 | `432318A68D13774646CF3A1E5BE6057D5C92DE7CE600E06FA6CF52BD0CD92E90` |
| `plans/work-unit-2a-remediation.md` | 27513 | `FD0DA659873A275944DE7FCC9C1E4D1D27EE9BD7F61F40F4A3371493173008B9` |
| `docs/wu2-source-decision.md` | 7235 | `E667ABCF6BEBFB522AE0EA76AFDD6EB628E11214B33773045AA5EC8B8C7FEA62` |
| `scripts/acquisition_harness.py` | 12845 | `AE6487D7F35E6A1CE351C07FD83DA219214705F1D3AC00611F5D7B9EF49559F9` |

以下同样冻结：

| Path | SHA256 |
|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `plans/work-unit-2-real-world-ingestion.md` | `894D5844E140BF62EC1DB89B1BE318EB4945FF4A0BF8B139E9B82C0B4929BA2C` |
| `docs/real-world-source-policy.md` | `B89D0836BCC17DD1D52CA215F38EF290134251295ECAC183BA7D54C45A1C4989` |
| `docs/real-world-contract-extension.md` | `BD2280BFA2C51F2FEC8521F16BB7DE73667A39142FD89E04F6A515CB42B8963E` |
| `tests/test_wu2a_acquisition_harness.py` | `C924608383A6382C18E232368809F81114CA44C6384638C4B18B35A43F9FA12B` |
| `pyproject.toml` | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` |
| `requirements.lock` | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` |

11 个 Schema 继续使用 WU2A-R Review §12 已核实的 hash 基线，Execute
C0 前逐个重算；任一不一致即停止。

### 2.3 Handbook

固定只读路径：

```text
<handbook>
```

Plan 阶段执行 `git fetch origin --prune` 后实测：

```text
local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree before/after fetch: clean
```

从 `origin/main` 完整重读：

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

直接影响：

- R10：旧缺失值不重建；新数字、hash、count、timestamp 只能来自运行；
- PER：本文件获批前零数据调用，Execute 后只进入一次 Resume Review；
- Scope：Git 只允许三个路径，系统临时文件不形成第四个仓库路径；
- Fixture-first：不创建语义 fixture；先对 pending decision 做单一预期失败，
  再以同一临时 validator 验证最终真实 decision。

## 3. 旧失败证据、Resume 必要性与冲突裁定

### 3.1 旧失败保持

旧 decision 的冻结事实：

```text
path: docs/wu2a-anchor-decision.md
sha256: 570649D6B7287B48F3C396E536AC05EF31D949FC7AF960EF2D3DFEB17D4A9F6D
status: INVESTIGATION_BLOCKED
ledger_complete: false
```

旧保守 accounting：

```text
GET: 1
Overpass POST: 2
byte-identical retry: 1
exact_call_count_independently_emitted: false
```

旧 O1 HTTP 400 被错误归为 transport failure，消耗唯一 retry，随后进程在
完整 ledger emission 前退出。G0/O1/O1-R1 的缺失 request/response evidence
保持 `null`。

### 3.2 为什么允许新运行

新运行不是重置旧计数，也不是把旧 call 当作未发生。它有新的独立
authorization 和 attempt group，理由是：

- 旧 harness 的 ledger emission 不可靠；
- HTTP response/transport 分类错误；
- 旧 request bytes 和 response metadata 无法诚实恢复；
- WU2A-R 已通过离线 fixture 和 Review 修复并验证这些 failure paths。

新 decision 同时引用旧 SHA256 和新 attempt group，使两个历史并存。任何
combined summary 都分别报告 old conservative accounting 与 new measured
accounting，不把它们合并成一个伪精确总数。

### 3.3 “删除记录”与冻结 harness 的边界

当前 WU2A-R harness 的冻结 14 字段是：

```text
attempt_id, purpose, endpoint, method, request_sha256,
started_at, completed_at, status, http_status, response_bytes,
response_sha256, content_type, error_class, retry_decision
```

它没有 deletion 字段，也不保存 raw response；body 只在进程内存中传给
deterministic postprocess。为了不虚构 harness 能力，本 Plan 采用两个相邻、
可追溯但不混称的 evidence surface：

1. `harness_ledger`：由冻结 WU2A-R harness 生产 attempts/retries；
2. `attempt_cleanup`：由 Resume orchestration 对每个 qualified attempt
   机械记录：
   - `raw_capture_created=false`；
   - `raw_capture_deletion_status=not_applicable_no_capture_file`；
   - `ledger_path_category=system_temp_random_file`；
   - ledger/helper 的最终 deletion 和 residue count。

因此每个 attempt 都有显式 deletion outcome，但 Plan 不声称该字段存在于
harness 的 14 字段内。若审批要求 deletion 必须字面进入 harness ledger，
则会需要修改已完成的 WU2A-R，触发 blocking，本 Plan 不可执行。

### 3.4 Compatibility token 歧义裁定

旧批准 Plan 对 `ADAPTER_COMPATIBLE_ONLY` 的定义是：

> response 满足冻结 adapter 输入，但原 WU2 target coverage 不足。

当前指令中“找到数据但不满足 WU2 adapter”的叙述与该 token 字面存在歧义。
本 Plan 保持旧已批准定义：

- 不满足 adapter：不得批准 recipe，compatibility 为
  `NOT_ADAPTER_COMPATIBLE`；
- 满足 adapter 但不足以恢复原 WU2：可记
  `ADAPTER_COMPATIBLE_ONLY`；
- 无论何种 compatibility，本工作单元都不恢复 WU2。

## 4. 新独立预算

### 4.1 Attempt group

```text
attempt_group: WU2A-resume-001
```

预算：

```yaml
scheduled_operations:
  geofabrik_poly_get: 1
  overpass_post: 3
transport_retry:
  total_across_group: 1
forbidden:
  osrm: 0
  nominatim: 0
  commercial_map: 0
  alternate_overpass: 0
  bbbike: 0
  wikidata_query_service: 0
```

`scheduled_operations` 与物理 attempts 分开统计。一次 transport retry 会增加
一个物理 HTTP attempt，但不会成为第二个 scheduled query。全组只有一个
共享 retry token：

```text
retry_remaining = 1
```

每次调用 `run_acquisition` 前，将 `max_transport_retries` 设为当前
`retry_remaining`；调用后按实际 `retries` relation 数扣减。任何结果使
全组 relation 数超过 1，立即停止并标记 harness/runner contract failure。

### 4.2 Allowed endpoints

唯一 GET：

```text
https://download.geofabrik.de/asia/china/jiangxi.poly
```

唯一 POST endpoint：

```text
https://overpass-api.de/api/interpreter
```

不在 Execute 中重新选择 endpoint，不切换实例。

### 4.3 HTTP transport boundary

真实 transport 只存在于系统临时 Resume helper，不写入仓库。它使用 Python
3.11 标准库：

```text
urllib.request
urllib.parse
json
hashlib
tempfile
```

冻结参数：

```text
User-Agent: trip-decider-wu2a-resume/0.1 non-production-research
Overpass Content-Type: application/x-www-form-urlencoded; charset=UTF-8
HTTP timeout: 40 seconds
Overpass query timeout: 25 seconds
```

POST 的实际 entity bytes 必须由：

```python
urllib.parse.urlencode({"data": query_text}).encode("ascii")
```

机械产生。Decision 同时记录：

- LF、UTF-8、无 BOM 的 `query_utf8`；
- `query_sha256`；
- percent-encoded entity 的 `request_sha256`；
- endpoint、method 和 headers profile。

不得在 HTTP 400 后修改 query、encoding、header 或 endpoint 后重试。

GET 的 harness `request_bytes` 是 exact endpoint ASCII bytes；injected
transport 必须从这些 bytes 解码并逐字符等于 allowlist URL，不能忽略传入
bytes 后使用另一个 URL。

## 5. Attempt 关联与 Resume Decision contract

### 5.1 新文档

新增：

```text
docs/wu2a-resume-decision.md
```

旧 `docs/wu2a-anchor-decision.md` 不修改。新文档必须包含：

```text
1. preserved historical states
2. previous investigation reference and SHA256
3. new authorization and independent budget
4. source/license/replay basis
5. exact query ladder
6. machine-readable resume ledger
7. deterministic selection analysis
8. recipe or bounded negative/blocked conclusion
9. WU2 compatibility classification
10. cleanup, forbidden-call and non-capability report
```

### 5.2 Qualified attempt ID

`run_acquisition` 的 `attempt-0001` 是单次 harness call 的本地 ID。Decision
使用不覆盖原字段的 qualified reference：

```text
WU2A-resume-001:G0:attempt-0001
WU2A-resume-001:G0:attempt-0002
WU2A-resume-001:O1:attempt-0001
...
```

每个 qualified record 包含：

- `attempt_group`；
- `operation_id`；
- 原始 harness attempt 14 字段；
- 对应 retry relation；
- `query_sha256` 或 GET URL hash；
- `observed_element_count`；
- `source_base_timestamp`，不存在时显式 `null`；
- `selection_result` 和稳定 reason token；
- `attempt_cleanup`。

Qualified ID 由字符串拼接机械生成，不根据 response 内容推断。

### 5.3 Resume ledger top-level

唯一 fenced JSON ledger 至少包含：

```json
{
  "decision_status": "INVESTIGATION_IN_PROGRESS",
  "attempt_group": "WU2A-resume-001",
  "previous_investigation": {
    "path": "docs/wu2a-anchor-decision.md",
    "sha256": "570649D6B7287B48F3C396E536AC05EF31D949FC7AF960EF2D3DFEB17D4A9F6D",
    "status": "INVESTIGATION_BLOCKED",
    "ledger_complete": false
  },
  "budget": {},
  "operations": [],
  "retry_relations": [],
  "forbidden_call_counts": {},
  "committed_raw_response_count": 0,
  "committed_coordinate_pair_count": 0,
  "fixture_count_created": 0,
  "approved_acquisition_recipe": null
}
```

最终 `decision_status` 只允许：

```text
APPROVED_ACQUISITION_RECIPE
OPEN_DATA_ROUTE_NOT_FEASIBLE
INVESTIGATION_BLOCKED
```

`INVESTIGATION_IN_PROGRESS` 只允许存在于 C1 未提交 worktree 的预验证阶段。

## 6. 数据与查询策略

### 6.1 G0 — Geofabrik `.poly`

用途仅是产生 sourced Jiangxi investigation bbox，不是行政边界。

标准库 parser：

- 只接受 `.poly` 文本结构和显式 numeric vertices；
- 检查 UTF-8、非空 polygon、经纬度数值及合法范围；
- 机械计算 `south/west/north/east`；
- 不选择县、POI 或 relation；
- 不保存 vertex list；
- Decision 只记录 response hash/bytes、vertex count 和四值 bbox。

G0 非 2xx、transport exhaust、parse failure 或超限 response 使结论成为
`INVESTIGATION_BLOCKED`，且不发起 O1。

### 6.2 O1 — exact relation discovery

从旧 WU2A Plan 原样保留模板：

```overpassql
[out:json][timeout:25][bbox:{SOUTH},{WEST},{NORTH},{EAST}];
(
  rel["boundary"="administrative"]["name"="婺源县"];
  rel["boundary"="administrative"]["name:zh"="婺源县"];
  nwr["place"]["name"="婺源"];
  nwr["place"]["name:zh"="婺源"];
);
out center tags;
```

只有一个 relation 同时由显式 `boundary=administrative`、`name`/`name:zh`
和返回的 admin tags 唯一支持时，relation ID 才能进入 O2。不得按第一条、
最近、相似名称或人工知识选择。

O1 HTTP 400/404/429/5xx 或 transport exhaust 不触发 O2/O3；它产生
`INVESTIGATION_BLOCKED`，因为 query ladder 没有获批的请求修正或 alternate
endpoint。O1 HTTP 200 的 zero/multiple relation 不是 transport failure，
跳过 O2，进入预注册 O3。

### 6.3 O2 — unique relation area

仅在 O1 唯一 relation 时执行：

```overpassql
[out:json][timeout:25];
rel(id:{CAPTURED_RELATION_ID})->.county;
.county map_to_area->.scope;
(
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["amenity"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["historic"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["leisure"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["natural"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["place"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["tourism"];
);
out center tags;
```

O2 返回满足 §6.5 的非空 selection 时停止，不调用 O3。O2 HTTP 200 但
zero/non-selectable/ambiguous 时进入 O3。O2 HTTP failure 或 transport exhaust
产生 `INVESTIGATION_BLOCKED`，不把失败替换成 bbox 成功。

### 6.4 O3 — sourced bbox fallback

只有 O1 无唯一 relation或 O2 HTTP 200 但无可批准 selection 时执行：

```overpassql
[out:json][timeout:25][bbox:{SOUTH},{WEST},{NORTH},{EAST}];
(
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["amenity"];
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["historic"];
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["leisure"];
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["natural"];
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["place"];
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["tourism"];
);
out center tags;
```

O3 不扩大 names、categories 或 region。它是最后一个 POST。

### 6.5 Deterministic selection

每个 selected object 必须：

- `type` 是 `node`、`way` 或 `relation`；
- `(type,id)` 在 response 内唯一；
- primary `tags.name` 是固定集合中逐字符相同的非空字符串；
- 至少一个 frozen category key 有非空字符串值：
  `amenity/historic/leisure/natural/place/tourism`；
- node 有显式 `lat/lon`，way/relation 有显式 `center.lat/center.lon`；
- 不包含由 first-result、distance、popularity、fuzzy、language fallback、
  LLM 或人工判断产生的选择。

Decision 只保存：

```text
type
id
tags.name
matched category key/value
coordinate_shape = node_lat_lon | reported_center
```

不保存 numeric coordinate pair、response excerpt 或完整 tags。

## 7. 结论状态与成功条件

### 7.1 APPROVED_ACQUISITION_RECIPE

必须同时满足：

- source 和 license/replay basis 来自冻结 WU2 source policy；
- endpoint、query bytes/hash、request hash 和 response hash 可回读；
- response 非空且 deterministic selection 至少一个；
- selected summary 满足 frozen adapter structural boundary；
- attempt ledger 完整；
- cleanup 完整；
- 无 forbidden call、raw commit、coordinate pair 或 fixture。

Recipe 至少包含：

```yaml
source: OSM through Overpass
endpoint:
method: POST
query_utf8:
query_sha256:
request_sha256:
geographic_scope:
selection_predicate:
observed_element_count:
selected_count:
observed_response_sha256:
license:
  identifier: ODbL-1.0
  url: https://opendatacommons.org/licenses/odbl/1-0/
  attribution: © OpenStreetMap contributors
replay_policy:
compatibility:
limitations:
```

OSM 可变；`replay_policy` 表示 exact query 可作为新 attempt 重跑和比较，
不保证未来 response hash 相同。

### 7.2 OPEN_DATA_ROUTE_NOT_FEASIBLE

只在所有适用的 G0/O1/O2/O3 都得到完整、可解析、可审计 response，但冻结
predicate 仍无法产生 adapter-compatible selection 时使用。其含义严格限于
本 attempt group、endpoint、query ladder 和时间点，不得写成“OSM 无数据”
或“开放数据永远不可行”。

### 7.3 INVESTIGATION_BLOCKED

用于：

- transport retry exhaust；
- HTTP response failure；
- parse/size/cleanup/ledger failure；
- required source-policy invariant 不满足；
- helper 无法安全删除；
- 其他导致 bounded investigation 未完整到达可判定终点的条件。

它是新 group 的技术结论，不改变旧 WU2A decision。

### 7.4 Compatibility

```text
WU2_C5_COMPATIBLE
  selected target identities satisfy the old WU2 POI acquisition boundary;
  this is still not authority to resume C5/C6.

ADAPTER_COMPATIBLE_ONLY
  response is structurally usable by the frozen OSM adapter, but old WU2
  target coverage or later route prerequisites are incomplete.

NOT_ADAPTER_COMPATIBLE
  no recipe may be approved.
```

## 8. Runtime、原始数据与清理策略

### 8.1 System-temp helper

Execute C1 允许创建一个随机系统临时 Python helper：

```text
trip-decider-wu2a-resume-<GUID>.py
```

要求：

- UTF-8 无 BOM；
- 只使用项目 `.venv` Python 和标准库；
- helper SHA256 在运行前记录；
- helper source 不含 credential；
- 不写 repository temporary file；
- 不接受自由 endpoint/query 参数；
- allowlist、query templates、budget 和 selection predicate 与本 Plan
  字面一致；
- `finally` 删除 helper、harness ledger 和任何 atomic `.tmp`；
- Review 记录 pattern residue count。

若临时 helper 实际需要偏离本 Plan 的 query、budget、endpoint、selection 或
cleanup，停止并修改 Plan，不在 Execute 中即兴调整。

### 8.2 Raw response

Response body 仅在 helper 进程内存中：

```text
urllib response
→ exact bytes
→ WU2A-R body length/hash
→ deterministic postprocess
→ selected summary
→ release memory
```

禁止把 raw body 写入 system temp、repo、stdout、Review 或 decision。因为
没有 raw capture file，每个 attempt 的 raw deletion 状态必须是：

```text
not_applicable_no_capture_file
```

不得写 `deleted=true` 冒充曾存在文件。

Harness ledger 位于 system temp。其内容被读取为 structured metadata 后，
ledger 文件删除；decision 记录：

```text
ledger_deleted: true
ledger_residue_count: 0
```

如果不能证明删除，decision 为 `INVESTIGATION_BLOCKED`；若连 blocked
decision 所需 ledger 也无法保留，整个工作单元停止，不提交伪完整 C1。

### 8.3 Output minimization

Runtime stdout 只允许 sanitized JSON：

- harness attempt/retry metadata；
- query/request/response hashes and counts；
- derived bbox；
- source base timestamp；
- minimal selected summaries；
- call counters and cleanup outcomes。

不得输出 raw response、numeric POI coordinates、absolute temp path、exception
message、secret 或 full tags。

## 9. Scope

### 9.1 精确三路径白名单

只允许：

```text
plans/work-unit-2a-resume.md
docs/wu2a-resume-decision.md
docs/reviews/work-unit-2a-resume-review.md
```

`acquisition record` 嵌入 `docs/wu2a-resume-decision.md` 的唯一
machine-readable JSON ledger，因此不需要第四个 Git path。

### 9.2 明确保护

不得修改：

```text
PLAN.md
plans/work-unit-2-real-world-ingestion.md
plans/work-unit-2-anchor-recovery.md
plans/work-unit-2a-remediation.md
docs/wu2a-anchor-decision.md
docs/reviews/work-unit-2a-remediation-review.md
docs/wu2-source-decision.md
docs/real-world-source-policy.md
docs/real-world-contract-extension.md
scripts/acquisition_harness.py
src/trip_decider/**
schemas/**
fixtures/**
tests/**
pyproject.toml
requirements.lock
.gitignore
handbook/**
```

不得新增 code、test、dependency、runtime directory、anchor 或 fixture。
需要第四个 Git path 即停止。

## 10. Decision 验证策略

WU2A-Resume 不重新测试 harness；WU2A-R 的 10 tests 和 143-test baseline
只作为冻结回归复核。

### 10.1 临时 validator

C1 在系统临时目录创建一个 standard-library validator，hash 并复用同一份
bytes。Validator 不联网，只读取 `docs/wu2a-resume-decision.md`。

预注册 12 checks：

```text
D01 UTF-8 no BOM and exactly one resume ledger JSON block
D02 previous decision path/SHA/status/ledger_complete exact
D03 attempt_group exact and old/new budgets separately represented
D04 scheduled operation and physical attempt counts within budget
D05 every harness attempt has exactly 14 fields and a qualified ID
D06 every query/request hash recomputes from recorded query/URL bytes
D07 response hashes/counts/timestamps/element-count types are strict
D08 retry relations are byte-identical and total relation count <=1
D09 every attempt has explicit cleanup outcome and residue evidence
D10 frozen ODbL/replay/attribution and source-policy ref are exact
D11 forbidden calls/raw/coordinates/fixtures are zero
D12 final status, recipe, compatibility and negative conclusion agree
```

Expected 值由本 Plan 字面定义，不从 decision 反向生成。

### 10.2 Pending Red

在任何网络调用前，先创建不含伪 attempt 的 decision skeleton：

```text
decision_status=INVESTIGATION_IN_PROGRESS
operations=[]
approved_acquisition_recipe=null
```

D01—D11 对 pending skeleton 只验证已有静态 contract；D12 必须是唯一失败：

```text
checks: 12
passed: 11
failures: 1
errors: 0
failure: D12
network attempts: 0
```

失败不得来自 missing file、import、dependency、syntax、malformed JSON 或
validator 自身错误。若不是上述分布，不进入 acquisition。

### 10.3 Final Green

完成 bounded run 并用实际输出更新同一 decision 后，以同一 validator bytes
和逐字符相同命令运行：

```text
checks: 12
passed: 12
failures: 0
errors: 0
network attempts: 0
```

随后运行现有完整非网络回归，仍必须：

```text
143 passed
0 failures
0 errors
```

Validator/helper 最终删除且 residue 为 0。Review 对关键字段使用独立
PowerShell/Python 只读命令复核，不把 validator 自报成功当唯一观察点。

## 11. Commit 序列

### WU2A-Resume-C0

```text
docs: record approved WU2A resume plan
```

文件：

- `plans/work-unit-2a-resume.md`

前置门：

- branch `main`；
- HEAD `f4e778f7fe2fc92ac6698ee96c36447f3d24aab1`；
- worktree 只有 approved Plan；
- Plan SHA256 精确等于批准值；
- remote/stash 为 0；
- WU2/WU2A/WU2A-R history、冻结 hash、11 Schemas 和 handbook 一致。

### WU2A-Resume-C1

```text
docs: record resumed acquisition investigation
```

文件：

- `docs/wu2a-resume-decision.md`

职责：

1. 创建 pending skeleton；
2. 取得 D01—D11 pass / D12 fail；
3. 使用系统临时 helper 和冻结 harness 执行 bounded run；
4. 写入真实 ledger、清理结果和最终结论；
5. 同一 validator 12/12 green；
6. 删除全部系统临时文件；
7. 运行 143-test non-network regression；
8. commit 只包含 Resume decision。

外部 HTTP 的 positive、negative 或 blocked response 都写入同一 C1，只要
ledger 和清理证据完整。若 harness/helper/ledger 本身失去审计能力，则不
提交伪完整 C1，工作单元停止。

### WU2A-Resume-C2

```text
docs: prepare WU2A resume review
```

文件：

- `docs/reviews/work-unit-2a-resume-review.md`

职责：

- 独立复核 Git、hash、预算、attempt、cleanup、decision 和回归；
- 逐条对照完成判定；
- 只允许最终状态：
  `READY_FOR_HUGIN_REVIEW`、`BLOCKED`、`INCOMPLETE`。

C2 完成后停止，不修改 C1，不执行新的 data call。

## 12. 完成判定

预注册 18 条，Review 必须逐条输出 `✓ 已完成`、`⚠ 已知限制` 或
`✗ 未完成`：

1. Approved Plan 按批准 SHA256 原文提交，执行期未修改；
2. WU2/WU2A 历史、旧 decision 和 WU2 Review absent 事实保持不变；
3. WU2A-R Plan、harness、test、Review 和 approval 历史保持不变；
4. Handbook fetch/八文件重读和 local/origin `0/0` 前后有证据；
5. 最终 Git diff 精确为三个白名单路径，dependency/code/test diff 为 0；
6. 新运行使用独立 `WU2A-resume-001`，旧保守 accounting 未删除或改写；
7. 新 scheduled budget 不超过 1 GET、3 POST，全组 transport retry relation
   不超过 1；
8. 只有两个 allowlisted endpoints 被调用，全部 forbidden call count 为 0；
9. 每个物理 attempt 有完整 14-field harness ledger、qualified ID、request
   hash、response evidence 和 explicit cleanup outcome；
10. Query/URL bytes、query hash、request hash 和 response hash 可机械复核；
11. Raw response 只在内存中，committed raw、coordinate pairs、anchor 和
    fixture 均为 0；
12. System-temp helper、validator、ledger 和 atomic temp residue 全部为 0；
13. Selection 只使用 exact name/category/type/id/coordinate-shape predicate，
    无 LLM、fuzzy、nearest、first、manual 或 silent fallback；
14. Final decision 是完整 recipe、bounded negative 或 evidenced blocked
    conclusion 之一，没有 partial approval；
15. D12-only pending red 与同 validator 12/12 green 均有命令和 exit evidence；
16. 现有 non-network regression 在 C1/C2 后仍为 143/143 green；
17. Review 提供实际 call counts、retry relation、source-policy、cleanup、
    hash、scope、secret/fallback 和三 commit evidence；
18. 未恢复 WU2 C5/C6，未开始 WU3，未 push、创建 remote 或新增 Plan。

任何 `✗` 均不得声明完成。一个合法的 bounded negative 或
`INVESTIGATION_BLOCKED` decision 可使本工作单元进入 Hugin Review，但不会
改变 WU2/WU2A 历史状态。

## 13. Blocking

立即停止，不扩大 scope：

- Execute baseline、approved Plan hash、历史、冻结 input、Schema 或 handbook
  不一致；
- 必须修改 `scripts/acquisition_harness.py` 或再次修 WU2A-R；
- literal deletion 字段必须进入 harness ledger 才能获批；
- 需要第四个 Git path、repo helper、test、dependency 或 runtime directory；
- 临时 helper 与本 Plan 的 endpoint/query/budget/selection/cleanup 不一致；
- 需要 query correction、第四个 POST、第二 retry 或 alternate Overpass；
- 需要 Nominatim、OSRM、商业地图、BBBike、Wikidata service、网页爬虫、
  全国 extract、人工 POI、手工坐标或 LLM 判断；
- raw response、coordinate list、absolute temp path、secret 或未授权数据会
  进入 Git/stdout；
- G0 bbox 或 OSM object identity/category/coordinate presence 需要猜测；
- helper、validator、ledger 或 atomic temp 无法证明删除；
- harness ledger 缺字段、未完成、与 runtime call counter 不一致；
- decision validator 的 pending red 不是 D12-only；
- final green 需要修改 validator expected、Plan、旧测试或冻结文件；
- 需要创建 anchor/fixture、恢复 WU2 C5/C6 或开始 WU3；
- 需要 amend/reset/rebase 任何既有历史。

外部 HTTP failure、transport exhaust 或 valid empty response 若有完整
ledger/cleanup，不自动构成 scope blocker；它们形成新 decision 中的
`INVESTIGATION_BLOCKED` 或 bounded negative conclusion。只有证据链本身
不完整时，整个工作单元以 `BLOCKED` 停止。

## 14. Review 证据与结束边界

Resume Review 至少提供：

- start/final HEAD 和 C0—C2 线性 history；
- 三路径 full diff/stat；
- old decision SHA 与 WU2/WU2A/WU2A-R history 对账；
- handbook 和 11 Schema 前后对账；
- helper/validator SHA、运行命令、exit code 和 residue；
- 每个 scheduled operation 与 physical attempt 的 ledger；
- global retry token 和 relation count；
- query/request/response hash 与 element/selected count；
- per-attempt cleanup 和 system-temp residue；
- source/license/replay/compatibility decision；
- D12-only red、12/12 green 和 143/143 regression；
- forbidden endpoint、fallback、secret、raw/coordinate signature 和 scope
  扫描；
- 18 条完成判定；
- 明确声明未恢复 WU2、未开始 WU3、未 push。

Review 完成后停止。不得自动执行 acquisition recipe、创建 anchor、恢复
WU2 或规划 WU3。

当前只完成 Plan，等待：

```text
批准执行 Work Unit 2A Resume
```
