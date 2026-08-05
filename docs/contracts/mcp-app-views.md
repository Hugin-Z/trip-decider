# MCP App 视图与地图边界

## 单一宿主管线

行程、核验与地图都复用已经在 Claude Desktop 实测通过的
`ui://trip-decider/workspace/v1.html`：工具通过 `ui.resourceUri` /
`openai/outputTemplate` 指向同一个自包含资源，结构化结果仍是权威数据。
MCP Apps 不可用时，客户端只是少一层渲染，不会少任何计划、核验结论或下一步。

## 证据徽章

MCP App 不计算 token。计划事件的 `fact_refs` 在适配层只负责连接到
`trip().presentation.evidence_statuses` 的读取时投影；HTML 原样显示 `token`、
`retrieved_at`、来源和 `next_action.detail`。呈现代码不存在 support/freshness
合取或 token 文案映射。

## 地图选型

采用资源内原生 SVG 坐标图，不接瓦片服务或第三方 JavaScript 地图库。理由：

- Claude Desktop 的 MCP App 运行在沙箱中，自包含 SVG 不依赖外网、API key、
  CSP 放行或宿主额外能力；
- 输入只接受现有 facts / `map_payload` 中明确给出的 GCJ-02 经纬度和路线点，
  无地理编码，也没有名称到坐标的模型推断；
- 地图失败不会影响时间轴、预算和核验表。没有一个有效坐标时整块地图不渲染；
  个别 POI 缺坐标时只略过该点；路线缺几何但两端坐标齐全时画虚线示意连接并
  明标其不是道路几何。

代价是没有真实底图、道路标签、缩放平移和跨坐标系转换。当前图用于展示相对点位与
逐日连接，不用于导航；这比在宿主沙箱中引入一项会失败的网络依赖更符合“地图是增强”
的边界。

## 核验增量

`verify_itinerary` 与 `read_verification` 都绑定同一资源。进行态报告提供“刷新核验
进度”按钮，调用既有 `read_verification(verify_id)` 并用增量结果重绘；宿主在外部
轮询时，`ui/notifications/tool-result` 也会触发同一渲染入口。视图不自动高频轮询，
避免后台核验尚未推进时制造无意义调用。
