# trip-decider architecture

The current implementation is documented in
[`CURRENT_ARCHITECTURE.md`](../CURRENT_ARCHITECTURE.md).

The former contents of this file described the pre-implementation A–H artifact
contract and were marked `DOCUMENT_CONTRACT_ONLY`. That proposed directory tree,
the `TRIP_DECIDER_AMAP_API_KEY` variable and destination pass-through behavior
do not describe the running product and have therefore been retired.

Current configuration uses `AMAP_WEB_SERVICE_KEY`. Current runtime state is
stored under `runtime/sessions/`, with evidence in
`evidence/current.json` and `evidence/guided-comparison.json`. The online
application/query services are the sole product path; the old offline artifact
pipeline is not part of the repository.

The support/freshness contract remains authoritative under `docs/contracts/`,
and `evidence_core.py` is its implementation kernel.
