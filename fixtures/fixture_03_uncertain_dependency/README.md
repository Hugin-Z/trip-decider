# fixture_03_uncertain_dependency

- Root: `urn:uuid:00000007-0000-4000-8000-000000000007` (`violations`, post-plan)
- Closure: `closed`
- Source: synthetic deterministic uncertainty structure from the frozen
  evidence and condition contracts.
- Minimal closure: request, constraint-parse, constraints, candidates,
  evidence, conditional plan, and post-plan violations.
- Clean coverage: orthogonal `unknown` support, `model_estimate` derivation,
  explicit freshness, a condition with constraint/fact refs, and matching
  `conditionally_feasible` status.
- Dirty case: remove the plan's sole condition and expect the exact `minItems`
  error.
- Non-coverage: evidence-state propagation and actual conditional feasibility;
  these remain for WU3/WU4.
