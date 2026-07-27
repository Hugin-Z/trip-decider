# Work Unit 1 Remediation Plan

Plan version: `v0.1`

Status: `PENDING_HUGIN_APPROVAL`

Work unit: `WU1R`

Predecessor:

```text
WU1 final HEAD: 80395c24612056eff6ff07f81eb3ac5df8c1660b
WU1 Review: docs/reviews/work-unit-1-review.md
WU1 Review status: INCOMPLETE
```

本 Plan 只规划 WU1 Review 已确认的两个缺口。未收到语义明确的
“批准执行 Work Unit 1 Remediation”前，不进入 Execute，不修改脚本、
测试或实现，不提交本 Plan。

## 1. 任务目标与边界

### 1.1 唯一目标

WU1R 只关闭以下两个已记录缺口：

1. **R1：完整单一验证入口。** 让
   `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu1.ps1`
   在一次执行中完成运行环境、lock、`pip check`、Schema registry、
   完整 unittest discovery、六个正式 fixture、历史 36 路径 scope、
   WU1R 增量 scope、fallback/guess/infer/warning、secret 和八个冻结
   输入 hash 检查；任何失败均确定性非零退出。
2. **R2：完整错误输出与退出码。** 复用已有七字段
   `ValidationProblem`，将机器问题作为 JSON Lines 写入 stderr，并严格
   区分退出码 `0/2/3/4/5`。

WU1R 完成后的历史语义只能是：

```text
WU1 Review at 80395c2: INCOMPLETE
WU1R later closes the two recorded gaps
```

不得改写为“原 WU1 当时已经完成”。

### 1.2 明确不做

WU1R 不负责：

- 修改任何工件 Schema 或工件产品契约；
- 修改现有 schema/fixture validator；
- 增加或修改旅游业务判断；
- 自然语言解析、证据业务定级、proof 正确性或可行性判断；
- 高德、Web、POI、路线、基地、分天、重排、HTML 或江西行程；
- 新增依赖、重锁依赖或修改 Python/PowerShell/Git 用户配置；
- 修订 WU1 Plan、WU1 Review 或 WU1 C0—C8、C3.1、C3.2 历史；
- 创建 WU2 Plan、执行 WU2、创建远端、push 或 PR。

## 2. 输入、实测基线与审计结论

### 2.1 Git 与工作目录

2026-07-26 Plan 阶段实测：

```text
工作目录: <repo>
分支: main
HEAD: 80395c24612056eff6ff07f81eb3ac5df8c1660b
git status --short: 0 条
remote: 0 个
stash: 0 条
tracked files: 46
WU1 起点..终点路径数: 36
WU1 commits: 11
```

WU1 的 11 个 commit 保持线性且不得 amend、reset、rebase、squash、
删除或补写：

```text
c1c1e01 C0
a3e1c4d C1
9a340d6 C2
bb626c7 C3
c8ad499 C3.1
5bb9fe5 C3.2
3762af8 C4
d8c1d1f C5
e426847 C6
5ed0c32 C7
80395c2 C8
```

### 2.2 八个被审计文件

以下 SHA256、行数和字节数均来自本地命令，不是估算：

| 文件 | SHA256 | 行 | 字节 |
|---|---|---:|---:|
| `scripts/verify_wu1.ps1` | `A8BC52F8A648FF40029BF369768F36C04200832DD8DFC429154F8CBA028471FE` | 177 | 5521 |
| `src/trip_decider/schema_validation.py` | `2061084E8AC27DF4C08F63DC264A2612685980D966AA5291A46660BE3F1CC017` | 1179 | 50666 |
| `src/trip_decider/fixture_validation.py` | `6C720C5F4D72356F2909854E6C1B605B891BC40787A4D87739CCA69C2590EBBF` | 514 | 16149 |
| `tests/test_schema_validation.py` | `A4075DC19E2D923E25862D589DA4DA83AEE39B2D2355BF9B553683C7E24C0DAA` | 1259 | 50700 |
| `tests/test_fixture_validation.py` | `E748784A658FFD098A97269F7C3864A9CFB6612839207640A0CA0B900908BC7B` | 471 | 17257 |
| `requirements.lock` | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` | 21 | 402 |
| `pyproject.toml` | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` | 16 | 365 |
| `docs/reviews/work-unit-1-review.md` | `C3E7CCF3D0F1A0181AD36E0435FCC481E56E3B3DAF42A921DB4E2E7EC72A659E` | 615 | 26427 |

附加冻结输入：

```text
plans/work-unit-1-contracts-fixtures.md
SHA256: B1C2517EE7B9579EFA85C5998FA5E29170589A650CBB051F1F5C00400EB39212
lines: 1250
bytes: 85186
```

### 2.3 运行环境审计

项目 `.venv` 的实际运行信息：

```text
Python: .venv\Scripts\python.exe
Python major/minor target: 3.11
sys.prefix: <project>\.venv
site-packages: <project>\.venv\Lib\site-packages
requirements.lock entries: 21
installed distributions: 23
lock 外允许的 bootstrap distributions: pip, setuptools
```

lock 中 21 个包与当前 `.venv` 的 21 个非 bootstrap 包可作精确
name/version 集合比较。名称比较采用 PEP 503 canonicalization；版本必须
逐字符一致。`pip` 和 `setuptools` 只作为明确列名的环境 bootstrap
排除项，不是任意 allowlist，也不能掩盖其他额外包。

### 2.4 Handbook 对账

固定路径：

```text
<handbook>
```

Plan 阶段完成 `fetch origin --prune` 后：

```text
local HEAD: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree: clean
```

从 `origin/main` 实际重新读取：

```text
STATE.md
INDEX.md
SUMMARY.md
tools/context-injection.md
principles/r10-honesty.rule.md
principles/per-protocol.rule.md
principles/scope-control.rule.md
principles/fixture-first.rule.md
```

对 WU1R 的直接影响：

- R10：第三方输出、输入值和 secret 不得进入机器错误；数字必须由命令
  产生；脚本 green 不能代替入口行为的独立故障注入。
- PER：本文件获批前不执行；Execute 完成后只进入一次 WU1R Review。
- Scope：五个路径在本 Plan 冻结；任何第六个路径需求立即停止。
- Fixture-first：先提交有效 red，再修改脚本/实现；合成输入仅用于
  确定性入口与错误分类，expected 由本 Plan 人工写定。

### 2.5 七个原冻结输入与 WU1 Plan hash

最终入口必须逐一校验以下八个 hash：

| 路径 | 冻结 SHA256 |
|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `plans/work-unit-0-bootstrap-d0.md` | `4C7FE14CD5D2CE0CC8E8D624D93C24338EAF61A9DBC0778D101AB3565602DE3B` |
| `docs/architecture.md` | `CA5B6F7D345E11623C94C13CDD73C0E774282AFD88F9E2E036035ED2396BB6F4` |
| `docs/artifact-contracts.md` | `695C0AC6738B71852DC60ADAFD2A98B974C5EC65BB744D19B0E22EC3550497BF` |
| `docs/prior-art.md` | `C1195E816DB5F21FE83B4208B6258BA9F138C9AB9404373A132CE75C457893E7` |
| `docs/handbook-context.md` | `1933DBA1B3697A394EDCC0238B60A032A18EA10B920F8C4358169490492115EB` |
| `docs/reviews/work-unit-0-review.md` | `D93373ECC7398DEE95FFCC04E0143DE80612B4FE948FD36282FA98F793477128` |
| `plans/work-unit-1-contracts-fixtures.md` | `B1C2517EE7B9579EFA85C5998FA5E29170589A650CBB051F1F5C00400EB39212` |

WU1R Review 另以独立命令证明：

- `docs/reviews/work-unit-1-review.md` 仍为
  `C3E7CCF3D0F1A0181AD36E0435FCC481E56E3B3DAF42A921DB4E2E7EC72A659E`；
- 本 WU1R Plan 的获批 SHA256 自 R0 后不变。

这两项是历史/审批证据，不加入 R1 所定义的八个入口 hash，以免把
Review 产物混成原冻结产品输入。

### 2.6 已确认缺口

只读审计确认：

- 当前脚本只检查 `.venv\Scripts\python.exe` 路径存在，没有断言运行时
  `sys.executable`、`sys.prefix` 和全部 site-packages 的真实归属；
- 当前脚本没有读取 `requirements.lock`，没有精确环境比较，没有
  `pip check`；
- Schema registry、82 个现有 unittest 和六个 fixture 已接入；
- 当前脚本没有 36 路径、fallback、secret 或冻结 hash 检查；
- 当前脚本没有可达的 artifact 退出码 2；
- fixture 问题只输出四字段 JSON 到 stdout；
- 当前脚本没有实现七字段 stderr JSONL；
- 两个 validator 已经共同使用七字段 `ValidationProblem`，不得重复
  建立第二套错误对象；
- 当前正式基线为 11 个 Schema、82 个 unittest、6 个 fixture 目录、
  38 个 documents、6 个 dirty cases。

## 3. 冲突与裁定

### 3.1 新测试数量与“成功路径仍为 82 tests”

需求同时要求：

1. 新增 WU1R 测试先取得 red；
2. 最终入口运行完整 unittest discovery；
3. 成功摘要仍精确为 82 tests。

若新增文件命名为 `tests/test_verify_wu1_entry.py`，标准
`unittest discover -s tests` 会自动发现它，成功计数必然大于 82，
与第 3 条直接冲突。

本 Plan 采用以下显式裁定，等待 Hugin 通过批准本 Plan 一并确认：

- 新增 `tests/wu1r_verify_entry_cases.py`，文件名故意不匹配标准
  `test*.py` discovery pattern；
- WU1R red/green 命令显式点名该模块，与原 82 个测试一起运行；
- 最终单入口继续执行标准 `unittest discover -s tests`，因此运行原
  WU1 正式 discovery 集并保持 82；
- WU1R Review 同时报告“显式 WU1R contract suite 总数”和“入口内
  discovery 总数”，不得将二者混写。

这不是遗漏测试：WU1R contract suite 是本修复工作单元的执行期
验收 harness；原 WU1 的标准 discovery 集保持冻结。若 Hugin 不接受
该解释，则必须在 Execute 前修订 Plan，不能执行时改名、改 pattern
或擅自接受大于 82 的计数。

### 3.2 原 WU1 36 路径与 WU1R 新路径

“36 路径 scope 检查”指原 WU1 起点
`21d8508a8f96472ecc4d7f798cdd6af3d7f54f68` 到原 WU1 终点
`80395c24612056eff6ff07f81eb3ac5df8c1660b` 的固定历史集合，不能因
WU1R 增加路径而改写成 41。

最终入口分两层检查：

1. 原 WU1 起点..终点的路径集合必须与 §5.3 的 36 项精确相等；
2. `80395c2..HEAD` 加当前 tracked/untracked 工作树变化必须是 §5.1
   五路径白名单的子集；任何第六个路径失败。

因此既能证明原 WU1 scope 未被重写，也能允许 Plan、red、green 和
Review 在各 commit 阶段逐步出现。不得只检查 `git status`，也不得
把未知 untracked 文件静默排除。

### 3.3 退出码分类边界

按具体问题类型分类，不按“发生在 fixture 阶段”粗分：

- 输入路径/读取/UTF-8/JSON/YAML 解析问题：`4`；
- validator internal、registry 必要项、format checker、运行环境、
  lock、`pip check`、scope/scan、unittest harness 问题：`5`；
- artifact/Schema metadata/version/payload hash/reference/closure 问题：
  `2`；
- fixture manifest、fixture bytes/hash、path、mutation、expected-error
  问题：`3`。

因此嵌在 fixture 中的 `UNRESOLVED_REFERENCE` 仍为 `2`，不能因为
调用来自 fixture validator 而错误映射成 `3`。若同一阶段返回多类
问题，退出码优先级固定为：

```text
internal(5) > input(4) > artifact(2) > fixture(3)
```

所有问题仍按 `artifact_path`、`json_pointer`、`error_code` 排序。
未知 `error_code` 不猜分类、不当作通过，而转换为固定的入口内部问题
并退出 `5`。

## 4. 实现设计

### 4.1 单一职责分层

新增 `src/trip_decider/verification_entry.py` 是必要的第 4 个源文件，
原因如下：

- Windows PowerShell 5.1 不适合可靠实现 Python distribution metadata、
  unittest discovery、AST 名称扫描和既有 `ValidationProblem` 复用；
- 退出码分类、JSONL 排序和 stdout/stderr 分流需要标准库单元测试和
  可注入的确定性故障边界；
- 如果全部堆在 `.ps1` 多行字符串里，只能靠整段进程测试，难以在不
  修改受保护输入的情况下证明 exit 2/3/4/5；
- 该模块只编排现有 validator 和标准库检查，不引入第二套工件验证器。

职责：

```text
scripts/verify_wu1.ps1
  仅定位项目、验证项目 .venv 启动路径、创建/删除系统临时 Python 文件、
  使用项目 Python 调用固定 verification_entry.main，并原样传播退出码

src/trip_decider/verification_entry.py
  运行全部 R1 检查、复用 ValidationProblem、分类退出码、输出 JSONL、
  生成固定人类摘要

src/trip_decider/schema_validation.py
src/trip_decider/fixture_validation.py
  保持字节不变，继续作为结构验证与七字段问题的唯一来源
```

模块只使用 Python 标准库和现有项目依赖，不修改
`src/trip_decider/__init__.py`。测试直接从模块路径导入。

### 4.2 可测试入口

R1 先冻结最小可导入接口：

```text
run_verification(repo_root, *, dependencies, stdout, stderr) -> int
main() -> int
```

`dependencies` 是显式 Python 调用边界，只供测试传入确定性
subprocess、Git、distribution 和文件表面；正常 `main()` 始终构造
真实实现。CLI 和 PowerShell 脚本不提供故障开关、skip、lenient、
环境变量 bypass 或自动修复。

测试可在内存或系统临时目录构造确定性失败，不修改 `PLAN.md`、现有
测试、Schema、fixture、Git index 或用户配置。

### 4.3 PowerShell 传输约束

保留已经验证过的传输方式：

- 临时文件位于系统临时目录；
- 文件名含随机 GUID；
- UTF-8 无 BOM；
- 文件内容只导入固定 `verification_entry.main`；
- 使用项目 `.venv\Scripts\python.exe`；
- `try/finally` 删除；
- 不在仓库内产生临时 `.py`；
- 不使用 `python -c`；
- 不使用 `Invoke-Expression`；
- 不启动嵌套 `powershell -Command`。

为测试失败路径清理，脚本把“写入—执行—finally 删除”封装为内部
PowerShell function。脚本被正常 `-File` 调用时执行 main；测试以
系统临时 `.ps1` harness dot-source 脚本并调用该内部 transport
function。harness 自身也在 `finally` 删除。正常入口没有额外参数或
绕过方式。

如果 `.venv` Python 尚不可调用，PowerShell bootstrap 不能导入 Python
模型；它只允许输出一条字段完全相同、内容固定且不含本机值的七字段
JSONL 到 stderr，并退出 `5`。这不是第二套 validator 错误模型，而是
Python 入口不可启动时唯一的 fail-closed bootstrap 表达。

### 4.4 环境与 lock

入口必须：

1. 对项目根、`.venv` 和运行路径使用解析后的绝对路径比较；
2. 断言 `sys.executable` 位于项目 `.venv` 且等于批准的项目 Python；
3. 断言 `sys.prefix` 等于项目 `.venv`；
4. 断言 `site.getsitepackages()` 及参与比较的 distribution location
   全部位于项目 `.venv`；
5. 严格 UTF-8 读取 `requirements.lock`，拒绝 BOM、空/畸形行、重复
   canonical name、非 `name==version`、URL、index、路径或凭据形式；
6. 精确比较 lock 与运行时包集合，只排除 `pip`、`setuptools`；
7. 使用 `[sys.executable, "-m", "pip", "check"]`，不用 shell，捕获
   stdout/stderr；非零只输出项目固定错误，不复制第三方内容。

任何 mismatch 都不得自动安装、换版本、改 lock 或回退全局 Python。

### 4.5 Schema、unittest 与 fixture

- Schema discovery 必须精确得到 11 个 `*.schema.json`；
- 调用现有 `validate_schema_registry`；Draft 2020-12、唯一 `$id`、
  本地 refs、九个 artifact registry、fixture registry 和 format
  self-check 继续由现有实现负责；
- 使用标准库 loader 执行 `unittest discover -s tests`，将 runner
  输出捕获到内存；失败时不复制 assertion/exception 原文，只发稳定
  七字段内部问题；
- 入口成功必须精确得到 82 tests；
- 调用现有 `validate_fixture_directory`，并逐个读取实际 manifest 以
  核对 closed closure、实际 `root_artifact_id`、目录数和汇总；
- 成功必须精确得到 6 个 fixture、38 documents、6 dirty cases；
- fixture 中的 artifact 问题按 §3.3 分类，不能全部变成 exit 3。

### 4.6 Scope 检查

原 WU1 固定 36 路径在 §5.3 完整列出。实现使用参数数组调用 Git，
不得 shell 拼接：

```text
git diff --name-only <WU1-start>..<WU1-final>
git diff --name-only 80395c2..HEAD
git status --porcelain=v1 --untracked-files=all
```

Git 不可用、输出无法解析或 baseline commit 不存在属于入口内部错误
exit 5，不得跳过。原 36 集必须精确相等；WU1R 累计和工作树只允许
§5.1 五路径。ignored `.venv`、`__pycache__` 和系统临时文件不进入
tracked/untracked scope 集。

### 4.7 fallback、warning 与 secret 扫描

扫描规则必须确定性且不因扫描器自身文本产生假阳性：

- 对 `src/**/*.py` 和 `tests/**/*.py` 用 Python AST 检查函数、方法和
  调用名的 `infer_`、`guess_`、`default_when_missing` 族；
- 对 Python/PowerShell 生产路径检查 `silent_fallback`、lenient/
  warning-as-pass、吞异常后成功、全局 Python fallback；
- 对 `scripts/verify_wu1.ps1` 额外检查 `python -c`、
  `Invoke-Expression`、嵌套 `powershell -Command`；
- secret 扫描覆盖所有 `git ls-files` 返回的 tracked 文件，检测常见
  key/token/private-key/带值 credential 赋值；空值和明确 placeholder
  不能被当成真实 secret；
- 测试通过系统临时输入表面注入命中；不得把含测试词汇的整份测试
  文件加入 allowlist，也不得用 blanket exclude 隐藏生产路径；
- 扫描器规则 token 在实现中以结构化 AST 或分段常量表达，不能用
  “发现自己后忽略当前行”的 silent self-exemption。

任何命中输出相对路径、安全类型和固定 message，不输出命中的实际值
或上下文文本。

### 4.8 输出契约

机器问题每行只写 stderr，严格包含且只包含：

```json
{
  "error_code": "",
  "artifact_path": "",
  "json_pointer": "",
  "schema_rule": "",
  "expected": "",
  "actual_type": "",
  "message": ""
}
```

约束：

- 七字段全部存在，无关值为空字符串；
- `artifact_path` 只用项目相对路径或固定逻辑名；
- `actual_type` 只用安全类型名，不输出值；
- `message` 只用项目固定模板；
- 不复制 Git、pip、unittest、jsonschema、PyYAML、I/O 或 PowerShell
  第三方异常原文；
- 多问题按 `artifact_path/json_pointer/error_code` 排序；
- stdout 只输出固定的人类 PASS/FAIL 摘要，不能混入机器 JSON；
- 成功摘要必须由实际计数生成并至少包含
  `tests=82 fixtures=6 documents=38 dirty_cases=6`；
- 失败摘要只能包含 stage、exit code 和问题数量等安全元数据。

稳定退出码：

| code | 含义 |
|---:|---|
| 0 | 全部检查通过 |
| 2 | artifact/Schema/version/hash/reference/closure 结构违规 |
| 3 | fixture manifest/bytes/path/mutation/expected-error 违规 |
| 4 | 输入路径、读取、UTF-8、JSON/YAML 解析违规 |
| 5 | internal/registry/format/runtime/lock/pip/scope/scan/test harness 违规 |

## 5. Scope 与路径白名单

### 5.1 WU1R 精确白名单：5 个路径

| 路径 | 动作 | 职责 |
|---|---|---|
| `plans/work-unit-1-remediation.md` | 新增，R0 后冻结 | 获批 Plan |
| `src/trip_decider/verification_entry.py` | 新增 | 单入口 Python 编排、分类和输出 |
| `tests/wu1r_verify_entry_cases.py` | 新增 | 非默认 discovery 的 WU1R red/green contract suite |
| `scripts/verify_wu1.ps1` | 修改 | `.venv` bootstrap 与系统临时文件 transport |
| `docs/reviews/work-unit-1-remediation-review.md` | 新增 | WU1R Review |

预计 WU1R tracked path 数固定为 5。Execute 中如需要第 6 个路径，立即
停止，不以“辅助文件”“临时证据”或“顺便补测试”名义新增。

### 5.2 明确保护

不得修改：

- `plans/work-unit-1-contracts-fixtures.md`；
- `docs/reviews/work-unit-1-review.md`；
- WU1 C0—C8、C3.1、C3.2 的任何 commit；
- `src/trip_decider/schema_validation.py`；
- `src/trip_decider/fixture_validation.py`；
- `src/trip_decider/__init__.py`；
- `tests/test_schema_validation.py`；
- `tests/test_fixture_validation.py`；
- `tests/__init__.py`；
- `schemas/` 全部内容；
- `fixtures/` 全部内容；
- `requirements.lock`、`pyproject.toml`；
- 七个原冻结输入、WU0 全部产物、`.gitignore`、`.env.example`；
- handbook 全部内容；
- 用户系统配置、其他仓库和任何 secret。

### 5.3 原 WU1 精确 36 路径

入口必须核对以下完整集合，不得以数量相等代替集合相等：

```text
docs/reviews/work-unit-1-review.md
fixtures/README.md
fixtures/fixture_01_feasible/README.md
fixtures/fixture_01_feasible/case.json
fixtures/fixture_02_direct_conflict/README.md
fixtures/fixture_02_direct_conflict/case.json
fixtures/fixture_03_uncertain_dependency/README.md
fixtures/fixture_03_uncertain_dependency/case.json
fixtures/fixture_04_replan_stability/README.md
fixtures/fixture_04_replan_stability/case.json
fixtures/fixture_05_evidence_state_mapping/README.md
fixtures/fixture_05_evidence_state_mapping/case.json
fixtures/fixture_06_no_plan_found_not_infeasible/README.md
fixtures/fixture_06_no_plan_found_not_infeasible/case.json
plans/work-unit-1-contracts-fixtures.md
pyproject.toml
requirements.lock
schemas/candidates.schema.json
schemas/common.schema.json
schemas/constraint-parse.schema.json
schemas/constraints.schema.json
schemas/evidence.schema.json
schemas/fixture-case.schema.json
schemas/plan-diff.schema.json
schemas/plan.schema.json
schemas/previous-plan.schema.json
schemas/request.schema.json
schemas/trip-card.contract.md
schemas/violations.schema.json
scripts/verify_wu1.ps1
src/trip_decider/__init__.py
src/trip_decider/fixture_validation.py
src/trip_decider/schema_validation.py
tests/__init__.py
tests/test_fixture_validation.py
tests/test_schema_validation.py
```

## 6. Fixture-first 与 Red → Green

### 6.1 测试类型与来源

WU1R 是确定性验证入口，不涉及语义、检索或真实旅行 anchor。允许使用
人工按本 Plan 写定的合成输入：

- clean：明确合规的依赖、hash、scope、问题对象和进程结果；
- dirty：一次只改变一个环境事实、路径、hash、问题类型或退出状态；
- expected：人工固定，不调用被测函数生成；
- 临时文件只写系统临时目录并在 `finally` 删除；
- 测试模块 docstring 必须声明来源、覆盖范围和不覆盖范围。

不覆盖旅游语义、证据真实性、可行性、路线或真实 API。

### 6.2 预注册 18 个 WU1R case

| ID | 独立行为 | 预期 |
|---|---|---|
| VE-01 | `sys.executable` 不在项目 `.venv` | 七字段 stderr，exit 5 |
| VE-02 | `sys.prefix` 或 site-packages 越出项目 `.venv` | 七字段 stderr，exit 5 |
| VE-03 | lock 与运行时 package set/version 不一致 | 七字段 stderr，exit 5 |
| VE-04 | `pip check` 非零 | 捕获第三方输出，固定问题，exit 5 |
| VE-05 | 任一冻结 hash 改变 | 不输出 hash 实值，exit 2 |
| VE-06 | 原 36 集不等或 WU1R 出现额外 tracked path | 相对路径问题，exit 5 |
| VE-07 | fallback/guess/infer/warning-as-pass 命中 | 不输出源码值，exit 5 |
| VE-08 | secret pattern 命中 | 不输出 secret/context，exit 5 |
| VE-09 | artifact/Schema/reference 问题 | 七字段 stderr，exit 2 |
| VE-10 | fixture manifest/mutation/expected 问题 | 七字段 stderr，exit 3 |
| VE-11 | 路径/读取/UTF-8/JSON/YAML 问题 | 七字段 stderr，exit 4 |
| VE-12 | registry/internal/format 问题 | 七字段 stderr，exit 5 |
| VE-13 | fixture 调用返回 artifact 问题 | 保持 exit 2，不误映射 3 |
| VE-14 | 多问题排序及混合类别优先级 | 确定性 JSONL 与固定优先级 |
| VE-15 | stdout/stderr 分离及字段精确集合 | stdout 无机器 JSON；stderr 每行恰七字段 |
| VE-16 | transport 成功 | 系统临时 Python 文件 residue 0 |
| VE-17 | transport 中 Python 非零 | `finally` 后 residue 0，原退出码传播 |
| VE-18 | 真实成功入口 | exit 0；82 tests、6 fixture、38 documents、6 dirty |

VE-04、VE-07、VE-08 和异常类 case 不得断言第三方原文；还要断言已知
敏感/输入 marker 不出现在 stdout、stderr 或 `message`。

### 6.3 R2 red 命令

R2 只新增测试，运行：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1r_verify_entry_cases -v
```

预注册 discovery 数：

```text
existing WU1 tests: 82
new WU1R tests: 18
explicit command total: 100
```

有效 red 门：

- 实际发现 100 个 tests；
- 原 82 个全部 green；
- 新增 case 中缺失的入口行为因 R1 的显式 `NotImplementedError` 或
  具体断言缺口失败，使命令非零；
- import、测试文件、PowerShell、依赖、语法和输入构造错误均为 0；
- 已存在的 transport 行为允许个别新增 case 已 green，但不能导致整个
  R2 命令误 green；
- 完整命令、exit code、每个 red test ID 和分类写入 Review。

若实际不是 100、原 82 回归、或 red 只能靠非批准原因制造，立即停止。

### 6.4 R3 green 命令

R3 使用逐字符相同命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1r_verify_entry_cases -v
```

必须实际达到：

```text
tests: 100
passed: 100
failures: 0
errors: 0
```

随后运行完整入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu1.ps1
```

必须达到：

```text
exit code: 0
unittest discovery: 82 passed
fixture directories: 6
documents: 38
dirty cases: 6
temporary Python residue: 0
```

R4 在 Review 文件最终成字节后再次逐字符运行两条命令。任何失败不得
在 R4 修改实现、测试或脚本。

## 7. 单入口 §10.2 检查矩阵

| # | 单入口内检查 | 实现位置 | 成功证据 | 失败 code |
|---:|---|---|---|---:|
| 1 | 项目 `.venv`，无全局 fallback | PS bootstrap + Python runtime | executable 路径 | 5 |
| 2 | executable/prefix/site-packages 真实归属 | Python entry | 三类路径均在 `.venv` | 5 |
| 3 | lock 与运行包精确匹配 | Python entry | 21 对 21，差异 0 | 5 |
| 4 | `pip check` | Python entry subprocess | return code 0 | 5 |
| 5 | Schema metadata/registry/format | 现有 validator，经 entry 调用 | 11 schemas、registry green | 2/4/5 |
| 6 | 完整 unittest discovery | Python entry | 82/82 | 5 |
| 7 | 六个正式 fixture | 现有 validator，经 entry 调用 | 6/38/6、closed/root | 2/3/4/5 |
| 8 | 原 36 + WU1R 五路径 scope | Python entry + Git | 精确集合/子集 | 5 |
| 9 | fallback/guess/infer/warning 扫描 | Python entry | 命中 0 | 5 |
| 10 | secret pattern 扫描 | Python entry | 命中 0 | 5 |
| 11 | 七冻结输入 + WU1 Plan hash | Python entry | 8/8 exact | 2/4 |
| 12 | 任一失败确定性非零 | dispatcher | 0/2/3/4/5 矩阵 | 2/3/4/5 |

“成功证据”数字必须由入口实际结果生成；Review 不得从本 Plan 抄数冒充
执行证据。

## 8. Exit 2/3/4/5 测试矩阵

| exit | 注入输入 | 必须断言 | 对应 case |
|---:|---|---|---|
| 2 | frozen hash mismatch | 不打印 expected/actual hash 值 | VE-05 |
| 2 | artifact/reference problem | 七字段、stderr、原 code | VE-09 |
| 2 | fixture 内 artifact problem | 不误映射为 3 | VE-13 |
| 3 | fixture manifest/mutation/expected | 七字段、stderr | VE-10 |
| 4 | read/UTF-8/JSON/YAML | 七字段、无第三方原文 | VE-11 |
| 5 | runtime/lock/pip/scope/scan | 固定项目 message | VE-01—VE-08 |
| 5 | internal/registry/format | 不复制 exception | VE-12 |
| mixed | 多类问题 | `5 > 4 > 2 > 3`，JSONL 仍按字段排序 | VE-14 |
| 0 | 全部真实检查通过 | stderr 空；人类 stdout 摘要 | VE-18 |

## 9. Commit 序列

获批后从 `80395c24612056eff6ff07f81eb3ac5df8c1660b` 在 `main` 上线性执行
五个 commit。不得 squash、amend 或改写原 WU1。

### R0 — `docs: record approved WU1 remediation plan`

- 文件：仅 `plans/work-unit-1-remediation.md`
- 职责：提交获批字节和 SHA256；状态文字保持获批原文，不回写
  `APPROVED`
- 前置：HEAD、工作树、原 WU1 Review hash、八个冻结 hash 与获批 Plan
  hash 全部匹配
- 验证：`git diff --check`、Plan SHA256/行数/字节数、单文件 diff、
  `git show --stat`
- 完成：R0 后 Plan 不再修改

### R1 — `chore: add importable WU1 remediation verification interface`

- 文件：仅 `src/trip_decider/verification_entry.py`
- 职责：添加标准库模块、数据边界和可导入的
  `run_verification/main` 接口；待实现行为显式
  `NotImplementedError`，不宣称入口已完成
- 前置：R0；无新依赖
- 验证：
  `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  保持 82 green，并用项目 Python 从 stdin 导入两个接口
- 完成：接口存在；没有脚本行为修改；现有 tests 不回归

### R2 — `test: add failing full-entry contract cases`

- 文件：仅 `tests/wu1r_verify_entry_cases.py`
- 职责：加入 §6.2 的 18 个确定性 clean/dirty case
- 前置：R1 接口可导入；PowerShell 和项目 `.venv` 可用
- 验证：运行 §6.3 唯一 red 命令；实际 100 tests；原 82 green；命令因
  新入口缺失行为非零
- 完成：记录有效 red；测试 expected 非被测函数生成

### R3 — `fix: complete WU1 verification entry contract`

- 文件：
  - `src/trip_decider/verification_entry.py`
  - `scripts/verify_wu1.ps1`
- 职责：实现 R1/R2，不修改 validator、Schema 或已有测试
- 前置：R2 有效 red
- 验证：
  1. 用逐字符相同命令得到 100/100 green；
  2. 运行完整入口得到 82/6/38/6、exit 0；
  3. `git diff --check`、两文件 diff、temp residue、七字段/secret 扫描
- 完成：所有 §7 检查实际在入口内；无可达
  `NotImplementedError`；只改两路径

### R4 — `docs: prepare WU1 remediation review`

- 文件：仅 `docs/reviews/work-unit-1-remediation-review.md`
- 职责：记录 Git、hash、red/green、fault injection、scope、输出、
  完成判定和唯一最终状态；引用但不修改原 WU1 Review
- 前置：R3 全绿
- 验证：Review 最终字节形成后再次运行 §6.4 两条命令；检查完整
  R0—R4 diff、工作树、remote、stash、保护 hash
- 完成：只新增 Review；最终状态为三者之一；停止等待 Hugin

除 R2 的有效 red 外，任何 commit 完成时测试不得失败。R4 不得修
实现。

## 10. 预注册的 18 条完成判定

WU1R Review 必须逐条用 `✓ 已完成`、`⚠ 已知限制` 或 `✗ 未完成`
对照，不能增删、拆分或合并：

1. WU1 final HEAD、11 个历史 commit 和原 WU1 Review 的
   `INCOMPLETE` 字节保持不变。
2. 获批 WU1R Plan 由 R0 单独提交，获批 SHA256 留痕且 R0 后未修改。
3. `pyproject.toml`、`requirements.lock` 和实际 dependency set 未被
   WU1R 修改或扩展。
4. WU1R 实际 diff 只含五路径白名单，原 WU1 36 路径集合精确匹配。
5. R1 只建立可导入入口边界，未提前实现 R2 测试所要求的行为。
6. R2 用固定命令取得有效 red；实际 100 tests，原 82 全 green，red
   不来自 import、路径、依赖、PowerShell、语法或畸形测试。
7. R3 用逐字符相同命令取得 100/100 green，18 个新 case 全通过。
8. 单入口真实断言 executable、prefix、site-packages 位于项目
   `.venv`，无全局 fallback。
9. 单入口精确比较 21 个 lock 包与运行包并执行 `pip check`；bootstrap
   排除项仅为 `pip`、`setuptools`。
10. 单入口验证 11 个 Schema metadata/registry/format、完整 82-test
    discovery，以及 6/38/6 closed/root fixture 契约。
11. 单入口精确检查原 36 路径、WU1R 五路径增量、fallback/guess/infer/
    warning 和 secret，实际白名单外/命中数均为 0。
12. 单入口逐一校验七个原冻结输入和 WU1 Plan 共 8 个 hash，全部匹配。
13. 故障注入实际证明 exit 2、3、4、5，artifact 问题没有被映射成 3，
    混合问题优先级确定。
14. 每个机器问题只在 stderr 以 JSONL 输出且恰含七字段；stdout 只含
    安全人类摘要；第三方原文、实际输入值和 secret 泄漏为 0。
15. PowerShell 继续使用系统临时 GUID、UTF-8 无 BOM、项目 Python 和
    `finally`；成功/失败 residue 均为 0，且无 `python -c`、
    `Invoke-Expression` 或嵌套 `powershell -Command`。
16. 完整入口在 R3 和 R4 两次独立运行均 exit 0，实际结果均为
    82 tests、6 fixture、38 documents、6 dirty cases。
17. schema/fixture validator、Schema、正式 fixture、原测试、WU0、
    handbook 和用户配置均保持不变；无业务/API/WU2 内容。
18. R0—R4 线性历史、完整 diff/stat、所有命令 exit code 和 hash 可
    独立复核；最终工作树干净、remote/stash/push 均为 0，并给出唯一
    WU1R Review 状态。

任一关键项为 `✗` 不得使用 `READY_FOR_HUGIN_REVIEW`。任何 `⚠` 是否
允许 READY 必须有执行前 Hugin 书面裁定；不得自行推断。

## 11. Review 证据

`docs/reviews/work-unit-1-remediation-review.md` 至少记录：

- WU1R 起点、最终 HEAD、R0—R4 log、完整 diff/stat；
- 原 WU1 11 commits 和 Review hash 前后对账；
- WU1R Plan 获批 SHA256 与 R0 后 hash；
- 五路径白名单、原 36 路径集合和额外路径数；
- 八个入口冻结 hash；
- requirements.lock 21 项、运行包、bootstrap 两项、`pip check`；
- executable/prefix/site-packages 实际路径归属；
- 11 Schema、registry 和 format checker；
- R2 red 与 R3 同命令 green 的完整 test ID、数量和 exit code；
- exit 2/3/4/5 故障注入、七字段 JSONL、stdout/stderr 分流；
- 两次完整入口的 82/6/38/6 和 temp residue；
- fallback、warning、secret、scope 和 protected-file scan；
- §10 的 18 条判定逐项状态；
- 无 remote、push、WU2 或 WU2 Plan；
- 以下唯一状态之一：

```text
READY_FOR_HUGIN_REVIEW
BLOCKED
INCOMPLETE
```

Review 后停止，不进入 WU2。

## 12. Blocking 条件

以下任一发生立即停止 WU1R Execute：

- 执行前 HEAD、分支、工作树、原 WU1 Review、冻结输入或获批 Plan
  hash 不匹配；
- Hugin 未明确批准本 Plan，或批准要求改变了本文件未体现的内容；
- 需要第六个路径，或需要修改任何保护文件、原 commit、handbook；
- 需要新增/升级依赖，修改 lock、pyproject 或用户配置；
- R2 不能取得 §6.3 定义的有效 red，或原 82 tests 出现回归；
- 新测试只有加入默认 discovery 才能实现，导致 82 计数裁定失效；
- PowerShell 5.1、Python 3.11、Git 或现有依赖无法在 Plan 内实现；
- lock/package identity 无法精确判断且只能靠猜测/宽松 allowlist；
- exit 2/3/4/5 只能靠统一模糊 code、复制第三方异常或修改 validator
  才能实现；
- scope/scan 只能靠排除未知文件、忽略 untracked 或 silent fallback
  才能通过；
- failure-path temp cleanup 只能通过暂改受保护文件或 Git index 验证；
- 继续会输出用户值、secret、本机私有路径或凭据；
- R3 green 需要修改测试、Schema、fixture 或现有 validator；
- R4 发现任何实现缺口；R4 只能报告，不能修复。

非阻塞但必须如实记录：

- WU1 Review 保持 `INCOMPLETE` 是正确历史，不是 WU1R 失败；
- WU1R 显式 suite 为 100 tests、入口 discovery 为 82 tests，二者是
  §3.1 批准的不同验收表面；
- 文档中出现 fallback/secret 等规则词不等于生产逻辑命中，扫描按
  §4.7 的结构化规则判定。

## 13. 延后事项

以下全部不进入 WU1R：

- WU2：高德 POI/路径 adapter；
- WU3：证据采集、正交定级和依赖传播；
- WU4：约束解析、环境检查和可行性状态；
- WU5：基地、分天、天内排序；
- WU6：重排稳定性和 plan diff；
- WU7：HTML 行程卡；
- WU8：江西真实 fixture 与旅行验收；
- v1：完整目的地发现。

WU1R 不创建这些工作单元的 Plan 或占位文件。
