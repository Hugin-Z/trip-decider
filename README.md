# trip-decider

一个以证据边界和约束合同为核心的可审计旅行决策原型。

trip-decider 不让 LLM 直接编行程。它先验证地点身份、证据边界和显式约束，再决定什么能够进入规划；不确定或未匹配的地点会作为 blocker 保留下来。

## 当前演示

公开示例输入是一份包含江岭、李坑、篁岭和庆源的婺源两日请求。当前离线结果是：

| 输入地点 | 结果 |
| --- | --- |
| 江岭 | Day 1，进入条件化粗计划 |
| 李坑 | Day 2，进入条件化粗计划 |
| 篁岭 | identity ambiguous，等待确认 |
| 庆源 | unmatched，当前候选池未匹配 |

计划状态是 `conditionally_feasible`，并保持 `publishable=false`。这是一份可审计的粗计划，不是最佳路线、完整旅游攻略或可直接发布的行程。

## 为什么这样设计

普通旅行 Agent 容易在地点同名时静默选择一个身份，在缺少来源时仍给出确定结论，或在没有路线、营业时间证据时声称行程可行。另一个常见错误，是把当前算法的 `no_plan_found` 写成数学上已经证明的 `proven_infeasible`。

trip-decider 采用以下边界：

- provider identity 原样保留，不在采集层静默合并；
- Evidence Gate 决定事实能否支撑后续阶段；
- `constraints.yaml` 是求解阶段唯一的约束 Source of Truth；
- `conditionally_feasible` 明示草案依赖尚未解决的条件；
- `no_plan_found != proven_infeasible`；
- ambiguous 和 unmatched seed 会显式传播到规划结果。

## 架构

```mermaid
flowchart LR
    A[Real OSM Anchor] --> B[Offline Recovery]
    B --> C[Evidence Runtime]
    C --> D[Constraint Projection]
    D --> E[Coarse Planner]
    E --> F[Static HTML Report]
```

- **Real OSM Anchor**：提供已提交、可回放的真实开放数据字节。
- **Offline Recovery**：恢复候选身份、seed accounting 和 record-local facts。
- **Evidence Runtime**：在 candidate-local 边界内生成证据工件和准入状态。
- **Constraint Projection**：只消费规范化约束，不从自然语言猜测求解条件。
- **Coarse Planner**：产生可解释的按日粗分配，并保留 blocker。
- **Static HTML Report**：把正式工件渲染为无脚本、可离线打开的报告。

## Quick Start

前置要求：

- Windows PowerShell；
- Python `>=3.11,<3.12`；
- 从仓库根目录执行命令；
- 项目 `.venv` 按 `requirements.lock` 准备。

首次准备环境：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --requirement .\requirements.lock
```

运行婺源两日演示：

```powershell
$demoRoot = Join-Path $env:TEMP 'trip-decider-wuyuan-demo'

if (Test-Path -LiteralPath $demoRoot) {
    Remove-Item -LiteralPath $demoRoot -Recurse -Force
}

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_wuyuan_demo.ps1 `
  -OutputRoot $demoRoot `
  -OpenReport
```

演示脚本本身不会删除或覆盖已有输出目录。上面的清理命令只删除用户可见、明确指定的系统临时演示目录。

成功时 CLI 输出：

```text
status=conditionally_feasible scheduled=2 blocked=2 publishable=false report=report/index.html
```

## 输出

一次成功运行产生恰好 13 个文件：

- `recovery/`：4 个候选恢复与 accounting 工件；
- `evidence/`：3 个 Evidence Runtime 工件；
- `planning/`：4 个计划、planning gate 与 violations 工件；
- `report/index.html`：1 个静态行程报告；
- `run-summary.json`：1 个顶层运行摘要。

最值得查看的是：

- `report/index.html`：面向人的离线报告；
- `planning/plan.json`：条件化粗计划；
- `planning/planning-gate.json`：未进入计划的 identity blocker；
- `evidence/evidence.json`：正交化的证据状态；
- `recovery/candidates.json`：未静默合并的 provider identities；
- `run-summary.json`：阶段结果、输出引用和网络/LLM 计数。

## 核心工程特点

- 契约驱动、可追溯的 artifact 管线；
- 真实开放数据 anchor 与离线 replay；
- candidate identity 不静默合并；
- support、derivation、freshness 和 source 正交表达；
- 规范化 constraints 作为 solver SSOT；
- 确定性输出、失败传播、事务安装与 rollback；
- 演示全程不调用网络或 LLM。

## 运行数据兼容性

> **运行数据不向后兼容。** `runtime/` 下的运行记录采用 `schema_version` 标记格式版本。v2（2026-08-02，落盘契约移除全部展示状态字段）与 v1 不兼容，且不提供迁移——v1 时期的运行数据无法归因到确定的代码版本（见 `docs/audit/handover-baseline.md` H6），迁移它们没有可验证的正确性标准。升级到 v2 前请自行备份或直接删除 `runtime/`。

本仓库的 v1 存量已于 2026-08-03 删除。删除后首次运行会自行重建目录。

## 当前边界

- 这是原型，不是生产系统；
- 当前只有一个已提交的真实数据 anchor，不声称支持任意城市；
- Evidence 的当前支持上限仍是 `unknown`，不代表来源已经核实；
- 没有路线、交通时间、营业时间或活动时长；
- 不包含地图、酒店、天气、费用、订票或景点推荐；
- ambiguous 地点需要用户确认后才能进一步决策；
- 当前 HTML 计划不可直接发布。

## 验证状态

机械复核（2026-08-03，P5 轮 3）：

- tests：305（1 条预期失败，登记在 `tests/invariant_ledger.json`：I4 等
  `hotel_price` 生产者）；
- fixture directories：9；
- 演示 network / LLM calls：0 / 0。

**本次未重新核对**：`fixtures/` 内部的 embedded documents / dirty cases 计数，
以 [`fixtures/README.md`](fixtures/README.md) 的表为准，不在这里抄第二份（D19）。

**已删除的条目**：原先此处的「schemas：11」指 `schemas/` 目录，该目录在 P4-a
截肢（`c7cbd50`）时整档删除，这行数字自那时起就没有指代对象。原「tests：210」
写于 `dfa6136`，之后再没跟过——这正是 D1 说的那种过期数字：没有任何东西会因为
它错了而响。

## 项目结构

- [`src/trip_decider/`](src/trip_decider/)：离线运行时与阶段边界；
- [`fixtures/`](fixtures/)：合成合同案例、真实 replay anchor、宿主实测夹具；
- [`examples/`](examples/)：可直接运行的公开输入；
- [`scripts/`](scripts/)：演示和独立验证入口；
- [`docs/reviews/`](docs/reviews/)：可复核的工作单元 Review 证据。

项目以简洁的 Plan → Execute → Review 纪律推进；代码能力、文档声明和实际验证必须保持一致。
