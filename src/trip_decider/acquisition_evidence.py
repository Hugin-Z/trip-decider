"""Failure-evidence orchestration interfaces for WU2R-FER.

This module owns no HTTP client, endpoint, provider behavior, response
normalizer, or retry scheduler.  Callers inject every effectful boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
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

_ATTEMPT_STATUSES = frozenset(
    {
        "succeeded",
        "transport_failure",
        "http_response_failure",
        "internal_failure",
    }
)
_RETRY_DECISIONS = frozenset(
    {
        "not_applicable",
        "not_retryable_http",
        "not_retryable_internal",
        "retry_scheduled",
        "retry_exhausted",
    }
)
_RESPONSE_STATUSES = frozenset(
    {
        "accepted",
        "rejected",
        "not_evaluated",
    }
)
_CLEANUP_STATUSES = frozenset(
    {
        "removed",
        "not_present",
        "failed",
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

    _validate_inputs(
        run_id=run_id,
        purpose=purpose,
        request_bytes=request_bytes,
        primary_path=primary_path,
        emergency_path=emergency_path,
        runner=runner,
        cleanup=cleanup,
        clock=clock,
        primary_persist=primary_persist,
        emergency_persist=emergency_persist,
    )

    primary_writer = primary_persist or _persist_atomically
    emergency_writer = emergency_persist or _persist_atomically
    request_sha256 = hashlib.sha256(request_bytes).hexdigest()
    started_at = _read_clock(clock)
    document = _new_document(
        run_id=run_id,
        purpose=purpose,
        request_sha256=request_sha256,
        started_at=started_at,
    )

    document["persistence"]["primary_status"] = "succeeded"
    try:
        _write_document(primary_writer, primary_path, document)
    except Exception:
        document["persistence"]["primary_status"] = "failed"
        _set_persistence_failure(document, clock)
        document["persistence"]["emergency_attempted"] = True
        document["persistence"]["emergency_status"] = "succeeded"
        try:
            _write_document(emergency_writer, emergency_path, document)
        except Exception:
            document["persistence"]["emergency_status"] = "failed"
            return AcquisitionEvidenceResult(
                document=document,
                evidence_path=None,
                emergency_path=None,
                durable_evidence=False,
            )
        return AcquisitionEvidenceResult(
            document=document,
            evidence_path=None,
            emergency_path=emergency_path,
            durable_evidence=True,
        )

    active_sink = "primary"
    durable_evidence = True

    try:
        observation = runner(request_bytes)
        (
            attempts,
            retries,
            response_phase,
            failure_codes,
            status,
            terminal_failure_code,
        ) = _consume_runner_observation(observation, request_sha256)
    except Exception:
        completed_at = _read_clock_safely(clock)
        attempts = [
            {
                "attempt_id": "attempt-0001",
                "request_sha256": request_sha256,
                "started_at": started_at,
                "completed_at": completed_at,
                "status": "internal_failure",
                "http_status": None,
                "response_bytes": None,
                "response_sha256": None,
                "content_type": None,
                "failure_code": ACQUISITION_INTERNAL_FAILURE,
                "retry_decision": "not_retryable_internal",
            }
        ]
        retries = []
        response_phase = {
            "status": "not_evaluated",
            "failure_kind": None,
        }
        failure_codes = [ACQUISITION_INTERNAL_FAILURE]
        status = "failed"
        terminal_failure_code = ACQUISITION_INTERNAL_FAILURE

    document["attempts"] = attempts
    document["retries"] = retries
    document["response_phase"] = response_phase
    document["failure_codes"] = failure_codes
    document["status"] = status
    document["terminal_failure_code"] = terminal_failure_code

    active_sink, durable_evidence = _persist_terminal(
        document=document,
        active_sink=active_sink,
        primary_path=primary_path,
        emergency_path=emergency_path,
        primary_writer=primary_writer,
        emergency_writer=emergency_writer,
    )

    try:
        cleanup_items = cleanup()
        cleanup_document = _consume_cleanup(cleanup_items)
    except Exception:
        cleanup_document = {
            "status": "failed",
            "items": [],
        }

    document["cleanup"] = cleanup_document
    if cleanup_document["status"] == "failed":
        _add_failure_code(document["failure_codes"], ACQUISITION_CLEANUP_FAILURE)
        document["status"] = "failed"
        document["terminal_failure_code"] = ACQUISITION_CLEANUP_FAILURE

    document["completed_at"] = _read_clock_safely(clock)
    active_sink, final_durable = _persist_terminal(
        document=document,
        active_sink=active_sink,
        primary_path=primary_path,
        emergency_path=emergency_path,
        primary_writer=primary_writer,
        emergency_writer=emergency_writer,
    )
    durable_evidence = durable_evidence and final_durable

    return AcquisitionEvidenceResult(
        document=document,
        evidence_path=(
            primary_path
            if durable_evidence and active_sink == "primary"
            else None
        ),
        emergency_path=(
            emergency_path
            if durable_evidence and active_sink == "emergency"
            else None
        ),
        durable_evidence=durable_evidence,
    )


def _validate_inputs(
    *,
    run_id: str,
    purpose: str,
    request_bytes: bytes,
    primary_path: Path,
    emergency_path: Path,
    runner: RunnerEffect,
    cleanup: CleanupEffect,
    clock: ClockEffect,
    primary_persist: PersistEffect | None,
    emergency_persist: PersistEffect | None,
) -> None:
    if not isinstance(run_id, str) or not run_id:
        raise TypeError("run_id must be a non-empty string")
    if not isinstance(purpose, str) or not purpose:
        raise TypeError("purpose must be a non-empty string")
    if type(request_bytes) is not bytes:
        raise TypeError("request_bytes must be bytes")
    if not isinstance(primary_path, Path):
        raise TypeError("primary_path must be a pathlib.Path")
    if not isinstance(emergency_path, Path):
        raise TypeError("emergency_path must be a pathlib.Path")
    if primary_path.resolve(strict=False) == emergency_path.resolve(strict=False):
        raise ValueError("primary_path and emergency_path must differ")
    if not callable(runner):
        raise TypeError("runner must be callable")
    if not callable(cleanup):
        raise TypeError("cleanup must be callable")
    if not callable(clock):
        raise TypeError("clock must be callable")
    if primary_persist is not None and not callable(primary_persist):
        raise TypeError("primary_persist must be callable or None")
    if emergency_persist is not None and not callable(emergency_persist):
        raise TypeError("emergency_persist must be callable or None")


def _new_document(
    *,
    run_id: str,
    purpose: str,
    request_sha256: str,
    started_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "purpose": purpose,
        "request_sha256": request_sha256,
        "started_at": started_at,
        "completed_at": None,
        "status": "started",
        "terminal_failure_code": None,
        "failure_codes": [],
        "attempts": [],
        "retries": [],
        "response_phase": {
            "status": "not_evaluated",
            "failure_kind": None,
        },
        "cleanup": {
            "status": "pending",
            "items": [],
        },
        "persistence": {
            "primary_status": "pending",
            "primary_path_kind": "ignored_runtime",
            "emergency_attempted": False,
            "emergency_status": "not_attempted",
            "emergency_path_kind": "system_temp",
        },
    }


def _consume_runner_observation(
    observation: RunnerObservation,
    request_sha256: str,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, str | None],
    list[str],
    str,
    str | None,
]:
    if not isinstance(observation, RunnerObservation):
        raise TypeError("runner must return RunnerObservation")
    if type(observation.attempts) is not tuple or not observation.attempts:
        raise ValueError("runner must return at least one attempt")
    if type(observation.retries) is not tuple:
        raise TypeError("runner retries must be a tuple")
    if not isinstance(observation.response_phase, ResponsePhaseObservation):
        raise TypeError("runner response phase is invalid")

    attempts = [
        _consume_attempt(item, request_sha256)
        for item in observation.attempts
    ]
    attempt_ids = [item["attempt_id"] for item in attempts]
    if len(attempt_ids) != len(set(attempt_ids)):
        raise ValueError("attempt IDs must be unique")

    retries = [
        _consume_retry(item, attempts)
        for item in observation.retries
    ]
    retry_pairs = [
        (item["original_attempt_id"], item["retry_attempt_id"])
        for item in retries
    ]
    if len(retry_pairs) != len(set(retry_pairs)):
        raise ValueError("retry relationships must be unique")
    _validate_retry_coverage(attempts, retries)

    response_phase = _consume_response_phase(observation.response_phase)
    failure_codes: list[str] = []
    for item in attempts:
        failure_code = _attempt_failure_code(item["status"])
        item["failure_code"] = failure_code
        if failure_code is not None:
            _add_failure_code(failure_codes, failure_code)

    last_attempt = attempts[-1]
    terminal_failure_code: str | None
    if last_attempt["status"] == "succeeded":
        if response_phase["status"] == "rejected":
            last_attempt["failure_code"] = ACQUISITION_RESPONSE_FAILURE
            _add_failure_code(
                failure_codes,
                ACQUISITION_RESPONSE_FAILURE,
            )
            status = "failed"
            terminal_failure_code = ACQUISITION_RESPONSE_FAILURE
        elif response_phase["status"] == "accepted":
            status = "succeeded"
            terminal_failure_code = None
        else:
            raise ValueError("successful response must be explicitly evaluated")
    else:
        if response_phase["status"] != "not_evaluated":
            raise ValueError("failed transport cannot have response evaluation")
        status = "failed"
        terminal_failure_code = _attempt_failure_code(last_attempt["status"])

    return (
        attempts,
        retries,
        response_phase,
        failure_codes,
        status,
        terminal_failure_code,
    )


def _consume_attempt(
    item: AttemptObservation,
    request_sha256: str,
) -> dict[str, Any]:
    if not isinstance(item, AttemptObservation):
        raise TypeError("attempt must be AttemptObservation")
    if not isinstance(item.attempt_id, str) or not item.attempt_id:
        raise TypeError("attempt_id must be a non-empty string")
    if item.request_sha256 != request_sha256:
        raise ValueError("attempt request hash does not match input bytes")
    if not isinstance(item.started_at, str) or not item.started_at:
        raise TypeError("attempt started_at must be a non-empty string")
    if item.completed_at is not None and (
        not isinstance(item.completed_at, str) or not item.completed_at
    ):
        raise TypeError("attempt completed_at must be a string or None")
    if item.status not in _ATTEMPT_STATUSES:
        raise ValueError("attempt status is unsupported")
    if item.http_status is not None and type(item.http_status) is not int:
        raise TypeError("attempt HTTP status must be an integer or None")
    if item.response_bytes is not None and (
        type(item.response_bytes) is not int or item.response_bytes < 0
    ):
        raise TypeError("response byte count must be non-negative or None")
    if item.response_sha256 is not None and not _sha256(item.response_sha256):
        raise ValueError("response SHA256 is invalid")
    if (item.response_bytes is None) != (item.response_sha256 is None):
        raise ValueError("response bytes and SHA256 must both be known or null")
    if item.content_type is not None and not isinstance(item.content_type, str):
        raise TypeError("content type must be a string or None")
    if item.retry_decision not in _RETRY_DECISIONS:
        raise ValueError("retry decision is unsupported")

    return {
        "attempt_id": item.attempt_id,
        "request_sha256": item.request_sha256,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
        "status": item.status,
        "http_status": item.http_status,
        "response_bytes": item.response_bytes,
        "response_sha256": item.response_sha256,
        "content_type": item.content_type,
        "failure_code": None,
        "retry_decision": item.retry_decision,
    }


def _consume_retry(
    item: RetryObservation,
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(item, RetryObservation):
        raise TypeError("retry must be RetryObservation")
    if not isinstance(item.original_attempt_id, str) or not item.original_attempt_id:
        raise TypeError("original attempt ID must be a non-empty string")
    if not isinstance(item.retry_attempt_id, str) or not item.retry_attempt_id:
        raise TypeError("retry attempt ID must be a non-empty string")
    if item.same_request_sha256 is not True:
        raise ValueError("retry request hash must be byte-identical")
    if item.retry_reason != "transport_failure":
        raise ValueError("only transport failure may be retried")

    index = {
        attempt["attempt_id"]: position
        for position, attempt in enumerate(attempts)
    }
    if item.original_attempt_id not in index:
        raise ValueError("retry original attempt does not resolve")
    if item.retry_attempt_id not in index:
        raise ValueError("retry attempt does not resolve")
    if index[item.original_attempt_id] >= index[item.retry_attempt_id]:
        raise ValueError("retry attempt must follow original attempt")
    original = attempts[index[item.original_attempt_id]]
    retried = attempts[index[item.retry_attempt_id]]
    if original["status"] != "transport_failure":
        raise ValueError("retry original must be transport failure")
    if original["retry_decision"] != "retry_scheduled":
        raise ValueError("retry original must record scheduling")
    if original["request_sha256"] != retried["request_sha256"]:
        raise ValueError("retry attempts must have matching request hashes")

    return {
        "original_attempt_id": item.original_attempt_id,
        "retry_attempt_id": item.retry_attempt_id,
        "same_request_sha256": True,
        "retry_reason": item.retry_reason,
    }


def _validate_retry_coverage(
    attempts: list[dict[str, Any]],
    retries: list[dict[str, Any]],
) -> None:
    incoming = {
        item["retry_attempt_id"]
        for item in retries
    }
    if len(attempts) > 1:
        for item in attempts[1:]:
            if item["attempt_id"] not in incoming:
                raise ValueError("later attempt requires an explicit retry relation")
    scheduled = {
        item["attempt_id"]
        for item in attempts
        if item["retry_decision"] == "retry_scheduled"
    }
    originals = {
        item["original_attempt_id"]
        for item in retries
    }
    if scheduled != originals:
        raise ValueError("retry scheduling and relationships must agree")


def _consume_response_phase(
    item: ResponsePhaseObservation,
) -> dict[str, str | None]:
    if item.status not in _RESPONSE_STATUSES:
        raise ValueError("response phase status is unsupported")
    if item.status == "rejected":
        if not isinstance(item.failure_kind, str) or not item.failure_kind:
            raise TypeError("rejected response requires a failure kind")
    elif item.failure_kind is not None:
        raise ValueError("non-rejected response cannot have a failure kind")
    return {
        "status": item.status,
        "failure_kind": item.failure_kind,
    }


def _consume_cleanup(
    items: tuple[CleanupItemObservation, ...],
) -> dict[str, Any]:
    if type(items) is not tuple:
        raise TypeError("cleanup must return a tuple")
    output: list[dict[str, Any]] = []
    failed = False
    resource_kinds: set[str] = set()
    for item in items:
        if not isinstance(item, CleanupItemObservation):
            raise TypeError("cleanup item must be CleanupItemObservation")
        if not isinstance(item.resource_kind, str) or not item.resource_kind:
            raise TypeError("cleanup resource kind must be non-empty")
        if item.resource_kind in resource_kinds:
            raise ValueError("cleanup resource kinds must be unique")
        resource_kinds.add(item.resource_kind)
        if type(item.existed_before) is not bool:
            raise TypeError("cleanup existed_before must be boolean")
        if type(item.deletion_attempted) is not bool:
            raise TypeError("cleanup deletion_attempted must be boolean")
        if item.status not in _CLEANUP_STATUSES:
            raise ValueError("cleanup status is unsupported")
        if type(item.residue_count) is not int or item.residue_count < 0:
            raise TypeError("cleanup residue count must be non-negative")
        if item.status in {"removed", "not_present"} and item.residue_count != 0:
            raise ValueError("successful cleanup cannot retain residue")
        if item.status == "failed":
            failed = True
        output.append(
            {
                "resource_kind": item.resource_kind,
                "existed_before": item.existed_before,
                "deletion_attempted": item.deletion_attempted,
                "status": item.status,
                "residue_count": item.residue_count,
            }
        )
    return {
        "status": "failed" if failed else "succeeded",
        "items": output,
    }


def _persist_terminal(
    *,
    document: dict[str, Any],
    active_sink: str | None,
    primary_path: Path,
    emergency_path: Path,
    primary_writer: PersistEffect,
    emergency_writer: PersistEffect,
) -> tuple[str | None, bool]:
    if active_sink == "primary":
        document["persistence"]["primary_status"] = "succeeded"
        try:
            _write_document(primary_writer, primary_path, document)
            return "primary", True
        except Exception:
            document["persistence"]["primary_status"] = "failed"
            _add_failure_code(
                document["failure_codes"],
                ACQUISITION_LEDGER_FAILURE,
            )
            document["status"] = "failed"
            document["terminal_failure_code"] = ACQUISITION_LEDGER_FAILURE
            document["persistence"]["emergency_attempted"] = True
            document["persistence"]["emergency_status"] = "succeeded"
            try:
                _write_document(emergency_writer, emergency_path, document)
                return "emergency", True
            except Exception:
                document["persistence"]["emergency_status"] = "failed"
                return None, False

    if active_sink == "emergency":
        document["persistence"]["emergency_status"] = "succeeded"
        try:
            _write_document(emergency_writer, emergency_path, document)
            return "emergency", True
        except Exception:
            document["persistence"]["emergency_status"] = "failed"
            _add_failure_code(
                document["failure_codes"],
                ACQUISITION_LEDGER_FAILURE,
            )
            document["status"] = "failed"
            document["terminal_failure_code"] = ACQUISITION_LEDGER_FAILURE
            return None, False

    _add_failure_code(document["failure_codes"], ACQUISITION_LEDGER_FAILURE)
    document["status"] = "failed"
    document["terminal_failure_code"] = ACQUISITION_LEDGER_FAILURE
    return None, False


def _set_persistence_failure(
    document: dict[str, Any],
    clock: ClockEffect,
) -> None:
    document["status"] = "evidence_persistence_failed"
    document["terminal_failure_code"] = ACQUISITION_LEDGER_FAILURE
    document["failure_codes"] = [ACQUISITION_LEDGER_FAILURE]
    document["completed_at"] = _read_clock_safely(clock)


def _attempt_failure_code(status: str) -> str | None:
    return {
        "succeeded": None,
        "transport_failure": ACQUISITION_TRANSPORT_FAILURE,
        "http_response_failure": ACQUISITION_HTTP_FAILURE,
        "internal_failure": ACQUISITION_INTERNAL_FAILURE,
    }[status]


def _add_failure_code(codes: list[str], code: str) -> None:
    if code not in FAILURE_CODES:
        raise ValueError("failure code is unsupported")
    if code not in codes:
        codes.append(code)


def _read_clock(clock: ClockEffect) -> str:
    value = clock()
    if not isinstance(value, str) or not value:
        raise TypeError("clock must return a non-empty string")
    return value


def _read_clock_safely(clock: ClockEffect) -> str | None:
    try:
        return _read_clock(clock)
    except Exception:
        return None


def _sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _write_document(
    persist: PersistEffect,
    path: Path,
    document: dict[str, Any],
) -> None:
    encoded = (
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )
        + "\n"
    ).encode("utf-8")
    persist(path, encoded)


def _persist_atomically(path: Path, payload: bytes) -> None:
    temporary_path = path.with_name(
        f"{path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary_path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
