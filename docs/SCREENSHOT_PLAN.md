# Public screenshot plan

README 当前不使用截图。现有 `docs/field-reports/*.png` 是 Claude 宿主中的历史故障与
复测片段，不是当前产品界面，也不能完整展示 intent、计划和证据状态，因此只保留为
工程记录，不复制到公开首页。

下面四张图应来自同一份干净的公开演示数据。不要为截图修改 runtime，也不要伪造
provider 结果；若真实运行没有出现目标状态，就记录结果，不强行截成预期结论。

## Screenshot 1 — Hero

- **真实场景**：复用武汉 → 婺源及上饶区域的 DIRECT_PLAN 宿主复测场景；日期改为
  截图时 12306 可查询的公开演示日期，两人、预算 ¥6000、慢节奏、自然与古村。
- **操作步骤**：在 Claude Desktop/MCP 或 standalone Web 创建并确认任务，走到已安装
  PlanVersion；展开一天的行程和证据详情。
- **停留状态**：最终 itinerary 可见，同时至少一条交通事实显示 evidence status。
- **画面必须有**：用户需求、最终行程、evidence status。
- **不得出现**：宿主账号、头像、会话侧栏、真实私人日期、key、绝对路径或 run ID。

## Screenshot 2 — Candidate comparison

- **真实场景**：使用 `scripts/smoke_action_loop.py` 的 OPEN_DISCOVERY 场景——武汉出发，
  “想找个山里安静的地方待两天”，两人、预算 ¥4000、自然风光；日期取当前可查询窗。
- **操作步骤**：完成 intent 确认并等待候选比较结束，不选择候选。
- **停留状态**：候选列表和 rejected/excluded 区域都已加载。
- **画面必须有**：2–3 个真实候选（若当次确有）、railway evidence、playable time、
  至少一个排除原因；不足 2 个候选时不拍，保留当次实测记录。
- **不得出现**：key、请求 URL、配额页面、调试响应、个人浏览器 chrome。

## Screenshot 3 — Plan

- **真实场景**：从 Screenshot 2 选择一个真实可行候选；若没有可行候选，改用
  Screenshot 1 已跑通的 DIRECT_PLAN 场景，不人工注入“成功”事实。
- **操作步骤**：走到 PlanVersion 安装完成，展开逐日时间轴与 evidence details。
- **停留状态**：完整计划页；未知项和其 `next_action` 处于可见区域。
- **画面必须有**：railway、local transit、attraction、evidence badges、一个 unknown
  或待复核项。
- **不得出现**：精确私人住址、订单信息、后台日志、run ID、绝对路径或凭据。

## Screenshot 4 — Verify

- **真实场景**：复用
  `docs/field-reports/verify-2026-08-04-third-party-vs-12306.md` 的铁路断言形状，改用
  截图当天仍在 12306 查询窗内、且有公开来源的行程断言。不得照抄已经过期的观测值。
- **操作步骤**：提交 claimed value，等待 live 12306 核验完成；只有当真实结果同时出现
  `conflicting` 与 `unknown` 时才拍这张目标图，否则记录当次实际结果后改日重试。
- **停留状态**：audit report 完整加载，首个 mismatch 已展开。
- **画面必须有**：claimed value、observed value、`conflicting`、`unknown/unsupported`，
  以及“unsupported ≠ false”的提示。
- **不得出现**：未公开的行程、订单号、Cookie、Authorization header、账号或乘客信息。

## 拍摄与验收

- 建议 1440×900 PNG、1× 缩放；只截产品内容区。
- 使用浏览器访客配置或裁掉浏览器 chrome；地图只显示公共枢纽和景点。
- 截图前检查 DOM、Network、URL 和终端，确认没有 key、安全密钥或请求签名。
- 导出后放大并 OCR 复核隐私，再执行仓库扫密规则；最终图片放入 `docs/screenshots/`。
