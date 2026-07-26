# fixture_02_direct_conflict

- Root: `urn:uuid:00000008-0000-4000-8000-000000000008` (`violations`, pre-plan)
- Closure: `closed`
- Source: synthetic deterministic direct-conflict structure from the frozen
  proof contract; no real-world claim is made.
- Minimal closure: request, constraint-parse, constraints, candidates,
  evidence, and pre-plan violations. A plan artifact is intentionally absent.
- Clean coverage: `proven_infeasible`, four input artifact references, one
  proof with constraint/fact refs and numeric bounds, and no `plan_ref`.
- Dirty case: remove the sole proof and expect the exact `minItems` error.
- Non-coverage: proof arithmetic and whether the conflict is true. WU4 must
  recompute any proof before making a business claim.
