# trip-decider

一个证据优先、可审计的本地旅行决策原型。它把“发现去哪”和“确定后怎么走”
拆成两个阶段：先用真实交通与地点数据验证候选，再生成从出发到返程的行程；
查不到的事实保持为 `unknown` 或待确认，不用看似合理的数字补空白。

> 当前是开发者预览版，不是订票、订房或生产托管服务。请先阅读
> [已知问题与边界](KNOWN_ISSUES.md)。

## 能做什么

- **Discover**：根据出发地、日期、预算和偏好预筛目的地，再以 12306 往返车次和
  净可玩时长验证可达性；落选候选保留明确原因。
- **Plan**：目的地确认后，组合跨城铁路、高德地点身份、公交优先的当地路线、
  粗时间轴、已知费用和待确认项。
- **Audit**：核实外部行程中的铁路断言，区分“有据”“冲突”和“查无实据”。
- **Revise**：修改约束时创建新版本；新版本不可用时不会覆盖已有可用版本。
- **Explain**：每个证据域同时表达可靠性、新鲜度和下一步动作，ambiguous /
  unmatched 地点不会被静默合并。

产品入口同时提供本地 Web 页面和 MCP 服务。详细操作见
[使用说明](docs/usage.md)，产品边界与纵向验收用例见 [PRODUCT.md](PRODUCT.md)。

## 数据源与覆盖

| 域 | 当前来源 | 边界 |
| --- | --- | --- |
| 跨城铁路 | 12306 实时查询 | 不需要 API key；查询窗口、网络和上游服务会影响结果 |
| 地点与当地交通 | 高德 Web 服务 | 需要 Web 服务 key；地点歧义必须由用户确认 |
| 网页地图 | 高德 JS API | 另需 JS key 与安全密钥；只影响地图渲染 |
| 住宿、天气与完整费用 | 部分或暂无来源 | 缺失项保持未知，不进入“已知费用” |

仓库附带一份可替换的目的地种子目录
[`examples/destination_catalog.json`](examples/destination_catalog.json)。种子只负责
缩小实查范围，不是可行性证明；最终候选必须通过真实数据门。

目前完成端到端实测的主链路是武汉到婺源区域。其他目的地仍应视为预览覆盖，
不能据此推断全国范围的完整支持。

## Quick Start

要求：

- Python `>=3.11,<3.12`；
- Windows PowerShell（当前提供的启动脚本在 Windows 上验证）；
- 从仓库根目录执行命令。

创建环境并安装锁定依赖：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --requirement .\requirements-dev.lock
```

配置真实地点与路线采集所需的高德 Web 服务 key：

```powershell
$env:AMAP_WEB_SERVICE_KEY = "<your-amap-web-service-key>"
```

如需网页地图，再配置：

```powershell
$env:AMAP_JS_API_KEY       = "<your-amap-js-key>"
$env:AMAP_JS_SECURITY_CODE = "<your-amap-js-security-code>"
```

凭据只应通过进程环境传入。不要把真实值写进仓库、示例、日志或截图。

启动本地网页：

```powershell
.\scripts\run_product.ps1
```

浏览器会打开 <http://127.0.0.1:8765/>。服务默认只绑定 loopback；不要把这个无认证
的开发服务器直接暴露到局域网或公网。

## MCP / Claude Desktop

MCP 配置、共享 Web 进程的启动方式和环境变量示例见
[docs/usage.md §2.2](docs/usage.md)。
同一个 `runtime/sessions/` 同时只允许一个进程持有；需要并行实例时必须使用不同
的 `TRIP_DECIDER_RUNTIME_ROOT`。

## 验证

完整离线测试：

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m pytest -q
```

真实网络冒烟会调用 12306 与高德，并消耗高德配额：

```powershell
.\.venv\Scripts\python.exe scripts\smoke_live.py
```

自动化测试不要求真实 key。长期不变式登记位于
[`tests/invariant_ledger.json`](tests/invariant_ledger.json)。

## 运行数据与安全边界

- `runtime/`、`.env*`、本地凭据文件和 Python 环境均由 `.gitignore` 排除；
- 运行记录采用版本化 schema，但不承诺跨版本迁移；
- runtime store 是单进程写入模型，入口会用 owner lock 阻止同目录重复启动；
- 本项目不执行支付、预订或账号登录。

## 项目结构

- [`src/trip_decider/`](src/trip_decider/)：产品、MCP、证据与规划运行时；
- [`examples/`](examples/)：公开示例输入和可替换的候选种子；
- [`scripts/`](scripts/)：启动、冒烟与独立验证入口；
- [`tests/`](tests/)：单元、表征、产品与不变式测试；
- [`docs/contracts/`](docs/contracts/)：当前契约和工程边界；
- [`docs/reviews/`](docs/reviews/) 与 [`plans/`](plans/)：历史执行证据，不是产品入口。

## 截图

公开截图尚未加入。所需画面、建议文件名和隐私检查见
[`docs/screenshots/README.md`](docs/screenshots/README.md)。现有
`docs/field-reports/*.png` 是历史实测证据，包含具体行程数据，不应直接复用为
公开首页素材。

## License

[MIT](LICENSE)
