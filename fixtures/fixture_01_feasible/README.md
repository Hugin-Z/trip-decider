# fixture_01_feasible

- Root: `urn:uuid:00000007-0000-4000-8000-000000000007` (`violations`, post-plan)
- Closure: `closed`
- Source: synthetic deterministic data fixed from the WU1 contract; synthesis
  is allowed because this case tests deterministic structure, not retrieved
  travel facts.
- Minimal closure: request, constraint-parse, constraints, candidates,
  evidence, plan, and post-plan violations.
- Clean coverage: request-scope constraint, relation-shaped route fact from an
  API response, `api_estimate` derivation detail, feasible plan, and matching
  post-plan status.
- Dirty case: remove the required estimate from the API-derived fact and expect
  the exact Schema `required` error.
- Non-coverage: evidence truth, actual travel time, real feasibility, routing,
  and itinerary quality. These remain for WU4/WU5.
