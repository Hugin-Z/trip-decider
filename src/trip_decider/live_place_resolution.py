"""Structured live-place resolution interfaces for WU7 Stage A.

Stage A accepts only injected, handwritten synthetic provider responses.  It
does not read credentials, open sockets, call a provider, or establish that
real provider data may be stored.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from trip_decider.schema_validation import ValidationResult


AMAP_PERSISTENCE_POLICY_STATUS = "AMAP_PERSISTENCE_POLICY_UNRESOLVED"
LIVE_SMOKE_STATUS = (
    "LIVE_SMOKE_NOT_AUTHORIZED_STORAGE_POLICY_UNRESOLVED"
)


@dataclass(frozen=True)
class StructuredTripInput:
    """Explicit structured user fields; no natural-language inference."""

    city: str
    start_at: str
    end_at: str
    input_recorded_at: str
    party_count: int
    transport_modes: tuple[str, ...]
    must_visit: tuple[str, ...]
    excluded: tuple[str, ...] = ()
    city_adcode: str | None = None
    locale: str = "zh-CN"
    interactive: bool = False


@dataclass(frozen=True)
class SyntheticProviderRequest:
    """De-keyed request descriptor passed to an injected fake transport."""

    operation: str
    endpoint_path: str
    parameters: Mapping[str, object]
    synthetic_test_data: bool = True


class SyntheticTransport(Protocol):
    """Injected Stage A boundary; implementations must not use the network."""

    def __call__(
        self,
        request: SyntheticProviderRequest,
    ) -> Mapping[str, object]:
        ...


SelectionReader = Callable[[str, tuple[tuple[str, str], ...]], str]


@dataclass(frozen=True)
class LivePlaceResolutionSummary:
    """Auditable paths and measured counts for one synthetic Stage A run."""

    run_id: str
    output_root: Path
    planning_input_root: Path
    provider_observation_root: Path
    resolution_root: Path
    selection_path: Path
    run_summary_path: Path
    candidate_count: int
    seed_status_counts: Mapping[str, int]
    synthetic_transport_calls: int
    network_attempts: int
    llm_calls: int
    synthetic_test_data: bool
    generation_allowed: bool
    output_sha256: Mapping[str, str]


def run_synthetic_live_place_resolution(
    structured_input: StructuredTripInput,
    output_root: Path,
    transport: SyntheticTransport,
    *,
    selection_reader: SelectionReader | None = None,
) -> ValidationResult[LivePlaceResolutionSummary]:
    """Compile input and resolve places using only an injected fake transport."""

    raise NotImplementedError("WU7 Stage A implementation is not available")


def replay_synthetic_normalized_snapshot(
    snapshot_root: Path,
    output_root: Path,
) -> ValidationResult[LivePlaceResolutionSummary]:
    """Replay a Stage A synthetic snapshot without provider or network access."""

    raise NotImplementedError("WU7 Stage A implementation is not available")


__all__ = [
    "AMAP_PERSISTENCE_POLICY_STATUS",
    "LIVE_SMOKE_STATUS",
    "LivePlaceResolutionSummary",
    "SelectionReader",
    "StructuredTripInput",
    "SyntheticProviderRequest",
    "SyntheticTransport",
    "replay_synthetic_normalized_snapshot",
    "run_synthetic_live_place_resolution",
]
