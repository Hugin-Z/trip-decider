"""OpenStreetMap/Overpass snapshot to candidate-artifact interface."""

from __future__ import annotations

from typing import Mapping

from trip_decider.schema_validation import ValidationResult

from .contracts import IngestionContext


def normalize_open_data_pois(
    snapshot: Mapping[str, object],
    context: IngestionContext,
) -> ValidationResult[dict[str, object]]:
    """Normalize one strict open-data POI snapshot."""

    raise NotImplementedError("WU2 POI normalization is not implemented")
