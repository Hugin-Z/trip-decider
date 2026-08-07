"""City-neutral runtime composition for one destination planning run."""

from __future__ import annotations

from collections.abc import Mapping
import time
from typing import Protocol

from trip_decider.evidence_core import SUPPORT_UNKNOWN
from trip_decider.intercity_rail import query_intercity_rail
from trip_decider.itinerary_planner import (
    plan_destination_context,
    revise_destination_plan,
    validate_destination_plan,
)
from trip_decider.simple_live import _LiveFailure, query_destination_district
from trip_decider.travel_agent import (
    DestinationCollectors,
    EvidenceItem,
    EvidenceStatus,
    Revision,
    ToolEvent,
    TaskMode,
    TravelIntent,
    execute_destination_pipeline,
)


class DestinationEvidenceProvider(Protocol):
    """Provider boundary used to collect one evidence domain."""

    def __call__(self, intent: TravelIntent) -> EvidenceItem:
        ...


def _missing_evidence(
    domain: str,
    reason: str,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"{domain}-missing",
        domain=domain,
        status=EvidenceStatus.MISSING,
        value=None,
        missing_reason=reason,
    )


def collect_railway_evidence(intent: TravelIntent) -> EvidenceItem:
    """Query arbitrary stations or preserve the absent fields as missing."""

    required = {
        "origin": intent.origin,
        "destination": intent.destination_anchor,
        "earliest_departure_at": intent.earliest_departure_at,
        "latest_return_at": intent.latest_return_at,
    }
    absent = sorted(name for name, value in required.items() if not value)
    if absent:
        return _missing_evidence(
            "railway",
            "missing_intent_fields:" + ",".join(absent),
        )
    started = time.monotonic()
    result = query_intercity_rail(
        origin=str(intent.origin),
        destination=str(intent.destination_anchor),
        earliest_departure_at=str(intent.earliest_departure_at),
        latest_return_at=str(intent.latest_return_at),
        travelers=intent.travelers or 1,
        budget_cny=intent.total_budget_cny,
    )
    result["timing_ms"] = round(
        (time.monotonic() - started) * 1000,
        3,
    )
    if result.get("support") != "sourced":
        return EvidenceItem(
            evidence_id="railway-live-query",
            domain="railway",
            status=EvidenceStatus.MISSING,
            value=dict(result),
            missing_reason=str(
                result.get("missing_reason", "railway_data_unavailable")
            ),
        )
    source = result.get("source")
    if not isinstance(source, Mapping):
        raise RuntimeError("sourced railway result omitted source")
    return EvidenceItem(
        evidence_id="railway-live-query",
        domain="railway",
        status=EvidenceStatus.SOURCED,
        value=dict(result),
        sources=(dict(source),),
    )


def collect_map_evidence(intent: TravelIntent) -> EvidenceItem:
    """Resolve the destination district through the existing AMap adapter."""

    if not intent.destination_anchor:
        return _missing_evidence("map", "destination_anchor_not_supplied")
    try:
        result = query_destination_district(intent.destination_anchor)
    except _LiveFailure as error:
        return EvidenceItem(
            evidence_id="map-live-query",
            domain="map",
            status=EvidenceStatus.MISSING,
            value={
                "failure_stage": error.stage,
                "http_status": error.http_status,
                "amap_status": error.amap_status,
                "amap_infocode": error.amap_infocode,
                "python_exception_type": error.python_exception_type,
                "response_bytes_received": error.response_bytes_received,
            },
            missing_reason=error.stage,
        )
    status = result.get("support")
    if status == SUPPORT_UNKNOWN:
        return EvidenceItem(
            evidence_id="map-live-query",
            domain="map",
            status=EvidenceStatus.MISSING,
            value=dict(result),
            missing_reason=str(
                result.get("missing_reason", "map_data_unavailable")
            ),
        )
    source = result.get("source")
    sources = (
        (dict(source),)
        if isinstance(source, Mapping)
        else ()
    )
    if status == "conflicting":
        details = result.get("conflict_details")
        if not isinstance(details, list) or any(
            not isinstance(item, str) for item in details
        ):
            raise RuntimeError("conflicting map result omitted details")
        return EvidenceItem(
            evidence_id="map-live-query",
            domain="map",
            status=EvidenceStatus.CONFLICTING,
            value=dict(result),
            sources=sources,
            conflict_details=tuple(details),
        )
    if status != "sourced" or not sources:
        raise RuntimeError("map result has invalid evidence status")
    return EvidenceItem(
        evidence_id="map-live-query",
        domain="map",
        status=EvidenceStatus.SOURCED,
        value=dict(result),
        sources=sources,
    )


def unavailable_web_evidence(intent: TravelIntent) -> EvidenceItem:
    """Preserve the unconfigured generic web collector as missing."""

    del intent
    return _missing_evidence("web", "web_search_collector_not_configured")


def default_destination_collectors() -> DestinationCollectors:
    """Return production collectors without catalog or static-data fallback."""

    return DestinationCollectors(
        railway=collect_railway_evidence,
        map=collect_map_evidence,
        web=unavailable_web_evidence,
    )


def execute_destination_intent(
    intent: TravelIntent,
    emit: ToolEvent,
    *,
    collectors: DestinationCollectors | None = None,
) -> Mapping[str, object]:
    """Execute the shared parse/collect/context/plan/validate path."""

    selected = collectors or default_destination_collectors()
    result = dict(
        execute_destination_pipeline(
            intent,
            emit,
            collectors=selected,
            planner=lambda context: plan_destination_context(
                context.to_dict()
            ),
            validator=lambda context, plan: validate_destination_plan(
                context.to_dict(),
                plan,
            ),
        )
    )
    result["task_mode"] = intent.task_mode.value
    result["mode_flow"] = {
        TaskMode.OPEN_DISCOVERY: "DISCOVER_EVIDENCE_AND_CANDIDATES",
        TaskMode.GUIDED_DISCOVERY: "GUIDED_REGION_COMPARISON",
        TaskMode.DIRECT_PLAN: "DIRECT_DESTINATION_PLAN",
        TaskMode.PLAN_AUDIT: "EXISTING_PLAN_AUDIT",
    }[intent.task_mode]
    return result


def revise_destination_result(
    previous_result: Mapping[str, object],
    revision: Revision,
    emit: ToolEvent,
) -> Mapping[str, object]:
    """Revise a generic result through the shared planner boundary."""

    emit("revise", "started", "开始应用结构化修改。", None)
    result = revise_destination_plan(
        previous_result,
        planner_edits=revision.planner_edits(),
        pace=revision.pace,
    )
    emit(
        "revise",
        "completed",
        "结构化修改已应用。",
        {"status": result.get("status")},
    )
    return result


__all__ = [
    "DestinationEvidenceProvider",
    "collect_map_evidence",
    "collect_railway_evidence",
    "default_destination_collectors",
    "execute_destination_intent",
    "revise_destination_result",
    "unavailable_web_evidence",
]
