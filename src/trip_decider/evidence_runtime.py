"""Candidate-local Evidence Runtime interface.

WU3-ER consumes only the four committed WU2R-DOR outputs.  It does not
acquire data, resolve identity ambiguity, rank candidates, or establish
route or itinerary feasibility.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from trip_decider.adapters.contracts import (
    safe_type,
    stable_artifact_id,
    stable_identifier,
)
from trip_decider.schema_validation import (
    LoadedDocument,
    ValidationProblem,
    ValidationResult,
    canonical_payload_sha256,
    load_document,
    validate_artifact,
    validate_schema_registry,
)


REQUIRED_EVIDENCE_SLOTS = (
    "provider_identity",
    "provider_category",
    "location",
    "source_reference",
)

EVIDENCE_RUNTIME_PROBLEM_CODES = frozenset(
    {
        "EVIDENCE_RUNTIME_INPUT_INVALID",
        "EVIDENCE_RUNTIME_NETWORK_ATTEMPTED",
        "EVIDENCE_RUNTIME_OUTPUT_HASH_MISMATCH",
        "EVIDENCE_RUNTIME_OUTPUT_ROOT_INVALID",
        "EVIDENCE_RUNTIME_REFERENCE_INVALID",
    }
)

_INPUT_FILENAMES = (
    "candidates.json",
    "seed-accounting.json",
    "record-local-facts.json",
    "run-summary.json",
)
_OUTPUT_FILENAMES = (
    "evidence.json",
    "evidence-gate.json",
    "run-summary.json",
)
_LOCATOR_KINDS = frozenset(
    {
        "observation_location",
        "pipeline_record",
        "provider_item",
        "response_location",
        "search_result",
        "user_input",
        "web_location",
    }
)
_SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas"
_MESSAGES = {
    "EVIDENCE_RUNTIME_INPUT_INVALID": (
        "Evidence Runtime input is not a complete WU2R-DOR output."
    ),
    "EVIDENCE_RUNTIME_NETWORK_ATTEMPTED": (
        "Evidence Runtime must not attempt network access."
    ),
    "EVIDENCE_RUNTIME_OUTPUT_HASH_MISMATCH": (
        "Installed Evidence Runtime bytes do not match prepared bytes."
    ),
    "EVIDENCE_RUNTIME_OUTPUT_ROOT_INVALID": (
        "Evidence Runtime output root must be missing or empty."
    ),
    "EVIDENCE_RUNTIME_REFERENCE_INVALID": (
        "Evidence Runtime candidate or source reference is invalid."
    ),
}


class _RuntimeIssue(ValueError):
    def __init__(
        self,
        code: str,
        pointer: str,
        rule: str,
        *,
        artifact_path: str = "",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.pointer = pointer
        self.rule = rule
        self.artifact_path = artifact_path


@dataclass(frozen=True)
class _PreparedInput:
    documents: Mapping[str, Mapping[str, object]]
    input_sha256: Mapping[str, str]
    candidate_document: LoadedDocument


@dataclass(frozen=True)
class _PreparedRuntime:
    evidence: Mapping[str, object]
    gate: Mapping[str, object]
    run_summary: Mapping[str, object]
    run_id: str
    candidate_results: tuple[CandidateEvidenceResult, ...]
    seed_results: tuple[SeedEvidenceResult, ...]


@dataclass(frozen=True)
class CandidateEvidenceResult:
    """Deterministic completeness result for one provider-backed candidate."""

    candidate_ref: str
    evidence_complete: bool
    required_slots: tuple[str, ...]
    satisfied_slots: tuple[str, ...]
    missing_slots: tuple[str, ...]
    fact_refs: tuple[str, ...]
    support_ceiling: str
    hard_conflict: bool


@dataclass(frozen=True)
class SeedEvidenceResult:
    """Identity plus evidence gate result for one original seed."""

    seed: str
    identity_status: str
    candidate_refs: tuple[str, ...]
    generation_status: str
    block_reasons: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceRuntimeSummary:
    """Auditable paths and counts for one offline Evidence Runtime run."""

    run_id: str
    evidence_path: Path
    evidence_gate_path: Path
    run_summary_path: Path
    candidate_count: int
    complete_candidate_count: int
    incomplete_candidate_count: int
    eligible_seed_count: int
    blocked_seed_count: int
    generation_allowed: bool
    network_attempts: int
    output_sha256: Mapping[str, str]


def _problem(
    code: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual: object = None,
    artifact_path: str = "",
) -> ValidationProblem:
    if code not in EVIDENCE_RUNTIME_PROBLEM_CODES:
        raise ValueError("unknown Evidence Runtime problem code")
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
    code: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual: object = None,
    artifact_path: str = "",
) -> ValidationResult[EvidenceRuntimeSummary]:
    return ValidationResult(
        None,
        (
            _problem(
                code,
                pointer,
                rule,
                expected=expected,
                actual=actual,
                artifact_path=artifact_path,
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
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _mapping(
    value: object,
    pointer: str,
    *,
    keys: set[str] | None = None,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_INPUT_INVALID",
            pointer,
            "type",
        )
    if keys is not None and set(value) != keys:
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_INPUT_INVALID",
            pointer,
            "exactKeys",
        )
    return value


def _sequence(value: object, pointer: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_INPUT_INVALID",
            pointer,
            "type",
        )
    return value


def _locator(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"kind", "value"}
        and value.get("kind") in _LOCATOR_KINDS
        and isinstance(value.get("value"), str)
        and bool(value.get("value"))
    )


def _locator_sequence(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_locator(item) for item in value)
    )


def _coordinate_location(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    latitude = value.get("latitude")
    longitude = value.get("longitude")
    return (
        value.get("kind") == "coordinates"
        and value.get("crs") in {"WGS84", "GCJ-02", "BD-09"}
        and isinstance(latitude, (int, float))
        and not isinstance(latitude, bool)
        and math.isfinite(float(latitude))
        and -90 <= float(latitude) <= 90
        and isinstance(longitude, (int, float))
        and not isinstance(longitude, bool)
        and math.isfinite(float(longitude))
        and -180 <= float(longitude) <= 180
        and _locator_sequence(value.get("source_refs"))
    )


def _load_inputs(recovery_root: Path) -> _PreparedInput | tuple[
    ValidationProblem, ...
]:
    if (
        not recovery_root.is_dir()
        or recovery_root.is_symlink()
    ):
        return (
            _problem(
                "EVIDENCE_RUNTIME_INPUT_INVALID",
                "/recovery_root",
                "directory",
                expected="regular DOR output directory",
                artifact_path=str(recovery_root),
            ),
        )
    try:
        entries = tuple(recovery_root.iterdir())
    except OSError:
        return (
            _problem(
                "EVIDENCE_RUNTIME_INPUT_INVALID",
                "/recovery_root",
                "readableDirectory",
                expected="readable DOR output directory",
                artifact_path=str(recovery_root),
            ),
        )
    if {item.name for item in entries} != set(_INPUT_FILENAMES):
        return (
            _problem(
                "EVIDENCE_RUNTIME_INPUT_INVALID",
                "/recovery_root",
                "exactFiles",
                expected="four exact WU2R-DOR outputs",
                artifact_path=str(recovery_root),
            ),
        )

    documents: dict[str, Mapping[str, object]] = {}
    hashes: dict[str, str] = {}
    candidate_document: LoadedDocument | None = None
    for filename in _INPUT_FILENAMES:
        path = recovery_root / filename
        if path.is_symlink() or not path.is_file():
            return (
                _problem(
                    "EVIDENCE_RUNTIME_INPUT_INVALID",
                    f"/documents/{filename}",
                    "regularFile",
                    expected="regular file",
                    artifact_path=str(path),
                ),
            )
        loaded = load_document(
            path,
            expected_artifact_type=(
                "candidates" if filename == "candidates.json" else None
            ),
        )
        if loaded.problems:
            return loaded.problems
        if loaded.value is None or not isinstance(loaded.value.data, Mapping):
            return (
                _problem(
                    "EVIDENCE_RUNTIME_INPUT_INVALID",
                    f"/documents/{filename}",
                    "object",
                    expected="JSON object",
                    artifact_path=str(path),
                ),
            )
        documents[filename] = loaded.value.data
        hashes[filename] = _sha256(path.read_bytes())
        if filename == "candidates.json":
            candidate_document = loaded.value
    if candidate_document is None:
        raise RuntimeError("candidate document was not loaded")
    return _PreparedInput(
        documents=documents,
        input_sha256=hashes,
        candidate_document=candidate_document,
    )


def _validate_candidate(
    prepared: _PreparedInput,
) -> tuple[ValidationProblem, ...]:
    schema_paths = tuple(sorted(_SCHEMA_ROOT.glob("*.schema.json")))
    registry = validate_schema_registry(schema_paths)
    if registry.problems:
        return registry.problems
    if registry.value is None:
        raise RuntimeError("validated schema registry has no value")
    validated = validate_artifact(prepared.candidate_document, registry.value)
    return validated.problems


def _validate_recovery_summary(
    prepared: _PreparedInput,
    candidate_count: int,
) -> Mapping[str, object]:
    summary = _mapping(
        prepared.documents["run-summary.json"],
        "/run_summary",
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
    if (
        summary.get("schema_version")
        != "wu2r-downstream-recovery-run/1.0"
        or not isinstance(summary.get("run_id"), str)
        or not summary.get("run_id")
        or summary.get("candidate_count") != candidate_count
        or summary.get("network_attempts") != 0
        or summary.get("completion_status") != "completed"
    ):
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_INPUT_INVALID",
            "/run_summary",
            "completedRecoveryRun",
        )
    paths = _mapping(
        summary.get("output_paths"),
        "/run_summary/output_paths",
    )
    if paths != {
        "candidate_artifact_path": "candidates.json",
        "seed_accounting_path": "seed-accounting.json",
        "record_local_facts_path": "record-local-facts.json",
        "run_summary_path": "run-summary.json",
    }:
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_INPUT_INVALID",
            "/run_summary/output_paths",
            "exactOutputPaths",
        )
    declared = _mapping(
        summary.get("output_sha256"),
        "/run_summary/output_sha256",
    )
    expected_hashes = {
        filename: prepared.input_sha256[filename]
        for filename in _INPUT_FILENAMES
        if filename != "run-summary.json"
    }
    if declared != expected_hashes:
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_INPUT_INVALID",
            "/run_summary/output_sha256",
            "actualBytes",
        )
    _mapping(
        summary.get("input_fixture_identity"),
        "/run_summary/input_fixture_identity",
    )
    return summary


def _candidate_items(
    candidate_artifact: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    payload = _mapping(candidate_artifact.get("payload"), "/candidate/payload")
    values = _sequence(
        payload.get("candidates"),
        "/candidate/payload/candidates",
    )
    candidates: list[Mapping[str, object]] = []
    for index, value in enumerate(values):
        candidates.append(
            _mapping(
                value,
                f"/candidate/payload/candidates/{index}",
            )
        )
    return tuple(candidates)


def _record_facts(
    prepared: _PreparedInput,
    recovery_run_id: str,
    candidate_ids: set[str],
) -> Mapping[str, Mapping[str, object]]:
    document = _mapping(
        prepared.documents["record-local-facts.json"],
        "/record_local_facts",
        keys={"schema_version", "run_id", "record_local_facts"},
    )
    if (
        document.get("schema_version")
        != "wu2r-downstream-record-local-facts/1.0"
        or document.get("run_id") != recovery_run_id
    ):
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_INPUT_INVALID",
            "/record_local_facts",
            "recoveryRunIdentity",
        )
    values = _sequence(
        document.get("record_local_facts"),
        "/record_local_facts/record_local_facts",
    )
    by_candidate: dict[str, Mapping[str, object]] = {}
    expected_keys = {
        "candidate_id",
        "provider_name",
        "provider_record_type",
        "provider_record_id",
        "categories",
        "location",
        "source_refs",
    }
    for index, value in enumerate(values):
        fact = _mapping(
            value,
            f"/record_local_facts/record_local_facts/{index}",
            keys=expected_keys,
        )
        candidate_id = fact.get("candidate_id")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or candidate_id in by_candidate
        ):
            raise _RuntimeIssue(
                "EVIDENCE_RUNTIME_REFERENCE_INVALID",
                f"/record_local_facts/record_local_facts/{index}/candidate_id",
                "uniqueCandidateReference",
            )
        by_candidate[candidate_id] = fact
    if set(by_candidate) != candidate_ids:
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_REFERENCE_INVALID",
            "/record_local_facts/record_local_facts",
            "candidateBijection",
        )
    return by_candidate


def _fact(
    candidate_id: str,
    field: str,
    value: object,
) -> dict[str, object]:
    fact_id = stable_identifier(
        "fact",
        "trip-decider:wu3:evidence-fact",
        f"{candidate_id}|{field}",
    )
    copied = copy.deepcopy(value)
    return {
        "fact_id": fact_id,
        "subject": {
            "subject_type": "entity",
            "entity_kind": "candidate",
            "entity_id": candidate_id,
        },
        "field": field,
        "value": copied,
        "unit": None,
        "support_status": "unknown",
        "derivation": "rule_derived",
        "freshness": {
            "retrieved_at": None,
            "effective_at": None,
            "expires_at": None,
            "status": "unknown",
        },
        "sources": [],
        "normalization": {
            "original_value": copy.deepcopy(value),
            "normalized_value": copy.deepcopy(value),
            "rule_id": "candidate-local-copy-v1",
        },
        "display_status": "unknown",
        "display_rule": "unknown-without-structured-source-v1",
        "conflict_source_refs": [],
        "derivation_detail": {"input_fact_ids": []},
    }


def _candidate_values(
    candidate: Mapping[str, object],
) -> Mapping[str, object]:
    provider = candidate.get("provider")
    provider_mapping = provider if isinstance(provider, Mapping) else {}
    categories = provider_mapping.get("categories")
    location = candidate.get("location")
    source_refs = candidate.get("source_refs")
    return {
        "provider_identity": {
            "name": provider_mapping.get("name"),
            "record_type": provider_mapping.get("record_type"),
            "record_id": provider_mapping.get("record_id"),
        },
        "provider_category": (
            copy.deepcopy(categories) if isinstance(categories, list) else []
        ),
        "location": (
            copy.deepcopy(dict(location))
            if isinstance(location, Mapping)
            else {}
        ),
        "source_reference": (
            copy.deepcopy(source_refs)
            if isinstance(source_refs, list)
            else []
        ),
    }


def _satisfied_slots(
    candidate: Mapping[str, object],
    local_fact: Mapping[str, object],
) -> tuple[str, ...]:
    satisfied: list[str] = []
    provider = candidate.get("provider")
    provider_mapping = provider if isinstance(provider, Mapping) else {}
    identity_ok = (
        isinstance(provider_mapping.get("name"), str)
        and bool(provider_mapping.get("name"))
        and isinstance(provider_mapping.get("record_type"), str)
        and bool(provider_mapping.get("record_type"))
        and isinstance(provider_mapping.get("record_id"), str)
        and bool(provider_mapping.get("record_id"))
        and local_fact.get("provider_name") == provider_mapping.get("name")
        and local_fact.get("provider_record_type")
        == provider_mapping.get("record_type")
        and local_fact.get("provider_record_id")
        == provider_mapping.get("record_id")
    )
    if identity_ok:
        satisfied.append("provider_identity")

    categories = provider_mapping.get("categories")
    if (
        isinstance(categories, list)
        and bool(categories)
        and local_fact.get("categories") == categories
    ):
        satisfied.append("provider_category")

    location = candidate.get("location")
    if (
        _coordinate_location(location)
        and local_fact.get("location") == location
    ):
        satisfied.append("location")

    source_refs = candidate.get("source_refs")
    if (
        _locator_sequence(source_refs)
        and isinstance(location, Mapping)
        and _locator_sequence(location.get("source_refs"))
        and local_fact.get("source_refs") == source_refs
    ):
        satisfied.append("source_reference")
    return tuple(satisfied)


def _candidate_evidence(
    candidate_artifact: Mapping[str, object],
    local_facts: Mapping[str, Mapping[str, object]],
) -> tuple[
    tuple[CandidateEvidenceResult, ...],
    tuple[dict[str, object], ...],
]:
    candidates = _candidate_items(candidate_artifact)
    candidate_ids = [item.get("candidate_id") for item in candidates]
    if (
        any(not isinstance(item, str) or not item for item in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
    ):
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_REFERENCE_INVALID",
            "/candidate/payload/candidates",
            "uniqueCandidateDefinition",
        )

    results: list[CandidateEvidenceResult] = []
    facts: list[dict[str, object]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: str(item["candidate_id"]),
    ):
        candidate_id = str(candidate["candidate_id"])
        values = _candidate_values(candidate)
        candidate_facts = [
            _fact(candidate_id, field, values[field])
            for field in REQUIRED_EVIDENCE_SLOTS
        ]
        satisfied = _satisfied_slots(candidate, local_facts[candidate_id])
        missing = tuple(
            slot
            for slot in REQUIRED_EVIDENCE_SLOTS
            if slot not in satisfied
        )
        results.append(
            CandidateEvidenceResult(
                candidate_ref=candidate_id,
                evidence_complete=not missing,
                required_slots=REQUIRED_EVIDENCE_SLOTS,
                satisfied_slots=satisfied,
                missing_slots=missing,
                fact_refs=tuple(
                    str(item["fact_id"]) for item in candidate_facts
                ),
                support_ceiling="unknown",
                hard_conflict=False,
            )
        )
        facts.extend(candidate_facts)
    return tuple(results), tuple(facts)


def _seed_gate(
    prepared: _PreparedInput,
    recovery_run_id: str,
    candidate_by_id: Mapping[str, Mapping[str, object]],
    candidate_results: Sequence[CandidateEvidenceResult],
) -> tuple[SeedEvidenceResult, ...]:
    document = _mapping(
        prepared.documents["seed-accounting.json"],
        "/seed_accounting",
        keys={"schema_version", "run_id", "seed_matches"},
    )
    if (
        document.get("schema_version")
        != "wu2r-downstream-seed-accounting/1.0"
        or document.get("run_id") != recovery_run_id
    ):
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_INPUT_INVALID",
            "/seed_accounting",
            "recoveryRunIdentity",
        )
    values = _sequence(
        document.get("seed_matches"),
        "/seed_accounting/seed_matches",
    )
    result_by_candidate = {
        item.candidate_ref: item for item in candidate_results
    }
    seen_seeds: set[str] = set()
    results: list[SeedEvidenceResult] = []
    status_counts = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    for index, value in enumerate(values):
        item = _mapping(
            value,
            f"/seed_accounting/seed_matches/{index}",
            keys={"seed", "status", "candidate_refs"},
        )
        seed = item.get("seed")
        status = item.get("status")
        refs_value = _sequence(
            item.get("candidate_refs"),
            f"/seed_accounting/seed_matches/{index}/candidate_refs",
        )
        refs = tuple(refs_value)
        if (
            not isinstance(seed, str)
            or not seed
            or seed in seen_seeds
            or status not in status_counts
            or any(not isinstance(ref, str) or not ref for ref in refs)
            or len(set(refs)) != len(refs)
        ):
            raise _RuntimeIssue(
                "EVIDENCE_RUNTIME_REFERENCE_INVALID",
                f"/seed_accounting/seed_matches/{index}",
                "identityAccounting",
            )
        seen_seeds.add(seed)
        status_counts[str(status)] += 1
        if (
            (status == "matched" and len(refs) != 1)
            or (status == "ambiguous" and len(refs) < 2)
            or (status == "unmatched" and refs)
            or any(ref not in candidate_by_id for ref in refs)
            or any(candidate_by_id[ref].get("label") != seed for ref in refs)
        ):
            raise _RuntimeIssue(
                "EVIDENCE_RUNTIME_REFERENCE_INVALID",
                f"/seed_accounting/seed_matches/{index}/candidate_refs",
                "identityAccounting",
            )

        if status == "ambiguous":
            generation_status = "BLOCKED_IDENTITY_AMBIGUOUS"
            reasons = ("identity_ambiguous",)
        elif status == "unmatched":
            generation_status = "BLOCKED_IDENTITY_UNMATCHED"
            reasons = ("identity_unmatched",)
        else:
            candidate_result = result_by_candidate[str(refs[0])]
            if not candidate_result.evidence_complete:
                generation_status = "BLOCKED_EVIDENCE_INCOMPLETE"
                reasons = ("evidence_incomplete",)
            elif candidate_result.hard_conflict:
                generation_status = "BLOCKED_EVIDENCE_INCOMPLETE"
                reasons = ("hard_evidence_conflict",)
            else:
                generation_status = "ELIGIBLE"
                reasons = ()
        results.append(
            SeedEvidenceResult(
                seed=seed,
                identity_status=str(status),
                candidate_refs=tuple(str(ref) for ref in refs),
                generation_status=generation_status,
                block_reasons=reasons,
            )
        )

    summary = _mapping(
        prepared.documents["run-summary.json"].get("seed_status_counts"),
        "/run_summary/seed_status_counts",
    )
    if summary != status_counts:
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_INPUT_INVALID",
            "/run_summary/seed_status_counts",
            "actualSeedCounts",
        )
    if not results:
        raise _RuntimeIssue(
            "EVIDENCE_RUNTIME_INPUT_INVALID",
            "/seed_accounting/seed_matches",
            "minItems",
        )
    return tuple(results)


def _candidate_result_document(
    value: CandidateEvidenceResult,
) -> dict[str, object]:
    return {
        "candidate_ref": value.candidate_ref,
        "evidence_complete": value.evidence_complete,
        "required_slots": list(value.required_slots),
        "satisfied_slots": list(value.satisfied_slots),
        "missing_slots": list(value.missing_slots),
        "fact_refs": list(value.fact_refs),
        "support_ceiling": value.support_ceiling,
        "hard_conflict": value.hard_conflict,
    }


def _seed_result_document(value: SeedEvidenceResult) -> dict[str, object]:
    return {
        "seed": value.seed,
        "identity_status": value.identity_status,
        "candidate_refs": list(value.candidate_refs),
        "generation_status": value.generation_status,
        "block_reasons": list(value.block_reasons),
    }


def _prepare_runtime(prepared: _PreparedInput) -> _PreparedRuntime:
    candidate_artifact = prepared.documents["candidates.json"]
    candidates = _candidate_items(candidate_artifact)
    candidate_by_id = {
        str(item["candidate_id"]): item for item in candidates
    }
    recovery_summary = _validate_recovery_summary(
        prepared,
        len(candidates),
    )
    recovery_run_id = str(recovery_summary["run_id"])
    local_facts = _record_facts(
        prepared,
        recovery_run_id,
        set(candidate_by_id),
    )
    candidate_results, facts = _candidate_evidence(
        candidate_artifact,
        local_facts,
    )
    seed_results = _seed_gate(
        prepared,
        recovery_run_id,
        candidate_by_id,
        candidate_results,
    )

    identity = "|".join(
        f"{name}:{prepared.input_sha256[name]}"
        for name in _INPUT_FILENAMES
    )
    run_id = stable_identifier(
        "run",
        "trip-decider:wu3:evidence-runtime",
        f"{recovery_run_id}|{identity}",
    )
    candidate_artifact_id = str(candidate_artifact["artifact_id"])
    evidence_set_id = stable_identifier(
        "evidence_set",
        "trip-decider:wu3:evidence-set",
        f"{candidate_artifact_id}|{identity}",
    )
    evidence_payload = {
        "evidence_set_id": evidence_set_id,
        "facts": list(facts),
        "mapping_rule_version": "candidate-local-evidence-v1",
    }
    evidence_payload_hash = canonical_payload_sha256(evidence_payload)
    evidence = {
        "schema_version": "0.1.0",
        "artifact_id": stable_artifact_id(
            "evidence",
            evidence_payload_hash,
        ),
        "artifact_type": "evidence",
        "created_at": candidate_artifact["created_at"],
        "producer": {
            "name": "trip-decider-evidence-runtime",
            "version": "0.1.0",
            "run_id": run_id,
        },
        "provenance": {
            "parent_artifact_ids": [candidate_artifact_id],
            "input_hashes": [
                {
                    "name": f"wu2r-dor-{name}",
                    "sha256": prepared.input_sha256[name],
                }
                for name in _INPUT_FILENAMES
            ],
            "pipeline_stage": "wu3-candidate-local-evidence",
        },
        "integrity": {
            "payload_sha256": evidence_payload_hash,
            "canonicalization": "canonical-json-v1",
        },
        "payload": evidence_payload,
    }
    generation_allowed = all(
        item.generation_status == "ELIGIBLE" for item in seed_results
    )
    gate = {
        "schema_version": "wu3-evidence-gate/1.0",
        "run_id": run_id,
        "candidate_results": [
            _candidate_result_document(item) for item in candidate_results
        ],
        "seed_results": [
            _seed_result_document(item) for item in seed_results
        ],
        "generation_allowed": generation_allowed,
    }
    evidence_bytes = _json_bytes(evidence)
    gate_bytes = _json_bytes(gate)
    complete_count = sum(
        item.evidence_complete for item in candidate_results
    )
    eligible_count = sum(
        item.generation_status == "ELIGIBLE" for item in seed_results
    )
    run_summary = {
        "schema_version": "wu3-evidence-runtime-run/1.0",
        "run_id": run_id,
        "input_recovery_identity": {
            "schema_version": recovery_summary["schema_version"],
            "run_id": recovery_run_id,
            "completion_status": recovery_summary["completion_status"],
            "candidate_artifact_id": candidate_artifact_id,
            "candidate_payload_sha256": candidate_artifact["integrity"][
                "payload_sha256"
            ],
            "input_fixture_identity": copy.deepcopy(
                recovery_summary["input_fixture_identity"]
            ),
            "input_file_sha256": dict(prepared.input_sha256),
            "declared_output_sha256": copy.deepcopy(
                recovery_summary["output_sha256"]
            ),
        },
        "evidence_artifact_id": evidence["artifact_id"],
        "evidence_payload_sha256": evidence_payload_hash,
        "candidate_count": len(candidate_results),
        "complete_candidate_count": complete_count,
        "incomplete_candidate_count": (
            len(candidate_results) - complete_count
        ),
        "eligible_seed_count": eligible_count,
        "blocked_seed_count": len(seed_results) - eligible_count,
        "generation_allowed": generation_allowed,
        "network_attempts": 0,
        "output_sha256": {
            "evidence.json": _sha256(evidence_bytes),
            "evidence-gate.json": _sha256(gate_bytes),
        },
        "completion_status": "completed",
    }
    return _PreparedRuntime(
        evidence=evidence,
        gate=gate,
        run_summary=run_summary,
        run_id=run_id,
        candidate_results=candidate_results,
        seed_results=seed_results,
    )


def _validate_evidence(
    evidence: Mapping[str, object],
    candidate_ids: set[str],
    output_path: Path,
) -> tuple[ValidationProblem, ...]:
    registry = validate_schema_registry(
        tuple(sorted(_SCHEMA_ROOT.glob("*.schema.json")))
    )
    if registry.problems:
        return registry.problems
    if registry.value is None:
        raise RuntimeError("validated schema registry has no value")
    loaded = LoadedDocument(path=output_path, data=evidence)
    validated = validate_artifact(loaded, registry.value)
    if validated.problems:
        return validated.problems
    payload = _mapping(evidence.get("payload"), "/evidence/payload")
    facts = _sequence(payload.get("facts"), "/evidence/payload/facts")
    for index, value in enumerate(facts):
        fact = _mapping(value, f"/evidence/payload/facts/{index}")
        subject = _mapping(
            fact.get("subject"),
            f"/evidence/payload/facts/{index}/subject",
        )
        if subject.get("entity_id") not in candidate_ids:
            return (
                _problem(
                    "EVIDENCE_RUNTIME_REFERENCE_INVALID",
                    f"/payload/facts/{index}/subject/entity_id",
                    "currentCandidate",
                    expected="candidate in current artifact",
                    artifact_path=str(output_path),
                ),
            )
        if (
            fact.get("support_status") != "unknown"
            or fact.get("derivation") != "rule_derived"
            or fact.get("sources") != []
            or fact.get("display_status") != "unknown"
            or fact.get("conflict_source_refs") != []
        ):
            return (
                _problem(
                    "EVIDENCE_RUNTIME_INPUT_INVALID",
                    f"/payload/facts/{index}",
                    "candidateLocalUnknown",
                    expected="unknown candidate-local fact",
                    artifact_path=str(output_path),
                ),
            )
    return ()


def _rollback_outputs(
    output_root: Path,
    temp_paths: Sequence[Path],
    final_paths: Sequence[Path],
    created_root: bool,
) -> None:
    first_error: OSError | None = None
    for path in tuple(temp_paths) + tuple(reversed(final_paths)):
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            if first_error is None:
                first_error = error
    if created_root:
        try:
            output_root.rmdir()
        except FileNotFoundError:
            pass
        except OSError as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error


def _install_outputs(
    output_root: Path,
    outputs: Sequence[tuple[str, bytes]],
) -> tuple[ValidationProblem, ...]:
    created_root = False
    temp_paths: list[Path] = []
    final_paths: list[Path] = []
    try:
        if not output_root.exists():
            output_root.mkdir()
            created_root = True
        for filename, content in outputs:
            final_path = output_root / filename
            temp_path = (
                output_root / f".{filename}.{uuid.uuid4().hex}.tmp"
            )
            temp_paths.append(temp_path)
            with temp_path.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if final_path.exists() or final_path.is_symlink():
                raise OSError("output path is occupied")
            os.replace(temp_path, final_path)
            temp_paths.remove(temp_path)
            final_paths.append(final_path)
            if final_path.read_bytes() != content:
                raise _RuntimeIssue(
                    "EVIDENCE_RUNTIME_OUTPUT_HASH_MISMATCH",
                    f"/outputs/{filename}",
                    "installedBytes",
                    artifact_path=str(final_path),
                )
    except _RuntimeIssue:
        _rollback_outputs(
            output_root,
            temp_paths,
            final_paths,
            created_root,
        )
        raise
    except OSError:
        _rollback_outputs(
            output_root,
            temp_paths,
            final_paths,
            created_root,
        )
        return (
            _problem(
                "EVIDENCE_RUNTIME_OUTPUT_ROOT_INVALID",
                "/output_root",
                "atomicInstall",
                expected="exclusive writable output root",
                artifact_path=str(output_root),
            ),
        )
    return ()


def run_evidence_runtime(
    recovery_root: Path,
    output_root: Path,
) -> ValidationResult[EvidenceRuntimeSummary]:
    """Create candidate-local unknown evidence from strict DOR outputs."""

    try:
        checked_recovery_root = Path(recovery_root)
        checked_output_root = Path(output_root)
    except TypeError:
        return _failure(
            "EVIDENCE_RUNTIME_INPUT_INVALID",
            "/paths",
            "pathType",
            expected="Path-compatible values",
        )

    if checked_output_root.exists():
        if (
            checked_output_root.is_symlink()
            or not checked_output_root.is_dir()
        ):
            return _failure(
                "EVIDENCE_RUNTIME_OUTPUT_ROOT_INVALID",
                "/output_root",
                "emptyDirectory",
                expected="missing or empty directory",
                artifact_path=str(checked_output_root),
            )
        try:
            if next(checked_output_root.iterdir(), None) is not None:
                return _failure(
                    "EVIDENCE_RUNTIME_OUTPUT_ROOT_INVALID",
                    "/output_root",
                    "emptyDirectory",
                    expected="missing or empty directory",
                    artifact_path=str(checked_output_root),
                )
        except OSError:
            return _failure(
                "EVIDENCE_RUNTIME_OUTPUT_ROOT_INVALID",
                "/output_root",
                "readableDirectory",
                expected="readable empty directory",
                artifact_path=str(checked_output_root),
            )
    elif (
        not checked_output_root.parent.is_dir()
        or checked_output_root.parent.is_symlink()
    ):
        return _failure(
            "EVIDENCE_RUNTIME_OUTPUT_ROOT_INVALID",
            "/output_root",
            "parentDirectory",
            expected="existing regular parent directory",
            artifact_path=str(checked_output_root),
        )

    loaded = _load_inputs(checked_recovery_root)
    if isinstance(loaded, tuple):
        return ValidationResult(None, loaded)
    prepared_input = loaded
    candidate_problems = _validate_candidate(prepared_input)
    if candidate_problems:
        return ValidationResult(None, candidate_problems)

    try:
        prepared_runtime = _prepare_runtime(prepared_input)
    except _RuntimeIssue as issue:
        return _failure(
            issue.code,
            issue.pointer,
            issue.rule,
            artifact_path=issue.artifact_path,
        )

    candidate_ids = {
        item.candidate_ref
        for item in prepared_runtime.candidate_results
    }
    evidence_problems = _validate_evidence(
        prepared_runtime.evidence,
        candidate_ids,
        checked_output_root / "evidence.json",
    )
    if evidence_problems:
        return ValidationResult(None, evidence_problems)

    evidence_bytes = _json_bytes(prepared_runtime.evidence)
    gate_bytes = _json_bytes(prepared_runtime.gate)
    summary_bytes = _json_bytes(prepared_runtime.run_summary)
    outputs = (
        ("evidence.json", evidence_bytes),
        ("evidence-gate.json", gate_bytes),
        ("run-summary.json", summary_bytes),
    )
    try:
        install_problems = _install_outputs(
            checked_output_root,
            outputs,
        )
    except _RuntimeIssue as issue:
        return _failure(
            issue.code,
            issue.pointer,
            issue.rule,
            artifact_path=issue.artifact_path,
        )
    if install_problems:
        return ValidationResult(None, install_problems)

    for filename, expected_bytes in outputs:
        try:
            installed = (checked_output_root / filename).read_bytes()
        except OSError:
            installed = b""
        if installed != expected_bytes:
            _rollback_outputs(
                checked_output_root,
                (),
                [
                    checked_output_root / name
                    for name in _OUTPUT_FILENAMES
                ],
                False,
            )
            return _failure(
                "EVIDENCE_RUNTIME_OUTPUT_HASH_MISMATCH",
                f"/outputs/{filename}",
                "installedBytes",
                expected="prepared output bytes",
                artifact_path=str(checked_output_root / filename),
            )

    complete_count = sum(
        item.evidence_complete
        for item in prepared_runtime.candidate_results
    )
    eligible_count = sum(
        item.generation_status == "ELIGIBLE"
        for item in prepared_runtime.seed_results
    )
    output_hashes = {
        filename: _sha256(content)
        for filename, content in outputs
    }
    return ValidationResult(
        EvidenceRuntimeSummary(
            run_id=prepared_runtime.run_id,
            evidence_path=checked_output_root / "evidence.json",
            evidence_gate_path=(
                checked_output_root / "evidence-gate.json"
            ),
            run_summary_path=checked_output_root / "run-summary.json",
            candidate_count=len(prepared_runtime.candidate_results),
            complete_candidate_count=complete_count,
            incomplete_candidate_count=(
                len(prepared_runtime.candidate_results) - complete_count
            ),
            eligible_seed_count=eligible_count,
            blocked_seed_count=(
                len(prepared_runtime.seed_results) - eligible_count
            ),
            generation_allowed=all(
                item.generation_status == "ELIGIBLE"
                for item in prepared_runtime.seed_results
            ),
            network_attempts=0,
            output_sha256=output_hashes,
        ),
        (),
    )


__all__ = [
    "CandidateEvidenceResult",
    "EVIDENCE_RUNTIME_PROBLEM_CODES",
    "EvidenceRuntimeSummary",
    "REQUIRED_EVIDENCE_SLOTS",
    "SeedEvidenceResult",
    "run_evidence_runtime",
]
