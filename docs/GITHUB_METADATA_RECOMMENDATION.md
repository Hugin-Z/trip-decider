# GitHub metadata recommendation

本文件只提供 GitHub About 配置建议。没有通过 `gh repo edit` 或网页修改远端仓库。
审计日期：2026-08-07。

## Recommended repository description

> Evidence-constrained travel planning agent that verifies real-world facts before they enter an itinerary.

这句话与 README 和 `pyproject.toml` 一致：重点是事实进入计划前的核验与约束，不暗示
自动预订、全国覆盖或所有数据都实时。

## Recommended topics

| Topic | Why it is appropriate |
| --- | --- |
| `ai-agent` | MCP host 可以理解请求、调用工具并推进有状态任务；事实与决策仍由 trip-decider 的边界约束。 |
| `llm` | 完整 Agent 模式由外部 LLM host 编排；项目明确区分 LLM 与 truth source。 |
| `mcp` | 仓库提供 MCP server、tools 和 MCP App workspace，并有协议与宿主测试。 |
| `travel-planner` | 核心产品输出是经过证据门控的旅行计划和行程审计。 |
| `evidence` | 字段级 evidence、support、freshness 和 next action 是项目的可靠性内核。 |
| `geospatial` | 高德适配器处理地点身份、POI、坐标和路线/当地交通。 |
| `python` | runtime、planner、provider adapters、MCP server 和测试均以 Python 实现。 |

## Current remote metadata at audit time

- Repository: `Hugin-Z/trip-decider`
- Visibility: public
- Default branch: `main`
- Description: `A travel-planning AI that produces itineraries you can actually follow.`
- Topics: `agent`, `claude`, `evidence`, `mcp`, `travel`

发布前由仓库所有者在 GitHub About 中人工应用建议值，并确认没有添加未使用的技术栈。
