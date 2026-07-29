"""City-neutral runtime composition for one destination planning run."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from trip_decider.intercity_rail import query_intercity_rail
from trip_decider.itinerary_planner import (
    plan_destination_context,
    revise_destination_plan,
    validate_destination_plan,
)
from trip_decider.travel_agent import (
    DestinationCollectors,
    EvidenceItem,
    EvidenceStatus,
    Revision,
    ToolEvent,
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
    result = query_intercity_rail(
        origin=str(intent.origin),
        destination=str(intent.destination_anchor),
        earliest_departure_at=str(intent.earliest_departure_at),
        latest_return_at=str(intent.latest_return_at),
        travelers=intent.travelers or 1,
        budget_cny=intent.total_budget_cny,
    )
    if result.get("evidence_status") != "sourced":
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


def unavailable_map_evidence(intent: TravelIntent) -> EvidenceItem:
    """Preserve the unconfigured generic map collector as missing."""

    del intent
    return _missing_evidence("map", "map_collector_not_configured")


def unavailable_web_evidence(intent: TravelIntent) -> EvidenceItem:
    """Preserve the unconfigured generic web collector as missing."""

    del intent
    return _missing_evidence("web", "web_search_collector_not_configured")


def default_destination_collectors() -> DestinationCollectors:
    """Return production collectors without catalog or static-data fallback."""

    return DestinationCollectors(
        railway=collect_railway_evidence,
        map=unavailable_map_evidence,
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
    return execute_destination_pipeline(
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
    "collect_railway_evidence",
    "default_destination_collectors",
    "execute_destination_intent",
    "revise_destination_result",
    "unavailable_map_evidence",
    "unavailable_web_evidence",
]
