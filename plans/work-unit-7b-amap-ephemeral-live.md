# Work Unit 7B · AMap Ephemeral Live Resolution

Plan version: v0.2
Status: `PENDING_HUGIN_APPROVAL`
Decision: `AMAP_P2_EPHEMERAL_SAME_RUN_WITH_PUBLIC_PARSER`
Compatibility verdict: `READY_FOR_EXECUTE_APPROVAL`
Parser reuse verdict: `AMAP_P2_PROVIDER_NEUTRAL_PARSER_REUSE_RESOLVED`
Safe final-output verdict: `AMAP_P2_FINAL_OUTPUT_REDACTION_DESIGN_FEASIBLE`

## 1. Revision and objective

- This v0.2 supersedes v0.1 in place; it does not create a second Plan.
- Superseded v0.1 SHA256: `FBB2FA0AE8C59BE44EB8AAF6FE627301D2FAB481137E4DEE022F686449D7006B`.
- WU7B is a new Work Unit and does not rewrite WU7 or WU7R history.
- Its target is a same-run chain from explicit structured input to a safe, non-publishable coarse Plan and HTML.
- Capability is limited to real place resolution, coarse Day allocation, and explicit ambiguous/unmatched blockers.
- It does not provide route time, opening hours, activity duration, fine scheduling, recommendations, or a publishable guide.
- This Plan does not authorize Execute, provider access, credential access, code changes, or a smoke run.

## 2. Measured baseline

- Branch/HEAD: `main` / `ef439444c5d71397d05a673a4dccefbd6ed92f09`.
- Worktree contains only untracked `plans/work-unit-7b-amap-ephemeral-live.md`.
- Remotes/stashes: `0/0`.
- Regression: `220/220`; Schemas: `11`; fixture directories/documents/dirty cases: `7/40/7`.
- WU7R Decision: `PROVIDER_NEUTRAL_AMAP_PARSER_CONTRACT_REMEDIATION`.
- WU7R Review: `docs/reviews/work-unit-7r-provider-neutral-parser-contract-review.md`.
- No AMap call, Key read, LLM call, or WU7B Execute occurred during this revision.

## 3. Handbook and execution discipline

- Handbook fixed path: `<handbook>`.
- Frozen public context remains origin/main `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`, ahead/behind `0/0`.
- R10 requires hard failure for policy, parse, redaction, cleanup, Schema, or secret-boundary violations.
- PER requires Hugin approval of this exact Plan before C0 and one Review after C5.
- Scope permits only the six frozen paths and prohibits opportunistic changes.
- Fixture-first requires the six fake-transport cases to fail at explicit public stubs before implementation.
- Counts, hashes, calls, residue, and completion statements must come from commands, not inference.

## 4. Public parser compatibility decision

- WU7R now publicly exports `AmapObservationMode`.
- It publicly exports `parse_amap_district_response` and `parse_amap_poi_response`.
- It publicly exports `bind_amap_observation_policy` and `project_amap_candidates`.
- `AmapObservationMode.EPHEMERAL_LIVE` requires no synthetic marker and binds the existing ephemeral policy.
- Its controlled values expose no file writer, snapshot, replay, serializer, or output-root capability.
- Synthetic and ephemeral observations share one parser and Candidate projection implementation.
- WU7B will call only these public interfaces; it will not import a private helper or copy parsing/projection logic.
- WU7B will not modify `live_place_resolution.py`.
- Therefore the v0.1 blocker is resolved as `AMAP_P2_PROVIDER_NEUTRAL_PARSER_REUSE_RESOLVED`.
- Any later need for a private helper, second parser, or WU7R edit stops as `AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED`.

## 5. Approved design chain

- Validate explicit structured input and compile the three planning-input artifacts.
- Validate that planning-input bundle CLOSED with `constraints.yaml` as its explicit root.
- Validate output-root safety and create one random system-temp run root.
- Read `AMAP_WEB_SERVICE_KEY` only inside the live wire closure.
- Call AMap District once and POI Search 2.0 once per unique seed within budget.
- Parse through the public pure parsers and bind every response as `EPHEMERAL_LIVE`.
- Project all identities through the shared public Candidate projector.
- Materialize exact temporary Recovery-compatible artifacts from the public projection.
- Run Evidence Runtime and Coarse Planner against explicit system-temp roots.
- Validate the temporary Planner output with its explicitly supplied CLOSED artifact sets.
- Translate provider-derived references to safe final-output references.
- Artifact-only validate the redacted final Plan and Violations; do not claim the nine-file tree is CLOSED.
- Render escaping-only HTML from the safe view and atomically install exactly nine final files.
- Delete raw, parsed, Candidate, Recovery, Evidence, FER, mapping, and temporary summaries in `finally`.

## 6. Temporary Recovery/Evidence/Planner boundary

- Temporary Recovery root is exactly `candidates.json`, `seed-accounting.json`, `record-local-facts.json`, and `run-summary.json`.
- The new module may serialize the public `AmapCandidateProjection`; it may not re-normalize through OSM Recovery code.
- Candidate IDs, provider facts, coordinates, addresses, categories, locators, and source references remain temporary.
- Recovery-compatible hashes and counts are computed mechanically and validated before Evidence Runtime.
- Its network count is stage-local downstream handoff `0`; top-level final summary records actual live transport calls.
- Evidence Runtime runs unchanged in system-temp and retains its honest unknown/rule-derived support ceiling.
- Ambiguous and unmatched state comes only from shared seed accounting; it is not invented as an Evidence fact.
- Coarse Planner runs unchanged from explicit Recovery, Evidence, and planning-input roots.
- Planner temporary Plan and Violations receive their explicit full artifact collections for CLOSED validation.
- No directory scan, “latest” selection, fallback artifact, or synthetic replay is allowed.

## 7. Safe-ID projection

- Provider Candidate identity and final-output safe identity are distinct types and namespaces.
- Provider Candidate identity may contain AMap POI ID, address, type/typecode, adcode, GCJ-02, and provider locator only temporarily.
- A safe Candidate ID derives only from request artifact identity, the exact user seed, and its alternative ordinal.
- Alternative ordinals follow the shared projector’s complete alternative order; no label/category/location deduplication occurs.
- Safe auxiliary refs derive only from the same safe tuple plus a fixed contract-owned reference kind or fact-slot ordinal.
- No safe ID or final hash input may include provider ID, address, coordinates, category, response hash, or provider Candidate hash.
- The provider-to-safe map exists only in memory or system-temp and is deleted in `finally`.
- Projection asserts a bijection: every temporary provider Candidate gets one safe ID and no two identities merge.
- It preserves seed order, alternative cardinality, matched/ambiguous/unmatched, blockers, and explicit current-run selection.
- It cannot upgrade Evidence support, `generation_allowed`, feasibility, or publishability.
- Safe IDs are deterministic only for the current request and observed alternative order, not stable provider identities.

## 8. Schema and final-reference boundary

- Temporary Plan/Violations remain CLOSED-valid before redaction and cleanup.
- Redacted `plan.json` and `violations.json` retain all required shapes and are individually Schema-valid.
- Required Candidate/Evidence artifact refs become safe logical refs; their IDs and integrity hashes use safe-only surrogate manifests.
- Activity Candidate refs, proof/evidence refs, plan refs, provenance parents, and payload hashes are rewritten consistently.
- `planning-gate.json` and planning `run-summary.json` are safe projections, not the raw Planner control documents.
- Final safe logical refs intentionally have no persisted Candidate/Evidence artifacts.
- Therefore final output is not represented as a CLOSED bundle and the verifier must reject any such overclaim.
- If Schema validity requires a provider-derived value or a persisted upstream provider artifact, stop as `AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED`.

## 9. Exact final output and redaction

- Final output contains exactly nine files:
- `planning-input/request.yaml`
- `planning-input/constraint-parse.json`
- `planning-input/constraints.yaml`
- `planning/plan.json`
- `planning/planning-gate.json`
- `planning/violations.json`
- `planning/run-summary.json`
- `report/index.html`
- `run-summary.json`
- Planning-input contains only explicit user input plus contract metadata derived from that input.
- Final output may retain user place names, Day assignment, matched/ambiguous/unmatched, and explicit-selection fact.
- It may retain `conditionally_feasible`, `publishable=false`, `generation_allowed_input=false`, call/cleanup counts, and source `高德地图`.
- It must not retain provider-observation, Recovery, Evidence, mapping, raw/normalized data, provider facts, or temp paths.
- It must not retain AMap POI ID, address, coordinates, category, typecode, adcode, response hash, or provider Candidate artifact.
- A recursive scanner compares every final scalar with the collected sensitive provider-value set before install.
- Any exact forbidden value, provider-derived ref, or forbidden field name stops as `AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED`.

## 10. Safe HTML

- Existing private HTML renderer is not reused because it can expose Candidate references.
- `amap_ephemeral_live.py` may implement a minimal escaping-only renderer over the safe final view.
- HTML may show user name, Day, unresolved blocker, conditional/non-publishable state, call count, cleanup, and AMap attribution.
- It must not show Candidate/POI IDs, alternative details, address, coordinates, category/typecode, artifact hash, or response metadata.
- Interactive candidate summaries are terminal-only and are never redirected into final files.
- Rendering cannot change planning semantics, select an identity, or raise Evidence support.

## 11. Credential, transport, and FER

- The sole credential source is current-process `AMAP_WEB_SERVICE_KEY`; CLI, config, prompt, and persistence are prohibited.
- Missing/empty credential returns `AMAP_CREDENTIAL_MISSING` before any network attempt.
- The Key is injected only by the wire closure and never enters descriptors, hashes, URL records, FER, logs, errors, files, Review, or HTML.
- Only GET `https://restapi.amap.com/v3/config/district` and GET `https://restapi.amap.com/v5/place/text` are allowed.
- District budget is `1`; POI budget is `1` per unique seed; unique seed maximum is `8`.
- Retry, fallback, second provider, background request, and LLM call budgets are all `0`.
- Confirmed district adcode and strict city limit are mandatory for POI requests.
- HTTP, transport, API-status, parse, and result-window failures remain failures, never unmatched.
- Failure acquisition reuses public `run_failure_evidenced_acquisition`; no second FER implementation is allowed.
- FER receives only a de-keyed descriptor, remains temporary, and exposes only safe class/status/counts after cleanup.

## 12. Ephemeral cleanup and atomicity

- Real AMap bytes and parsed values may exist only in process memory or a random system-temp run root.
- Success and failure both delete raw bytes, parsed values, Candidates, Recovery, Evidence, mapping, FER, and temporary summaries.
- Cleanup runs in `finally`; raw provider, normalized provider, and temporary residue targets are each `0`.
- Cleanup evidence retains only counts, safe status tokens, and resource kinds, never provider values or secret-bearing paths.
- Cleanup failure returns `AMAP_P2_CLEANUP_FAILED` and prohibits final-output installation.
- Nonempty output root is rejected; partial output is rolled back; final install is atomic.

## 13. Fixture-first and Red → Green

- C2 adds exactly P201-P206 using handwritten provider-shaped fake data with `AmapObservationMode.EPHEMERAL_LIVE`.
- P201: deterministic planning-input artifacts and explicit CLOSED validation.
- P202: pre-network credential failure and sentinel-Key absence from every observable channel.
- P203: public parser/projector → temporary Recovery/Evidence/Planner → safe nine-file projection.
- P204: multiple identities remain ambiguous; explicit selection is run-local; no provider identity persists.
- P205: HTTP/API/parse/window failures use FER; no partial final output or residue remains.
- P206: safe Plan/HTML, recursive redaction, nonempty-root refusal, environment restoration, and cleanup-fault failure.
- Fake tests must not invoke the synthetic wrapper, private helpers, real credential reads, network, or LLM.
- C2 command: `.\.venv\Scripts\python.exe -m unittest tests.test_wu7b_amap_ephemeral_live -v`.
- C2 target: `6` tests, `0` pass, `0` failure, `6` explicit `NotImplementedError`.
- C2 counters: network `0`, credential reads `0`, LLM `0`.
- C3 uses the character-identical command and reaches `6/6`.
- Protected WU7R/WU7 suites remain `4/4` and `6/6`.
- Full regression target is `226/226`; Schemas `11`; fixtures/documents/dirty cases `7/40/7`.
- Offline network calls, LLM calls, and temporary residue are each `0`.

## 14. One real smoke in Execute verifier

- Only the approved C4 verifier may run one real smoke after fake Green, regression, secret, cleanup, and scope gates pass.
- Smoke input is city `上海市`, city-adcode `310000`, seed `外滩`.
- It permits at most one District GET and one POI GET, with retry/fallback `0`.
- It must not freeze POI IDs, response hashes, coordinates, addresses, result counts, Candidate counts, or match status.
- Ambiguous is a valid live parsing result but cannot trigger automatic selection.
- Success proves calls `<=2`, final files `9`, Key leakage `0`, provider persistence `0`, all residue `0`, and LLM `0`.
- Provider or credential failure remains a hard failure with safe temporary FER and zero final output.

## 15. Scope and commit sequence

- Exact six-path whitelist:
- `plans/work-unit-7b-amap-ephemeral-live.md`
- `src/trip_decider/amap_ephemeral_live.py`
- `tests/test_wu7b_amap_ephemeral_live.py`
- `scripts/run_amap_ephemeral_live.ps1`
- `scripts/verify_wu7b_amap_ephemeral_live.ps1`
- `docs/reviews/work-unit-7b-amap-ephemeral-live-review.md`
- Protected: WU7R/WU7 files, `live_place_resolution.py`, Evidence Runtime, Coarse Planner, Recovery, FER, Schemas, fixtures, dependencies, README, `PLAN.md`, handbook, and historical verifiers.
- C0 `docs: record WU7B AMap ephemeral live plan`
- C1 `chore: add AMap ephemeral live interface`
- C2 `test: add failing AMap ephemeral live cases`
- C3 `feat: implement AMap ephemeral same-run resolution`
- C4 `chore: add AMap ephemeral run and verification entries`
- C5 `docs: prepare WU7B AMap ephemeral live review`
- No amend, squash, reset, rebase, push, remote creation, or scope expansion is authorized.

## 16. Completion and blocking

- Completion requires the exact six commits, `226/226`, `11`, `7/40/7`, fake gates, and the single bounded smoke.
- It requires nine final files, Schema-valid safe Plan/Violations, no false CLOSED claim, and recursive redaction Green.
- It requires actual network calls `<=2` only in smoke, Key leakage `0`, provider persistence `0`, all residue `0`, and LLM `0`.
- It requires no protected-path change and independently reviewable hashes, call counts, cleanup, scope, and secret scans.
- Immediate tokens: `AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED`, `AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED`, `AMAP_CREDENTIAL_MISSING`, `AMAP_PROVIDER_FAILURE`, `AMAP_P2_CLEANUP_FAILED`.
- Stop for private-helper need, second parser, WU7R/Schema/Planner/Evidence change, unsafe ID, forbidden final value, Key exposure, or unverifiable cleanup.
- Stop for a seventh path, dependency, retry, fallback, second provider, route logic, opening hours, duration, fine Planner, or capability overclaim.
- Key absence is not a current Plan-stage blocker and was not read or tested in this revision.
- Current compatibility verdict is `READY_FOR_EXECUTE_APPROVAL`; this is readiness for Hugin review, not Execute authorization.
- Await exact approval: `批准执行 Work Unit 7B AMap Ephemeral Live Resolution v0.2`.
