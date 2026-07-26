# fixture_04_replan_stability

- Root: `urn:uuid:0000000a-0000-4000-8000-00000000000a` (`plan-diff`)
- Closure: `closed`
- Source: synthetic deterministic previous/new plan snapshots from the frozen
  plan-diff contract.
- Minimal closure: request, constraint-parse, constraints, candidates,
  evidence, previous-plan snapshot, new plan, and plan-diff.
- Clean coverage: explicit previous/new plan IDs, configured change weights,
  one change, change score, reason, constraint refs, and `previous`
  `resolution_scope`.
- Dirty case: remove `resolution_scope` and expect the exact Schema `required`
  error.
- Non-coverage: whether the score is minimal or the replan is optimal. WU6
  implements and evaluates those behaviors.
