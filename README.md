# trip-decider

trip-decider 从模糊出游意图出发，选出现实可达的目的地，并排出一份真正走得通、能解释、能修改的行程。

当前仓库处于 v0 的 Work Unit 0：仓库基线、handbook 上下文、D0 prior-art，以及目录和工件的文档级契约。冻结产品定义见 [`PLAN.md`](PLAN.md)，当前执行范围见 [`plans/work-unit-0-bootstrap-d0.md`](plans/work-unit-0-bootstrap-d0.md)。

## 当前能力边界

当前没有业务实现：

- 没有 POI 或高德 API 接入；
- 没有实际 JSON Schema、领域模型或 validator；
- 没有 fixture、测试、CLI 或配置加载；
- 没有约束证明、行程求解、重排或 HTML 行程卡；
- 没有能力 A（目的地发现）实现或 Web UI。

WU0 的文档契约不能被表述为上述能力已经可运行。

## 工程纪律

- `PLAN.md` 是冻结的产品 Source of Truth，不直接修改；
- 每个工作单元分别执行 Plan → Hugin 审核 → Execute → Review → Hugin 验收；
- 事实状态不得高于证据实际支持；
- 启发式没有找到方案不等于已经证明无解；
- 语义和检索类真实 anchor 不由 AI 捏造；
- 不提交 key、token、`.env`、真实旅行隐私或未授权真实 fixture；
- 不自动创建远端、不 push、不提前开始下一个工作单元。

## Secrets

WU0 不需要高德 key。未来高德适配器使用环境变量 `TRIP_DECIDER_AMAP_API_KEY`；真实 key 不得写入仓库或日志。
