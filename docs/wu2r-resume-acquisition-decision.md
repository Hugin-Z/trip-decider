# WU2R Resume Acquisition Decision

Status: WU2R_ACQUISITION_COMPLETED

Checked on: 2026-07-28

Scope: the single approved `WU2R-resume-001` acquisition group only

## 1. Preserved historical state

```text
WU2:      BLOCKED
WU2R:     BLOCKED
WU2R-FER: APPROVED
```

WU2R Resume does not amend or reinterpret the old WU2/WU2R attempt. The old
deleted ledger cannot independently prove physical attempts, retry use, or
the response state. Its budget is therefore recorded exactly as:

```text
OLD_WU2R_ATTEMPT_BUDGET:
UNRECONCILABLE_FROM_DELETED_LEDGER
```

It is not described as consumed or unconsumed. No old WU2 C5/C6 or WU2R
commit is reopened.

The predecessor FER Review is:

```text
path:
docs/reviews/work-unit-2r-failure-evidence-review.md

sha256:
2F6D893C57C70D5B74F432E96CCB72AFCC65F23BA0903BDF6CCDC6DC5D9E0B85

status:
READY_FOR_HUGIN_REVIEW
```

That Review established a future, offline-tested failure-evidence boundary.
It did not reconstruct the old attempt or itself authorize a new network
call.

## 2. New attempt-group identity and FER link

The new authority is isolated by exact values:

```text
attempt_group_id:
WU2R-resume-001

run_id:
run_wu2r_resume_001

failure_evidence_path:
runtime/wu2r-failure-evidence/run_wu2r_resume_001/failure-evidence.json

query_sha256:
5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F

request_sha256:
6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045
```

The future integration boundary must receive these values explicitly.
Timestamp order, directory scanning, a “latest file” rule, and filename
inference are not valid association mechanisms.

The authoritative sanitized ledger path is ignored runtime state. A
subordinate harness ledger, if needed, may exist only at a random system
temporary path and must be deleted. Raw response bytes may exist only in
memory or a random system temporary file until every persistence gate passes.

## 3. Frozen source and policy gate

The source remains OpenStreetMap data through the single approved Overpass
endpoint:

```text
endpoint:
https://overpass-api.de/api/interpreter

method:
POST

source_class:
open_data

capture_mode:
persistent_anchor

storage_policy:
persistent_allowed

replay_allowed:
true

fixture_allowed:
true

license:
ODbL-1.0

attribution:
© OpenStreetMap contributors
```

On 2026-07-28, immediately before this gate was committed, the four direct
primary pages were reopened read-only:

| Primary page | Access result | Gate result |
|---|---|---|
| <https://www.openstreetmap.org/copyright> | accessible; 70 rendered lines | identifies OSM data as ODbL and requires OSM credit plus a visible license basis |
| <https://opendatacommons.org/licenses/odbl/1-0/> | accessible; 237 rendered lines | permits use, extraction, and temporary or permanent reproduction subject to the license conditions |
| <https://osmfoundation.org/wiki/Licence/Attribution_Guidelines> | accessible; 217 rendered lines | preserves the existing OSM attribution requirement |
| <https://wiki.openstreetmap.org/wiki/Overpass_API> | accessible; 935 rendered lines | identifies Overpass as a selected-extract service and lists the approved endpoint |

These pages support the already frozen, narrow, non-production fixture
policy. They do not prove OSM accuracy, completeness, freshness, service
availability, or the absence of record-local third-party rights. No search
summary is used as authority.

The exact query is the UTF-8 code block already frozen in
`docs/wu2-recovery-source-and-capture.md` section 4. It may not be edited,
normalized, re-indented, re-encoded, expanded, or reconstructed from memory.
The request body is the application/x-www-form-urlencoded encoding of those
exact bytes. Both hashes must be recomputed and matched before transport.

## 4. New call budget

Approval covers only this new group:

```text
scheduled Overpass POST: 1
byte-identical retry after typed transport failure: at most 1
maximum physical Overpass attempts: 2

OSRM: 0
Nominatim: 0
commercial maps: 0
alternate Overpass instance: 0
Geofabrik: 0
other data sources: 0
web crawlers: 0
```

Only DNS, timeout, connection reset, or an equivalent typed transport
failure may schedule the one retry. The retry must preserve endpoint, method,
headers, timeout, query bytes, request bytes, and request hash.

HTTP status, UTF-8/JSON/shape, empty-elements, adapter, identity/coverage,
policy, ledger, cleanup, or internal failure is terminal and non-retryable.
No failure permits another group, query modification, alternate endpoint, or
provider fallback.

## 5. Candidate and persistence boundary

The consumed identity decision remains:

```text
Decision: MULTI_IDENTITY_CANDIDATE
Rejected: UNIQUE_IDENTITY_REQUIRED_AT_ADAPTER
```

Every valid `(type,id)` provider identity in the accepted response must
become exactly one candidate. No same-label identity may be selected,
ranked, merged, or removed by array order, category, first/nearest,
popularity, manual judgment, or an LLM.

The frozen seeds are:

```text
篁岭
江岭
李坑
庆源
```

Success requires non-empty `matched`, `ambiguous`, and `unmatched` accounting
with resolving candidate references. An unmatched seed creates no
placeholder and is not a claim about OSM or real-world absence.

No raw response enters Git until strict UTF-8/JSON, contributor-field,
adapter, identity, coverage, source-policy, persistence, and independently
authored fixture gates all pass. Failure creates no anchor and must be
represented only by a durable sanitized FER envelope.

## 6. Completed acquisition facts

```text
map_data_calls_in_C0_C1:
0

anchor_created:
true

fixture_created:
true

route_acquisition:
false

attempt_group_id:
WU2R-resume-001

run_id:
run_wu2r_resume_001

scheduled_overpass_posts:
1

physical_attempts:
1

retry_relations:
0

fer_status:
succeeded

fer_terminal_failure_code:
null

failure_evidence_path:
runtime/wu2r-failure-evidence/run_wu2r_resume_001/failure-evidence.json

failure_evidence_sha256:
817197DA1D64AC660455C20725A11B03D8BAD7E9EACC9945FAEC815D7AD36CA3

query_sha256:
5A51E39FFD53FCD1B204AEBD6652CC7267853BD236B4FBA5D807941CFF62993F

request_sha256:
6765ABDAA3BBBB4A70F1E28EA7B4A339F81ED7A2F9CCC8B9A4CE8BA1DE275045

response_sha256:
41520443BB370919F184CF46441DB897A809EB1B86119B7CF2B6007F20A5B382

response_bytes:
4362

source_base_timestamp:
2026-07-28T08:39:45Z

provider_identity_count:
7

candidate_count:
7

seed_status_counts:
matched=2
ambiguous=1
unmatched=1

cleanup_status:
succeeded

cleanup_residue_count:
0

primary_persistence:
succeeded

emergency_persistence:
not_attempted
```

The authoritative FER ledger records one successful HTTP 200 attempt, an
empty retry list, an accepted response phase, successful primary persistence,
and successful cleanup. The independently authored anchor retains all seven
provider identities exactly once. Its seed accounting contains all three
required states and creates no placeholder for the unmatched seed.

The 11 Resume cases pass offline, including byte replay with zero network
attempts. No second acquisition, route acquisition, provider fallback,
identity selection, or old-work-unit restoration occurred.

```text
OLD_WU2_C5_C6_UNCHANGED:
PROHIBITED

AUTOMATIC_WU2R_RESUME:
PROHIBITED

AUTOMATIC_WU3_WU5_START:
PROHIBITED
```

WU2R_ACQUISITION_COMPLETED
