"""Public interfaces for strict artifact contract validation.

Work Unit 1 C1 freezes these interfaces before their fixture-first
implementation.  Every public operation is intentionally unimplemented here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Generic, TypeVar


T = TypeVar("T")


class BundleClosure(str, Enum):
    """Explicit bundle validation strength."""

    ARTIFACT_ONLY = "artifact_only"
    CLOSED = "closed"


@dataclass(frozen=True)
class ValidationProblem:
    """Stable, secret-safe machine problem."""

    error_code: str
    artifact_path: str
    json_pointer: str
    schema_rule: str
    expected: str
    actual_type: str
    message: str


@dataclass(frozen=True)
class ValidationResult(Generic[T]):
    """A validation value or an ordered tuple of problems."""

    value: T | None
    problems: tuple[ValidationProblem, ...]


@dataclass(frozen=True)
class LoadedDocument:
    """Strictly parsed document plus its original path."""

    path: Path
    data: object


@dataclass(frozen=True)
class SchemaRegistry:
    """Loaded local schema registry."""

    schemas: dict[str, object]


@dataclass(frozen=True)
class ValidatedArtifact:
    """Schema- and integrity-validated artifact."""

    artifact_id: str
    artifact_type: str
    document: LoadedDocument


@dataclass(frozen=True)
class ValidatedBundle:
    """Explicitly rooted bundle validation result."""

    closure: BundleClosure
    root_artifact_id: str
    validated_artifact_ids: tuple[str, ...]
    resolved_artifact_ids: tuple[str, ...]


class ValidatorInternalError(RuntimeError):
    """A stable project-owned internal validation failure."""


def load_document(
    path: Path,
    *,
    expected_artifact_type: str | None = None,
) -> ValidationResult[LoadedDocument]:
    raise NotImplementedError("Work Unit 1 schema loader is not implemented")


def validate_schema_registry(
    schema_paths: Sequence[Path],
) -> ValidationResult[SchemaRegistry]:
    raise NotImplementedError("Work Unit 1 schema registry is not implemented")


def validate_artifact(
    document: LoadedDocument,
    registry: SchemaRegistry,
) -> ValidationResult[ValidatedArtifact]:
    raise NotImplementedError("Work Unit 1 artifact validator is not implemented")


def validate_bundle(
    documents: Sequence[LoadedDocument],
    registry: SchemaRegistry,
    *,
    closure: BundleClosure,
    root_artifact_id: str,
) -> ValidationResult[ValidatedBundle]:
    raise NotImplementedError("Work Unit 1 bundle validator is not implemented")
