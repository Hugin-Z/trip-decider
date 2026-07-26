"""Strict fixture-manifest and embedded-document validation.

This module validates only WU1 structural fixture contracts.  It does not
execute or interpret ``behavior_expected``.
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath

from .schema_validation import (
    BundleClosure,
    LoadedDocument,
    SchemaRegistry,
    ValidationProblem,
    ValidationResult,
    ValidatorInternalError,
    _LoadIssue,
    _ordered,
    _parse_json,
    _parse_yaml,
    _problem,
    _schema_problems,
    load_document,
    validate_bundle,
)


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


def _fixture_problem(
    code: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual: object = None,
    artifact_path: str = "case.json",
) -> ValidationProblem:
    return _problem(
        code,
        artifact_path,
        pointer,
        rule,
        expected=expected,
        actual=actual,
    )


def _manifest_schema_problems(
    manifest: Mapping[str, object],
    registry: SchemaRegistry,
) -> tuple[ValidationProblem, ...]:
    schema = registry.schemas.get(registry.fixture_schema_id)
    if not isinstance(schema, Mapping):
        raise ValidatorInternalError("fixture schema is absent from the registry")
    document = LoadedDocument(path=Path("case.json"), data=manifest)
    problems: list[ValidationProblem] = []
    for problem in _schema_problems(document, schema, registry):
        problems.append(
            ValidationProblem(
                error_code="FIXTURE_SCHEMA_VALIDATION_ERROR",
                artifact_path=problem.artifact_path,
                json_pointer=problem.json_pointer,
                schema_rule=problem.schema_rule,
                expected=problem.expected,
                actual_type=problem.actual_type,
                message="Fixture manifest does not conform to its schema.",
            )
        )
    return _ordered(problems)


def _is_safe_relative_path(value: str) -> bool:
    if "\\" in value:
        return False
    path = PurePosixPath(value)
    parts = value.split("/")
    return (
        not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in parts)
    )


def _parse_embedded_document(
    item: Mapping[str, object],
    index: int,
    registry: SchemaRegistry,
) -> ValidationResult[LoadedDocument]:
    pointer = f"/documents/{index}"
    relative_path = str(item["relative_path"])
    content = str(item["content_utf8"])
    if not _is_safe_relative_path(relative_path):
        return ValidationResult(
            None,
            (
                _fixture_problem(
                    "UNSAFE_FIXTURE_PATH",
                    f"{pointer}/relative_path",
                    "safeRelativePath",
                ),
            ),
        )
    if content.startswith("\ufeff") or "\r" in content:
        return ValidationResult(
            None,
            (
                _fixture_problem(
                    "FIXTURE_CONTENT_NOT_CANONICAL",
                    f"{pointer}/content_utf8",
                    "canonicalUtf8",
                ),
            ),
        )
    try:
        encoded = content.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return ValidationResult(
            None,
            (
                _fixture_problem(
                    "FIXTURE_CONTENT_NOT_CANONICAL",
                    f"{pointer}/content_utf8",
                    "canonicalUtf8",
                ),
            ),
        )
    actual_hash = hashlib.sha256(encoded).hexdigest()
    if item["file_sha256"] != actual_hash:
        return ValidationResult(
            None,
            (
                _fixture_problem(
                    "FIXTURE_FILE_HASH_MISMATCH",
                    f"{pointer}/file_sha256",
                    "fileHash",
                    expected="SHA256 of exact content_utf8 bytes",
                    actual=item["file_sha256"],
                ),
            ),
        )
    try:
        if item["media_type"] == "application/json":
            data = _parse_json(content)
        else:
            data = _parse_yaml(content)
    except _LoadIssue as issue:
        return ValidationResult(
            None,
            (
                _fixture_problem(
                    issue.code,
                    issue.pointer,
                    issue.rule,
                    artifact_path=relative_path,
                ),
            ),
        )
    artifact_type = data.get("artifact_type") if isinstance(data, Mapping) else None
    registered_schema_id = (
        registry.artifact_schema_ids.get(artifact_type)
        if isinstance(artifact_type, str)
        else None
    )
    if (
        registered_schema_id is not None
        and item["expected_schema_id"] != registered_schema_id
    ):
        return ValidationResult(
            None,
            (
                _fixture_problem(
                    "FIXTURE_SCHEMA_ID_MISMATCH",
                    f"{pointer}/expected_schema_id",
                    "schemaIdentity",
                    expected=registered_schema_id,
                    actual=item["expected_schema_id"],
                ),
            ),
        )
    return ValidationResult(
        LoadedDocument(path=Path(relative_path), data=data),
        (),
    )


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must start with slash")
    tokens: list[str] = []
    for raw_token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", raw_token):
            raise ValueError("invalid JSON Pointer escape")
        tokens.append(raw_token.replace("~1", "/").replace("~0", "~"))
    return tuple(tokens)


def _sequence_index(token: str, length: int, *, allow_end: bool) -> int:
    if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
        raise ValueError("invalid array index")
    index = int(token)
    limit = length if allow_end else length - 1
    if index < 0 or index > limit:
        raise ValueError("array index out of range")
    return index


def _apply_mutation(
    document: object,
    dirty_case: Mapping[str, object],
) -> object:
    operation = str(dirty_case["operation"])
    tokens = _pointer_tokens(str(dirty_case["json_pointer"]))
    if not tokens:
        if operation in {"add", "replace"}:
            return copy.deepcopy(dirty_case["value"])
        raise ValueError("document root cannot be removed")
    result = copy.deepcopy(document)
    parent = result
    for token in tokens[:-1]:
        if isinstance(parent, Mapping):
            if token not in parent:
                raise ValueError("mapping segment does not exist")
            parent = parent[token]
        elif isinstance(parent, list):
            parent = parent[_sequence_index(token, len(parent), allow_end=False)]
        else:
            raise ValueError("pointer parent is not a container")
    final = tokens[-1]
    if isinstance(parent, dict):
        exists = final in parent
        if operation == "add":
            if exists:
                raise ValueError("add target already exists")
            parent[final] = copy.deepcopy(dirty_case["value"])
        elif operation == "replace":
            if not exists:
                raise ValueError("replace target does not exist")
            parent[final] = copy.deepcopy(dirty_case["value"])
        else:
            if not exists:
                raise ValueError("remove target does not exist")
            del parent[final]
    elif isinstance(parent, list):
        if operation == "add":
            index = _sequence_index(final, len(parent), allow_end=True)
            parent.insert(index, copy.deepcopy(dirty_case["value"]))
        else:
            index = _sequence_index(final, len(parent), allow_end=False)
            if operation == "replace":
                parent[index] = copy.deepcopy(dirty_case["value"])
            else:
                del parent[index]
    else:
        raise ValueError("mutation target parent is not a container")
    return result


def _dirty_documents(
    documents: list[LoadedDocument],
    dirty_case: Mapping[str, object],
    dirty_index: int,
) -> ValidationResult[list[LoadedDocument]]:
    target = str(dirty_case["target_document"])
    matching = [
        index for index, document in enumerate(documents) if str(document.path) == target
    ]
    if len(matching) != 1:
        return ValidationResult(
            None,
            (
                _fixture_problem(
                    "FIXTURE_MUTATION_TARGET_NOT_FOUND",
                    f"/dirty_cases/{dirty_index}/target_document",
                    "mutationTarget",
                    expected="exactly one embedded relative_path",
                    actual=target,
                ),
            ),
        )
    target_index = matching[0]
    try:
        mutated_data = _apply_mutation(
            documents[target_index].data,
            dirty_case,
        )
    except (KeyError, TypeError, ValueError):
        return ValidationResult(
            None,
            (
                _fixture_problem(
                    "FIXTURE_MUTATION_ERROR",
                    f"/dirty_cases/{dirty_index}/json_pointer",
                    "jsonPointerMutation",
                ),
            ),
        )
    result = list(documents)
    result[target_index] = LoadedDocument(
        path=documents[target_index].path,
        data=mutated_data,
    )
    return ValidationResult(result, ())


def _expectation_matches(
    problem: ValidationProblem,
    expected: Mapping[str, object],
) -> bool:
    return (
        problem.error_code == expected["error_code"]
        and problem.json_pointer == expected["json_pointer"]
        and problem.schema_rule == expected["schema_rule"]
    )


def validate_fixture_manifest(
    manifest: Mapping[str, object],
    registry: SchemaRegistry,
) -> ValidationResult[ValidatedFixtureManifest]:
    manifest_problems = _manifest_schema_problems(manifest, registry)
    if manifest_problems:
        return ValidationResult(None, manifest_problems)

    documents: list[LoadedDocument] = []
    paths: set[str] = set()
    for index, item in enumerate(manifest["documents"]):
        assert isinstance(item, Mapping)
        relative_path = str(item["relative_path"])
        if relative_path in paths:
            return ValidationResult(
                None,
                (
                    _fixture_problem(
                        "DUPLICATE_FIXTURE_DOCUMENT_PATH",
                        f"/documents/{index}/relative_path",
                        "uniqueDocumentPath",
                    ),
                ),
            )
        parsed = _parse_embedded_document(item, index, registry)
        if parsed.problems:
            return ValidationResult(None, parsed.problems)
        assert parsed.value is not None
        paths.add(relative_path)
        documents.append(parsed.value)

    closure = BundleClosure(str(manifest["bundle_closure"]))
    root_artifact_id = str(manifest["root_artifact_id"])
    clean = validate_bundle(
        documents,
        registry,
        closure=closure,
        root_artifact_id=root_artifact_id,
    )
    if clean.problems:
        return ValidationResult(None, clean.problems)

    for dirty_index, dirty_case in enumerate(manifest["dirty_cases"]):
        assert isinstance(dirty_case, Mapping)
        mutated = _dirty_documents(documents, dirty_case, dirty_index)
        if mutated.problems:
            return ValidationResult(None, mutated.problems)
        assert mutated.value is not None
        dirty_result = validate_bundle(
            mutated.value,
            registry,
            closure=closure,
            root_artifact_id=root_artifact_id,
        )
        expected = dirty_case["expected_error"]
        assert isinstance(expected, Mapping)
        if (
            not dirty_result.problems
            or not _expectation_matches(dirty_result.problems[0], expected)
        ):
            return ValidationResult(
                None,
                (
                    _fixture_problem(
                        "FIXTURE_EXPECTATION_MISMATCH",
                        f"/dirty_cases/{dirty_index}/expected_error",
                        "expectedError",
                        expected="exact error_code/json_pointer/schema_rule",
                    ),
                ),
            )

    return ValidationResult(
        ValidatedFixtureManifest(
            case_id=str(manifest["case_id"]),
            root_artifact_id=root_artifact_id,
            document_count=len(documents),
            dirty_case_count=len(manifest["dirty_cases"]),
        ),
        (),
    )


def validate_fixture_directory(
    root: Path,
    registry: SchemaRegistry,
) -> ValidationResult[FixtureDirectorySummary]:
    root = Path(root)
    if not root.is_dir():
        return ValidationResult(
            None,
            (
                _fixture_problem(
                    "INPUT_READ_ERROR",
                    "",
                    "directory",
                    expected="fixture root directory",
                    artifact_path=str(root),
                ),
            ),
        )
    try:
        case_paths = sorted(
            path / "case.json"
            for path in root.iterdir()
            if path.is_dir() and (path / "case.json").is_file()
        )
    except OSError:
        return ValidationResult(
            None,
            (
                _fixture_problem(
                    "INPUT_READ_ERROR",
                    "",
                    "directory",
                    artifact_path=str(root),
                ),
            ),
        )

    fixture_count = 0
    document_count = 0
    dirty_case_count = 0
    case_ids: set[str] = set()
    for case_path in case_paths:
        loaded = load_document(case_path)
        if loaded.problems:
            return ValidationResult(None, loaded.problems)
        assert loaded.value is not None
        manifest = loaded.value.data
        if not isinstance(manifest, Mapping):
            return ValidationResult(
                None,
                (
                    _fixture_problem(
                        "FIXTURE_SCHEMA_VALIDATION_ERROR",
                        "",
                        "type",
                        expected="object",
                        actual=manifest,
                        artifact_path=str(case_path),
                    ),
                ),
            )
        validated = validate_fixture_manifest(manifest, registry)
        if validated.problems:
            return ValidationResult(None, validated.problems)
        assert validated.value is not None
        if validated.value.case_id in case_ids:
            return ValidationResult(
                None,
                (
                    _fixture_problem(
                        "DUPLICATE_FIXTURE_CASE_ID",
                        "/case_id",
                        "uniqueCase",
                        artifact_path=str(case_path),
                    ),
                ),
            )
        case_ids.add(validated.value.case_id)
        fixture_count += 1
        document_count += validated.value.document_count
        dirty_case_count += validated.value.dirty_case_count

    return ValidationResult(
        FixtureDirectorySummary(
            fixture_count=fixture_count,
            document_count=document_count,
            dirty_case_count=dirty_case_count,
        ),
        (),
    )
