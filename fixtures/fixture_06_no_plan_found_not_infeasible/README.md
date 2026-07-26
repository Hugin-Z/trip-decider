# fixture_06_no_plan_found_not_infeasible

- Root: `urn:uuid:00000007-0000-4000-8000-000000000007` (`violations`, post-plan)
- Closure: `closed`
- Source: synthetic deterministic status-boundary structure from the frozen
  four-state plan contract.
- Minimal closure: request, constraint-parse, constraints, candidates,
  evidence, no-plan-found plan, and post-plan violations.
- Clean coverage: `no_plan_found`, zero plan days, zero proof refs, zero
  violation proofs, and an explicit `plan_ref`.
- Dirty case: remove `plan_ref` and expect the exact Schema `required` error.
- Non-coverage: planner completeness and real infeasibility. WU4/WU5 must not
  turn this state into an “impossible” claim.
