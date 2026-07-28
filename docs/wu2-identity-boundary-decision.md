# WU2 Real-world Identity Boundary Decision

Status: DECISION_RECORDED

Recorded on: 2026-07-28

Scope: WU2 Decision Gate only

This document freezes a responsibility boundary. It does not acquire data,
select a real-world POI, create an artifact, or authorize execution of the
stopped WU2 commits.

## 1. Preserved historical states

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

The historical meanings are preserved:

- WU2 stopped before C5 because the real anchor boundary was not satisfied.
- WU2A correctly exposed an incomplete acquisition ledger and remained
  `INVESTIGATION_BLOCKED`.
- WU2A-R repaired only acquisition-ledger mechanics.
- WU2A-Resume approved one exact open-data acquisition recipe with
  `ADAPTER_COMPATIBLE_ONLY` compatibility.
- No prior Plan, decision, Review, test, Schema, adapter, or commit is
  rewritten by this Gate.

## 2. Frozen inputs

| Input | SHA256 |
|---|---|
| `PLAN.md` | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| WU2 Plan | `894D5844E140BF62EC1DB89B1BE318EB4945FF4A0BF8B139E9B82C0B4929BA2C` |
| WU2A Plan | `432318A68D13774646CF3A1E5BE6057D5C92DE7CE600E06FA6CF52BD0CD92E90` |
| WU2A-R Plan | `FD0DA659873A275944DE7FCC9C1E4D1D27EE9BD7F61F40F4A3371493173008B9` |
| WU2A-Resume Plan | `B363FA80F1E62168E7AF654DE1195A24812F890352FB6C15852D65C488EE9BDB` |
| old WU2A decision | `570649D6B7287B48F3C396E536AC05EF31D949FC7AF960EF2D3DFEB17D4A9F6D` |
| WU2A-R Review | `DBA77226011F013D687FB3C6AF6085C692217167803E3280246EC70ABA93338F` |
| WU2A-Resume decision | `417F4E89A059CA99A5E96E960B839FA0297935F2438D76B100E7F8F30313B40A` |
| WU2A-Resume Review | `9CE29F71B065768B4BEE173144944A13003BC2838FCB42007ABCD8EAEEE4C64C` |
| real-world contract extension | `BD2280BFA2C51F2FEC8521F16BB7DE73667A39142FD89E04F6A515CB42B8963E` |
| OSM POI adapter | `F39EBF86B682EDECF182F6148178AEBA434A287B34A270FE84D3FAEE8F80944B` |
| Candidate Schema | `3E29144E1CEE4B300724D1E3DD63EB77DAE1F564135D6AB1B7C9B60F84B0CAB2` |
| Evidence Schema | `54904C8553BA5223BFB16A2253F1FDBD1FA18CFB77BDB7E5A616C41F24782F8B` |

These bytes remain read-only.

## 3. Acquisition fact boundary

The accepted WU2A-Resume result is:

```text
acquisition decision: APPROVED_ACQUISITION_RECIPE
compatibility: ADAPTER_COMPATIBLE_ONLY
attempt group: WU2A-resume-001
scheduled Geofabrik GET: 1
scheduled Overpass POST: 2
physical attempts: 3
retry relations: 0
```

The O2 response contained seven structurally selectable OSM objects:

| Exact primary label | Structural observation |
|---|---|
| 婺源县 | multiple distinct provider identities |
| 篁岭 | multiple distinct provider identities |
| 江岭 | one structurally selectable identity in this response |
| 李坑 | one structurally selectable identity in this response |
| 庆源 | no selected identity |

Every selected object had:

- a unique OSM `(type,id)` in the captured response;
- an exact primary `tags.name` from the frozen name set;
- at least one frozen provider category;
- an explicit node coordinate shape or reported way/relation center.

The acquisition did not use first, nearest, popularity, fuzzy matching,
language fallback, manual coordinates, guessed IDs, or LLM judgment.

### 3.1 What the response does not prove

It does not prove:

- which 婺源县 identity represents the user's intended trip base;
- whether the 篁岭 village or tourism-attraction record is the intended POI;
- whether same-name records represent the same physical feature;
- that 庆源 is absent from OSM;
- that seven records equal the old WU2 target set;
- that either planned route endpoint is resolved;
- that a planner can already propagate identity ambiguity.

Structural selectability is not identity truth.

## 4. Identity layers

The system separates three kinds of identity:

### 4.1 Provider identity

```text
(provider name, provider record type, provider record ID)
```

The adapter can validate and preserve this identity deterministically.

### 4.2 Candidate identity

Each valid provider identity maps to one stable candidate ID. Two candidates
may share a label without sharing an identity.

### 4.3 User-intent identity

The question “which provider record did the user mean by 篁岭?” depends on
intent, constraints, and evidence. The acquisition response alone does not
answer it.

The adapter owns provider-to-candidate normalization. It does not own
user-intent resolution.

## 5. Option comparison

### Option A — disambiguate in the adapter

```text
OSM records
→ adapter chooses one record
→ one candidate
```

Benefits:

- downstream data appears simpler;
- route code receives one apparent endpoint;
- fixture counts are easier to describe.

Costs and risks:

- category or array order becomes an unstated preference rule;
- a structural parser takes on travel-domain judgment;
- discarded identities and uncertainty disappear;
- the decision becomes provider-, city-, or seed-specific;
- a future response reorder can change the chosen place;
- no source supports “the adapter chose the correct 篁岭”;
- silent first/nearest/popularity fallback becomes likely.

Option A violates the rule that data acquisition must not perform travel
decision-making.

### Option B — retain every valid identity as a candidate

```text
OSM records
→ one candidate per provider identity
→ candidate pool
→ record-local evidence
→ explicit constraints or later planning decision
```

Benefits:

- provider facts remain auditable;
- the adapter remains deterministic and city-independent;
- same-name ambiguity is visible;
- explicit user confirmation or stronger evidence can resolve it later;
- no legal record is discarded merely because another record has a more
  travel-looking category.

Costs and required downstream work:

- labels cannot be used as unique keys;
- route acquisition must consume stable candidate references;
- evidence must distinguish source facts from identity-match derivation;
- planner/constraints must keep unresolved alternatives visible;
- missing seeds require explicit unmatched accounting.

Option B preserves evidence before generation and makes uncertainty
reviewable.

## 6. Decision

The fixed decision tokens are:

```text
Decision: MULTI_IDENTITY_CANDIDATE
Rejected: UNIQUE_IDENTITY_REQUIRED_AT_ADAPTER
WU2_C5_C6_RESUME: NOT_AUTHORIZED_NOW
OLD_WU2_C5_C6_UNCHANGED: PROHIBITED
```

One valid provider identity produces one candidate. Same-name candidates
remain separate. Neither adapter output order nor provider category chooses
the user-intended place.

Unique identity may become a later constraint result only when supported by
explicit user input, deterministic constraints, or auditable evidence. It is
not a universal adapter precondition.

## 7. Responsibility matrix

| Layer | Owns | Must not own |
|---|---|---|
| Adapter | strict response validation; unique provider identity; provider-local categories/location/source; deterministic normalization | preferred POI, intent match, first/nearest/popularity selection |
| Candidate | one stable entity per provider identity; record-local metadata; same-label coexistence | embedded truth claim that one alternative is correct |
| Evidence | source facts for each candidate; explicit support/derivation/freshness; future rule-derived ambiguity state | recommendation, preferred candidate, unsupported identity certainty |
| Constraint | explicit user selection; deterministic exclusion; confirmation requirements | hidden defaults or label-only identity resolution |
| Planner | choose an itinerary candidate when constraints/evidence support it; expose unresolved dependencies | real-world truth declaration, adapter fallback, silent deletion of alternatives |

The boundary is directional:

```text
adapter supplies records
candidate preserves identities
evidence describes facts
constraints authorize exclusions/selections
planner uses the authorized result
```

No downstream layer may retroactively claim that the adapter proved user
intent.

## 8. Candidate model ruling

### 8.1 Use multiple candidates

The accepted representation is:

```text
candidate_A:
  provider.name: osm
  provider.record_type: node
  provider.record_id: one provider ID

candidate_B:
  provider.name: osm
  provider.record_type: node
  provider.record_id: another provider ID
```

The existing adapter already derives a stable candidate ID from the full OSM
identity and emits all valid records in deterministic order. The existing
Candidate Schema accepts an array and does not require labels to be unique.

### 8.2 Do not add candidate-local alternatives

This Gate rejects a new candidate field shaped like:

```text
ambiguity:
  status: ambiguous
  alternatives: [...]
```

Reasons:

- ambiguity belongs to one input seed/context and a set of candidates;
- it is not an intrinsic provider property of a single candidate;
- copying the alternatives into every candidate creates cyclic, duplicated
  state;
- the current Candidate Schema has no such field;
- this Gate has no authority to modify the Schema.

### 8.3 Unmatched input

The unselected 庆源 seed remains:

```text
unmatched input seed
```

It does not become a placeholder candidate and is not evidence that OSM lacks
the place. A future recovery contract must explicitly choose where
matched/unmatched/ambiguous seed accounting lives.

## 9. Evidence model ruling

### 9.1 Record-local source facts

For two same-label candidates, Evidence should state source facts separately:

```text
candidate_A has provider category place=hamlet
candidate_B has provider category tourism=attraction
```

Each fact remains tied to its candidate and provider record. Neither fact
means that the record is the user-intended destination.

### 9.2 Rule-derived identity-match state

An exact seed matching multiple candidate labels can later produce a
rule-derived state with this semantic shape:

```yaml
field: identity_match_status
value:
  seed: 篁岭
  status: ambiguous
  alternative_candidate_refs:
    - candidate_A
    - candidate_B
derivation: rule_derived
```

This state says only that the frozen matching rule found alternatives. It
does not rank them.

### 9.3 Current contract limitation

The current Evidence Schema supports:

- a candidate entity as fact subject;
- arbitrary fact fields/values;
- route, transfer, and service-between relation subjects.

It does not define an N-way identity-ambiguity relation. Candidate references
placed inside an arbitrary fact value do not automatically gain bundle
closure/reference semantics.

Therefore this Gate does not claim the conceptual shape above is implemented.
WU3 must freeze and test an explicit mapping contract. If that requires a
Schema, validator, or new artifact change, it must use a separate contract
remediation work unit.

Identity ambiguity must not be disguised as a route, transfer, or service
relation.

## 10. Constraint and planner boundary

A candidate can be selected for an itinerary only when at least one of these
is present:

- the user explicitly chooses a stable candidate reference;
- a user hard constraint deterministically excludes every alternative;
- an official or equivalently auditable source resolves the identity;
- a pre-registered rule over supported evidence produces a unique result.

The following never suffice on their own:

- response order;
- nearest coordinates;
- popularity;
- a tourism-looking category;
- label similarity;
- model knowledge;
- a city-specific branch.

Planner selection means:

> this itinerary uses candidate X under the cited constraints/evidence.

It does not mean:

> candidate X is proven to be the only real-world object with this name.

If an activity or route still depends on unresolved identity, the planner
must retain the condition or request confirmation. It may not output
unconditional feasibility based on an invisible default, and failure to
resolve identity is not automatically `proven_infeasible`.

## 11. Downstream effects

### 11.1 WU2

- Keep one-candidate-per-provider-identity normalization.
- Do not resume old C5/C6 unchanged.
- Do not use natural-language labels as route endpoint identities.
- A future POI replay must retain all valid identities and unmatched seed
  accounting.
- Route acquisition needs explicit stable candidate references.

### 11.2 WU3

- Create source facts per candidate, not one merged same-label fact.
- Keep support, derivation, freshness, and display status orthogonal.
- Define identity-match ambiguity as an explicit rule-derived contract before
  it affects a hard decision.
- Never turn provider category into recommendation truth.

### 11.3 WU5

- Consume candidate references rather than labels.
- Treat alternatives as mutually exclusive only after an explicit group
  contract exists.
- Cite constraint/evidence references for any selected identity.
- Propagate unresolved identity into conditions, confirmation requirements,
  or violations.
- Do not recreate silent-first behavior inside planner code.

No downstream implementation is claimed by this document.

## 12. WU2 recovery gate

### 12.1 Current authorization

WU2 remains blocked. Approval of this responsibility decision does not itself
authorize a data call, anchor, fixture, route request, or WU2 status change.

The old WU2 Plan explicitly states that C5 is not created when names or
identities cannot be matched unambiguously. The observed result contains
exactly that unresolved condition. Historical Plan bytes cannot be
retroactively reinterpreted.

### 12.2 Preconditions for a future recovery Plan

A separate recovery Plan must satisfy all twelve conditions:

1. Hugin has accepted this Gate Review.
2. The recovery Plan cites the multi-identity decision without rewriting old
   WU2 history.
3. The POI anchor boundary becomes the complete valid provider-identity
   candidate pool, not an adapter-selected list of approximately five labels.
4. Every supplied seed has explicit matched, unmatched, or ambiguous
   accounting.
5. 庆源 remains unmatched unless a newly authorized source response provides
   a valid record.
6. Every candidate retains independently auditable provider identity,
   category, location, source, retrieval, and hash evidence.
7. Re-executing the acquisition recipe receives a new explicit data-call and
   persistence authorization.
8. Every route endpoint is an explicitly selected stable candidate reference,
   never a label lookup.
9. If route endpoint identity remains unresolved, route acquisition remains
   blocked or is separated from POI ingestion in the approved recovery Plan.
10. The Evidence/constraint ambiguity mapping is frozen and tested in its own
    applicable work unit before it supports a hard planner decision.
11. Any needed Schema, validator, adapter, or fixture-policy change goes
    through a separately approved remediation Plan.
12. Recovery follows a new PER cycle and does not reuse this Gate approval as
    Execute authority.

Satisfying these conditions permits submission of a recovery Plan for Hugin
approval. It does not automatically authorize execution.

### 12.3 Rejected recovery shortcuts

- choose the tourism category automatically;
- choose the first 婺源县 record;
- drop place records with duplicate labels;
- ignore the unmatched seed and call the old target set complete;
- let a route adapter search labels for coordinates;
- change the old WU2 Plan to make its uniqueness requirement disappear.

## 13. Scope and non-capabilities

Actual Decision Gate execution counters:

```text
map_data_network_attempts: 0
new_osm_queries: 0
new_data_sources: 0
created_candidates: 0
created_evidence_facts: 0
created_anchors: 0
created_fixtures: 0
created_routes: 0
schema_changes: 0
adapter_changes: 0
validator_changes: 0
test_changes: 0
```

The handbook fetch used for context is not a map-data acquisition and did not
modify the handbook.

This Gate does not implement a disambiguation model, recommendation,
constraint resolver, planner, route selection, evidence mapper, or real
Jiangxi itinerary.

## 14. Final boundary

The accepted boundary is:

```text
provider identity plurality is preserved
→ candidate pool remains plural
→ evidence remains record-local
→ ambiguity remains explicit
→ only supported constraints/planning may select an itinerary candidate
```

The stopped WU2 C5/C6 cannot be continued under their old unchanged Plan.
The next permissible step after Hugin accepts this Gate is planning a
separate recovery work unit. This document does not create that Plan.
