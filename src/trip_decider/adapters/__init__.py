"""Strict WU2 external-record normalization interfaces."""

from .contracts import (
    IngestionContext,
    RunSummary,
    stable_identifier,
)
from .open_data_poi import normalize_open_data_pois
from .route_evidence import normalize_route_evidence

__all__ = [
    "IngestionContext",
    "RunSummary",
    "normalize_open_data_pois",
    "normalize_route_evidence",
    "stable_identifier",
]
