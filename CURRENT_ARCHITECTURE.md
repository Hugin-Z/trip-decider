# Current Architecture

This document describes the system that is running now. Historical migration
plans and baseline measurements remain under `PLAN.md` and `docs/contracts/`,
but they are not an alternative runtime design.

## Data and control flow

```text
Intent
  -> Agent Runtime
  -> Evidence Collection
  -> Fact Model
  -> Support/Freshness Evaluation
  -> Planner
  -> Read Model
  -> MCP/Web adapters
```

### Intent

`travel_agent.TravelIntent` is the structured input boundary. It contains the
task mode, time window, party, budget, pace, transport preferences, themes and
optional destination anchor. The core runtime does not interpret natural
language.

### Agent Runtime

`travel_agent.py`, `trip_application.py` and `agent_actions.py` own run state,
lifecycle transitions and the action loop. `TripApplicationService` is the
write-side coordinator. Durable state is JSON under `runtime/sessions/`; there
is no database. A runtime directory is owned by one process at a time. Runtime
persistence formats before v2 are not supported.

### Evidence Collection

`destination_runtime.py`, `dynamic_discovery.py`, `guided_discovery.py`,
`intercity_rail.py` and `simple_live.py` collect provider results. The
`EvidenceBroker` is the only cross-run evidence cache and applies the declared
reuse bounds. A seed catalog may propose open-discovery candidates, but railway,
map and destination facts are checked by the live collectors before planning.

### Fact Model

`EvidenceItem` persists collection metadata and field-level `facts`. Each fact
keeps provenance, data type, retrieval time and support. Unknown and conflicting
facts remain explicit instead of being replaced with plausible values.

### Support/Freshness Evaluation

`evidence_core.py` is the reliability kernel. It contains the pure rules for
support aggregation, freshness, display tokens and next actions; it performs no
I/O and reads no clock by itself. `evidence_projection.py` adapts persisted
evidence to that kernel and injects the read time and policy.

### Planner

`planning_input_compiler.py` converts evaluated facts into planner input.
`itinerary_planner.py` builds and validates the deterministic itinerary
structure. Estimated, unknown, conflicting or stale inputs retain their
conditions and blockers; the planner does not invent missing facts.

### Read Model

`trip_query.py` is the query boundary and `trip_read_model.py` builds the
user-facing projections. Read-time support/freshness evaluation happens here,
while writes and refresh persistence are delegated to the application service.

### MCP/Web adapters

`mcp_server.py` and `mcp_adapter.py` expose the application and query services
as MCP tools and MCP App views. MCP mode relies on the external LLM host (for
example Claude Desktop) to interpret conversation and call those structured
tools; trip-decider does not embed an LLM.

`product_web.py` exposes the same services over local HTTP. Its standalone text
entry uses deterministic parsing (explicit patterns for dates, destinations,
party size, budget and preferences), not an embedded model. Both surfaces share
the same application/query boundaries and read model.

## Deliberate boundaries

- No database, LangGraph, CrewAI or multi-agent framework.
- No second planner or parallel evidence contract.
- Provider adapters collect facts; they do not change support or freshness
  policy.
- UI adapters render the read model; they do not create facts or planning
  decisions.
