"""WU2R Resume acquisition composition interfaces.

This module composes already-frozen failure-evidence and candidate-ingestion
boundaries.  It owns no HTTP client, endpoint selection, retry scheduling,
provider fallback, identity selection, route lookup, or planner behavior.
Every effectful boundary is injected.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from trip_decider.acquisition_evidence import (
    AcquisitionEvidenceResult,
    CleanupEffect,
    PersistEffect,
    RunnerObservation,
)
from trip_decider.adapters.contracts import IngestionContext
from trip_decider.recovery import RecoveryCandidateResult
from trip_decider.schema_validation import ValidationProblem


@dataclass(frozen=True)
class ResumeSnapshotMetadata:
    """Explicit metadata required to construct one OSM snapshot."""

    format_version: str
    provider: str
    operation: str
    crs: str
    retrieved_at: str
    request_fingerprint: str
    response_locator: Mapping[str, object]
    data_policy: Mapping[str, object]


@dataclass(frozen=True)
class ResumeCaptureObservation:
    """Sanitized attempt metadata plus in-memory response bytes."""

    runner_observation: RunnerObservation
    response_bytes: bytes | None
    snapshot_metadata: ResumeSnapshotMetadata | None


@dataclass(frozen=True)
class ResumeAcquisitionResult:
    """FER result and candidate output for one explicit acquisition group."""

    run_id: str
    attempt_group_id: str
    query_sha256: str
    request_sha256: str
    failure_evidence_path: Path
    evidence: AcquisitionEvidenceResult
    candidate_result: RecoveryCandidateResult | None
    eligible_response_bytes: bytes | None
    problems: tuple[ValidationProblem, ...]


@dataclass(frozen=True)
class ResumeReplayResult:
    """Deterministic candidate output reconstructed from committed bytes."""

    run_id: str
    query_sha256: str
    request_sha256: str
    response_sha256: str
    response_bytes: int
    candidate_result: RecoveryCandidateResult
    network_attempts: int
    problems: tuple[ValidationProblem, ...]


class ResumeCaptureEffect(Protocol):
    """Injected transport/harness boundary for the one approved attempt."""

    def __call__(self, request_bytes: bytes) -> ResumeCaptureObservation:
        ...


ClockEffect = Callable[[], str]


def run_wu2r_resume_acquisition(
    *,
    run_id: str,
    attempt_group_id: str,
    purpose: str,
    query_bytes: bytes,
    request_bytes: bytes,
    expected_query_sha256: str,
    expected_request_sha256: str,
    failure_evidence_path: Path,
    emergency_evidence_path: Path,
    capture: ResumeCaptureEffect,
    cleanup: CleanupEffect,
    clock: ClockEffect,
    seeds: Sequence[str],
    context: IngestionContext,
    primary_persist: PersistEffect | None = None,
    emergency_persist: PersistEffect | None = None,
) -> ResumeAcquisitionResult:
    """Run one injected Resume acquisition and compose FER with ingestion."""

    raise NotImplementedError("WU2R Resume acquisition is not implemented")


def replay_wu2r_resume_anchor(
    *,
    run_id: str,
    query_bytes: bytes,
    request_bytes: bytes,
    expected_query_sha256: str,
    expected_request_sha256: str,
    response_bytes: bytes,
    expected_response_sha256: str,
    snapshot_metadata: ResumeSnapshotMetadata,
    seeds: Sequence[str],
    context: IngestionContext,
) -> ResumeReplayResult:
    """Replay committed bytes through the deterministic candidate boundary."""

    raise NotImplementedError("WU2R Resume replay is not implemented")
