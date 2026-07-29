# Work Unit 6 · Portfolio Packaging + Reproducible Demo

Plan version: v0.1
Status: PENDING_HUGIN_APPROVAL
Decision: PACKAGE_APPROVED_MVP_WITHOUT_NEW_CAPABILITY

## 1. Objective and execution model

WU6 packages the approved offline E2E as a public-facing portfolio project: one root README, one committed three-artifact planning example, and one PowerShell demo entry.
It adds no product capability and follows `Package → Verify → Review`; manufacturing a Red/`NotImplementedError` phase would not test a new interface.
The package must explain that identity and evidence gates precede planning, then reproduce the existing conditional two-day result without network or LLM use.
It must not change runtime, renderer, Schema, validator, fixture, test, dependency, architecture, recommendation, route, map, or discovery behavior.

## 2. Measured baseline and handbook

- Branch/HEAD: `main` / `91ee1a0c7c29a9ac03a270d35ad5ea983ea86ce7`.
- Worktree clean; remotes `0`; stashes `0`; Python `3.11.9`.
- Existing verification: `210/210` tests, `11` schemas, fixtures/documents/dirty cases `7/40/7`.
- Existing E2E: `13` output files; network attempts `0`; LLM calls `0`; temporary residue `0`.
- `README.md` exists but describes the old WU0 bootstrap and must be replaced, not appended to.
- `.gitignore` does not reserve a generic repository `demo-output/`; all generated demo output therefore remains caller-selected and outside the repository.
- Handbook local/origin HEAD is `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`, ahead/behind `0/0`, clean.
- Rules reread from `origin/main`: `STATE.md`, `INDEX.md`, `SUMMARY.md`, context injection, R10, PER, Scope, and Fixture-first.
- R10 requires measured claims and explicit limitations; PER requires approval before C0; Scope fixes eight paths; fixture discipline forbids deriving expected input from planner output.

## 3. Example input source and exact contract

Create `examples/wuyuan-two-day/` only during C1, using the deterministic, independently authored two-day bundle in `tests/test_wu4_coarse_planner.py`.
Do not call Planner to generate it, infer it from `plan.json`, introduce random IDs/current time, or add machine paths.
The example is a public demo input, not a test fixture, real user request, recommendation, or complete travel guide.
It expresses a two-day window and `must_visit = [江岭, 李坑, 篁岭, 庆源]`; `constraints.yaml` remains the only solver SSOT.

| File | Artifact ID | Payload SHA256 | Preregistered file SHA256 |
| --- | --- | --- | --- |
| `request.yaml` | `urn:uuid:20000001-0000-4000-8000-000000000001` | `B49538AA6AEA6526E4154E7AA18053EC343C3C5FA7A2436BDFB4F43143593823` | `EE1E8BAEF43868757FE8A7B4BB4A3C0148C4FB81241C2D91DF23E26A6D4F23F1` |
| `constraint-parse.json` | `urn:uuid:72a359c8-bb4b-49d1-aeae-59e649fab048` | `5CC8D256F6F0A57C79210D1BCDB68C9508B2FB6CB8B220E7374EFD82A87F385C` | `DF5B1D9809E628CD1B1B8F7D3056D11E03691EB654C89420549DDB57E0F69898` |
| `constraints.yaml` | `urn:uuid:93d97ccf-c2ce-4c63-9db5-2722024705a8` | `EC577FABA1241B7A1FED1FEB3BFCFBCB7C03FAB4577AD82AF1CC2517DB00E065` | `769BFC565DBBD0BDA555AA0F91DCD97A272F34CF696B71321DA868B688C51EC2` |

The constraints artifact is the explicit CLOSED root and the reachable bundle contains exactly these three artifacts.
The request ref must equal the committed Candidate artifact ref in artifact ID, artifact type `request`, schema version `0.1.0`, and payload SHA256.
All three files must independently pass the existing Schema registry, use UTF-8 without BOM, contain no absolute path, and remain byte-stable across two reads.
They add no default time, route, distance, duration, or natural-language parsing dependency.

## 4. Demo script contract

Create `scripts/run_wuyuan_demo.ps1` with mandatory `[string]$OutputRoot` and optional `[switch]$OpenReport`.
Resolve the repository from the script location and require `<repo>\.venv\Scripts\python.exe`; do not fall back to global Python or install the project.
Invoke the existing module with the committed anchor, example directory, and caller output root:
`python -m trip_decider.e2e_demo --anchor-root fixtures/jiangxi_multi_identity_smoke --planning-input-root examples/wuyuan-two-day --output-root <OutputRoot>`.
Save the prior `PYTHONPATH`, set it to `<repo>\src` only around the child process, and restore absence or the exact prior value in `finally`.
Require an explicit output root that does not exist and whose parent exists; never choose a repository default, delete an existing path, or hide cleanup.
Stream the child’s safe stdout/stderr and preserve its nonzero exit code; do not downgrade failures to warnings or expose raw provider data, coordinates, full JSON, or secrets.
The measured success line remains `status=conditionally_feasible scheduled=2 blocked=2 publishable=false report=report/index.html`.
With `-OpenReport`, call `Start-Process` only after exit `0` and existence of `report/index.html`; verification never enables this switch.

## 5. README information architecture

Replace the root README for GitHub visitors, AI product/engineering interviewers, and local demo users; do not retain internal approval history.
Use the title `trip-decider` and describe an auditable travel-decision prototype centered on evidence boundaries and constraint contracts.
State plainly that the system first decides what facts and identities may enter planning instead of asking an LLM to invent an itinerary.
Show the measured demo: Day 1 江岭, Day 2 李坑, 篁岭 identity ambiguity, 庆源 unmatched, conditional draft, `publishable=false`.
Explain failure modes addressed: silent identity choice, unsupported certainty, unjustified feasibility, and conflating `no_plan_found` with `proven_infeasible`.
Include one Mermaid or text architecture: real OSM anchor → Offline Recovery → Evidence Runtime → Constraint Projection → Coarse Planner → static HTML.
Give one sentence per stage and 5–7 engineering traits: contracts, replay, identity retention, orthogonal evidence, solver SSOT, rollback/determinism, offline reproducibility.
Quick Start must use Python `>=3.11,<3.12`, Windows PowerShell, standard `venv`, and `requirements.lock`; it must not reference a nonexistent installer.
Environment preparation may show `py -3.11 -m venv .venv` and `.\.venv\Scripts\python.exe -m pip install --requirement .\requirements.lock`.
The runnable block visibly removes only `$demoRoot = Join-Path $env:TEMP 'trip-decider-wuyuan-demo'`, then invokes the demo script with `-OpenReport`.
Explain the 13-file tree, emphasizing the report, plan, planning gate, evidence, candidates, and top-level summary without duplicating their schemas.
Link only to existing repository-relative targets and describe only `src/trip_decider/`, `schemas/`, `fixtures/`, `examples/`, `scripts/`, and `docs/reviews/`.
State boundaries: non-production; one committed real anchor; evidence ceiling unknown; no route, hours, duration, map, hotel, weather, cost, or recommendation; ambiguity needs confirmation.
Measured status may state `210` tests, `11` schemas, `7/40/7`, and demo network/LLM `0/0` only after Execute remeasures them.
No badges, screenshots, external assets, absolute paths, “best route”, arbitrary-city support, verified-source claim, or detailed Work Unit narrative.

## 6. Verification entry and real run

Create `scripts/verify_wu6_portfolio_packaging.ps1`; use the project venv and system temp, with cleanup and environment restoration in `finally`.
It must independently perform these 20 checks and fail deterministically on any mismatch:
1. Prove project venv executable/prefix/site-packages, exact lock inventory, and `pip check`.
2. Verify the Hugin-approved WU6 Plan SHA256.
3. Enforce exactly the eight WU6 paths.
4. Enforce the exact ordered five-commit prefix.
5. Verify all 11 existing Schema hashes.
6. Verify frozen `PLAN.md`, runtime, fixture, and dependency hashes.
7. Audit README existence, UTF-8 without BOM, and absence of absolute paths.
8. Resolve every README repository-relative file link.
9. Load all three example files and validate Schema plus explicit-root CLOSED closure.
10. Compare the example request ref with the Candidate artifact exactly.
11. Invoke `run_wuyuan_demo.ps1` against a missing system-temp output root.
12. Require demo exit `0` and the exact safe E2E result line.
13. Require exactly the approved 13 output paths.
14. Check HTML for 江岭, 李坑, 篁岭, 庆源, and conditional/non-publishable boundary text.
15. Reject prohibited HTML capability claims and external resource dependencies.
16. Require top-level summary network/LLM calls `0/0`.
17. Run full discovery and require measured `210/210`.
18. Require schemas and fixtures/documents/dirty cases `11` and `7/40/7`.
19. Require zero repository/system-temp residue after `finally`.
20. Prove the caller’s original `PYTHONPATH` is restored after success and injected failure.

The verifier must not create repository outputs, invoke `-OpenReport`, call network/LLM, mutate examples, or weaken historical gates.

## 7. Exact scope

The complete indivisible whitelist is exactly:
`plans/work-unit-6-portfolio-packaging.md`;
`README.md`;
`examples/wuyuan-two-day/request.yaml`;
`examples/wuyuan-two-day/constraint-parse.json`;
`examples/wuyuan-two-day/constraints.yaml`;
`scripts/run_wuyuan_demo.ps1`;
`scripts/verify_wu6_portfolio_packaging.ps1`;
`docs/reviews/work-unit-6-portfolio-packaging-review.md`.
Protected: `src/`, `schemas/`, `fixtures/`, `tests/`, dependencies, `pyproject.toml`, `PLAN.md`, handbook, historical verifiers, and every ninth path.

## 8. Linear commits

- C0 `docs: record WU6 portfolio packaging plan` — approved Plan only; verify approved bytes/hash and clean baseline.
- C1 `feat: add reproducible Wuyuan demo package` — three examples plus run script; validate bundle/ref and execute the script successfully.
- C2 `docs: add portfolio README` — README only; copy-run Quick Start and audit claims/links against measured output.
- C3 `chore: add portfolio packaging verification` — verifier only; run all 20 checks and the full `210/210` regression.
- C4 `docs: prepare WU6 portfolio packaging review` — Review only; rerun the same verifier, then stop.
No amend, squash, reset, rebase, push, remote creation, or next Work Unit.

## 9. Twelve completion determinations

1. Starting HEAD, branch, worktree, remotes, and stashes match the approved baseline.
2. Approved Plan bytes and SHA256 remain unchanged after C0.
3. The final diff contains exactly the eight approved paths.
4. The example bundle passes individual Schema and CLOSED validation.
5. Its request ref exactly matches the real Candidate artifact.
6. One script invocation on a clean root produces exactly 13 formal outputs.
7. The script preserves user environment and never overwrites an existing root.
8. README Quick Start is copied verbatim and succeeds.
9. README accurately explains architecture, result, value, and limits.
10. README contains no absolute path, false capability, or internal approval transcript.
11. Regression is `210/210`; Schema/fixture counts remain `11` and `7/40/7`.
12. Review records Git, hashes, example validation, real demo, README audit, and boundaries, then stops.

## 10. Blocking

Stop if the request ref does not match, the example changes approved WU5 semantics, Quick Start cannot run from a clean checkout, or verification needs runtime/Schema/fixture/test/dependency changes.
Also stop for network/LLM need, project installation or `pyproject.toml` change, external asset/screenshot need, a ninth path, secret risk, or any claim beyond measured capability.
Typos, Markdown/Mermaid, PowerShell encoding/line wrapping, example serialization, mechanical hashes, verifier import paths, exact commit-prefix synchronization, and relative links may be corrected only inside the eight paths and recorded in Review.
Execution is not authorized until the exact instruction `批准执行 Work Unit 6 Portfolio Packaging`.
