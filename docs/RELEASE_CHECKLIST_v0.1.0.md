# trip-decider v0.1.0 release checklist

本清单是创建公开 `v0.1.0` tag / GitHub Release 前的最终人工闸门。勾选只表示对应
证据已经在准备发布的同一个 commit 上复核，不能用本地旧结果代替 GitHub 上的结果。

## Required before release

- [ ] GitHub Actions CI passes on `main`。
- [x] README links are valid（本地相对链接已检查；外部链接在发布前再点检一次）。
- [ ] No screenshots contain secrets or private data（现有 field-report PNG 需由所有者做最终隐私裁决；README 当前不引用截图）。
- [ ] No API keys/tokens/cookies exist in repository（tag 前在最终 commit 上重跑全历史与工作区扫密）。
- [x] Current scope is accurately stated（主要真实复测范围：武汉 → 婺源及上饶区域）。
- [x] Unsupported capabilities are documented（booking、完整酒店库存、完整天气、全国覆盖等）。
- [x] Runtime persistence v1 compatibility statement is visible：`runtime persistence formats before v2 are not supported.`

## CI badge

本地 `origin` 已确认是 `https://github.com/Hugin-Z/trip-decider.git`，workflow 路径是
`.github/workflows/ci.yml`。README 使用以下真实地址，不是占位：

```text
https://github.com/Hugin-Z/trip-decider/actions/workflows/ci.yml/badge.svg
https://github.com/Hugin-Z/trip-decider/actions/workflows/ci.yml
```

badge 只有在 workflow 推送并由 GitHub Actions 实际执行后，才能作为通过证据。

## Verification layers

三层验证回答不同问题，不能合并成一个“测试通过”。

### A. Offline CI

- 确定性回归；
- 不需要 API credentials；
- 每个 PR 和 `main` push 运行；
- 执行 `pytest`、Ruff、Pyright；
- 证明固定输入下的代码与契约没有回退，不证明外部 provider 此刻可用。

### B. Live smoke

- 需要 provider access、网络和 `AMAP_WEB_SERVICE_KEY`；
- 12306 不需要 key，但仍依赖实时网络与当前查询窗口；
- 人工执行 `scripts/smoke_live.py` 与 `scripts/smoke_action_loop.py`；
- 验证当前外部响应能否通过采集器和产品动作循环；一次成功不证明长期可靠性。

### C. Soak

- 在真实 provider 数据和时序波动下重复执行完整动作循环；
- 是发布信心检查，不是普通 CI；
- 需要网络、credentials、配额和更长执行时间；
- 到达明确终态不等于每轮都生成计划，也不证明未来 provider 可用。

详细边界见 [`docs/verification.md`](verification.md)。

## Tag gate

- [ ] 将 consolidation、release-baseline 和 presentation 改动整理为可审计 commit。
- [ ] 推送 `main`，等待 GitHub-hosted CI 通过。
- [ ] 在最终 commit 上执行 manual live smoke，确认当前 12306 / AMap integration；保存脱敏结果。
- [ ] 在最终 commit 上执行 release soak，或由发布负责人明确记录为何接受现有可追溯报告。
- [ ] 在将要打 tag 的 commit 上完成最终扫密与截图人工复核。
- [ ] 核对 `pyproject.toml`、`trip_decider.__version__`、MCP server version 均为 `0.1.0`。
- [ ] 使用 [`docs/releases/v0.1.0.md`](releases/v0.1.0.md) 创建 GitHub Release，最后再创建/推送 `v0.1.0` tag。

## Version audit note

公开版本已对齐：`pyproject.toml`、`trip_decider.__version__` 与 MCP server 都是
`0.1.0`。`product_web.py` 的 HTTP `Server` header 仍使用
`trip-decider-local/0.1`；它是本地服务标识，不是包/release 版本，也没有公开文档依赖
它。本轮因严格禁止修改 `src/` 而保持不动，不把它冒充成已对齐项。
