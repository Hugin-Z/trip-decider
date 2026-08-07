# Public claims audit — v0.1.0

本表核对 README 的主要公开声明。置信度只评价“仓库证据能否支持这句窄声明”，不代表
全国覆盖率、provider SLA 或未来数据正确性。

| Claim | Implementation / test / report evidence | Confidence |
| --- | --- | --- |
| **MCP Agent mode**：外部 MCP host 理解自然语言并调用工具；trip-decider 管理状态、证据、规划与核验。 | [`mcp_server.py`](../src/trip_decider/mcp_server.py)、[`mcp_adapter.py`](../src/trip_decider/mcp_adapter.py)、[`test_mcp_adapter.py`](../tests/test_mcp_adapter.py)、[`retest-2026-08-03-host-adoption.md`](field-reports/retest-2026-08-03-host-adoption.md) | **High**：实现、离线 MCP 测试与 Claude Desktop 实测均存在。只声明 MCP-capable host 模式，不声明宿主模型质量。 |
| **Deterministic standalone Web mode**：Web 对显式日期、地点、人数、预算和偏好做确定性结构提取，不调用模型 API。 | [`product_web._intent_from_trip_text`](../src/trip_decider/product_web.py)、[`test_product_web.py`](../tests/test_product_web.py) | **High**：实现是显式规则/正则并有生命周期测试。措辞限定为 structured extraction，不声称自由文本理解等同 LLM。 |
| **12306 integration**：查询铁路车次、时刻和票价，并用于规划与核验。 | [`intercity_rail.py`](../src/trip_decider/intercity_rail.py)、[`test_itinerary_verification.py`](../tests/test_itinerary_verification.py)、[`verify-2026-08-04-third-party-vs-12306.md`](field-reports/verify-2026-08-04-third-party-vs-12306.md) | **High for integration; time-bound for data**：有实现、受控测试和真实查询记录。历史快照不被描述为当前时刻表。 |
| **AMap integration**：采集地点身份、POI、路线和当地公共交通。 | [`simple_live.py`](../src/trip_decider/simple_live.py)、[`destination_runtime.py`](../src/trip_decider/destination_runtime.py)、[`test_local_transit_detail_expansion.py`](../tests/test_local_transit_detail_expansion.py)、[`soak-2026-08-05-r8-r9-gate.md`](field-reports/soak-2026-08-05-r8-r9-gate.md) | **High for adapter path; limited coverage**：代码、解析测试和真实链路记录存在；不声明实时到站、全国质量或每条线路都有数据。 |
| **Plan capability**：从确认后的 intent、候选与证据编译逐日结构，包含交通、预算、返程边界和版本化 revision。 | [`planning_input_compiler.py`](../src/trip_decider/planning_input_compiler.py)、[`itinerary_planner.py`](../src/trip_decider/itinerary_planner.py)、[`test_planning_input_compiler.py`](../tests/test_planning_input_compiler.py)、[`test_revision_chain_after_convergence.py`](../tests/test_revision_chain_after_convergence.py) | **High for implemented behavior**：主链有离线覆盖；真实端到端范围仍限定为 README 的 Current scope。 |
| **Verify capability**：逐条输出 `sourced`、`conflicting`、`unknown`；`unknown` 不等于 false。 | [`itinerary_verification.py`](../src/trip_decider/itinerary_verification.py)、[`test_itinerary_verification.py`](../tests/test_itinerary_verification.py)、[真实铁路对账](field-reports/verify-2026-08-04-third-party-vs-12306.md) | **High**：三档语义有直接测试和真实冲突实例。当前公开声明只覆盖铁路断言核验。 |
| **Field-level evidence model**：事实字段分别携带来源、支持状态、采集时间和依赖，不以整份文档的单一标签替代。 | [`travel_agent.EvidenceItem`](../src/trip_decider/travel_agent.py)、[`evidence_core.py`](../src/trip_decider/evidence_core.py)、[`test_evidence_facts_derivation.py`](../tests/test_evidence_facts_derivation.py)、[`test_persisted_round_trip_keeps_verdicts.py`](../tests/test_persisted_round_trip_keeps_verdicts.py) | **High**：字段级 facts 的推导、落盘和往返一致性均有测试。 |
| **Support × Freshness**：support 为 sourced/estimated/conflicting/unknown；freshness 为 fresh/stale/undated，并在读取时计算。 | [`evidence_core.py`](../src/trip_decider/evidence_core.py)、[`evidence_projection.py`](../src/trip_decider/evidence_projection.py)、[`test_invariant_i2_token_matches_support.py`](../tests/test_invariant_i2_token_matches_support.py)、[`test_invariant_i5_freshness_is_read_time.py`](../tests/test_invariant_i5_freshness_is_read_time.py) | **High**：取值域、合取和读时重算有直接不变式测试。 |
| **Stateful runtime**：任务经历 intent、confirmation、execution、blocked/completed、revision；blocked 暴露 recovery/next action。 | [`travel_agent.py`](../src/trip_decider/travel_agent.py)、[`trip_application.py`](../src/trip_decider/trip_application.py)、[`agent_actions.py`](../src/trip_decider/agent_actions.py)、[`test_action_loop_crash_recovery.py`](../tests/test_action_loop_crash_recovery.py)、[`test_every_error_carries_a_next_call.py`](../tests/test_every_error_carries_a_next_call.py) | **High**：状态、恢复、错误出口与 revision 均有直接测试；不声明多进程共享或分布式执行。 |
| **Current tested scope**：主要真实端到端场景是武汉 → 婺源及上饶区域；另有有限的其他 soak seeds。 | [`docs/field-reports/`](field-reports/)、[`soak-2026-08-05-r8-r9-gate.md`](field-reports/soak-2026-08-05-r8-r9-gate.md)、[`KNOWN_ISSUES.md`](../KNOWN_ISSUES.md) | **High for the stated narrow scope**：有真实报告；README 明确拒绝把它外推为全国或通用覆盖。 |

## Wording decisions

- 不使用“实时 everything”：只有具体 provider 的当次查询可称 live，历史结果明确是快照。
- 不使用“自动预订”或“消费级服务”：系统不持有账户，也不执行订票/订房。
- 不把 `unknown` 写成 false，不把到达 soak 终态写成“生成计划成功”。
- AMap 声明限于已实现的地点、POI、路线和当地交通字段；不声称实时到站。
- Verify 的公开范围写成铁路断言核验，不暗示所有旅行事实类型都已有同等核验器。
