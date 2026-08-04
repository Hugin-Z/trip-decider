# 第三次复测：卡死是否消失 + 核实模式是否可用

前情：第二次实测（2026-08-04）好消息是 description 重写生效——宿主主动调了
`create_trip_task`，intent 一次填对，零试错。坏消息是**卡死 4 分钟**，宿主超时
放弃回退 web search。

---

## 〇、卡死的归因（已复现、已修，供复测时对照）

**不是**「同步采集堵住了请求线程」。实测下来采集本身一直在后台线程里跑，比较
进行中前台调用仍是 0.03 秒。

真正的成因是**结论被丢弃**：

1. 选完候选后动作循环停在 `web` 动作——那是只有外部才能做的
   `codex_web_research`；
2. 循环**算出**了「走不动了，要外部补证据」；
3. 但只有后台线程那一支会把这个结论落成 run 状态，`execute_trip` 的同步支
   算出同一结论后直接丢掉；
4. 于是 run 永远停在 `RUNNING`，宿主每次 `advance_trip_task` 都拿到
   `checkpoint=RUNNING`。

最反直觉的一点：**没有任何一次调用是慢的**。每次都在 10 秒内老实返回，只是
永远不前进。只盯单次耗时的守卫会对这种形状全绿放行——所以 I13 同时守
「单次有上界」和「循环必须能到达检查点」两条。

实测对照（同一条链路，真 STDIO 子进程）：

| | 修复前 | 修复后 |
|---|---|---|
| 选完候选后的 `advance` | 每次 10s，`RUNNING`，连续 24 次仍未终止（>240s） | **一次，0.08s**，`NEED_USER_INPUT_OR_EVIDENCE` |
| 最慢的一次调用 | 10.09s | 10.00s（`wait_seconds=10` 主动等待，符合预期） |

---

## 一、取证命令清单（如果复测又卡住，先跑这些）

**先说一件事**：本机 `%APPDATA%\Claude` 下**没有 logs 目录**（2026-08-04 查过），
所以「去看日志」这一步目前是空的。下面第 1 条先解决「有没有日志」。

```powershell
# 1. 日志到底在不在
Get-ChildItem "$env:APPDATA\Claude" -Recurse -Filter "*.log" -ErrorAction SilentlyContinue |
  Select-Object FullName, Length, LastWriteTime
# 空 = 这个版本没开文件日志。Claude Desktop 里
#   Settings → Developer → 打开 MCP 日志，然后重启，再复现一次

# 2. 服务器进程还活着吗（"crashed, or not running" 的直接判据）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*trip_decider.mcp_server*" } |
  Select-Object ProcessId, CreationDate, CommandLine | Format-List
# 没有输出 = 服务器没起来或已崩溃，去看第 1 条的日志
# 有输出   = 服务器活着，是「在等什么」而不是「挂了」，走第 3 条

# 3. 卡住的那个 run 停在哪一步（最有用的一条）
$run = Get-ChildItem "<repo>\runtime\sessions" -Directory |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1
"run: $($run.Name)"
$r = Get-Content "$($run.FullName)\run.json" -Raw -Encoding utf8 | ConvertFrom-Json
"status={0}  error_code={1}  action_loop_status={2}" -f `
  $r.status, $r.error_code, $r.result.action_loop_status
(Get-Content "$($run.FullName)\action-loop.json" -Raw -Encoding utf8 |
  ConvertFrom-Json).action_status
# status=RUNNING 且某个动作长期 waiting = 本轮修的那个病复发了，把这段贴回来

# 4. 事件流最后几条（它会说清停在哪个动作）
Get-Content "$($run.FullName)\events.jsonl" -Tail 6 -Encoding utf8

# 5. 服务器能不能独立跑通（把宿主摘出去）
cd "<repo>"
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m trip_decider.mcp_server --runtime-root .\runtime\sessions
# 光标停住不报错 = 正常（它在等 STDIO 输入），Ctrl+C 退出
# 立刻报错退出 = 贴报错回来
```

---

## 二、复测步骤

### 准备

1. **重启 Claude Desktop**（工具描述在连接时读一次，不重启还是旧的）。
2. **开新对话**（旧对话里宿主已经学会了旧调用方式，会污染观察）。
3. 可选：按取证清单第 1 条把 MCP 日志打开，这样万一又卡住就有据可查。

### 场景 A：同款输入，看还卡不卡（本轮主目标）

> 我想 8 月 11 号从武汉出发去婺源上饶那边玩到 8 月 14 号，两个人，预算 6000，
> 节奏慢一点，想看自然和古村。帮我安排一下。

**通过标准**

| # | 看什么 | 通过 |
|---|---|---|
| A1 | 有没有出现「4 分钟无响应」 | **没有**。这是本轮唯一的硬指标 |
| A2 | 选完候选后的那次 `advance_trip_task` | 应当很快返回一个**具体检查点**，不再是一串 `RUNNING` |
| A3 | 到达的检查点是否说清了下一步 | 返回体的 `next_call` 应点名 `submit_trip_evidence` 与缺的域 |
| A4 | 宿主是否照着 `next_call` 走 | 它应当去补 web 证据，而不是重复调 `advance` |

**注意**：跑完整条链路仍然需要几十秒（实查车次是真的在查），期间可能要调两三次
`advance_trip_task`——**那是正常的**，描述里也写了。要区分「等了几十秒但在前进」
与「永远 RUNNING」：看每次返回的 `checkpoint` 有没有变化。

### 场景 B：核实模式（本轮新工具）

先让它自己排一份（不提工具名）：

> 帮我查一下 8 月 11 号武汉到上饶有哪些高铁，选一趟中午出发的。

它多半会 web search 给一个车次。然后：

> 这个车次和票价靠谱吗？帮我核实一下。

**通过标准**

| # | 看什么 | 通过 |
|---|---|---|
| B1 | 它是否调用了 `verify_itinerary` | 是 |
| B2 | assertions 是否一次填对 | 四个必填项齐全，时间是不带时区的本地 ISO |
| B3 | 结论是否三档 | sourced / conflicting / unknown，**不是**「对/错」两档 |
| B4 | unknown 的措辞 | 应说「查无实据」并给建议动作，**不能**说成「这趟车不存在」 |
| B5 | 总评格式 | 「N 条断言：a 条有据、b 条冲突、c 条查无实据，建议出发前确认第 x、y 条」 |

**已知的真实结果**（2026-08-04 实查，可直接对照）：8 月 11 日武汉→上饶方向
**没有** G868，有 G867；G868 是**回程**车次（上饶→武汉）。G867/G868 的二等座
实查票价是 **¥209.5 / ¥219.5**（取决于武汉侧是哪个站），比上次宿主引用的
Autohome「149–176 元」区间**高 34–70 元**。

也就是说：上次那份 web search 行程，车次方向错了、时刻错了、票价低估了。
如果 B1–B5 都通过，核实模式应该能把这些一条条指出来。

### 场景 C：当地交通（上轮遗留，顺带复看）

拿到行程后问「第二天从住的地方到景点这一段具体怎么走」，应给出线路名与上下车站；
驾车兜底段没有线路可报，不算失败。

---

## 记录模板

```
日期：              Claude Desktop 版本：
场景 A
  A1 是否出现 4 分钟无响应：
  A2 选完候选后 advance 的返回（checkpoint 序列）：
  A3 next_call 内容：
  A4 宿主下一步做了什么：
场景 B
  B1 是否调用 verify_itinerary：
  B2 参数是否一次填对（否则记它试了几次、错在哪）：
  B3/B4 三档措辞是否准确（unknown 有没有被说成「假」）：
  B5 总评原文：
场景 C
  答复原文：
主观印象：哪一步最别扭（按原话记，这条最有价值）
```

---

## 本轮**没有**改的（撞到不算回归）

- **一次完整规划仍需几十秒**：实查车次的固有耗时。
- **web 证据要外部补**：`codex_web_research` 本来就设计成由宿主完成。现在
  它会**明确停在检查点并说清要什么**，而不是假装还在跑。
- **核实模式只核铁路域**：住宿、门票、当地交通未核验，返回体里明写了。
- **换乘各走多远 / 发车间隔 / 实时到站**：见
  `docs/contracts/local-transit-coverage.md` §2。
- **住宿价格是 unknown**：`hotel_price` 生产者未落地（I4 仍红，登记在案）。
