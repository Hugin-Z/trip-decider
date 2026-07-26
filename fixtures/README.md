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
