# WU1 structured fixtures

These six fixtures are synthetic deterministic structural cases derived from
the frozen WU1 contract. They are not real Jiangxi travel anchors and do not
claim that evidence is true, a proof is correct, a route is feasible, or a
replan is optimal.

Every `case.json` embeds the exact UTF-8/LF bytes of its documents, records the
SHA256 of those bytes, declares `bundle_closure: closed`, and names one actual
envelope artifact ID as `root_artifact_id`. Each dirty case performs one
pre-registered mutation and requires an exact error code, JSON Pointer, and
schema rule.

| Fixture | Root type | Documents | Dirty cases | Behavior deferred to |
|---|---|---:|---:|---|
| `fixture_01_feasible` | post-plan violations | 7 | 1 | WU4/WU5 |
| `fixture_02_direct_conflict` | pre-plan violations | 6 | 1 | WU4 |
| `fixture_03_uncertain_dependency` | post-plan violations | 7 | 1 | WU3/WU4 |
| `fixture_04_replan_stability` | plan-diff | 8 | 1 | WU6 |
| `fixture_05_evidence_state_mapping` | evidence | 3 | 1 | WU3 |
| `fixture_06_no_plan_found_not_infeasible` | post-plan violations | 7 | 1 | WU4/WU5 |

The fixture validator checks only structure, exact bytes/hash, safe paths,
explicit root/closure, root-reachable closure, mutation mechanics, and expected
structural errors. `behavior_expected` remains opaque in WU1.

## 其余夹具目录

上表只覆盖 WU1 的六个结构夹具。同级还有三个来源不同的目录：

| 目录 | 来源 | 用途 |
|---|---|---|
| `golden_cases/` | 构造的目的地上下文 | 端到端回放 |
| `jiangxi_multi_identity_smoke/` | 单次获批的 Overpass POST（2026-07-28） | 字节级离线回放、复数 provider 身份 |
| `host_mcp_smoke/` | 首次真实宿主实测（Claude Desktop MCP，2026-08-03） | D21「真实调用最小可跑」名单的两条契约测试 |

`host_mcp_smoke/` 的两份夹具是**宿主真实提交的形状**，脱敏只改地名与时间窗。
**不补键**——两个 P0 都是形状对不上而不是值不对，补一个键夹具就不再复现事故。
详见该目录的 README 与 `docs/contracts/engineering-discipline.md` D21。
