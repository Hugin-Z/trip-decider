# Verification levels

trip-decider uses three verification levels. A green result at one level does
not stand in for either of the others.

## A. CI / offline regression

CI runs on every pull request and every push to `main`, on the supported Python
3.11 line. It installs `requirements-dev.lock`, then runs:

```powershell
python -m ruff check src
python -m pyright
python -m pytest -q
```

This level is deterministic and requires no API credentials. The pytest suite
uses fixtures, controlled collectors and mocks; it does not run the live smoke
or soak scripts. CI verifies repository logic and contracts, not whether an
external provider is currently reachable or returning useful data. A transport
test may use a loopback-only local server; no provider endpoint is required.

## B. Live smoke

Live smoke is a manual integration check against the providers as they behave
now. It requires network access and `AMAP_WEB_SERVICE_KEY`; 12306 access is also
network-dependent even though it needs no credential.

```powershell
python scripts\smoke_live.py
python scripts\smoke_action_loop.py
```

These scripts check that current provider responses can pass through the live
collectors and product action loop. One successful run does not establish
long-term reliability, national coverage or data correctness beyond the
observed inputs.

## C. Soak

Soak repeatedly exercises the real action loop under provider timing and data
variation. It is a manual release gate, not a normal CI job, because it consumes
credentials, network access, provider quota and several minutes of wall time.

```powershell
python scripts\soak_full_loop.py --rounds 20
```

A green soak means every sampled round reached a terminal state recognized by
the probe under that run's conditions. It does not mean every candidate produced
a plan, and it does not prove future provider availability.
