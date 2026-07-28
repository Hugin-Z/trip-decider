"""WU2 Recovery multi-identity ingestion interfaces.

This module owns deterministic seed accounting, candidate-local source views,
route endpoint guarding, and offline replay orchestration.  It does not own a
network client, provider adapter, identity resolver, evidence runtime,
planner, or route acquisition.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from trip_decider.adapters.contracts import IngestionContext
from trip_decider.schema_validation import ValidationResult


@dataclass(frozen=True)
class SeedMatch:
    """Exact seed-to-candidate accounting for one candidate snapshot."""

    seed: str
    status: str
    candidate_refs: tuple[str, ...]


@dataclass(frozen=True)
class RecordLocalFact:
    """Provider facts projected from one candidate without evidence rating."""

    candidate_id: str
    provider_name: str
    provider_record_type: str
    provider_record_id: str
    categories: tuple[tuple[str, str | None], ...]
    location: Mapping[str, object]
    source_refs: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class RecoveryCandidateResult:
    """Plural candidate artifact plus exact seed and source-fact views."""

    candidate_artifact: Mapping[str, object]
    seed_matches: tuple[SeedMatch, ...]
    record_local_facts: tuple[RecordLocalFact, ...]


@dataclass(frozen=True)
class RouteEndpointPair:
    """Stable candidate references authorized for route preparation."""

    from_candidate_ref: str
    to_candidate_ref: str


@dataclass(frozen=True)
class RecoveryRunSummary:
    """Auditable output metadata for one offline Recovery replay."""

    run_id: str
    candidate_artifact_path: Path
    seed_accounting_path: Path
    record_local_facts_path: Path
    run_summary_path: Path
    candidate_count: int
    seed_status_counts: Mapping[str, int]
    network_attempts: int
    output_sha256: Mapping[str, str]


def ingest_candidate_pool(
    snapshot: Mapping[str, object],
    seeds: Sequence[str],
    context: IngestionContext,
) -> ValidationResult[RecoveryCandidateResult]:
    """Normalize all provider identities and account for every exact seed."""

    raise NotImplementedError("WU2 Recovery candidate ingestion is not implemented")


def prepare_route_endpoints(
    candidate_result: RecoveryCandidateResult,
    from_seed: str,
    to_seed: str,
) -> ValidationResult[RouteEndpointPair]:
    """Return stable refs only when both seed identities are uniquely matched."""

    raise NotImplementedError("WU2 Recovery route guard is not implemented")


def run_wu2_recovery(
    replay_root: Path,
    output_root: Path,
) -> ValidationResult[RecoveryRunSummary]:
    """Run the approved multi-identity anchor replay without network access."""

    raise NotImplementedError("WU2 Recovery offline replay is not implemented")


__all__ = [
    "RecordLocalFact",
    "RecoveryCandidateResult",
    "RecoveryRunSummary",
    "RouteEndpointPair",
    "SeedMatch",
    "ingest_candidate_pool",
    "prepare_route_endpoints",
    "run_wu2_recovery",
]
