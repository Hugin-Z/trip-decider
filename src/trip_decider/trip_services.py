"""Composition root for one authoritative trip application runtime.

Transport adapters receive this bundle instead of constructing stores or
repositories themselves.  A bundle always contains one application service
and one query service over the same durable run store.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trip_decider.evidence_broker import EvidenceBroker
from trip_decider.trip_application import (
    default_trip_application_service,
    ComparisonBuilder,
    EvidenceCollector,
    RevisionExecutor,
    TripApplicationService,
)
from trip_decider.trip_query import (
    default_trip_query_service,
    TripQueryService,
)
from trip_decider.travel_agent import InMemoryAgentStore


@dataclass(frozen=True)
class TripServices:
    """The command and query boundaries for one local application runtime."""

    application: TripApplicationService
    query: TripQueryService

    def __post_init__(self) -> None:
        if self.query.application_service is not self.application:
            raise ValueError(
                "query service must reference the bundled application service"
            )
        if self.query.store is not self.application.store:
            raise ValueError("trip services must share one authoritative store")


_DEFAULT_SERVICES: TripServices | None = None


def default_trip_services() -> TripServices:
    """进程级默认服务组合，首次调用时才构造（invariants.md I11）。"""

    global _DEFAULT_SERVICES
    if _DEFAULT_SERVICES is None:
        application = default_trip_application_service()
        _DEFAULT_SERVICES = TripServices(
            application=application,
            query=default_trip_query_service(),
        )
    return _DEFAULT_SERVICES


def build_trip_services(
    runtime_root: Path | str,
    *,
    evidence_cache_root: Path | str | None = None,
    railway_collector: EvidenceCollector | None = None,
    map_collector: EvidenceCollector | None = None,
    web_collector: EvidenceCollector | None = None,
    comparison_builder: ComparisonBuilder | None = None,
    revision_executor: RevisionExecutor | None = None,
) -> TripServices:
    """Build one durable runtime for tests or an explicit local deployment."""

    sessions_root = Path(runtime_root).resolve()
    cache_root = (
        Path(evidence_cache_root).resolve()
        if evidence_cache_root is not None
        else sessions_root.parent / "evidence-cache"
    )
    store = InMemoryAgentStore(sessions_root)
    arguments: dict[str, object] = {
        "store": store,
        "evidence_broker": EvidenceBroker(cache_root),
    }
    for name, value in (
        ("railway_collector", railway_collector),
        ("map_collector", map_collector),
        ("web_collector", web_collector),
        ("comparison_builder", comparison_builder),
        ("revision_executor", revision_executor),
    ):
        if value is not None:
            arguments[name] = value
    application = TripApplicationService(**arguments)
    query = TripQueryService(
        store=store,
        application_service=application,
    )
    return TripServices(application=application, query=query)


__all__ = [
    "default_trip_services",
    "TripServices",
    "build_trip_services",
]
