"""Shared contract helpers for evidence normalization.

The WU2 open-data and route-evidence normalizers were removed with the
offline artifact pipeline (persistence-v2.md ruling 13.5).  What remains is
``contracts``, which the live modules still depend on for identifier and
type helpers.
"""

from .contracts import (
    IngestionContext,
    RunSummary,
    stable_identifier,
)

__all__ = [
    "IngestionContext",
    "RunSummary",
    "stable_identifier",
]
