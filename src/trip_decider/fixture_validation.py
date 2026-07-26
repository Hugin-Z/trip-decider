"""Public interfaces for strict fixture validation.

The implementations intentionally remain red until Work Unit 1 C6.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .schema_validation import SchemaRegistry, ValidationResult


@dataclass(frozen=True)
class ValidatedFixtureManifest:
    """Validated fixture manifest summary."""

    case_id: str
    root_artifact_id: str
    document_count: int
    dirty_case_count: int


@dataclass(frozen=True)
class FixtureDirectorySummary:
    """Deterministic summary of validated fixture directories."""

    fixture_count: int
    document_count: int
    dirty_case_count: int


def validate_fixture_manifest(
    manifest: Mapping[str, object],
    registry: SchemaRegistry,
) -> ValidationResult[ValidatedFixtureManifest]:
    raise NotImplementedError("Work Unit 1 fixture manifest validator is not implemented")


def validate_fixture_directory(
    root: Path,
    registry: SchemaRegistry,
) -> ValidationResult[FixtureDirectorySummary]:
    raise NotImplementedError("Work Unit 1 fixture directory validator is not implemented")
