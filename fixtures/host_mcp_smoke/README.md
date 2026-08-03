# 宿主实测最小可跑夹具（Claude Desktop MCP，2026-08-03）

首次真实宿主实测撞出两个 P0。两条路径的**真实提交形状**脱敏后固定在这里，
供 D21 名单里的两条契约测试使用。

脱敏只改地名与时间窗，**不改键集合、不改嵌套层数、不补键**——形状本身就是
证据：两个 bug 都是「形状对不上」而不是「值不对」，补一个键夹具就不再复现事故。

| 文件 | 来自 | 钉住的事故 |
|---|---|---|
| `user_supply_railway.json` | 宿主按 `railway_manual` 动作的 `required_fields` 手工提交的铁路证据 | 四层校验全过，Planner 消费 `KeyError: 'origin_station'`，run 落 `PLANNER_ACTION_FAILED` |
| `guided_discovery_intent.json` | 宿主首轮提交的意图（目的地是「方向」不是承诺） | 分类为 `GUIDED_DISCOVERY`，比较代理抛 `TravelAgentError` 后 run 无出路 |

## `user_supply_railway.json`

宿主看到的 `required_fields` 是 `["outbound", "return", "fare", "source"]`，
于是它按这四个键提交。四个键都给了，`EvidenceItem.from_mapping` 的四层
（status / evidence_id / domain / sources）全过，`tool.completed` 事件写的是
「12306 查询取得有效证据」——然后 Planner 在 `make_rail_event` 里按
`origin_station` 取值崩掉。声明的表和消费的表不是同一张（D2）。

宿主提交里**没有** `origin_station` / `destination_station`，因为没有任何
地方要求过它们。这正是要钉住的东西：夹具保留这个缺席。

## `guided_discovery_intent.json`

目的地表达是方向而非承诺，`_classify_task_mode` 落到
`destination_anchor_without_direct_commitment` → `GUIDED_DISCOVERY`。分类本身
成立；事故在于比较代理拿不到活体候选时 run 变成没有出口的 BLOCKED。

宿主当时的绕法是在 `destination_expression` 里写「已承诺无需比较」触发
`_DIRECT_DESTINATION_MARKERS` 改走 `DIRECT_PLAN`。**「用户须用话术绕过状态机」
是产品缺陷**，这条夹具的关闭标准就是同款输入不再需要那句咒语。

## 网络

两条契约测试都不依赖网络：采集器与比较构造器由测试注入。
