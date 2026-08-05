# 第七次复测要点

第六次挂在行程装配：证据提交三轮全部 `accepted: false`、零字段级报错,宿主止损。
宿主自己给的观察数据质量很高,归因几乎是照着它的清单走完的。

**先说结论:宿主的根因假设是错的,但它报的三个现象条条属实。**

---

## 归因

### 决定性测试:宿主假设证伪

宿主假设「user_supply 证据只存了原始附件,未接入与 live-query 相同的 fact
extraction 管线」。按 D6 先做决定性测试:取一次 live-query 成功的内部结构,
**原样**包成 user_supply 提交——

| | facts 条数 | local_transit 段数 |
|---|---|---|
| live-query | 15 | 2 |
| user_supply(同一份内容) | **15** | **2** |

逐条相等。**管线是共用的,假设不成立。**

### 真因是三处各自独立的「说谎」

| # | 现象 | 真因 | 位置 |
|---|---|---|---|
| 1 | `accepted:false` 但证据实际入库 | `submit_run_evidence` 忘了传 `accepted=True`,而它默认 `False`——**漏传不报错** | `trip_application.py:489`(修前) |
| 2 | 事件流发 `support: sourced`,状态计数却是 0 | 事件与可读结构没有一致性约束 | 无守卫 |
| 3 | 描述承诺 missing 给 `required_fields`,实际只回 blockers | `missing_information` 返回 planning_draft,而字段清单在动作快照里,两者从没接上 | `trip_query.py:502` |

### poi_coordinate 疑点:独立缺陷,已单列

宿主看到 map 域 blocker 的 `data_type` 是 `poi_coordinate`,推断「系统要的可能
是坐标」而自己交的是班车时刻。

**这个推断合理但错。** `poi_coordinate` 是 **freshness 策略的键**,不是 schema
提示——map 域解析过路线时是 `route_duration`,否则是 `poi_coordinate`
(`evidence_projection.py:99-105`)。它跟「该交什么形状」毫无关系。

宿主没有任何办法知道这一点,因为**没有任何地方说过它不是**。这条由「missing
视图公布 schema」覆盖:以后不必去猜 `data_type` 的含义,直接看
`pending_actions[].required_fields`。

---

## 本轮修了什么

1. **「半接受」在形状上不可能**——`ApplicationOutcome` 的 `accepted=False` 且
   本命令是收活的时,`rejection_reason` 必填(构造即校验)。返回体新增
   `parsed_facts_count`(布尔不够,数字才说得清进去了多少)。
2. **事件与状态一致**——用例钉住「事件宣布 sourced ⇒ planner 可读结构里必须
   有事实」,逐域核对。
3. **missing 兑现承诺**——新增 `pending_actions[]`,每项带
   `required_fields` / `optional_fields` / `example` / `submit_action_id`,
   直接取自动作快照(不另造第二份 schema)。另有用例:**描述里承诺的字段,
   missing 返回体必须在场**。
4. **守卫扩展**——从「错误必带 next_call」扩到「**否定语义布尔必带解释**」
   (`accepted`/`valid`/`allowed`/`complete` 为假时)。裸 `false` 会红。
5. **I12 覆盖面重画成四段**——提交 / 入库 / 解析 / 消费,任何一段不接都红,
   夹具用宿主三轮的真实提交形状。

---

## 复测场景

### A. 提交证据(本轮核心)

走到需要补 map 或 web 证据处,让宿主提交。

| # | 看什么 | 通过 |
|---|---|---|
| A1 | 成功提交的返回体 | `accepted: true` + `parsed_facts_count > 0` |
| A2 | 被拒的提交 | `accepted: false` **且**带 `rejection_reason` / `missing_keys`,不再是裸 false |
| A3 | 宿主是否还需要多轮试错 | 目标 **≤1 次**被拒即改对 |
| A4 | 事件流说 sourced 时 | 对应域的计数应同步动,不再一个说有一个说无 |

### B. missing 视图(本轮新兑现)

让宿主调 `read_trip(view="missing")`。

| # | 看什么 | 通过 |
|---|---|---|
| B1 | 返回体是否有 `pending_actions` | 有 |
| B2 | 每项是否带 `required_fields` | 有 |
| B3 | 宿主是否照着它一次填对 | 这是本轮最想看到的 |

### C. 呈现层实渲验收(随本次)

前几轮的三视图只做过内容级单测(Node + 假 DOM),**没在真宿主里渲染过**。

| # | 看什么 | 记什么 |
|---|---|---|
| C1 | 行程视图 | 时间轴、徽章颜色、预算表是否正常显示 |
| C2 | 核验报告 | 总评串、conflicting 两值是否并排 |
| C3 | 地图 | SVG 是否渲染;坐标缺失时是否优雅无图 |
| C4 | 宿主不支持 App 渲染时 | 结构化内容是否仍然完整可用 |

## 本轮**没有**改的(撞到不算回归)

- 住宿价格 unknown——高德 POI 无价格字段(实测 250 样本 0 命中),I4 的
  生产者写得对但对着实网永远产 unknown
- 景点开放时间 / 门票价格 unknown(同族)
- 发车间隔、实时到站、备选路线、途经站名
