"""WU5 end-to-end orchestration and static HTML result interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from trip_decider.schema_validation import ValidationResult


@dataclass(frozen=True)
class E2EDemoSummary:
    """Auditable control metadata for one complete offline demo run."""

    run_id: str
    run_summary_path: Path
    report_path: Path
    planning_status: str
    draft_created: bool
    publishable: bool
    generation_allowed_input: bool
    scheduled_count: int
    blocked_count: int
    network_attempts: int
    llm_calls: int
    output_sha256: Mapping[str, str]


def run_e2e_demo(
    anchor_root: Path,
    planning_input_root: Path,
    output_root: Path,
) -> ValidationResult[E2EDemoSummary]:
    """Run the approved offline stages and render their proven result."""

    raise NotImplementedError("WU5-E2E interface awaiting implementation")


__all__ = [
    "E2EDemoSummary",
    "run_e2e_demo",
]
