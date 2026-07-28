"""Failure-evidence orchestration interfaces for WU2R-FER.

This module owns no HTTP client, endpoint, provider behavior, response
normalizer, or retry scheduler.  Callers inject every effectful boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


ACQUISITION_TRANSPORT_FAILURE = "ACQUISITION_TRANSPORT_FAILURE"
ACQUISITION_HTTP_FAILURE = "ACQUISITION_HTTP_FAILURE"
ACQUISITION_RESPONSE_FAILURE = "ACQUISITION_RESPONSE_FAILURE"
ACQUISITION_LEDGER_FAILURE = "ACQUISITION_LEDGER_FAILURE"
ACQUISITION_CLEANUP_FAILURE = "ACQUISITION_CLEANUP_FAILURE"
ACQUISITION_INTERNAL_FAILURE = "ACQUISITION_INTERNAL_FAILURE"

FAILURE_CODES = frozenset(
    {
        ACQUISITION_TRANSPORT_FAILURE,
        ACQUISITION_HTTP_FAILURE,
        ACQUISITION_RESPONSE_FAILURE,
        ACQUISITION_LEDGER_FAILURE,
        ACQUISITION_CLEANUP_FAILURE,
        ACQUISITION_INTERNAL_FAILURE,
    }
)


@dataclass(frozen=True)
class AttemptObservation:
    """One sanitized attempt observation returned by an injected runner."""

    attempt_id: str
    request_sha256: str
    started_at: str
    completed_at: str | None
    status: str
    http_status: int | None
    response_bytes: int | None
    response_sha256: str | None
    content_type: str | None
    retry_decision: str


@dataclass(frozen=True)
class RetryObservation:
    """A runner-owned retry relationship."""

    original_attempt_id: str
    retry_attempt_id: str
    same_request_sha256: bool
    retry_reason: str


@dataclass(frozen=True)
class ResponsePhaseObservation:
    """Explicit response-phase result; no response body is retained."""

    status: str
    failure_kind: str | None = None


@dataclass(frozen=True)
class RunnerObservation:
    """Sanitized output from the injected acquisition runner."""

    attempts: tuple[AttemptObservation, ...]
    retries: tuple[RetryObservation, ...]
    response_phase: ResponsePhaseObservation


@dataclass(frozen=True)
class CleanupItemObservation:
    """One allowlisted cleanup result without a filesystem path."""

    resource_kind: str
    existed_before: bool
    deletion_attempted: bool
    status: str
    residue_count: int


@dataclass(frozen=True)
class AcquisitionEvidenceResult:
    """Returned evidence state and the durable sink, if any."""

    document: dict[str, Any]
    evidence_path: Path | None
    emergency_path: Path | None
    durable_evidence: bool


class RunnerEffect(Protocol):
    """Injected harness boundary; it may execute transport and retry."""

    def __call__(self, request_bytes: bytes) -> RunnerObservation:
        ...


class CleanupEffect(Protocol):
    """Injected cleanup boundary."""

    def __call__(self) -> tuple[CleanupItemObservation, ...]:
        ...


PersistEffect = Callable[[Path, bytes], None]
ClockEffect = Callable[[], str]


def run_failure_evidenced_acquisition(
    *,
    run_id: str,
    purpose: str,
    request_bytes: bytes,
    primary_path: Path,
    emergency_path: Path,
    runner: RunnerEffect,
    cleanup: CleanupEffect,
    clock: ClockEffect,
    primary_persist: PersistEffect | None = None,
    emergency_persist: PersistEffect | None = None,
) -> AcquisitionEvidenceResult:
    """Run an injected acquisition with durable, sanitized failure evidence."""

    raise NotImplementedError(
        "WU2R-FER failure evidence persistence is not implemented"
    )
