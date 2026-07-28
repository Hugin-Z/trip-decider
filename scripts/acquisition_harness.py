"""Offline-injectable acquisition harness contract.

WU2A-R owns failure-path evidence mechanics only.  This module does not
provide an HTTP client, choose an endpoint, construct a query, or acquire
real data.  Callers must inject every effectful boundary explicitly.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError


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

    _validate_inputs(
        purpose=purpose,
        endpoint=endpoint,
        method=method,
        request_bytes=request_bytes,
        ledger_path=ledger_path,
        transport=transport,
        clock=clock,
        max_transport_retries=max_transport_retries,
        postprocess=postprocess,
    )

    request_sha256 = hashlib.sha256(request_bytes).hexdigest()
    attempts: list[dict[str, Any]] = []
    retries: list[dict[str, Any]] = []
    retry_count = 0

    while True:
        attempt_id = f"attempt-{len(attempts) + 1:04d}"
        attempt = _new_attempt(
            attempt_id=attempt_id,
            purpose=purpose,
            endpoint=endpoint,
            method=method,
            request_sha256=request_sha256,
            started_at=_read_clock(clock),
        )
        attempts.append(attempt)

        # Ledger-first invariant: no injected transport runs until the started
        # entry is durably visible at the caller-supplied system-temp path.
        _persist_ledger(ledger_path, attempts, retries)

        schedule_retry = False
        try:
            try:
                response = transport(request_bytes)
            except HTTPError as error:
                _record_http_error(attempt, error)
            except (
                socket.gaierror,
                TimeoutError,
                socket.timeout,
                ConnectionResetError,
                ConnectionError,
            ):
                schedule_retry = _record_transport_failure(
                    attempt=attempt,
                    attempts=attempts,
                    retries=retries,
                    request_sha256=request_sha256,
                    retry_count=retry_count,
                    max_transport_retries=max_transport_retries,
                )
            except URLError as error:
                if _url_error_is_transport_failure(error):
                    schedule_retry = _record_transport_failure(
                        attempt=attempt,
                        attempts=attempts,
                        retries=retries,
                        request_sha256=request_sha256,
                        retry_count=retry_count,
                        max_transport_retries=max_transport_retries,
                    )
                else:
                    _record_internal_failure(attempt)
            except Exception:
                _record_internal_failure(attempt)
            else:
                try:
                    _record_response(attempt, response)
                    if attempt["status"] == "succeeded" and postprocess is not None:
                        postprocess(response)
                except Exception:
                    _record_internal_failure(attempt)
        finally:
            try:
                attempt["completed_at"] = _read_clock(clock)
            except Exception:
                attempt["completed_at"] = None
                _record_internal_failure(attempt)
                _persist_ledger(ledger_path, attempts, retries)
                raise
            _persist_ledger(ledger_path, attempts, retries)

        if not schedule_retry:
            break
        retry_count += 1

    return AcquisitionResult(
        ledger_path=ledger_path,
        attempts=tuple(attempts),
        retries=tuple(retries),
    )


def _validate_inputs(
    *,
    purpose: str,
    endpoint: str,
    method: str,
    request_bytes: bytes,
    ledger_path: Path,
    transport: Callable[[bytes], TransportResponse],
    clock: Callable[[], str],
    max_transport_retries: int,
    postprocess: Callable[[TransportResponse], None] | None,
) -> None:
    if not isinstance(purpose, str) or not purpose:
        raise TypeError("purpose must be a non-empty string")
    if not isinstance(endpoint, str) or not endpoint:
        raise TypeError("endpoint must be a non-empty string")
    if not isinstance(method, str) or not method:
        raise TypeError("method must be a non-empty string")
    if type(request_bytes) is not bytes:
        raise TypeError("request_bytes must be bytes")
    if not isinstance(ledger_path, Path):
        raise TypeError("ledger_path must be a pathlib.Path")
    if not callable(transport):
        raise TypeError("transport must be callable")
    if not callable(clock):
        raise TypeError("clock must be callable")
    if (
        type(max_transport_retries) is not int
        or max_transport_retries < 0
    ):
        raise ValueError("max_transport_retries must be a non-negative integer")
    if postprocess is not None and not callable(postprocess):
        raise TypeError("postprocess must be callable or None")

    resolved_ledger = ledger_path.resolve(strict=False)
    system_temp = Path(tempfile.gettempdir()).resolve()
    try:
        resolved_ledger.relative_to(system_temp)
    except ValueError as error:
        raise ValueError("ledger_path must be inside the system temp directory") from error
    if not resolved_ledger.parent.is_dir():
        raise FileNotFoundError("ledger parent directory does not exist")
    if resolved_ledger.is_dir():
        raise IsADirectoryError("ledger_path points to a directory")


def _read_clock(clock: Callable[[], str]) -> str:
    value = clock()
    if not isinstance(value, str) or not value:
        raise TypeError("clock must return a non-empty RFC 3339 string")
    return value


def _new_attempt(
    *,
    attempt_id: str,
    purpose: str,
    endpoint: str,
    method: str,
    request_sha256: str,
    started_at: str,
) -> dict[str, Any]:
    return {
        "attempt_id": attempt_id,
        "purpose": purpose,
        "endpoint": endpoint,
        "method": method,
        "request_sha256": request_sha256,
        "started_at": started_at,
        "completed_at": None,
        "status": "started",
        "http_status": None,
        "response_bytes": None,
        "response_sha256": None,
        "content_type": None,
        "error_class": None,
        "retry_decision": "not_evaluated",
    }


def _persist_ledger(
    ledger_path: Path,
    attempts: list[dict[str, Any]],
    retries: list[dict[str, Any]],
) -> None:
    document = {
        "attempts": attempts,
        "retries": retries,
    }
    encoded = (
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )
        + "\n"
    ).encode("utf-8")
    temporary_path = ledger_path.with_name(
        f"{ledger_path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary_path.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, ledger_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _record_http_error(
    attempt: dict[str, Any],
    error: HTTPError,
) -> None:
    attempt["status"] = "http_response_failure"
    attempt["error_class"] = "http_response_failure"
    attempt["retry_decision"] = "not_retryable_http"
    attempt["http_status"] = (
        error.code
        if type(error.code) is int
        else None
    )
    attempt["content_type"] = _read_content_type(error.headers)
    body = _read_http_error_body(error)
    _record_body_metadata(attempt, body)


def _read_http_error_body(error: HTTPError) -> bytes | None:
    if getattr(error, "fp", None) is None:
        return None
    try:
        body = error.read()
    except Exception:
        return None
    return body if type(body) is bytes else None


def _read_content_type(headers: Any) -> str | None:
    if headers is None or not hasattr(headers, "get"):
        return None
    try:
        value = headers.get("Content-Type")
    except Exception:
        return None
    return value if isinstance(value, str) else None


def _record_response(
    attempt: dict[str, Any],
    response: TransportResponse,
) -> None:
    if not isinstance(response, TransportResponse):
        raise TypeError("transport must return TransportResponse")
    if type(response.status) is not int:
        raise TypeError("response status must be an integer")
    if response.body is not None and type(response.body) is not bytes:
        raise TypeError("response body must be bytes or None")
    if response.content_type is not None and not isinstance(
        response.content_type,
        str,
    ):
        raise TypeError("response content_type must be a string or None")

    attempt["http_status"] = response.status
    attempt["content_type"] = response.content_type
    _record_body_metadata(attempt, response.body)

    if 200 <= response.status <= 299:
        attempt["status"] = "succeeded"
        attempt["error_class"] = None
        attempt["retry_decision"] = "not_applicable"
    else:
        attempt["status"] = "http_response_failure"
        attempt["error_class"] = "http_response_failure"
        attempt["retry_decision"] = "not_retryable_http"


def _record_body_metadata(
    attempt: dict[str, Any],
    body: bytes | None,
) -> None:
    if body is None:
        attempt["response_bytes"] = None
        attempt["response_sha256"] = None
        return
    attempt["response_bytes"] = len(body)
    attempt["response_sha256"] = hashlib.sha256(body).hexdigest()


def _url_error_is_transport_failure(error: URLError) -> bool:
    return isinstance(
        error.reason,
        (
            socket.gaierror,
            TimeoutError,
            socket.timeout,
            ConnectionResetError,
            ConnectionError,
        ),
    )


def _record_transport_failure(
    *,
    attempt: dict[str, Any],
    attempts: list[dict[str, Any]],
    retries: list[dict[str, Any]],
    request_sha256: str,
    retry_count: int,
    max_transport_retries: int,
) -> bool:
    attempt["status"] = "transport_failure"
    attempt["error_class"] = "transport_failure"
    attempt["http_status"] = None
    attempt["response_bytes"] = None
    attempt["response_sha256"] = None
    attempt["content_type"] = None

    if retry_count >= max_transport_retries:
        attempt["retry_decision"] = "retry_exhausted"
        return False

    attempt["retry_decision"] = "retry_scheduled"
    retry_attempt_id = f"attempt-{len(attempts) + 1:04d}"
    retries.append(
        {
            "original_attempt_id": attempt["attempt_id"],
            "retry_attempt_id": retry_attempt_id,
            "same_request_sha256": (
                attempt["request_sha256"] == request_sha256
            ),
            "reason": "transport_failure",
        }
    )
    return True


def _record_internal_failure(attempt: dict[str, Any]) -> None:
    attempt["status"] = "internal_failure"
    attempt["error_class"] = "internal_failure"
    attempt["retry_decision"] = "not_retryable_internal"
