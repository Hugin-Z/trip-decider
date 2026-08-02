"""Shared fixtures and scanners for the I1-I9 invariant tests.

This module is deliberately not named ``test_*`` so ``unittest discover`` does
not collect it.  It owns three things:

* the forbidden key/value vocabularies that I1 and I6 scan for;
* a parser for the authoritative data_type registry in
  ``docs/contracts/freshness-policy.md`` section 2.2;
* an offline run driver that produces a complete run directory without
  network access, used by I1 and I5.

Nothing here asserts.  Assertions live in the individual invariant tests.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
from pathlib import Path
import re

from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.trip_application import TripApplicationService
from trip_decider.trip_query import TripQueryService
from trip_decider.travel_agent import (
    EvidenceItem,
    EvidenceStatus,
    InMemoryAgentStore,
    TaskMode,
    TravelIntent,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
CONTRACTS_ROOT = REPO_ROOT / "docs" / "contracts"
FRESHNESS_POLICY_DOC = CONTRACTS_ROOT / "freshness-policy.md"
MCP_APP_HTML = SRC_ROOT / "trip_decider" / "mcp_app_workspace_v1.html"
WEB_APP_JS = SRC_ROOT / "trip_decider" / "web" / "app.js"


# --------------------------------------------------------------------------
# I1 vocabularies (docs/contracts/invariants.md I1)
# --------------------------------------------------------------------------

FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "display_status",
        "display_rule",
        "evidence_status",
        "schedule_status",
        "snapshot_status",
        "fare_status",
        "timing_status",
        "expires_at",
        "displayable",
        "planning_state",
    }
)

FORBIDDEN_VALUES: frozenset[str] = frozenset(
    {
        "verified",
        "sourced_stale",
        "sourced_undated",
        "estimated_stale",
        "estimated_undated",
        "LIVE",
        "STALE",
        "MISSING",
        "DISPLAYABLE_CONDITIONAL_ITINERARY",
        "SUPPLEMENTING_DATA",
        "sourced_live_snapshot",
        "sourced_stale_snapshot",
    }
)

ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "support",
        "retrieved_at",
        "effective_at",
        "data_type",
        # 采集元数据，非展示态（evidence-axes.md §3.4）。它记录发生过什么，
        # 不记录该怎么显示，因此可持久化。
        "refresh_failure",
        "local_transit_refresh_failure",
    }
)


# --------------------------------------------------------------------------
# I2 / I6 vocabularies (docs/contracts/evidence-axes.md section 4.1)
# --------------------------------------------------------------------------

SUPPORT_VALUES: frozenset[str] = frozenset(
    {"sourced", "estimated", "conflicting", "unknown"}
)
FRESHNESS_VALUES: frozenset[str] = frozenset({"fresh", "stale", "undated"})

TOKEN_TABLE: dict[tuple[str, str], str] = {
    ("sourced", "fresh"): "verified",
    ("sourced", "stale"): "sourced_stale",
    ("sourced", "undated"): "sourced_undated",
    ("estimated", "fresh"): "estimated",
    ("estimated", "stale"): "estimated_stale",
    ("estimated", "undated"): "estimated_undated",
    ("conflicting", "fresh"): "conflicting",
    ("conflicting", "stale"): "conflicting",
    ("conflicting", "undated"): "conflicting",
    ("unknown", "fresh"): "unknown",
    ("unknown", "stale"): "unknown",
    ("unknown", "undated"): "unknown",
}

# The token literals I6 scans for.  Bare ``unknown``/``conflicting``/
# ``estimated``/``sourced`` are excluded: they are ordinary words that appear
# throughout the tree for unrelated reasons, so scanning them would report
# noise rather than parallel token implementations.
SCANNED_TOKEN_LITERALS: frozenset[str] = FORBIDDEN_VALUES

# I9 place-name seed list.  Derived once from the 28 ``name`` values in
# src/trip_decider/destination_catalog.json plus the places named in
# PRODUCT.md:22 and PRODUCT.md:50-56 as the one verified chain.  See
# docs/contracts/invariants.md I9 for why this list is maintained by hand.
CITY_LITERAL_SEEDS: tuple[str, ...] = (
    "婺源",
    "上饶",
    "三清山",
    "武汉",
    "篁岭",
    "江岭",
    "李坑",
    "庆源",
    "杭州",
    "绍兴",
    "黄山",
    "景德镇",
    "衢州",
    "南昌",
    "九江",
    "庐山",
    "宏村",
    "西递",
    "千岛湖",
    "莫干山",
)

I9_WHITELIST_DIRS: tuple[str, ...] = (
    "tests",
    "fixtures",
    "examples",
    "docs",
    "schemas",
    "plans",
)


# --------------------------------------------------------------------------
# JSON walking
# --------------------------------------------------------------------------


def iter_json_documents(root: Path) -> Iterator[tuple[Path, object]]:
    """Yield every parsed .json document and .jsonl record beneath ``root``."""

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".json":
            try:
                yield path, json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
        elif path.suffix == ".jsonl":
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for line in lines:
                if not line.strip():
                    continue
                try:
                    yield path, json.loads(line)
                except json.JSONDecodeError:
                    continue


def walk_scalars(
    document: object,
    pointer: str = "",
) -> Iterator[tuple[str, str | None, object]]:
    """Yield ``(pointer, key, value)`` for every scalar in ``document``."""

    if isinstance(document, Mapping):
        for key, value in document.items():
            child = f"{pointer}/{key}"
            if isinstance(value, (Mapping, list)):
                yield from walk_scalars(value, child)
            else:
                yield child, str(key), value
    elif isinstance(document, list):
        for index, value in enumerate(document):
            child = f"{pointer}[{index}]"
            if isinstance(value, (Mapping, list)):
                yield from walk_scalars(value, child)
            else:
                yield child, None, value


# --------------------------------------------------------------------------
# Registry parsing (docs/contracts/freshness-policy.md section 2.2)
# --------------------------------------------------------------------------

_REGISTRY_ROW = re.compile(
    r"^\|\s*`(?P<data_type>[a-z_]+)`"
    r"\s*\|\s*`(?P<status>active|planned|reserved)`"
    r"\s*\|\s*`(?P<tolerance_seconds>\d+)`"
    r"\s*\|\s*`(?P<max_reuse_seconds>\d+)`"
    r"\s*\|\s*`(?P<stale_allowed>True|False)`"
    r"\s*\|\s*`(?P<on_stale>auto_refetch|flag_for_confirmation|block)`"
    r"\s*\|\s*(?P<feasibility_critical>是|否)"
    r"\s*\|\s*(?P<planned_for>[^|]*?)\s*\|\s*$"
)


def parse_policy_registry(
    document: Path = FRESHNESS_POLICY_DOC,
) -> dict[str, dict[str, object]]:
    """Parse the authoritative data_type registry out of the contract."""

    registry: dict[str, dict[str, object]] = {}
    for line in document.read_text(encoding="utf-8").splitlines():
        match = _REGISTRY_ROW.match(line.strip())
        if match is None:
            continue
        values = match.groupdict()
        planned_for = values["planned_for"].strip()
        registry[values["data_type"]] = {
            "status": values["status"],
            "tolerance_seconds": int(values["tolerance_seconds"]),
            "max_reuse_seconds": int(values["max_reuse_seconds"]),
            "stale_allowed": values["stale_allowed"] == "True",
            "on_stale": values["on_stale"],
            "feasibility_critical": values["feasibility_critical"] == "是",
            "planned_for": "" if planned_for in {"—", "-", ""} else planned_for,
        }
    return registry


# ``data_type`` is bound either directly or through a conditional expression
# (evidence_broker.py:317 picks between two literals on one line), so the
# scanner takes everything to the right of the binding and collects every
# string literal it finds there.
_DATA_TYPE_BINDING = re.compile(r"data_type\s*=(?!=)\s*(?P<rest>.+)$")
_STRING_LITERAL = re.compile(r"\"([a-z_]+)\"|'([a-z_]+)'")


def scan_produced_data_types(
    root: Path = SRC_ROOT,
    *,
    known: frozenset[str] | None = None,
) -> dict[str, list[str]]:
    """Return ``data_type -> ["file:line", ...]`` for every producer in src.

    ``known`` filters the collected literals down to registered data_type
    names so unrelated keyword strings on the same line are not reported.
    """

    produced: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            binding = _DATA_TYPE_BINDING.search(line)
            if binding is None:
                continue
            location = f"{path.relative_to(REPO_ROOT).as_posix()}:{number}"
            for first, second in _STRING_LITERAL.findall(binding.group("rest")):
                literal = first or second
                if literal == "data_type":
                    continue
                if known is not None and literal not in known:
                    continue
                produced.setdefault(literal, []).append(location)
    return produced


# --------------------------------------------------------------------------
# Source scanning
# --------------------------------------------------------------------------


def scan_literals(
    literals: frozenset[str] | tuple[str, ...],
    *,
    root: Path = SRC_ROOT,
    suffixes: tuple[str, ...] = (".py", ".json", ".html", ".js", ".css"),
    quoted_only: bool = False,
) -> list[tuple[str, int, str]]:
    """Return ``(relative_path, line_number, literal)`` for every hit."""

    hits: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if "__pycache__" in path.parts:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        for number, line in enumerate(lines, start=1):
            for literal in literals:
                needles = (
                    (f'"{literal}"', f"'{literal}'")
                    if quoted_only
                    else (literal,)
                )
                if any(needle in line for needle in needles):
                    hits.append((relative, number, literal))
    return hits


# --------------------------------------------------------------------------
# Offline run driver (I1, I5)
# --------------------------------------------------------------------------


class NoBackgroundApplication(TripApplicationService):
    """Run every stage on the calling thread so tests stay deterministic."""

    @staticmethod
    def _spawn(*, target: object, args: object, name: str) -> None:
        del target, args, name


def noop_collector(intent: TravelIntent) -> EvidenceItem:
    """A collector that never touches the network and never succeeds.

    I5 requires this: once P5 lands auto_refetch, a second read would
    otherwise replace the evidence between the two reads and make the test
    flap.  A no-op collector keeps both reads observing the same evidence.
    """

    del intent
    return EvidenceItem(
        evidence_id="invariant-noop",
        domain="railway",
        status=EvidenceStatus.MISSING,
        value=None,
        missing_reason="collector_not_configured",
    )


def offline_intent() -> dict[str, object]:
    return {
        "task_mode": "GUIDED_DISCOVERY",
        "origin": "甲地",
        "destination_anchor": "乙地区",
        "destination_expression": "倾向乙地区",
        "earliest_departure_at": "2026-08-04T12:00",
        "latest_return_at": "2026-08-07T22:00",
        "travelers": 2,
        "total_budget_cny": 6000,
        "pace": "relaxed",
        "transport_preferences": ["rail"],
        "themes": ["自然", "古村"],
    }


# 这三个 fixture 暂不收编到 tests/evidence_factory。P4-b 试过一次：工厂的默认
# 拓扑（景点数、路线段命名）与规划器接续「跨城铁路 → 车站 → 住宿片区 → 景点」
# 的期望不符，动作循环走不到计划安装，于是 I1 的落盘测量少了 plan-version 与
# plans/ 两个文件——测量本身变得不可信。
#
# 收编前需要先搞清规划器对证据拓扑的确切要求（p4a-fixture-shapes.md §3 的
# 「其余构造点收编」一项）。在那之前保留字面形状，宁可重复也不要让测量说谎。


def controlled_railway() -> EvidenceItem:
    retrieved_at = "2026-08-01T09:00:00+08:00"
    return EvidenceItem(
        evidence_id="controlled-railway",
        domain="railway",
        status=EvidenceStatus.SOURCED,
        value={
            "evidence_status": "sourced",
            "domain": "railway",
            "origin": "甲站",
            "destination": "乙站",
            "outbound": {
                "train_code": "G100",
                "origin_station": "甲站",
                "destination_station": "乙站",
                "departure_at": "2026-08-04T13:00",
                "arrival_at": "2026-08-04T16:00",
                "duration_seconds": 10800,
                "second_class_fare_cny_per_person": 200.0,
                "second_class_availability": "available",
            },
            "return": {
                "train_code": "G101",
                "origin_station": "乙站",
                "destination_station": "甲站",
                "departure_at": "2026-08-07T18:00",
                "arrival_at": "2026-08-07T21:00",
                "duration_seconds": 10800,
                "second_class_fare_cny_per_person": 200.0,
                "second_class_availability": "available",
            },
            "snapshot": {
                "status": "LIVE",
                "retrieved_at": retrieved_at,
                "attempted_at": retrieved_at,
                "availability_semantics": "current_at_retrieval_only",
                "display": "LIVE",
            },
            "roundtrip_fare_cny": 800.0,
            "roundtrip_duration_seconds": 21600,
        },
        sources=(
            {"provider": "controlled-rail", "retrieved_at": retrieved_at},
        ),
    )


def controlled_map() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="controlled-map",
        domain="map",
        status=EvidenceStatus.SOURCED,
        value={
            "destination": {"name": "乙地"},
            "retrieved_at": "2026-08-01T09:00:00+08:00",
            "local_transit": [
                {
                    "route_id": "route-station-base",
                    "from": "乙站",
                    "to": "住宿片区",
                    "duration_seconds": 1800,
                    "distance_meters": 12000,
                    "fare": {"status": "unknown", "amount_cny": None},
                },
                {
                    "route_id": "route-base-spot",
                    "from": "住宿片区",
                    "to": "景点甲",
                    "duration_seconds": 1200,
                    "distance_meters": 6000,
                    "fare": {"status": "unknown", "amount_cny": None},
                },
            ],
        },
        sources=(
            {
                "provider": "controlled-map",
                "retrieved_at": "2026-08-01T09:00:00+08:00",
            },
        ),
    )


def controlled_web() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="controlled-web",
        domain="web",
        status=EvidenceStatus.SOURCED,
        value={
            "destination_official_name": "乙地",
            "retrieved_at": "2026-08-01T09:00:00+08:00",
            "verified_facts": [
                {
                    "field": "official_administrative_name",
                    "value": "乙地",
                }
            ],
            "attractions": [
                {
                    "attraction_id": "spot-1",
                    "name": "景点甲",
                    "visit_minutes": 90,
                }
            ],
            "hotel_area": {"name": "住宿片区"},
        },
        sources=(
            {
                "publisher": "controlled-web",
                "retrieved_at": "2026-08-01T09:00:00+08:00",
            },
        ),
    )


def controlled_option() -> dict[str, object]:
    """One candidate card in the shape guided_discovery.py:548-590 emits."""

    return {
        "destination_id": "option-one",
        "destination_anchor": "乙地",
        "name": "乙地",
        "region_label": "乙地区",
        "gateway_checked": "乙站",
        "feasibility_status": "CONDITIONALLY_FEASIBLE",
        "coarse_plan_status": "CONDITIONALLY_FEASIBLE",
        "roundtrip_transport": {
            "token": "verified",
            "duration_seconds": 21600,
            "known_cost_cny": 800.0,
            "outbound": None,
            "return": None,
            "retrieved_at": "2026-08-01T09:00:00+08:00",
            "missing_reason": None,
            "from_cache": False,
            "timed_out": False,
        },
        "playable_time_seconds": 280800.0,
        "local_transport_difficulty": {"status": "MISSING", "value": None},
        "themes": ["自然", "古村"],
        "physical_intensity": "适中",
        "budget_headroom_after_known_transport_cny": 5200.0,
        "evidence_statuses": [
            {
                "domain": domain,
                "token": "verified",
                "collected_at": "2026-08-01T09:00:00+08:00",
                "from_cache": False,
                "timed_out": False,
            }
            for domain in ("railway", "map", "web")
        ],
        "evidence_missing": ["住宿价格与可用性"],
    }


def controlled_comparison(intent: object, **arguments: object) -> dict[str, object]:
    """A comparison builder that emits the same progress a live one would."""

    del intent
    option = controlled_option()
    progress = arguments.get("progress")
    if callable(progress):
        progress("comparison_started", "乙地区", {"candidate_count": 1})
        progress(
            "candidate_completed",
            "乙地",
            {
                "destination_id": "option-one",
                "feasibility_status": option["feasibility_status"],
                "option": option,
            },
        )
    return {
        "stage": "guided_discovery",
        "task_mode": "GUIDED_DISCOVERY",
        "region_anchor": "乙地区",
        "expected_option_count": 1,
        "option_count": 1,
        "cancelled": False,
        "options": [option],
        "reusable_evidence": {
            "option-one": {
                item.domain: item.to_dict()
                for item in (
                    controlled_railway(),
                    controlled_map(),
                    controlled_web(),
                )
            }
        },
        "selection_required": True,
        "detailed_plan_created": False,
        "conditions": [],
    }


def build_offline_services(
    sessions_root: Path,
) -> tuple[TripApplicationService, TripQueryService]:
    """Build one isolated runtime that never reads runtime/sessions."""

    store = InMemoryAgentStore(sessions_root)
    application = NoBackgroundApplication(
        store=store,
        evidence_broker=EvidenceBroker(sessions_root.parent / "evidence-cache"),
        railway_collector=noop_collector,
        map_collector=noop_collector,
        web_collector=noop_collector,
        comparison_builder=controlled_comparison,
    )
    query = TripQueryService(store=store, application_service=application)
    return application, query


def drive_offline_run(sessions_root: Path) -> tuple[
    TripApplicationService,
    TripQueryService,
    str,
]:
    """Drive one guided run to an installed plan without any network call.

    Every stage goes through the real application path; only the collectors
    and the comparison builder are injected.  Because ``_spawn`` is neutered
    the background body is invoked directly on this thread, which keeps the
    run deterministic while still emitting the events a live run emits.
    """

    application, query = build_offline_services(sessions_root)
    run = application.create_trip(offline_intent())
    application.confirm_trip(run.run_id)
    application.execute_trip(run.run_id)
    application._candidate_comparison_background(
        run.run_id,
        TaskMode.GUIDED_DISCOVERY,
    )
    application.select_candidate(run.run_id, "option-one")
    application.execute_trip(run.run_id)
    return application, query, run.run_id


__all__ = [
    "ALLOWED_KEYS",
    "CITY_LITERAL_SEEDS",
    "CONTRACTS_ROOT",
    "FORBIDDEN_KEYS",
    "FORBIDDEN_VALUES",
    "FRESHNESS_POLICY_DOC",
    "FRESHNESS_VALUES",
    "I9_WHITELIST_DIRS",
    "MCP_APP_HTML",
    "REPO_ROOT",
    "SCANNED_TOKEN_LITERALS",
    "SRC_ROOT",
    "SUPPORT_VALUES",
    "TOKEN_TABLE",
    "WEB_APP_JS",
    "build_offline_services",
    "controlled_map",
    "controlled_railway",
    "controlled_web",
    "drive_offline_run",
    "iter_json_documents",
    "noop_collector",
    "offline_intent",
    "parse_policy_registry",
    "scan_literals",
    "scan_produced_data_types",
    "walk_scalars",
]
