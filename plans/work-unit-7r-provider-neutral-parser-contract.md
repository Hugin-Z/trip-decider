# Work Unit 7R · Provider-Neutral AMap Parser Contract Remediation

Plan version: `v0.1`
Status: `PENDING_HUGIN_APPROVAL`
Decision: `PROVIDER_NEUTRAL_AMAP_PARSER_CONTRACT_REMEDIATION`
Prepared: 2026-07-29

## 1. Objective and non-goals

WU7R removes the contract blocker that prevented WU7B from reusing the approved AMap-shaped parser honestly.
It exposes one public pure parsing path and one shared Candidate projection path, with an explicit closed observation mode.
Existing WU7 Stage A public functions and persisted bytes remain compatible.
It does not implement HTTP, Key access, live requests, P2 orchestration, Planner, HTML, routes, opening hours, another provider, durable live data, live snapshots, or a live smoke.
WU7B remains `BLOCKED_BEFORE_EXECUTE`; this Plan does not authorize it.

## 2. Measured baseline

- Repository: `main` at `5754c1b7117f4dd1604a7529df61ffc5ad2d595c`.
- Worktree: only `?? plans/work-unit-7b-amap-ephemeral-live.md`.
- WU7B Plan SHA256: `FBB2FA0AE8C59BE44EB8AAF6FE627301D2FAB481137E4DEE022F686449D7006B`.
- Remotes/stashes: `0/0`.
- Project `.venv` rerun: AP01-AP06 `6/6`; full regression `216/216`.
- Schemas: `11`; fixtures/documents/dirty cases: `7/40/7`.
- WU7 runtime SHA256: `34E7A01CD0FBA5EC50F24BFF872226F5D9E4E9021B646F3019AC93443FDB04C1`.
- WU7 test SHA256: `443905617A067838C9BED34B63308F8F23403A373425E4FE53BEA523840A0962`.
- WU7 Review SHA256: `42E9902CD8FC8EF6901E990CC9FF7D88002C1358B9DEBC05CD62C89B3148A50E`.
- `common.schema.json`: `A9134A705C67CF955228A28844AA2C5C42812AA2E0167E1256DB72F0ACAC36D7`.
- `candidates.schema.json`: `3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2`.
One Plan-stage handbook fetch occurred despite the no-network instruction.
It changed no repository/handbook bytes, made no provider/API call, and read no AMap Key or credential.
Execute must perform zero network calls; the deviation remains explicit in Plan and Review.

## 3. Handbook context

Fixed path: `<handbook>`.
Local/origin: `6502e423ad2a1ab30db7f805e8ebc8fb31fc500b`; ahead/behind `0/0`; worktree clean before and after.
Loaded from `origin/main`: `STATE.md`, `INDEX.md`, `SUMMARY.md`, `tools/context-injection.md`, R10, PER, Scope, and Fixture-first.
R10 requires malformed shape, policy mismatch, and unsupported mode to hard-fail without defaults or inferred provenance.
PER separates this Plan from Execute and Review; Scope confines all repository changes to five paths.
Fixture-first requires four handwritten deterministic cases to fail at explicit stubs before implementation.

## 4. Read-only contract audit

`_require_synthetic_response`, `_resolve_city`, `_coordinates`, and POI shape checks are private provider-shape parsing boundaries.
`_normalized_text` implements Unicode NFC, outer trim, and case-fold.
`_candidate_from_poi` combines provider identity projection with synthetic policy and `synthetic-amap:poi:<id>` locator construction.
`_resolution_documents` combines exact matching, alternatives, matched/ambiguous/unmatched accounting, and explicit selection.
`_snapshot_document`, `_manifest_document`, `_prepare_and_install`, and replay are synthetic persistence boundaries, not parser duties.
AP01 depends on deterministic planning artifacts and CLOSED validation.
AP02 depends on no Key access/leak and de-keyed descriptors.
AP03 depends on `amap`/`poi`, provider ID, GCJ-02, synthetic policy, unknown Evidence, and zero network.
AP04 depends on all alternatives, explicit selection, and Candidate bytes independent of selection.
AP05 depends on FER failure evidence with no partial success.
AP06 depends on byte-identical synthetic replay and transactionality.
Evidence Runtime consumes Candidate/local-fact structure and keeps support/display/freshness unknown; it needs no change.
The Candidate Schema already accepts synthetic fixture and temporary commercial capture policies; it needs no change.
Verdict: modifying only `live_place_resolution.py` can close the contract gap.

## 5. Frozen public contract

Add closed enum `AmapObservationMode` with exactly `SYNTHETIC_TEST = "synthetic_test"` and `EPHEMERAL_LIVE = "ephemeral_live"`.
String coercion, a default mode, unknown members, and mode inference are forbidden.
Add immutable controlled values: `ParsedAmapDistrict`, `ParsedAmapPoi`, `ParsedAmapDistrictResponse`, `ParsedAmapPoiResponse`, `PolicyBoundAmapObservation`, and `AmapCandidateProjection`.
These values contain copied scalar/tuple data, never caller-owned mutable mappings.

Public pure functions are `parse_amap_district_response(response)` and `parse_amap_poi_response(response)`.
Each accepts bytes or a decoded mapping, validates status/infocode and the relevant AMap shape, and returns controlled parsed values.
They perform no policy choice, network, Key access, file access, persistence, snapshot, Candidate construction, or selection.

Public policy function is `bind_amap_observation_policy(parsed, *, mode, policy_checked_at)`.
The keyword-only mode has no default and must be the closed enum.
Synthetic mode requires `synthetic_test_data is True`.
Ephemeral mode rejects `synthetic_test_data is True`; absence is accepted and no marker is added.
Either mismatch returns stable `OBSERVATION_POLICY_MISMATCH`.
Mode maps internally to sealed policy and locator strategies.
Synthetic preserves the existing policy and `synthetic-amap:poi:<provider-id>` locator exactly.
Ephemeral maps to existing temporary commercial capture policy, `replay_allowed=false`, `fixture_allowed=false`, and a current-run ephemeral provider-item locator.
Callers cannot supply policy fields, locator prefixes, persistence flags, or provenance strings.

Public projection function is `project_amap_candidates(*, city, city_adcode, seeds, district, poi_by_seed, selection_reader)`.
District and POI inputs must already be policy-bound to the same mode; mixed-mode inputs hard-fail.
One implementation owns NFC/trim/case-fold, exact matching, provider ID identity, `amap`/`poi`, GCJ-02, deterministic Candidate IDs, all alternatives, three identity states, and explicit selection.
It returns immutable in-memory Candidate/local-fact/accounting/selection values with no Path, writer, serializer, snapshot, or replay method.

Existing `run_synthetic_live_place_resolution` and `replay_synthetic_normalized_snapshot` remain public.
They bind `SYNTHETIC_TEST`, call the shared parser/projector, and retain existing serializers, FER, snapshot, replay, atomic install, and errors.
No public ephemeral function can reach those persistence functions.

## 6. Backward-compatibility gate

AP01-AP06 are protected and must remain byte/semantics compatible.
A pre-refactor deterministic run with seeds `景点甲` and `未匹配` produced 12 files.
Its tree SHA256 is `7319F394CB7CDCD5060EC9E9A3D9B6756E78C1E4A68D9C87578AAFD15CCD7EE5`.
The tree algorithm frames each relative UTF-8 path and file bytes with an eight-byte big-endian length.
Its `resolution/candidates.json` SHA256 is `608A5FA4659F9375FFAAEED17DDEFE1EE361F74135FF781D2CD5F17EF2262324`.
PN01 and the verifier use these Plan-stage pre-registered values, never new implementation output fed back as expected.
Any mismatch stops as `WU7_SYNTHETIC_BACKWARD_COMPATIBILITY_BLOCKED`.

## 7. Fixture-first cases

Create exactly four cases in `tests/test_wu7r_provider_neutral_parser_contract.py`.
PN01 checks public synthetic projection, wrapper semantics, 12-file tree hash, Candidate hash, markers, policy, and selection independence.
PN02 checks marker-free ephemeral parsing/projection, temporary policy, in-memory-only values, no persistence surface, no file, and no residue.
PN03 checks synthetic missing/false markers and live true markers all return `OBSERVATION_POLICY_MISMATCH`, without correction or inference.
PN04 checks both modes share normalization, exact matching, identity, GCJ-02, alternatives, selection, and forbidden-import/Key rules.
All inputs and expected fields are handwritten deterministic transformations; they are not real anchors and prove no live behavior.

## 8. Red → Green commands and gates

C1 leaves existing `216/216` green and exposes only types/signatures plus explicit `NotImplementedError` stubs.
C2 command:
`.\.venv\Scripts\python.exe -m unittest tests.test_wu7r_provider_neutral_parser_contract -v`
must report exactly `4 tests / 0 passed / 0 failures / 4 errors`, all approved stubs; network/LLM `0/0`.
C3 uses the character-identical command for `4/4` green.
Then `.\.venv\Scripts\python.exe -m unittest tests.test_wu7_live_place_resolution -v` must be `6/6`.
The frozen full module list must report `220/220`, 11 schemas, `7/40/7`, network/credential/LLM `0/0/0`, and residue `0`.

## 9. Scope and preserved WU7B Plan

The exact five repository paths are:
1. `plans/work-unit-7r-provider-neutral-parser-contract.md`;
2. `src/trip_decider/live_place_resolution.py`;
3. `tests/test_wu7r_provider_neutral_parser_contract.py`;
4. `scripts/verify_wu7r_provider_neutral_parser_contract.ps1`;
5. `docs/reviews/work-unit-7r-provider-neutral-parser-contract-review.md`.
Protected: WU7 Plan/Review, WU7B Plan, existing tests, schemas, fixtures, Evidence Runtime, FER, Planner, E2E, dependencies, README, `PLAN.md`, handbook, and historical verifiers.
Before Execute, preserve WU7B in place rather than moving or committing it.
The start gate rehashes it, permits only its exact pre-existing untracked status plus the approved WU7R Plan, and stages C0 by explicit path.
The verifier may exempt only that exact path after exact-hash verification and rejects every other out-of-scope change.
Review reports the expected remaining untracked WU7B Plan honestly.

## 10. Linear commit sequence

- C0 `docs: record WU7R provider-neutral parser plan` — Plan only.
- C1 `chore: add provider-neutral parser contract interface` — runtime only.
- C2 `test: add failing provider-neutral parser cases` — new test only.
- C3 `refactor: implement provider-neutral parser contract` — runtime only.
- C4 `chore: add provider-neutral parser verification` — verifier only.
- C5 `docs: prepare WU7R provider-neutral parser review` — Review only.
No amend, squash, reset, rebase, push, remote creation, or WU7B execution.

## 11. Verification entry

`scripts/verify_wu7r_provider_neutral_parser_contract.ps1` performs exactly 15 gates:
1. project `.venv`, exact lock, and `pip check`;
2. approved Plan hash;
3. five-path diff and exact commit prefix;
4. protected hashes and exact WU7B exemption;
5. four new tests;
6. AP01-AP06;
7. full 220 tests;
8. 12-file/tree/Candidate compatibility;
9. ephemeral no-file/no-snapshot/no-replay behavior;
10. policy mismatch hard failures;
11. no HTTP/socket/network import;
12. no `AMAP_WEB_SERVICE_KEY` read;
13. one shared parser/projector;
14. 11 schemas and `7/40/7`;
15. zero residue.
Every gate hard-fails nonzero; no warning-as-pass or global Python fallback.

## 12. Completion determinations (exactly 16)

1. Approved Plan hash and start baseline match.
2. WU7B Plan hash and bytes remain unchanged and uncommitted.
3. Pure district and POI parsing public interfaces exist.
4. Observation mode is explicit, closed, and has no default.
5. Policy mismatch produces the stable required problem.
6. Policy, locator, persistence, and provenance cannot be caller-forged.
7. Ephemeral projection has no durable, snapshot, or replay capability.
8. One projection core owns normalization, identity, matching, and selection.
9. Existing public synthetic run and replay functions remain available.
10. AP01-AP06 and pre-registered bytes remain compatible.
11. C2 Red is exactly four approved interface errors.
12. C3 Green is 4/4 and original WU7 is 6/6.
13. Full regression is 220/220; counts remain 11 and `7/40/7`.
14. Network, credential, LLM, and temporary residue counts are zero.
15. Scope is exactly five paths with protected hashes unchanged.
16. Review evidence independently supports the final status.

## 13. Blocking

Stop for a second parser, Schema/existing-test/dependency change, synthetic byte drift, network or Key need, arbitrary policy strings, ephemeral snapshot/replay reachability, a sixth repository path, or WU7B/Planner/HTML.
Stop as `PROVIDER_NEUTRAL_CONTRACT_REMEDIATION_SCOPE_BLOCKED` if Evidence, FER, Planner, Schema, validator, or dependency work becomes necessary.
Stop as `WU7_SYNTHETIC_BACKWARD_COMPATIBILITY_BLOCKED` on approved synthetic semantic or byte drift.
Plan-stage handbook-fetch deviation must remain visible in Review history.

Await: `批准执行 Work Unit 7R Provider-Neutral Parser Contract Remediation`
