"""Deterministic conditional coarse-planner interface.

WU4-CP consumes only explicit structured constraints plus completed Recovery
and Evidence Runtime outputs.  It does not parse natural language, resolve
identity ambiguity, call external services, or establish route feasibility.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import re

from trip_decider.adapters.contracts import (
    safe_type,
    stable_artifact_id,
    stable_identifier,
)
from trip_decider.schema_validation import (
    BundleClosure,
    LoadedDocument,
    ValidationProblem,
    ValidationResult,
    canonical_payload_sha256,
    load_document,
    validate_artifact,
    validate_bundle,
    validate_schema_registry,
)


COARSE_PLANNER_PROBLEM_CODES = frozenset(
    {
        "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
        "COARSE_PLANNER_INPUT_INVALID",
        "COARSE_PLANNER_INTERNAL_ERROR",
        "COARSE_PLANNER_OUTPUT_HASH_MISMATCH",
        "COARSE_PLANNER_OUTPUT_ROOT_INVALID",
        "COARSE_PLANNER_REFERENCE_INVALID",
    }
)


@dataclass(frozen=True)
class CoarsePlannerSummary:
    """Auditable paths and counts for one offline coarse-planner run."""

    run_id: str
    plan_path: Path
    violations_path: Path
    planning_gate_path: Path
    run_summary_path: Path
    planning_status: str
    draft_created: bool
    day_count: int
    eligible_candidate_count: int
    required_candidate_count: int
    scheduled_candidate_count: int
    blocked_seed_count: int
    network_attempts: int
    llm_calls: int
    output_sha256: Mapping[str, str]


@dataclass(frozen=True)
class _InputSet:
    recovery: Mapping[str, Mapping[str, object]]
    evidence: Mapping[str, Mapping[str, object]]
    planning: Mapping[str, Mapping[str, object]]
    formal: Mapping[str, LoadedDocument]
    hashes: Mapping[str, str]


@dataclass(frozen=True)
class _ConstraintProfile:
    dates: tuple[str, ...]
    time_constraint: Mapping[str, object]
    must_constraint: Mapping[str, object] | None
    excluded_constraint: Mapping[str, object] | None
    enabled_constraints: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class _Admission:
    candidate_by_id: Mapping[str, Mapping[str, object]]
    candidate_result_by_id: Mapping[str, Mapping[str, object]]
    seed_results: tuple[Mapping[str, object], ...]
    eligible_refs: tuple[str, ...]
    required_refs: tuple[str, ...]
    unselected_refs: tuple[str, ...]
    excluded_refs: tuple[str, ...]
    blocked_seeds: tuple[Mapping[str, object], ...]
    unmet_must: tuple[Mapping[str, object], ...]


class _RuntimeIssue(ValueError):
    def __init__(
        self,
        code: str,
        pointer: str,
        rule: str,
        *,
        expected: str = "",
        actual: object = None,
        artifact_path: str = "",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.pointer = pointer
        self.rule = rule
        self.expected = expected
        self.actual = actual
        self.artifact_path = artifact_path


_RECOVERY_FILENAMES = (
    "candidates.json",
    "seed-accounting.json",
    "record-local-facts.json",
    "run-summary.json",
)
_EVIDENCE_FILENAMES = (
    "evidence.json",
    "evidence-gate.json",
    "run-summary.json",
)
_PLANNING_FILENAMES = (
    "request.yaml",
    "constraint-parse.json",
    "constraints.yaml",
)
_OUTPUT_FILENAMES = (
    "plan.json",
    "violations.json",
    "planning-gate.json",
    "run-summary.json",
)
_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"
_MESSAGES = {
    "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED": (
        "Enabled constraint is outside the approved coarse-planner profile."
    ),
    "COARSE_PLANNER_INPUT_INVALID": (
        "Coarse-planner input is incomplete or structurally invalid."
    ),
    "COARSE_PLANNER_INTERNAL_ERROR": (
        "Coarse-planner validation or registry capability failed."
    ),
    "COARSE_PLANNER_OUTPUT_HASH_MISMATCH": (
        "Installed coarse-planner bytes do not match prepared bytes."
    ),
    "COARSE_PLANNER_OUTPUT_ROOT_INVALID": (
        "Coarse-planner output root must be missing or empty."
    ),
    "COARSE_PLANNER_REFERENCE_INVALID": (
        "Coarse-planner artifact or entity reference is invalid."
    ),
}
_PROFILE = {
    "time_window": ("within", "travel_window"),
    "must_visit": ("include", "must_visit"),
    "excluded": ("exclude", "excluded"),
}
_DATE_RANGE = re.compile(
    r"^(?P<start>[0-9]{4}-[0-9]{2}-[0-9]{2})/"
    r"(?P<end>[0-9]{4}-[0-9]{2}-[0-9]{2})$"
)


def _problem(
    code: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual: object = None,
    artifact_path: str = "",
) -> ValidationProblem:
    if code not in COARSE_PLANNER_PROBLEM_CODES:
        raise ValueError("unknown coarse-planner problem code")
    return ValidationProblem(
        error_code=code,
        artifact_path=artifact_path,
        json_pointer=pointer,
        schema_rule=rule,
        expected=expected,
        actual_type=safe_type(actual),
        message=_MESSAGES[code],
    )


def _failure(
    issue: _RuntimeIssue,
) -> ValidationResult[CoarsePlannerSummary]:
    return ValidationResult(
        None,
        (
            _problem(
                issue.code,
                issue.pointer,
                issue.rule,
                expected=issue.expected,
                actual=issue.actual,
                artifact_path=issue.artifact_path,
            ),
        ),
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )


def _mapping(
    value: object,
    pointer: str,
    *,
    keys: set[str] | None = None,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _RuntimeIssue(
            "COARSE_PLANNER_INPUT_INVALID",
            pointer,
            "object",
            expected="object",
            actual=value,
        )
    if keys is not None and set(value) != keys:
        raise _RuntimeIssue(
            "COARSE_PLANNER_INPUT_INVALID",
            pointer,
            "exactKeys",
            expected="approved exact keys",
            actual=value,
        )
    return value


def _sequence(value: object, pointer: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _RuntimeIssue(
            "COARSE_PLANNER_INPUT_INVALID",
            pointer,
            "array",
            expected="array",
            actual=value,
        )
    return value


def _logical_ref(document: Mapping[str, object]) -> dict[str, object]:
    integrity = _mapping(document.get("integrity"), "/integrity")
    return {
        "artifact_id": document["artifact_id"],
        "artifact_type": document["artifact_type"],
        "schema_version": document["schema_version"],
        "payload_sha256": integrity["payload_sha256"],
    }


def _load_root(
    root: Path,
    root_label: str,
    filenames: Sequence[str],
    formal_types: Mapping[str, str],
) -> tuple[
    dict[str, Mapping[str, object]],
    dict[str, LoadedDocument],
    dict[str, str],
]:
    if root.is_symlink() or not root.is_dir():
        raise _RuntimeIssue(
            "COARSE_PLANNER_INPUT_INVALID",
            f"/{root_label}",
            "directory",
            expected=f"regular {root_label} directory",
            artifact_path=root_label,
        )
    values: dict[str, Mapping[str, object]] = {}
    formal: dict[str, LoadedDocument] = {}
    hashes: dict[str, str] = {}
    for filename in filenames:
        path = root / filename
        logical_path = f"{root_label}/{filename}"
        if path.is_symlink() or not path.is_file():
            raise _RuntimeIssue(
                "COARSE_PLANNER_INPUT_INVALID",
                f"/{root_label}/{filename}",
                "regularFile",
                expected="named regular file",
                artifact_path=logical_path,
            )
        loaded = load_document(
            path,
            expected_artifact_type=formal_types.get(filename),
        )
        if loaded.problems or loaded.value is None:
            problem = loaded.problems[0] if loaded.problems else None
            raise _RuntimeIssue(
                "COARSE_PLANNER_INPUT_INVALID",
                problem.json_pointer if problem else "",
                problem.schema_rule if problem else "loadedDocument",
                expected="strict UTF-8 JSON/YAML document",
                artifact_path=logical_path,
            )
        value = loaded.value.data
        if not isinstance(value, Mapping):
            raise _RuntimeIssue(
                "COARSE_PLANNER_INPUT_INVALID",
                f"/{root_label}/{filename}",
                "object",
                expected="JSON/YAML object",
                actual=value,
                artifact_path=logical_path,
            )
        values[filename] = value
        hashes[logical_path] = _sha256(path.read_bytes())
        if filename in formal_types:
            formal[logical_path] = loaded.value
    return values, formal, hashes


def _validate_registry():
    registry = validate_schema_registry(
        tuple(sorted(_SCHEMA_ROOT.glob("*.schema.json")))
    )
    if registry.problems or registry.value is None:
        problem = registry.problems[0] if registry.problems else None
        raise _RuntimeIssue(
            "COARSE_PLANNER_INTERNAL_ERROR",
            problem.json_pointer if problem else "/schemas",
            problem.schema_rule if problem else "schemaRegistry",
            expected="valid 11-schema registry",
            artifact_path="schemas",
        )
    return registry.value


def _validate_artifact_input(
    document: LoadedDocument,
    registry,
    logical_path: str,
) -> None:
    result = validate_artifact(document, registry)
    if result.problems:
        problem = result.problems[0]
        raise _RuntimeIssue(
            "COARSE_PLANNER_INPUT_INVALID",
            problem.json_pointer,
            problem.schema_rule,
            expected="schema-valid artifact",
            artifact_path=logical_path,
        )


def _validate_input_controls(inputs: _InputSet) -> None:
    recovery = inputs.recovery
    evidence = inputs.evidence
    candidates = recovery["candidates.json"]
    candidate_payload = _mapping(
        candidates.get("payload"),
        "/recovery/candidates/payload",
    )
    candidate_items = _sequence(
        candidate_payload.get("candidates"),
        "/recovery/candidates/payload/candidates",
    )

    seed_document = _mapping(
        recovery["seed-accounting.json"],
        "/recovery/seed_accounting",
        keys={"schema_version", "run_id", "seed_matches"},
    )
    fact_document = _mapping(
        recovery["record-local-facts.json"],
        "/recovery/record_local_facts",
        keys={"schema_version", "run_id", "record_local_facts"},
    )
    recovery_summary = _mapping(
        recovery["run-summary.json"],
        "/recovery/run_summary",
        keys={
            "schema_version",
            "run_id",
            "input_fixture_identity",
            "output_paths",
            "candidate_count",
            "seed_status_counts",
            "network_attempts",
            "output_sha256",
            "completion_status",
        },
    )
    recovery_run_id = recovery_summary.get("run_id")
    if (
        recovery_summary.get("schema_version")
        != "wu2r-downstream-recovery-run/1.0"
        or not isinstance(recovery_run_id, str)
        or not recovery_run_id
        or recovery_summary.get("candidate_count") != len(candidate_items)
        or recovery_summary.get("network_attempts") != 0
        or recovery_summary.get("completion_status") != "completed"
        or seed_document.get("run_id") != recovery_run_id
        or fact_document.get("run_id") != recovery_run_id
        or seed_document.get("schema_version")
        != "wu2r-downstream-seed-accounting/1.0"
        or fact_document.get("schema_version")
        != "wu2r-downstream-record-local-facts/1.0"
    ):
        raise _RuntimeIssue(
            "COARSE_PLANNER_INPUT_INVALID",
            "/recovery/run_summary",
            "completedRecoveryRun",
        )
    if recovery_summary.get("output_paths") != {
        "candidate_artifact_path": "candidates.json",
        "seed_accounting_path": "seed-accounting.json",
        "record_local_facts_path": "record-local-facts.json",
        "run_summary_path": "run-summary.json",
    }:
        raise _RuntimeIssue(
            "COARSE_PLANNER_INPUT_INVALID",
            "/recovery/run_summary/output_paths",
            "exactOutputPaths",
        )
    recovery_output_hashes = {
        filename: inputs.hashes[f"recovery/{filename}"]
        for filename in _RECOVERY_FILENAMES
        if filename != "run-summary.json"
    }
    if recovery_summary.get("output_sha256") != recovery_output_hashes:
        raise _RuntimeIssue(
            "COARSE_PLANNER_INPUT_INVALID",
            "/recovery/run_summary/output_sha256",
            "actualBytes",
        )

    evidence_artifact = evidence["evidence.json"]
    evidence_gate = _mapping(
        evidence["evidence-gate.json"],
        "/evidence/gate",
        keys={
            "schema_version",
            "run_id",
            "candidate_results",
            "seed_results",
            "generation_allowed",
        },
    )
    evidence_summary = _mapping(
        evidence["run-summary.json"],
        "/evidence/run_summary",
        keys={
            "schema_version",
            "run_id",
            "input_recovery_identity",
            "evidence_artifact_id",
            "evidence_payload_sha256",
            "candidate_count",
            "complete_candidate_count",
            "incomplete_candidate_count",
            "eligible_seed_count",
            "blocked_seed_count",
            "generation_allowed",
            "network_attempts",
            "output_sha256",
            "completion_status",
        },
    )
    candidate_results = _sequence(
        evidence_gate.get("candidate_results"),
        "/evidence/gate/candidate_results",
    )
    seed_results = _sequence(
        evidence_gate.get("seed_results"),
        "/evidence/gate/seed_results",
    )
    evidence_run_id = evidence_summary.get("run_id")
    complete_count = sum(
        isinstance(item, Mapping)
        and item.get("evidence_complete") is True
        for item in candidate_results
    )
    eligible_count = sum(
        isinstance(item, Mapping)
        and item.get("generation_status") == "ELIGIBLE"
        for item in seed_results
    )
    generation_allowed = all(
        isinstance(item, Mapping)
        and item.get("generation_status") == "ELIGIBLE"
        for item in seed_results
    )
    if (
        evidence_summary.get("schema_version")
        != "wu3-evidence-runtime-run/1.0"
        or evidence_gate.get("schema_version")
        != "wu3-evidence-gate/1.0"
        or not isinstance(evidence_run_id, str)
        or not evidence_run_id
        or evidence_gate.get("run_id") != evidence_run_id
        or evidence_summary.get("candidate_count") != len(candidate_results)
        or evidence_summary.get("complete_candidate_count") != complete_count
        or evidence_summary.get("incomplete_candidate_count")
        != len(candidate_results) - complete_count
        or evidence_summary.get("eligible_seed_count") != eligible_count
        or evidence_summary.get("blocked_seed_count")
        != len(seed_results) - eligible_count
        or evidence_summary.get("generation_allowed") is not generation_allowed
        or evidence_gate.get("generation_allowed") is not generation_allowed
        or evidence_summary.get("network_attempts") != 0
        or evidence_summary.get("completion_status") != "completed"
        or evidence_summary.get("evidence_artifact_id")
        != evidence_artifact.get("artifact_id")
        or evidence_summary.get("evidence_payload_sha256")
        != _mapping(
            evidence_artifact.get("integrity"),
            "/evidence/integrity",
        ).get("payload_sha256")
    ):
        raise _RuntimeIssue(
            "COARSE_PLANNER_INPUT_INVALID",
            "/evidence/run_summary",
            "completedEvidenceRun",
        )
    evidence_output_hashes = {
        filename: inputs.hashes[f"evidence/{filename}"]
        for filename in _EVIDENCE_FILENAMES
        if filename != "run-summary.json"
    }
    if evidence_summary.get("output_sha256") != evidence_output_hashes:
        raise _RuntimeIssue(
            "COARSE_PLANNER_INPUT_INVALID",
            "/evidence/run_summary/output_sha256",
            "actualBytes",
        )
    recovery_identity = _mapping(
        evidence_summary.get("input_recovery_identity"),
        "/evidence/run_summary/input_recovery_identity",
    )
    if (
        recovery_identity.get("run_id") != recovery_run_id
        or recovery_identity.get("candidate_artifact_id")
        != candidates.get("artifact_id")
        or recovery_identity.get("input_file_sha256")
        != {
            filename: inputs.hashes[f"recovery/{filename}"]
            for filename in _RECOVERY_FILENAMES
        }
        or recovery_identity.get("declared_output_sha256")
        != recovery_output_hashes
    ):
        raise _RuntimeIssue(
            "COARSE_PLANNER_REFERENCE_INVALID",
            "/evidence/run_summary/input_recovery_identity",
            "recoveryIdentity",
        )
    recovery_seeds = _sequence(
        seed_document.get("seed_matches"),
        "/recovery/seed_accounting/seed_matches",
    )
    if len(recovery_seeds) != len(seed_results):
        raise _RuntimeIssue(
            "COARSE_PLANNER_REFERENCE_INVALID",
            "/evidence/gate/seed_results",
            "seedAccounting",
        )
    for index, (recovery_seed, evidence_seed) in enumerate(
        zip(recovery_seeds, seed_results, strict=True)
    ):
        recovery_item = _mapping(
            recovery_seed,
            f"/recovery/seed_accounting/seed_matches/{index}",
            keys={"seed", "status", "candidate_refs"},
        )
        evidence_item = _mapping(
            evidence_seed,
            f"/evidence/gate/seed_results/{index}",
            keys={
                "seed",
                "identity_status",
                "candidate_refs",
                "generation_status",
                "block_reasons",
            },
        )
        if (
            evidence_item.get("seed") != recovery_item.get("seed")
            or evidence_item.get("identity_status")
            != recovery_item.get("status")
            or evidence_item.get("candidate_refs")
            != recovery_item.get("candidate_refs")
        ):
            raise _RuntimeIssue(
                "COARSE_PLANNER_REFERENCE_INVALID",
                f"/evidence/gate/seed_results/{index}",
                "seedAccounting",
            )


def _load_inputs(
    recovery_root: Path,
    evidence_root: Path,
    planning_root: Path,
    registry,
) -> _InputSet:
    recovery, recovery_formal, recovery_hashes = _load_root(
        recovery_root,
        "recovery",
        _RECOVERY_FILENAMES,
        {"candidates.json": "candidates"},
    )
    evidence, evidence_formal, evidence_hashes = _load_root(
        evidence_root,
        "evidence",
        _EVIDENCE_FILENAMES,
        {"evidence.json": "evidence"},
    )
    planning, planning_formal, planning_hashes = _load_root(
        planning_root,
        "planning",
        _PLANNING_FILENAMES,
        {
            "request.yaml": "request",
            "constraint-parse.json": "constraint-parse",
            "constraints.yaml": "constraints",
        },
    )
    formal = {
        **recovery_formal,
        **evidence_formal,
        **planning_formal,
    }
    inputs = _InputSet(
        recovery=recovery,
        evidence=evidence,
        planning=planning,
        formal=formal,
        hashes={
            **recovery_hashes,
            **evidence_hashes,
            **planning_hashes,
        },
    )
    _validate_artifact_input(
        formal["recovery/candidates.json"],
        registry,
        "recovery/candidates.json",
    )
    _validate_artifact_input(
        formal["evidence/evidence.json"],
        registry,
        "evidence/evidence.json",
    )
    planning_bundle = validate_bundle(
        (
            formal["planning/request.yaml"],
            formal["planning/constraint-parse.json"],
            formal["planning/constraints.yaml"],
        ),
        registry,
        closure=BundleClosure.CLOSED,
        root_artifact_id=str(planning["constraints.yaml"]["artifact_id"]),
    )
    if planning_bundle.problems:
        problem = planning_bundle.problems[0]
        raise _RuntimeIssue(
            "COARSE_PLANNER_INPUT_INVALID",
            problem.json_pointer,
            problem.schema_rule,
            expected="CLOSED planning input bundle",
            artifact_path="planning",
        )
    if (
        _mapping(
            recovery["candidates.json"].get("payload"),
            "/recovery/candidates/payload",
        ).get("request_ref")
        != _logical_ref(planning["request.yaml"])
    ):
        raise _RuntimeIssue(
            "COARSE_PLANNER_REFERENCE_INVALID",
            "/recovery/candidates/payload/request_ref",
            "planningRequestIdentity",
        )
    _validate_input_controls(inputs)
    return inputs


def _date_range(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        raise _RuntimeIssue(
            "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
            "/constraints/time_window/value",
            "dateRange",
            expected="YYYY-MM-DD/YYYY-MM-DD",
            actual=value,
        )
    matched = _DATE_RANGE.fullmatch(value)
    if matched is None:
        raise _RuntimeIssue(
            "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
            "/constraints/time_window/value",
            "dateRange",
            expected="YYYY-MM-DD/YYYY-MM-DD",
            actual=value,
        )
    try:
        start = date.fromisoformat(matched.group("start"))
        end = date.fromisoformat(matched.group("end"))
    except ValueError as error:
        raise _RuntimeIssue(
            "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
            "/constraints/time_window/value",
            "dateRange",
            expected="valid ISO dates",
        ) from error
    if start > end:
        raise _RuntimeIssue(
            "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
            "/constraints/time_window/value",
            "orderedDateRange",
            expected="start not later than end",
        )
    return tuple(
        date.fromordinal(day).isoformat()
        for day in range(start.toordinal(), end.toordinal() + 1)
    )


def _constraint_profile(inputs: _InputSet) -> _ConstraintProfile:
    request_payload = _mapping(
        inputs.planning["request.yaml"].get("payload"),
        "/planning/request/payload",
    )
    request_id = request_payload.get("request_id")
    constraints_payload = _mapping(
        inputs.planning["constraints.yaml"].get("payload"),
        "/planning/constraints/payload",
    )
    raw_constraints = _sequence(
        constraints_payload.get("constraints"),
        "/planning/constraints/payload/constraints",
    )
    enabled: list[Mapping[str, object]] = []
    by_category: dict[str, Mapping[str, object]] = {}
    for index, raw in enumerate(raw_constraints):
        item = _mapping(
            raw,
            f"/planning/constraints/payload/constraints/{index}",
        )
        if item.get("enabled") is not True:
            continue
        category = item.get("category")
        if not isinstance(category, str) or category not in _PROFILE:
            raise _RuntimeIssue(
                "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
                f"/planning/constraints/payload/constraints/{index}",
                "supportedCategory",
                expected="time_window|must_visit|excluded",
                actual=category,
            )
        expected_operator, expected_scope = _PROFILE[category]
        origin = _mapping(
            item.get("origin"),
            f"/planning/constraints/payload/constraints/{index}/origin",
        )
        target_refs = item.get("target_refs")
        expected_target = [
            {
                "target_type": "request_scope",
                "request_id": request_id,
                "scope_kind": expected_scope,
            }
        ]
        if (
            item.get("layer") != "hard"
            or item.get("operator") != expected_operator
            or target_refs != expected_target
            or item.get("unit") is not None
            or origin.get("kind") not in {"explicit", "user_edited"}
            or category in by_category
        ):
            raise _RuntimeIssue(
                "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
                f"/planning/constraints/payload/constraints/{index}",
                "exactConstraintProfile",
                expected=(
                    f"one enabled hard {category}/{expected_operator} "
                    f"request_scope/{expected_scope}"
                ),
            )
        by_category[category] = item
        enabled.append(item)
    time_constraint = by_category.get("time_window")
    if time_constraint is None:
        raise _RuntimeIssue(
            "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
            "/planning/constraints/payload/constraints",
            "requiredTimeWindow",
            expected="one enabled time_window/within constraint",
        )
    dates = _date_range(time_constraint.get("value"))
    for category in ("must_visit", "excluded"):
        item = by_category.get(category)
        if item is None:
            continue
        values = _sequence(
            item.get("value"),
            f"/planning/constraints/{category}/value",
        )
        checked: list[str] = []
        for value in values:
            if not isinstance(value, str) or not value or value in checked:
                raise _RuntimeIssue(
                    "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
                    f"/planning/constraints/{category}/value",
                    "uniqueNonemptyStrings",
                    expected="non-empty unique string array",
                    actual=value,
                )
            checked.append(value)
        if not checked:
            raise _RuntimeIssue(
                "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
                f"/planning/constraints/{category}/value",
                "minItems",
                expected="non-empty unique string array",
            )
    return _ConstraintProfile(
        dates=dates,
        time_constraint=time_constraint,
        must_constraint=by_category.get("must_visit"),
        excluded_constraint=by_category.get("excluded"),
        enabled_constraints=tuple(enabled),
    )


def _admission(inputs: _InputSet, profile: _ConstraintProfile) -> _Admission:
    candidate_payload = _mapping(
        inputs.recovery["candidates.json"].get("payload"),
        "/recovery/candidates/payload",
    )
    candidate_items = _sequence(
        candidate_payload.get("candidates"),
        "/recovery/candidates/payload/candidates",
    )
    candidate_by_id: dict[str, Mapping[str, object]] = {}
    candidate_order: list[str] = []
    for index, raw in enumerate(candidate_items):
        item = _mapping(
            raw,
            f"/recovery/candidates/payload/candidates/{index}",
        )
        candidate_id = item.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id in candidate_by_id:
            raise _RuntimeIssue(
                "COARSE_PLANNER_REFERENCE_INVALID",
                f"/recovery/candidates/payload/candidates/{index}/candidate_id",
                "uniqueCandidate",
            )
        candidate_by_id[candidate_id] = item
        candidate_order.append(candidate_id)

    evidence_payload = _mapping(
        inputs.evidence["evidence.json"].get("payload"),
        "/evidence/payload",
    )
    facts = _sequence(
        evidence_payload.get("facts"),
        "/evidence/payload/facts",
    )
    fact_by_id: dict[str, Mapping[str, object]] = {}
    for index, raw in enumerate(facts):
        fact = _mapping(raw, f"/evidence/payload/facts/{index}")
        fact_id = fact.get("fact_id")
        if not isinstance(fact_id, str) or fact_id in fact_by_id:
            raise _RuntimeIssue(
                "COARSE_PLANNER_REFERENCE_INVALID",
                f"/evidence/payload/facts/{index}/fact_id",
                "uniqueFact",
            )
        fact_by_id[fact_id] = fact

    gate = _mapping(
        inputs.evidence["evidence-gate.json"],
        "/evidence/gate",
    )
    raw_candidate_results = _sequence(
        gate.get("candidate_results"),
        "/evidence/gate/candidate_results",
    )
    candidate_result_by_id: dict[str, Mapping[str, object]] = {}
    for index, raw in enumerate(raw_candidate_results):
        result = _mapping(
            raw,
            f"/evidence/gate/candidate_results/{index}",
            keys={
                "candidate_ref",
                "evidence_complete",
                "required_slots",
                "satisfied_slots",
                "missing_slots",
                "fact_refs",
                "support_ceiling",
                "hard_conflict",
            },
        )
        candidate_ref = result.get("candidate_ref")
        fact_refs = _sequence(
            result.get("fact_refs"),
            f"/evidence/gate/candidate_results/{index}/fact_refs",
        )
        if (
            not isinstance(candidate_ref, str)
            or candidate_ref not in candidate_by_id
            or candidate_ref in candidate_result_by_id
            or any(ref not in fact_by_id for ref in fact_refs)
            or any(
                _mapping(
                    fact_by_id[str(ref)].get("subject"),
                    "/evidence/fact/subject",
                ).get("entity_id")
                != candidate_ref
                for ref in fact_refs
            )
        ):
            raise _RuntimeIssue(
                "COARSE_PLANNER_REFERENCE_INVALID",
                f"/evidence/gate/candidate_results/{index}",
                "candidateEvidenceReferences",
            )
        candidate_result_by_id[candidate_ref] = result
    if set(candidate_result_by_id) != set(candidate_by_id):
        raise _RuntimeIssue(
            "COARSE_PLANNER_REFERENCE_INVALID",
            "/evidence/gate/candidate_results",
            "completeCandidateCoverage",
        )

    raw_seed_results = _sequence(
        gate.get("seed_results"),
        "/evidence/gate/seed_results",
    )
    seed_results: list[Mapping[str, object]] = []
    seed_by_name: dict[str, Mapping[str, object]] = {}
    candidate_seed: dict[str, Mapping[str, object]] = {}
    eligible_refs: list[str] = []
    blocked: list[Mapping[str, object]] = []
    for index, raw in enumerate(raw_seed_results):
        item = _mapping(
            raw,
            f"/evidence/gate/seed_results/{index}",
            keys={
                "seed",
                "identity_status",
                "candidate_refs",
                "generation_status",
                "block_reasons",
            },
        )
        seed = item.get("seed")
        refs = _sequence(
            item.get("candidate_refs"),
            f"/evidence/gate/seed_results/{index}/candidate_refs",
        )
        if (
            not isinstance(seed, str)
            or not seed
            or seed in seed_by_name
            or len(set(refs)) != len(refs)
            or any(ref not in candidate_by_id for ref in refs)
        ):
            raise _RuntimeIssue(
                "COARSE_PLANNER_REFERENCE_INVALID",
                f"/evidence/gate/seed_results/{index}",
                "seedCandidateReferences",
            )
        seed_by_name[seed] = item
        seed_results.append(item)
        for ref in refs:
            if str(ref) in candidate_seed:
                raise _RuntimeIssue(
                    "COARSE_PLANNER_REFERENCE_INVALID",
                    f"/evidence/gate/seed_results/{index}/candidate_refs",
                    "oneSeedPerCandidate",
                )
            candidate_seed[str(ref)] = item
        if item.get("generation_status") == "ELIGIBLE":
            if len(refs) != 1:
                raise _RuntimeIssue(
                    "COARSE_PLANNER_REFERENCE_INVALID",
                    f"/evidence/gate/seed_results/{index}",
                    "uniqueEligibleCandidate",
                )
            ref = str(refs[0])
            candidate_result = candidate_result_by_id[ref]
            if (
                candidate_result.get("evidence_complete") is not True
                or candidate_result.get("hard_conflict") is not False
                or candidate_result.get("missing_slots") != []
            ):
                raise _RuntimeIssue(
                    "COARSE_PLANNER_REFERENCE_INVALID",
                    f"/evidence/gate/seed_results/{index}",
                    "completeEligibleEvidence",
                )
            if ref in eligible_refs:
                raise _RuntimeIssue(
                    "COARSE_PLANNER_REFERENCE_INVALID",
                    f"/evidence/gate/seed_results/{index}",
                    "uniqueEligibleCandidate",
                )
            eligible_refs.append(ref)
        else:
            blocked.append(copy.deepcopy(dict(item)))

    def resolve_token(token: str) -> tuple[str, ...]:
        seed_match = seed_by_name.get(token)
        candidate_match = candidate_by_id.get(token)
        if seed_match is not None and candidate_match is not None:
            raise _RuntimeIssue(
                "COARSE_PLANNER_REFERENCE_INVALID",
                "/constraints/value",
                "unambiguousExactReference",
            )
        if seed_match is not None:
            return tuple(str(ref) for ref in seed_match["candidate_refs"])
        if candidate_match is not None:
            return (token,)
        raise _RuntimeIssue(
            "COARSE_PLANNER_REFERENCE_INVALID",
            "/constraints/value",
            "existingSeedOrCandidate",
        )

    excluded_tokens = (
        list(profile.excluded_constraint["value"])
        if profile.excluded_constraint is not None
        else []
    )
    excluded_set: set[str] = set()
    for token in excluded_tokens:
        excluded_set.update(resolve_token(str(token)))

    must_tokens = (
        list(profile.must_constraint["value"])
        if profile.must_constraint is not None
        else []
    )
    if set(must_tokens).intersection(excluded_tokens):
        raise _RuntimeIssue(
            "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
            "/planning/constraints",
            "mustExcludedDisjoint",
        )
    for must_token in must_tokens:
        if set(resolve_token(str(must_token))).intersection(excluded_set):
            raise _RuntimeIssue(
                "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
                "/planning/constraints",
                "mustExcludedDisjoint",
            )

    required: list[str] = []
    unmet: list[Mapping[str, object]] = []
    if profile.must_constraint is None:
        required.extend(
            ref for ref in eligible_refs if ref not in excluded_set
        )
    else:
        for token in must_tokens:
            token_text = str(token)
            seed_match = seed_by_name.get(token_text)
            candidate_match = candidate_by_id.get(token_text)
            if seed_match is not None:
                refs = [str(ref) for ref in seed_match["candidate_refs"]]
                if (
                    seed_match.get("generation_status") == "ELIGIBLE"
                    and len(refs) == 1
                    and refs[0] not in excluded_set
                ):
                    required.append(refs[0])
                else:
                    unmet.append(
                        {
                            "input_ref": token_text,
                            "candidate_refs": refs,
                            "generation_status": seed_match.get(
                                "generation_status"
                            ),
                            "reasons": list(seed_match.get("block_reasons", [])),
                        }
                    )
            elif candidate_match is not None:
                seed_match = candidate_seed.get(token_text)
                if (
                    seed_match is not None
                    and seed_match.get("generation_status") == "ELIGIBLE"
                    and token_text not in excluded_set
                ):
                    required.append(token_text)
                else:
                    alternatives = (
                        list(seed_match.get("candidate_refs", []))
                        if seed_match is not None
                        else [token_text]
                    )
                    reasons = (
                        list(seed_match.get("block_reasons", []))
                        if seed_match is not None
                        else ["candidate_not_linked_to_eligible_seed"]
                    )
                    unmet.append(
                        {
                            "input_ref": token_text,
                            "candidate_refs": alternatives,
                            "generation_status": (
                                seed_match.get("generation_status")
                                if seed_match is not None
                                else "BLOCKED_NOT_ELIGIBLE"
                            ),
                            "reasons": reasons,
                        }
                    )
            else:
                raise _RuntimeIssue(
                    "COARSE_PLANNER_REFERENCE_INVALID",
                    "/planning/constraints/must_visit/value",
                    "existingSeedOrCandidate",
                )
    if len(set(required)) != len(required):
        raise _RuntimeIssue(
            "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
            "/planning/constraints/must_visit/value",
            "uniqueResolvedCandidates",
        )
    unselected = [
        ref
        for ref in eligible_refs
        if ref not in required and ref not in excluded_set
    ]
    excluded_order = [
        ref for ref in candidate_order if ref in excluded_set
    ]
    return _Admission(
        candidate_by_id=candidate_by_id,
        candidate_result_by_id=candidate_result_by_id,
        seed_results=tuple(seed_results),
        eligible_refs=tuple(eligible_refs),
        required_refs=tuple(required),
        unselected_refs=tuple(unselected),
        excluded_refs=tuple(excluded_order),
        blocked_seeds=tuple(blocked),
        unmet_must=tuple(unmet),
    )


def _latest_created_at(documents: Sequence[Mapping[str, object]]) -> str:
    values: list[tuple[datetime, str]] = []
    for document in documents:
        raw = document.get("created_at")
        if not isinstance(raw, str):
            raise _RuntimeIssue(
                "COARSE_PLANNER_INPUT_INVALID",
                "/created_at",
                "date-time",
            )
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as error:
            raise _RuntimeIssue(
                "COARSE_PLANNER_INPUT_INVALID",
                "/created_at",
                "date-time",
            ) from error
        values.append((parsed, raw))
    return max(values, key=lambda item: item[0])[1]


def _condition(
    condition_id: str,
    description: str,
    *,
    constraint_refs: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "condition_id": condition_id,
        "description": description,
        "constraint_refs": list(constraint_refs),
        "evidence_fact_refs": [],
    }


def _build_outputs(
    inputs: _InputSet,
    profile: _ConstraintProfile,
    admission: _Admission,
) -> tuple[
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
    Mapping[str, object],
]:
    input_identity = "|".join(
        f"{name}:{inputs.hashes[name]}" for name in sorted(inputs.hashes)
    )
    run_id = stable_identifier(
        "run",
        "trip-decider:wu4:coarse-planner",
        input_identity,
    )
    request = inputs.planning["request.yaml"]
    constraints = inputs.planning["constraints.yaml"]
    candidates = inputs.recovery["candidates.json"]
    evidence = inputs.evidence["evidence.json"]
    created_at = _latest_created_at(
        (request, constraints, candidates, evidence)
    )
    time_constraint_id = str(profile.time_constraint["constraint_id"])
    must_constraint_id = (
        str(profile.must_constraint["constraint_id"])
        if profile.must_constraint is not None
        else None
    )
    excluded_constraint_id = (
        str(profile.excluded_constraint["constraint_id"])
        if profile.excluded_constraint is not None
        else None
    )
    required_count = len(admission.required_refs)
    draft_created = (
        required_count > 0 and len(profile.dates) >= required_count
    )
    planning_status = (
        "conditionally_feasible" if draft_created else "no_plan_found"
    )
    if required_count == 0:
        no_plan_reason: str | None = "NO_REQUIRED_ELIGIBLE_CANDIDATE"
    elif len(profile.dates) < required_count:
        no_plan_reason = (
            "INSUFFICIENT_DAY_CAPACITY_FOR_ONE_PER_DAY_ALLOCATOR"
        )
    else:
        no_plan_reason = None

    conditions: list[dict[str, object]] = []
    if draft_created:
        conditions.extend(
            (
                _condition(
                    "condition_route_evidence_unavailable",
                    "Route evidence is unavailable; no route is asserted.",
                ),
                _condition(
                    "condition_opening_hours_evidence_unavailable",
                    "Opening-hours evidence is unavailable.",
                ),
                _condition(
                    "condition_activity_duration_unavailable",
                    "Activity duration evidence is unavailable.",
                ),
                _condition(
                    "condition_specific_activity_times_unscheduled",
                    "Activities are assigned to dates without specific times.",
                    constraint_refs=(time_constraint_id,),
                ),
            )
        )
        if admission.blocked_seeds or admission.unmet_must:
            conditions.append(
                _condition(
                    "condition_candidate_admission_blockers_remain",
                    (
                        "Identity or evidence blockers remain; exact details "
                        "are retained in the planning gate."
                    ),
                    constraint_refs=(
                        (must_constraint_id,)
                        if must_constraint_id is not None
                        and admission.unmet_must
                        else ()
                    ),
                )
            )

    days: list[dict[str, object]] = []
    scheduled_refs: list[str] = []
    if draft_created:
        for index, day_date in enumerate(profile.dates):
            activities: list[dict[str, object]] = []
            if index < required_count:
                candidate_ref = admission.required_refs[index]
                scheduled_refs.append(candidate_ref)
                constraint_refs = [time_constraint_id]
                if must_constraint_id is not None:
                    constraint_refs.append(must_constraint_id)
                activities.append(
                    {
                        "activity_id": stable_identifier(
                            "activity",
                            "trip-decider:wu4:activity",
                            f"{run_id}|{day_date}|{candidate_ref}",
                        ),
                        "candidate_ref": candidate_ref,
                        "timing_status": "day_assigned_unscheduled",
                        "constraint_refs": constraint_refs,
                        "evidence_fact_refs": list(
                            admission.candidate_result_by_id[
                                candidate_ref
                            ]["fact_refs"]
                        ),
                    }
                )
            days.append(
                {
                    "day_id": stable_identifier(
                        "day",
                        "trip-decider:wu4:day",
                        f"{run_id}|{day_date}",
                    ),
                    "date": day_date,
                    "activities": activities,
                    "legs": [],
                }
            )

    excluded_candidates = []
    for candidate_ref in admission.excluded_refs:
        result = admission.candidate_result_by_id.get(candidate_ref)
        excluded_candidates.append(
            {
                "candidate_ref": candidate_ref,
                "reason": "Excluded by an explicit normalized constraint.",
                "constraint_refs": (
                    [excluded_constraint_id]
                    if excluded_constraint_id is not None
                    else []
                ),
                "evidence_fact_refs": (
                    list(result["fact_refs"]) if result is not None else []
                ),
            }
        )

    evaluation_results: dict[str, str] = {
        "time_window": (
            "conditional" if draft_created else "not_evaluated"
        ),
        "excluded": "satisfied",
    }
    if profile.must_constraint is not None:
        if not draft_created:
            evaluation_results["must_visit"] = "unsatisfied"
        elif admission.unmet_must:
            evaluation_results["must_visit"] = "conditional"
        else:
            evaluation_results["must_visit"] = "satisfied"
    constraint_evaluations = [
        {
            "constraint_ref": item["constraint_id"],
            "result": evaluation_results[str(item["category"])],
        }
        for item in profile.enabled_constraints
    ]

    plan_id = stable_identifier(
        "plan",
        "trip-decider:wu4:plan",
        input_identity,
    )
    plan_payload = {
        "plan_id": plan_id,
        "request_ref": _logical_ref(request),
        "constraint_set_ref": _logical_ref(constraints),
        "candidate_set_ref": _logical_ref(candidates),
        "evidence_set_ref": _logical_ref(evidence),
        "plan_status": planning_status,
        "conditions": conditions,
        "base_selections": [],
        "days": days,
        "excluded_candidates": excluded_candidates,
        "constraint_evaluations": constraint_evaluations,
        "objective_breakdown": {"components": []},
        "proof_refs": [],
    }
    plan_payload_hash = canonical_payload_sha256(plan_payload)
    plan = {
        "schema_version": "0.1.0",
        "artifact_id": stable_artifact_id("plan", plan_payload_hash),
        "artifact_type": "plan",
        "created_at": created_at,
        "producer": {
            "name": "trip-decider-coarse-planner",
            "version": "0.1.0",
            "run_id": run_id,
        },
        "provenance": {
            "parent_artifact_ids": [
                request["artifact_id"],
                constraints["artifact_id"],
                candidates["artifact_id"],
                evidence["artifact_id"],
            ],
            "input_hashes": [
                {"name": name, "sha256": inputs.hashes[name]}
                for name in sorted(inputs.hashes)
            ],
            "pipeline_stage": "wu4-conditional-coarse-planning",
        },
        "integrity": {
            "payload_sha256": plan_payload_hash,
            "canonicalization": "canonical-json-v1",
        },
        "payload": plan_payload,
    }

    violation_items: list[dict[str, object]] = []
    if not draft_created:
        refs = [time_constraint_id]
        if must_constraint_id is not None:
            refs.append(must_constraint_id)
        violation_items.append(
            {
                "violation_id": stable_identifier(
                    "violation",
                    "trip-decider:wu4:capacity",
                    f"{run_id}|{no_plan_reason}",
                ),
                "kind": "conditional",
                "message": (
                    "The one-candidate-per-day coarse allocator found no "
                    "plan under the explicit day capacity; this does not "
                    "prove infeasibility."
                ),
                "constraint_refs": refs,
                "evidence_fact_refs": [],
                "proof_refs": [],
            }
        )
    violations_payload = {
        "evaluation_stage": "post_plan",
        "plan_status": planning_status,
        "plan_ref": _logical_ref(plan),
        "violations": violation_items,
        "conditions": copy.deepcopy(conditions),
        "candidate_conflict_sets": [],
        "proofs": [],
    }
    violations_payload_hash = canonical_payload_sha256(violations_payload)
    violations = {
        "schema_version": "0.1.0",
        "artifact_id": stable_artifact_id(
            "violations",
            violations_payload_hash,
        ),
        "artifact_type": "violations",
        "created_at": created_at,
        "producer": {
            "name": "trip-decider-coarse-planner",
            "version": "0.1.0",
            "run_id": run_id,
        },
        "provenance": {
            "parent_artifact_ids": [plan["artifact_id"]],
            "input_hashes": [
                {"name": name, "sha256": inputs.hashes[name]}
                for name in sorted(inputs.hashes)
            ],
            "pipeline_stage": "wu4-conditional-coarse-planning",
        },
        "integrity": {
            "payload_sha256": violations_payload_hash,
            "canonicalization": "canonical-json-v1",
        },
        "payload": violations_payload,
    }

    unsatisfied_conditions: list[dict[str, object]] = []
    if draft_created:
        unsatisfied_conditions.extend(
            {
                "code": str(item["condition_id"]).removeprefix(
                    "condition_"
                ).upper(),
                "constraint_refs": list(item["constraint_refs"]),
                "evidence_fact_refs": [],
                "input_ref": None,
                "candidate_refs": [],
                "reasons": ["required_evidence_unavailable"],
            }
            for item in conditions
            if item["condition_id"]
            != "condition_candidate_admission_blockers_remain"
        )
    if no_plan_reason is not None:
        unsatisfied_conditions.append(
            {
                "code": no_plan_reason,
                "constraint_refs": [
                    item["constraint_id"]
                    for item in profile.enabled_constraints
                    if item["category"] in {"time_window", "must_visit"}
                ],
                "evidence_fact_refs": [],
                "input_ref": None,
                "candidate_refs": list(admission.required_refs),
                "reasons": ["coarse_allocator_no_plan"],
            }
        )
    for item in admission.unmet_must:
        unsatisfied_conditions.append(
            {
                "code": "MUST_VISIT_TARGET_NOT_ADMISSIBLE",
                "constraint_refs": (
                    [must_constraint_id]
                    if must_constraint_id is not None
                    else []
                ),
                "evidence_fact_refs": [],
                "input_ref": item["input_ref"],
                "candidate_refs": list(item["candidate_refs"]),
                "reasons": list(item["reasons"]),
            }
        )
    gate = {
        "schema_version": "wu4-coarse-planning-gate/1.0",
        "run_id": run_id,
        "draft_created": draft_created,
        "publishable": False,
        "planning_status": planning_status,
        "generation_allowed_input": inputs.evidence[
            "evidence-gate.json"
        ]["generation_allowed"],
        "eligible_candidate_refs": list(admission.eligible_refs),
        "scheduled_candidate_refs": scheduled_refs,
        "unscheduled_eligible_candidate_refs": (
            [] if draft_created else list(admission.required_refs)
        ),
        "unselected_eligible_candidate_refs": list(
            admission.unselected_refs
        ),
        "excluded_candidate_refs": list(admission.excluded_refs),
        "blocked_seeds": [
            copy.deepcopy(dict(item)) for item in admission.blocked_seeds
        ],
        "unsatisfied_conditions": unsatisfied_conditions,
        "no_plan_reason": no_plan_reason,
    }

    plan_bytes = _json_bytes(plan)
    violations_bytes = _json_bytes(violations)
    gate_bytes = _json_bytes(gate)
    output_hashes = {
        "plan.json": _sha256(plan_bytes),
        "violations.json": _sha256(violations_bytes),
        "planning-gate.json": _sha256(gate_bytes),
    }
    run_summary = {
        "schema_version": "wu4-coarse-planner-run/1.0",
        "run_id": run_id,
        "input_artifacts": {
            name: {
                "artifact_id": document["artifact_id"],
                "payload_sha256": document["integrity"]["payload_sha256"],
            }
            for name, document in (
                ("request", request),
                ("constraints", constraints),
                ("candidates", candidates),
                ("evidence", evidence),
            )
        },
        "input_file_sha256": dict(inputs.hashes),
        "day_count": len(profile.dates),
        "eligible_candidate_count": len(admission.eligible_refs),
        "required_candidate_count": required_count,
        "scheduled_candidate_count": len(scheduled_refs),
        "blocked_seed_count": len(admission.blocked_seeds),
        "output_paths": {
            "plan_path": "plan.json",
            "violations_path": "violations.json",
            "planning_gate_path": "planning-gate.json",
            "run_summary_path": "run-summary.json",
        },
        "output_artifacts": {
            "plan_artifact_id": plan["artifact_id"],
            "violations_artifact_id": violations["artifact_id"],
        },
        "output_sha256": output_hashes,
        "network_attempts": 0,
        "llm_calls": 0,
        "completion_status": "completed",
    }
    return plan, violations, gate, run_summary


def _validate_prepared_outputs(
    inputs: _InputSet,
    registry,
    staging_root: Path,
) -> None:
    plan_loaded = load_document(
        staging_root / "plan.json",
        expected_artifact_type="plan",
    )
    violations_loaded = load_document(
        staging_root / "violations.json",
        expected_artifact_type="violations",
    )
    if (
        plan_loaded.problems
        or violations_loaded.problems
        or plan_loaded.value is None
        or violations_loaded.value is None
    ):
        raise _RuntimeIssue(
            "COARSE_PLANNER_INTERNAL_ERROR",
            "/outputs",
            "loadPreparedArtifacts",
        )
    upstream = (
        inputs.formal["planning/request.yaml"],
        inputs.formal["planning/constraint-parse.json"],
        inputs.formal["planning/constraints.yaml"],
        inputs.formal["recovery/candidates.json"],
        inputs.formal["evidence/evidence.json"],
    )
    plan_data = plan_loaded.value.data
    violations_data = violations_loaded.value.data
    if not isinstance(plan_data, Mapping) or not isinstance(
        violations_data, Mapping
    ):
        raise _RuntimeIssue(
            "COARSE_PLANNER_INTERNAL_ERROR",
            "/outputs",
            "object",
        )
    plan_bundle = validate_bundle(
        (*upstream, plan_loaded.value),
        registry,
        closure=BundleClosure.CLOSED,
        root_artifact_id=str(plan_data["artifact_id"]),
    )
    if plan_bundle.problems:
        problem = plan_bundle.problems[0]
        raise _RuntimeIssue(
            "COARSE_PLANNER_INTERNAL_ERROR",
            problem.json_pointer,
            problem.schema_rule,
            expected="CLOSED plan bundle",
            artifact_path="plan.json",
        )
    violations_bundle = validate_bundle(
        (*upstream, plan_loaded.value, violations_loaded.value),
        registry,
        closure=BundleClosure.CLOSED,
        root_artifact_id=str(violations_data["artifact_id"]),
    )
    if violations_bundle.problems:
        problem = violations_bundle.problems[0]
        raise _RuntimeIssue(
            "COARSE_PLANNER_INTERNAL_ERROR",
            problem.json_pointer,
            problem.schema_rule,
            expected="CLOSED violations bundle",
            artifact_path="violations.json",
        )


def _output_root_problem(output_root: Path) -> _RuntimeIssue | None:
    if output_root.exists():
        if output_root.is_symlink() or not output_root.is_dir():
            return _RuntimeIssue(
                "COARSE_PLANNER_OUTPUT_ROOT_INVALID",
                "/output_root",
                "directory",
                expected="missing or empty regular directory",
            )
        try:
            if any(output_root.iterdir()):
                return _RuntimeIssue(
                    "COARSE_PLANNER_OUTPUT_ROOT_INVALID",
                    "/output_root",
                    "emptyDirectory",
                    expected="missing or empty regular directory",
                )
        except OSError:
            return _RuntimeIssue(
                "COARSE_PLANNER_OUTPUT_ROOT_INVALID",
                "/output_root",
                "readableDirectory",
            )
    parent = output_root.parent
    if (
        parent.is_symlink()
        or not parent.is_dir()
    ):
        return _RuntimeIssue(
            "COARSE_PLANNER_OUTPUT_ROOT_INVALID",
            "/output_root",
            "existingParent",
            expected="existing regular parent directory",
        )
    return None


def _install_outputs(
    output_root: Path,
    staging_root: Path,
    expected: Mapping[str, bytes],
) -> tuple[ValidationProblem, ...]:
    existed = output_root.exists()
    installed: list[Path] = []
    try:
        if not existed:
            output_root.mkdir()
        for filename in _OUTPUT_FILENAMES:
            target = output_root / filename
            os.replace(staging_root / filename, target)
            installed.append(target)
        for filename, prepared_bytes in expected.items():
            target = output_root / filename
            if target.read_bytes() != prepared_bytes:
                raise _RuntimeIssue(
                    "COARSE_PLANNER_OUTPUT_HASH_MISMATCH",
                    f"/outputs/{filename}",
                    "installedBytes",
                    artifact_path=filename,
                )
    except _RuntimeIssue as issue:
        for path in reversed(installed):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        if not existed:
            try:
                output_root.rmdir()
            except OSError:
                pass
        return _failure(issue).problems
    except OSError:
        for path in reversed(installed):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        if not existed:
            try:
                output_root.rmdir()
            except OSError:
                pass
        return (
            _problem(
                "COARSE_PLANNER_OUTPUT_ROOT_INVALID",
                "/output_root",
                "atomicInstall",
                expected="all four outputs installed atomically",
            ),
        )
    return ()


def run_coarse_planner(
    recovery_root: Path,
    evidence_root: Path,
    planning_input_root: Path,
    output_root: Path,
) -> ValidationResult[CoarsePlannerSummary]:
    """Create a non-publishable coarse plan from explicit structured inputs."""

    try:
        checked_recovery_root = Path(recovery_root)
        checked_evidence_root = Path(evidence_root)
        checked_planning_root = Path(planning_input_root)
        checked_output_root = Path(output_root)
    except TypeError:
        return _failure(
            _RuntimeIssue(
                "COARSE_PLANNER_INPUT_INVALID",
                "/paths",
                "pathType",
                expected="Path-compatible values",
            )
        )
    output_problem = _output_root_problem(checked_output_root)
    if output_problem is not None:
        return _failure(output_problem)
    try:
        registry = _validate_registry()
        inputs = _load_inputs(
            checked_recovery_root,
            checked_evidence_root,
            checked_planning_root,
            registry,
        )
        profile = _constraint_profile(inputs)
        admission = _admission(inputs, profile)
        plan, violations, gate, run_summary = _build_outputs(
            inputs,
            profile,
            admission,
        )
        output_values = {
            "plan.json": plan,
            "violations.json": violations,
            "planning-gate.json": gate,
            "run-summary.json": run_summary,
        }
        output_bytes = {
            name: _json_bytes(value)
            for name, value in output_values.items()
        }
        with tempfile.TemporaryDirectory(
            prefix="trip-decider-wu4-cp-"
        ) as staging:
            staging_root = Path(staging)
            for filename in _OUTPUT_FILENAMES:
                (staging_root / filename).write_bytes(
                    output_bytes[filename]
                )
            _validate_prepared_outputs(inputs, registry, staging_root)
            install_problems = _install_outputs(
                checked_output_root,
                staging_root,
                output_bytes,
            )
        if install_problems:
            return ValidationResult(None, install_problems)
    except _RuntimeIssue as issue:
        return _failure(issue)

    return ValidationResult(
        CoarsePlannerSummary(
            run_id=str(run_summary["run_id"]),
            plan_path=checked_output_root / "plan.json",
            violations_path=checked_output_root / "violations.json",
            planning_gate_path=checked_output_root / "planning-gate.json",
            run_summary_path=checked_output_root / "run-summary.json",
            planning_status=str(gate["planning_status"]),
            draft_created=bool(gate["draft_created"]),
            day_count=int(run_summary["day_count"]),
            eligible_candidate_count=int(
                run_summary["eligible_candidate_count"]
            ),
            required_candidate_count=int(
                run_summary["required_candidate_count"]
            ),
            scheduled_candidate_count=int(
                run_summary["scheduled_candidate_count"]
            ),
            blocked_seed_count=int(run_summary["blocked_seed_count"]),
            network_attempts=0,
            llm_calls=0,
            output_sha256=dict(run_summary["output_sha256"]),
        ),
        (),
    )
