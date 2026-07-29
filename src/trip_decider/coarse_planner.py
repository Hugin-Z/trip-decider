"""Deterministic conditional coarse-planner interface.

WU4-CP consumes only explicit structured constraints plus completed Recovery
and Evidence Runtime outputs.  It does not parse natural language, resolve
identity ambiguity, call external services, or establish route feasibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from trip_decider.schema_validation import ValidationResult


COARSE_PLANNER_PROBLEM_CODES = frozenset(
    {
        "COARSE_PLANNER_CONSTRAINT_UNSUPPORTED",
        "COARSE_PLANNER_INPUT_INVALID",
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


def run_coarse_planner(
    recovery_root: Path,
    evidence_root: Path,
    planning_input_root: Path,
    output_root: Path,
) -> ValidationResult[CoarsePlannerSummary]:
    """Create a non-publishable coarse plan from explicit structured inputs."""

    raise NotImplementedError
