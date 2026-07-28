# Work Unit 2A Plan · Open Data Anchor Recovery

Plan version: v0.1

Status: PENDING_HUGIN_APPROVAL

Prepared on: 2026-07-28

Execution authorization required:

```text
批准执行 Work Unit 2 Anchor Recovery
```

This Plan freezes only WU2A. It does not authorize execution, a data-source
query, a raw download, fixture creation, adapter/Schema/validator changes,
resumption of WU2 C5/C6, WU3, a push, or a remote.

## 1. 当前 WU2 BLOCKED 证据与历史边界

WU2 remains:

```text
BLOCKED
```

This is a correct R10 outcome, not a failed implementation and not an
absence-of-data conclusion. WU2 stopped before C5 because its single approved
POI acquisition returned a valid but empty Overpass result:

| Field | Measured value |
|---|---|
| Endpoint | `https://overpass-api.de/api/interpreter` |
| Method | `POST` |
| HTTP status | `200` |
| Response date | `2026-07-28T02:52:23Z` |
| Query SHA256 | `32D93312511D093F0EB3E3517ACF9361967941648A96007357AC605FF48BE08E` |
| Response bytes | `424` |
| Response SHA256 | `AD3054C0F768292F03758BC4901C35E21758829D6387A008E864EA4232EBECCB` |
| OSM base | `2026-07-28T02:51:04Z` |
| Area base | `2026-05-12T07:36:16Z` |
| Elements | `0` |

The exact query was:

```overpassql
[out:json][timeout:25];area["name"="婺源县"]["boundary"="administrative"]->.a;nwr(area.a)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"];out center tags;
```

The result proves only that these query bytes produced zero elements at that
endpoint and time. It does not prove that OSM has no Wuyuan data. No response
was committed. No OSRM, Nominatim, or commercial request followed.

The preserved WU2 history is:

```text
4a3242f docs: record approved WU2 plan
a4a91fc docs: record WU2 source and capture gate
cd4f577 chore: add WU2 ingestion interfaces
d01d198 test: add failing WU2 adapter contract cases
352dbbc feat: implement open-data artifact adapters
```

WU2A will not amend, reset, rebase, squash, replace, or reinterpret these
commits. `docs/reviews/work-unit-2-review.md` does not exist because WU2
correctly stopped before C5/C6/C7. That absence is a measured historical fact;
WU2A must not create or backfill the missing WU2 Review.

## 2. 基线与输入

### 2.1 Repository gate

Measured before writing this Plan:

```text
repository: <repo>
branch: main
HEAD: 352dbbcd0b73b3104c85cd02c38442748dcd4b96
worktree: clean
remotes: 0
stashes: 0
```

The WU2A Execute gate will require the same branch and HEAD, zero remotes and
stashes, and a worktree containing only the approved untracked WU2A Plan.

### 2.2 Frozen context

| Path | Bytes | SHA256 / state |
|---|---:|---|
| `PLAN.md` | 9914 | `563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456` |
| `plans/work-unit-2-real-world-ingestion.md` | 32985 | `894D5844E140BF62EC1DB89B1BE318EB4945FF4A0BF8B139E9B82C0B4929BA2C` |
| `docs/wu2-source-decision.md` | 7235 | `E667ABCF6BEBFB522AE0EA76AFDD6EB628E11214B33773045AA5EC8B8C7FEA62` |
| `docs/real-world-source-policy.md` | 13095 | `B89D0836BCC17DD1D52CA215F38EF290134251295ECAC183BA7D54C45A1C4989` |
| `docs/real-world-contract-extension.md` | 14969 | `BD2280BFA2C51F2FEC8521F16BB7DE73667A39142FD89E04F6A515CB42B8963E` |
| `docs/reviews/work-unit-2-review.md` | — | absent because WU2 stopped before C7 |

All WU1/WU1R/WU1C history, all WU2 commits, all 11 Schemas, both validators,
all fixtures, dependency files, and existing tests are frozen. WU2A adds no
dependency and does not install a GIS or OSM parser.

Before C0, hashes for the five existing files above and all 11 Schemas will
be remeasured. A mismatch stops before commit.

## 3. Handbook 状态与影响

Fixed read-only repository:

```text
<handbook>
```

The Plan-stage fetch/reconciliation measured:

```text
local HEAD: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
origin/main: 6502e423ad2a1ab30db7f805e8ebc8fb31fc500b
ahead/behind: 0/0
branch: main
worktree before/after fetch: clean
```

The following were reread only through `git show origin/main:<path>`:

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

WU2A consequences:

- **R10:** an empty successful HTTP response remains empty; it is neither a
  target set nor proof that OSM lacks data. Every count, byte length, hash,
  timestamp, endpoint and selection outcome comes from tooling.
- **PER:** this document is Plan. No investigation call or repository commit
  occurs before Hugin approval. Execute is followed by one independent Review.
- **Scope:** only the four paths in §10 may change. Temporary acquisition bytes
  never become a fifth Git path.
- **Fixture-first:** WU2A creates no semantic fixture. Its executable contract
  validates an investigation ledger and final decision, and establishes a
  focused red before the decision is finalized.

The handbook remains read-only throughout WU2A.

## 4. 问题分析

### 4.1 What the zero result can mean

The original query coupled two independent assumptions:

1. an Overpass area existed with exact tags
   `name=婺源县` and `boundary=administrative`;
2. target objects inside that area used one of six exact primary names.

Official Overpass documentation states that area creation is selective, can
lag the main OSM database, and may skip relations that do not form a valid
area. The response itself reported an area base more than two months older
than the main OSM base. Therefore area resolution is a plausible query-layer
failure, but WU2A will not call it the cause until measured.

### 4.2 OSM model facts relevant to recovery

Primary pages checked during Plan:

```text
https://wiki.openstreetmap.org/wiki/Elements
https://wiki.openstreetmap.org/wiki/Names
https://wiki.openstreetmap.org/wiki/Key:tourism
https://wiki.openstreetmap.org/wiki/Key:historic
https://wiki.openstreetmap.org/wiki/Key:place
https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL
```

Their contract-relevant consequences are:

- OSM objects can be nodes, ways, or relations; all can carry tags.
- `name=*` is the primary real-world label. Other name keys exist, but the
  frozen WU2 adapter deliberately requires `tags.name` and has no label
  fallback.
- `place=*` commonly identifies named settlement centres or outlines.
- `tourism=*` may occur on a node or an area.
- `historic=*` is open-valued and can occur on any OSM object.
- a way/relation `out center` value is a bounding-box centre and is not an
  entrance or field observation.
- a spatial bbox is ordered south, west, north, east; a bbox avoids relying on
  delayed area generation.

The frozen adapter category allowlist is exactly:

```text
amenity
historic
leisure
natural
place
tourism
```

Acquisition may query these explicit keys. It may not invent a category or
map one category into another.

### 4.3 Decision question

WU2A must distinguish three outcomes:

```text
APPROVED_ACQUISITION_RECIPE
  A legal, replayable, traceable Overpass recipe produced at least one
  non-empty response whose selected objects satisfy the frozen adapter input
  boundary. Compatibility with the original WU2 target coverage is explicit.

OPEN_DATA_ROUTE_NOT_FEASIBLE
  The bounded investigation completed, but no response can be selected
  without ambiguity, guessing, contract change, or another prohibited source.
  WU2 remains BLOCKED.

INVESTIGATION_BLOCKED
  WU2A itself could not complete its bounded checks because a required
  official source/policy was inaccessible, bytes could not be safely handled,
  or another §12 blocker occurred.
```

Only the first state may contain an `approved acquisition recipe`. Even then,
WU2 C5/C6 do not resume without a separate Hugin instruction.

## 5. 候选数据源与 license/replay 分析

The source observations below are point-in-time engineering inputs, not legal
advice and not promises that an endpoint or dataset will remain unchanged.

| Candidate | License / replay basis | Current suitability | Decision |
|---|---|---|---|
| OSM via Overpass | OSM data is ODbL 1.0; attribution and share-alike remain explicit; existing WU1C `open_data_anchor` policy already models persistence/replay | Emits the exact JSON object model accepted by the frozen adapter; query can be regional and tag-bounded | **selected conditionally** |
| Geofabrik Jiangxi extract | Download page labels processed data ODbL 1.0 and excludes contributor user/uid/changeset from public files | Page reports a 46.9 MB PBF, 124 MB Shapefile and 125 MB GeoPackage; none is Overpass JSON, and parsing would require an unapproved tool/dependency or a new adapter | **not an anchor; boundary/coverage diagnostic only** |
| Geofabrik Jiangxi `.poly` | Same download site and ODbL attribution surface; technical page says `.poly` is the extract clipping boundary, not an administrative boundary | Small text can provide a non-guessed regional bbox; it must not be represented as county truth | **allowed only to derive the investigation bbox** |
| BBBike custom extract | Uses OSM data and displays OSM attribution; service offers OSM/PBF/GeoJSON and other formats | Requires an extract request and email workflow; output still does not match the frozen adapter; adds external coordination | **not selected** |
| OSM planet/full China extract | ODbL | Planet is unbounded; current China PBF is approximately 1.5 GB and violates the no-national-expansion boundary | **forbidden** |
| Wikidata | Structured data is CC0 and offers traceable entity access | Provider, record shape, category semantics and policy differ from the frozen `provider=osm` / Overpass adapter contract | **not selected; contract remediation would be required** |
| Nominatim or commercial map APIs | Outside the approved open-data route or persistence basis | Explicitly forbidden by WU2A | **forbidden** |

Primary pages:

```text
https://www.openstreetmap.org/copyright
https://osmfoundation.org/wiki/Licence/Attribution_Guidelines
https://download.geofabrik.de/asia/china/jiangxi.html
https://download.geofabrik.de/technical.html
https://download.geofabrik.de/osm-data-in-gis-formats-free.pdf
https://planet.openstreetmap.org/
https://extract.bbbike.org/extract.html
https://www.wikidata.org/wiki/Wikidata:Licensing
https://www.wikidata.org/wiki/Wikidata:Data_access
```

The Geofabrik PBF/GeoPackage/Shapefile and BBBike/Wikidata paths are not
runtime fallbacks. If Overpass cannot yield an adapter-compatible recipe,
WU2A records the negative result instead of switching source.

## 6. Acquisition 策略

### 6.1 Bounded call budget

WU2A Execute may make only:

```text
1 GET:
  Geofabrik Jiangxi .poly, for a regional bbox only

at most 3 POST requests:
  the pre-registered Overpass query ladder below

at most 1 transport retry total:
  same endpoint and byte-identical request only
```

HTTP 200 with zero elements, a valid provider error, ambiguous content, or a
policy failure is not a transport failure and is not retryable. No alternate
Overpass instance is introduced during Execute. No OSRM call is part of WU2A.

Every call records:

```text
attempt_id
request purpose
query/request UTF-8 bytes
query/request SHA256
endpoint and method
started_at / completed_at
HTTP status
response byte length
response SHA256
content type
provider/source base timestamp when present
element count
temporary path category (never the absolute user path)
temporary deletion result and residue count
selection predicate
selection result and reason
```

Raw bytes are held only in a random system-temporary file, parsed with the
Python standard library, hashed before parsing, and deleted in `finally`.
Only the measured ledger and the minimal `(type, id, tags.name, matched
category keys, coordinate shape present)` selection summary enter the
decision document. `coordinate_shape` may state `node_lat_lon` or
`reported_center`; it never stores the numeric pair. No raw response,
coordinate pair, response excerpt, fixture, or repository temporary file is
committed by WU2A.

### 6.2 Bbox derivation

The Execute step fetches:

```text
https://download.geofabrik.de/asia/china/jiangxi.poly
```

The standard library parser accepts only the documented text polygon form,
computes the min/max coordinate bounds from explicit numeric vertices, and
records the source hash and derived south/west/north/east. It does not call the
clip polygon an administrative boundary. A parse error, empty polygon,
out-of-range coordinate, or unexpected extra content blocks WU2A.

### 6.3 Query ladder

The following templates are frozen. Execute substitutes only values captured
by an earlier approved step. Executed query bytes use UTF-8 without BOM and LF
line endings; the final substituted bytes, not the template, receive the
recorded SHA256.

#### O1 — exact scope discovery inside the sourced Jiangxi bbox

```overpassql
[out:json][timeout:25][bbox:{SOUTH},{WEST},{NORTH},{EAST}];
(
  rel["boundary"="administrative"]["name"="婺源县"];
  rel["boundary"="administrative"]["name:zh"="婺源县"];
  nwr["place"]["name"="婺源"];
  nwr["place"]["name:zh"="婺源"];
);
out center tags;
```

O1 does not select a target by distance or similarity. A county relation may
feed O2 only when one relation is uniquely supported by explicit boundary,
name/name:zh and admin tags in the returned bytes. If zero or multiple
relations remain, O2 is skipped; O3 may still perform the regional exact-name
check.

#### O2 — exact target names in the unique relation area

```overpassql
[out:json][timeout:25];
rel(id:{CAPTURED_RELATION_ID})->.county;
.county map_to_area->.scope;
(
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["amenity"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["historic"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["leisure"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["natural"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["place"];
  nwr(area.scope)["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["tourism"];
);
out center tags;
```

The regular expression is an anchored finite exact-name set, not a fuzzy
match. O2 runs only after an unambiguous O1 relation.

#### O3 — exact target names in the sourced Jiangxi bbox

```overpassql
[out:json][timeout:25][bbox:{SOUTH},{WEST},{NORTH},{EAST}];
(
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["amenity"];
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["historic"];
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["leisure"];
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["natural"];
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["place"];
  nwr["name"~"^(婺源县|婺源|江岭|篁岭|李坑|庆源)$"]["tourism"];
);
out center tags;
```

O3 is the only pre-registered bypass for missing or stale Overpass areas. It
does not broaden names, categories, or geographic coverage.

### 6.4 Deterministic selection

A response may support the recipe only when every selected object:

- is `node`, `way`, or `relation`;
- has a unique `(type, id)`;
- has a non-empty primary `tags.name`;
- has at least one frozen category key with a non-empty string value;
- has `lat/lon` for a node or explicit `center.lat/center.lon` for a
  way/relation;
- can be matched by exact primary name from the finite set above;
- is not chosen by distance, popularity, source order, first-result behavior,
  language fallback, or human/LLM semantic resemblance.

For each exact seed, zero matches remain absent and multiple matches remain
ambiguous. Neither condition is repaired. The final document reports the
actual selected count; it never rounds the count to five.

An approved recipe additionally states one of:

```text
WU2_C5_COMPATIBLE
  The captured target identities satisfy the existing WU2 C5 target and route
  endpoint prerequisites.

ADAPTER_COMPATIBLE_ONLY
  A legal adapter-compatible open-data response exists, but the original WU2
  target coverage is not met. WU2 C5 must not resume without a separate Plan
  or Hugin ruling.
```

The second label can complete WU2A research but cannot silently loosen WU2.

### 6.5 Reproducibility meaning

OSM is mutable. A future rerun of the same query is not required or expected
to have the same response hash. WU2A reproducibility means:

1. the exact executed query bytes and their SHA256 are recoverable;
2. the endpoint, timestamps, response hash and count for the historical
   attempt are recorded;
3. the selection predicate is deterministic;
4. a rerun can be compared as a new attempt rather than rewriting history.

Tests never call a live endpoint and never assert that mutable OSM must return
an old response hash.

## 7. 禁止 fallback

WU2A has no fallback to:

- Nominatim, 高德, 百度, 腾讯, Google, a webpage scraper or a travelogue;
- a second Overpass instance or an unregistered fourth query;
- a China-wide/planet extract;
- a Geofabrik/BBBike/Wikidata object relabeled as an Overpass response;
- manual coordinates, an LLM-supplied ID, nearest-result logic, fuzzy name
  choice, transliteration, `name:zh` as an adapter label, or first-result
  selection;
- guessed CRS, provider, category, permission, status, timestamp, route or
  endpoint;
- a synthetic response represented as a real anchor;
- an empty response represented as success.

If the query ladder cannot make a deterministic selection, the final decision
is negative and WU2 stays BLOCKED.

## 8. 测试策略

WU2A does not test adapters, evidence mapping, routing, planning, or POI
quality. It adds one standard-library test module that parses machine-readable
JSON blocks in `docs/wu2a-anchor-decision.md`.

Pre-registered cases: 12.

```text
A01 decision document is strict UTF-8
A02 acquisition ledger JSON block is unique and parseable
A03 every attempt has the complete fixed field set
A04 query SHA256 recomputes from recorded UTF-8 query bytes
A05 endpoint/method and maximum-call budget are allowlisted
A06 HTTP status, byte count, response hash, timestamps and element count types
A07 every temporary capture records deletion success and residue zero
A08 ODbL identifier, URL, attribution, replay and fixture policy are explicit
A09 candidate-source table records selected/rejected reason for every option
A10 forbidden-source call counts and committed raw-byte count are zero
A11 minimal selected summaries satisfy the declared deterministic predicate
A12 final decision is non-pending and recipe/negative-result fields agree
```

The C2 red command is:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_wu2a_acquisition_decision -v
```

C2 expected result:

```text
tests: 12
passed: 11
failures: 1
errors: 0
red ID: A12
cause: decision_status is explicitly INVESTIGATION_IN_PROGRESS
```

Import, dependency, PowerShell, path, missing-file, syntax, malformed-test and
network errors must be zero. The test contains independent expected field
sets and hashes the recorded query text itself; no acquisition function
generates expected values.

C3 modifies only the decision document and uses the character-identical
command for:

```text
tests: 12
passed: 12
failures: 0
errors: 0
```

The full non-network regression command is:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_schema_validation tests.test_fixture_validation tests.wu1c_contract_compatibility_cases tests.test_wu2_adapters tests.test_wu2a_acquisition_decision -v
```

Expected total after C3 is 145 tests: 115 WU1/WU1C, 18 WU2 adapter, and
12 WU2A decision cases. Final numbers come from actual unittest output.

## 9. Anchor Acquisition Decision contract

`docs/wu2a-anchor-decision.md` has these fixed sections:

```text
1. WU2 blocker preserved
2. official-source observations
3. OSM tag/element/query analysis
4. candidate-source decision matrix
5. machine-readable acquisition ledger
6. selection analysis
7. license, attribution and replay decision
8. approved acquisition recipe or negative conclusion
9. WU2 compatibility classification
10. limitations and non-capabilities
```

The machine-readable ledger records attempts, not raw responses. During C1
its final state is explicitly `INVESTIGATION_IN_PROGRESS`. C3 changes only the
decision section and status after all bounded attempts are recorded.

An approved recipe contains:

```yaml
source: OSM through Overpass
endpoint:
method:
query_utf8:
query_sha256:
geographic_scope:
selection_predicate:
observed_element_count:
observed_response_sha256:
license:
  identifier: ODbL-1.0
  url: https://opendatacommons.org/licenses/odbl/1-0/
  attribution: © OpenStreetMap contributors
replay_policy:
compatibility:
limitations:
```

It is a reviewed acquisition instruction, not a fixture and not proof that a
future mutable response will be byte-identical.

## 10. 精确 Scope 与 commit 序列

### 10.1 Four-path whitelist

Only these repository paths may be created:

```text
plans/work-unit-2-anchor-recovery.md
docs/wu2a-anchor-decision.md
tests/test_wu2a_acquisition_decision.py
docs/reviews/work-unit-2a-review.md
```

System-temporary acquisition files are not repository paths and must be
deleted before each attempt completes. No `runtime/` output is authorized.

Protected paths include:

```text
PLAN.md
plans/work-unit-2-real-world-ingestion.md
docs/wu2-source-decision.md
docs/reviews/work-unit-2-review.md
src/trip_decider/**
schemas/**
fixtures/**
scripts/**
all existing tests
pyproject.toml
requirements.lock
.gitignore
all WU0/WU1/WU1R/WU1C history
handbook and every other repository
user/system configuration
```

### 10.2 Linear commits

| Step | Exact message | Paths | Gate |
|---|---|---|---|
| WU2A-C0 | `docs: record approved anchor recovery plan` | approved Plan only | Plan hash and Execute baseline match approval |
| WU2A-C1 | `docs: record open-data investigation` | decision document only | bounded calls complete or explicit investigation blocker recorded; all raw temp bytes deleted |
| WU2A-C2 | `test: add acquisition reproducibility cases` | new test only | valid 12-case 11/1 red; no infrastructure/network error |
| WU2A-C3 | `docs: finalize anchor decision` | decision document only | same command 12/12 green; no test change |
| WU2A-C4 | `docs: prepare WU2A review` | WU2A Review only | full 145-case regression and independent evidence checks green |

No commit is amended, squashed, rebased, reset, or rewritten. C2 remains as
the valid red commit. WU2A-C1 may end with a documented external investigation
blocker; in that case C2-C4 are not started and WU2A stops.

## 11. 完成判定

WU2A pre-registers exactly 18 criteria:

1. Execute starts at `main@352dbbc`, with only the approved Plan untracked,
   zero remotes and zero stashes.
2. The five WU2 commits remain byte/history-identical and WU2 remains
   explicitly BLOCKED at the start of WU2A.
3. The missing WU2 Review is reported as absent and is not created or
   backfilled.
4. Handbook fetch/reconciliation and all eight `origin/main` rereads are
   recorded; handbook remains unchanged.
5. Frozen product, WU2 Plan/source-policy/contract and all 11 Schema hashes
   remain unchanged.
6. Every license, endpoint, tag-model and extract claim in the decision uses
   an opened primary/project source and records its checked date.
7. Execution stays within one `.poly` GET, three Overpass POSTs and at most one
   byte-identical transport retry; actual call counts are reported.
8. Every executed attempt records exact request bytes/hash, endpoint,
   timestamps, HTTP result, response bytes/hash/count and selection reason.
9. Every temporary response is deleted with measured residue zero; committed
   raw responses, coordinates and fixtures remain zero.
10. Nominatim, commercial maps, alternate Overpass instances, BBBike,
    Wikidata query services, national extracts and OSRM receive zero calls.
11. Candidate sources have explicit license/replay/format/dependency analysis;
    open licensing is not treated as adapter compatibility.
12. Selection uses only exact source fields and the frozen deterministic
    predicate; no LLM, fuzzy/nearest/first result, guessed field or silent
    fallback is used.
13. C2 records the valid 12-case 11-pass/1-failure red with A12 as the only
    failure and zero infrastructure errors.
14. C3 uses the character-identical command for 12/12 green without modifying
    the test.
15. Full regression reports 145/145 green: 115 WU1/WU1C, 18 WU2 and 12 WU2A.
16. The final document contains either a complete approved recipe with an
    explicit WU2 compatibility class or a fully evidenced negative conclusion;
    no partial result is labeled approved.
17. Git history is the five planned commits and the final diff is exactly the
    four-path whitelist; dependency, adapter, Schema, validator and fixture
    diffs are zero.
18. WU2A Review independently reports Git, hashes, source access, call budget,
    temp deletion, red/green, full regression, secrets/fallback/scope scans and
    all 18 criteria, ending only as `READY_FOR_HUGIN_REVIEW`, `BLOCKED`, or
    `INCOMPLETE`.

Finding approximately five attractions is not itself the completion standard.
WU2A is complete when it has either a legal, replayable, traceable,
adapter-compatible acquisition recipe or a bounded, evidenced negative
conclusion. A completed negative investigation may be
`READY_FOR_HUGIN_REVIEW` while WU2 itself remains BLOCKED.

## 12. Blocking

Stop WU2A before the next commit when:

- the baseline, approved Plan hash, handbook state, frozen input or Schema
  hashes differ;
- a required primary license/policy/technical page is inaccessible or no
  longer supports the recorded classification;
- the `.poly` cannot be parsed without guessing or cannot be classified for
  this bounded diagnostic use;
- the bounded query ladder or one total transport retry is insufficient;
- an object identity, category, primary name, coordinate presence, source
  class, CRS, permission, timestamp or selection remains ambiguous;
- raw bytes, contributor personal metadata, a credential, secret, coordinate
  list or unapproved response would need to enter Git;
- progress needs a commercial API, Nominatim, alternate endpoint, web
  scraping, travelogue, LLM judgment, manual POI, nationwide extract, real
  fixture, OSRM call, or synthetic-as-real data;
- progress needs an adapter, Schema, validator, fixture/source-policy,
  dependency, business module, runtime, fifth Git path, or existing-test
  change;
- WU2 history or its absent Review would need alteration;
- an acquisition test needs live network access;
- WU2 C5/C6, WU3, recommendation, planning, ranking, route optimization or
  evidence scoring becomes necessary.

On a blocker, preserve only completed approved WU2A commits, record the exact
access/command result, and stop. Do not improvise another source or query and
do not prepare a continuation Plan without Hugin direction.

## 13. Review evidence

WU2A-C4 may create only `docs/reviews/work-unit-2a-review.md`. It will include:

- start/final HEAD, five-commit log, full diff/stat and four-path reconciliation;
- frozen hashes and handbook before/after reconciliation;
- WU2 BLOCKED history and missing WU2 Review preservation;
- every official source URL/access result and the complete attempt ledger;
- actual request counts, response hashes/counts and temp residue evidence;
- C2 red and character-identical C3 green evidence;
- full regression counts and exit code;
- scans for Nominatim/commercial endpoints in executable changes, secret
  patterns, silent fallback, `infer_*`/`guess_*`, raw response signatures and
  scope drift;
- all 18 completion criteria marked `✓`, `⚠`, or `✗`;
- explicit statements that no fixture/adapter/Schema/validator/dependency was
  changed, WU2 C5/C6 did not resume, and WU3 did not start.

After Review, WU2A stops for Hugin review. It never automatically resumes WU2.
