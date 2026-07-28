"""Shared WU2 adapter contracts.

The wire inputs remain mappings. These dataclasses carry only explicit
run-scoped values and do not infer provider, CRS, policy, timestamps, or IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


INGESTION_PROBLEM_CODES = frozenset(
    {
        "INGESTION_INPUT_INVALID",
        "INGESTION_PROVIDER_MISSING",
        "INGESTION_CRS_MISSING",
        "INGESTION_CRS_UNSUPPORTED",
        "INGESTION_POLICY_INVALID",
        "INGESTION_RESPONSE_EMPTY",
        "INGESTION_PROVIDER_ERROR",
        "INGESTION_RECORD_INVALID",
        "INGESTION_ROUTE_COUNT_INVALID",
        "INGESTION_DURATION_INVALID",
    }
)


@dataclass(frozen=True)
class IngestionContext:
    """Explicit artifact-envelope and relation inputs for normalization."""

    request_ref: Mapping[str, object]
    run_id: str
    created_at: str
    producer_name: str = "trip-decider-wu2"
    producer_version: str = "0.1.0"


@dataclass(frozen=True)
class RunSummary:
    """Measured outputs from one offline replay run."""

    run_id: str
    output_root: Path
    candidate_artifact_path: Path
    evidence_artifact_path: Path
    metadata_path: Path
    candidate_count: int
    evidence_fact_count: int
    network_attempt_count: int


def stable_identifier(prefix: str, namespace: str, seed: str) -> str:
    """Return the frozen SHA256-derived UUID-shaped identifier."""

    raise NotImplementedError("WU2 adapter behavior is not implemented")
