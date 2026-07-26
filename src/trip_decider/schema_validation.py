"""Strict structural validation for trip-decider artifacts.

This module validates bytes, JSON/YAML structure, Draft 2020-12 schemas,
canonical payload hashes, explicit definition/reference registries, local
scopes, bundle roots, and root-reachable closure.  It intentionally contains
no travel-domain inference, feasibility reasoning, routing, or optimization.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Generic, TypeVar

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry, Resource


T = TypeVar("T")

SUPPORTED_SCHEMA_MAJOR = 0
SCHEMA_BASE = "https://trip-decider.example/schemas/0.1.0/"
ARTIFACT_TYPES = (
    "request",
    "constraint-parse",
    "constraints",
    "candidates",
    "evidence",
    "previous-plan",
    "plan",
    "plan-diff",
    "violations",
)


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
    resources: Registry = field(default_factory=Registry)
    artifact_schema_ids: dict[str, str] = field(default_factory=dict)
    fixture_schema_id: str = ""


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


@dataclass(frozen=True)
class _Definition:
    artifact_id: str
    kind: str
    entity_id: str
    pointer: str


@dataclass(frozen=True)
class _ArtifactReference:
    pointer: str
    value: Mapping[str, object]
    expected_type: str
    required: bool


@dataclass(frozen=True)
class _EntityReference:
    pointer: str
    entity_id: str
    expected_kind: str


class _LoadIssue(ValueError):
    def __init__(self, code: str, pointer: str, rule: str) -> None:
        super().__init__(code)
        self.code = code
        self.pointer = pointer
        self.rule = rule


_MESSAGES = {
    "INPUT_READ_ERROR": "Input document could not be read.",
    "UNSUPPORTED_MEDIA_TYPE": "Input document media type is not supported.",
    "INVALID_UTF8": "Input document is not valid UTF-8.",
    "UTF8_BOM_NOT_ALLOWED": "UTF-8 byte order marks are not allowed.",
    "INVALID_JSON": "Input document is not valid JSON.",
    "INVALID_YAML": "Input document is not valid YAML.",
    "DUPLICATE_MAPPING_KEY": "Mapping keys must be unique.",
    "NON_STRING_MAPPING_KEY": "Mapping keys must be strings.",
    "INVALID_JSON_CONSTANT": "JSON numbers must be finite.",
    "ARTIFACT_TYPE_MISMATCH": "Artifact type does not match the required type.",
    "SCHEMA_VALIDATION_ERROR": "Document does not satisfy its schema.",
    "UNKNOWN_SCHEMA_MAJOR": "Schema major version is not supported.",
    "PAYLOAD_HASH_MISMATCH": "Payload hash does not match canonical payload bytes.",
    "DUPLICATE_DEFINITION_ID": "Entity definition IDs must be unique in their scope.",
    "UNRESOLVED_REFERENCE": "A required reference cannot be resolved.",
    "REFERENCE_KIND_MISMATCH": "A reference target has an incompatible kind or identity.",
    "DUPLICATE_ARTIFACT_ID": "Artifact IDs must be unique in a bundle.",
    "DUPLICATE_LOCAL_SOURCE_ID": "Evidence source IDs must be unique within one fact.",
    "UNRESOLVED_LOCAL_SOURCE_REFERENCE": "Evidence source reference must resolve within its fact.",
    "UNRESOLVED_PLAN_VERSION_ENTITY": "Plan-version entity reference cannot be resolved.",
    "AMBIGUOUS_PLAN_VERSION_ENTITY": "Plan-version entity reference is not unique.",
    "UNRESOLVED_BUNDLE_ROOT": "Explicit bundle root cannot be resolved.",
    "UNEXPECTED_BUNDLE_ARTIFACT": "Artifact is outside the root-reachable closure.",
    "PLAN_STATUS_MISMATCH": "Post-plan status does not match its referenced plan.",
}


def _escape_pointer_token(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _pointer(parts: Sequence[object]) -> str:
    if not parts:
        return ""
    return "/" + "/".join(_escape_pointer_token(part) for part in parts)


def _safe_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _problem(
    code: str,
    artifact_path: str,
    pointer: str,
    rule: str,
    *,
    expected: str = "",
    actual: object = None,
) -> ValidationProblem:
    return ValidationProblem(
        error_code=code,
        artifact_path=artifact_path,
        json_pointer=pointer,
        schema_rule=rule,
        expected=expected,
        actual_type=_safe_type(actual),
        message=_MESSAGES.get(code, "Structural validation failed."),
    )


def _ordered(problems: Sequence[ValidationProblem]) -> tuple[ValidationProblem, ...]:
    return tuple(
        sorted(
            problems,
            key=lambda item: (item.artifact_path, item.json_pointer, item.error_code),
        )
    )


def canonical_payload_sha256(payload: object) -> str:
    """Return the frozen canonical-json-v1 payload digest."""

    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValidatorInternalError("canonical payload serialization failed") from error
    return hashlib.sha256(encoded).hexdigest()


def _json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _LoadIssue("DUPLICATE_MAPPING_KEY", "", "uniqueKeys")
        result[key] = value
    return result


def _json_constant(_: str) -> object:
    raise _LoadIssue("INVALID_JSON_CONSTANT", "", "finiteNumber")


class _StrictSafeLoader(yaml.SafeLoader):
    pass


_StrictSafeLoader.yaml_implicit_resolvers = copy.deepcopy(
    yaml.SafeLoader.yaml_implicit_resolvers
)
for first_character, resolvers in list(_StrictSafeLoader.yaml_implicit_resolvers.items()):
    _StrictSafeLoader.yaml_implicit_resolvers[first_character] = [
        resolver
        for resolver in resolvers
        if resolver[0] != "tag:yaml.org,2002:timestamp"
    ]


def _yaml_mapping(
    loader: _StrictSafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise _LoadIssue("NON_STRING_MAPPING_KEY", "", "stringKeys")
        if key in result:
            raise _LoadIssue("DUPLICATE_MAPPING_KEY", "", "uniqueKeys")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _yaml_mapping,
)


def _parse_json(text: str) -> object:
    try:
        return json.loads(
            text,
            object_pairs_hook=_json_pairs,
            parse_constant=_json_constant,
        )
    except _LoadIssue as issue:
        if issue.code == "INVALID_JSON_CONSTANT":
            match = re.search(
                r'"([^"\\]+)"\s*:\s*(?:NaN|Infinity|-Infinity)',
                text,
            )
            if match:
                raise _LoadIssue(
                    issue.code,
                    "/" + _escape_pointer_token(match.group(1)),
                    issue.rule,
                ) from issue
        raise
    except (json.JSONDecodeError, RecursionError) as error:
        raise _LoadIssue("INVALID_JSON", "", "jsonSyntax") from error


def _parse_yaml(text: str) -> object:
    try:
        return yaml.load(text, Loader=_StrictSafeLoader)
    except _LoadIssue:
        raise
    except yaml.YAMLError as error:
        raise _LoadIssue("INVALID_YAML", "", "yamlSyntax") from error


def load_document(
    path: Path,
    *,
    expected_artifact_type: str | None = None,
) -> ValidationResult[LoadedDocument]:
    path = Path(path)
    artifact_path = str(path)
    try:
        if not path.is_file():
            return ValidationResult(
                None,
                (
                    _problem(
                        "INPUT_READ_ERROR",
                        artifact_path,
                        "",
                        "file",
                        expected="regular file",
                    ),
                ),
            )
        raw = path.read_bytes()
    except OSError:
        return ValidationResult(
            None,
            (_problem("INPUT_READ_ERROR", artifact_path, "", "file"),),
        )
    if raw.startswith(b"\xef\xbb\xbf"):
        return ValidationResult(
            None,
            (_problem("UTF8_BOM_NOT_ALLOWED", artifact_path, "", "utf8"),),
        )
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return ValidationResult(
            None,
            (_problem("INVALID_UTF8", artifact_path, "", "utf8"),),
        )
    try:
        suffix = path.suffix.lower()
        if suffix == ".json":
            data = _parse_json(text)
        elif suffix in {".yaml", ".yml"}:
            data = _parse_yaml(text)
        else:
            return ValidationResult(
                None,
                (
                    _problem(
                        "UNSUPPORTED_MEDIA_TYPE",
                        artifact_path,
                        "",
                        "fileExtension",
                        expected=".json|.yaml|.yml",
                    ),
                ),
            )
    except _LoadIssue as issue:
        return ValidationResult(
            None,
            (_problem(issue.code, artifact_path, issue.pointer, issue.rule),),
        )
    if expected_artifact_type is not None:
        actual = data.get("artifact_type") if isinstance(data, Mapping) else None
        if actual != expected_artifact_type:
            return ValidationResult(
                None,
                (
                    _problem(
                        "ARTIFACT_TYPE_MISMATCH",
                        artifact_path,
                        "/artifact_type",
                        "const",
                        expected=expected_artifact_type,
                        actual=actual,
                    ),
                ),
            )
    return ValidationResult(LoadedDocument(path=path, data=data), ())


def _assert_format_checker() -> FormatChecker:
    checker = FormatChecker()
    try:
        valid = checker.conforms("2026-07-26T08:00:00+08:00", "date-time")
        invalid = checker.conforms("2026-07-26", "date-time")
    except Exception as error:
        raise ValidatorInternalError("required format checker is unavailable") from error
    if not valid or invalid:
        raise ValidatorInternalError("required format checker self-check failed")
    return checker


def validate_schema_registry(
    schema_paths: Sequence[Path],
) -> ValidationResult[SchemaRegistry]:
    _assert_format_checker()
    schemas: dict[str, object] = {}
    artifact_schema_ids: dict[str, str] = {}
    fixture_schema_id = ""
    resources = Registry()
    problems: list[ValidationProblem] = []
    for path_value in schema_paths:
        path = Path(path_value)
        artifact_path = str(path)
        try:
            raw = path.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                raise _LoadIssue("UTF8_BOM_NOT_ALLOWED", "", "utf8")
            data = _parse_json(raw.decode("utf-8", errors="strict"))
        except UnicodeDecodeError:
            problems.append(_problem("INVALID_UTF8", artifact_path, "", "utf8"))
            continue
        except OSError:
            problems.append(_problem("INPUT_READ_ERROR", artifact_path, "", "file"))
            continue
        except _LoadIssue as issue:
            problems.append(
                _problem(issue.code, artifact_path, issue.pointer, issue.rule)
            )
            continue
        if not isinstance(data, Mapping):
            problems.append(
                _problem(
                    "SCHEMA_VALIDATION_ERROR",
                    artifact_path,
                    "",
                    "type",
                    expected="object",
                    actual=data,
                )
            )
            continue
        schema_id = data.get("$id")
        if not isinstance(schema_id, str):
            problems.append(
                _problem(
                    "SCHEMA_VALIDATION_ERROR",
                    artifact_path,
                    "",
                    "required",
                    expected="$id",
                    actual=data,
                )
            )
            continue
        if schema_id in schemas:
            problems.append(
                _problem(
                    "SCHEMA_VALIDATION_ERROR",
                    artifact_path,
                    "/$id",
                    "uniqueSchemaId",
                    expected="unique $id",
                    actual=schema_id,
                )
            )
            continue
        try:
            Draft202012Validator.check_schema(data)
            resources = resources.with_resource(
                schema_id,
                Resource.from_contents(data),
            )
        except (SchemaError, Exception) as error:
            if isinstance(error, ValidatorInternalError):
                raise
            problems.append(
                _problem(
                    "SCHEMA_VALIDATION_ERROR",
                    artifact_path,
                    "",
                    "checkSchema",
                    expected="Draft 2020-12",
                    actual=data,
                )
            )
            continue
        schemas[schema_id] = dict(data)
        stem = path.name.removesuffix(".schema.json")
        if stem in ARTIFACT_TYPES:
            artifact_schema_ids[stem] = schema_id
        elif stem == "fixture-case":
            fixture_schema_id = schema_id
    if problems:
        return ValidationResult(None, _ordered(problems))
    missing = sorted(set(ARTIFACT_TYPES) - set(artifact_schema_ids))
    if missing or not fixture_schema_id:
        raise ValidatorInternalError("required schema registry entries are missing")
    return ValidationResult(
        SchemaRegistry(
            schemas=schemas,
            resources=resources,
            artifact_schema_ids=artifact_schema_ids,
            fixture_schema_id=fixture_schema_id,
        ),
        (),
    )


def _leaf_schema_errors(error: ValidationError) -> list[ValidationError]:
    if not error.context:
        return [error]
    leaves: list[ValidationError] = []
    for child in error.context:
        leaves.extend(_leaf_schema_errors(child))
    return leaves


def _schema_problems(
    document: LoadedDocument,
    schema: Mapping[str, object],
    registry: SchemaRegistry,
) -> list[ValidationProblem]:
    checker = _assert_format_checker()
    try:
        validator = Draft202012Validator(
            schema,
            registry=registry.resources,
            format_checker=checker,
        )
        top_errors = list(validator.iter_errors(document.data))
    except Exception as error:
        raise ValidatorInternalError("schema validation execution failed") from error
    errors: list[ValidationError] = []
    for top_error in top_errors:
        errors.extend(_leaf_schema_errors(top_error))
    priority = {
        "required": 0,
        "format": 1,
        "const": 2,
        "minItems": 3,
        "maxItems": 4,
        "additionalProperties": 5,
        "pattern": 6,
    }
    errors.sort(
        key=lambda item: (
            _pointer(tuple(item.absolute_path)),
            priority.get(str(item.validator), 20),
            str(item.validator),
        )
    )
    seen: set[tuple[str, str]] = set()
    problems: list[ValidationProblem] = []
    for error in errors:
        pointer = _pointer(tuple(error.absolute_path))
        rule = str(error.validator)
        key = (pointer, rule)
        if key in seen:
            continue
        seen.add(key)
        problems.append(
            _problem(
                "SCHEMA_VALIDATION_ERROR",
                str(document.path),
                pointer,
                rule,
                expected=rule,
                actual=error.instance,
            )
        )
    return problems


def _definitions(data: Mapping[str, object]) -> list[_Definition]:
    artifact = str(data["artifact_id"])
    artifact_type = str(data["artifact_type"])
    payload = data["payload"]
    assert isinstance(payload, Mapping)
    result: list[_Definition] = []

    def add(kind: str, value: object, pointer: str) -> None:
        if isinstance(value, str):
            result.append(_Definition(artifact, kind, value, pointer))

    if artifact_type == "request":
        add("request", payload.get("request_id"), "/payload/request_id")
    elif artifact_type == "constraint-parse":
        for index, item in enumerate(payload.get("parsed_constraints", [])):
            add("parse_item", item.get("parse_item_id"), f"/payload/parsed_constraints/{index}/parse_item_id")
    elif artifact_type == "constraints":
        add("constraint_set", payload.get("constraint_set_id"), "/payload/constraint_set_id")
        for index, item in enumerate(payload.get("constraints", [])):
            add("constraint", item.get("constraint_id"), f"/payload/constraints/{index}/constraint_id")
    elif artifact_type == "candidates":
        add("candidate_set", payload.get("candidate_set_id"), "/payload/candidate_set_id")
        for index, item in enumerate(payload.get("candidates", [])):
            add("candidate", item.get("candidate_id"), f"/payload/candidates/{index}/candidate_id")
    elif artifact_type == "evidence":
        add("evidence_set", payload.get("evidence_set_id"), "/payload/evidence_set_id")
        for index, item in enumerate(payload.get("facts", [])):
            add("evidence_fact", item.get("fact_id"), f"/payload/facts/{index}/fact_id")
    elif artifact_type == "plan":
        add("plan", payload.get("plan_id"), "/payload/plan_id")
        for index, item in enumerate(payload.get("base_selections", [])):
            add("base_selection", item.get("base_selection_id"), f"/payload/base_selections/{index}/base_selection_id")
        for day_index, day in enumerate(payload.get("days", [])):
            add("day", day.get("day_id"), f"/payload/days/{day_index}/day_id")
            for item_index, item in enumerate(day.get("activities", [])):
                add("activity", item.get("activity_id"), f"/payload/days/{day_index}/activities/{item_index}/activity_id")
            for item_index, item in enumerate(day.get("legs", [])):
                add("leg", item.get("leg_id"), f"/payload/days/{day_index}/legs/{item_index}/leg_id")
    elif artifact_type == "violations":
        for index, item in enumerate(payload.get("violations", [])):
            add("violation", item.get("violation_id"), f"/payload/violations/{index}/violation_id")
        for index, item in enumerate(payload.get("proofs", [])):
            add("proof", item.get("proof_id"), f"/payload/proofs/{index}/proof_id")
    elif artifact_type == "plan-diff":
        for index, item in enumerate(payload.get("changes", [])):
            add("change", item.get("change_id"), f"/payload/changes/{index}/change_id")
    return result


def _duplicate_definition_problems(
    document: LoadedDocument,
    definitions: Sequence[_Definition],
) -> list[ValidationProblem]:
    first: dict[str, _Definition] = {}
    problems: list[ValidationProblem] = []
    for definition in definitions:
        if definition.entity_id in first:
            problems.append(
                _problem(
                    "DUPLICATE_DEFINITION_ID",
                    str(document.path),
                    definition.pointer,
                    "uniqueDefinition",
                    expected=first[definition.entity_id].kind,
                    actual=definition.entity_id,
                )
            )
        else:
            first[definition.entity_id] = definition
    return problems


def _previous_local_definitions(data: Mapping[str, object]) -> list[tuple[str, str, str]]:
    if data.get("artifact_type") != "previous-plan":
        return []
    payload = data["payload"]
    assert isinstance(payload, Mapping)
    snapshot = payload.get("snapshot", {})
    result: list[tuple[str, str, str]] = []
    result.append(("plan", str(payload.get("previous_plan_id")), "/payload/previous_plan_id"))
    for index, item in enumerate(snapshot.get("base_selections", [])):
        result.append(("base_selection", str(item.get("base_selection_id")), f"/payload/snapshot/base_selections/{index}/base_selection_id"))
    for day_index, day in enumerate(snapshot.get("days", [])):
        result.append(("day", str(day.get("day_id")), f"/payload/snapshot/days/{day_index}/day_id"))
        for item_index, item in enumerate(day.get("activities", [])):
            result.append(("activity", str(item.get("activity_id")), f"/payload/snapshot/days/{day_index}/activities/{item_index}/activity_id"))
        for item_index, item in enumerate(day.get("legs", [])):
            result.append(("leg", str(item.get("leg_id")), f"/payload/snapshot/days/{day_index}/legs/{item_index}/leg_id"))
    return result


def _local_reference_problems(document: LoadedDocument) -> list[ValidationProblem]:
    data = document.data
    assert isinstance(data, Mapping)
    artifact_type = data["artifact_type"]
    payload = data["payload"]
    assert isinstance(payload, Mapping)
    problems: list[ValidationProblem] = []
    if artifact_type == "constraints":
        defined = {item["constraint_id"] for item in payload.get("constraints", [])}
        for index, item in enumerate(payload.get("constraints", [])):
            target = item.get("supersedes_constraint_id")
            if target is not None and target not in defined:
                problems.append(_problem("UNRESOLVED_REFERENCE", str(document.path), f"/payload/constraints/{index}/supersedes_constraint_id", "localReference", expected="constraint", actual=target))
    elif artifact_type == "candidates":
        defined = {item["candidate_id"] for item in payload.get("candidates", [])}
        for index, item in enumerate(payload.get("candidates", [])):
            target = item.get("parent_candidate_id")
            if target is not None and target not in defined:
                problems.append(_problem("UNRESOLVED_REFERENCE", str(document.path), f"/payload/candidates/{index}/parent_candidate_id", "localReference", expected="candidate", actual=target))
    elif artifact_type == "evidence":
        fact_ids = {item["fact_id"] for item in payload.get("facts", [])}
        for fact_index, fact in enumerate(payload.get("facts", [])):
            sources: dict[str, int] = {}
            for source_index, source in enumerate(fact.get("sources", [])):
                source_id = source["source_id"]
                if source_id in sources:
                    problems.append(_problem("DUPLICATE_LOCAL_SOURCE_ID", str(document.path), f"/payload/facts/{fact_index}/sources/{source_index}/source_id", "uniqueLocalSource", expected="unique within fact", actual=source_id))
                else:
                    sources[source_id] = source_index
            for ref_index, source_id in enumerate(fact.get("conflict_source_refs", [])):
                if source_id not in sources:
                    problems.append(_problem("UNRESOLVED_LOCAL_SOURCE_REFERENCE", str(document.path), f"/payload/facts/{fact_index}/conflict_source_refs/{ref_index}", "localSourceReference", expected="source in current fact", actual=source_id))
            detail = fact.get("derivation_detail", {})
            for ref_index, fact_id in enumerate(detail.get("input_fact_ids", [])):
                if fact_id not in fact_ids:
                    problems.append(_problem("UNRESOLVED_REFERENCE", str(document.path), f"/payload/facts/{fact_index}/derivation_detail/input_fact_ids/{ref_index}", "localReference", expected="evidence_fact", actual=fact_id))
    elif artifact_type == "violations":
        proofs = {item["proof_id"] for item in payload.get("proofs", [])}
        for violation_index, violation in enumerate(payload.get("violations", [])):
            for ref_index, proof_id in enumerate(violation.get("proof_refs", [])):
                if proof_id not in proofs:
                    problems.append(_problem("UNRESOLVED_REFERENCE", str(document.path), f"/payload/violations/{violation_index}/proof_refs/{ref_index}", "localReference", expected="proof", actual=proof_id))
    elif artifact_type == "previous-plan":
        seen: dict[str, str] = {}
        for kind, entity_id, pointer in _previous_local_definitions(data):
            if entity_id in seen:
                problems.append(_problem("DUPLICATE_DEFINITION_ID", str(document.path), pointer, "uniqueDefinition", expected=seen[entity_id], actual=entity_id))
            else:
                seen[entity_id] = kind
    return problems


def validate_artifact(
    document: LoadedDocument,
    registry: SchemaRegistry,
) -> ValidationResult[ValidatedArtifact]:
    data = document.data
    if not isinstance(data, Mapping):
        return ValidationResult(
            None,
            (_problem("SCHEMA_VALIDATION_ERROR", str(document.path), "", "type", expected="object", actual=data),),
        )
    version = data.get("schema_version")
    if isinstance(version, str):
        major_text = version.split(".", 1)[0]
        if major_text.isdigit() and int(major_text) != SUPPORTED_SCHEMA_MAJOR:
            return ValidationResult(
                None,
                (_problem("UNKNOWN_SCHEMA_MAJOR", str(document.path), "/schema_version", "supportedMajor", expected=str(SUPPORTED_SCHEMA_MAJOR), actual=version),),
            )
    artifact_type = data.get("artifact_type")
    if not isinstance(artifact_type, str) or artifact_type not in registry.artifact_schema_ids:
        return ValidationResult(
            None,
            (_problem("SCHEMA_VALIDATION_ERROR", str(document.path), "/artifact_type", "enum", expected="registered artifact type", actual=artifact_type),),
        )
    schema_id = registry.artifact_schema_ids[artifact_type]
    schema = registry.schemas[schema_id]
    assert isinstance(schema, Mapping)
    schema_problems = _schema_problems(document, schema, registry)
    if schema_problems:
        return ValidationResult(None, _ordered(schema_problems))
    payload = data["payload"]
    integrity = data["integrity"]
    assert isinstance(integrity, Mapping)
    actual_hash = canonical_payload_sha256(payload)
    if integrity["payload_sha256"] != actual_hash:
        return ValidationResult(
            None,
            (_problem("PAYLOAD_HASH_MISMATCH", str(document.path), "/integrity/payload_sha256", "payloadHash", expected="canonical-json-v1 SHA256", actual=integrity["payload_sha256"]),),
        )
    definitions = _definitions(data)
    problems = _duplicate_definition_problems(document, definitions)
    problems.extend(_local_reference_problems(document))
    if problems:
        return ValidationResult(None, _ordered(problems))
    return ValidationResult(
        ValidatedArtifact(
            artifact_id=str(data["artifact_id"]),
            artifact_type=artifact_type,
            document=document,
        ),
        (),
    )


def _artifact_references(data: Mapping[str, object]) -> list[_ArtifactReference]:
    artifact_type = data["artifact_type"]
    payload = data["payload"]
    assert isinstance(payload, Mapping)
    result: list[_ArtifactReference] = []

    def add(name: str, expected: str, required: bool = True) -> None:
        value = payload.get(name)
        if isinstance(value, Mapping):
            result.append(_ArtifactReference(f"/payload/{name}", value, expected, required))

    if artifact_type == "constraint-parse":
        add("request_ref", "request")
    elif artifact_type == "constraints":
        add("request_ref", "request")
        add("parse_ref", "constraint-parse")
    elif artifact_type == "candidates":
        add("request_ref", "request")
    elif artifact_type == "previous-plan":
        add("previous_plan_artifact_ref", "plan", required=False)
    elif artifact_type == "plan":
        add("request_ref", "request")
        add("constraint_set_ref", "constraints")
        add("candidate_set_ref", "candidates")
        add("evidence_set_ref", "evidence")
        if "previous_plan_ref" in payload:
            add("previous_plan_ref", "previous-plan")
    elif artifact_type == "violations":
        if payload["evaluation_stage"] == "pre_plan":
            add("request_ref", "request")
            add("constraint_set_ref", "constraints")
            add("candidate_set_ref", "candidates")
            add("evidence_set_ref", "evidence")
        else:
            add("plan_ref", "plan")
    return result


def _entity_references(data: Mapping[str, object]) -> list[_EntityReference]:
    artifact_type = data["artifact_type"]
    payload = data["payload"]
    assert isinstance(payload, Mapping)
    result: list[_EntityReference] = []

    def add(pointer: str, value: object, kind: str) -> None:
        if isinstance(value, str):
            result.append(_EntityReference(pointer, value, kind))

    if artifact_type == "constraint-parse":
        for index, item in enumerate(payload.get("parsed_constraints", [])):
            add(f"/payload/parsed_constraints/{index}/constraint_id", item.get("constraint_id"), "constraint")
    elif artifact_type == "constraints":
        for constraint_index, item in enumerate(payload.get("constraints", [])):
            for target_index, target in enumerate(item.get("target_refs", [])):
                if target["target_type"] == "request_scope":
                    add(f"/payload/constraints/{constraint_index}/target_refs/{target_index}/request_id", target.get("request_id"), "request")
                else:
                    add(f"/payload/constraints/{constraint_index}/target_refs/{target_index}/entity_id", target.get("entity_id"), str(target.get("entity_kind")))
            origin = item.get("origin", {})
            for ref_index, ref in enumerate(origin.get("refs", [])):
                add(f"/payload/constraints/{constraint_index}/origin/refs/{ref_index}/parse_item_id", ref.get("parse_item_id"), "parse_item")
    elif artifact_type == "candidates":
        for candidate_index, item in enumerate(payload.get("candidates", [])):
            for ref_index, value in enumerate(item.get("evidence_fact_refs", [])):
                add(f"/payload/candidates/{candidate_index}/evidence_fact_refs/{ref_index}", value, "evidence_fact")
    elif artifact_type == "evidence":
        for fact_index, fact in enumerate(payload.get("facts", [])):
            subject = fact["subject"]
            if subject["subject_type"] == "entity":
                add(f"/payload/facts/{fact_index}/subject/entity_id", subject.get("entity_id"), "candidate")
            else:
                add(f"/payload/facts/{fact_index}/subject/from_candidate_ref", subject.get("from_candidate_ref"), "candidate")
                add(f"/payload/facts/{fact_index}/subject/to_candidate_ref", subject.get("to_candidate_ref"), "candidate")
    elif artifact_type == "previous-plan":
        add("/payload/baseline_constraint_set_id", payload.get("baseline_constraint_set_id"), "constraint_set")
    elif artifact_type == "plan":
        for condition_index, item in enumerate(payload.get("conditions", [])):
            for ref_index, value in enumerate(item.get("constraint_refs", [])):
                add(f"/payload/conditions/{condition_index}/constraint_refs/{ref_index}", value, "constraint")
            for ref_index, value in enumerate(item.get("evidence_fact_refs", [])):
                add(f"/payload/conditions/{condition_index}/evidence_fact_refs/{ref_index}", value, "evidence_fact")
        for base_index, item in enumerate(payload.get("base_selections", [])):
            add(f"/payload/base_selections/{base_index}/candidate_ref", item.get("candidate_ref"), "candidate")
            for ref_index, value in enumerate(item.get("constraint_refs", [])):
                add(f"/payload/base_selections/{base_index}/constraint_refs/{ref_index}", value, "constraint")
            for ref_index, value in enumerate(item.get("evidence_fact_refs", [])):
                add(f"/payload/base_selections/{base_index}/evidence_fact_refs/{ref_index}", value, "evidence_fact")
        for day_index, day in enumerate(payload.get("days", [])):
            for item_index, item in enumerate(day.get("activities", [])):
                prefix = f"/payload/days/{day_index}/activities/{item_index}"
                add(prefix + "/candidate_ref", item.get("candidate_ref"), "candidate")
                for ref_index, value in enumerate(item.get("constraint_refs", [])):
                    add(prefix + f"/constraint_refs/{ref_index}", value, "constraint")
                for ref_index, value in enumerate(item.get("evidence_fact_refs", [])):
                    add(prefix + f"/evidence_fact_refs/{ref_index}", value, "evidence_fact")
            for item_index, item in enumerate(day.get("legs", [])):
                add(f"/payload/days/{day_index}/legs/{item_index}/derivation_fact_ref", item.get("derivation_fact_ref"), "evidence_fact")
        for item_index, item in enumerate(payload.get("excluded_candidates", [])):
            prefix = f"/payload/excluded_candidates/{item_index}"
            add(prefix + "/candidate_ref", item.get("candidate_ref"), "candidate")
            for ref_index, value in enumerate(item.get("constraint_refs", [])):
                add(prefix + f"/constraint_refs/{ref_index}", value, "constraint")
            for ref_index, value in enumerate(item.get("evidence_fact_refs", [])):
                add(prefix + f"/evidence_fact_refs/{ref_index}", value, "evidence_fact")
        for item_index, item in enumerate(payload.get("constraint_evaluations", [])):
            add(f"/payload/constraint_evaluations/{item_index}/constraint_ref", item.get("constraint_ref"), "constraint")
        for ref_index, value in enumerate(payload.get("proof_refs", [])):
            add(f"/payload/proof_refs/{ref_index}", value, "proof")
    elif artifact_type == "violations":
        for item_index, item in enumerate(payload.get("violations", [])):
            for ref_index, value in enumerate(item.get("constraint_refs", [])):
                add(f"/payload/violations/{item_index}/constraint_refs/{ref_index}", value, "constraint")
            for ref_index, value in enumerate(item.get("evidence_fact_refs", [])):
                add(f"/payload/violations/{item_index}/evidence_fact_refs/{ref_index}", value, "evidence_fact")
        for item_index, item in enumerate(payload.get("conditions", [])):
            for ref_index, value in enumerate(item.get("constraint_refs", [])):
                add(f"/payload/conditions/{item_index}/constraint_refs/{ref_index}", value, "constraint")
            for ref_index, value in enumerate(item.get("evidence_fact_refs", [])):
                add(f"/payload/conditions/{item_index}/evidence_fact_refs/{ref_index}", value, "evidence_fact")
        for item_index, item in enumerate(payload.get("candidate_conflict_sets", [])):
            for ref_index, value in enumerate(item.get("constraint_refs", [])):
                add(f"/payload/candidate_conflict_sets/{item_index}/constraint_refs/{ref_index}", value, "constraint")
            for ref_index, value in enumerate(item.get("evidence_fact_refs", [])):
                add(f"/payload/candidate_conflict_sets/{item_index}/evidence_fact_refs/{ref_index}", value, "evidence_fact")
        for item_index, item in enumerate(payload.get("proofs", [])):
            for ref_index, value in enumerate(item.get("constraint_refs", [])):
                add(f"/payload/proofs/{item_index}/constraint_refs/{ref_index}", value, "constraint")
            for ref_index, value in enumerate(item.get("input_fact_ids", [])):
                add(f"/payload/proofs/{item_index}/input_fact_ids/{ref_index}", value, "evidence_fact")
    elif artifact_type == "plan-diff":
        add("/payload/new_plan_id", payload.get("new_plan_id"), "plan")
        for item_index, item in enumerate(payload.get("changes", [])):
            for ref_index, value in enumerate(item.get("constraint_refs", [])):
                add(f"/payload/changes/{item_index}/constraint_refs/{ref_index}", value, "constraint")
    return result


def _version_documents(
    data: Mapping[str, object],
    documents: Sequence[LoadedDocument],
) -> tuple[list[LoadedDocument], list[ValidationProblem]]:
    if data.get("artifact_type") != "plan-diff":
        return [], []
    payload = data["payload"]
    assert isinstance(payload, Mapping)
    previous_matches: list[LoadedDocument] = []
    new_matches: list[LoadedDocument] = []
    for document in documents:
        candidate = document.data
        assert isinstance(candidate, Mapping)
        candidate_payload = candidate["payload"]
        assert isinstance(candidate_payload, Mapping)
        if candidate["artifact_type"] == "previous-plan" and candidate_payload.get("previous_plan_id") == payload.get("previous_plan_id"):
            previous_matches.append(document)
        if candidate["artifact_type"] == "plan" and candidate_payload.get("plan_id") == payload.get("new_plan_id"):
            new_matches.append(document)
    problems: list[ValidationProblem] = []
    path = ""
    if len(previous_matches) != 1:
        code = "UNRESOLVED_PLAN_VERSION_ENTITY" if not previous_matches else "AMBIGUOUS_PLAN_VERSION_ENTITY"
        problems.append(_problem(code, path, "/payload/previous_plan_id", "planVersionReference", expected="one previous-plan version", actual=payload.get("previous_plan_id")))
    if len(new_matches) != 1:
        code = "UNRESOLVED_PLAN_VERSION_ENTITY" if not new_matches else "AMBIGUOUS_PLAN_VERSION_ENTITY"
        problems.append(_problem(code, path, "/payload/new_plan_id", "planVersionReference", expected="one new plan version", actual=payload.get("new_plan_id")))
    if problems:
        return [], problems
    return [previous_matches[0], new_matches[0]], []


def _plan_version_entity_problems(
    document: LoadedDocument,
    previous: LoadedDocument,
    new: LoadedDocument,
) -> list[ValidationProblem]:
    data = document.data
    assert isinstance(data, Mapping)
    payload = data["payload"]
    assert isinstance(payload, Mapping)
    previous_data = previous.data
    new_data = new.data
    assert isinstance(previous_data, Mapping)
    assert isinstance(new_data, Mapping)
    previous_defs = {
        (kind, entity_id)
        for kind, entity_id, _ in _previous_local_definitions(previous_data)
    }
    new_defs = {
        (item.kind, item.entity_id)
        for item in _definitions(new_data)
        if item.kind in {"base_selection", "day", "activity", "leg"}
    }
    problems: list[ValidationProblem] = []
    for index, change in enumerate(payload.get("changes", [])):
        entity = change["entity"]
        key = (entity["entity_kind"], entity["entity_id"])
        scope = entity["resolution_scope"]
        previous_count = int(key in previous_defs)
        new_count = int(key in new_defs)
        valid = (
            (scope == "previous" and previous_count == 1)
            or (scope == "new" and new_count == 1)
            or (scope == "either" and previous_count + new_count >= 1)
        )
        if not valid:
            problems.append(_problem("UNRESOLVED_PLAN_VERSION_ENTITY", str(document.path), f"/payload/changes/{index}/entity/entity_id", "planVersionReference", expected=scope, actual=entity["entity_id"]))
    return problems


def validate_bundle(
    documents: Sequence[LoadedDocument],
    registry: SchemaRegistry,
    *,
    closure: BundleClosure,
    root_artifact_id: str,
) -> ValidationResult[ValidatedBundle]:
    validated: list[ValidatedArtifact] = []
    problems: list[ValidationProblem] = []
    for document in documents:
        result = validate_artifact(document, registry)
        if result.problems:
            problems.extend(result.problems)
        elif result.value is not None:
            validated.append(result.value)
    if problems:
        return ValidationResult(None, _ordered(problems))
    by_artifact: dict[str, list[ValidatedArtifact]] = {}
    for item in validated:
        by_artifact.setdefault(item.artifact_id, []).append(item)
    for artifact, items in by_artifact.items():
        if len(items) > 1:
            for duplicate in items[1:]:
                problems.append(_problem("DUPLICATE_ARTIFACT_ID", str(duplicate.document.path), "/artifact_id", "uniqueArtifact", expected="unique artifact_id", actual=artifact))
    if problems:
        return ValidationResult(None, _ordered(problems))
    root_items = by_artifact.get(root_artifact_id, [])
    if len(root_items) != 1:
        return ValidationResult(
            None,
            (_problem("UNRESOLVED_BUNDLE_ROOT", "", "", "bundleRoot", expected="one explicit artifact root", actual=root_artifact_id),),
        )
    validated_ids = tuple(sorted(item.artifact_id for item in validated))
    if closure == BundleClosure.ARTIFACT_ONLY:
        return ValidationResult(
            ValidatedBundle(
                closure=closure,
                root_artifact_id=root_artifact_id,
                validated_artifact_ids=validated_ids,
                resolved_artifact_ids=(),
            ),
            (),
        )
    if closure != BundleClosure.CLOSED:
        raise ValidatorInternalError("unsupported bundle closure")

    all_definitions: dict[str, list[_Definition]] = {}
    document_by_artifact: dict[str, LoadedDocument] = {}
    for item in validated:
        document_by_artifact[item.artifact_id] = item.document
        data = item.document.data
        assert isinstance(data, Mapping)
        for definition in _definitions(data):
            all_definitions.setdefault(definition.entity_id, []).append(definition)
    for entity_id, definitions in all_definitions.items():
        if len(definitions) > 1:
            for duplicate in definitions[1:]:
                owner = document_by_artifact[duplicate.artifact_id]
                problems.append(_problem("DUPLICATE_DEFINITION_ID", str(owner.path), duplicate.pointer, "uniqueDefinition", expected=definitions[0].kind, actual=entity_id))
    if problems:
        return ValidationResult(None, _ordered(problems))

    reachable: set[str] = {root_artifact_id}
    version_pairs: dict[str, tuple[LoadedDocument, LoadedDocument]] = {}
    changed = True
    while changed and not problems:
        changed = False
        for artifact in sorted(tuple(reachable)):
            document = document_by_artifact[artifact]
            data = document.data
            assert isinstance(data, Mapping)
            artifact_reference_failed = False
            for reference in _artifact_references(data):
                target_id = reference.value.get("artifact_id")
                targets = by_artifact.get(str(target_id), [])
                if not targets:
                    if reference.required:
                        problems.append(_problem("UNRESOLVED_REFERENCE", str(document.path), reference.pointer, "closedReference", expected=reference.expected_type, actual=target_id))
                        artifact_reference_failed = True
                        break
                    continue
                target = targets[0]
                target_data = target.document.data
                assert isinstance(target_data, Mapping)
                target_integrity = target_data["integrity"]
                assert isinstance(target_integrity, Mapping)
                compatible = (
                    target.artifact_type == reference.expected_type
                    and reference.value.get("artifact_type") == reference.expected_type
                    and str(reference.value.get("schema_version", "")).split(".", 1)[0] == str(target_data.get("schema_version", "")).split(".", 1)[0]
                    and reference.value.get("payload_sha256") == target_integrity.get("payload_sha256")
                )
                if not compatible:
                    problems.append(_problem("REFERENCE_KIND_MISMATCH", str(document.path), reference.pointer, "referenceIdentity", expected=reference.expected_type, actual=reference.value))
                    artifact_reference_failed = True
                    break
                if target.artifact_id not in reachable:
                    reachable.add(target.artifact_id)
                    changed = True
            if artifact_reference_failed:
                continue
            for reference in _entity_references(data):
                definitions = all_definitions.get(reference.entity_id, [])
                compatible = [item for item in definitions if item.kind == reference.expected_kind]
                if not compatible:
                    code = "REFERENCE_KIND_MISMATCH" if definitions else "UNRESOLVED_REFERENCE"
                    problems.append(_problem(code, str(document.path), reference.pointer, "closedReference", expected=reference.expected_kind, actual=reference.entity_id))
                    continue
                target_artifact = compatible[0].artifact_id
                if target_artifact not in reachable:
                    reachable.add(target_artifact)
                    changed = True
            if data["artifact_type"] == "plan-diff":
                dependencies, dependency_problems = _version_documents(data, documents)
                for dependency_problem in dependency_problems:
                    problems.append(
                        ValidationProblem(
                            dependency_problem.error_code,
                            str(document.path),
                            dependency_problem.json_pointer,
                            dependency_problem.schema_rule,
                            dependency_problem.expected,
                            dependency_problem.actual_type,
                            dependency_problem.message,
                        )
                    )
                if not dependency_problems:
                    version_pairs[artifact] = (dependencies[0], dependencies[1])
                    for dependency in dependencies:
                        dependency_data = dependency.data
                        assert isinstance(dependency_data, Mapping)
                        dependency_id = str(dependency_data["artifact_id"])
                        if dependency_id not in reachable:
                            reachable.add(dependency_id)
                            changed = True
    if problems:
        return ValidationResult(None, _ordered(problems))

    for artifact, pair in version_pairs.items():
        problems.extend(
            _plan_version_entity_problems(
                document_by_artifact[artifact],
                pair[0],
                pair[1],
            )
        )
    for artifact in sorted(reachable):
        document = document_by_artifact[artifact]
        data = document.data
        assert isinstance(data, Mapping)
        if data["artifact_type"] == "violations":
            payload = data["payload"]
            assert isinstance(payload, Mapping)
            if payload["evaluation_stage"] == "post_plan":
                ref = payload["plan_ref"]
                target = document_by_artifact.get(str(ref["artifact_id"]))
                if target is not None:
                    target_data = target.data
                    assert isinstance(target_data, Mapping)
                    target_payload = target_data["payload"]
                    assert isinstance(target_payload, Mapping)
                    if payload["plan_status"] != target_payload["plan_status"]:
                        problems.append(_problem("PLAN_STATUS_MISMATCH", str(document.path), "/payload/plan_status", "statusConsistency", expected="referenced plan status", actual=payload["plan_status"]))
    if problems:
        return ValidationResult(None, _ordered(problems))

    extra = sorted(set(document_by_artifact) - reachable)
    for artifact in extra:
        document = document_by_artifact[artifact]
        problems.append(_problem("UNEXPECTED_BUNDLE_ARTIFACT", str(document.path), "/artifact_id", "rootReachability", expected="root-reachable artifact", actual=artifact))
    if problems:
        return ValidationResult(None, _ordered(problems))
    return ValidationResult(
        ValidatedBundle(
            closure=closure,
            root_artifact_id=root_artifact_id,
            validated_artifact_ids=validated_ids,
            resolved_artifact_ids=tuple(sorted(reachable)),
        ),
        (),
    )
