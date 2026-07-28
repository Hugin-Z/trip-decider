"""Offline WU2 replay entry interface."""

from __future__ import annotations

from pathlib import Path

from trip_decider.adapters.contracts import RunSummary
from trip_decider.schema_validation import ValidationResult


def run_jiangxi_smoke(
    replay_root: Path,
    output_root: Path,
) -> ValidationResult[RunSummary]:
    """Run the approved Jiangxi smoke replay without network access."""

    raise NotImplementedError("WU2 offline ingestion is not implemented")
