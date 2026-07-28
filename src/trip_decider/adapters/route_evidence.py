"""OSRM route snapshot to evidence-artifact interface."""

from __future__ import annotations

from typing import Mapping

from trip_decider.schema_validation import ValidationResult

from .contracts import IngestionContext


def normalize_route_evidence(
    snapshot: Mapping[str, object],
    context: IngestionContext,
) -> ValidationResult[dict[str, object]]:
    """Normalize strict open route records into evidence facts."""

    raise NotImplementedError("WU2 route normalization is not implemented")
