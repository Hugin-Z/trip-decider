"""WU2R Resume acquisition composition interfaces.

This module composes already-frozen failure-evidence and candidate-ingestion
boundaries.  It owns no HTTP client, endpoint selection, retry scheduling,
provider fallback, identity selection, route lookup, or planner behavior.
Every effectful boundary is injected.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from trip_decider.acquisition_evidence import (
    AcquisitionEvidenceResult,
    CleanupEffect,
    PersistEffect,
    ResponsePhaseObservation,
    RunnerObservation,
    run_failure_evidenced_acquisition,
)
from trip_decider.adapters.contracts import IngestionContext, safe_type
from trip_decider.recovery import RecoveryCandidateResult, ingest_candidate_pool
from trip_decider.schema_validation import ValidationProblem


_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_CONTRIBUTOR_ACCOUNT_FIELDS = frozenset({"user", "uid", "changeset"})
_REQUIRED_SEED_STATES = frozenset({"matched", "ambiguous", "unmatched"})
_PROBLEM_MESSAGES = {
    "RESUME_RESPONSE_INVALID": "Captured response bytes are structurally invalid.",
    "RESUME_CONTRIBUTOR_FIELDS_PRESENT": (
        "Captured response contains contributor account fields."
    ),
    "RESUME_SNAPSHOT_METADATA_INVALID": (
        "Captured response metadata does not match the explicit request."
    ),
    "RESUME_COVERAGE_INVALID": (
        "Candidate seed accounting does not contain all required states."
    ),
}


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


def _problem(
    code: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual: object = None,
) -> ValidationProblem:
    if code not in _PROBLEM_MESSAGES:
        raise ValueError("unknown WU2R Resume problem code")
    return ValidationProblem(
        error_code=code,
        artifact_path="",
        json_pointer=pointer,
        schema_rule=rule,
        expected=expected,
        actual_type=safe_type(actual),
        message=_PROBLEM_MESSAGES[code],
    )


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _validate_hash(
    *,
    label: str,
    value: bytes,
    expected: str,
) -> str:
    if type(value) is not bytes:
        raise TypeError(f"{label} bytes must be bytes")
    if not _valid_sha256(expected):
        raise ValueError(f"expected {label} SHA256 is invalid")
    actual = hashlib.sha256(value).hexdigest()
    if actual != expected.lower():
        raise ValueError(f"{label} SHA256 does not match bytes")
    return actual


def _strict_json(raw: bytes) -> object:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("UTF-8 BOM is not allowed")
    text = raw.decode("utf-8", errors="strict")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        output: dict[str, object] = {}
        for key, value in pairs:
            if key in output:
                raise ValueError("duplicate JSON object key")
            output[key] = value
        return output

    def reject_constant(_value: str) -> object:
        raise ValueError("non-finite JSON number")

    return json.loads(
        text,
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )


def _metadata_snapshot(
    metadata: ResumeSnapshotMetadata,
    document: Mapping[str, object],
) -> dict[str, object]:
    return {
        "format_version": metadata.format_version,
        "provider": metadata.provider,
        "operation": metadata.operation,
        "crs": metadata.crs,
        "retrieved_at": metadata.retrieved_at,
        "request_fingerprint": metadata.request_fingerprint,
        "response_locator": copy.deepcopy(dict(metadata.response_locator)),
        "data_policy": copy.deepcopy(dict(metadata.data_policy)),
        "result": {
            "status": "success",
            "document": copy.deepcopy(dict(document)),
        },
    }


def _canonicalize_element_order(
    document: Mapping[str, object],
) -> dict[str, object]:
    output = copy.deepcopy(dict(document))
    elements = output.get("elements")
    if not isinstance(elements, list):
        return output
    sortable = all(
        isinstance(item, Mapping)
        and isinstance(item.get("type"), str)
        and type(item.get("id")) is int
        for item in elements
    )
    if sortable:
        output["elements"] = sorted(
            elements,
            key=lambda item: (str(item["type"]), int(item["id"])),
        )
    return output


def _evaluate_response(
    *,
    response_bytes: bytes,
    snapshot_metadata: ResumeSnapshotMetadata | None,
    request_sha256: str,
    seeds: Sequence[str],
    context: IngestionContext,
) -> tuple[
    RecoveryCandidateResult | None,
    tuple[ValidationProblem, ...],
]:
    if type(response_bytes) is not bytes:
        return (
            None,
            (
                _problem(
                    "RESUME_RESPONSE_INVALID",
                    "",
                    "type",
                    expected="bytes",
                    actual=response_bytes,
                ),
            ),
        )
    try:
        document = _strict_json(response_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return (
            None,
            (
                _problem(
                    "RESUME_RESPONSE_INVALID",
                    "",
                    "strictUtf8Json",
                    expected="unique-key finite UTF-8 JSON object",
                    actual=response_bytes,
                ),
            ),
        )
    if not isinstance(document, Mapping):
        return (
            None,
            (
                _problem(
                    "RESUME_RESPONSE_INVALID",
                    "",
                    "type",
                    expected="object",
                    actual=document,
                ),
            ),
        )
    elements = document.get("elements")
    if isinstance(elements, list):
        for index, element in enumerate(elements):
            if isinstance(element, Mapping):
                forbidden = _CONTRIBUTOR_ACCOUNT_FIELDS.intersection(element)
                if forbidden:
                    return (
                        None,
                        (
                            _problem(
                                "RESUME_CONTRIBUTOR_FIELDS_PRESENT",
                                f"/elements/{index}",
                                "contributorAccountFields",
                                expected="no contributor account fields",
                                actual=element,
                            ),
                        ),
                    )
    if not isinstance(snapshot_metadata, ResumeSnapshotMetadata):
        return (
            None,
            (
                _problem(
                    "RESUME_SNAPSHOT_METADATA_INVALID",
                    "/snapshot_metadata",
                    "type",
                    expected="ResumeSnapshotMetadata",
                    actual=snapshot_metadata,
                ),
            ),
        )
    if (
        not _valid_sha256(snapshot_metadata.request_fingerprint)
        or snapshot_metadata.request_fingerprint.lower() != request_sha256
    ):
        return (
            None,
            (
                _problem(
                    "RESUME_SNAPSHOT_METADATA_INVALID",
                    "/snapshot_metadata/request_fingerprint",
                    "requestFingerprint",
                    expected="captured request SHA256",
                    actual=snapshot_metadata.request_fingerprint,
                ),
            ),
        )

    snapshot = _metadata_snapshot(
        snapshot_metadata,
        _canonicalize_element_order(document),
    )
    candidate = ingest_candidate_pool(snapshot, seeds, context)
    if candidate.problems:
        return None, candidate.problems
    if candidate.value is None:
        raise RuntimeError("candidate ingestion returned neither value nor problems")
    states = {item.status for item in candidate.value.seed_matches}
    if not _REQUIRED_SEED_STATES.issubset(states):
        return (
            None,
            (
                _problem(
                    "RESUME_COVERAGE_INVALID",
                    "/seed_matches",
                    "requiredSeedStates",
                    expected="matched, ambiguous, and unmatched",
                    actual=tuple(sorted(states)),
                ),
            ),
        )
    return candidate.value, ()


def _replace_response_phase(
    observation: RunnerObservation,
    *,
    status: str,
    failure_kind: str | None,
) -> RunnerObservation:
    return RunnerObservation(
        attempts=observation.attempts,
        retries=observation.retries,
        response_phase=ResponsePhaseObservation(
            status=status,
            failure_kind=failure_kind,
        ),
    )


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

    if not isinstance(run_id, str) or not run_id:
        raise TypeError("run_id must be a non-empty string")
    if not isinstance(attempt_group_id, str) or not attempt_group_id:
        raise TypeError("attempt_group_id must be a non-empty string")
    if not isinstance(purpose, str) or not purpose:
        raise TypeError("purpose must be a non-empty string")
    if not isinstance(failure_evidence_path, Path):
        raise TypeError("failure_evidence_path must be a pathlib.Path")
    if not isinstance(emergency_evidence_path, Path):
        raise TypeError("emergency_evidence_path must be a pathlib.Path")
    if not callable(capture):
        raise TypeError("capture must be callable")
    if not callable(cleanup):
        raise TypeError("cleanup must be callable")
    if not callable(clock):
        raise TypeError("clock must be callable")
    if not isinstance(context, IngestionContext):
        raise TypeError("context must be IngestionContext")

    query_sha256 = _validate_hash(
        label="query",
        value=query_bytes,
        expected=expected_query_sha256,
    )
    request_sha256 = _validate_hash(
        label="request",
        value=request_bytes,
        expected=expected_request_sha256,
    )
    candidate_result: RecoveryCandidateResult | None = None
    eligible_response_bytes: bytes | None = None
    problems: tuple[ValidationProblem, ...] = ()

    def runner(request: bytes) -> RunnerObservation:
        nonlocal candidate_result, eligible_response_bytes, problems
        captured = capture(request)
        if not isinstance(captured, ResumeCaptureObservation):
            raise TypeError("capture must return ResumeCaptureObservation")
        observation = captured.runner_observation
        if not isinstance(observation, RunnerObservation):
            raise TypeError("capture runner observation is invalid")
        if (
            observation.response_phase.status != "not_evaluated"
            or observation.response_phase.failure_kind is not None
        ):
            raise ValueError("capture cannot pre-evaluate the response phase")
        if not observation.attempts:
            raise ValueError("capture must include at least one attempt")

        terminal_attempt = observation.attempts[-1]
        if terminal_attempt.status != "succeeded":
            if (
                captured.response_bytes is not None
                or captured.snapshot_metadata is not None
            ):
                raise ValueError("failed capture cannot return response content")
            return observation

        if type(captured.response_bytes) is not bytes:
            candidate_result = None
            eligible_response_bytes = None
            problems = (
                _problem(
                    "RESUME_RESPONSE_INVALID",
                    "",
                    "capturedBody",
                    expected="bytes",
                    actual=captured.response_bytes,
                ),
            )
            return _replace_response_phase(
                observation,
                status="rejected",
                failure_kind="missing_response_bytes",
            )
        response_hash = hashlib.sha256(captured.response_bytes).hexdigest()
        if (
            terminal_attempt.response_bytes != len(captured.response_bytes)
            or terminal_attempt.response_sha256 != response_hash
        ):
            raise ValueError("captured bytes do not match attempt metadata")

        candidate_result, problems = _evaluate_response(
            response_bytes=captured.response_bytes,
            snapshot_metadata=captured.snapshot_metadata,
            request_sha256=request_sha256,
            seeds=seeds,
            context=context,
        )
        if problems:
            eligible_response_bytes = None
            return _replace_response_phase(
                observation,
                status="rejected",
                failure_kind=problems[0].error_code.lower(),
            )
        if candidate_result is None:
            raise RuntimeError("response gate returned no result")
        eligible_response_bytes = captured.response_bytes
        return _replace_response_phase(
            observation,
            status="accepted",
            failure_kind=None,
        )

    evidence = run_failure_evidenced_acquisition(
        run_id=run_id,
        purpose=purpose,
        request_bytes=request_bytes,
        primary_path=failure_evidence_path,
        emergency_path=emergency_evidence_path,
        runner=runner,
        cleanup=cleanup,
        clock=clock,
        primary_persist=primary_persist,
        emergency_persist=emergency_persist,
    )
    if (
        not evidence.durable_evidence
        or evidence.document.get("status") != "succeeded"
    ):
        candidate_result = None
        eligible_response_bytes = None

    return ResumeAcquisitionResult(
        run_id=run_id,
        attempt_group_id=attempt_group_id,
        query_sha256=expected_query_sha256,
        request_sha256=expected_request_sha256,
        failure_evidence_path=failure_evidence_path,
        evidence=evidence,
        candidate_result=candidate_result,
        eligible_response_bytes=eligible_response_bytes,
        problems=problems,
    )


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

    if not isinstance(run_id, str) or not run_id:
        raise TypeError("run_id must be a non-empty string")
    if not isinstance(context, IngestionContext):
        raise TypeError("context must be IngestionContext")
    query_sha256 = _validate_hash(
        label="query",
        value=query_bytes,
        expected=expected_query_sha256,
    )
    request_sha256 = _validate_hash(
        label="request",
        value=request_bytes,
        expected=expected_request_sha256,
    )
    response_sha256 = _validate_hash(
        label="response",
        value=response_bytes,
        expected=expected_response_sha256,
    )
    candidate_result, problems = _evaluate_response(
        response_bytes=response_bytes,
        snapshot_metadata=snapshot_metadata,
        request_sha256=request_sha256,
        seeds=seeds,
        context=context,
    )
    if problems or candidate_result is None:
        code = problems[0].error_code if problems else "RESUME_RESPONSE_INVALID"
        raise ValueError(f"WU2R Resume replay rejected: {code}")
    return ResumeReplayResult(
        run_id=run_id,
        query_sha256=expected_query_sha256,
        request_sha256=expected_request_sha256,
        response_sha256=response_sha256,
        response_bytes=len(response_bytes),
        candidate_result=candidate_result,
        network_attempts=0,
        problems=(),
    )
