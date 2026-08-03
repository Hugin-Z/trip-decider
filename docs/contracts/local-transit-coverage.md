# 当地交通：展开范围与缺口

**起因**：用户实测点名（Hugin，2026-08-03）——「行程只给时长估算，不给乘什么、
在哪换、多少钱」。

**归因先说清楚**：这**不是数据源缺口**。`simple_live._transit_route_value` 一直在
解析高德公交路线规划 2.0 的 `segments[].bus.buslines[]`，线路名、上下车站、运营
时刻、`cost.transit_fee`、`walking_distance` 全都采到了、也进了内存。

丢失点是**一处归一化**：`agent_actions._normalize_local_transit` 把采集结果抄进
`local_transit` 时只留了 `duration_seconds` / `distance_meters` / `fare` /
`polyline`，其余原地丢弃。后面每一层（编译器、读取层、界面）都无从显示——它们
拿到的东西里根本没有。

`itinerary_planner.make_transit_event` 更早就写好了渲染 `services` / `board_at` /
`alight_at` / `operating` 的分支，本轮清点**调用点 0 处**：一段写好了、导出了、
从来没接上的能力。

---

## 1. 本轮已展开

| 用户要问的 | 字段 | 出处 |
|---|---|---|
| 乘什么 | `services[].service` | 高德 `buslines[].name` |
| 在哪上车 / 下车 | `services[].board_at` / `.alight_at` | `departure_stop.name` / `arrival_stop.name` |
| 在哪换 | `transfers[]`（相邻两段推出）+ `same_stop` | 派生，不另存 |
| 首末班车 | `services[].operating_start` / `.operating_end` | `start_time` / `end_time` |
| 多少钱 | `fare.amount_cny`（`status: estimated`） | `cost.transit_fee` |
| 走多远 | `walking_distance_meters`（全程合计） | `transit.walking_distance` |

`transfers` 是**推出来的不是存下来的**：第 n 段的 `alight_at` 与第 n+1 段的
`board_at` 之间就是一次换乘。存一份就是第二份可以和 `services` 不一致的数据
（D19）。`same_stop=false` 表示下车站与上车站不同名，需要走出站换乘。

每个字段进 facts 时是**独立一条**（`local_transit[0].services[0].service` 等），
所以运营时刻未知不会拖累线路名——字段级 support 的直接收益。

---

## 2. 缺口

分两类。**采集层可取未取**的可以在不换数据源的情况下补；**数据源不给**的必须先
换或加数据源，本轮都不硬补。

### 2.1 采集层可取未取（改 `simple_live` 即可）

| # | 缺口 | 现状 | 增量 |
|---|---|---|---|
| 1 | **每次换乘各走多远、多久** | 只有整条路线的 `walking_distance` 总和。解析循环里 `bus = segment.get("bus")`，拿不到 `bus` 就 `continue`——`segments[].walking` 被整段跳过 | 解析 `segments[].walking` 的 `distance` / `cost.duration`，与公交段按原顺序交织成一条「步行→乘车→步行」的段序列 |
| 2 | **备选路线** | `min(parsed, key=...)` 只留最优一条，`transits[]` 里其余全丢 | 保留 top-N（响应已经在手，不增加请求） |
| 3 | **途经站** | `buslines[].via_stops` 未解析 | 直接解析；只影响详情展开深度 |

三条都不增加网络请求——响应字节已经拿到了，是解析取舍。

### 2.2 数据源不给（本轮不补）

| # | 缺口 | 为什么 |
|---|---|---|
| 4 | **发车间隔 / 预计等车时间** | 公交路线规划 2.0 不返回准确班次间隔。`bus_time_tips` 是文案不是结构化数值，且不保证有 |
| 5 | **实时到站** | Web 服务路线规划不提供。需要另一类接口 |
| 6 | **票价在部分城市为空** | `cost.transit_fee` 高德不保证返回。缺时如实 `status: unknown`，不按距离折算——按距离编一个票价正是「不猜」要防的 |

---

## 3. 展示

- 事件 detail（时间轴）：线路串 `A（甲站 上，乙站 下）→ B（…）`、全程步行米数；
- 「已核验的当地交通」卡片：线路串 + 需走出站的换乘 + 运营时间 + 步行距离。

票价缺失显示「费用待核验」，不显示 0，也不折算。

---

## 4. 对应测试

`tests/test_local_transit_detail_expansion.py`——三层各守一段：归一化不丢、
字段级投影往返不丢、编译出的事件 detail 上真的有。
