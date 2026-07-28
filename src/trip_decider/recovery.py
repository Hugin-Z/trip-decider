"""WU2 Recovery multi-identity ingestion interfaces.

This module owns deterministic seed accounting, candidate-local source views,
route endpoint guarding, and offline replay orchestration.  It does not own a
network client, provider adapter, identity resolver, evidence runtime,
planner, or route acquisition.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from trip_decider.adapters.contracts import IngestionContext, safe_type
from trip_decider.adapters.open_data_poi import normalize_open_data_pois
from trip_decider.schema_validation import (
    ValidationProblem,
    ValidationResult,
    canonical_payload_sha256,
)


_RECOVERY_MESSAGES = {
    "RECOVERY_SEED_INPUT_INVALID": "Recovery seed input is invalid.",
    "RECOVERY_CANDIDATE_ARTIFACT_INVALID": (
        "Recovery candidate artifact is inconsistent."
    ),
    "RECOVERY_ROUTE_ENDPOINT_UNRESOLVED": (
        "Route endpoint does not have one resolved candidate."
    ),
    "RECOVERY_REPLAY_INVALID": "Recovery replay control is invalid.",
    "RECOVERY_REPLAY_HASH_MISMATCH": "Recovery replay hash does not match.",
    "RECOVERY_NETWORK_ATTEMPTED": "Recovery replay attempted network access.",
}

_ANCHOR_FILENAMES = frozenset(
    {"README.md", "case.json", "replay.json", "osm-pois.json"}
)
_OUTPUT_FILENAMES = (
    "candidates.json",
    "seed-accounting.json",
    "record-local-facts.json",
    "run-summary.json",
)
_SOURCE_DOCUMENT_SHA256 = (
    "b34ed5eb0fa570a11e0b43e9f0a714c30f4a44fc53ee3d5d38302074b1de9ca1"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_QUERY_BLOCK_PATTERN = re.compile(
    r"Exact UTF-8 query:\n\n```text\n(.*?)```",
    flags=re.DOTALL,
)


class _ControlError(ValueError):
    """Expected fixture/control violation without unsafe exception text."""


class _CandidateControlError(ValueError):
    """Independent Candidate bytes or integrity contradict the control."""


class _InstalledBytesMismatch(RuntimeError):
    """Installed bytes differ from the deterministic bytes prepared in memory."""

    def __init__(self, filename: str):
        super().__init__("installed output bytes differ")
        self.filename = filename


@dataclass(frozen=True)
class _PreparedReplay:
    case: Mapping[str, object]
    replay: Mapping[str, object]
    expected_candidate: Mapping[str, object]
    response_bytes: bytes
    query_bytes: bytes
    request_bytes: bytes
    case_sha256: str
    replay_sha256: str
    response_sha256: str


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


def _problem(
    code: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual: object = None,
    artifact_path: str = "",
) -> ValidationProblem:
    if code not in _RECOVERY_MESSAGES:
        raise ValueError("unknown WU2 Recovery problem code")
    return ValidationProblem(
        error_code=code,
        artifact_path=artifact_path,
        json_pointer=pointer,
        schema_rule=rule,
        expected=expected,
        actual_type=safe_type(actual),
        message=_RECOVERY_MESSAGES[code],
    )


def _failure(
    code: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual: object = None,
    artifact_path: str = "",
):
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


def _candidate_sequence(
    artifact: object,
) -> list[Mapping[str, object]] | None:
    if not isinstance(artifact, Mapping):
        return None
    payload = artifact.get("payload")
    if not isinstance(payload, Mapping):
        return None
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return None
    if not all(isinstance(item, Mapping) for item in candidates):
        return None
    return candidates


def _coordinate_candidate(candidate: Mapping[str, object]) -> bool:
    provider = candidate.get("provider")
    location = candidate.get("location")
    if not isinstance(provider, Mapping) or not isinstance(location, Mapping):
        return False
    latitude = location.get("latitude")
    longitude = location.get("longitude")
    return (
        location.get("kind") == "coordinates"
        and location.get("crs") in {"WGS84", "GCJ-02", "BD-09"}
        and isinstance(latitude, (int, float))
        and not isinstance(latitude, bool)
        and math.isfinite(float(latitude))
        and -90 <= float(latitude) <= 90
        and isinstance(longitude, (int, float))
        and not isinstance(longitude, bool)
        and math.isfinite(float(longitude))
        and -180 <= float(longitude) <= 180
    )


def ingest_candidate_pool(
    snapshot: Mapping[str, object],
    seeds: Sequence[str],
    context: IngestionContext,
) -> ValidationResult[RecoveryCandidateResult]:
    """Normalize all provider identities and account for every exact seed."""

    if isinstance(seeds, (str, bytes)) or not isinstance(seeds, Sequence):
        return _failure(
            "RECOVERY_SEED_INPUT_INVALID",
            "/seeds",
            "type",
            expected="array",
            actual=seeds,
        )

    checked_seeds: list[str] = []
    seen_seeds: set[str] = set()
    for index, seed in enumerate(seeds):
        if not isinstance(seed, str) or not seed:
            return _failure(
                "RECOVERY_SEED_INPUT_INVALID",
                f"/seeds/{index}",
                "seed",
                expected="non-empty string",
                actual=seed,
            )
        if seed in seen_seeds:
            return _failure(
                "RECOVERY_SEED_INPUT_INVALID",
                f"/seeds/{index}",
                "uniqueSeed",
                expected="unique seed",
                actual=seed,
            )
        seen_seeds.add(seed)
        checked_seeds.append(seed)

    normalized = normalize_open_data_pois(snapshot, context)
    if normalized.problems:
        return ValidationResult(None, normalized.problems)

    artifact = normalized.value
    candidates = _candidate_sequence(artifact)
    if candidates is None:
        return _failure(
            "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
            "/payload/candidates",
            "candidateArtifact",
            expected="candidate array",
            actual=artifact,
        )

    by_label: dict[str, list[str]] = {}
    record_local_facts: list[RecordLocalFact] = []
    seen_candidate_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        candidate_id = candidate.get("candidate_id")
        label = candidate.get("label")
        provider = candidate.get("provider")
        location = candidate.get("location")
        source_refs = candidate.get("source_refs")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or candidate_id in seen_candidate_ids
            or not isinstance(label, str)
            or not label
            or not isinstance(provider, Mapping)
            or not isinstance(location, Mapping)
            or not isinstance(source_refs, list)
            or not all(isinstance(item, Mapping) for item in source_refs)
        ):
            return _failure(
                "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
                f"/payload/candidates/{index}",
                "candidateRecord",
                expected="complete unique candidate",
                actual=candidate,
            )
        seen_candidate_ids.add(candidate_id)

        provider_name = provider.get("name")
        record_type = provider.get("record_type")
        record_id = provider.get("record_id")
        categories = provider.get("categories")
        if (
            not isinstance(provider_name, str)
            or not provider_name
            or not isinstance(record_type, str)
            or not record_type
            or not isinstance(record_id, str)
            or not record_id
            or not isinstance(categories, list)
            or not categories
            or not all(isinstance(item, Mapping) for item in categories)
        ):
            return _failure(
                "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
                f"/payload/candidates/{index}/provider",
                "providerIdentity",
                expected="complete provider identity",
                actual=provider,
            )

        category_values: list[tuple[str, str | None]] = []
        for category_index, category in enumerate(categories):
            code = category.get("code")
            category_label = category.get("label")
            if (
                not isinstance(code, str)
                or not code
                or (
                    category_label is not None
                    and (
                        not isinstance(category_label, str)
                        or not category_label
                    )
                )
            ):
                return _failure(
                    "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
                    (
                        f"/payload/candidates/{index}/provider/categories/"
                        f"{category_index}"
                    ),
                    "providerCategory",
                    expected="provider category",
                    actual=category,
                )
            category_values.append((code, category_label))

        by_label.setdefault(label, []).append(candidate_id)
        record_local_facts.append(
            RecordLocalFact(
                candidate_id=candidate_id,
                provider_name=provider_name,
                provider_record_type=record_type,
                provider_record_id=record_id,
                categories=tuple(category_values),
                location=copy.deepcopy(dict(location)),
                source_refs=tuple(
                    copy.deepcopy(dict(item)) for item in source_refs
                ),
            )
        )

    seed_matches: list[SeedMatch] = []
    for seed in checked_seeds:
        candidate_refs = tuple(sorted(by_label.get(seed, ())))
        if len(candidate_refs) == 0:
            status = "unmatched"
        elif len(candidate_refs) == 1:
            status = "matched"
        else:
            status = "ambiguous"
        seed_matches.append(
            SeedMatch(
                seed=seed,
                status=status,
                candidate_refs=candidate_refs,
            )
        )

    record_local_facts.sort(key=lambda item: item.candidate_id)
    return ValidationResult(
        RecoveryCandidateResult(
            candidate_artifact=artifact,
            seed_matches=tuple(seed_matches),
            record_local_facts=tuple(record_local_facts),
        ),
        (),
    )


def prepare_route_endpoints(
    candidate_result: RecoveryCandidateResult,
    from_seed: str,
    to_seed: str,
) -> ValidationResult[RouteEndpointPair]:
    """Return stable refs only when both seed identities are uniquely matched."""

    candidates = _candidate_sequence(candidate_result.candidate_artifact)
    if candidates is None:
        return _failure(
            "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
            "/candidate_artifact/payload/candidates",
            "candidateArtifact",
            expected="candidate array",
            actual=candidate_result.candidate_artifact,
        )

    candidate_by_id: dict[str, Mapping[str, object]] = {}
    for index, candidate in enumerate(candidates):
        candidate_id = candidate.get("candidate_id")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or candidate_id in candidate_by_id
        ):
            return _failure(
                "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
                f"/candidate_artifact/payload/candidates/{index}/candidate_id",
                "uniqueCandidateId",
                expected="unique candidate ID",
                actual=candidate_id,
            )
        candidate_by_id[candidate_id] = candidate

    matches: dict[str, SeedMatch] = {}
    for index, match in enumerate(candidate_result.seed_matches):
        if (
            not isinstance(match, SeedMatch)
            or not match.seed
            or match.seed in matches
            or match.status not in {"matched", "unmatched", "ambiguous"}
        ):
            return _failure(
                "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
                f"/seed_matches/{index}",
                "seedAccounting",
                expected="unique seed accounting",
                actual=match,
            )
        matches[match.seed] = match

    def resolve(seed: object, pointer: str) -> ValidationResult[str]:
        if not isinstance(seed, str) or not seed:
            return _failure(
                "RECOVERY_ROUTE_ENDPOINT_UNRESOLVED",
                pointer,
                "matchedCandidate",
                expected="matched seed",
                actual=seed,
            )
        match = matches.get(seed)
        if (
            match is None
            or match.status != "matched"
            or len(match.candidate_refs) != 1
        ):
            return _failure(
                "RECOVERY_ROUTE_ENDPOINT_UNRESOLVED",
                pointer,
                "matchedCandidate",
                expected="one candidate reference",
                actual=(None if match is None else match.status),
            )
        candidate_ref = match.candidate_refs[0]
        candidate = candidate_by_id.get(candidate_ref)
        if candidate is None:
            return _failure(
                "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
                f"{pointer}/candidate_refs/0",
                "candidateReference",
                expected="current candidate reference",
                actual=candidate_ref,
            )
        if candidate.get("label") != seed:
            return _failure(
                "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
                f"{pointer}/candidate_refs/0",
                "candidateLabel",
                expected="exact seed label",
                actual=candidate.get("label"),
            )
        if not _coordinate_candidate(candidate):
            return _failure(
                "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
                f"{pointer}/candidate_refs/0",
                "candidateCoordinates",
                expected="provider-backed coordinates",
                actual=candidate.get("location"),
            )
        return ValidationResult(candidate_ref, ())

    from_result = resolve(from_seed, "/from_seed")
    if from_result.problems:
        return ValidationResult(None, from_result.problems)
    to_result = resolve(to_seed, "/to_seed")
    if to_result.problems:
        return ValidationResult(None, to_result.problems)

    return ValidationResult(
        RouteEndpointPair(
            from_candidate_ref=from_result.value,
            to_candidate_ref=to_result.value,
        ),
        (),
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and _SHA256_PATTERN.fullmatch(value) is not None
    )


def _strict_json_bytes(raw: bytes) -> object:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _ControlError("UTF-8 BOM is not allowed")

    def unique_object(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise _ControlError("duplicate object key")
            value[key] = item
        return value

    def reject_constant(_: str) -> object:
        raise _ControlError("non-finite number")

    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _ControlError("invalid strict UTF-8 JSON") from error


def _read_control(path: Path) -> tuple[Mapping[str, object], bytes]:
    if path.is_symlink() or not path.is_file():
        raise _ControlError("control must be a regular file")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise _ControlError("control cannot be read") from error
    value = _strict_json_bytes(raw)
    if not isinstance(value, Mapping):
        raise _ControlError("control root must be an object")
    return value, raw


def _exact_keys(value: object, expected: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise _ControlError("control object keys do not match")
    return value


def _nonempty_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _ControlError("required string is missing")
    return value


def _sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise _ControlError("required array is missing")
    return value


def _immediate_child_name(value: object) -> str:
    name = _nonempty_string(value)
    path = Path(name)
    if (
        path.is_absolute()
        or path.name != name
        or "/" in name
        or "\\" in name
        or name in {".", ".."}
    ):
        raise _ControlError("path is not one safe immediate child")
    return name


def _prepare_replay(replay_root: Path) -> _PreparedReplay:
    if replay_root.is_symlink() or not replay_root.is_dir():
        raise _ControlError("replay root must be a regular directory")
    try:
        children = list(replay_root.iterdir())
    except OSError as error:
        raise _ControlError("replay root cannot be read") from error
    if (
        len(children) != len(_ANCHOR_FILENAMES)
        or {item.name for item in children} != _ANCHOR_FILENAMES
        or any(item.is_symlink() or not item.is_file() for item in children)
    ):
        raise _ControlError("replay root does not contain the exact anchor")

    case, case_bytes = _read_control(replay_root / "case.json")
    replay, replay_bytes = _read_control(replay_root / "replay.json")
    _exact_keys(
        case,
        {
            "behavior_expected",
            "bundle_closure",
            "case_id",
            "case_version",
            "coverage",
            "dirty_cases",
            "documents",
            "fixture_type",
            "non_coverage",
            "root_artifact_id",
            "source",
        },
    )
    if (
        case.get("bundle_closure") != "closed"
        or case.get("fixture_type") != "real_anchor"
    ):
        raise _ControlError("fixture closure or type is invalid")
    _nonempty_string(case.get("case_id"))
    _nonempty_string(case.get("case_version"))
    root_artifact_id = _nonempty_string(case.get("root_artifact_id"))
    if not isinstance(case.get("behavior_expected"), Mapping):
        raise _ControlError("fixture expected behavior is invalid")
    for name in ("coverage", "dirty_cases", "non_coverage"):
        _sequence(case.get(name))
    _exact_keys(
        case.get("source"),
        {"data_policy", "description", "kind", "origin_url"},
    )

    embedded: dict[str, Mapping[str, object]] = {}
    documents = _sequence(case.get("documents"))
    for item in documents:
        document = _exact_keys(
            item,
            {
                "content_utf8",
                "expected_schema_id",
                "file_sha256",
                "media_type",
                "relative_path",
            },
        )
        relative_path = _immediate_child_name(document.get("relative_path"))
        if relative_path in embedded:
            raise _ControlError("embedded document path is duplicated")
        if document.get("media_type") != "application/json":
            raise _ControlError("embedded document media type is invalid")
        _nonempty_string(document.get("expected_schema_id"))
        declared_file_hash = document.get("file_sha256")
        if not _valid_sha256(declared_file_hash):
            raise _ControlError("embedded document hash is invalid")
        content = _nonempty_string(document.get("content_utf8"))
        content_bytes = content.encode("utf-8")
        if _sha256(content_bytes) != str(declared_file_hash).lower():
            raise _ControlError("embedded document hash does not match")
        parsed = _strict_json_bytes(content_bytes)
        if not isinstance(parsed, Mapping):
            raise _ControlError("embedded document must be an object")
        embedded[relative_path] = parsed
    if set(embedded) != {"request.json", "candidates.json"}:
        raise _ControlError("embedded document set is invalid")

    request_document = embedded["request.json"]
    expected_candidate = embedded["candidates.json"]
    if (
        request_document.get("artifact_type") != "request"
        or expected_candidate.get("artifact_type") != "candidates"
        or expected_candidate.get("artifact_id") != root_artifact_id
    ):
        raise _CandidateControlError("embedded artifact identity is invalid")
    request_payload = request_document.get("payload")
    candidate_payload = expected_candidate.get("payload")
    request_integrity = request_document.get("integrity")
    candidate_integrity = expected_candidate.get("integrity")
    if (
        not isinstance(request_payload, Mapping)
        or not isinstance(candidate_payload, Mapping)
        or not isinstance(request_integrity, Mapping)
        or not isinstance(candidate_integrity, Mapping)
    ):
        raise _CandidateControlError("embedded artifact envelope is invalid")
    if (
        canonical_payload_sha256(request_payload)
        != request_integrity.get("payload_sha256")
        or canonical_payload_sha256(candidate_payload)
        != candidate_integrity.get("payload_sha256")
    ):
        raise _CandidateControlError("embedded payload integrity is invalid")

    _exact_keys(
        replay,
        {
            "artifact_context",
            "attempt_group_id",
            "coverage",
            "endpoint",
            "expected",
            "failure_evidence",
            "integration",
            "method",
            "network_required",
            "non_coverage",
            "query_sha256",
            "raw_response",
            "request_sha256",
            "response_bytes",
            "response_sha256",
            "retrieved_at",
            "run_id",
            "schema_version",
            "snapshot_metadata",
            "source_base_timestamp",
            "source_policy",
        },
    )
    if (
        replay.get("schema_version") != "wu2r-resume-replay/1.0"
        or replay.get("method") != "POST"
        or replay.get("network_required") is not False
    ):
        raise _ControlError("replay mode is invalid")
    for name in (
        "attempt_group_id",
        "endpoint",
        "retrieved_at",
        "run_id",
        "source_base_timestamp",
    ):
        _nonempty_string(replay.get(name))
    for name in ("coverage", "non_coverage"):
        _sequence(replay.get(name))
    integration = _exact_keys(replay.get("integration"), {"function", "module"})
    if integration != {
        "function": "replay_wu2r_resume_anchor",
        "module": "trip_decider.resume_acquisition",
    }:
        raise _ControlError("replay integration is invalid")

    for name in ("query_sha256", "request_sha256", "response_sha256"):
        if not _valid_sha256(replay.get(name)):
            raise _ControlError("replay hash is invalid")
    raw_control = _exact_keys(
        replay.get("raw_response"),
        {"bytes", "relative_path", "sha256"},
    )
    raw_name = _immediate_child_name(raw_control.get("relative_path"))
    if raw_name != "osm-pois.json" or not _valid_sha256(
        raw_control.get("sha256")
    ):
        raise _ControlError("raw response control is invalid")
    raw_path = replay_root / raw_name
    if raw_path.is_symlink() or not raw_path.is_file():
        raise _ControlError("raw response path is invalid")
    try:
        response_bytes = raw_path.read_bytes()
    except OSError as error:
        raise _ControlError("raw response cannot be read") from error
    response_hash = _sha256(response_bytes)
    response_size = replay.get("response_bytes")
    raw_size = raw_control.get("bytes")
    if (
        type(response_size) is not int
        or type(raw_size) is not int
        or response_size < 1
        or raw_size != response_size
        or len(response_bytes) != response_size
        or response_hash != str(raw_control.get("sha256")).lower()
        or response_hash != str(replay.get("response_sha256")).lower()
    ):
        raise _ControlError("raw response identity does not match")

    expected = _exact_keys(
        replay.get("expected"),
        {
            "candidate_artifact_id",
            "candidate_count",
            "candidate_payload_sha256",
            "provider_identities",
            "record_local_facts",
            "request_artifact_id",
            "request_payload_sha256",
            "seed_matches",
            "seed_status_counts",
        },
    )
    for name in (
        "candidate_artifact_id",
        "request_artifact_id",
    ):
        _nonempty_string(expected.get(name))
    for name in ("candidate_payload_sha256", "request_payload_sha256"):
        if not _valid_sha256(expected.get(name)):
            raise _ControlError("expected payload hash is invalid")
    candidate_count = expected.get("candidate_count")
    if type(candidate_count) is not int or candidate_count < 1:
        raise _ControlError("expected candidate count is invalid")
    provider_identities = _sequence(expected.get("provider_identities"))
    seed_matches = _sequence(expected.get("seed_matches"))
    facts = _sequence(expected.get("record_local_facts"))
    if len(provider_identities) != candidate_count or len(facts) != candidate_count:
        raise _ControlError("expected candidate views have invalid counts")
    for identity in provider_identities:
        checked = _exact_keys(identity, {"record_id", "record_type"})
        _nonempty_string(checked.get("record_id"))
        _nonempty_string(checked.get("record_type"))
    seen_seeds: set[str] = set()
    computed_counts = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    for match in seed_matches:
        checked = _exact_keys(match, {"candidate_refs", "seed", "status"})
        seed = _nonempty_string(checked.get("seed"))
        if seed in seen_seeds:
            raise _ControlError("expected seed is duplicated")
        seen_seeds.add(seed)
        status = checked.get("status")
        if status not in computed_counts:
            raise _ControlError("expected seed status is invalid")
        refs = _sequence(checked.get("candidate_refs"))
        if not all(isinstance(item, str) and item for item in refs):
            raise _ControlError("expected candidate reference is invalid")
        computed_counts[str(status)] += 1
    counts = _exact_keys(
        expected.get("seed_status_counts"),
        {"matched", "ambiguous", "unmatched"},
    )
    if counts != computed_counts:
        raise _ControlError("expected seed status counts do not match")
    for fact in facts:
        checked = _exact_keys(
            fact,
            {
                "candidate_id",
                "categories",
                "location",
                "provider_name",
                "provider_record_id",
                "provider_record_type",
                "source_refs",
            },
        )
        for name in (
            "candidate_id",
            "provider_name",
            "provider_record_id",
            "provider_record_type",
        ):
            _nonempty_string(checked.get(name))
        _sequence(checked.get("categories"))
        _exact_keys(
            checked.get("location"),
            {"crs", "kind", "latitude", "longitude", "source_refs"},
        )
        _sequence(checked.get("source_refs"))

    candidates = _candidate_sequence(expected_candidate)
    if candidates is None or len(candidates) != candidate_count:
        raise _CandidateControlError("embedded Candidate count is invalid")
    if (
        expected_candidate.get("artifact_id")
        != expected.get("candidate_artifact_id")
        or canonical_payload_sha256(candidate_payload)
        != str(expected.get("candidate_payload_sha256")).lower()
        or request_document.get("artifact_id")
        != expected.get("request_artifact_id")
        or canonical_payload_sha256(request_payload)
        != str(expected.get("request_payload_sha256")).lower()
    ):
        raise _CandidateControlError("independent artifact identity mismatches")
    candidate_identities: list[dict[str, str]] = []
    for candidate in candidates:
        provider = candidate.get("provider")
        if not isinstance(provider, Mapping):
            raise _CandidateControlError("candidate provider is invalid")
        record_type = provider.get("record_type")
        record_id = provider.get("record_id")
        if (
            not isinstance(record_type, str)
            or not record_type
            or not isinstance(record_id, str)
            or not record_id
        ):
            raise _CandidateControlError("candidate provider identity is invalid")
        candidate_identities.append(
            {"record_type": record_type, "record_id": record_id}
        )
    if candidate_identities != provider_identities:
        raise _CandidateControlError("provider identities do not match")

    snapshot = _exact_keys(
        replay.get("snapshot_metadata"),
        {
            "crs",
            "data_policy",
            "format_version",
            "operation",
            "provider",
            "request_fingerprint",
            "response_locator",
            "retrieved_at",
        },
    )
    for name in (
        "crs",
        "format_version",
        "operation",
        "provider",
        "retrieved_at",
    ):
        _nonempty_string(snapshot.get(name))
    if not _valid_sha256(snapshot.get("request_fingerprint")):
        raise _ControlError("snapshot request fingerprint is invalid")
    _exact_keys(snapshot.get("response_locator"), {"kind", "value"})
    if not isinstance(snapshot.get("data_policy"), Mapping):
        raise _ControlError("snapshot policy is invalid")

    context = _exact_keys(
        replay.get("artifact_context"),
        {
            "created_at",
            "producer_name",
            "producer_version",
            "request_ref",
            "run_id",
        },
    )
    for name in ("created_at", "producer_name", "producer_version", "run_id"):
        _nonempty_string(context.get(name))
    request_ref = _exact_keys(
        context.get("request_ref"),
        {"artifact_id", "artifact_type", "payload_sha256", "schema_version"},
    )
    if request_ref.get("artifact_type") != "request":
        raise _ControlError("request reference type is invalid")
    for name in ("artifact_id", "schema_version"):
        _nonempty_string(request_ref.get(name))
    if not _valid_sha256(request_ref.get("payload_sha256")):
        raise _ControlError("request reference hash is invalid")

    source_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "wu2-recovery-source-and-capture.md"
    )
    if source_path.is_symlink() or not source_path.is_file():
        raise _ControlError("frozen source document is unavailable")
    try:
        source_bytes = source_path.read_bytes()
    except OSError as error:
        raise _ControlError("frozen source document cannot be read") from error
    if (
        source_bytes.startswith(b"\xef\xbb\xbf")
        or _sha256(source_bytes) != _SOURCE_DOCUMENT_SHA256
    ):
        raise _ControlError("frozen source document identity is invalid")
    try:
        source_text = source_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _ControlError("frozen source document is not UTF-8") from error
    matches = _QUERY_BLOCK_PATTERN.findall(source_text)
    if len(matches) != 1:
        raise _ControlError("frozen query block is not unique")
    query_text = matches[0]
    query_bytes = query_text.encode("utf-8")
    request_bytes = urlencode(
        {"data": query_text},
        encoding="utf-8",
        errors="strict",
    ).encode("ascii")

    return _PreparedReplay(
        case=case,
        replay=replay,
        expected_candidate=expected_candidate,
        response_bytes=response_bytes,
        query_bytes=query_bytes,
        request_bytes=request_bytes,
        case_sha256=_sha256(case_bytes),
        replay_sha256=_sha256(replay_bytes),
        response_sha256=response_hash,
    )


def _seed_document(
    run_id: str,
    candidate_result: RecoveryCandidateResult,
) -> dict[str, object]:
    return {
        "schema_version": "wu2r-downstream-seed-accounting/1.0",
        "run_id": run_id,
        "seed_matches": [
            {
                "seed": item.seed,
                "status": item.status,
                "candidate_refs": list(item.candidate_refs),
            }
            for item in candidate_result.seed_matches
        ],
    }


def _facts_document(
    run_id: str,
    candidate_result: RecoveryCandidateResult,
) -> dict[str, object]:
    return {
        "schema_version": "wu2r-downstream-record-local-facts/1.0",
        "run_id": run_id,
        "record_local_facts": [
            {
                "candidate_id": item.candidate_id,
                "provider_name": item.provider_name,
                "provider_record_type": item.provider_record_type,
                "provider_record_id": item.provider_record_id,
                "categories": [
                    {"code": code, "label": label}
                    for code, label in item.categories
                ],
                "location": copy.deepcopy(dict(item.location)),
                "source_refs": [
                    copy.deepcopy(dict(source)) for source in item.source_refs
                ],
            }
            for item in sorted(
                candidate_result.record_local_facts,
                key=lambda fact: fact.candidate_id,
            )
        ],
    }


def _json_output_bytes(value: Mapping[str, object]) -> bytes:
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


def run_wu2_recovery(
    replay_root: Path,
    output_root: Path,
) -> ValidationResult[RecoveryRunSummary]:
    """Run the approved multi-identity anchor replay without network access."""

    try:
        checked_replay_root = Path(replay_root)
        checked_output_root = Path(output_root)
    except TypeError:
        return _failure(
            "RECOVERY_REPLAY_INVALID",
            "/paths",
            "pathType",
            expected="Path",
            actual=None,
        )

    if checked_output_root.exists():
        if checked_output_root.is_symlink() or not checked_output_root.is_dir():
            return _failure(
                "RECOVERY_REPLAY_INVALID",
                "/output_root",
                "emptyDirectory",
                expected="missing or empty directory",
                actual=None,
                artifact_path=str(checked_output_root),
            )
        try:
            if next(checked_output_root.iterdir(), None) is not None:
                return _failure(
                    "RECOVERY_REPLAY_INVALID",
                    "/output_root",
                    "emptyDirectory",
                    expected="missing or empty directory",
                    actual=None,
                    artifact_path=str(checked_output_root),
                )
        except OSError:
            return _failure(
                "RECOVERY_REPLAY_INVALID",
                "/output_root",
                "readableDirectory",
                expected="readable empty directory",
                actual=None,
                artifact_path=str(checked_output_root),
            )
    elif (
        not checked_output_root.parent.is_dir()
        or checked_output_root.parent.is_symlink()
    ):
        return _failure(
            "RECOVERY_REPLAY_INVALID",
            "/output_root",
            "parentDirectory",
            expected="existing regular parent directory",
            actual=None,
            artifact_path=str(checked_output_root),
        )

    try:
        prepared = _prepare_replay(checked_replay_root)
    except _CandidateControlError:
        return _failure(
            "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
            "/documents/candidates.json",
            "independentCandidate",
            expected="valid independent Candidate",
            actual=None,
            artifact_path=str(checked_replay_root / "case.json"),
        )
    except _ControlError:
        return _failure(
            "RECOVERY_REPLAY_INVALID",
            "/replay",
            "strictReplayControl",
            expected="valid frozen replay controls",
            actual=None,
            artifact_path=str(checked_replay_root),
        )

    replay = prepared.replay
    expected = replay["expected"]
    snapshot_value = replay["snapshot_metadata"]
    context_value = replay["artifact_context"]
    from trip_decider.resume_acquisition import (
        ResumeSnapshotMetadata,
        replay_wu2r_resume_anchor,
    )

    snapshot_metadata = ResumeSnapshotMetadata(
        format_version=snapshot_value["format_version"],
        provider=snapshot_value["provider"],
        operation=snapshot_value["operation"],
        crs=snapshot_value["crs"],
        retrieved_at=snapshot_value["retrieved_at"],
        request_fingerprint=snapshot_value["request_fingerprint"],
        response_locator=snapshot_value["response_locator"],
        data_policy=snapshot_value["data_policy"],
    )
    context = IngestionContext(
        request_ref=context_value["request_ref"],
        run_id=context_value["run_id"],
        created_at=context_value["created_at"],
        producer_name=context_value["producer_name"],
        producer_version=context_value["producer_version"],
    )
    seeds = tuple(item["seed"] for item in expected["seed_matches"])
    try:
        replay_result = replay_wu2r_resume_anchor(
            run_id=replay["run_id"],
            query_bytes=prepared.query_bytes,
            request_bytes=prepared.request_bytes,
            expected_query_sha256=replay["query_sha256"],
            expected_request_sha256=replay["request_sha256"],
            response_bytes=prepared.response_bytes,
            expected_response_sha256=replay["response_sha256"],
            snapshot_metadata=snapshot_metadata,
            seeds=seeds,
            context=context,
        )
    except (TypeError, ValueError):
        return _failure(
            "RECOVERY_REPLAY_INVALID",
            "/replay",
            "resumeReplay",
            expected="accepted offline Resume replay",
            actual=None,
            artifact_path=str(checked_replay_root),
        )

    if replay_result.network_attempts != 0:
        return _failure(
            "RECOVERY_NETWORK_ATTEMPTED",
            "/network_attempts",
            "const",
            expected="0",
            actual=replay_result.network_attempts,
            artifact_path=str(checked_replay_root),
        )
    candidate_result = replay_result.candidate_result
    candidate_artifact = candidate_result.candidate_artifact
    if candidate_artifact != prepared.expected_candidate:
        return _failure(
            "RECOVERY_CANDIDATE_ARTIFACT_INVALID",
            "/candidate_artifact",
            "independentCandidate",
            expected="fixture Candidate equality",
            actual=candidate_artifact,
            artifact_path=str(checked_replay_root / "case.json"),
        )

    seed_document = _seed_document(replay["run_id"], candidate_result)
    facts_document = _facts_document(replay["run_id"], candidate_result)
    if seed_document["seed_matches"] != expected["seed_matches"]:
        return _failure(
            "RECOVERY_REPLAY_INVALID",
            "/expected/seed_matches",
            "independentExpected",
            expected="exact seed accounting",
            actual=seed_document["seed_matches"],
            artifact_path=str(checked_replay_root / "replay.json"),
        )
    if facts_document["record_local_facts"] != expected["record_local_facts"]:
        return _failure(
            "RECOVERY_REPLAY_INVALID",
            "/expected/record_local_facts",
            "independentExpected",
            expected="exact record-local facts",
            actual=facts_document["record_local_facts"],
            artifact_path=str(checked_replay_root / "replay.json"),
        )

    candidates = _candidate_sequence(candidate_artifact)
    if candidates is None:
        raise RuntimeError("accepted Resume Candidate has no candidate array")
    status_counts = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    for match in candidate_result.seed_matches:
        if match.status not in status_counts:
            raise RuntimeError("accepted Resume seed status is unknown")
        status_counts[match.status] += 1
    if (
        len(candidates) != expected["candidate_count"]
        or status_counts != expected["seed_status_counts"]
    ):
        return _failure(
            "RECOVERY_REPLAY_INVALID",
            "/expected",
            "independentCounts",
            expected="exact candidate and seed counts",
            actual=None,
            artifact_path=str(checked_replay_root / "replay.json"),
        )

    candidate_bytes = _json_output_bytes(candidate_artifact)
    seed_bytes = _json_output_bytes(seed_document)
    facts_bytes = _json_output_bytes(facts_document)
    output_sha256 = {
        "candidates.json": _sha256(candidate_bytes),
        "seed-accounting.json": _sha256(seed_bytes),
        "record-local-facts.json": _sha256(facts_bytes),
    }
    run_summary_document = {
        "schema_version": "wu2r-downstream-recovery-run/1.0",
        "run_id": replay["run_id"],
        "input_fixture_identity": {
            "case_id": prepared.case["case_id"],
            "case_version": prepared.case["case_version"],
            "root_artifact_id": prepared.case["root_artifact_id"],
            "case_sha256": prepared.case_sha256,
            "replay_sha256": prepared.replay_sha256,
            "raw_response_sha256": prepared.response_sha256,
        },
        "output_paths": {
            "candidate_artifact_path": "candidates.json",
            "seed_accounting_path": "seed-accounting.json",
            "record_local_facts_path": "record-local-facts.json",
            "run_summary_path": "run-summary.json",
        },
        "candidate_count": len(candidates),
        "seed_status_counts": status_counts,
        "network_attempts": 0,
        "output_sha256": output_sha256,
        "completion_status": "completed",
    }
    summary_bytes = _json_output_bytes(run_summary_document)
    outputs = (
        ("candidates.json", candidate_bytes),
        ("seed-accounting.json", seed_bytes),
        ("record-local-facts.json", facts_bytes),
        ("run-summary.json", summary_bytes),
    )

    created_root = False
    temp_paths: list[Path] = []
    final_paths: list[Path] = []
    try:
        if not checked_output_root.exists():
            checked_output_root.mkdir()
            created_root = True
        for filename, content in outputs:
            final_path = checked_output_root / filename
            temp_path = (
                checked_output_root
                / f".{filename}.{uuid.uuid4().hex}.tmp"
            )
            temp_paths.append(temp_path)
            with temp_path.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if final_path.exists() or final_path.is_symlink():
                raise _ControlError("output path became non-empty")
            os.replace(temp_path, final_path)
            temp_paths.remove(temp_path)
            final_paths.append(final_path)
            if final_path.read_bytes() != content:
                raise _InstalledBytesMismatch(filename)
    except _InstalledBytesMismatch as error:
        _rollback_outputs(
            checked_output_root,
            temp_paths,
            final_paths,
            created_root,
        )
        return _failure(
            "RECOVERY_REPLAY_HASH_MISMATCH",
            f"/outputs/{error.filename}",
            "installedBytes",
            expected="prepared output bytes",
            actual=None,
            artifact_path=str(checked_output_root / error.filename),
        )
    except _ControlError:
        _rollback_outputs(
            checked_output_root,
            temp_paths,
            final_paths,
            created_root,
        )
        return _failure(
            "RECOVERY_REPLAY_INVALID",
            "/output_root",
            "emptyDirectory",
            expected="exclusive output paths",
            actual=None,
            artifact_path=str(checked_output_root),
        )
    except Exception:
        _rollback_outputs(
            checked_output_root,
            temp_paths,
            final_paths,
            created_root,
        )
        raise

    for filename, expected_bytes in outputs:
        installed = (checked_output_root / filename).read_bytes()
        if installed != expected_bytes:
            _rollback_outputs(
                checked_output_root,
                (),
                [checked_output_root / name for name in _OUTPUT_FILENAMES],
                created_root,
            )
            return _failure(
                "RECOVERY_REPLAY_HASH_MISMATCH",
                f"/outputs/{filename}",
                "installedBytes",
                expected="prepared output bytes",
                actual=None,
                artifact_path=str(checked_output_root / filename),
            )

    return ValidationResult(
        RecoveryRunSummary(
            run_id=replay["run_id"],
            candidate_artifact_path=checked_output_root / "candidates.json",
            seed_accounting_path=checked_output_root
            / "seed-accounting.json",
            record_local_facts_path=checked_output_root
            / "record-local-facts.json",
            run_summary_path=checked_output_root / "run-summary.json",
            candidate_count=len(candidates),
            seed_status_counts=status_counts,
            network_attempts=0,
            output_sha256=output_sha256,
        ),
        (),
    )


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
