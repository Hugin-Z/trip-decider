# D0 prior art：ChinaTravel、Hao et al. 与 ItiNera

研究状态：`COMPLETE_WITH_KNOWN_LICENSE_LIMITS`

研究时间盒上限为 240 分钟。本次三项对象均已通过正式论文与作者/项目官方仓库完成身份消歧和核验；没有用搜索摘要、二手综述或模型记忆补结论。统一检索时间为 `2026-07-26T14:23:27.2744504+08:00`。许可结论只描述来源当前明确写出的内容，不构成法律意见。

## 1. 现有方法已解决

### ChinaTravel

- 正式对象是 ICLR 2026 论文 *ChinaTravel: An Open-Ended Travel Planning Benchmark with Compositional Constraint Validation for Language Agents*，当前 arXiv 为 v5（2026-04-29）。论文把评估拆成环境可行性、逻辑约束满足和偏好比较三层。[CT-PAPER，§2，pp. 3–4]
- 论文给出 `25` 条环境约束的六类口径：dietary、accommodation、transportation、temporal、spatial、attraction-related。这是 sandbox 环境可行性分类；同文后述的“七个 DSL basic-concept clusters”是另一种逻辑概念共现分析口径，不能混称为六类环境约束。[CT-PAPER，§2.1 与 §3/Fig. 4]
- DSL 使用 Python-like 组合结构：变量、布尔/算术运算、属性函数、空间关系、赋值 effect、集合运算、枚举和条件 effect。约束程序消费计划及 sandbox 数据并产生可执行验证结果；偏好则表达最小化/最大化比较目标。[CT-PAPER，Table 1、§2.2–2.3、Appendix D.3]
- 官方仓库实际可访问，并提供运行/评估代码、数据库下载入口及 `--oracle_translation`；该开关直接暴露标注的 `hard_logic_py` 与 `hard_logic_nl`，因此 oracle 成绩不能视作真实自然语言解析能力。[CT-REPO，README “Quick Start/Note”]
- 官方 Hugging Face 数据集页面实际可访问；官方仓库的 Google Drive 和 NJU Drive 数据库入口也能打开。可访问入口不等于已获准复制或已验证所有文件完整性。[CT-DATA；CT-REPO，README “Setup”]

### Hao et al.

- 本项目所指对象已由作者项目页、ACL Anthology 与代码仓库三方消歧为 Hao、Chen、Zhang、Fan 的 NAACL 2025 long paper *Large Language Models Can Solve Real-World Planning Rigorously with Formal Verification Tools*。[HAO-ACL；HAO-PROJECT；HAO-REPO]
- 方法把自然语言请求转成步骤，再转成调用数据 API 与 SMT solver 的 Python 代码。对被正确编码进 SMT 的约束，sound and complete solver 可以给出 satisfiable/unsatisfiable 结论。[HAO-PDF，§3.2–3.3，pp. 3436–3438]
- 正式主表的最高 TravelPlanner Final Pass Rate 是 Claude-3 在 validation `93.3%`、test `93.9%`。论文附录 `Ours+JSON` 是不同配置：GPT-4 test `97.0%`；主配置 GPT-4 test 是 `90.2%`。因此 ChinaTravel 所引的“97%”与正式摘要的“93.9%”不是同一模型/配置，不能互换。[HAO-PDF，Table 1 与 Table 8]
- 实现确实调用 Z3 `get_unsat_core` 提取 unsatisfiable reasons，并用其驱动交互式修复；但“尽量小改”只是 LLM prompt 指令和候选建议，并未给出最小冲突集或最小约束放松的完备最小化证明。[HAO-PDF，§3.3.3–3.4、Appendix G prompts]
- 作者仓库实际可访问，包含 UnsatChristmas 小型数据库、unsat CSV、prompt 和运行脚本；satisfiable TravelPlanner 主数据仍要求到 TravelPlanner 项目另行下载。[HAO-REPO，README “Setup Environment/Running”]

### ItiNera

- 正式对象是 EMNLP 2024 Industry Track 论文 *ItiNera: Integrating Spatial Optimization with Large Language Models for Open-domain Urban Itinerary Planning*。[ITI-ACL]
- 流水线把候选池建立、请求拆解、POI 检索、空间候选选择、排序和自然语言生成分开。候选池来自用户链接/趋势内容抽取后的 POI 数据库，并由地图 API 补位置、embedding 模型补向量；它不是从无外部资料的空白输入凭空生成。[ITI-PAPER，§3.2]
- POI selection 与空间优化是明确分阶段的：先按正负偏好 embedding 检索并合并 must-see POI，再按距离阈值建邻接图、聚类、用簇分数筛候选，最后以跨簇和簇内层次 TSP 排序。[ITI-PAPER，§3.3–3.5、Algorithm 1–2]
- 优化器的关键输入契约是：已检索 POI 与偏好分数、距离阈值、候选数阈值；排序阶段再消费空间簇、候选 POI 和距离矩阵，输出有序 POI。[ITI-PAPER，Algorithm 1–2]
- 官方仓库实际可访问，提供上海中英文示例 CSV/embedding 和推理代码；README 明确这些数据仅用于开源演示，实际部署应换成自己的数据。[ITI-REPO，README “Example Data”]

## 2. 可直接复用

这里的“直接复用”仅指不复制受限代码/数据的设计原则与接口模式。

- 采用 ChinaTravel 的三层思想区分环境可行性、用户硬约束和软偏好，并借用六类环境约束作为 v0 初始词表；不复制其 Python DSL，也不把 oracle annotation 当线上输入。
- 将约束编译/验证做成确定性边界：只有被正确形式化且由完备检查覆盖的矛盾才可称 `proven_infeasible`。Hao 的 unsat core 与 LLM 修复建议之间的边界直接支持 `candidate_conflict_set` 命名。
- 采用 ItiNera 的阶段契约：候选生成/检索与空间优化分开；选择器输出稳定 POI ID、偏好分数、must-see 标识及坐标/来源，排序器只消费统一候选和距离/时长矩阵。
- 采用层次化、可解释的空间优化思路：先控制候选池，再选择空间簇，最后做簇间与簇内排序；v0 不必复刻完整 TSP 系统。
- 所有研究对象都强化同一边界：LLM 适合语义拆解、抽取与理由表达，确定性验证/优化器负责可复核结论；LLM 输出本身不是事实证据。

## 3. 真实旅行仍未解决

- ChinaTravel 的“实时 API”是固定数据库上的商业 API 模拟接口；论文数据覆盖固定城市和候选集合，不能证明真实 Web 中营业时间、临时闭馆、路径时长或酒店片区事实仍然有效。[CT-PAPER，§2.1、§2.4、Appendix D.1]
- ChinaTravel 的 oracle DSL 直接提供 ground truth constraint program；真实用户请求仍要处理歧义、错抽取、需要确认及来源冲突，不能把 oracle 结果当端到端能力。
- Hao 的完备性只对正确形式化且数据完备的 SMT 问题成立；自然语言到代码的错误、外部数据遗漏和时效变化不在 solver 保证内。其修复建议也不是经过确定性变更代价验证的最小重排。
- ItiNera 主要解决单日城市步行场景的个性化与空间连贯性。距离矩阵/TSP 不等于真实路时、交通方式、开放时间、活动时长、多日住宿基地或 evidence freshness 的联合可行性。[ITI-PAPER，§3.1、§3.5]
- 三项工作均未提供 trip-decider 需要的证据正交状态、来源冲突传播、旧计划基准上的确定性 plan diff，以及“状态误标为零”的真实旅行验收闭环。

## 4. 对 trip-decider 的具体影响

- `constraints.yaml` 必须把 environment、hard、soft 分开；六类环境约束只作初始 taxonomy，不成为城市专属分支或封闭菜单。
- `constraint-parse.json` 必须保留自然语言到规范约束的版本、说明、确认需求和 hash；不能把 ChinaTravel 的 oracle DSL 当作真实解析替代。
- `evidence.json` 必须保留来源、原始值、标准化值、retrieved/effective/expiry 时间与定级规则。地图 API 路时仍是 `api_estimate`，不得因经过算法计算就升级为直接观测。
- `violations.json` 必须区分 solver/规则证明与启发式失败。只有完备检查覆盖的冲突可产生 `proven_infeasible`；unsat core 之外的修复建议仍是 `candidate_conflict_set`。
- `candidates.json` 与 `plan.json` 之间冻结阶段边界：adapter/候选阶段可感知供应商和地区，planner 只消费统一 ID、证据和矩阵，不感知城市名。
- 重排必须消费 `previous-plan.json`，并用配置化变更代价生成 `plan-diff.json`；研究对象中的自然语言“少改”提示不能替代该目标函数。

## 5. 不应重复实现的内容

- 不自创完整 benchmark；ChinaTravel 已提供组合约束、环境可行性和偏好评估框架。v0 只建立对真实江西旅行有用的少量 fixture 与 replay。
- 不复制 ChinaTravel 的 Python-like DSL 或整套 sandbox。它面向 benchmark 自动评估，并含 oracle 通道；trip-decider 需要可编辑工件和真实来源 provenance。
- 不在 v0 自建通用 SMT 代码生成框架。先实现 Plan 中列出的确定性下界矛盾和启发式规划状态；需要完备求解器时另走 PER。
- 不复制 ItiNera 的社交内容采集、embedding 候选库或完整层次 TSP；这些属于 v1 目的地/候选发现或后续优化，而且会提前引入模型、数据和依赖。
- 不复制许可未清或带 copyleft/非商业限制的代码、数据或 fixture。WU0 只记录思想和公开论文事实。

## 6. 本项目仍需验证的假设

- 六类环境 taxonomy 是否足以覆盖 v0 真实江西行程，还是需要在不改 planner 核心的前提下扩充 adapter 输出。
- 高德 POI/路径与地方官方来源能否稳定提供开放时间、位置和路时，并携带足够 freshness/provenance。
- 候选池规模控制、空间簇和贪心分天能否在可解释性优先下找到真实可走方案；找不到时能否诚实输出 `no_plan_found`。
- `unknown/conflicting` 依赖传播是否能阻止不受支持事实静默支撑 `feasible`，同时不让输出退化为不可用。
- 简单变更权重是否能在真实重排中保持日期、相对顺序和住宿基地，并产生用户认可的最小改变。
- 真实旅行前/中 replay 是否能区分来源变化、来源过期、采集错误、标准化错误与证据状态误标。

## 7. 一手来源清单

所有条目的 `retrieved_at` 均为 `2026-07-26T14:23:27.2744504+08:00`。

| ID | 一手来源与访问结果 | 版本/发表信息 | locator | license 事实 |
|---|---|---|---|---|
| CT-PAPER | [arXiv HTML](https://arxiv.org/html/2412.13682)，HTTP 内容可读 | arXiv:2412.13682v5；ICLR 2026 论文元数据见官方仓库引用 | §2.1–2.4、§3、Table 1、Fig. 4、Appendix D/I | Appendix I 写 benchmark/dataset 为 `CC-BY-NC 4.0`、限非商业研究 |
| CT-REPO | [LAMDA-NeSy/ChinaTravel](https://github.com/LAMDA-NeSy/ChinaTravel)，仓库与 README 可读；Google Drive/NJU Drive 入口实际打开 | `main`；官方 ICLR 2026 codebase | README “Quick Start”“Note”“Docs”；`chinatravel/symbol_verification/readme.md` | GitHub repository API `license=null`，根目录无 LICENSE 文件；不能据此假定代码许可 |
| CT-DATA | [官方 Hugging Face dataset](https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel)，dataset viewer 可读 | `LAMDA-NeSy/ChinaTravel` 当前页面 | Dataset card、Files/Data Studio、license metadata | 页面标 `cc-by-nc-sa-4.0`，与论文 Appendix I 的 `CC-BY-NC 4.0` 冲突；任何衍生 fixture 前须先澄清，当前不复制 |
| HAO-ACL | [ACL Anthology 正式页](https://aclanthology.org/2025.naacl-long.176/) 与 [PDF](https://aclanthology.org/2025.naacl-long.176.pdf)，均可读 | NAACL 2025 Long Paper；DOI `10.18653/v1/2025.naacl-long.176` | Abstract、§3.2–3.4、Table 1、Table 8、Appendix G | ACL 论文许可不自动授权作者仓库代码/数据 |
| HAO-PROJECT | [作者项目页](https://sites.google.com/view/llm-rwplanning)，可读并链接论文与仓库 | NAACL 2025 Main (Oral) | Abstract、Dataset & Code link | 页面未给代码/数据许可 |
| HAO-REPO | [yih301/LLM_Formal_Travel_Planner](https://github.com/yih301/LLM_Formal_Travel_Planner)，仓库、数据目录和脚本清单可读 | `main`；作者项目页链接的 code/dataset | README “Setup Environment”“Running”“Evaluation” | GitHub repository API `license=null`，根目录无 LICENSE 文件；当前不复制代码/数据 |
| ITI-ACL | [ACL Anthology 正式页](https://aclanthology.org/2024.emnlp-industry.104/) | EMNLP 2024 Industry Track，pp. 1413–1432 | Abstract 与正式发表元数据 | ACL 论文许可不替代仓库许可 |
| ITI-PAPER | [arXiv HTML](https://arxiv.org/html/2402.07204)，全文可读 | arXiv:2402.07204；内容对应正式论文 | §3.1–3.5、Algorithm 1–2、Appendix B/E | 论文页面许可不替代代码/示例数据许可 |
| ITI-REPO | [YihongT/ITINERA](https://github.com/YihongT/ITINERA)，仓库、示例数据说明和 LICENSE 可读 | `main` | README “Example Data”“License”；根目录 `LICENSE` | GitHub API 为 `GPL-3.0`；README 另要求商业使用联系作者，故本项目不复制实现 |

访问结论：没有对象级 `BLOCKED`。ChinaTravel dataset 的两处官方许可元数据存在冲突，ChinaTravel 与 Hao 仓库没有可识别的代码许可证；这些是已核实的复用限制，不是用推断补齐的许可结论。
