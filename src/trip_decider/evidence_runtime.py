"""Candidate-local Evidence Runtime interface.

WU3-ER consumes only the four committed WU2R-DOR outputs.  It does not
acquire data, resolve identity ambiguity, rank candidates, or establish
route or itinerary feasibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from trip_decider.schema_validation import ValidationResult


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


def run_evidence_runtime(
    recovery_root: Path,
    output_root: Path,
) -> ValidationResult[EvidenceRuntimeSummary]:
    """Create candidate-local unknown evidence from strict DOR outputs."""

    raise NotImplementedError("WU3 Evidence Runtime is not implemented")


__all__ = [
    "CandidateEvidenceResult",
    "EVIDENCE_RUNTIME_PROBLEM_CODES",
    "EvidenceRuntimeSummary",
    "REQUIRED_EVIDENCE_SLOTS",
    "SeedEvidenceResult",
    "run_evidence_runtime",
]
