# Work Unit 7R · Provider-Neutral Parser Contract Review

Review prepared: `2026-07-29T14:18:53+08:00`

Final status: `READY_FOR_HUGIN_REVIEW`

Decision implemented: `PROVIDER_NEUTRAL_AMAP_PARSER_CONTRACT_REMEDIATION`

WU7B status remains: `BLOCKED_BEFORE_EXECUTE`

## 1. Review boundary

WU7R exposes pure AMap-shaped district and POI parsers, an explicit closed observation mode, policy binding, and one shared Candidate projection path. The existing synthetic WU7 wrapper now delegates to that path while preserving its corrected UTF-8 compatibility baseline.

WU7R did not implement HTTP, read an AMap Key, call a provider, add live orchestration, persist ephemeral observations, modify a Schema, or begin WU7B.

The approved Plan remains byte-identical:

```text
plans/work-unit-7r-provider-neutral-parser-contract.md
SHA256:
CAF2674C0C0065432291DA6DCAF07A55FE1500ECCEDF10836F93038FB0709D2D
```

## 2. Git evidence

Start HEAD:

```text
5754c1b7117f4dd1604a7529df61ffc5ad2d595c
```

C4 HEAD used to prepare this Review:

```text
8388583b301f3e65f4235d0d075d6958594a298b
```

The final C5 commit is the commit containing this document with subject:

```text
docs: prepare WU7R provider-neutral parser review
```

The required seven-message linear history is:

```text
docs: record WU7R provider-neutral parser plan
chore: add provider-neutral parser contract interface
test: add failing provider-neutral parser cases
test: correct UTF-8 synthetic compatibility baseline
refactor: implement provider-neutral parser contract
chore: add provider-neutral parser verification
docs: prepare WU7R provider-neutral parser review
```

No commit was amended, squashed, reset, rebased, or rewritten. C2 remains the original Red commit, and C2.1 is a separate approved correction.

Before C5, `git diff --stat 5754c1b..8388583` reported:

```text
4 files changed, 2166 insertions(+), 164 deletions(-)
```

The four committed paths at that point were the Plan, runtime, new tests, and verifier. C5 adds only this Review, making the final WU7R scope exactly five paths.

## 3. Scope and protected state

The final five-path whitelist is:

```text
plans/work-unit-7r-provider-neutral-parser-contract.md
src/trip_decider/live_place_resolution.py
tests/test_wu7r_provider_neutral_parser_contract.py
scripts/verify_wu7r_provider_neutral_parser_contract.ps1
docs/reviews/work-unit-7r-provider-neutral-parser-contract-review.md
```

The pre-existing WU7B Plan remains untracked and unchanged:

```text
plans/work-unit-7b-amap-ephemeral-live.md
SHA256:
FBB2FA0AE8C59BE44EB8AAF6FE627301D2FAB481137E4DEE022F686449D7006B
```

Repository remotes and stashes remained `0/0`. No WU7B file was committed, executed, moved, or edited.

Protected hashes:

```text
WU7 runtime:
8FCAD57A8A7EF2F4B7924DE3A4DAE83808C680929B6BD3872144D7372B8B8EF9

WU7R tests:
5448FBA20F1F571CD2CF744F1B8F723252061A12C1B0DD9DAE068A954769180F

original WU7 tests:
443905617A067838C9BED34B63308F8F23403A373425E4FE53BEA523840A0962

original WU7 Review:
42E9902CD8FC8EF6901E990CC9FF7D88002C1358B9DEBC05CD62C89B3148A50E
```

All 11 Schema hashes were frozen in the verifier and matched. Schema, fixture, dependency, FER, Evidence Runtime, Planner, E2E, and historical-verifier files were not modified.

## 4. C2 Red evidence

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu7r_provider_neutral_parser_contract -v
```

Valid C2 result:

```text
tests: 4
passed: 0
failures: 0
errors: 4
exit code: 1
```

Every error was an explicit public-interface `NotImplementedError`. Import, path, dependency, syntax, malformed-input, network, credential, and unexpected error counts were zero.

During test construction, an earlier pre-commit invocation expanded PN03 subtests into seven error records. The subtest wrapper was removed before C2 was committed, without changing the four mismatch inputs or assertions. The committed C2 Red is the required 4/0/0/4 result.

## 5. C2.1 UTF-8 compatibility baseline correction

The frozen Plan recorded these original PN01 values:

```text
tree:
7319F394CB7CDCD5060EC9E9A3D9B6756E78C1E4A68D9C87578AAFD15CCD7EE5

resolution/candidates.json:
608A5FA4659F9375FFAAEED17DDEFE1EE361F74135FF781D2CD5F17EF2262324
```

Those values came from a Plan-stage PowerShell pipeline that damaged direct Chinese text. The effective seeds became `???`, and Candidate count became `0`; therefore those hashes did not represent the Plan-declared UTF-8 input.

Before editing the test, the C2 commit version of the pre-refactor wrapper was loaded independently from Git, while the uncommitted C3 runtime was excluded. An ASCII-only Python source used Unicode literals for the exact seeds:

```text
景点甲
未匹配
```

The independent run was performed twice. Both runs reported:

```text
files: 12
candidate count: 1
network calls: 0
credential reads: 0
LLM calls: 0

tree SHA256:
2F0EF9F8FDB9A8FE732A37BBCBA2408958412F7540ACF6F93BEAD41F6A071BA8

resolution/candidates.json SHA256:
D3718AD0B5D2AE259E4FE54D6B4FA0F658862700D4E6E98DD5FFFB86A8A1874C
```

Hugin approved C2.1 before the edit. Commit `5996245917aa9ad0141d9f794d705d4e37974d98` changed only the two expected hash constants. It did not change test input, Candidate count, tree framing, Candidate hashing, assertions, runtime, Plan, Schema, dependency, or product contract.

The Plan bytes and Plan SHA256 were deliberately not rewritten. The approved C2.1 evidence supersedes only the two corrupted Plan-stage hash values.

## 6. C3 Green and compatibility

After C2.1, the character-identical command reported:

```text
4 passed
0 failures
0 errors
```

The protected WU7 command reported:

```text
6 passed
0 failures
0 errors
```

The complete frozen module list reported:

```text
220 passed
0 failures
0 errors
```

C3 commit `1b9b3a14ec27873440b5727e0c9bde57582f0b0a` contains only:

```text
src/trip_decider/live_place_resolution.py
```

No test was modified in C3. The separate C2.1 test correction preceded C3 and remains visible in history.

Implemented boundaries:

- `AmapObservationMode` has exactly `synthetic_test` and `ephemeral_live`;
- mode is keyword-only and has no default or string coercion;
- pure district and POI parsers return controlled values;
- policy mismatch returns `OBSERVATION_POLICY_MISMATCH`;
- ephemeral mode binds only the existing temporary, non-replayable, non-fixture policy;
- controlled projection values have no write, snapshot, replay, serialization, or output-root capability;
- normalization, identity, exact matching, alternatives, and explicit selection have one shared projection implementation;
- the synthetic wrapper uses the shared parser/projector chain and retains corrected UTF-8 output bytes.

No public ephemeral path reaches persistence.

## 7. C4 verification entry

Command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu7r_provider_neutral_parser_contract.ps1
```

Post-C4 result:

```text
exit code: 0
gates: 15/15
tests: 220
schemas: 11
fixtures/documents/dirty cases: 7/40/7
synthetic files: 12
synthetic candidates: 1
network calls: 0
credential reads: 0
LLM calls: 0
temporary residue: 0
```

The verifier independently reproduced the corrected hashes:

```text
TREE_SHA256=2F0EF9F8FDB9A8FE732A37BBCBA2408958412F7540ACF6F93BEAD41F6A071BA8
CANDIDATES_SHA256=D3718AD0B5D2AE259E4FE54D6B4FA0F658862700D4E6E98DD5FFFB86A8A1874C
```

### C4 pre-commit verifier corrections

Four failed invocations occurred before the C4 commit. Each exposed a verifier-boundary defect rather than a product, fixture, Schema, or test failure:

1. The system-temporary Python file lacked the repository root on `sys.path`; the approved temporary-verifier import path was added.
2. The compatibility helper used a different synthetic provider ID and label spacing than PN01; it was aligned to the frozen PN01 input.
3. The count matcher expected `Ran 1 tests` instead of unittest's `Ran 1 test`; only singular/plural command-output matching changed.
4. The source audit assumed the public wrapper directly named all parser/projector functions; it was corrected to inspect the actual wrapper → preparation → binding/projection delegation chain while retaining exact single-definition checks.

No gate threshold, test count, hash, Schema hash, scope, network, credential, LLM, or residue requirement was lowered. C4 was created only after all 15 gates passed, and the same entry passed again after the C4 commit.

## 8. R10 and capability-boundary audit

The final verifier confirmed:

- no network client import or AMap endpoint in the runtime;
- no `AMAP_WEB_SERVICE_KEY`, `os.environ`, or `getenv` read in the runtime;
- no OpenAI/Anthropic import or model-call surface;
- no reachable `NotImplementedError` in the WU7R public contract;
- no `silent_fallback`, `infer_*`, or `guess_*` runtime path;
- exactly one district parser, one POI parser, and one Candidate projector;
- policy mismatch is a stable hard failure;
- ephemeral mode creates no file and exposes no snapshot/replay surface;
- the synthetic transport reports zero network attempts;
- no secret value was read, printed, persisted, or committed.

`EPHEMERAL_LIVE` means only that already-supplied AMap-shaped bytes can be parsed and projected in memory. It does not claim that live HTTP, authentication, durable capture, a real provider smoke, WU7B orchestration, recommendation, planning, or HTML exists.

## 9. Handbook deviation retained

The Plan-stage handbook audit performed one `git fetch` despite the explicit no-network instruction. This deviation remains recorded and is not rewritten as compliant behavior.

Facts preserved:

```text
handbook local HEAD:
6502e423ad2a1ab30db7f805e8ebc8fb31fc500b

handbook origin/main:
6502e423ad2a1ab30db7f805e8ebc8fb31fc500b

ahead/behind:
0/0

handbook worktree:
clean
```

The fetch changed no repository or handbook bytes, made no map-provider/API call, and read no credential. WU7R Execute and Review made zero network calls.

## 10. Completion determinations

1. ✓ Approved Plan hash and start baseline match.
2. ✓ WU7B Plan bytes and hash remain unchanged and uncommitted.
3. ✓ Pure district and POI parsing public interfaces exist.
4. ✓ Observation mode is explicit, closed, and has no default.
5. ✓ Policy mismatch produces `OBSERVATION_POLICY_MISMATCH`.
6. ✓ Policy, locator, persistence, and provenance cannot be caller-forged.
7. ✓ Ephemeral projection has no durable, snapshot, or replay capability.
8. ✓ One projection core owns normalization, identity, matching, and selection.
9. ✓ Existing public synthetic run and replay functions remain available.
10. ⚠ AP01–AP06 pass and corrected UTF-8 bytes are compatible. The Plan-stage two hashes were encoding-corrupted; Hugin-approved C2.1 records the valid pre-refactor values without rewriting the Plan.
11. ✓ Committed C2 Red is exactly four approved interface errors.
12. ✓ C3 Green is 4/4 and protected WU7 is 6/6.
13. ✓ Full regression is 220/220; counts remain 11 and `7/40/7`.
14. ✓ Network, credential, LLM, and temporary residue counts are zero.
15. ✓ Scope is exactly five paths with protected hashes unchanged.
16. ✓ This Review and the single verification entry independently support the final status.

The single known limitation in item 10 is an approved test-baseline correction, not a remaining runtime or contract failure.

## 11. Final state

```text
READY_FOR_HUGIN_REVIEW
```

WU7B was not started. No real AMap request, Key read, Planner, HTML, route, push, remote creation, or later Work Unit occurred.
