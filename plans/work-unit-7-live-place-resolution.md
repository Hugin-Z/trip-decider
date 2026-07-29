# Work Unit 7 · Structured User Input + Live Place Resolution

Plan version: v0.3
Status: PENDING_HUGIN_APPROVAL
Decision: AMAP_IMPLEMENTATION_WITH_PROVIDER_STORAGE_CONFIRMATION_GATE

## 1. Objective, phase boundary, and non-goals

WU7 compiles explicit CLI input into the existing planning artifacts and implements an AMap-shaped place-resolution boundary without overstating permission to persist real AMap service data.
Stage A is the approvable offline implementation: deterministic input compilation, strict parsing, identity/matching, explicit selection, secret-safe FER, transactional output, and downstream-compatible contracts.
Stage A uses only handwritten fake transport responses and handwritten synthetic AMap-shaped values; it performs zero real provider calls and produces no real AMap output.
Synthetic values prove code behavior only; they are not AMap service data, live evidence, policy approval, or a real-world place verification.
Stage B is real AMap validation and remains gated by official written confirmation of the intended durable-storage use.
Before that confirmation: `network calls = 0` and `real AMap output files = 0`.
The sole future live provider is AMap; OSM remains historical offline regression/demo input, and Baidu remains a future independent adapter rather than a fallback.
No LLM, natural-language parsing, recommendation, rank, route, opening hours, duration, fine planning, HTML, web app, second provider, retry, or silent fallback is added.
Execution is not authorized by this Plan.

## 2. Measured baseline and supersession

- Branch/HEAD: `main` / `3d3336b96453150b952a2b83fb49c34fe0e94368`.
- Worktree contains only this untracked Plan; remotes `0`; stashes `0`; tracked changes `0`.
- Existing independent verification: `210/210` tests, `11` schemas, fixtures/documents/dirty cases `7/40/7`.
- `PLAN.md` SHA256: `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456`.
- Schema-set SHA256: `C53FAD02B5964291734994FC679C247EF3D483854A6FC8CFA3A1283559DAB762`.
- Handbook local/origin: `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`; ahead/behind `0/0`; clean after fetch.
- Reread from `origin/main`: `STATE.md`, `INDEX.md`, `SUMMARY.md`, context injection, R10, PER, Scope, and Fixture-first.
- Plan v0.2 SHA256: `0344BADA09A809E059BC7007C9A445DD5E07AB58616901F366044DEAEE9A381E`.
- v0.3 supersedes v0.2 in place; no second Plan file is created.

## 3. Preserved technical compatibility decisions

Read-only audit remains based on both Candidate schemas, Evidence Runtime, Coarse Planner, Failure Evidence, Schema validation, the OSM adapter, and WU3/WU4/WU5 tests.
`common.schema.json` accepts lower-snake provider names, provider record IDs/types, `provider_item` locators, and `GCJ-02`.
`candidates.schema.json` requires stable provider identity, location, request ref, category metadata, and Schema validity but does not require OSM identity syntax.
Evidence Runtime is provider-independent, accepts `GCJ-02`, preserves Candidate provider/location, and performs no coordinate conversion.
Coarse Planner consumes generic Candidate refs, seed accounting, record-local facts, and Evidence outputs; it does not require WGS84 or OSM fields.
The Recovery-compatible boundary remains `candidates.json`, `seed-accounting.json`, `record-local-facts.json`, and `run-summary.json`.
The AMap implementation must construct Candidate documents directly against shared contracts and must not reuse the OSM/WGS84-specific adapter.
Candidate provider metadata remains `provider.name=amap`, `record_type=poi`, official AMap POI ID, and `crs=GCJ-02`.
Preserved decision: `AMAP_LIVE_RESOLUTION_DOWNSTREAM_COMPATIBLE`.
Preserved FER decision: `AMAP_SECRET_SAFE_FER_COMPATIBLE`.
Preserved release gate: `AMAP_TERMS_CONFIRMATION_REQUIRED_BEFORE_PUBLIC_RELEASE`.
No Schema, validator, WU3, WU4, Recovery, FER, or existing test change is authorized.

## 4. Verified AMap technical API contract

Official sources already checked on 2026-07-29:
- [Web Service API overview](https://lbs.amap.com/api/webservice/summary/)
- [Create a Web Service key](https://lbs.amap.com/api/webservice/guide/create-project/get-key)
- [District query](https://lbs.amap.com/api/webservice/guide/api/district)
- [POI Search 2.0](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch)
- [Coordinate-system FAQ](https://lbs.amap.com/faq/advisory/others/39838)
- [Flow limits](https://lbs.amap.com/api/webservice/guide/tools/flowlevel), [quotas](https://lbs.amap.com/upgrade), [status codes](https://lbs.amap.com/api/web-service/tools/info), and [terms](https://lbs.amap.com/pages/terms/)
The only future live provider token is `provider: amap_web_service`.
City resolution is one `GET https://restapi.amap.com/v3/config/district`; POI resolution is one `GET https://restapi.amap.com/v5/place/text` per unique seed.
The required `key` exists only in the wire query created inside the secret-injecting transport closure.
District parameters are `keywords`, `subdistrict=0`, `page=1`, `offset=20`, `extensions=base`, and `output=JSON`.
POI parameters are `keywords`, confirmed `region`, `city_limit=true`, `langCode=zh`, `page_size=25`, `page_num=1`, and `output=json`.
Each unique `must_visit ∪ excluded` seed receives at most one request; unique seeds are capped at `8`; automatic retry, fallback, and background calls are `0`.
Official basic fields needed by the parser are POI `id`, `name`, `location`, `type`, `typecode`, address/administrative fields, and response status metadata.
Official POI `id` is provider identity; rank, result order, name, coordinates, popularity, and distance never replace it.
AMap coordinates are `GCJ-02`; no WGS84 claim, CRS guess, conversion, or cross-provider coordinate comparison is allowed.
Provider/API/transport/parse failure remains failure and is never converted to unmatched.
Technical API compatibility is verified; authorization to durably store normalized real service data is not.

## 5. Active persistence-policy blocker

The current terms restrict direct storage, caching, and detached use of service data and related content; they do not state that normalization automatically removes those restrictions.
Therefore `AMAP_PERSISTENCE_POLICY_UNRESOLVED` is active now.
`NO_PERSISTENT_RAW_PROVIDER_CACHE` remains necessary but is not sufficient to authorize durable normalized POI fields.
The earlier proposal to persist POI ID, name, type/typecode, address, adcode, coordinates, and provider observation cannot be used with real AMap data until confirmed.
The earlier normalized snapshot replay design is only a synthetic contract test until provider authorization is established.
The earlier public-release gate is later than this blocker and does not replace it.
The new mandatory gate is `AMAP_DURABLE_STORAGE_CONFIRMATION_REQUIRED_BEFORE_LIVE_EXECUTION`.
Personal free quota, a valid key, API success, and code completion are not storage authorization.
No user-defined boolean flag, environment variable, checkbox, or local acknowledgment can substitute for an official AMap answer.

## 6. Required official confirmation

An official ticket or written response must describe: a personal authenticated developer; personal study/research; and a local, self-used travel-planning tool.
It must identify Web Service District Query and POI Search 2.0, no complete raw JSON retention, no publication, and no third-party data provision.
It must ask about local persistence of the proposed minimum fields: POI ID, name, type/typecode, address summary, adcode, GCJ-02 location, request time, response SHA256, and byte count.
It must ask whether those fields may support the current plan, audit, and later local offline replay without another API request.
The six questions requiring explicit answers are:
1. May the proposed minimum normalized fields be persisted on the user's machine?
2. May they be used for later offline replay without another API call?
3. What retention period or deletion condition applies?
4. May POI names and derived planning results be displayed in static HTML?
5. What exact AMap attribution/source statement is required?
6. Is an additional technical-service licence or written authorization required?
Only a safe summary may be recorded: `confirmation_status`, `confirmation_date`, `approved_use_summary`, `retention_limit`, and `attribution_requirement`.
Plan and Review must not contain the key, account ID, name, phone, email, ticket transcript, or other private contact/account information.
No ticket text or provider-response file may be added as a seventh path.

## 7. Outcome branches after official confirmation

P1 — minimum normalized persistence allowed:
Freeze only the provider-approved field whitelist, retention limit, attribution, and deletion rules before any live request.
Only then may durable output contain `provider-observation/`, `resolution/`, `selection.json`, and `run-summary.json`.
Raw response bytes remain memory/system-temp only and are deleted in `finally`; durable output may contain only expressly authorized fields and safe hashes/metadata.
Normalized replay promises only identical approved snapshot plus identical selection produces byte-identical four-file resolution.
Phase B still requires explicit Hugin authorization after the safe official-confirmation summary and exact P1 limits are reviewable.
P2 — current-run use allowed but offline persistence forbidden:
Remove `--normalized-replay-root`, normalized snapshot replay, and long-lived `provider-observation/` for real data.
Real provider values may exist only in process/system temp and must flow in the same run through Evidence Runtime, Planner, and HTML before deletion.
Because P2 changes WU7 output and orchestration contracts, stop and submit a revised Plan for approval before implementation or live calls.
P3 — proposed use not allowed:
Set `AMAP_PROVIDER_POLICY_BLOCKED`; do not call AMap and do not switch to Baidu, Nominatim, OSM, or another provider.
An unclear, partial, expired, or scope-mismatched answer leaves `AMAP_DURABLE_STORAGE_CONFIRMATION_MISSING` active and selects no branch.

## 8. Key isolation and Failure Evidence

The sole credential source remains process environment variable `AMAP_WEB_SERVICE_KEY`.
The CLI and PowerShell wrapper expose no `--key`/`-Key`; config, prompt, stdout/stderr, logs, files, hashes, URLs, FER, Review, and HTML contain no key.
Missing/empty key would hard-fail before output or network as `AMAP_CREDENTIAL_MISSING`, but persistence authorization is checked even earlier.
FER receives canonical UTF-8 bytes for a de-keyed descriptor containing method, endpoint path, operation, and sorted non-secret parameters.
An injected transport closure reads the environment key only at the wire boundary; the key-bearing URL is never returned to FER.
Exception classes are mapped without third-party message text, headers, response excerpts, actual inputs, or wire URLs.
Synthetic tests inject a sentinel key into URL/error text and require its absence from all displayed and persisted surfaces.
Reuse `run_failure_evidenced_acquisition`; do not implement a second Failure Evidence model.

## 9. Structured input and offline implementation contract

Required CLI fields remain `--city`, `--start-at`, `--end-at`, `--input-recorded-at`, `--party-count`, one or more `--transport-mode`, one or more `--must-visit`, and `--output-root`.
Optional fields remain `--city-adcode`, repeated `--excluded`, `--interactive`, `--locale`, and the contract-only `--normalized-replay-root`.
The replay option is exercised only with synthetic snapshots in Stage A and may reach real data only under P1.
Generate deterministic UTF-8 `planning-input/request.yaml`, `constraint-parse.json`, and `constraints.yaml`; no BOM, absolute path, current-clock value, or inferred travel default is allowed.
Emit only `time_window/within`, `must_visit/include`, and optional `excluded/exclude`; `constraints.yaml` remains solver SSOT.
Validate individual artifacts and the three-document CLOSED bundle rooted at `constraints.yaml` before credential access or any future network call.
Request sequence is preserved; unique query seeds deduplicate by first occurrence, with must-visit before previously unseen excluded values.
Comparison normalization remains Unicode NFC, outer trim, and case-fold only.
One exact official-ID alternative is matched; multiple remain ambiguous; zero is unmatched; non-interactive ambiguity selects nothing.
Interactive selection accepts only a displayed Candidate ID or `0`, records `selection_source=user_explicit`, and preserves all alternatives.
Unmatched values create no placeholder; result-window/provider failures do not masquerade as unmatched.

## 10. Synthetic output and transaction boundary

Stage A may create synthetic `planning-input/`, `provider-observation/`, `resolution/`, `selection.json`, and `run-summary.json` only inside tests/system temp.
Synthetic observations may model `manifest.json`, city/seed records, and `acquisition-evidence.json` solely to exercise deterministic contracts.
They must be clearly marked `synthetic_test_data=true` and must never be described as AMap observations or live evidence.
Candidate `source_refs` use a synthetic provider-item locator in tests; production code may use a real AMap locator only after P1 authorization.
Resolution still emits exactly the audited four files and preserves Candidate/provider/category/location/source-ref bijection.
Evidence Runtime output remains candidate-local unknown evidence with `generation_allowed=false`; an API-shaped value is not direct observation or verified travel evidence.
Same-parent staging, non-existing output root, atomic final rename, rollback, exact environment restoration, and zero residue are required.
No real `provider-observation/`, real Candidate POI fields, or real normalized replay is created before the durable-storage gate passes.

## 11. Fixture-first tests and Red → Green

Add exactly six tests in `tests/test_wu7_live_place_resolution.py`; all use injected fake transport and handwritten expected values.
- AP01: deterministic planning artifacts and CLOSED bundle, with no default or LLM inference.
- AP02: key only from environment; zero network when missing; no key on any persisted/displayed surface.
- AP03: one synthetic POI becomes matched, preserves synthetic official-ID shape/`GCJ-02`, and passes Evidence Runtime.
- AP04: multiple synthetic POIs remain ambiguous; explicit selection changes only accounting.
- AP05: synthetic provider failure uses existing FER and leaves no partial success.
- AP06: synthetic normalized snapshot is deterministic under the simulated P1 contract; nonempty-root, rollback, environment, and residue gates pass.
AP06 proves deterministic implementation only and does not prove provider permission to cache real data.
Red/Green command: `.\.venv\Scripts\python.exe -m unittest tests.test_wu7_live_place_resolution -v`.
C2 Red is exactly `6` tests, `0` passed, `0` failures, and `6` explicit `NotImplementedError`; network and LLM calls are `0`.
C3 Green is `6/6`; full regression is `216/216`; schemas and fixture counts remain `11` and `7/40/7`; residue is `0`.
Unit, Green, regression, and normal verification must not call a real API.

## 12. Live smoke gate and final status

Without official persistence confirmation, the verifier records `LIVE_SMOKE_NOT_AUTHORIZED_STORAGE_POLICY_UNRESOLVED`.
This is distinct from `LIVE_SMOKE_NOT_RUN_CREDENTIAL_MISSING`; policy authorization is checked first and no key need be read when policy is unresolved.
A real smoke requires all five facts: provider policy confirmed, persistence branch selected, `AMAP_WEB_SERVICE_KEY` present, current quota available, and endpoints/documentation unchanged.
Any unmet prerequisite yields `network calls = 0` and final status `BLOCKED`.
If P1 is later authorized, the single smoke remains Shanghai/外滩 with at most one district call, one POI call, zero retry, and zero fallback.
No real response hash, POI ID, count, address, coordinate, or match cardinality is frozen in advance.
Provider failure must preserve secret-safe FER and cleanup evidence without durable unapproved provider fields.
Stage A may finish code and fake tests with final status `BLOCKED_PENDING_AMAP_STORAGE_CONFIRMATION`.
That status means implementation complete, offline tests green, live persistence not authorized, and real smoke not run.
Only authorized P1 limits, successful real smoke, FER/cleanup evidence, and every verification gate permit `READY_FOR_HUGIN_REVIEW`.
P2 requires a new approved Plan; P3 remains `AMAP_PROVIDER_POLICY_BLOCKED`.

## 13. Run, verification, scope, and commits

`scripts/run_live_place_resolution.ps1` uses project `.venv`, inherits the environment key only after policy gating, temporarily sets/restores `PYTHONPATH`, and never accepts `-Key`, installs, overwrites, or falls back globally.
`scripts/verify_wu7_live_place_resolution.ps1` checks venv/lock, protected hashes, six-path scope, tests/counts, synthetic contracts, FER secrecy, rollback, environment restoration, and residue.
Before confirmation it must prove the live transport was not invoked and must not treat offline Green as live acceptance.
The exact whitelist remains:
`plans/work-unit-7-live-place-resolution.md`;
`src/trip_decider/live_place_resolution.py`;
`tests/test_wu7_live_place_resolution.py`;
`scripts/run_live_place_resolution.ps1`;
`scripts/verify_wu7_live_place_resolution.ps1`;
`docs/reviews/work-unit-7-live-place-resolution-review.md`.
Protected: existing runtime/tests/verifiers, `schemas/`, `fixtures/`, dependencies, README, `PLAN.md`, handbook, remotes, and every seventh path.
- C0 `docs: record WU7 live place resolution plan` — approved v0.3 bytes only.
- C1 `chore: add live place resolution interface` — module stub only.
- C2 `test: add failing live place resolution cases` — AP01–AP06 Red only.
- C3 `feat: implement structured live place resolution` — module only; same command Green.
- C4 `chore: add live place resolution run and verification entries` — scripts only; no unauthorized live call.
- C5 `docs: prepare WU7 live place resolution review` — Review only; outcome-dependent final status, then stop.
No commit may add ticket correspondence; no amend, squash, reset, rebase, push, remote, or next Work Unit.

## 14. Completion determinations and blocking

1. v0.3 Plan, handbook state, baseline, and six-path scope match approval.
2. Technical endpoint, identity, GCJ-02, provider, FER, and downstream contracts remain verified.
3. `AMAP_PERSISTENCE_POLICY_UNRESOLVED` is active until an adequate official answer exists.
4. Stage A uses only synthetic data and performs zero network/LLM calls.
5. Planning artifacts are deterministic, Schema-valid, CLOSED, and preserve solver SSOT.
6. All provider identities/alternatives survive without rank, fuzzy, first-result, or cross-provider choice.
7. Secret-safe FER receives only de-keyed descriptors and no key reaches any surface.
8. Synthetic transaction/replay behavior is deterministic but is not called live evidence or authorization.
9. Red is exactly six interface errors; Green is 6/6; regression is 216/216 and 11 plus 7/40/7 remain.
10. Before confirmation, real calls/files are zero and the smoke state is the policy-unresolved token.
11. Official confirmation is summarized without personal/contact/account/transcript data.
12. P1, P2, or P3 is selected only from the official answer and its exact scope.
13. P1 live evidence is required for `READY_FOR_HUGIN_REVIEW`; otherwise status is honest and blocking.
14. Review proves Git, hashes, tests, network zero/live gate, secrets, rollback, policy, and residue, then stops.
Immediate blockers: `AMAP_PROVIDER_POLICY_BLOCKED`, `AMAP_PERSISTENCE_POLICY_UNRESOLVED`, `AMAP_DURABLE_STORAGE_CONFIRMATION_MISSING`, `AMAP_COORDINATE_CONTRACT_BLOCKED`, `AMAP_CANDIDATE_PROVIDER_CONTRACT_BLOCKED`, `AMAP_DOWNSTREAM_COMPATIBILITY_BLOCKED`, and `AMAP_SECRET_SAFE_FER_INCOMPATIBLE`.
Also stop for normalization-as-authorization, real POI persistence or smoke before confirmation, custom confirmation flags, quota-as-permission, second provider, protected/seventh path, Schema/validator/dependency changes, identity/CRS guessing, route/planner expansion, or LLM use.
Execution requires the exact instruction `批准执行 Work Unit 7 Live Place Resolution v0.3`.
