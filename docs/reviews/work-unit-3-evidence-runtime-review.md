# Work Unit 3 Evidence Runtime Review

Review status: `READY_FOR_HUGIN_REVIEW`

Work unit: `WU3-ER · Evidence Runtime MVP`

Approved Plan:

```text
plans/work-unit-3-evidence-runtime.md
Version: v0.1
SHA256: D27D083ADED805A0E0E11528918E4557A769C73B78C60C63DA54C62BF97BBC19
Lines: 283
Bytes: 11446
Decision: CANDIDATE_LOCAL_EVIDENCE_ONLY
```

This Review covers only the approved C0-C5 sequence. It does not revise old
WU2/WU2R history, call a network or LLM, select an identity, create a new
fixture, implement evidence collection, rate real-world truth, recommend a
candidate, or begin WU4/WU5.

## 1. Execution gate and preserved baseline

The execution preflight matched the approval:

```text
branch: main
start HEAD: a1a79665d7eaba1cd3f1224b88c8c316e4d86051
worktree: ?? plans/work-unit-3-evidence-runtime.md
remotes: 0
stashes: 0
Plan SHA256: D27D083ADED805A0E0E11528918E4557A769C73B78C60C63DA54C62BF97BBC19
```

The approved Plan was the only worktree entry. Its bytes were committed
unchanged in C0.

The previous WU2R-DOR verifier was also invoked during preflight. It exited
before running tests because its own historical scope gate correctly rejected
the newly approved, untracked WU3 Plan:

```text
WU2R-DOR verification FAIL:
Path outside WU2R-DOR whitelist:
plans/work-unit-3-evidence-runtime.md
```

This was a historical verifier scope rejection, not a regression or test
failure. The same nine pre-WU3 unittest modules were then run directly:

```text
Ran 186 tests in 11.583s
OK
exit code: 0
```

Baseline fixture validation remained:

```text
fixture directories: 7
embedded documents: 40
dirty cases: 7
```

## 2. Handbook and frozen inputs

The handbook remained read-only:

```text
fixed path: <handbook>
local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree entries: 0
```

The following files were re-read from `origin/main`:

```text
STATE.md
INDEX.md
SUMMARY.md
tools/context-injection.md
principles/r10-honesty.rule.md
principles/per-protocol.rule.md
principles/scope-control.rule.md
principles/fixture-first.rule.md
```

The verifier mechanically checked the approved Plan plus the runtime/test
hashes and all protected implementation, anchor, dependency, and Schema
inputs. Relevant hashes are:

| Path | SHA256 |
|---|---|
| `plans/work-unit-3-evidence-runtime.md` | `D27D083ADED805A0E0E11528918E4557A769C73B78C60C63DA54C62BF97BBC19` |
| `src/trip_decider/evidence_runtime.py` | `626D052F068537D050D350E8404948286670405D0B75C2E793CAA71656C89C04` |
| `tests/test_wu3_evidence_runtime.py` | `4C7F3FF666FB92A9242064D81FEA33B4404EAE9099593832FFE798703F962747` |
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `requirements.lock` | `BFE485EFB4105DC01C475D21EFB7858FD8468A69EBD0056363FBD9C84E6C6927` |
| `pyproject.toml` | `FD6622AA930E4BFA5986F26274EFA42B2512089050B716F445006C8EB98EA995` |
| `src/trip_decider/recovery.py` | `C0E098DD4AB997727A0EFBCCC9C396AC480DEEB3477DBF4CDCB5E31A34E0D8BA` |
| `src/trip_decider/resume_acquisition.py` | `86229BA52695D3B4725DFDB54D709C8D79580DD35B8FCEE010D3AD59B7D0A6AE` |
| `src/trip_decider/acquisition_evidence.py` | `BF7F25FC4A41C8085431450501B86866A7757B125A208363AA5113AD5F82FEDB` |
| `src/trip_decider/adapters/open_data_poi.py` | `F39EBF86B682EDECF182F6148178AEBA434A287B34A270FE84D3FAEE8F80944B` |
| `src/trip_decider/schema_validation.py` | `2061084E8AC27DF4C08F63DC264A2612685980D966AA5291A46660BE3F1CC017` |
| `src/trip_decider/fixture_validation.py` | `6C720C5F4D72356F2909854E6C1B605B891BC40787A4D87739CCA69C2590EBBF` |
| `fixtures/jiangxi_multi_identity_smoke/case.json` | `6052797C4FE43B0E1BE216187EAD6AC10FB1617F07CD7784CF81F8403843F3C8` |
| `fixtures/jiangxi_multi_identity_smoke/replay.json` | `5D8086E128FE1B33FD0314151C49256A459DB401233B1C548843791AFAC1919A` |
| `fixtures/jiangxi_multi_identity_smoke/osm-pois.json` | `41520443BB370919F184CF46441DB897A809EB1B86119B7CF2B6007F20A5B382` |

All 11 Schema hashes remained unchanged:

| Schema | SHA256 |
|---|---|
| `candidates.schema.json` | `3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2` |
| `common.schema.json` | `83FE17127A545D168A16F58911564E53D2E17AFF826B6D34437D873ECF8E75BE` |
| `constraint-parse.schema.json` | `0D41493B52B6178AEE8DE44B2F3607B193B62C263AD79DEF380B638B22B400A4` |
| `constraints.schema.json` | `25069E0DEFBDC03FEA7E92E83EE10F952A31A2B18BDC3678D17786C537EE4473` |
| `evidence.schema.json` | `54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B` |
| `fixture-case.schema.json` | `630E57E7F27A660F388407A8FF1B81D851B8B3A047E5B98DCB70E1920177E45A` |
| `plan.schema.json` | `81EEB5899C33F19DC6FA059C7D447D747E72E355F3084D925FD9410272389BD3` |
| `plan-diff.schema.json` | `37B94FE5E03A73B046D7E6D79BEABF31C4105E50CD54DE520CA6C293AB3E8B43` |
| `previous-plan.schema.json` | `59692D17EB79C7EA2D4A2E2866898DD97A0E49B97834EC8AFC5EAB46A80BEDAC` |
| `request.schema.json` | `BC7F46E9A85CE9697F9BA01FF1506A5B56C161F2F6B5140D91FCF0B100762914` |
| `violations.schema.json` | `C117415030993C24649B17837EC2A35C69A2F1CEC7D923742ABD383BA85B394F` |

No dependency was added. The verifier confirmed that the running interpreter,
prefix, and site-packages are project `.venv` paths, the lock exactly matches
installed package versions, and `pip check` reports:

```text
No broken requirements found.
```

## 3. Git and scope evidence

Linear C0-C4 history before this Review:

```text
dbb81a5d7e0330238b2a4d5d5537dbf1263fb9bd docs: record WU3 evidence runtime plan
e7dae18d54a9fe857a26d246a3cb791f8bdb028c chore: add Evidence Runtime interface
5492b4f1d750561efa478ded414c152574b528e6 test: add failing Evidence Runtime cases
e2bb99b44b04d3ce31ae2406f2e2b4a8673f4e25 feat: implement candidate Evidence Runtime
dda3c6a5f1205508909604f2a8487090f2dd2995 chore: add Evidence Runtime verification entry
```

C5 adds only this Review with the approved message:

```text
docs: prepare WU3 evidence runtime review
```

Before C5, the diff stat from the approved start was:

```text
plans/work-unit-3-evidence-runtime.md   |  283 +++++++
scripts/verify_wu3_evidence_runtime.ps1 |  551 +++++++++++++
src/trip_decider/evidence_runtime.py    | 1335 +++++++++++++++++++++++++++++++
tests/test_wu3_evidence_runtime.py      |  274 +++++++
4 files changed, 2443 insertions(+)
```

C5 completes the exact five-path whitelist:

```text
plans/work-unit-3-evidence-runtime.md
src/trip_decider/evidence_runtime.py
tests/test_wu3_evidence_runtime.py
scripts/verify_wu3_evidence_runtime.ps1
docs/reviews/work-unit-3-evidence-runtime-review.md
```

No Schema, fixture, Recovery, Resume, FER, adapter, validator, dependency,
existing test, `PLAN.md`, or handbook file changed. No amend, squash, reset,
rebase, remote creation, push, or PR occurred.

`git diff --check` over C1-C4 was clean. Running it from the pre-C0 start also
reports the two Markdown hard-break spaces in approved Plan lines 3 and 4.
Those bytes pre-existed approval and are required by the approved Plan hash;
they were not silently rewritten.

## 4. Fixture-first Red to Green

### C2 Red

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu3_evidence_runtime -v
```

Observed:

```text
tests: 6
passed: 0
failures: 0
errors: 6
exit code: 1
```

The six erroring test IDs were ER01-ER06:

```text
test_er01_candidate_local_facts_produce_valid_evidence
test_er02_subjects_and_source_references_resolve
test_er03_matched_complete_seeds_are_eligible
test_er04_ambiguous_seed_preserves_all_alternatives
test_er05_unmatched_seed_has_no_placeholder
test_er06_outputs_are_deterministic_offline_and_atomic
```

Every error was the approved public interface state:

```text
NotImplementedError: WU3 Evidence Runtime is not implemented
```

Import, dependency, path, syntax, malformed-test, assertion, unexpected
exception, and network error counts were all zero.

### C3 Green

The byte-for-byte same command produced:

```text
Ran 6 tests in 2.517s
OK
exit code: 0
passed/failures/errors: 6/0/0
network attempts: 0
```

C3 changed only `src/trip_decider/evidence_runtime.py`; no test or Schema was
changed to obtain green. No execution-time correction commit was needed.

The full suite before C3 commit also passed:

```text
Ran 192 tests in 13.942s
OK
```

## 5. Runtime contract evidence

The runtime reads exactly the four DOR output files from an explicit root and
emits exactly:

```text
evidence.json
evidence-gate.json
run-summary.json
```

The committed anchor deterministically produces:

```text
candidates: 7
facts: 28
facts per candidate: 4
complete candidates: 7
eligible seeds: 2
blocked seeds: 2
generation_allowed: false
```

Each candidate has exactly these ordered facts:

```text
provider_identity
provider_category
location
source_reference
```

Every fact remains within the approved evidence ceiling:

```text
support_status: unknown
derivation: rule_derived
freshness.retrieved_at: null
freshness.effective_at: null
freshness.expires_at: null
freshness.status: unknown
sources: []
display_status: unknown
conflict_source_refs: []
derivation_detail.input_fact_ids: []
support_ceiling: unknown
```

No `api_response`, webpage, or `direct_observation` source is constructed.
Candidate `source_reference` remains a local locator value and is not
misrepresented as an Evidence source.

The seed gate is:

```text
篁岭: BLOCKED_IDENTITY_AMBIGUOUS
江岭: ELIGIBLE
李坑: ELIGIBLE
庆源: BLOCKED_IDENTITY_UNMATCHED
```

The 篁岭 alternatives remain in seed-accounting order, and 庆源 retains zero
candidate refs. Ambiguity/unmatched status is consumed only from
`seed-accounting.json`; it is not emitted as an Evidence fact and does not
cause identity selection. `ELIGIBLE` means only that the record may be handed
to a later stage; it does not mean verified, recommended, feasible, or
generation-authorized.

A separate system-temporary-directory run yielded stable IDs and bytes:

```text
run_id: run_1521f9da-a773-44ca-b43b-c0bb6e15ab9f
evidence artifact_id: urn:uuid:bdc11296-ea19-4ded-93ea-dfc4edafe712
evidence_set_id: evidence_set_0a29a68b-31ec-4a75-aee7-7e0e8e16c4a0
evidence.json: 144BF69FDCF9DC91AC426CEDB4DF4C6277F4100A2215B8222CAD70E9481CC20A
evidence-gate.json: 6DF1931FBF13812978F47A82433C44A4E45332E75984153220327FC2A62CB55C
run-summary.json: 9E23474A370263D00569F17E4A7B6140CBF1D412908E007AD8AEDA2812FCCEBE
temporary residue: 0
```

The runtime output and gate are validated against the existing Schema and
cross-document rules. Two clean roots are byte-identical. Non-empty output
roots are rejected without overwrite; injected installation failure rolls
back all partial files; installed bytes and hashes are re-read and checked.

### Auxiliary evidence-print correction

The first auxiliary command used only to format seed labels successfully
completed Recovery and Evidence Runtime and printed the IDs/counts/hashes
above, but its final formatter assumed a nonexistent `seed_ref` key. It exited
1 with `KeyError: 'seed_ref'`; the temporary directory was still cleaned.
The control document actually uses the frozen `seed` field. A corrected,
read-only rerun used that field and exited 0 with the four statuses above.
This was not a runtime, Schema, fixture, or verification-gate failure and
caused no file change.

## 6. Complete verification entry

Command before C4 commit:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify_wu3_evidence_runtime.ps1
```

Observed:

```text
exit code: 0
Ran 192 tests in 14.093s
OK
WU3-ER verification PASS:
tests=192 schemas=11 fixtures=7 documents=40 dirty_cases=7
evidence_facts=28 outputs=3 generation_allowed=false
network_attempts=0 temporary_residue=0
```

The identical command after C4 commit produced:

```text
exit code: 0
Ran 192 tests in 14.275s
OK
WU3-ER verification PASS:
tests=192 schemas=11 fixtures=7 documents=40 dirty_cases=7
evidence_facts=28 outputs=3 generation_allowed=false
network_attempts=0 temporary_residue=0
```

The entry validates project `.venv`, exact lock replay, `pip check`, the
approved commit prefix, five-path scope, frozen inputs, all 11 Schema hashes,
fixture counts, runtime semantics, deterministic outputs, complete unittest
suite, scans, zero network attempts, and zero system-temporary residue.

## 7. R10 and boundary audit

Mechanical scans and source review found:

```text
silent fallback / guess / infer tokens: 0
warning-as-pass / default-when-missing tokens: 0
reachable NotImplementedError in runtime: 0
forbidden Evidence source kinds in runtime: 0
network transport implementation in runtime: 0
secret patterns in changed files: 0
```

The runtime does not coerce missing facts, guess provider/CRS/identity, scan
for alternate inputs, silently accept a non-empty output root, or convert an
error into a warning/pass. Stable seven-field `ValidationProblem` values are
used; actual input values, third-party exception text, and secrets are not
copied into machine problems.

Code and documentation claim only candidate-local, rule-derived, unknown
Evidence plus a structural downstream gate. There is no claim of real-world
verification, freshness, recommendation, feasibility, routing, or planning.

## 8. Completion criteria

1. ✓ 已完成 — approved Plan bytes and SHA256 are unchanged.
2. ✓ 已完成 — baseline, handbook, and frozen input hashes were reconciled.
3. ✓ 已完成 — the final diff is restricted to the five approved paths.
4. ✓ 已完成 — every Candidate has exactly four candidate-local facts.
5. ✓ 已完成 — every subject/ref resolves to the current Candidate contract.
6. ✓ 已完成 — support, display, freshness, sources, and ceiling remain unknown.
7. ✓ 已完成 — ambiguity is consumed only from seed accounting.
8. ✓ 已完成 — the deterministic gate priority is implemented and checked.
9. ✓ 已完成 — the current anchor has `generation_allowed=false`.
10. ✓ 已完成 — Evidence Schema, integrity, provenance hashes, and refs pass.
11. ✓ 已完成 — C2 produced exactly six explicit `NotImplementedError` errors.
12. ✓ 已完成 — C3 used the identical command and passed 6/6.
13. ✓ 已完成 — the complete suite passed 192/192.
14. ✓ 已完成 — fixtures/documents/dirty cases remain 7/40/7.
15. ✓ 已完成 — network/residue are 0; atomic/no-overwrite/determinism pass.
16. ✓ 已完成 — this Review independently records Git, hashes, R10, scope, and
   all completion criteria.

## 9. Final boundary

WU3-ER did not modify old histories or protected paths, call a network or
LLM, select an identity, create a source it did not observe, start a planner,
or begin WU4/WU5. No push or remote creation occurred.

Final status:

```text
READY_FOR_HUGIN_REVIEW
```
