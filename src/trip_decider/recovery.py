"""WU2 Recovery multi-identity ingestion interfaces.

This module owns deterministic seed accounting, candidate-local source views,
route endpoint guarding, and offline replay orchestration.  It does not own a
network client, provider adapter, identity resolver, evidence runtime,
planner, or route acquisition.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from trip_decider.adapters.contracts import IngestionContext, safe_type
from trip_decider.adapters.open_data_poi import normalize_open_data_pois
from trip_decider.schema_validation import ValidationProblem, ValidationResult


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


def run_wu2_recovery(
    replay_root: Path,
    output_root: Path,
) -> ValidationResult[RecoveryRunSummary]:
    """Run the approved multi-identity anchor replay without network access."""

    raise NotImplementedError("WU2 Recovery offline replay is not implemented")


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
