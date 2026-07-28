"""Offline-injectable acquisition harness contract.

WU2A-R owns failure-path evidence mechanics only.  This module does not
provide an HTTP client, choose an endpoint, construct a query, or acquire
real data.  Callers must inject every effectful boundary explicitly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ATTEMPT_FIELDS = (
    "attempt_id",
    "purpose",
    "endpoint",
    "method",
    "request_sha256",
    "started_at",
    "completed_at",
    "status",
    "http_status",
    "response_bytes",
    "response_sha256",
    "content_type",
    "error_class",
    "retry_decision",
)

ATTEMPT_STATUSES = frozenset(
    {
        "started",
        "succeeded",
        "http_response_failure",
        "transport_failure",
        "internal_failure",
    }
)

RETRY_DECISIONS = frozenset(
    {
        "not_evaluated",
        "not_applicable",
        "not_retryable_http",
        "retry_scheduled",
        "retry_exhausted",
        "not_retryable_internal",
    }
)


@dataclass(frozen=True)
class TransportResponse:
    """Response metadata supplied by an injected transport."""

    status: int
    body: bytes | None
    content_type: str | None


@dataclass(frozen=True)
class AcquisitionResult:
    """Completed acquisition run loaded from its persisted ledger."""

    ledger_path: Path
    attempts: tuple[dict[str, Any], ...]
    retries: tuple[dict[str, Any], ...]


def run_acquisition(
    *,
    purpose: str,
    endpoint: str,
    method: str,
    request_bytes: bytes,
    ledger_path: Path,
    transport: Callable[[bytes], TransportResponse],
    clock: Callable[[], str],
    max_transport_retries: int = 1,
    postprocess: Callable[[TransportResponse], None] | None = None,
) -> AcquisitionResult:
    """Run one acquisition with transport-only retries and durable evidence."""

    raise NotImplementedError("WU2A-R acquisition behavior is not implemented")
