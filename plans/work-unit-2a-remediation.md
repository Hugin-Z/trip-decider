# Work Unit 2A Remediation Plan

Plan version: v0.1
Status: PENDING_HUGIN_APPROVAL
Work unit: WU2A-R · Acquisition Harness Remediation
Prepared: 2026-07-28
Execution approval required: `批准执行 Work Unit 2A Remediation`

## 1. 当前状态与任务目标

### 1.1 历史状态

以下历史语义保持不变：

```text
WU0      APPROVED
WU1      APPROVED
WU1R     APPROVED
WU1C     APPROVED
WU2      BLOCKED
WU2A     INVESTIGATION_BLOCKED
```

WU2 的 `BLOCKED` 和 WU2A 的 `INVESTIGATION_BLOCKED` 都不是待改写的失败记录。它们证明真实数据获取路径在证据不足时正确停止。WU2A-R 是一个新的 PER 工作单元，不 amend、reset、rebase、补写或重新解释 WU2/WU2A 历史。

当前历史事实：

| 范围 | Commit | Message |
|---|---|---|
| WU2 C0 | `4a3242f` | `docs: record approved WU2 plan` |
| WU2 C1 | `a4a91fc` | `docs: record WU2 source and capture gate` |
| WU2 C2 | `cd4f577` | `chore: add WU2 ingestion interfaces` |
| WU2 C3 | `d01d198` | `test: add failing WU2 adapter contract cases` |
| WU2 C4 | `352dbbc` | `feat: implement open-data artifact adapters` |
| WU2A C0 | `0327e9f` | `docs: record approved anchor recovery plan` |
| WU2A C1 | `0a19f5e` | `docs: record open-data investigation` |

WU2 C5/C6 未开始，`docs/reviews/work-unit-2-review.md` 不存在。WU2A 在 C1 后停止，没有创建测试、anchor、fixture 或 Review。

### 1.2 WU2A-R 唯一目标

WU2A-R 只修复 acquisition harness 的失败路径证据能力：

1. attempt 在请求前进入 ledger，任何已开始的 attempt 都留下记录；
2. HTTP response failure 与 transport failure 按 Python 异常层级和实际响应边界正确分类；
3. retry 只由 transport failure 触发，并留下原 attempt 与 retry attempt 的确定性关联；
4. 未取得的 response hash、字节数或 metadata 保持显式 `null`，不得重建、猜测或从异常文本推导。

完成 WU2A-R 不等于找到 OSM 数据、不等于取得 anchor，也不自动恢复 WU2 或 WU2A。

### 1.3 明确不负责

WU2A-R 不负责：

- 新 Overpass 查询、O2/O3 或 Geofabrik 重新下载；
- 调用 Overpass、Nominatim、OSRM、商业地图或任何其他地图 API；
- OSM 覆盖分析、数据源选择或 query 修改；
- 创建真实 anchor、fixture、candidate 或 evidence；
- 修改 adapter、Schema、validator 或 source policy；
- 开始 WU2 C5/C6、WU3 或 WU3 Plan；
- 证明真实数据源可行或生成 acquisition recipe。

## 2. 输入、基线与冻结证据

### 2.1 项目基线

Plan 阶段实测：

```text
repository: <repo>
branch: main
HEAD: 0a19f5ea9053f018e5d3ba341500c97556fb65b7
worktree: clean before this Plan
remote count: 0
stash count: 0
project Python: .venv\Scripts\python.exe
existing explicit regression: 133 tests, OK
```

133 个现有测试由以下命令实测：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters -q
```

结果：

```text
Ran 133 tests
OK
exit code 0
```

### 2.2 冻结输入

| Path | SHA256 |
|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `plans/work-unit-2-real-world-ingestion.md` | `894D5844E140BF62EC1DB89B1BE318EB4945FF4A0BF8B139E9B82C0B4929BA2C` |
| `plans/work-unit-2-anchor-recovery.md` | `432318A68D13774646CF3A1E5BE6057D5C92DE7CE600E06FA6CF52BD0CD92E90` |
| `docs/wu2-source-decision.md` | `E667ABCF6BEBFB522AE0EA76AFDD6EB628E11214B33773045AA5EC8B8C7FEA62` |
| `docs/real-world-source-policy.md` | `B89D0836BCC17DD1D52CA215F38EF290134251295ECAC183BA7D54C45A1C4989` |
| `docs/wu2a-anchor-decision.md` | `570649D6B7287B48F3C396E536AC05EF31D949FC7AF960EF2D3DFEB17D4A9F6D` |

`docs/wu2a-anchor-decision.md` 是本工作单元的历史证据输入，不是输出。其 `INVESTIGATION_BLOCKED` 状态、缺失字段和原始失败叙事必须保持字节不变。

11 个 Schema 同样冻结：

| Schema | SHA256 |
|---|---|
| `candidates.schema.json` | `3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2` |
| `common.schema.json` | `83FE17127A545D168A16F58911564E53D2E17AFF826B6D34437D873ECF8E75BE` |
| `constraint-parse.schema.json` | `0D41493B52B6178AEE8DE44B2F3607B193B62C263AD79DEF380B638B22B400A4` |
| `constraints.schema.json` | `25069E0DEFBDC03FEA7E92E83EE10F952A31A2B18BDC3678D17786C537EE4473` |
| `evidence.schema.json` | `54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B` |
| `fixture-case.schema.json` | `630E57E7F27A660F388407A8FF1B81D851B8B3A047E5B98DCB70E1920177E45A` |
| `plan.schema.json` | `81EEB5899C33F19DC6FA059C7D447D747E72E355F3084D925FD9410272389BD3` |
| `plan-diff.schema.json` | `37B94FE5E03A73B046D7E6D79BEABF31C4105E50CD54DE520CA6C293AB3E8B43` |
| `previous-plan.schema.json` | `59692D17EB79C7EA2D4A2E2866898DD97A0E49B97834EC8AFC5EAB46A80BEDAC` |
| `request.schema.json` | `BC7F46E9A85CE9697F9BA01FF1506A5B56C161F2F6B5140D91FCF0B100762914` |
| `violations.schema.json` | `C117415030993C24649B17837EC2A35C69A2F1CEC7D923742ABD383BA85B394F` |

### 2.3 Handbook 状态

固定路径：

```text
<handbook>
```

Plan 阶段已执行 `git fetch origin --prune`，实测：

```text
local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree: clean
```

从 `origin/main` 实际重新读取：

- `STATE.md`
- `INDEX.md`
- `SUMMARY.md`
- `tools/context-injection.md`
- `principles/r10-honesty.rule.md`
- `principles/per-protocol.rule.md`
- `principles/scope-control.rule.md`
- `principles/fixture-first.rule.md`

对 WU2A-R 的直接影响：

- R10：未知字段保持 `null`；不得从异常消息重建值；执行结果、数量和 hash 由命令产生；
- PER：本 Plan 获批前不进入 Execute，完成后只进入 WU2A-R Review；
- Scope：4 个路径为完整白名单；需要第 5 个路径即停止；
- Fixture-first：先建立可导入但未实现的接口，再以合成确定性 failure fixture 取得有效 red，随后用同一命令转 green。

## 3. 阻塞证据与 harness 问题分析

### 3.1 已有证据

冻结 decision 文档记录：

- 旧 harness 通过 stdin 传给项目 `.venv` Python，没有入仓；
- ledger 计划在完整 acquisition sequence 结束后一次性输出；
- O1 返回 HTTP 400；
- `urllib.error.HTTPError` 因同时是 `URLError` 子类，被错误进入 transport retry 分支；
- O1 消耗了唯一 byte-identical retry；
- retry 再次返回 HTTP 400，未捕获异常使进程在 ledger emission 前退出；
- G0/O1/O1-R1 的多个时间、request hash、response hash、response bytes 和 content type 只能保留为 `null`；
- 当前文档明确标记 `ledger_complete=false`，没有从记忆重建。

这只能证明旧 harness 不满足失败路径审计要求，不能证明 OSM 无数据、Overpass 不可用或开放数据路线不可行。

### 3.2 根因

根因一：异常分类顺序错误。

```text
HTTPError
  is-a URLError
```

如果先捕获 `URLError`，HTTP response 会被误认为没有 response 的 transport failure。正确实现必须先处理 `HTTPError`，再处理非 HTTP 的 `URLError`。

根因二：ledger emission 太晚。只在流程末尾输出汇总，任何中途异常都会让整个 attempt 记录消失。正确实现必须在 transport 调用前持久化 `started` entry，并在 `finally` 中持久化终态。

根因三：retry 没有以 failure class 为门。正确实现必须只允许稳定、显式的 transport failure 集合进入 retry；HTTP 400/404/429/500+ 均已有 HTTP response，不消耗 transport retry。

### 3.3 当前代码事实

当前仓库不存在：

```text
scripts/acquisition_harness.py
tests/test_wu2a_acquisition_harness.py
```

因此不能直接先提交测试；否则 red 会来自文件/import 缺失，违反批准要求。WU2A-R 需要一个独立的接口桩 commit，接口可导入且行为统一抛出明确 `NotImplementedError`，然后再提交测试取得有效 red。

## 4. Scope 与路径白名单

### 4.1 精确白名单：4 个路径

| Path | 作用 |
|---|---|
| `plans/work-unit-2a-remediation.md` | 获批 Plan 原文 |
| `scripts/acquisition_harness.py` | acquisition harness 接口、ledger 持久化、分类和 retry 实现 |
| `tests/test_wu2a_acquisition_harness.py` | 离线、合成、确定性的 failure-path contract cases |
| `docs/reviews/work-unit-2a-remediation-review.md` | WU2A-R 独立 Review |

从建议白名单中移除 `docs/wu2a-anchor-decision.md`。A06 通过 harness 结果及持久化 JSON 的 `null` 断言验证“不重建”，不需要改历史 decision 文档。

### 4.2 明确保护

不得修改：

- `PLAN.md`；
- `plans/work-unit-2-real-world-ingestion.md`；
- `plans/work-unit-2-anchor-recovery.md`；
- `docs/wu2a-anchor-decision.md`；
- `docs/wu2-source-decision.md`；
- `docs/real-world-source-policy.md`；
- `docs/real-world-contract-extension.md`；
- `src/trip_decider/adapters.py`、`src/trip_decider/ingestion.py`；
- `src/trip_decider/schema_validation.py`、`src/trip_decider/fixture_validation.py`；
- `schemas/` 全部内容；
- `fixtures/` 全部内容；
- 既有 tests、scripts、依赖和 lock 文件；
- handbook 全部内容；
- Git 历史、remote、stash 和用户系统配置。

### 4.3 规模和边界

预计新增 4 个文件，不修改任何既有 tracked 文件。只使用 Python 3.11 标准库，不新增 dependency，不新增真实 HTTP client，不提供 CLI 自动联网入口。

若实现需要第 5 个路径、修改已有文件或引入依赖，立即停止并报告。

## 5. Attempt Ledger First 设计

### 5.1 接口边界

`scripts/acquisition_harness.py` 提供可导入的确定性接口。接口接收：

- `purpose`、`endpoint`、`method`；
- 已由调用者准备好的 immutable `request_bytes`；
- 调用者注入的 `transport(request_bytes)`；
- 调用者注入的时钟；
- 系统临时目录中的 `ledger_path`；
- 明确的 `max_transport_retries`，默认值为 1；
- 可选、仅供测试和后续 orchestration 使用的 `postprocess(response)`。

模块不自行构造 query、不选择 endpoint、不读取环境变量、不调用 `urlopen`，也不包含任何 provider fallback。实际网络 transport 仍属于后续经批准的 WU2A acquisition 执行。

### 5.2 持久化顺序

每个 attempt 的确定顺序：

```text
validate caller inputs and compute request_sha256
↓
allocate attempt_id
↓
append in-memory entry with status=started and every field present
↓
atomically persist ledger to caller-supplied system-temp path
↓
invoke injected transport
↓
classify result or failure
↓
finally set completed_at and terminal status
↓
atomically persist terminal ledger state
```

初次 ledger persist 失败时不得发起 transport。终态 persist 失败属于明确 internal/ledger failure并硬失败，不得报告成功。

持久化使用标准库 UTF-8 JSON、同目录随机临时文件和 `os.replace`。每次替换前 flush/close；不在仓库内创建临时文件。测试必须用 `tempfile.TemporaryDirectory()`，并验证临时内容清理。ledger 不保存 response body 或真实 query bytes，只保存经批准的 metadata 与 SHA256。

“process failure”在本工作单元中指 transport 已返回后，postprocess 或 harness 内部步骤抛出普通 Python 异常；`finally` 必须完成终态记录。操作系统强制终止、断电和无法执行 `finally` 不在 WU2A-R 保证范围内；这种情形至少保留请求前已持久化的 `started` entry，不能虚构 completed 状态。

### 5.3 Attempt 字段

每个 attempt 必须始终包含以下 14 个字段；未知值显式为 JSON `null`：

```json
{
  "attempt_id": "",
  "purpose": "",
  "endpoint": "",
  "method": "",
  "request_sha256": "",
  "started_at": "",
  "completed_at": null,
  "status": "started",
  "http_status": null,
  "response_bytes": null,
  "response_sha256": null,
  "content_type": null,
  "error_class": null,
  "retry_decision": "not_evaluated"
}
```

字段规则：

- `attempt_id`：由本次 harness run 内的单调序号生成，不从 response 推断；
- `request_sha256`：在 transport 前对调用者提供的 exact bytes 计算；
- `started_at` / `completed_at`：由注入时钟生成 RFC 3339 字符串；
- `status`：只允许冻结状态集；
- `http_status`：只有确实收到 HTTP status 时为整数；
- `response_bytes`：只有确实读取到 body bytes 时为非负整数；
- `response_sha256`：只有确实读取到 body bytes 时计算，包括空 body 的 SHA256；
- `content_type`：只有 response header 明确提供时记录；
- `error_class`：使用稳定内部 token，不复制第三方异常原文；
- `retry_decision`：使用稳定枚举，不根据异常文本自由生成。

冻结 attempt status：

```text
started
succeeded
http_response_failure
transport_failure
internal_failure
```

冻结 `retry_decision`：

```text
not_evaluated
not_applicable
not_retryable_http
retry_scheduled
retry_exhausted
not_retryable_internal
```

### 5.4 Response body 边界

HTTP 非 2xx body 只有在 injected transport/`HTTPError` 提供可读 bytes 时才做机械测量。harness 记录 byte count 和 SHA256，但不把 body 写入 ledger。

若 body 不存在或读取失败：

```json
{
  "response_bytes": null,
  "response_sha256": null
}
```

不得使用异常字符串长度代替 response bytes，不得对异常字符串做 response hash，不得把 status、header 或历史日志拼成 body。

## 6. Error classification

### 6.1 HTTP response failure

以下均属于 `http_response_failure`，不触发 transport retry：

- `urllib.error.HTTPError`，包括 400、404、429 和 500+；
- injected transport 正常返回但 status 不在 200—299。

处理 `HTTPError` 必须先于 `URLError`。应记录：

- 实际 HTTP status；
- 可机械读取时的 response byte count 与 SHA256；
- 明确 header 中的 content type；
- `error_class=http_response_failure`；
- `retry_decision=not_retryable_http`。

不得复制 HTTP reason、异常消息或 response body 内容到 ledger。

### 6.2 Transport failure

以下稳定类属于 `transport_failure`：

- DNS：`socket.gaierror`，包括作为非 HTTP `URLError.reason` 的情形；
- timeout：`TimeoutError`、`socket.timeout`；
- connection failure：`ConnectionError`；
- reset：`ConnectionResetError`；
- 非 HTTP 且底层原因属于以上集合的 `urllib.error.URLError`。

记录：

```text
http_status=null
response_bytes=null
response_sha256=null
content_type=null
error_class=transport_failure
```

异常文本不得进入 ledger。未列入的异常不得通过名称包含关系猜成 transport failure，应进入 `internal_failure` 并且不 retry。

### 6.3 Internal/process failure

transport 返回后，postprocess 或 harness 内部非分类异常属于：

```text
status=internal_failure
error_class=internal_failure
retry_decision=not_retryable_internal
```

已经机械取得的 response status/bytes/hash/content type保留；未取得的字段保持 `null`。`finally` 必须写入 `completed_at` 并持久化终态。

## 7. Retry 规则

### 7.1 唯一触发条件

只有已分类的 `transport_failure` 且剩余 retry budget 大于 0 时，才创建 retry attempt。

以下不 retry：

- HTTP 400/404/429/500+；
- provider/query error；
- postprocess/internal failure；
- ledger persist failure；
- 未知异常。

### 7.2 Retry ledger

顶层 ledger 除 `attempts` 外包含 `retries`。每个 retry relation 必须完整包含：

```json
{
  "original_attempt_id": "",
  "retry_attempt_id": "",
  "same_request_sha256": true,
  "reason": "transport_failure"
}
```

规则：

- retry attempt 必须先拥有自己的 `started` entry 并持久化，再调用 transport；
- retry 使用同一份 immutable request bytes；
- 两个 attempt 的 `request_sha256` 必须逐字符相同；
- `same_request_sha256` 由两个已计算 hash 的确定性比较产生；
- `reason` 只能是稳定 token `transport_failure`；
- 原 attempt 在调度 retry 时为 `retry_scheduled`；
- 最后一个 transport failure 没有剩余 budget 时为 `retry_exhausted`；
- HTTP failure 不得创建 retry relation。

## 8. Fixture-first 测试策略

### 8.1 Fixture 类型和边界

这些 case 是确定性变换类合成 fixture：

- transport、clock、response 和 exception 均由测试内手写 fake 提供；
- expected status、字段、hash 和 call count 根据本 Plan 人工写定；
- expected 不得由被测 harness 输出反喂；
- 不发生 DNS、HTTP 或任何网络调用；
- 不代表真实 provider 行为、OSM 覆盖、query 正确性或 anchor 可得性。

测试模块 docstring 必须声明来源、覆盖范围和不覆盖范围。每个 case 验证一个主要行为，happy path 至少断言具体状态、字段、hash、call count 和持久化结果。

### 8.2 预注册 case：10 个

| ID | 输入 | 主要预期 |
|---|---|---|
| A01 | `HTTPError(400)`，body 可读 | 1 次 transport；不 retry；完整终态；status/error class 为 `http_response_failure`；status/body bytes/hash 被记录 |
| A02 | 第一次 timeout，retry 成功 | 2 个完整 attempts；原 attempt `retry_scheduled`；1 个 retry relation；相同 request hash |
| A03 | `URLError(socket.gaierror(...))`，retry 成功 | DNS 分类为 transport；允许一次 retry；不读取异常文本 |
| A04 | 两次 transport failure | 2 个完整 attempts；只 retry 一次；最终 `retry_exhausted`；无第三次调用 |
| A05 | 2xx response 后 postprocess 抛异常 | `finally` 写入 completed；状态 `internal_failure`；已有 response metadata 保留；不 retry |
| A06 | HTTP failure body 不可读/不存在 | response bytes/hash 保持 `null`；持久化 JSON 仍为 `null`；不从异常或旧 decision 文档重建 |
| A07 | injected response status 500 | 分类为 HTTP response failure；不 retry；body metadata 可回读 |
| A08 | `HTTPError(429)` | 不消耗 transport retry；不创建 retry relation |
| A09 | connection reset 后 retry 成功 | transport 分类；relation 四字段精确；两个 request hash 一致 |
| A10 | 2xx clean success | `succeeded`；response metadata 完整；`error_class=null`；`retry_decision=not_applicable` |

### 8.3 有效 Red

为避免 import/file 缺失造成伪 red，先提交可导入接口桩。随后只新增测试，并运行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2a_acquisition_harness -v
```

预期 red：

```text
tests: 10
passed: 0
failures: 0
errors: 10
```

10 个 error 必须全部来自预批准公开行为入口的 `NotImplementedError`。以下必须为 0：

- import error；
- 文件/路径错误；
- dependency error；
- syntax error；
- malformed test；
- unexpected exception；
- network attempt。

若实际分布不同，停止，不进入实现 commit。

### 8.4 Green 与回归

实现完成后用逐字符相同命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2a_acquisition_harness -v
```

目标：

```text
10 passed
0 failures
0 errors
```

再运行完整结构回归：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_harness -v
```

预期：

```text
143 passed
0 failures
0 errors
```

所有数量以 Execute 阶段真实 unittest 输出为准；任何不一致必须如实记录，不得把预注册数字当实测。

## 9. Commit 序列

原建议的四 commit 序列调整为五个线性 commit。增加接口桩是为了满足“red 不得来自 import 或文件不存在”，不是提前实现行为。

### WU2A-R-C0

```text
docs: record acquisition remediation plan
```

文件：

- `plans/work-unit-2a-remediation.md`

前置条件：

- branch `main`；
- HEAD `0a19f5ea9053f018e5d3ba341500c97556fb65b7`；
- 工作树只有获批 Plan；
- Plan SHA256 与批准值一致；
- remote/stash 均为 0；
- handbook 与冻结输入复核一致。

完成判定：

- commit 只包含获批 Plan 原文；
- 不为更新状态而修改 Plan 字节。

### WU2A-R-C1

```text
chore: add acquisition harness interface
```

文件：

- `scripts/acquisition_harness.py`

职责：

- 冻结公开数据结构、稳定 token 和函数签名；
- 模块可从项目根导入；
- 行为入口明确抛出 `NotImplementedError`；
- 不实现 transport、ledger、classification 或 retry；
- 不包含 live HTTP client。

验证：

```powershell
.\.venv\Scripts\python.exe -c "from scripts.acquisition_harness import run_acquisition; print(run_acquisition.__name__)"
```

预期只证明 import/interface 存在，不声明行为完成。

### WU2A-R-C2

```text
test: add acquisition failure contract cases
```

文件：

- `tests/test_wu2a_acquisition_harness.py`

职责：

- 新增 A01—A10；
- 不修改 C1 接口文件；
- 取得 §8.3 的有效 red；
- 保存完整命令、exit code、test IDs 和 error 分类。

完成判定：

- 10 个 case 全由批准的 `NotImplementedError` 变 red；
- network call count 为 0；
- commit 只有测试。

### WU2A-R-C3

```text
feat: fix acquisition ledger and error classification
```

文件：

- `scripts/acquisition_harness.py`

职责：

- 实现 ledger-first 持久化；
- 实现 HTTP/transport/internal 分类；
- 实现仅 transport retry 及 relation；
- 保留显式 `null`；
- 不修改测试。

验证：

- 用 §8.3 逐字符相同命令转为 10/10 green；
- 运行 143-test 回归；
- 扫描 live network、fallback、guess/infer 和 secrets。

### WU2A-R-C4

```text
docs: prepare acquisition remediation review
```

文件：

- `docs/reviews/work-unit-2a-remediation-review.md`

职责：

- 只记录独立 Review 证据；
- 不修改 Plan、实现或测试；
- 明确旧 WU2/WU2A 状态仍分别为 `BLOCKED` / `INVESTIGATION_BLOCKED`；
- 最终状态只允许 `READY_FOR_HUGIN_REVIEW`、`BLOCKED` 或 `INCOMPLETE`。

## 10. Review 与验证证据

WU2A-R Review 至少记录：

1. 起点 HEAD、最终 HEAD 和 C0—C4 线性历史；
2. 完整 diff/stat 和 4 路径白名单对账；
3. C2 red 与 C3 同命令 green 的完整 test IDs、数量和 exit code；
4. 133-test 既有基线和 143-test 完整回归实测；
5. A01—A10 逐项结果；
6. injected transport 的逐 case 调用次数，证明无实际网络；
7. HTTPError 在 URLError 前处理的源码与行为证据；
8. ledger 首次 persist 发生在 transport 调用前的 spy/event-order 证据；
9. started/terminal 两次持久化和 `finally` 行为证据；
10. retry relation 四字段和 byte-identical hash 证据；
11. response body 不可读时两个字段仍为 `null` 的 JSON 证据；
12. 系统临时目录测试残留为 0；
13. 6 个冻结输入、11 个 Schema 和 handbook 前后 hash/状态对账；
14. WU2/WU2A commits 与 `docs/wu2a-anchor-decision.md` 未变；
15. remote/stash/push/WU2 C5/C6/WU3 均未发生；
16. fallback、guess/infer、live endpoint、secret 和 scope 扫描。

建议扫描：

```powershell
rg -n "infer_|guess_|default_when_missing|silent_fallback|warning_as_pass" scripts/acquisition_harness.py tests/test_wu2a_acquisition_harness.py
rg -n "urlopen|requests\\.|httpx\\.|overpass-api|nominatim|amap|baidu|osrm" scripts/acquisition_harness.py
rg -n "(?i)(api[_-]?key|access[_-]?token|secret|password)\\s*[:=]" plans/work-unit-2a-remediation.md scripts/acquisition_harness.py tests/test_wu2a_acquisition_harness.py docs/reviews/work-unit-2a-remediation-review.md
```

匹配结果需人工分类；扫描命中不自动等于违规，零命中也不替代 diff 审查。

## 11. 完成判定

预注册 20 条完成判定，Review 必须逐条输出 `✓ 已完成`、`⚠ 已知限制` 或 `✗ 未完成`，不得遗漏：

1. 获批 Plan 以批准 SHA256 原文提交，执行期未修改；
2. WU2/WU2A 历史 commits 未改写，历史状态未重述为成功或失败；
3. `docs/wu2a-anchor-decision.md` SHA256 前后保持 `570649D6B7287B48F3C396E536AC05EF31D949FC7AF960EF2D3DFEB17D4A9F6D`；
4. 其他 5 个冻结输入、11 个 Schema 和 handbook 前后保持不变；
5. 实际 diff 只涉及 4 个白名单路径；
6. 没有新增 dependency，`.venv`、`pyproject.toml` 和 `requirements.lock` 未修改；
7. C1 接口可导入，且在 C2 前没有行为实现；
8. C2 取得 10-case 有效 red，错误只来自 `NotImplementedError`；
9. C3 使用逐字符相同命令取得 10/10 green；
10. 完整回归实测 143/143 green；
11. 每次已开始 attempt 在 transport 前持久化 `started` entry；
12. 每个 attempt 的 14 个冻结字段始终存在，未知值显式 `null`；
13. HTTP 400/404/429/500+ 被归为 HTTP response failure 且不 retry；
14. DNS、connection、timeout 和 reset 被归为 transport failure，且只在预算内 retry；
15. retry relation 四字段完整，retry request hash 与原 attempt 相同；
16. postprocess/internal failure 仍通过 `finally` 留下 completed terminal ledger；
17. unreadable/absent response body 不被异常文本、日志或历史文档重建；
18. 测试和实现均无真实网络调用，系统临时测试残留为 0；
19. 没有创建 anchor/fixture，没有修改 adapter/Schema/validator/source policy，没有开始 WU2 C5/C6 或 WU3；
20. Review 提供 Git、hash、scope、red/green、R10、secret 和无 push/remote 的独立证据。

任一 `✗` 均不得声明 WU2A-R 完成。`⚠` 必须说明能力边界，不能被静默折算成 `✓`。

## 12. Blocking 与停止条件

出现以下任一情况立即停止整个 WU2A-R，最终状态使用 `BLOCKED` 或 `INCOMPLETE`：

- 执行前 branch、HEAD、worktree、remote、stash、批准 Plan hash 或冻结输入不一致；
- 需要修改第 5 个路径；
- 需要修改既有 Plan、decision、Review、adapter、Schema、validator、source policy、fixture 或 dependency；
- C2 red 不是 10 个批准的接口态 `NotImplementedError`；
- C3 需要修改测试才能 green；
- Python 3.11 标准库不足，必须引入 dependency；
- 需要真实网络、Overpass、Nominatim、OSRM、商业地图或其他数据服务；
- 需要创建、保存或提交真实 response、query、坐标、anchor 或 fixture；
- 需要从异常文本、日志、记忆或旧 decision 文档重建未知字段；
- ledger 无法在 transport 前持久化，或 terminal persist 失败却会被报告为成功；
- retry 需要扩展到 HTTP response failure；
- 发现契约不足并需要 Schema/adapter/source-policy remediation；
- 可能提交 secret、未授权 raw data 或本机绝对临时路径；
- 需要 amend/reset/rebase WU2 或 WU2A 历史；
- 需要开始 WU2 C5/C6、WU3 或任何后续工作单元。

## 13. 执行结束边界

Plan 获批后只执行 WU2A-R C0—C4。C4 Review 完成后停止，不自动：

- 重开 WU2A acquisition；
- 发起新的数据调用；
- 将 WU2A 改为成功；
- 恢复 WU2；
- 创建 WU2/WU3 后续 Plan；
- push、创建 remote、PR 或 release。

允许的 Review 终态：

```text
READY_FOR_HUGIN_REVIEW
BLOCKED
INCOMPLETE
```

当前停在 Plan 阶段，等待：

```text
批准执行 Work Unit 2A Remediation
```
