# trip-decider 接手基线报告

> 核对日期：2026-08-02
> 核对对象：`main` @ `cc354b8`（工作树有 2 个未提交改动，见 §1.6）
> 性质：只读摸底。本轮不设计方案、不提修复计划。
> 证据规则：每条结论给出 `文件:行号` 或「命令 + 输出」。无法给出证据的一律标注【待验证】。

---

## 0. 本轮实际做了什么（副作用披露）

只读约束的执行情况：

- 未修改任何源码、配置、测试；未执行 `git commit / checkout / stash / reset` 等改变仓库状态的操作。
- 唯一写入仓库的文件：本报告 `docs/audit/handover-baseline.md`。
- **有两处非仓库副作用，如实披露**：
  1. 执行测试套件（题目允许）时，`trip_decider.travel_agent` 在模块导入期构造 `DEFAULT_AGENT_STORE`（`src/trip_decider/travel_agent.py:1589-1592`），测试过程在 `runtime/sessions/` 新建了一个 session 目录 `e2c395d4-13ea-4e4c-aa6f-64c4d0836e79`（mtime `2026-08-02T09:35:35`），并重写了 `runtime/evidence-cache/records.json`（mtime `2026-08-02T09:35:36`）。`runtime/` 被 `.gitignore:18` 忽略，仓库状态未变，但磁盘状态变了。
  2. 执行 `scripts/run_wuyuan_demo.ps1` 验证 README 声明，输出写入会话 scratchpad 目录，未写入仓库。

---

## 1. 事实盘点（命令实测）

### 1.1 规模

命令：`git ls-files | wc -l`、按扩展名统计。

| 项 | 数值 |
|---|---|
| 受版本控制文件总数 | 174 |
| Python | 64 个文件 / 51,649 行 |
| Markdown | 62 个文件 / 25,472 行 |
| JSON | 24 个文件 / 3,914 行 |
| PowerShell `.ps1` | 14 个文件 / 6,743 行 |
| HTML | 2 个文件 / 557 行 |
| JS | 1 个文件 / 2,071 行 |
| CSS | 1 个文件 / 974 行 |
| YAML / TOML / lock | 2 / 1 / 1 |

Python 行数分布（`wc -l`）：

- `src/trip_decider/` **36,662 行**（36 个 `.py`）
- `tests/` **14,366 行**（25 个 `.py`）
- `scripts/` 621 行（2 个 `.py`）

单文件前五（`src/`）：`simple_live.py` 3,005 / `amap_ephemeral_live.py` 2,950 / `itinerary_planner.py` 2,533 / `live_place_resolution.py` 2,352 / `agent_actions.py` 2,154。

文档规模：`plans/` 21 个文件 13,588 行；`docs/reviews/` 17 个文件 7,735 行；`docs/*.md` 3,996 行。**文档行数（25,472）接近 src 行数（36,662）的 70%。**

### 1.2 依赖

`pyproject.toml:1-20`：

- `requires-python = ">=3.11,<3.12"`
- 直接依赖 3 个：`mcp==2.0.0`、`PyYAML==6.0.3`、`jsonschema[format-nongpl]==4.26.0`
- 构建后端 `setuptools`；`[tool.setuptools.package-data] trip_decider = ["*.html"]`

`requirements.lock` 44 行，全部为精确 pin。其中 `httpx2==2.9.1`、`httpcore2==2.9.1`、`mcp-types==2.0.0`、`starlette==1.3.1`、`uvicorn==0.52.0`、`sse-starlette==3.4.6` 均由 `mcp` 传递引入。

**没有任何开发依赖**：无 `pytest`、无 `ruff`/`flake8`、无 `mypy`、无 `coverage`。实测：

```
$ ./.venv/Scripts/python.exe -m pytest --version
<repo>\.venv\Scripts\python.exe: No module named pytest
```

无 CI 配置（`git ls-files` 中无 `.github/`、无 `.gitlab-ci.yml`、无 `tox.ini`、无 `Makefile`）。

本机 `python --version` = `Python 3.11.9`，`.venv` 已按 lock 准备。

### 1.3 程序入口

存在 **4 个互不相同的入口**：

| 入口 | 位置 | 说明 |
|---|---|---|
| MCP STDIO server | `src/trip_decider/mcp_server.py:304-347`（`main()`，`if __name__ == "__main__"`） | 最新入口，`cc354b8` 引入 |
| 本地 HTTP 产品 | `src/trip_decider/product_web.py`，由 `scripts/run_product.ps1` 以 `python -m trip_decider.product_web --host 127.0.0.1 --port 8765` 启动 | PRODUCT.md:14 声称的「产品入口」 |
| Codex CLI 桥 | `scripts/trip_agent.py:20-29` → `src/trip_decider/codex_host.py`（HTTP 客户端，`DEFAULT_PRODUCT_URL = "http://127.0.0.1:8765"`，`codex_host.py:18`） | 依赖上面的 HTTP 服务在跑 |
| 离线 artifact 演示 | `scripts/run_wuyuan_demo.ps1` → `src/trip_decider/e2e_demo.py` | README.md:67-88 声称的入口 |

`pyproject.toml` 中**没有 `[project.scripts]` 控制台入口**，四个入口都靠脚本或 `-m` 拉起。

### 1.4 MCP server 如何注册与启动

- 注册：`mcp_server.py:65-273` 的 `build_mcp_server(adapter)`，用 `mcp.server.mcpserver.MCPServer` 装饰器风格注册 1 个 resource + 10 个 tool。
- 资源：`mcp_server.py:88-100` 注册 `ui://trip-decider/workspace/v1.html`（`mcp_app.py:13`），内容来自 `src/trip_decider/mcp_app_workspace_v1.html`（433 行，`mcp_app.py:17-24` 用 `importlib.resources` 读取）。
- 传输：`mcp_server.py:336` `server.run("stdio")`。
- 依赖注入：`mcp_server.py:332-334` 注入 `TripMCPAdapter(services.application, services.query)`；`services` 来自 `trip_services.py:44-47` 的 `DEFAULT_TRIP_SERVICES` 或 `--runtime-root` 指定的 `build_trip_services()`。
- `--with-web`（`mcp_server.py:288-331`）可在同进程另起线程跑 `product_web`，共享同一个 runtime。

### 1.5 测试

无 pytest，用 `unittest` 发现。实测：

```
$ ./.venv/Scripts/python.exe -m unittest discover -s tests -t .
----------------------------------------------------------------------
Ran 261 tests in 45.235s

OK
```

- 测试文件：`tests/test_*.py` 共 **23 个**（另有 2 个非 `test_` 前缀的用例库 `wu1c_contract_compatibility_cases.py`、`wu1r_verify_entry_cases.py`）。
- 用例数：**261**，全部通过，**0 失败 / 0 跳过 / 0 error**（输出中无 `skipped`/`expected failure`，grep 计数为 0）。
- 分布极不均衡（`grep -c "    def test_"`）：`test_schema_validation.py` 63、`test_product_web.py` 33、`test_fixture_validation.py` 19 …… 而 **整个 MCP 工具面只有 `test_mcp_adapter.py` 的 3 个用例**（`test_mcp_adapter.py:230,243,276`），`test_trip_query.py` 4 个、`test_trip_application.py` 4 个。
- 覆盖率不可测（无 coverage 依赖）。【待验证：真实行覆盖率】

### 1.6 git

```
$ git log --oneline | wc -l
135
$ git log --reverse --format="%h %ad %s" --date=short | head -1
60c0718 2026-07-26 chore: establish WU0 repository baseline
```

- commit 总数 **135**，时间跨度 **2026-07-26 → 2026-08-01，共 7 天**。平均约 19 commit/天。
- 最近 20 条 commit message：

```
cc354b8 2026-08-01 feat: add shared headless MCP and interactive app
a24f305 2026-08-01 refactor: centralize trip query read models
6e86243 2026-08-01 refactor: extract trip application service
b120894 2026-08-01 feat: gate plan installation on evidence readiness
2099c49 2026-08-01 feat: isolate run evidence behind broker
01a273b 2026-08-01 refactor: unify product runtime modes and routes
57afc6f 2026-07-30 feat: establish persistent agent runtime baseline
3976776 2026-07-30 feat: establish generic trip runtime baseline
49656f8 2026-07-29 fix: make final redaction origin-aware
25ee041 2026-07-29 test: require origin-aware final redaction
5871f41 2026-07-29 fix: preserve safe provider failure classification
7c9c642 2026-07-29 test: require safe provider failure classification
1ee4212 2026-07-29 feat: implement AMap ephemeral same-run resolution
5f4f84b 2026-07-29 test: add failing AMap ephemeral live cases
39f28f0 2026-07-29 chore: add AMap ephemeral live interface
1ca7ce1 2026-07-29 docs: record WU7B AMap ephemeral live plan
ef43944 2026-07-29 docs: prepare WU7R provider-neutral parser review
8388583 2026-07-29 chore: add provider-neutral parser verification
1b9b3a1 2026-07-29 refactor: implement provider-neutral parser contract
5996245 2026-07-29 test: correct UTF-8 synthetic compatibility baseline
```

**返工痕迹（`git log --format=format: --name-only` 计数）**：

| 文件 | 被改动 commit 数 |
|---|---|
| `src/trip_decider/product_web.py` | 8 |
| `src/trip_decider/travel_agent.py` | 5 |
| `src/trip_decider/agent_actions.py` | 5 |
| `tests/test_product_web.py` | 5 |

单看次数不高，但**单次改动量极大**。`01a273b`（"refactor: unify product runtime modes and routes"）一次提交：16 个文件、**+10,343 / −916 行**，其中 `product_web.py +3,277`、`guided_discovery.py +770`（新文件）、`dynamic_discovery.py +753`（新文件）、`web/app.js +1,665`。这不是渐进重构，是一次性大爆炸提交。7 月 30 日的两条 commit（`3976776` "generic trip runtime baseline"、`57afc6f` "persistent agent runtime baseline"）语义相近、相隔同日，也属于同一处反复奠基。

**可追溯性缺口（重要）**：`runtime/sessions/` 中存在的字段 `catalog_seed_notice` 在**全部 135 个 commit 的任何一版代码里都不存在**：

```
$ git log --all --oneline -S "catalog_seed_notice"
(无输出)
$ git log --all --oneline -S "主题和体力标签来自候选种子库"
(无输出)
$ grep -rl "catalog_seed_notice" runtime/sessions/ | wc -l
11
```

对照组验证 `-S` 有效：`git log --oneline -S "candidate_source_notice"` → `01a273b`。

结论：磁盘上的历史运行数据是由**从未提交过的工作树代码**产生的。

**工作树未提交改动**：

```
$ git status --porcelain
 M src/trip_decider/mcp_app_workspace_v1.html
 M tests/test_mcp_adapter.py
```

改动内容是 MCP App 的 `ui/initialize` 时序、`size-changed` 通知与 `availableDisplayModes`（`git diff tests/test_mcp_adapter.py`），共 +65/−24 行。

---

## 2. 架构还原

### 2.1 对外暴露的 MCP tool（10 个）

字段取自代码实现，非 docstring。返回结构逐个从 `mcp_adapter.py` 与 `trip_query.py` 读出。

| # | tool | 签名（`mcp_server.py`） | 实现 | 返回结构真实顶层字段 |
|---|---|---|---|---|
| 1 | `create_trip_task` | `intent: dict` | `mcp_adapter.py:55-65` | 即 `TripQueryService.trip()`：`session` / `run` / `presentation` / `events`（RUNNING 时额外 `action_loop`）— `trip_query.py:99-121` |
| 2 | `confirm_trip_intent` | `run_id: str, intent: dict\|None = None` | `mcp_adapter.py:67-78` | 同上 |
| 3 | `advance_trip_task` | `run_id: str, wait_seconds: float = 10.0` | `mcp_adapter.py:80-119` | `trip` / `checkpoint`；COMPLETED 时可能加 `plan` 或 `candidates`；RUNNING/BLOCKED/FAILED 时加 `missing`（`mcp_adapter.py:256-276`） |
| 4 | `read_trip` | `run_id: str, view: str = "overview"` | `mcp_adapter.py:121-141` | 取决于 `view`，6 个合法值见 `mcp_adapter.py:28-35` |
| 5 | `show_trip_candidates` | `run_id: str` | `mcp_adapter.py:143-156` | `view`（常量 `"candidates"`）/ `run_id` / **`current_version`（硬编码 `None`，`mcp_adapter.py:153`）** / `candidates` |
| 6 | `show_trip_plan` | `run_id: str` | `mcp_adapter.py:158-175` | `view` / `run_id` / `current_version`（真读 `plan.plan_version`）/ `trip` / `plan` |
| 7 | `select_trip_candidate` | `run_id: str, candidate_id: str` | `mcp_adapter.py:177-191` | `trip` / `accepted` / `action_loop`（`mcp_adapter.py:317-326`） |
| 8 | `submit_trip_evidence` | `run_id: str, evidence: dict` | `mcp_adapter.py:193-207` | 同上 |
| 9 | `revise_trip_plan` | `run_id: str, revision: dict` | `mcp_adapter.py:209-226` | `trip` / `plan`（**无 `accepted`**，与 7/8 不一致） |
| 10 | `audit_trip_plan` | `run_id: str\|None, plan: dict\|None, content: str\|None` | `mcp_adapter.py:228-254` | `trip` / `audit` |

`read_trip` 的 6 个 view 对应真实读模型（`mcp_adapter.py:133-140`）：

- `overview` → `trip_query.trip()`：`session/run/presentation/events`
- `candidates` → `trip_query.candidates()`：`run_id / task_mode / stage / comparison_completed / selection_required / candidates`（`trip_query.py:193-200`）
- `plan` → `trip_query.current_plan()`：`run_id / plan_version / planning_state / plan / context`（`travel_agent.py:972-980` 写入的 payload 形状）
- `missing` → `trip_query.missing_information()`：`planning_draft` 读模型
- `map` → `trip_query.map_payload()`：`plan_version / day / markers / route_polylines`（实测输出）
- `audit` → `trip_query.audit_result()`

**MCP 面 vs HTTP 面能力不对等**：`product_web.py:483-560` 的 REST 还有 `retry-action`（`/api/trips/{id}/actions/{action}/retry`）、`select_hotel`（`evidence` + `hotel_id`）、`execute` 带 `action_id`、以及 `/api/trips` 的自然语言 `text` → intent 解析。MCP 一个都没有。

### 2.2 运行时状态机

**`task_mode`** — 定义在 `src/trip_decider/travel_agent.py:46-52`，4 个取值：

```
OPEN_DISCOVERY / GUIDED_DISCOVERY / DIRECT_PLAN / PLAN_AUDIT
```

**`RunStatus`** — `travel_agent.py:119-125`，6 个取值：

```
AWAITING_CONFIRMATION / CONFIRMED / RUNNING / COMPLETED / BLOCKED / FAILED
```

合法迁移由 `InMemoryAgentStore` 的方法各自守卫（**没有集中的迁移表**）：

| 迁移 | 守卫位置 |
|---|---|
| — → AWAITING_CONFIRMATION | `travel_agent.py:717-721`（`create`） |
| AWAITING_CONFIRMATION → CONFIRMED | `travel_agent.py:786-790`（`confirm`，断言前态） |
| CONFIRMED → RUNNING | `travel_agent.py:804-806`（`start`，断言前态） |
| RUNNING → COMPLETED | `travel_agent.py:823-825`（`complete`，断言前态） |
| RUNNING → BLOCKED | `travel_agent.py:1016-1018`（`block`，断言前态） |
| 任意 → FAILED | `travel_agent.py:991-996`（`fail`，**无前态断言**） |
| COMPLETED → RUNNING | `travel_agent.py:841-845`（`resume`，断言前态） |
| COMPLETED → CONFIRMED | `travel_agent.py:864-874`（同 run 换 intent 继续） |
| {COMPLETED,BLOCKED,FAILED} → CONFIRMED | `travel_agent.py:905-921`（`revise_run` 路径） |

**`stage`** — **不是枚举，是散落的字符串字面量**，只在 `run.result["stage"]` 里出现。全仓 `src/` 中被写入的取值只有 4 个：

| 值 | 写入位置 |
|---|---|
| `"open_discovery"` / `"guided_discovery"` | `guided_discovery.py:464-469`（按 `task_mode` 二选一） |
| `"plan_audit"` | `trip_application.py:494` |
| `"discover"` / `"plan"` | `destination_discovery.py:394,453`（**该模块已不在产品路径**，见 §2.5） |

消费位置分散在至少 6 处：`trip_query.py:144-151,196,245`、`trip_application.py:192`、`mcp_adapter.py:301-313`、`trip_read_model.py:984,1417`。**DIRECT_PLAN 的成功结果不写 `stage`**（`agent_actions.py:1036-1058` 产出的 result 只有 `action_loop_status/planning_state/task_mode/context/planning_draft/validation/pipeline/plan`），这直接导致 §5.1 的现象。

**MCP checkpoint 名**（对外的第三套状态词表）— `mcp_adapter.py:295-314`：`NEED_INTENT_CONFIRMATION / RUNNING / NEED_USER_INPUT_OR_EVIDENCE / CANDIDATES_READY / AUDIT_READY / PLAN_OR_PARTIAL_RESULT_READY`。

**`planning_state`**（第四套）— `planning_input_compiler.py:216-227`：`BLOCKED / COLLECTING_EVIDENCE / PARTIAL_READY / PLAN_READY`；可安装集合 `_INSTALLABLE_STATES = {"PARTIAL_READY","PLAN_READY"}`（`planning_input_compiler.py:21`）。

### 2.3 核心数据模型

| 概念 | 定义位置 | 字段 |
|---|---|---|
| Task（意图） | `travel_agent.py:134-143`（`TravelIntent`，frozen dataclass） | `task_mode, origin, destination_anchor, earliest_departure_at, latest_return_at, travelers, …`（另有 `total_budget_cny/themes/pace/transport_preferences/classification_basis/destination_expression/interpretation` 等，见 `to_dict()`） |
| Run | `travel_agent.py:605-618`（`AgentRun`，可变 dataclass） | `run_id, session_id, intent, status, created_at, parent_run_id, revision, confirmed_at, started_at, completed_at, result, error_code` |
| Session | `travel_agent.py:641-646`（`AgentSession`） | `session_id, created_at, run_ids, current_run_id` |
| Event | `travel_agent.py:579-589`（`AgentEvent`） | `sequence, event_id, session_id, run_id, event_type, status, message, occurred_at, details` |
| Candidate | **无类型定义**。是 `guided_discovery.py:548-590` 的 `_coarse_option()` 返回的匿名 dict，19 个键：`destination_id, destination_anchor, name, region_label, gateway_checked, feasibility_status, coarse_plan_status, roundtrip_transport, playable_time_seconds, local_transport_difficulty, themes, physical_intensity, budget_headroom_after_known_transport_cny, evidence_statuses, evidence_missing, candidate_source_notice` |
| Plan / PlanningDraft | **无类型定义**。`planning_input_compiler.py:233-258` 返回 `artifact_kind: "PlanningDraft"` 的 dict |
| PlanVersion | **无类型定义**。`agent_actions.py:1055-1058` 把 draft 复制一份、改 `artifact_kind: "PlanVersion"`。持久化 payload 由 `travel_agent.py:972-980` 组装：`run_id, plan_version, planning_state, plan, context` |
| Evidence（运行时） | `travel_agent.py:456-522`（`EvidenceItem`，frozen dataclass） | `evidence_id, domain, status(EvidenceStatus), value, sources, missing_reason, conflict_details` |
| Evidence（离线契约） | `schemas/evidence.schema.json` | `fact_id, subject, field, value, unit, support_status, derivation, freshness, sources, normalization, display_status, display_rule, conflict_source_refs, derivation_detail` |
| DestinationContext | `travel_agent.py:525-533` | `context_id, intent, evidence, built_at` |

**Candidate / Plan / PlanVersion 三个核心概念在代码里没有任何类型或 schema 约束**，全靠调用方逐键 `isinstance` 检查。

### 2.4 持久化与 run 生命周期

- 实现：`travel_agent.py:668-702` 的 `InMemoryAgentStore`。**类名与行为不符**——它同时持有内存 dict 和磁盘文件；`__init__` 传入 `runtime_root` 时会 `mkdir(parents=True, exist_ok=True)` 并 `_load_runtime()` 全量加载。
- 默认根目录：`travel_agent.py:1589-1591`，`Path(__file__).resolve().parents[2] / "runtime" / "sessions"`。即仓库根下的 `runtime/sessions/`。当前有 **56 个 session 目录**。
- **模块级副作用**：`travel_agent.py:1592` `DEFAULT_AGENT_STORE = InMemoryAgentStore(_DEFAULT_RUNTIME_ROOT)` 在 import 时就建目录并读盘。任何 `import trip_decider.travel_agent` 都触发。
- 每个 run 目录的文件（实测 `runtime/sessions/f4d3aec8-.../`）：`run.json`、`session.json`、`events.jsonl`、`plan-version.json`、`plans/plan-NNNN.json`、`evidence.json`、`guided-evidence.json`、`action-loop.json`。
- 证据缓存另在 `runtime/evidence-cache/records.json`（`evidence_broker.py:212-222`，`schema_version: "1"`）。
- run 生命周期由 `TripApplicationService`（`trip_application.py:80-...`）编排，实际状态写入全部下沉到 `InMemoryAgentStore`。后台执行用线程：`trip_application.py:786-847`（`_spawn_action_loop` / `_run_action_loop_background`），候选比较用 `ThreadPoolExecutor`（`guided_discovery.py:151-154`）。
- **无数据库、无迁移机制、无 schema 版本号**（除 evidence-cache 的 `schema_version`）。`plan-version.json` 没有版本标记，其格式已在 `b120894` 变更过一次（见 §5.1）。

### 2.5 模块可达性（实测，AST 静态导入图）

以 `mcp_server` 为根做可达性分析，`src/trip_decider/` 36 个模块中：

**可达（22 个）**：`mcp_server, mcp_adapter, mcp_app, trip_services, trip_application, trip_query, trip_read_model, travel_agent, agent_actions, product_web, guided_discovery, dynamic_discovery, destination_runtime, evidence_broker, intercity_rail, itinerary_planner, planning_input_compiler, simple_live, live_place_resolution, schema_validation, acquisition_evidence, adapters.contracts`

**不可达（14 个，合计 13,347 行 = src 的 36.4%）**：

| 模块 | 行数 |
|---|---|
| `amap_ephemeral_live` | 2,950 |
| `e2e_demo` | 1,902 |
| `coarse_planner` | 1,879 |
| `recovery` | 1,431 |
| `evidence_runtime` | 1,335 |
| `verification_entry` | 1,309 |
| `resume_acquisition` | 570 |
| `destination_discovery` | 524 |
| `fixture_validation` | 514 |
| `adapters.route_evidence` | 341 |
| `adapters.open_data_poi` | 299 |
| `codex_host` | 259（另有入口 `scripts/trip_agent.py`） |
| `ingestion` | 17 |
| `adapters`（`__init__`） | 17 |

除 `codex_host` 外的 13,088 行只被测试和彼此引用。`destination_discovery.py` 的唯一导入方是 `tests/test_product_web.py`。

**这构成两条平行世界**：

- 「在线运行时」：MCP/HTTP → `trip_application` → `agent_actions` → `guided_discovery`/`intercity_rail`/`simple_live`/`itinerary_planner`
- 「离线 artifact 管线」（WU0–WU7 遗产）：`e2e_demo` → `recovery` → `evidence_runtime` → `coarse_planner` → `schema_validation` + `schemas/*.json`

两条线各有一套证据模型、一套计划模型、一套状态词表。

---

## 3. 五态证据模型专项核对

### 3.1 五态的准确定义位置

**唯一的五态定义在 `schemas/evidence.schema.json`**：

```json
"display_status": {
  "enum": ["verified", "sourced", "estimated", "conflicting", "unknown"]
}
```

（另有正交的 `support_status: ["verified","sourced","conflicting","unknown"]` 四态、`freshness.status: ["current","stale","unknown"]` 三态、`derivation` 六态。）

`PLAN.md:62-70` 用表格冻结了同一组五态；`PLAN.md:72` 冻结 invariant：

> **Invariant(冻结,不可协商):任何事实的展示状态不得高于证据实际支持的状态。**

### 3.2 代码里实际存在的是四套互不兼容的词表

| 词表 | 取值 | 定义位置 | 是否在 MCP 返回值里 |
|---|---|---|---|
| A. 五态 display_status | `verified/sourced/estimated/conflicting/unknown` | `schemas/evidence.schema.json`；生产者 `evidence_runtime.py:586`、`adapters/route_evidence.py:313` | **否**（两个生产者都不可达） |
| B. 运行时 EvidenceStatus | `sourced/missing/conflicting`（**三态**） | `travel_agent.py:128-131` | 间接（`EvidenceItem.to_dict()`，`travel_agent.py:513-522`） |
| C. 候选展示态 | `LIVE/STALE/MISSING`（**三态**） | `guided_discovery.py:53-59` `_EvidenceCheck.display_status`，赋值在 `guided_discovery.py:593-630, 633-651` | **是**，`show_trip_candidates` 的 `evidence_statuses[].status` |
| D. 行程读模型态 | `LIVE/STALE/MISSING`，域=`railway/attraction/local_transit/accommodation` | `trip_read_model.py:809-846`，输出在 `trip_read_model.py:889-922` | **是**，`presentation.evidence_statuses` |

**结论：五态（词表 A）在产品运行路径上一次都不出现。** 验证命令：

```
$ grep -c '"verified"\|"estimated"\|"conflicting"' <每个可达模块>
mcp_adapter: 0   trip_query: 0   trip_read_model: 0   guided_discovery: 0
dynamic_discovery: 0   evidence_broker: 0   product_web: 0   trip_application: 0
```

可达模块里出现的 `"estimated"` 全部是 `itinerary_planner.py:167,369,406,469,580,1525` 与 `planning_input_compiler.py:372,769,832,981,1137` 的 **`timing_status`/`support` 字段**，语义是「时刻是推算的」，不是证据五态。

**更严重的是字段名撞车**：`planning_input_compiler.py:238-242` 也叫 `display_status`，但取值是 `DISPLAYABLE_CONDITIONAL_ITINERARY / SUPPLEMENTING_DATA`——一个 UI 可展示性开关。它经 `agent_actions.py:1008` 进入 PlanVersion，最终出现在 MCP `show_trip_plan` 的返回里。**同名字段在同一产品的两处含义完全不同**。

### 3.3 状态迁移规则在哪里实现

**没有单一权威实现。至少散落在 5 处，且互相不知道对方存在**：

1. `guided_discovery.py:593-630` `_check_from_evidence()`：`EvidenceStatus.SOURCED → "LIVE"`，其余一律 `→ "MISSING"`；随后若 `value.snapshot.status == "STALE"` 或 `value.freshness.status == "STALE"` 则降为 `"STALE"`。
2. `guided_discovery.py:633-651` `_missing_check()`：直接构造 `MISSING`。
3. `evidence_broker.py:359-443` `_stale_projection()`：把缓存证据改写为 `freshness.status="STALE"`，并按 `data_type` 分支重写 `snapshot.status`、`schedule_status`、`fare_status`、`*availability`、`hotel_price_status`。
4. `trip_read_model.py:223-238` `snapshot_status()` + `trip_read_model.py:809-846`：另一套 LIVE/STALE/MISSING 推导。
5. `planning_input_compiler.py:216-227`：`planning_state` 四态推导（不是证据态，但同样影响对外展示）。
6. `evidence_runtime.py:572-587`（不可达）：唯一一处真正产出五态 `display_status: "unknown"` + `display_rule: "unknown-without-structured-source-v1"` 的实现。

### 3.4 序列化到 MCP 返回值时是否被降级或丢失

**被降级，且有实测证据。**

**降级 1：CONFLICTING → MISSING。** `guided_discovery.py:595-599`：

```python
display_status = "LIVE" if evidence.status is EvidenceStatus.SOURCED else "MISSING"
```

`EvidenceStatus.CONFLICTING`（`travel_agent.py:131`）落进 `else` 分支，变成 `MISSING`。「来源冲突」与「没有信息」在候选卡上无法区分。`EvidenceItem.conflict_details`（`travel_agent.py:466`）也未被 `_coarse_option()` 输出（`guided_discovery.py:548-590` 无该字段）。

**降级 2（违反冻结 invariant）：未知/缺失证据被展示为 `LIVE`。** `trip_read_model.py:231-238`：

```python
return (
    str(status).upper()
    if isinstance(status, str) and str(status).upper() in {"LIVE", "STALE"}
    else "LIVE"
    if domain in evidence          # ← 只要该 domain 的 key 存在，就当作 LIVE
    else "MISSING"
)
```

实测（`PYTHONPATH=src python`，直接调用 `_map_payload_contract`）：

```
railway item present, status=missing   -> [('武汉', 'LIVE'), ('上饶', 'LIVE')]
railway item absent                    -> [('武汉', 'MISSING'), ('上饶', 'MISSING')]
railway snapshot UNKNOWN               -> [('武汉', 'LIVE'), ('上饶', 'LIVE')]
```

即：一条 `status: "missing"`、`missing_reason: "rail_query_failed"` 的铁路证据，在 `read_trip(view="map")` 的 marker 上显示为 `evidence_status: "LIVE"`。这是 `PLAN.md:72` 冻结 invariant 的直接违反，且**证据完全缺失时反而显示 MISSING，证据存在但失败时显示 LIVE**——方向是反的。

**丢失 3：MCP App UI 根本不渲染证据状态。** `mcp_app_workspace_v1.html:212-268` 的候选卡只渲染 `feasibility_status`、`roundtrip_transport`、`playable_time_seconds`、`themes`、`physical_intensity`、`budget_headroom_*` 和 `evidence_missing`（中文自由文本列表）。**`evidence_statuses` 数组在 HTML 全文中未被引用**（`grep -n "evidence_statuses" mcp_app_workspace_v1.html` 无结果）。结构化返回值里有的状态，用户界面上看不到。

**丢失 4：11 个 JSON Schema 不作用于任何 MCP 返回值。** `schema_validation.py` 是唯一 import `jsonschema` 的模块（`schema_validation.py:22-23`），在线路径只用到 `live_place_resolution` 的**解析器**（`simple_live.py:31-40` 只导入 `parse_amap_district_response` / `parse_amap_poi_response` 等），不调用 `validate_artifact` / `validate_bundle`。产品路径唯一的校验是 `itinerary_planner.py:2385-2410` 的 `validate_destination_plan()`——手写的 `evidence_refs` 引用完整性检查，与五态无关。

### 3.5 状态迁移的测试覆盖

| 覆盖对象 | 测试 | 覆盖路径 |
|---|---|---|
| 五态 `display_status` | `test_wu3_evidence_runtime.py:112`、`test_wu2_adapters.py:332`、`test_wu5_e2e_demo.py:327`、`test_wu7_live_place_resolution.py:322`、`test_schema_validation.py:318` | **只覆盖不可达模块**：断言 `unknown`（4 处）、`estimated`（1 处）、`sourced`（1 处）。**`verified` 和 `conflicting` 两个态没有任何断言。** |
| 缓存 STALE 投影 | `test_evidence_broker.py:34,50,113,153,176,224`（6 个用例） | TTL 边界、跨 run 复用、fixture/catalog 来源拒绝、live-first-then-stale |
| STALE → planning blocker | `test_planning_input_compiler.py:255-262` | 断言 `display_status == "SUPPLEMENTING_DATA"`（词表 B/C，非五态） |
| RunStatus 迁移 | `test_product_web.py:220,736,887,889,911,922,1001,1664,1704,1715`、`test_trip_application.py:59` | 覆盖 AWAITING→CONFIRMED→RUNNING→COMPLETED/BLOCKED/FAILED、revise 后回 COMPLETED |
| `LIVE/STALE/MISSING` 在 `trip_read_model` 的推导 | **无直接用例**（`grep "snapshot_status" tests/` 无结果） | — |
| `CONFLICTING → MISSING` 折叠 | **无用例** | — |
| `show_trip_candidates` 返回字段 | `test_mcp_adapter.py:425-434` 只断言 `view == "candidates"` 和 `candidates == candidates`。**`current_version` 无断言**（`current_version` 的 3 处断言 `test_mcp_adapter.py:464,509,569` 全在 `show_trip_plan` 上） | — |

---

## 4. 文档 vs 实现 偏差表

仓库内设计文档：`PLAN.md`（179 行，标头 `# trip-decider · Plan v3(冻结版)`，`PLAN.md:3-4` 声明 "v3.0 · 2026-07-26 冻结 / 方案冻结,进入执行"）、`PRODUCT.md`（60 行）、`README.md`（147 行）、`docs/*.md`（8 个，3,996 行）、`plans/*.md`（21 个）、`docs/reviews/*.md`（17 个）。

PLAN.md 已标记 frozen，以下偏离一律列出，不代为找理由。

| 文档位置 | 文档声称 | 代码实际（路径:行号） | 偏差类型 |
|---|---|---|---|
| `PLAN.md:62-70` | 每个进入决策的事实字段必须携带五态之一：verified/sourced/estimated/conflicting/unknown | 运行时枚举只有三态 `sourced/missing/conflicting`（`travel_agent.py:128-131`）；对外候选态是 `LIVE/STALE/MISSING`（`guided_discovery.py:595-624`）；五态仅存在于 `schemas/evidence.schema.json` 和不可达的 `evidence_runtime.py:586` | **实现不符** |
| `PLAN.md:72`（冻结 invariant） | 任何事实的展示状态不得高于证据实际支持的状态 | `trip_read_model.py:231-238` 在证据条目存在但 `status="missing"` 或 `snapshot.status="UNKNOWN"` 时返回 `"LIVE"`；已实测（§3.4） | **实现不符（违反冻结项）** |
| `PLAN.md:44` | `[D] 字段级证据采集与定级  v0:实现(五态模型)` | 产品路径的定级是 `guided_discovery.py:593-630` 的三态映射 | **实现不符** |
| `PLAN.md:74` | unknown 或 conflicting 的事实不得静默成为硬约束决策依据 | `guided_discovery.py:520-536`：可行性判定只看 `evidence.status is SOURCED`；conflicting 已在 `:595-599` 被折叠成 MISSING，无法区分 | **实现不符** |
| `PLAN.md:35`（架构红线 1） | 不得存在任何城市专属的代码或配置 | `src/trip_decider/destination_catalog.json` 硬编码 28 个中国目的地；`guided_discovery.py:715` 硬编码 `("自治州","地区","市","县","区")`；`guided_discovery.py:723-736` 硬编码中文词表；`travel_agent.py:55-61` 硬编码 `("倾向","优先","大概想去","考虑")`；`PRODUCT.md:22,27` 自述只有「武汉—婺源」一条链路已验证 | **实现不符（违反红线）** |
| `PLAN.md:37-46`（管线 A–H） | 阶段 A→H 顺序管线，模块 B 的数据契约 v0 定死 | 存在两套并行实现：在线 `agent_actions → guided_discovery/itinerary_planner`，离线 `e2e_demo → recovery → evidence_runtime → coarse_planner`；后者从 MCP 入口不可达（§2.5） | **实现不符** |
| `PLAN.md:47`（架构红线 2） | 阶段间以文件传递(fixture-first,可重跑) | 在线路径阶段间靠内存 dict + 线程（`trip_application.py:786-847`）；落盘的只有 run 快照 | **实现不符** |
| `PLAN.md:105-113`（工件契约） | `request.yaml / constraints.yaml / candidates.json / evidence.json / plan.json / violations.json / trip-card.html` | 只有不可达的 `e2e_demo` 产出这套工件（实测演示产出 13 个文件）；在线路径产出的是 `run.json / plan-version.json / events.jsonl / guided-evidence.json / action-loop.json` | **实现不符** |
| `PLAN.md:140` | `D1-2 … evidence.json 五态落地` | 在线路径无 `evidence.json` 五态；run 目录下的 `evidence.json` 是 `EvidenceItem` 三态序列化 | **未实现** |
| `PLAN.md:148-160`（预注册验收） | 硬指标：8.5 前产出江西行程且实际按它走；全程零次「标称 verified、实际为错」 | 代码从不产出 `verified`（§3.2 grep 计数为 0），该 invariant 检验在当前实现下**不可能被触发**，即验收判据形同虚设 | **实现不符** |
| `README.md:133` | tests：210 | 实测 `Ran 261 tests` | **文档过期** |
| `README.md:134` | schemas：11 | `ls schemas/*.json` = 11 | 一致 |
| `README.md:135` | fixture directories / embedded documents / dirty cases：7 / 40 / 7 | `ls -d fixtures/fixture_*` = 6（另有 `golden_cases/`、`jiangxi_multi_identity_smoke/`）。embedded documents / dirty cases 无可机械核对的定义 | **文档过期 / 无法判断** |
| `README.md:35-49`（架构图） | `Real OSM Anchor → Offline Recovery → Evidence Runtime → Constraint Projection → Coarse Planner → Static HTML Report` | 图中 5 个环节对应的模块（`recovery/evidence_runtime/coarse_planner/e2e_demo`）从 MCP 入口全部不可达（§2.5）。README 描述的是一条支线 | **文档过期** |
| `README.md:87` | 演示输出 `status=conditionally_feasible scheduled=2 blocked=2 publishable=false report=report/index.html` | 实测逐字一致，产出 13 个文件（README:92 声称 13） | 一致 |
| `README.md:5` | 「trip-decider 不让 LLM 直接编行程」 | 在线路径确实无 LLM 调用（无任何 LLM SDK 依赖，`requirements.lock` 44 行内无） | 一致 |
| `PRODUCT.md:14` | 「产品入口是 `product_web.py`」 | `cc354b8` 已新增 `mcp_server.py` 作为独立入口（`mcp_server.py:304-347`），PRODUCT.md 未更新 | **文档过期** |
| `PRODUCT.md:12` | 「`destination_discovery.py` 默认输出 `PRELIMINARY_NOT_FEASIBILITY_VERIFIED`」 | `destination_discovery.py` 已被产品路径抛弃，唯一导入方是 `tests/test_product_web.py`；候选生成改由 `dynamic_discovery.py:44-179` 用高德实时 POI | **文档过期** |
| `PRODUCT.md:12` | 「`destination_catalog.json` 只是候选种子库」 | 该文件在在线候选生成中已不被读取（`dynamic_discovery.py` 不引用它；唯一读者 `destination_discovery.py:11,25,277,441` 不可达） | **文档过期** |
| `PRODUCT.md:41` | `plans/work-unit-*.md`（当前 21 个） | 实测 21 | 一致 |
| `PRODUCT.md:42` | `docs/reviews/work-unit-*-review.md`（当前 18 个） | 实测 **17** | **文档过期** |
| `PRODUCT.md:43` | `scripts/verify_wu*.ps1`（当前 12 个） | 实测 **11** | **文档过期** |
| `PRODUCT.md:44` | `scripts/run_amap_ephemeral_live.ps1`（历史 live/smoke 入口） | 该文件**不存在**（`test -f` = NO，`git ls-files` 无此项） | **文档过期** |
| `PRODUCT.md:46` | 不得从 `product_web.py`、Discover 或 Plan 运行时调用这些文件 | `product_web.py:18-46` 只 import `agent_actions/trip_application/trip_query/trip_read_model/travel_agent`，未引用 legacy | 一致 |
| `docs/architecture.md:51` | `evidence/`：support、derivation、freshness、source conflict 的正交模型；外显五态映射和依赖传播 | 该实现在 `evidence_runtime.py`，从 MCP 入口不可达 | **文档过期** |
| `docs/artifact-contracts.md:146` | 外显五态确定性映射，优先级固定 | 同上；在线路径无对应实现 | **未实现** |

---

## 5. 可疑现象逐条定位

**先定位样本**：题目描述的返回值与 `runtime/sessions/f4d3aec8-cf6f-49fd-9e09-ff55e4d267c7` 完全吻合（脚本扫描 56 个 session 后唯一命中）：

```
==== f4d3aec8-cf6f-49fd-9e09-ff55e4d267c7 candidates: 2
   婺源   | playable: 265620.0 | ev: [('railway','STALE',True,False), ('map','MISSING',False,False), ('web','MISSING',False,False)]
   三清山 | playable: 267780.0 | ev: [('railway','STALE',True,False), ('map','MISSING',False,False), ('web','MISSING',False,False)]
```

该 run：`created_at 2026-07-30T20:09:09`、`completed_at 2026-08-01T17:03:53`、`status COMPLETED`、`intent.task_mode GUIDED_DISCOVERY`（选择后改为 DIRECT_PLAN）。

**前置事实（影响下面 5 条的可信度）**：该 run 的候选事件里字段名是 `catalog_seed_notice`，而当前代码的字段名是 `candidate_source_notice`（`guided_discovery.py:586`）。`catalog_seed_notice` **在全部 135 个 commit 中都不存在**（§1.6）。因此这份返回值是由一份未提交的旧代码产生的。下面逐条区分「当前代码仍会复现」与「已随代码变更」。

---

### 5.1 `comparison_completed=true` 但 `current_version=null`

**两个独立成因，都在当前代码里成立。**

**成因 A（设计如此，但是错的）**：`mcp_adapter.py:143-156`：

```python
def render_trip_candidates(self, run_id):
    return self._guard(lambda: {
        "view": "candidates",
        "run_id": run_id,
        "current_version": None,        # ← 第 153 行，硬编码
        "candidates": self._query.candidates(run_id),
    })
```

`current_version` **无条件返回 `None`**，与 run 的实际状态无关。对照 `render_trip_plan`（`mcp_adapter.py:164-173`）是真读 `plan.get("plan_version")`。这是为了让 MCP App 的两个 render tool 共用一个信封而塞的占位字段。测试没有覆盖（§3.5）。

**成因 B（缺陷，且是数据格式回归）**：即使改成真读，这个 run 也读不到。`trip_query.py:293-319` `_current_plan_payload()` 的准入判定：

```python
if (planning_state not in {"PARTIAL_READY", "PLAN_READY"}
    or plan.get("artifact_kind") != "PlanVersion"
    or plan.get("planning_state") != planning_state
    or plan.get("displayable") is not True):
    return None
```

实测该 run 的 `plan-version.json`：

```
plan-version top keys: ['plan', 'plan_version', 'run_id']
plan_version: 9 | planning_state: None
plan.artifact_kind: None | plan.planning_state: None | displayable: True
```

文件里**根本没有 `planning_state` 键，`plan.artifact_kind` 也不是 `"PlanVersion"`**。写入方 `travel_agent.py:972-980` 现在会写这两个键，但该写入契约是 `b120894`（2026-08-01 21:46）才加的（`git log -S 'planner result is not eligible for plan installation'` → `b120894`），读取端的判定是 `a24f305` 才加的（`git log -S 'PARTIAL_READY' -- trip_query.py` → `a24f305`）。

**结论**：`b120894` 变更了 `plan-version.json` 的落盘格式，**没有版本号、没有迁移、没有兼容分支**。所有此前产生的 run（该 run 已经装到第 9 版计划）在当前代码下都被判定为「没有已安装计划」。`comparison_completed=true` 正常（`trip_query.py:187-192` 从 `guided.comparison.completed` 事件推出，该事件存在，实测 `comparison.completed present: True`）。

**定性：两处都是缺陷。A 是明知故犯的占位，B 是无迁移的格式回归。**

---

### 5.2 `evidence_statuses` 只出现 STALE 和 MISSING；五态其余状态在这条路径上是否可能出现

**不可能。这条路径上的取值域只有 3 个：`LIVE / STALE / MISSING`。**

取值域的完整生成集合（`guided_discovery.py`）：

- `:593-630` `_check_from_evidence()`：`SOURCED → "LIVE"`；其余 → `"MISSING"`；再按 `snapshot.status=="STALE"` 或 `freshness.status=="STALE"` 降为 `"STALE"`。
- `:633-651` `_missing_check()`：固定 `"MISSING"`（用于 collector 未配置 / 取消 / 异常 / 超时）。

`_coarse_option()`（`guided_discovery.py:575-584`）直接把 `checks[domain].display_status` 放进 `evidence_statuses[].status`，中间无任何映射。

因此 `verified / estimated / conflicting / unknown / sourced` **在这条路径上永远不会出现**。更具体地：

- `conflicting`：`EvidenceStatus.CONFLICTING` 存在（`travel_agent.py:131`），但在 `:595-599` 落进 `else` 分支被折叠成 `MISSING`，且 `conflict_details` 未被输出。**信息丢失**。
- 本例中 `LIVE` 没出现的原因：railway 走了缓存降级路径（见 5.3），map/web 采集失败。实测 `guided-evidence.json`：`map.missing_reason = "exact_destination_district_not_found"`，`railway.status = "sourced"`。

**定性：缺陷。五态是产品的核心差异化声明（`PLAN.md:62-72`），但对外的候选比较接口在设计上就无法表达它。**

---

### 5.3 railway `from_cache=true` 且 `status=STALE`，系统不重采、不提示刷新；刷新策略与阈值

**刷新阈值在 `evidence_broker.py:38-61`，`FRESHNESS_POLICIES`：**

| data_type | stale_ttl_seconds | stale_allowed |
|---|---|---|
| `seat_availability` | 0 | **False** |
| `hotel_price` | 0 | **False** |
| `railway_schedule_fare` | 21600（**6 小时**） | True |
| `route_duration` | 21600（6 小时） | True |
| `poi_coordinate` | 2592000（30 天） | True |
| `opening_hours` | 86400（24 小时） | True |
| `ticket_price` | 86400（24 小时） | True |
| `destination_profile` | 86400（24 小时） | True |

**STALE 只在一条路径上产生**：`evidence_broker.py:177-206` `stale_after_failure()`，且开头就断言「必须是一次已经失败的实采」：

```python
if _is_usable_live(query, live_failure):
    raise TravelAgentError("stale lookup requires an unusable live result")
```

调用点全部在 `guided_discovery.py:335-341`（采集返回非 SOURCED）、`:370-385`（采集抛异常）、`:422-435`（采集超时）。另有约束 `record.run_id == run_id → return None`（`:195-196`，同 run 不复用自己的缓存）与 `age > stale_ttl_seconds → return None`（`:203-205`）。

**所以「没有触发重新采集」是设计如此**：STALE 是「已经试过实采、失败了、才退回 6 小时内的旧值」的结果，不是「跳过采集直接用缓存」。本例 railway `collected_at = 2026-07-30T17:42:14`，而事件写入于 `2026-07-30T20:09` 前后，符合 6 小时 TTL。

**但「没有向调用方提示需要刷新」是缺陷。** `_stale_projection()`（`evidence_broker.py:359-379`）明明写入了两个可用信号：

```python
normalized["freshness"] = {"status": "STALE", "retrieved_at": ..., "expires_at": ..., "data_type": ...}
normalized["refresh_failure"] = {"missing_reason": live_failure.missing_reason}
```

`expires_at` 和 `refresh_failure` **都没有被 `_coarse_option()` 输出到候选卡上**（`guided_discovery.py:556-566` 的 `roundtrip_transport` 只取 `status/duration/known_cost/outbound/return/retrieved_at/missing_reason/from_cache/timed_out`）。同时 `_stale_projection` 返回的 `EvidenceItem`（`evidence_broker.py:437-443`）**没有传 `missing_reason` 参数**，默认为 `None`——这正是本例 `roundtrip_transport.missing_reason = null` 而 `status = "STALE"` 的原因。

MCP 面也**没有任何刷新工具**：10 个 tool 里没有 `retry_action`（该能力只在 HTTP 面，`product_web.py:536-549`）。调用方即使知道数据陈旧也无法通过 MCP 触发重采。

**定性：「不自动重采」是设计；「不提示、不暴露 expires_at/refresh_failure、MCP 无重试入口」是缺陷。**

---

### 5.4 map/web `status=MISSING` `timed_out=false` 但没有原因字段；与 `roundtrip_transport.missing_reason` 不一致

**成因在 `guided_discovery.py:548-590` 的结构设计——railway 有专属块，map/web 只有通用元组。**

```python
"roundtrip_transport": {                       # :556-566，railway 专属，10 个字段
    "status": rail_check.display_status,
    ...
    "missing_reason": evidence.missing_reason,  # :563  ← 只有这里有
    "from_cache": rail_check.from_cache,
    "timed_out": rail_check.timed_out,
},
...
"evidence_statuses": [                          # :575-584，三域通用，只有 5 个字段
    {
        "domain": domain,
        "status": checks[domain].display_status,
        "collected_at": checks[domain].collected_at,
        "from_cache": checks[domain].from_cache,
        "timed_out": checks[domain].timed_out,
    }
    for domain in ("railway", "map", "web")
],
```

`missing_reason` **确实存在于内部对象上**——`_EvidenceCheck.evidence.missing_reason`（`guided_discovery.py:55`）在 `_missing_check()` 里被填成 `"collector_not_configured"` / `"cancelled_by_user"` / `"collector_error:<Type>"` / `"collector_timeout"`（`:222,276,358,409`），实采失败时是 provider 给的原因（本例 `guided-evidence.json` 里 map = `"exact_destination_district_not_found"`）。**它在写 `evidence_statuses` 时被丢掉了。**

为什么不一致：`roundtrip_transport` 是先写的、面向「跨城交通」这个业务概念的富结构；`evidence_statuses` 是后加的、面向「三个 collector 都跑完了没有」的进度元组。两者是不同意图的产物，没人回头统一。

对照：`travel_agent.py:495-498` 在构造 `EvidenceItem` 时**强制**要求 `MISSING` 必须带 `missing_reason`——即数据模型层是要求有原因的，只是展示层没有透出。

**定性：缺陷。数据存在、模型强制要求、展示层单方面丢弃。**

---

### 5.5 `catalog_seed_notice`：硬编码还是动态生成；是否说明种子与事实的边界未在代码层强制隔离

**是硬编码的中文字符串字面量，且当前已改名。**

- 观测到的字段名 `catalog_seed_notice` 与文案「主题和体力标签来自候选种子库，不是交通、价格或可行性事实来源。」**在 135 个 commit 中都不存在**（§1.6）。它来自一份未提交的旧工作树。
- 当前对应实现是 `guided_discovery.py:586-589`：

```python
"candidate_source_notice": (
    "候选来自本次高德POI实时检索；可行性只使用"
    "本次铁路、地图和补充事实证据。"
),
```

同样是**无条件拼接的字面量**，不读取任何证据状态、不随 run 变化。且 MCP App HTML 从不渲染它（`grep -n "notice" mcp_app_workspace_v1.html` 只匹配到 CSS class 和错误提示）。

**「是否说明边界未强制隔离」——是的，而且有比这条文案更硬的证据。** 看同一个 `_coarse_option()` 返回体（`guided_discovery.py:548-590`）：

```python
"themes": list(seed.get("themes", [])),                       # :572 ← 种子来源
"physical_intensity": seed.get("intensity"),                  # :573 ← 种子来源
"region_label": seed["region_label"],                         # :552 ← 种子来源
"roundtrip_transport": {...},                                 # :556 ← 证据来源
"playable_time_seconds": playable,                            # :567 ← 证据推算
"evidence_statuses": [...],                                   # :575 ← 证据来源
```

**种子派生字段和证据派生字段在同一层 dict 里平铺，无命名空间、无 provenance 标记、无类型区分。** 唯一的边界表达就是那句人类可读的中文提示——即「靠文案约定，不靠代码约束」。下游消费方（`trip_read_model.py:1068-1126`、`mcp_app_workspace_v1.html:224-232`）也确实无差别地把 `themes` / `physical_intensity` 和 `roundtrip_transport` 放在同一张卡片上呈现。

补充：`dynamic_discovery.py:157-160` 生成 seed 时，`themes` 直接抄自用户 intent（`list(intent.themes)`），`intensity` 硬编码为 `"待核验"`。所以「主题」字段实际是用户自己的输入回显，既不是种子库也不是证据——文案本身也不准确。

**定性：缺陷。用文案代替类型约束。**

---

### 5.6 只有 2 个候选，且两者 `playable_time_seconds` 差异不足 40 分钟

**候选数量是数据源枯竭的结果，不是配置。**

- 事件实证：`runtime/sessions/f4d3aec8-.../events.jsonl` seq 267 `guided.comparison.started` 的 `details.candidate_count = 2`，seq 282 `guided.comparison.completed` 的 `option_count = 2`。`candidate_count` 在 `guided_discovery.py:120-125` 是 `len(seeds)`，即**种子生成阶段就只产出了 2 个**，不是后续被过滤掉的。
- 调用链：`guided_discovery.py:119` `seeds = guided_region_seeds(intent, limit=3)` → `guided_discovery.py:83-85`（校验 `limit in {2,3}`，否则报错）→ `dynamic_discovery.py:44-179` `dynamic_destination_seeds(intent, limit=3)`（校验 `limit in {2,3,4,5}`——**两处校验集合不一致**）。
- 生成逻辑：`dynamic_discovery.py:64-120`，用 `_discovery_queries(intent)` 并发调高德 POI 搜索（每关键词最多 25 条），按 `district_code` 分组，按「组内不同 `provider_record_id` 数量降序、标签升序」排序（`:114-120`），取前 `limit` 组（`:170-171` `if len(seeds) == limit: break`）。
- 下限守卫：`dynamic_discovery.py:175-178`，`len(seeds) < 2` 直接抛 `TravelAgentError("live destination search produced fewer than two candidates")`。**没有任何补位、没有 fallback 到 catalog。**

所以「2 个」= 高德在「江西上饶、婺源那块」这个 anchor 下只聚出 2 个不同的 district_code。上限是 3，下限是 2，中间没有质量判据。

**筛选逻辑与差异性无关。** 排序键（`dynamic_discovery.py:114-120`）只有「POI 命中数」和「标签字典序」——**没有任何多样性/差异化目标函数**。这与 `PLAN.md:19` 声称的「筛出 2-3 个**差异化**的可行目的地方案」直接冲突。

`playable_time_seconds` 的算法（`guided_discovery.py:502-513`）：

```python
available = _available_seconds(intent)        # latest_return_at - earliest_departure_at
playable = max(0.0, available - duration)     # 减去往返铁路时长
```

本例 `available` 对两个候选完全相同（同一 intent），差异只来自 `roundtrip_duration_seconds`：婺源 29,580s、三清山 27,420s，差 2,160s = **36 分钟**。也就是说，`playable_time_seconds` 这个指标在同一 intent 下**只能反映往返车程差**，与目的地本身的可玩内容无关。两个候选看起来「差不多」是这个指标定义的必然结果，不是巧合。

**定性：候选数量是数据源结果（设计如此，无兜底）；「候选无差异化」是缺陷，与 PLAN.md:19 的产品定义不符。**

---

### 5.7 交通证据里 `duration_seconds` 与 outbound/return 分段时长是否有校验

**没有任何校验。一致性是「同源产生」的副产品，不是被保证的不变式。**

- 产生端一致：`intercity_rail.py:600-603`

```python
"roundtrip_fare_cny": float(total),
"roundtrip_duration_seconds": (
    outbound.duration_seconds + inbound.duration_seconds
),
```

同一个函数里同时产出三个值，所以实采路径下必然自洽（本例婺源 12,960 + 16,620 = 29,580 ✓）。

- 消费端不校验：`guided_discovery.py:502-504` 与 `:558-561` **各自独立**从 rail dict 里取值：

```python
duration = _nonnegative_number(rail.get("roundtrip_duration_seconds"))   # :502
...
"duration_seconds": duration,                    # :558
"outbound": _train_summary(rail.get("outbound")), # :560
"return": _train_summary(rail.get("return")),     # :561
```

`_train_summary()`（`guided_discovery.py:678-689`）只做键投影，不做任何数值检查。`_nonnegative_number()`（`:700-707`）只查 `>= 0`。**两者之间没有一行断言。**

- STALE 投影也不重算：`evidence_broker.py:380-401` 处理 `railway_schedule_fare` 时改写了 `snapshot.status`、`schedule_status`、`fare_status`、`*availability`，但 `roundtrip_duration_seconds` 原样保留、outbound/return 的 `duration_seconds` 原样保留。若缓存值本身不自洽，会被原封不动传播。

- 外部注入路径完全无防护：`submit_trip_evidence`（`mcp_adapter.py:193-207`）→ `trip_application.submit_run_evidence`（`:279-299`）→ `EvidenceItem.from_mapping`（`travel_agent.py:468-511`）。`from_mapping` 只校验 `status/evidence_id/domain/sources/missing_reason/conflict_details` 的存在性与类型，**`value` 是 `deepcopy(value.get("value"))` 原样收下**（`travel_agent.py:507`）。也就是说，一个 MCP 客户端可以提交 `roundtrip_duration_seconds: 60` 配 `outbound.duration_seconds: 99999`，系统全盘接受，并据此算出 `playable_time_seconds` 和 `feasibility_status`。

- schema 层也不管：`schemas/*.json` 不作用于在线路径（§3.4 丢失 4）。

**定性：缺陷。跨字段一致性完全没有校验层，且外部可注入。**

---

## 6. 债务清单

按严重度排序。给现象、证据位置、影响面。**不给修复方案。**

### 阻断

**B1. 五态证据模型在产品运行路径上不存在**
- 现象：产品对外声称的核心差异化（诚实标注证据强度）在 MCP 返回值里只有 `LIVE/STALE/MISSING` 三态；`verified/estimated/conflicting/unknown` 一次都不出现。
- 证据：`schemas/evidence.schema.json`（唯一五态定义）vs `travel_agent.py:128-131`（三态枚举）vs `guided_discovery.py:595-624`（三态展示）；可达模块 grep 计数为 0（§3.2）；唯一五态生产者 `evidence_runtime.py:586` 从 `mcp_server` 不可达（§2.5）。
- 影响面：全部 10 个 MCP tool 的返回值；MCP App UI；`PLAN.md:62-72` 冻结契约；`PLAN.md:148-160` 的验收判据（「零次标称 verified 实际为错」在从不产出 verified 的实现下无法检验）。

**B2. 缺失/未知证据被展示为 LIVE，违反冻结 invariant**
- 现象：`status:"missing"` 或 `snapshot.status:"UNKNOWN"` 的证据，在 map 读模型里渲染成 `evidence_status: "LIVE"`；证据完全缺席时反而显示 `MISSING`，方向相反。
- 证据：`trip_read_model.py:231-238`；实测输出见 §3.4。违反 `PLAN.md:72`。
- 影响面：`read_trip(view="map")`、`trip()` 的 `presentation.map_payload`、HTTP `/api/trips/{id}` 的地图渲染。这是「向用户断言一个未经核实的事实为已核实」，是产品定位的反面。

### 高

**H1. `plan-version.json` 落盘格式无版本、无迁移地变更，历史 run 的已安装计划全部不可读**
- 现象：`b120894` 起写入方新增 `planning_state` 顶层键和 `plan.artifact_kind == "PlanVersion"`；读取方 `a24f305` 起把这两项作为准入硬条件。此前所有 run 的 `plan-version.json` 一律被判为「无计划」。
- 证据：写入 `travel_agent.py:954-980`；读取 `trip_query.py:311-318`；实测 `f4d3aec8` 的 `plan-version.json` 有 `plan_version: 9` 但无 `planning_state`、`artifact_kind` 为 `None`。
- 影响面：`runtime/sessions/` 下 56 个 session 中所有 `b120894` 之前产生的 run；`read_trip(view="plan")`、`show_trip_plan`、`presentation.plan_version`、`budget_summary`（`trip_query.py:90-91` 在无计划时置 `None`）。

**H2. 36% 的 src 代码从产品入口不可达，形成两套并行的证据/计划实现**
- 现象：14 个模块共 13,347 行（含 `amap_ephemeral_live` 2,950、`e2e_demo` 1,902、`coarse_planner` 1,879、`recovery` 1,431、`evidence_runtime` 1,335、`verification_entry` 1,309）只被测试和彼此引用。
- 证据：§2.5 的 AST 可达性分析；`destination_discovery.py` 的唯一导入方是 `tests/test_product_web.py`。
- 影响面：261 个用例中大量在测不可达代码（`test_schema_validation.py` 63 个、`test_fixture_validation.py` 19 个、`test_wu*` 系列 ~60 个）；README/architecture.md 描述的架构对应的是这条死支路；任何「测试全绿」的信心与产品路径的实际质量脱钩。

**H3. `show_trip_candidates` 的 `current_version` 硬编码 `None`，且无测试覆盖**
- 现象：无论 run 是否已安装计划，该字段恒为 `null`。
- 证据：`mcp_adapter.py:153`；测试仅断言 `view` 和 `candidates`（`test_mcp_adapter.py:425-434`），`current_version` 的 3 处断言全在 `show_trip_plan`。
- 影响面：MCP App 在候选视图无法判断是否已有计划（`mcp_app_workspace_v1.html:287` 的 `payload.current_version` fallback 永远拿不到值）；任何依赖该字段做分支的宿主。

**H4. MCP 面与 HTTP 面能力不对等，且 `advance_trip_task` 对 COMPLETED run 永不推进**
- 现象：`advance_trip_task` 在 `status` ∈ {AWAITING_CONFIRMATION, COMPLETED, BLOCKED, FAILED} 时直接返回 checkpoint，从不调用 `execute_trip`。而 `TripApplicationService.execute_trip`（`trip_application.py:145-160`）明确支持「COMPLETED/BLOCKED 的 DIRECT_PLAN run 重启 action loop」——这条路径 MCP 客户端够不到。MCP 也没有 `retry_action` / `select_hotel`。
- 证据：`mcp_adapter.py:96-107` 与 `mcp_adapter.py:36-41`；对照 `product_web.py:483-560` 的 REST 路由。
- 影响面：MCP 宿主无法重试失败的单个 collector、无法选酒店、无法继续一个已完成的计划 run；同一后端在两个宿主面下能力不同。

**H5. MCP 工具面几乎无测试**
- 现象：10 个 tool 只有 3 个用例（`test_mcp_adapter.py:230,243,276`），其中一个还是纯架构断言（`test_adapter_has_no_store_http_or_projection_dependency`）。
- 证据：`grep -c "    def test_" tests/test_mcp_adapter.py` = 3；对比 `test_schema_validation.py` = 63（测的是不可达模块）。
- 影响面：测试投入与产品面严重错配；`current_version`、`checkpoint` 名、错误路径、`audit_trip_plan` 的三参数组合均无覆盖。

**H6. 运行时产物无法追溯到任何 commit**
- 现象：`runtime/sessions/` 中 11 个 session 含字段 `catalog_seed_notice`，该字符串在全部 135 个 commit 的任何一版代码中都不存在。
- 证据：`git log --all -S "catalog_seed_notice"` 无输出（对照组 `candidate_source_notice` → `01a273b`）；§1.6。
- 影响面：所有基于历史 run 的观测（包括本次核对的样本）都无法归因到具体代码版本；`01a273b` 一次 +10,343 行的大爆炸提交说明这是常态而非偶发。

### 中

**M1. `CONFLICTING` 证据被折叠为 `MISSING`，`conflict_details` 完全丢弃**
- 证据：`guided_discovery.py:595-599`（`else → "MISSING"`）；`EvidenceItem.conflict_details`（`travel_agent.py:466`）未出现在 `_coarse_option()` 的任何输出字段中（`:548-590`）。
- 影响面：「来源冲突」与「无信息」在候选卡上不可区分，直接违反 `PLAN.md:74`。

**M2. STALE 证据不暴露刷新信号，MCP 无重采入口**
- 证据：`evidence_broker.py:371-379` 写入的 `freshness.expires_at` 与 `refresh_failure` 未被 `guided_discovery.py:556-566` 输出；`_stale_projection` 返回的 `EvidenceItem` 未传 `missing_reason`（`evidence_broker.py:437-443`）导致 `missing_reason: null`；MCP 无 `retry_action`。
- 影响面：调用方无法判断数据还有多久过期、为什么刷新失败、如何刷新。

**M3. `evidence_statuses` 与 `roundtrip_transport` 字段不对称**
- 证据：`guided_discovery.py:556-566`（10 字段，含 `missing_reason`）vs `:575-584`（5 字段，无 `missing_reason`）；`missing_reason` 在内部对象上存在（`:222,276,358,409`）。
- 影响面：map/web 域的 MISSING 无法解释；与 `travel_agent.py:495-498`「MISSING 必须有 reason」的模型约束自相矛盾。

**M4. 跨字段一致性无任何校验，且外部可注入**
- 证据：`guided_discovery.py:502-504` 与 `:558-561` 独立取值无断言；`evidence_broker.py:380-401` STALE 投影不重算；`travel_agent.py:507` 对 `value` 原样 `deepcopy`；`schemas/*.json` 不作用于在线路径。
- 影响面：`submit_trip_evidence` 可提交自相矛盾的交通证据，进而污染 `playable_time_seconds` 和 `feasibility_status`。

**M5. 候选生成无差异化目标，`playable_time_seconds` 只反映车程差**
- 证据：`dynamic_discovery.py:114-120` 排序键只有 POI 命中数和字典序；`guided_discovery.py:508-513` 的 playable = 固定窗口 − 车程。
- 影响面：与 `PLAN.md:19`「筛出 2-3 个**差异化**的可行目的地方案」冲突；候选比较对用户的信息量接近 0。

**M6. 四套状态词表并存，且 `display_status` 字段名被两种语义复用**
- 证据：§3.2 的 A/B/C/D 四表；`planning_input_compiler.py:238-242`（`DISPLAYABLE_CONDITIONAL_ITINERARY`/`SUPPLEMENTING_DATA`）vs `schemas/evidence.schema.json`（五态），同名 `display_status`。
- 影响面：任何读取 `display_status` 的代码都必须先知道自己在哪条管线上；跨管线复用不可能。

**M7. `stage` 不是枚举，DIRECT_PLAN 结果不写 `stage`**
- 证据：`stage` 字面量散落于 `guided_discovery.py:464-469`、`trip_application.py:494`、`destination_discovery.py:394,453`；消费点 6 处；`agent_actions.py:1036-1058` 的 result 无 `stage` 键。
- 影响面：`trip_query.candidates()` 在计划完成后被迫走事件重建分支（`trip_query.py:153-192`），这正是 §5.1 现象的触发条件；`mcp_adapter._checkpoint_name`（`:295-314`）依赖 `stage` 判断 checkpoint。

**M8. 模块级 I/O 副作用与脆弱的路径假设**
- 证据：`travel_agent.py:1592` 在 import 时构造 `DEFAULT_AGENT_STORE`，触发 `mkdir` + 全量 `_load_runtime()`（`:686-688`）；根目录 `Path(__file__).resolve().parents[2]`（`:1589-1591`）假定源码位于 `<repo>/src/trip_decider/`，装成 wheel 后指向 site-packages 的上两级。
- 影响面：任何 import 该模块的进程（含测试）都读写磁盘；本次核对已实测产生副作用（§0）；打包分发会写到非预期位置。

**M9. `InMemoryAgentStore` 类名与行为不符**
- 证据：`travel_agent.py:668-669` docstring 自述 "with optional durable runtime files"；实际默认实例就是持久化的。
- 影响面：读代码的人会低估这个类的 I/O 与并发面（它同时持 `RLock`/`Condition`、写 jsonl、做原子 json 落盘）。

**M10. 无 lint / type-check / CI / 覆盖率**
- 证据：`pyproject.toml` 无 dev 依赖；无 `.github/`；`pytest` 未安装；`requirements.lock` 44 行内无任何质量工具。
- 影响面：36,662 行 src 全靠人工 review；`docs/reviews/` 17 个文件 7,735 行的 review 记录无法机械复现。

**M11. 文档计数与实际不符（多处）**
- 证据：README.md:133 `tests：210` vs 261；PRODUCT.md:42 `18 个` vs 17；PRODUCT.md:43 `12 个` vs 11；PRODUCT.md:44 引用不存在的 `scripts/run_amap_ephemeral_live.ps1`；README.md:135 `fixture directories 7` vs 6。
- 影响面：文档已不能作为核对依据；`README.md:147`「代码能力、文档声明和实际验证必须保持一致」的自我要求未达成。

### 低

**L1. `advance_trip_task` 三个 elif 分支体完全相同**
- 证据：`mcp_adapter.py:100-107`，`COMPLETED` / `{BLOCKED,FAILED}` / `else` 三支都执行 `return self._checkpoint(run_id, before)`；且 `:101-102` 的注释描述的分支行为并未实现。

**L2. `candidate_source_notice` 硬编码且从不渲染，内容还不准确**
- 证据：`guided_discovery.py:586-589` 字面量；`mcp_app_workspace_v1.html` 不引用；`dynamic_discovery.py:157` 的 `themes` 实为用户 intent 回显，`:158` 的 `intensity` 硬编码 `"待核验"`。

**L3. `limit` 校验集合在调用链上下游不一致**
- 证据：`guided_discovery.py:83-84` 要求 `limit in {2,3}`；`dynamic_discovery.py:56-57` 要求 `limit in {2,3,4,5}`。

**L4. `revise_trip_plan` 返回结构与其他 mutating tool 不一致**
- 证据：`mcp_adapter.py:220-224` 返回 `{trip, plan}`，而 `select_trip_candidate`/`submit_trip_evidence`（`:189,205` → `_with_outcome`）返回 `{trip, accepted, action_loop}`。

**L5. 工作树有 2 个未提交改动**
- 证据：`git status --porcelain`：`M src/trip_decider/mcp_app_workspace_v1.html`、`M tests/test_mcp_adapter.py`（+65/−24）。内容是 MCP App 的 `ui/initialize` 时序与 display modes。

**L6. `fail()` 无前态断言**
- 证据：`travel_agent.py:991-996`，与 `confirm/start/complete/block/resume` 都断言前态的做法不一致，任何状态都能被打成 FAILED。

---

## 7. 收敛为决策清单（需 Hugin 拍板）

以下 7 条的答案会改变后续工程路线，且不是实现细节。

**D1. 五态证据模型是继续作为产品定义，还是承认已经废弃？**
- 保留 → 必须为在线路径建立一套权威的证据定级与映射，现有的 `LIVE/STALE/MISSING`、`sourced/missing/conflicting`、`planning_state`、`checkpoint` 四套词表都要重新对齐到它，工作量覆盖 `guided_discovery` / `trip_read_model` / `planning_input_compiler` / MCP 返回契约 / App UI。
- 放弃 → `PLAN.md:62-72` 的冻结 invariant 和「别的工具在数据不足时照样一本正经，这个会诚实说没底」这句对外主张必须改写，产品差异化需要重新定义。

**D2. 两条平行管线（在线 MCP/HTTP 运行时 vs 离线 artifact 管线）保留哪一条为主干？**
- 保在线 → 13,088 行（`e2e_demo`/`recovery`/`evidence_runtime`/`coarse_planner`/`adapters`/`fixture_validation`/`verification_entry`/`amap_ephemeral_live`）连同它们的 ~140 个测试用例、11 个 JSON Schema、6 个 fixture 目录一并成为死代码，README 和 docs/architecture.md 描述的架构作废。
- 保离线 → 现有 MCP App、HTTP 产品页、Codex 桥全部推倒，回到「改 yaml 重跑」的 PLAN.md 原始形态。
- 两条都留 → 必须明确它们的契约边界和同步责任，否则四套状态词表会继续增殖。

**D3. 保留几个宿主面？（MCP STDIO / 本地 HTTP + Web UI / Codex CLI 桥）**
- 三个都留 → 每加一个 application 方法都要在三处暴露，当前已经出现能力漂移（MCP 缺 `retry_action`/`select_hotel`/文本 intent 解析，且 COMPLETED run 无法推进）。
- 收敛到一个 → 另外两条的 UI 资产（`web/app.js` 2,071 行、`web/styles.css` 974 行、`mcp_app_workspace_v1.html` 433 行）需要决定去留。

**D4. `runtime/sessions/` 里的 56 个历史 run 是资产还是包袱？**
- 是资产 → `plan-version.json` 的格式回归（H1）必须补迁移，且今后所有落盘契约需要版本号和兼容策略。
- 是包袱 → 明确宣布历史 run 不保证可读，清空目录，并接受「产品迄今为止的所有真实运行数据都不可回溯」（H6 已表明它们本就无法归因到 commit）。

**D5. `PLAN.md:35` 的架构红线「不得存在任何城市专属的代码或配置」是否仍然成立？**
- 仍成立 → `destination_catalog.json` 的 28 个中国目的地、`guided_discovery.py:715,723-736` 与 `travel_agent.py:55-61` 的中文词表、`PRODUCT.md:22` 自述的「武汉—婺源」专用链路都属于违规，需要处置。
- 不再成立 → 承认这是一个中国境内、以特定线路为起点的产品，`PLAN.md` 冻结状态需要正式解冻并重写，「城市无关」不再作为架构约束或对外卖点。

**D6. `PLAN.md:148-160` 预注册的 v0 验收标准是否仍是验收口径？**
- 仍是 → 硬指标「8.5 前产出江西行程且实际按它走」距今 3 天；且「全程零次标称 verified 实际为错」在当前实现下不可检验（从不产出 `verified`），需要先决定 D1。
- 不是 → 需要一份新的、可机械核对的验收判据，否则「做完了没有」永远没有答案。

**D7. 证据陈旧或缺失时，产品的默认行为是什么？**
- 阻断（不出结果）→ 当前 STALE 会照常进入可行性判定（`guided_discovery.py:520-536` 只看 `SOURCED`，而 `_stale_projection` 返回的仍是 `SOURCED`，`evidence_broker.py:440`），需要反转。
- 降级展示（出结果但标注）→ 需要 D1 的定级体系落地，且展示层必须停止 `LIVE` 默认（B2）。
- 自动刷新 → 需要新增刷新触发器、TTL 之外的主动过期策略，以及 MCP 面的重采入口（H4）。

---

*报告结束。本轮不含修复方案。*
