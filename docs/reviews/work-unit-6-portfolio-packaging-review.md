# Work Unit 6 · Portfolio Packaging Review

Review status: READY_FOR_HUGIN_REVIEW
Decision preserved: PACKAGE_APPROVED_MVP_WITHOUT_NEW_CAPABILITY
Execution model: Package → Verify → Review

## 1. Scope and baseline

Approved Plan:

```text
plans/work-unit-6-portfolio-packaging.md
Version: v0.1
SHA256: 415AA4B45A22D2C7F2947D1C3BD56A4E1FA2174D011B4093B71DBD669E8DFA24
```

Execution started from:

```text
branch: main
HEAD: 91ee1a0c7c29a9ac03a270d35ad5ea983ea86ce7
worktree: only the approved WU6 Plan
remotes: 0
stashes: 0
tests: 210/210
schemas: 11
fixtures/documents/dirty cases: 7/40/7
```

Handbook remained read-only:

```text
local/origin: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree changes: 0
```

No runtime, Schema, validator, fixture, test, dependency, `pyproject.toml`,
`PLAN.md`, handbook, or historical verifier was changed.

## 2. Linear Git history

The first four committed WU6 changes are:

```text
54e236358b043a6126d7e3e8c9e466e560ef97df docs: record WU6 portfolio packaging plan
117a786c084c6f0e862482a20f29d27637b5b1c2 feat: add reproducible Wuyuan demo package
dfa613607921e1f1c5f699d144ae1f5a06b4648a docs: add portfolio README
bec4b9b84ff5a63ad48ba4c00a3cc5c2f4ae4ab8 chore: add portfolio packaging verification
```

C4 uses the approved message:

```text
docs: prepare WU6 portfolio packaging review
```

The committed C0–C3 diff before this Review was:

```text
7 files changed, 1340 insertions(+), 20 deletions(-)
```

Adding this Review is the eighth and final approved path. The final
post-commit `git log` and verifier output are handoff evidence because a
document cannot contain the hash of the commit that contains itself.

## 3. Exact eight-path scope

Final WU6 scope is:

```text
plans/work-unit-6-portfolio-packaging.md
README.md
examples/wuyuan-two-day/request.yaml
examples/wuyuan-two-day/constraint-parse.json
examples/wuyuan-two-day/constraints.yaml
scripts/run_wuyuan_demo.ps1
scripts/verify_wu6_portfolio_packaging.ps1
docs/reviews/work-unit-6-portfolio-packaging-review.md
```

The verifier unions committed diff paths, tracked working changes, and
untracked files. It rejects every ninth path and requires all seven package
paths before Review; after C4 it requires all eight paths and all five exact
commit messages.

## 4. Frozen hashes

| Path | SHA256 |
| --- | --- |
| `plans/work-unit-6-portfolio-packaging.md` | `415AA4B45A22D2C7F2947D1C3BD56A4E1FA2174D011B4093B71DBD669E8DFA24` |
| `README.md` | `88BCAD43CAB71E3531AB3B45A3F73E6B874869F3B521131687D0ABB007F9ED14` |
| `examples/wuyuan-two-day/request.yaml` | `EE1E8BAEF43868757FE8A7B4BB4A3C0148C4FB81241C2D91DF23E26A6D4F23F1` |
| `examples/wuyuan-two-day/constraint-parse.json` | `DF5B1D9809E628CD1B1B8F7D3056D11E03691EB654C89420549DDB57E0F69898` |
| `examples/wuyuan-two-day/constraints.yaml` | `769BFC565DBBD0BDA555AA0F91DCD97A272F34CF696B71321DA868B688C51EC2` |
| `scripts/run_wuyuan_demo.ps1` | `A8C40539F639E0E0118DFE39C6C86C7D9B32A7A272A680CDFE4D54F21C6EE14C` |
| `scripts/verify_wu6_portfolio_packaging.ps1` | `0F5F57DB633AE585FF5F675872310019E9D128886B31350DA6F230C822EE7ADB` |
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `pyproject.toml` | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` |
| `requirements.lock` | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` |

The verifier also freezes all 11 Schema hashes, the four relevant runtime
modules, the WU4/WU5 tests that define and exercise the example, and the four
committed anchor files.

## 5. Example input evidence

The three examples were materialized from the independently authored
two-day planning input in `tests/test_wu4_coarse_planner.py`; they were not
derived from Planner or final plan output.

| Artifact | Artifact ID | Payload SHA256 |
| --- | --- | --- |
| request | `urn:uuid:20000001-0000-4000-8000-000000000001` | `b49538aa6aea6526e4154e7aa18053ec343c3c5fa7a2436bdfb4f43143593823` |
| constraint-parse | `urn:uuid:72a359c8-bb4b-49d1-aeae-59e649fab048` | `5cc8d256f6f0a57c79210d1bcdb68c9508b2fb6cb8b220e7374efd82a87f385c` |
| constraints | `urn:uuid:93d97ccf-c2ce-4c63-9db5-2722024705a8` | `ec577faba1241b7a1fed1feb3bfcfbcb7c03fab4577ad82af1cc2517db00e065` |

Independent verification proved:

```text
documents individually Schema-valid: 3
CLOSED root: urn:uuid:93d97ccf-c2ce-4c63-9db5-2722024705a8
reachable artifacts: 3
Candidate request ref: exact
constraints_are_solver_ssot: true
request_auto_overwrite: false
UTF-8 BOM: 0
absolute paths: 0
byte-read mismatches: 0
```

The examples contain the explicit two-day window and ordered must-visit
values 江岭, 李坑, 篁岭, 庆源. They add no route, distance, duration, default
time, random ID, current timestamp, or machine path.

## 6. Demo script evidence

The script uses only:

```text
<repo>\.venv\Scripts\python.exe
python -m trip_decider.e2e_demo
fixtures/jiangxi_multi_identity_smoke
examples/wuyuan-two-day
caller-supplied missing OutputRoot
```

It does not install the project, fall back to global Python, copy E2E
orchestration, choose a repository output root, or delete an existing root.
The existing-root injection returned nonzero and preserved its only marker
file.

The script saves `PYTHONPATH`, sets it to `<repo>\src` around the child, and
restores it in `finally`. Runtime verification covered:

```text
success with pre-existing sentinel: restored exact value
injected failure with originally absent variable: variable absent afterward
permanent user environment changes: 0
```

`-OpenReport` is guarded by child exit `0` and existence of
`report/index.html`. The automated verifier never enables that switch.

## 7. Real demo result

The approved entry was executed against a missing system-temp output root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_wuyuan_demo.ps1 `
  -OutputRoot <system-temp-output>
```

Actual safe stdout:

```text
status=conditionally_feasible scheduled=2 blocked=2 publishable=false report=report/index.html
```

Independent output checks:

```text
exit code: 0
stderr: empty
output files: 13
planning_status: conditionally_feasible
scheduled: 2
blocked: 2
publishable: false
generation_allowed_input: false
network attempts: 0
LLM calls: 0
temporary residue: 0
```

The HTML contains Day 1 江岭, Day 2 李坑, 篁岭, 庆源,
`support_status: unknown`, `display_status: unknown`,
`publishable: false`, and `generation_allowed_input: false`. It contains no
script, image, external URL, or positive best-route/verified/publishable claim.

## 8. README audit

The old WU0 bootstrap README was replaced rather than appended. The new
README has:

```text
repository-relative links: 6/6 resolve
external links/images/badges: 0
absolute paths: 0
Hugin/Codex approval transcript: 0
Mermaid architecture diagrams: 1
UTF-8 BOM: 0
```

It accurately states the two scheduled locations, both blocker states,
conditional/non-publishable result, evidence ceiling, one-anchor limitation,
and absence of route, opening-hours, duration, map, hotel, weather, cost, and
recommendation capability.

The host initially refused an inline execution containing a recursive delete
token before the command ran. No path was deleted. The README run block was
then mechanically extracted without changing its bytes and executed verbatim
with an isolated system-temporary `TEMP`. That actual run produced:

```text
exit code: 0
outputs: 13
network/LLM: 0/0
temporary residue: 0
```

This is an execution-environment command transport correction, not a README,
script, or product-contract change.

## 9. Verification entry

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\verify_wu6_portfolio_packaging.ps1
```

The first complete C3 run was green before commit. The character-identical
independent rerun after C3 was also green:

```text
WU6_PORTFOLIO_PACKAGING_VERIFICATION=PASS
checks=20
tests=210
schemas=11
fixtures=7
documents=40
dirty_cases=7
outputs=13
network_attempts=0
llm_calls=0
temporary_residue=0
```

Environment evidence additionally reported:

```text
project venv executable/prefix/site-packages: true/true/true
exact lock packages: 21
pip check: No broken requirements found
README links: 6
Candidate request ref: exact
```

## 10. Twenty verification checks

1. ✓ Project venv, exact lock inventory, and `pip check`.
2. ✓ Approved Plan SHA256.
3. ✓ Approved eight-path Scope with C3/C4 phase gate.
4. ✓ Exact ordered five-commit prefix with C3/C4 phase gate.
5. ✓ All 11 Schema hashes.
6. ✓ Protected runtime, fixture, dependency, and `PLAN.md` hashes.
7. ✓ README existence, strict UTF-8, no BOM or absolute path.
8. ✓ Six repository-relative README links resolve.
9. ✓ Three example artifacts pass Schema and CLOSED validation.
10. ✓ Example request ref exactly matches the Candidate artifact.
11. ✓ Real `run_wuyuan_demo.ps1` execution.
12. ✓ Exit `0`, empty stderr, and exact safe status line.
13. ✓ Exactly 13 approved output paths.
14. ✓ HTML locations and conditional/non-publishable boundary text.
15. ✓ HTML prohibited-capability and external-resource scan.
16. ✓ Top-level summary network/LLM `0/0`.
17. ✓ Full explicit regression `210/210`.
18. ✓ Schema and fixture statistics `11` and `7/40/7`.
19. ✓ Repository/system-temp WU6 residue `0`.
20. ✓ `PYTHONPATH` restoration after success and injected failure.

## 11. Process corrections

All corrections were command-level and changed no approved product bytes:

1. The historical WU5 verifier rejected the newly approved WU6 Plan at its
   intentionally frozen WU5 Scope gate. It was not modified or bypassed.
2. A raw `unittest discover -s tests` invocation omitted the `src/`
   `PYTHONPATH`, so it produced import errors and no valid regression result.
3. The corrected source-layout invocation discovered 177 conventionally named
   tests but omitted the intentionally non-`test_` WU1C compatibility module.
4. The frozen explicit module suite then ran the actual complete `210/210`;
   the WU6 verifier uses that exact complete suite.
5. The host blocked the inline README cleanup command before execution; the
   unchanged block subsequently passed verbatim in an isolated temporary
   environment.

No failed command was represented as a product or contract failure, and none
was hidden from this Review.

## 12. R10 and scope audit

```text
silent fallback added: 0
guess/infer behavior added: 0
warning-as-pass behavior added: 0
secrets committed: 0
network calls: 0
LLM calls: 0
generated repository HTML/runtime output: 0
production runtime changes: 0
Schema/validator changes: 0
fixture/test/dependency changes: 0
push/remote creation: 0
next Work Unit work: 0
```

README claims remain below actual capability: Evidence stays unknown, the
draft stays conditional and non-publishable, ambiguous identity is not
selected, unmatched identity receives no placeholder, and the result is not
described as a best route or complete guide.

## 13. Twelve completion determinations

1. ✓ Starting HEAD, branch, worktree, remotes, and stashes matched.
2. ✓ Approved Plan bytes and SHA256 remained unchanged.
3. ✓ Final WU6 change set is exactly the eight approved paths.
4. ✓ Example bundle passed individual Schema and CLOSED validation.
5. ✓ Example request ref exactly matched the real Candidate artifact.
6. ✓ One script invocation produced exactly 13 formal outputs.
7. ✓ Script preserved environment and rejected an existing output root.
8. ✓ README Quick Start was executed verbatim in isolated TEMP and succeeded.
9. ✓ README accurately explains architecture, result, value, and limits.
10. ✓ README has no absolute path, false capability, or approval transcript.
11. ✓ Regression is `210/210`; counts remain `11` and `7/40/7`.
12. ✓ Review records Git, hashes, example, real demo, README, and boundaries.

## 14. Final state

All approved WU6 package, verification, and Review work is complete. The
post-C4 handoff must rerun the same verifier, confirm the five-commit/eight-path
final gate, a clean worktree, remotes `0`, stashes `0`, and no push.

```text
READY_FOR_HUGIN_REVIEW
```
