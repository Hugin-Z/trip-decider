"""Same-run AMap resolution boundary for WU7B-P2.

The public contract keeps provider observations ephemeral and exposes only a
safe, non-publishable coarse-planning result.  Implementation is added after
the approved fixture-first Red commit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from trip_decider.live_place_resolution import StructuredTripInput
from trip_decider.schema_validation import ValidationResult


AMAP_CREDENTIAL_MISSING = "AMAP_CREDENTIAL_MISSING"
AMAP_PROVIDER_FAILURE = "AMAP_PROVIDER_FAILURE"
AMAP_P2_CLEANUP_FAILED = "AMAP_P2_CLEANUP_FAILED"
AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED = (
    "AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED"
)
AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED = (
    "AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED"
)


@dataclass(frozen=True)
class AmapLiveRequest:
    """De-keyed request descriptor supplied to the wire transport."""

    operation: str
    endpoint_path: str
    parameters: Mapping[str, str]


class AmapLiveTransport(Protocol):
    """Injected wire closure; credential injection occurs only here."""

    def __call__(
        self,
        request: AmapLiveRequest,
        credential: str,
    ) -> bytes:
        ...


@dataclass(frozen=True)
class AmapEphemeralLiveConfig:
    """Explicit structured input plus current-run alternative selections."""

    structured_input: StructuredTripInput
    selection_ordinals: Mapping[str, int]


@dataclass(frozen=True)
class SafeSeedResult:
    """Provider-free identity and allocation result for one user seed."""

    seed: str
    identity_status: str
    explicitly_selected: bool
    day_number: int | None
    blocker: str | None


@dataclass(frozen=True)
class AmapEphemeralLiveSummary:
    """Safe summary of one completed same-run resolution."""

    output_root: Path
    planning_status: str
    publishable: bool
    generation_allowed_input: bool
    seed_results: tuple[SafeSeedResult, ...]
    scheduled_count: int
    blocked_count: int
    network_calls: int
    llm_calls: int
    cleanup_counts: Mapping[str, int]
    output_sha256: Mapping[str, str]


def run_amap_ephemeral_live(
    config: AmapEphemeralLiveConfig,
    output_root: Path,
    *,
    transport: AmapLiveTransport | None = None,
) -> ValidationResult[AmapEphemeralLiveSummary]:
    """Resolve live places and install only the safe nine-file output."""

    raise NotImplementedError("WU7B C1 interface stub")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the approved structured WU7B command-line interface."""

    raise NotImplementedError("WU7B C1 interface stub")


__all__ = [
    "AMAP_CREDENTIAL_MISSING",
    "AMAP_PROVIDER_FAILURE",
    "AMAP_P2_CLEANUP_FAILED",
    "AMAP_P2_FINAL_OUTPUT_REDACTION_BLOCKED",
    "AMAP_P2_PUBLIC_PARSER_INTEGRATION_BLOCKED",
    "AmapEphemeralLiveConfig",
    "AmapEphemeralLiveSummary",
    "AmapLiveRequest",
    "AmapLiveTransport",
    "SafeSeedResult",
    "main",
    "run_amap_ephemeral_live",
]
