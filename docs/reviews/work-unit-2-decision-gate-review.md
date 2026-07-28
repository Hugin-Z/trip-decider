# Work Unit 2 Decision Gate Review

Review status: READY_FOR_HUGIN_REVIEW

Reviewed on: 2026-07-28

Scope: WU2 Decision Gate C0-C2

Start HEAD:
`71eeed24bceaf7f5df9a29f0cb9749004cb83a05`

C2 materialization base HEAD:
`6bdda33`

The C2 commit containing this document cannot contain its own Git object ID.
The final handoff reports the resulting HEAD after commit.

## 1. Outcome

The Decision Gate produced one responsibility-boundary decision:

```text
MULTI_IDENTITY_CANDIDATE
```

The rejected boundary is adapter-level semantic disambiguation. One valid
provider identity remains one candidate, and same-label candidates remain
separate.

Current WU2 execution authority remains:

```text
NOT_AUTHORIZED_NOW
```

The original C5/C6 cannot be resumed under their unchanged Plan. This Review
does not create a recovery Plan, execute the acquisition recipe, or change
the WU2 status.

## 2. Preserved project states

The following states remain:

```text
WU0:          APPROVED
WU1:          APPROVED
WU1R:         APPROVED
WU1C:         APPROVED
WU2:          BLOCKED
WU2A:         INVESTIGATION_BLOCKED
WU2A-R:       APPROVED
WU2A-Resume:  APPROVED
```

`docs/reviews/work-unit-2-review.md` remains absent because WU2 did not reach
its Review commit. No old Plan, decision, Review, test, adapter, Schema, or
history was edited.

The accepted WU2A-Resume facts remain:

```text
decision: APPROVED_ACQUISITION_RECIPE
compatibility: ADAPTER_COMPATIBLE_ONLY
selected OSM objects: 7
婺源县: multiple identities
篁岭: multiple identities
庆源: unmatched
```

The Decision Gate does not promote those structural facts into a claim that
any identity is the user's intended POI.

## 3. Approved Plan and commit evidence

Approved Plan:

```text
path: plans/work-unit-2-decision-gate.md
version: v0.1
sha256: CFD545EAFE52EB21CC504B99FA9756AD16D2C1E01DFCAAB74562EBDC43F6FA1C
```

C0:

```text
73a5806 docs: record approved decision gate plan
files: plans/work-unit-2-decision-gate.md only
```

C1:

```text
6bdda33 docs: record identity boundary decision
files: docs/wu2-identity-boundary-decision.md only
```

C2 adds only:

```text
docs/reviews/work-unit-2-decision-gate-review.md
```

The history is linear. No commit was amended, reset, rebased, squashed, or
rewritten.

## 4. Frozen hash review

All 13 frozen inputs were recomputed before C0, during C1 checks, and during
C2 checks:

| Input | Actual SHA256 | Result |
|---|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` | match |
| WU2 Plan | `894D5844E140BF62EC1DB89B1BE318EB4945FF4A0BF8B139E9B82C0B4929BA2C` | match |
| WU2A Plan | `432318A68D13774646CF3A1E5BE6057D5C92DE7CE600E06FA6CF52BD0CD92E90` | match |
| WU2A-R Plan | `FD0DA659873A275944DE7FCC9C1E4D1D27EE9BD7F61F40F4A3371493173008B9` | match |
| WU2A-Resume Plan | `B363FA80F1E62168E7AF654DE1195A24812F890352FB6C15852D65C488EE9BDB` | match |
| old WU2A decision | `570649D6B7287B48F3C396E536AC05EF31D949FC7AF960EF2D3DFEB17D4A9F6D` | match |
| WU2A-R Review | `DBA77226011F013D687FB3C6AF6085C692217167803E3280246EC70ABA93338F` | match |
| WU2A-Resume decision | `417F4E89A059CA99A5E96E960B839FA0297935F2438D76B100E7F8F30313B40A` | match |
| WU2A-Resume Review | `9CE29F71B065768B4BEE173144944A13003BC2838FCB42007ABCD8EAEEE4C64C` | match |
| real-world contract extension | `BD2280BFA2C51F2FEC8521F16BB7DE73667A39142FD89E04F6A515CB42B8963E` | match |
| OSM POI adapter | `F39EBF86B682EDECF182F6148178AEBA434A287B34A270FE84D3FAEE8F80944B` | match |
| Candidate Schema | `3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2` | match |
| Evidence Schema | `54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B` | match |

The approved Gate Plan remained byte-identical through execution.

## 5. Handbook review

The fixed handbook repository was fetched read-only before C0:

```text
local HEAD:  6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
worktree before/after fetch: clean
```

The following files were read from `origin/main`:

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

The handbook was not modified.

## 6. Responsibility-boundary review

### 6.1 Adapter

The adapter remains responsible for:

- strict source-response structure;
- unique provider `(type,id)`;
- provider-local category, location, and source metadata;
- deterministic one-provider-identity-to-one-candidate normalization.

It is not responsible for selecting the user-intended real-world place.

### 6.2 Candidate

The candidate pool retains every structurally valid provider identity.
Labels need not be unique. The Gate rejected a new candidate-local
`ambiguity.alternatives` field because ambiguity is a relation between a
seed/context and a set of candidates, not an intrinsic provider property.

No Candidate Schema change was made.

### 6.3 Evidence

Evidence must describe each candidate's record-local source facts separately.
A future exact-seed-to-multiple-candidate result may be represented as a
rule-derived ambiguity state, but it must not choose a preferred identity.

The current Evidence Schema does not define an N-way identity-ambiguity
relation. Its existing relation subject is limited to route, transfer, and
service-between. The decision explicitly refuses to relabel identity
ambiguity as one of those relation types or to claim that arbitrary nested
values already have reference semantics.

No Evidence Schema or validator change was made.

### 6.4 Constraint and planner

Only explicit user selection, deterministic constraints, auditable identity
evidence, or a pre-registered supported rule may resolve an identity.

Planner may say which candidate an itinerary uses under cited support. It may
not say that candidate is proven to be the only real-world object, silently
choose the first/nearest/popular record, or hide unresolved alternatives.

### 6.5 WU2/WU3/WU5 effects

- WU2 keeps multi-candidate normalization but cannot resume old C5/C6.
- WU3 must freeze and test record-local evidence plus an explicit ambiguity
  mapping before it affects a hard decision.
- WU5 must consume stable candidate references and propagate unresolved
  identity into conditions, confirmation requirements, or violations.

No implementation in those units is claimed.

## 7. WU2 recovery review

The decision contains exactly twelve prerequisites for a future recovery
Plan. They cover:

- Gate acceptance and preserved history;
- a complete provider-identity candidate pool;
- explicit matched/unmatched/ambiguous seed accounting;
- no fabricated 庆源 record;
- auditable per-candidate provenance;
- a new acquisition authorization;
- stable candidate references for routes;
- continued route blocking or explicit scope split while identity is
  unresolved;
- a separately frozen ambiguity contract;
- separate remediation for any Schema/validator/adapter/policy change;
- a new PER cycle.

These are prerequisites for submitting a future Plan, not Execute authority.

Rejected shortcuts include category preference, first-result selection,
dropping same-label place records, ignoring the unmatched seed, label-based
route lookup, and rewriting the old WU2 Plan.

## 8. G01-G14 evidence

### 8.1 C1 final validation

The first C1 check run reported:

```text
checks: 14
passed: 13
failures: 1
errors: 0
failure: G14
network attempts: 0
```

The document was not at fault. The initial G14 command scanned every
occurrence of the word `placeholder`, including the explicit prohibition
against creating a placeholder candidate. That was broader than the approved
G14 contract, which checks for a pending/placeholder conclusion.

The check implementation was narrowed to Status/Decision/recovery conclusion
fields. No decision content, expected token, Plan, Schema, adapter, or test
was changed.

The valid C1 result was:

```text
PASS G01
PASS G02
PASS G03
PASS G04
PASS G05
PASS G06
PASS G07
PASS G08
PASS G09
PASS G10
PASS G11
PASS G12
PASS G13
PASS G14
checks: 14
passed: 14
failures: 0
errors: 0
network attempts: 0
```

### 8.2 C2 independent validation

After C1 commit and from a clean worktree, C2 independently returned the same:

```text
checks: 14
passed: 14
failures: 0
errors: 0
network attempts: 0
```

The checks proved:

- UTF-8 without BOM;
- all four machine decision/recovery tokens exactly once;
- 13 frozen hash matches;
- all five responsibility layers;
- both options;
- multiple-candidate/no-nested-alternatives boundary;
- record-local evidence and current-contract limitation;
- WU2/WU3/WU5 effects;
- exactly 12 recovery prerequisites;
- all 12 prohibited-action counters at zero;
- no pending conclusion.

## 9. Scope and Git review

The exact final whitelist is:

```text
plans/work-unit-2-decision-gate.md
docs/wu2-identity-boundary-decision.md
docs/reviews/work-unit-2-decision-gate-review.md
```

Diff outside those paths is zero:

```text
src/: 0
schemas/: 0
tests/: 0
fixtures/: 0
scripts/: 0
dependencies: 0
runtime: 0
```

Execution created:

```text
candidate artifacts: 0
evidence artifacts: 0
anchors: 0
fixtures: 0
routes: 0
map-data network attempts: 0
```

`git remote` and `git stash list` remain empty. No branch, remote, push, PR,
recovery Plan, or later work-unit Plan was created.

## 10. R10 review

- No array order, category, distance, popularity, model knowledge, or city
  special case was promoted to an identity choice.
- The unmatched seed is not represented as proof that OSM lacks a place.
- Structural adapter compatibility is not represented as old WU2 target
  compatibility.
- The conceptual future ambiguity fact is labeled unimplemented; the Review
  does not claim WU3 behavior exists.
- The initial G14 false positive is retained in this Review rather than
  rewritten as a first-run pass.
- All counts and hashes come from commands.
- No secret, raw response, coordinate list, or provider credential entered
  the diff.

Text mentions `first`, `nearest`, `guess`, and `silent fallback` only as
explicitly rejected behavior. There is no executable code diff.

## 11. Completion criteria

1. ✓ 已完成 — approved Plan bytes match the approved SHA256 and were not edited during execution.
2. ✓ 已完成 — WU2/WU2A/WU2A-R/WU2A-Resume states, history, and frozen files remain unchanged.
3. ✓ 已完成 — handbook fetch, eight reads, matching HEADs, `0/0`, and clean status are evidenced.
4. ✓ 已完成 — seven selected objects, duplicate-label identities, and unmatched 庆源 are preserved without an identity-truth claim.
5. ✓ 已完成 — Options A and B and all eight decision criteria are recorded.
6. ✓ 已完成 — the sole accepted decision is multi-identity candidates.
7. ✓ 已完成 — adapter responsibility is structural validation and one identity per candidate, not semantic selection.
8. ✓ 已完成 — the Candidate boundary uses separate candidates and adds no nested alternatives field.
9. ✓ 已完成 — Evidence remains record-local and the missing N-way ambiguity contract is explicitly disclosed.
10. ✓ 已完成 — Constraint/Planner selection requires user or evidence support; unresolved identity stays visible.
11. ✓ 已完成 — WU2, WU3, and WU5 effects are separated without implementation overclaim.
12. ✓ 已完成 — current recovery remains unauthorized and all 12 future recovery prerequisites are present.
13. ✓ 已完成 — final diff is restricted to three documents; code/Schema/adapter/test/fixture diff is zero.
14. ✓ 已完成 — no map API/data acquisition or anchor/fixture/runtime creation occurred.
15. ✓ 已完成 — valid C1 and independent C2 checks both returned 14/14 from command output.
16. ✓ 已完成 — WU2 was not restored; no later work unit, push, remote, or PR was started.

## 12. Final state

```text
READY_FOR_HUGIN_REVIEW
```

Execution stops after the C2 commit. WU2 remains `BLOCKED`, WU2 C5/C6 remain
unauthorized, and no recovery or WU3 Plan is created.
