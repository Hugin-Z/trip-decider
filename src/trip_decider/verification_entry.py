"""Complete, deterministic verification entry for the frozen WU1 surface.

This module orchestrates structural validators and repository checks.  It does
not implement travel semantics, inference, routing, optimization, or repair.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import io
import json
import os
import re
import site
import subprocess
import sys
import unittest
from urllib.parse import urljoin
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, TextIO

from .fixture_validation import (
    validate_fixture_directory,
    validate_fixture_manifest,
)
from .schema_validation import (
    ValidationProblem,
    ValidatorInternalError,
    load_document,
    validate_schema_registry,
)


WU1_START = "21d8508a8f96472ecc4d7f798cdd6af3d7f54f68"
WU1_FINAL = "80395c24612056eff6ff07f81eb3ac5df8c1660b"
EXPECTED_SCHEMA_COUNT = 11
EXPECTED_TEST_COUNT = 82
EXPECTED_FIXTURE_COUNT = 6
EXPECTED_DOCUMENT_COUNT = 38
EXPECTED_DIRTY_CASE_COUNT = 6

FROZEN_HASHES = {
    "PLAN.md": "563692C54D91F431C4CF5D92FCBA6BB1CCE2DDB60857E79EEED6081D481D5456",
    "plans/work-unit-0-bootstrap-d0.md": (
        "4C7FE14CD5D2CE0CC8E8D624D93C24338EAF61A9DBC0778D101AB3565602DE3B"
    ),
    "docs/architecture.md": (
        "CA5B6F7D345E11623C94C13CDD73C0E774282AFD88F9E2E036035ED2396BB6F4"
    ),
    "docs/artifact-contracts.md": (
        "695C0AC6738B71852DC60ADAFD2A98B974C5EC65BB744D19B0E22EC3550497BF"
    ),
    "docs/prior-art.md": (
        "C1195E816DB5F21FE83B4208B6258BA9F138C9AB9404373A132CE75C457893E7"
    ),
    "docs/handbook-context.md": (
        "1933DBA1B3697A394EDCC0238B60A032A18EA10B920F8C4358169490492115EB"
    ),
    "docs/reviews/work-unit-0-review.md": (
        "D93373ECC7398DEE95FFCC04E0143DE80612B4FE948FD36282FA98F793477128"
    ),
    "plans/work-unit-1-contracts-fixtures.md": (
        "B1C2517EE7B9579EFA85C5998FA5E29170589A650CBB051F1F5C00400EB39212"
    ),
}

ORIGINAL_WU1_PATHS = frozenset(
    {
        "docs/reviews/work-unit-1-review.md",
        "fixtures/README.md",
        "fixtures/fixture_01_feasible/README.md",
        "fixtures/fixture_01_feasible/case.json",
        "fixtures/fixture_02_direct_conflict/README.md",
        "fixtures/fixture_02_direct_conflict/case.json",
        "fixtures/fixture_03_uncertain_dependency/README.md",
        "fixtures/fixture_03_uncertain_dependency/case.json",
        "fixtures/fixture_04_replan_stability/README.md",
        "fixtures/fixture_04_replan_stability/case.json",
        "fixtures/fixture_05_evidence_state_mapping/README.md",
        "fixtures/fixture_05_evidence_state_mapping/case.json",
        "fixtures/fixture_06_no_plan_found_not_infeasible/README.md",
        "fixtures/fixture_06_no_plan_found_not_infeasible/case.json",
        "plans/work-unit-1-contracts-fixtures.md",
        "pyproject.toml",
        "requirements.lock",
        "schemas/candidates.schema.json",
        "schemas/common.schema.json",
        "schemas/constraint-parse.schema.json",
        "schemas/constraints.schema.json",
        "schemas/evidence.schema.json",
        "schemas/fixture-case.schema.json",
        "schemas/plan-diff.schema.json",
        "schemas/plan.schema.json",
        "schemas/previous-plan.schema.json",
        "schemas/request.schema.json",
        "schemas/trip-card.contract.md",
        "schemas/violations.schema.json",
        "scripts/verify_wu1.ps1",
        "src/trip_decider/__init__.py",
        "src/trip_decider/fixture_validation.py",
        "src/trip_decider/schema_validation.py",
        "tests/__init__.py",
        "tests/test_fixture_validation.py",
        "tests/test_schema_validation.py",
    }
)

WU1R_PATHS = frozenset(
    {
        "docs/reviews/work-unit-1-remediation-review.md",
        "plans/work-unit-1-remediation.md",
        "scripts/verify_wu1.ps1",
        "src/trip_decider/verification_entry.py",
        "tests/wu1r_verify_entry_cases.py",
    }
)

INPUT_CODES = frozenset(
    {
        "DUPLICATE_MAPPING_KEY",
        "INPUT_READ_ERROR",
        "INVALID_JSON",
        "INVALID_JSON_CONSTANT",
        "INVALID_UTF8",
        "INVALID_YAML",
        "NON_STRING_MAPPING_KEY",
        "UNSUPPORTED_MEDIA_TYPE",
        "UTF8_BOM_NOT_ALLOWED",
    }
)

FIXTURE_CODES = frozenset(
    {
        "DUPLICATE_FIXTURE_CASE_ID",
        "DUPLICATE_FIXTURE_DOCUMENT_PATH",
        "ENTRY_FIXTURE_CONTRACT_MISMATCH",
        "FIXTURE_CONTENT_NOT_CANONICAL",
        "FIXTURE_EXPECTATION_MISMATCH",
        "FIXTURE_FILE_HASH_MISMATCH",
        "FIXTURE_MUTATION_ERROR",
        "FIXTURE_MUTATION_TARGET_NOT_FOUND",
        "FIXTURE_SCHEMA_ID_MISMATCH",
        "FIXTURE_SCHEMA_VALIDATION_ERROR",
        "UNSAFE_FIXTURE_PATH",
    }
)

ARTIFACT_CODES = frozenset(
    {
        "AMBIGUOUS_PLAN_VERSION_ENTITY",
        "ARTIFACT_TYPE_MISMATCH",
        "DUPLICATE_ARTIFACT_ID",
        "DUPLICATE_DEFINITION_ID",
        "DUPLICATE_LOCAL_SOURCE_ID",
        "ENTRY_FROZEN_HASH_MISMATCH",
        "ENTRY_SCHEMA_COUNT_MISMATCH",
        "PAYLOAD_HASH_MISMATCH",
        "PLAN_STATUS_MISMATCH",
        "REFERENCE_KIND_MISMATCH",
        "SCHEMA_VALIDATION_ERROR",
        "UNEXPECTED_BUNDLE_ARTIFACT",
        "UNKNOWN_SCHEMA_MAJOR",
        "UNRESOLVED_BUNDLE_ROOT",
        "UNRESOLVED_LOCAL_SOURCE_REFERENCE",
        "UNRESOLVED_PLAN_VERSION_ENTITY",
        "UNRESOLVED_REFERENCE",
    }
)

INTERNAL_CODES = frozenset(
    {
        "ENTRY_FALLBACK_SCAN_HIT",
        "ENTRY_GIT_ERROR",
        "ENTRY_INTERNAL_ERROR",
        "ENTRY_LOCK_FORMAT_ERROR",
        "ENTRY_LOCK_MISMATCH",
        "ENTRY_PIP_CHECK_FAILED",
        "ENTRY_REGISTRY_INTERNAL_ERROR",
        "ENTRY_RUNTIME_IDENTITY_ERROR",
        "ENTRY_SCAN_PARSE_ERROR",
        "ENTRY_SCOPE_VIOLATION",
        "ENTRY_SECRET_SCAN_HIT",
        "ENTRY_UNITTEST_FAILED",
        "ENTRY_UNITTEST_COUNT_MISMATCH",
        "ENTRY_UNCLASSIFIED_PROBLEM",
    }
)

ENTRY_MESSAGES = {
    "ENTRY_FALLBACK_SCAN_HIT": "Suspicious fallback behavior was detected.",
    "ENTRY_FROZEN_HASH_MISMATCH": "A frozen input hash does not match.",
    "ENTRY_GIT_ERROR": "Required Git verification could not be completed.",
    "ENTRY_INTERNAL_ERROR": "The verification entry failed internally.",
    "ENTRY_LOCK_FORMAT_ERROR": "The lock file is not in the strict format.",
    "ENTRY_LOCK_MISMATCH": "The runtime package set does not match the lock.",
    "ENTRY_PIP_CHECK_FAILED": "The locked environment failed its health check.",
    "ENTRY_REGISTRY_INTERNAL_ERROR": "Schema registry verification failed internally.",
    "ENTRY_RUNTIME_IDENTITY_ERROR": "The runtime is not the project virtual environment.",
    "ENTRY_SCAN_PARSE_ERROR": "A source file could not be scanned safely.",
    "ENTRY_SCHEMA_COUNT_MISMATCH": "The frozen Schema count does not match.",
    "ENTRY_SCOPE_VIOLATION": "A repository path is outside the approved scope.",
    "ENTRY_SECRET_SCAN_HIT": "A credential-shaped value was detected.",
    "ENTRY_UNITTEST_COUNT_MISMATCH": "The frozen unittest count does not match.",
    "ENTRY_UNITTEST_FAILED": "The frozen unittest discovery failed.",
    "ENTRY_UNCLASSIFIED_PROBLEM": "A validation problem has no approved classification.",
    "ENTRY_FIXTURE_CONTRACT_MISMATCH": "The frozen fixture surface does not match.",
}


class VerificationDependencies(Protocol):
    """Explicit dependency boundary used by deterministic contract tests."""

    def runtime_snapshot(self) -> Mapping[str, object]: ...

    def read_lock(self, path: Path) -> bytes: ...

    def run_pip_check(self) -> int: ...

    def check_schemas(self, root: Path) -> Mapping[str, object]: ...

    def run_unittest_discovery(self, root: Path) -> Mapping[str, object]: ...

    def check_fixtures(
        self,
        root: Path,
        registry: object,
    ) -> Mapping[str, object]: ...

    def scope_snapshot(self, root: Path) -> Mapping[str, object]: ...

    def source_files(self, root: Path) -> Mapping[str, str]: ...

    def frozen_hashes(
        self,
        root: Path,
        expected_paths: tuple[str, ...],
    ) -> Mapping[str, str]: ...


class _InputSurfaceError(RuntimeError):
    def __init__(self, problem: ValidationProblem) -> None:
        super().__init__("input surface error")
        self.problem = problem


def _entry_problem(
    code: str,
    path: str,
    rule: str,
    *,
    pointer: str = "",
    expected: str = "",
    actual_type: str = "",
) -> ValidationProblem:
    return ValidationProblem(
        error_code=code,
        artifact_path=path,
        json_pointer=pointer,
        schema_rule=rule,
        expected=expected,
        actual_type=actual_type,
        message=ENTRY_MESSAGES.get(code, "Verification failed."),
    )


def _resolved(path: Path) -> Path:
    return Path(os.path.abspath(os.path.normpath(str(path))))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((_resolved(path), _resolved(parent))) == str(
            _resolved(parent)
        )
    except (OSError, ValueError):
        return False


def _relative_artifact_path(value: str, root: Path) -> str:
    if not value:
        return ""
    candidate = Path(value)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return "external-input"


def _safe_problem(problem: ValidationProblem, root: Path) -> ValidationProblem:
    return ValidationProblem(
        error_code=problem.error_code,
        artifact_path=_relative_artifact_path(problem.artifact_path, root),
        json_pointer=problem.json_pointer,
        schema_rule=problem.schema_rule,
        expected=problem.expected,
        actual_type=problem.actual_type,
        message=problem.message,
    )


def _problem_exit_code(code: str) -> int | None:
    if code in INTERNAL_CODES:
        return 5
    if code in INPUT_CODES:
        return 4
    if code in ARTIFACT_CODES:
        return 2
    if code in FIXTURE_CODES:
        return 3
    return None


def _normalize_problems(
    problems: Sequence[ValidationProblem],
    root: Path,
) -> tuple[ValidationProblem, ...]:
    normalized: list[ValidationProblem] = []
    for raw_problem in problems:
        problem = _safe_problem(raw_problem, root)
        if _problem_exit_code(problem.error_code) is None:
            problem = _entry_problem(
                "ENTRY_UNCLASSIFIED_PROBLEM",
                problem.artifact_path,
                "problemClassification",
                pointer=problem.json_pointer,
                actual_type="validation-problem",
            )
        normalized.append(problem)
    return tuple(
        sorted(
            normalized,
            key=lambda item: (
                item.artifact_path,
                item.json_pointer,
                item.error_code,
            ),
        )
    )


def _exit_for_problems(problems: Sequence[ValidationProblem]) -> int:
    codes = {_problem_exit_code(problem.error_code) for problem in problems}
    for candidate in (5, 4, 2, 3):
        if candidate in codes:
            return candidate
    return 5


def _problem_json(problem: ValidationProblem) -> str:
    value = {
        "error_code": problem.error_code,
        "artifact_path": problem.artifact_path,
        "json_pointer": problem.json_pointer,
        "schema_rule": problem.schema_rule,
        "expected": problem.expected,
        "actual_type": problem.actual_type,
        "message": problem.message,
    }
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _fail(
    problems: Sequence[ValidationProblem],
    root: Path,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    normalized = _normalize_problems(problems, root)
    code = _exit_for_problems(normalized)
    stdout.write(f"WU1 verification FAIL: exit={code} problems={len(normalized)}\n")
    for problem in normalized:
        stderr.write(_problem_json(problem) + "\n")
    return code


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _parse_lock(raw: bytes) -> tuple[dict[str, str] | None, ValidationProblem | None]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return None, _entry_problem(
            "UTF8_BOM_NOT_ALLOWED",
            "requirements.lock",
            "utf8",
        )
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, _entry_problem(
            "INVALID_UTF8",
            "requirements.lock",
            "utf8",
        )
    pattern = re.compile(
        r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)=="
        r"(?P<version>[A-Za-z0-9][A-Za-z0-9.!+_-]*)$"
    )
    values: dict[str, str] = {}
    lines = text.splitlines()
    if not lines:
        return None, _entry_problem(
            "ENTRY_LOCK_FORMAT_ERROR",
            "requirements.lock",
            "strictLock",
            expected="one name==version entry per line",
            actual_type="text",
        )
    for line in lines:
        match = pattern.fullmatch(line)
        if match is None:
            return None, _entry_problem(
                "ENTRY_LOCK_FORMAT_ERROR",
                "requirements.lock",
                "strictLock",
                expected="one name==version entry per line",
                actual_type="text",
            )
        name = _canonical_name(match.group("name"))
        if name in values:
            return None, _entry_problem(
                "ENTRY_LOCK_FORMAT_ERROR",
                "requirements.lock",
                "uniquePackageName",
                expected="unique canonical package names",
                actual_type="package-name",
            )
        values[name] = match.group("version")
    return values, None


def _runtime_problem(
    root: Path,
    snapshot: Mapping[str, object],
) -> ValidationProblem | None:
    venv = _resolved(root / ".venv")
    expected_python = _resolved(venv / "Scripts" / "python.exe")
    try:
        executable = _resolved(Path(snapshot["executable"]))
        prefix = _resolved(Path(snapshot["prefix"]))
        site_packages = tuple(Path(item) for item in snapshot["site_packages"])
        distributions = tuple(snapshot["distributions"])
    except (KeyError, TypeError, ValueError):
        return _entry_problem(
            "ENTRY_RUNTIME_IDENTITY_ERROR",
            ".venv",
            "runtimeSnapshot",
            expected="complete project virtual environment identity",
            actual_type="runtime-snapshot",
        )
    if executable != expected_python or prefix != venv:
        return _entry_problem(
            "ENTRY_RUNTIME_IDENTITY_ERROR",
            ".venv",
            "runtimeIdentity",
            expected="project .venv executable and prefix",
            actual_type="path",
        )
    if not site_packages or any(
        not _is_within(path, venv) for path in site_packages
    ):
        return _entry_problem(
            "ENTRY_RUNTIME_IDENTITY_ERROR",
            ".venv",
            "sitePackagesIdentity",
            expected="all site-packages inside project .venv",
            actual_type="path-list",
        )
    for distribution in distributions:
        if not isinstance(distribution, Mapping):
            return _entry_problem(
                "ENTRY_RUNTIME_IDENTITY_ERROR",
                ".venv",
                "distributionIdentity",
                expected="all distributions inside project .venv",
                actual_type="distribution-list",
            )
        location = distribution.get("location")
        if not isinstance(location, Path) or not _is_within(location, venv):
            return _entry_problem(
                "ENTRY_RUNTIME_IDENTITY_ERROR",
                ".venv",
                "distributionIdentity",
                expected="all distributions inside project .venv",
                actual_type="path-list",
            )
    return None


def _runtime_packages(
    snapshot: Mapping[str, object],
) -> dict[str, str] | None:
    values: dict[str, str] = {}
    distributions = snapshot.get("distributions")
    if not isinstance(distributions, Sequence):
        return None
    for distribution in distributions:
        if not isinstance(distribution, Mapping):
            return None
        name = distribution.get("name")
        version = distribution.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            return None
        canonical = _canonical_name(name)
        if canonical in {"pip", "setuptools"}:
            continue
        if canonical in values:
            return None
        values[canonical] = version
    return values


def _scan_python_names(
    path: str,
    text: str,
) -> tuple[ValidationProblem, ...]:
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:
        return (
            _entry_problem(
                "ENTRY_SCAN_PARSE_ERROR",
                path,
                "pythonAst",
                actual_type="python-source",
            ),
        )
    prefixes = (
        "infer" + "_",
        "guess" + "_",
        "default" + "_when_" + "missing",
    )
    problems: list[ValidationProblem] = []
    for node in ast.walk(tree):
        name = ""
        actual_type = ""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            actual_type = "function-name"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            actual_type = "call-name"
        if name.startswith(prefixes):
            problems.append(
                _entry_problem(
                    "ENTRY_FALLBACK_SCAN_HIT",
                    path,
                    "suspiciousName",
                    actual_type=actual_type,
                )
            )
    return tuple(problems)


def _scan_fallbacks(files: Mapping[str, str]) -> tuple[ValidationProblem, ...]:
    raw_tokens = (
        "silent" + "_fallback",
        "default" + "_when_missing",
        "--" + "lenient",
    )
    warning_tokens = (
        "Write-" + "Warning",
        "warnings." + "warn",
        "logging." + "warning",
    )
    problems: list[ValidationProblem] = []
    for path in sorted(files):
        text = files[path]
        suffix = Path(path).suffix.lower()
        if suffix == ".py":
            problems.extend(_scan_python_names(path, text))
        if suffix in {".py", ".ps1"}:
            if any(token in text for token in raw_tokens + warning_tokens):
                problems.append(
                    _entry_problem(
                        "ENTRY_FALLBACK_SCAN_HIT",
                        path,
                        "fallbackToken",
                        actual_type="source-token",
                    )
                )
        if path == "scripts/verify_wu1.ps1":
            forbidden = (
                "Invoke-" + "Expression",
                "python " + "-c",
                "powershell " + "-Command",
                "powershell.exe " + "-Command",
            )
            if any(token.lower() in text.lower() for token in forbidden):
                problems.append(
                    _entry_problem(
                        "ENTRY_FALLBACK_SCAN_HIT",
                        path,
                        "unsafePowerShellInvocation",
                        actual_type="source-token",
                    )
                )
            bare_python = re.compile(
                r"(?im)^\s*&\s*(?:python|py)(?:\.exe)?\b"
            )
            if bare_python.search(text):
                problems.append(
                    _entry_problem(
                        "ENTRY_FALLBACK_SCAN_HIT",
                        path,
                        "globalPythonFallback",
                        actual_type="command-name",
                    )
                )
    return tuple(problems)


def _scan_secrets(files: Mapping[str, str]) -> tuple[ValidationProblem, ...]:
    label = (
        r"(?i)(?<![A-Za-z0-9])(?:[A-Za-z0-9]+_)?"
        r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
        r"client[_-]?secret|password)\b"
    )
    patterns = (
        re.compile(label + r"\s*[:=]\s*[\"']?[A-Za-z0-9_./+\-]{16,}"),
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"https?://[^/\s:@]+:[^/\s@]+@"),
    )
    problems: list[ValidationProblem] = []
    for path in sorted(files):
        text = files[path]
        if any(pattern.search(text) for pattern in patterns):
            problems.append(
                _entry_problem(
                    "ENTRY_SECRET_SCAN_HIT",
                    path,
                    "credentialPattern",
                    actual_type="credential-pattern",
                )
            )
    return tuple(problems)


def _stage_problems(value: object) -> tuple[ValidationProblem, ...]:
    if not isinstance(value, Sequence):
        return ()
    return tuple(item for item in value if isinstance(item, ValidationProblem))


def run_verification(
    repo_root: Path,
    *,
    dependencies: VerificationDependencies,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Run all WU1 verification checks and return the stable exit code."""

    root = _resolved(Path(repo_root))
    try:
        runtime = dependencies.runtime_snapshot()
        problem = _runtime_problem(root, runtime)
        if problem is not None:
            return _fail((problem,), root, stdout, stderr)

        try:
            raw_lock = dependencies.read_lock(root / "requirements.lock")
        except _InputSurfaceError as error:
            return _fail((error.problem,), root, stdout, stderr)
        except (OSError, UnicodeError):
            return _fail(
                (
                    _entry_problem(
                        "INPUT_READ_ERROR",
                        "requirements.lock",
                        "file",
                    ),
                ),
                root,
                stdout,
                stderr,
            )
        lock, lock_problem = _parse_lock(raw_lock)
        if lock_problem is not None:
            return _fail((lock_problem,), root, stdout, stderr)
        runtime_packages = _runtime_packages(runtime)
        if lock is None or runtime_packages is None or runtime_packages != lock:
            return _fail(
                (
                    _entry_problem(
                        "ENTRY_LOCK_MISMATCH",
                        "requirements.lock",
                        "exactPackageSet",
                        expected="exact requirements.lock package set",
                        actual_type="package-set",
                    ),
                ),
                root,
                stdout,
                stderr,
            )

        if dependencies.run_pip_check() != 0:
            return _fail(
                (
                    _entry_problem(
                        "ENTRY_PIP_CHECK_FAILED",
                        "requirements.lock",
                        "pipCheck",
                        expected="healthy locked environment",
                        actual_type="process-exit",
                    ),
                ),
                root,
                stdout,
                stderr,
            )

        expected_paths = tuple(FROZEN_HASHES)
        try:
            actual_hashes = dependencies.frozen_hashes(root, expected_paths)
        except _InputSurfaceError as error:
            return _fail((error.problem,), root, stdout, stderr)
        missing_hash_paths = [
            path for path in expected_paths if path not in actual_hashes
        ]
        if missing_hash_paths:
            return _fail(
                tuple(
                    _entry_problem("INPUT_READ_ERROR", path, "file")
                    for path in missing_hash_paths
                ),
                root,
                stdout,
                stderr,
            )
        mismatches = [
            path
            for path in expected_paths
            if str(actual_hashes[path]).upper() != FROZEN_HASHES[path]
        ]
        if mismatches:
            return _fail(
                tuple(
                    _entry_problem(
                        "ENTRY_FROZEN_HASH_MISMATCH",
                        path,
                        "frozenSha256",
                        expected="approved frozen SHA256",
                        actual_type="string",
                    )
                    for path in mismatches
                ),
                root,
                stdout,
                stderr,
            )

        try:
            schema = dependencies.check_schemas(root)
        except ValidatorInternalError:
            return _fail(
                (
                    _entry_problem(
                        "ENTRY_REGISTRY_INTERNAL_ERROR",
                        "schemas",
                        "schemaRegistry",
                        actual_type="internal-error",
                    ),
                ),
                root,
                stdout,
                stderr,
            )
        schema_problems = _stage_problems(schema.get("problems"))
        if schema_problems:
            return _fail(schema_problems, root, stdout, stderr)
        if schema.get("schema_count") != EXPECTED_SCHEMA_COUNT:
            return _fail(
                (
                    _entry_problem(
                        "ENTRY_SCHEMA_COUNT_MISMATCH",
                        "schemas",
                        "schemaCount",
                        expected="11 schemas",
                        actual_type="integer",
                    ),
                ),
                root,
                stdout,
                stderr,
            )
        registry = schema.get("registry")
        if registry is None:
            return _fail(
                (
                    _entry_problem(
                        "ENTRY_REGISTRY_INTERNAL_ERROR",
                        "schemas",
                        "schemaRegistry",
                        actual_type="registry",
                    ),
                ),
                root,
                stdout,
                stderr,
            )

        tests = dependencies.run_unittest_discovery(root)
        test_problems = _stage_problems(tests.get("problems"))
        if test_problems:
            return _fail(test_problems, root, stdout, stderr)
        if tests.get("failures") != 0 or tests.get("errors") != 0:
            return _fail(
                (
                    _entry_problem(
                        "ENTRY_UNITTEST_FAILED",
                        "tests",
                        "unittestDiscovery",
                        expected="zero failures and errors",
                        actual_type="test-summary",
                    ),
                ),
                root,
                stdout,
                stderr,
            )
        if tests.get("tests") != EXPECTED_TEST_COUNT:
            return _fail(
                (
                    _entry_problem(
                        "ENTRY_UNITTEST_COUNT_MISMATCH",
                        "tests",
                        "unittestCount",
                        expected="82 tests",
                        actual_type="integer",
                    ),
                ),
                root,
                stdout,
                stderr,
            )

        fixtures = dependencies.check_fixtures(root, registry)
        fixture_problems = _stage_problems(fixtures.get("problems"))
        if fixture_problems:
            return _fail(fixture_problems, root, stdout, stderr)
        fixture_surface_matches = (
            fixtures.get("fixtures") == EXPECTED_FIXTURE_COUNT
            and fixtures.get("documents") == EXPECTED_DOCUMENT_COUNT
            and fixtures.get("dirty_cases") == EXPECTED_DIRTY_CASE_COUNT
            and tuple(fixtures.get("closures", ())) == ("closed",) * 6
            and len(tuple(fixtures.get("root_artifact_ids", ()))) == 6
            and all(fixtures.get("root_artifact_ids", ()))
        )
        if not fixture_surface_matches:
            return _fail(
                (
                    _entry_problem(
                        "ENTRY_FIXTURE_CONTRACT_MISMATCH",
                        "fixtures",
                        "fixtureSurface",
                        expected="6 closed fixtures, 38 documents, 6 dirty cases",
                        actual_type="fixture-summary",
                    ),
                ),
                root,
                stdout,
                stderr,
            )

        try:
            scope = dependencies.scope_snapshot(root)
        except ValidatorInternalError:
            return _fail(
                (
                    _entry_problem(
                        "ENTRY_GIT_ERROR",
                        ".git",
                        "gitScope",
                        actual_type="internal-error",
                    ),
                ),
                root,
                stdout,
                stderr,
            )
        original_paths = frozenset(scope.get("original_paths", ()))
        if original_paths != ORIGINAL_WU1_PATHS:
            return _fail(
                (
                    _entry_problem(
                        "ENTRY_SCOPE_VIOLATION",
                        "git:wu1-history",
                        "exactHistoricalPathSet",
                        expected="36 approved WU1 paths",
                        actual_type="path-set",
                    ),
                ),
                root,
                stdout,
                stderr,
            )
        remediation_paths = set(scope.get("remediation_paths", ()))
        worktree_paths = set(scope.get("worktree_paths", ()))
        untracked_paths = set(scope.get("untracked_paths", ()))
        combined = remediation_paths | worktree_paths | untracked_paths
        extras = sorted(combined - WU1R_PATHS)
        if extras:
            return _fail(
                tuple(
                    _entry_problem(
                        "ENTRY_SCOPE_VIOLATION",
                        path,
                        "wu1rPathWhitelist",
                        expected="approved WU1R path",
                        actual_type="repository-path",
                    )
                    for path in extras
                ),
                root,
                stdout,
                stderr,
            )

        try:
            source_files = dependencies.source_files(root)
        except _InputSurfaceError as error:
            return _fail((error.problem,), root, stdout, stderr)
        fallback_problems = _scan_fallbacks(source_files)
        if fallback_problems:
            return _fail(fallback_problems, root, stdout, stderr)
        secret_problems = _scan_secrets(source_files)
        if secret_problems:
            return _fail(secret_problems, root, stdout, stderr)

    except _InputSurfaceError as error:
        return _fail((error.problem,), root, stdout, stderr)
    except Exception:
        return _fail(
            (
                _entry_problem(
                    "ENTRY_INTERNAL_ERROR",
                    "verification-entry",
                    "internalInvariant",
                    actual_type="internal-error",
                ),
            ),
            root,
            stdout,
            stderr,
        )

    stdout.write(
        "WU1 verification PASS: "
        f"schemas={EXPECTED_SCHEMA_COUNT} "
        f"tests={tests['tests']} "
        f"fixtures={fixtures['fixtures']} "
        f"documents={fixtures['documents']} "
        f"dirty_cases={fixtures['dirty_cases']}\n"
    )
    return 0


def _walk_refs(value: object) -> Sequence[str]:
    refs: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "$ref" and isinstance(child, str):
                refs.append(child)
            else:
                refs.extend(_walk_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.extend(_walk_refs(child))
    return refs


def _command(
    arguments: Sequence[str],
    *,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(arguments),
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="strict",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
        )
    except (OSError, UnicodeError) as error:
        raise ValidatorInternalError("required command failed") from error


class RealVerificationDependencies:
    """Real, fail-closed observations for the single verification entry."""

    def runtime_snapshot(self) -> Mapping[str, object]:
        distributions: list[dict[str, object]] = []
        for distribution in importlib.metadata.distributions():
            name = distribution.metadata.get("Name")
            if not isinstance(name, str):
                raise ValidatorInternalError("distribution name is absent")
            distributions.append(
                {
                    "name": name,
                    "version": distribution.version,
                    "location": Path(distribution.locate_file("")).resolve(),
                }
            )
        return {
            "executable": Path(sys.executable).resolve(),
            "prefix": Path(sys.prefix).resolve(),
            "site_packages": tuple(
                Path(value).resolve() for value in site.getsitepackages()
            ),
            "distributions": tuple(distributions),
        }

    def read_lock(self, path: Path) -> bytes:
        try:
            return path.read_bytes()
        except OSError as error:
            raise _InputSurfaceError(
                _entry_problem("INPUT_READ_ERROR", "requirements.lock", "file")
            ) from error

    def run_pip_check(self) -> int:
        result = _command(
            (sys.executable, "-m", "pip", "check"),
            cwd=Path.cwd(),
        )
        return result.returncode

    def check_schemas(self, root: Path) -> Mapping[str, object]:
        schema_paths = tuple(sorted((root / "schemas").glob("*.schema.json")))
        if len(schema_paths) != EXPECTED_SCHEMA_COUNT:
            return {
                "schema_count": len(schema_paths),
                "registry": None,
                "problems": (),
            }
        result = validate_schema_registry(schema_paths)
        if result.problems or result.value is None:
            return {
                "schema_count": len(schema_paths),
                "registry": None,
                "problems": result.problems,
            }
        registry = result.value
        metadata_problems: list[ValidationProblem] = []
        draft = "https://json-schema.org/draft/2020-12/schema"
        schema_ids = set(registry.schemas)
        for path in schema_paths:
            expected_id = None
            for schema_id, schema in registry.schemas.items():
                if isinstance(schema, Mapping) and schema.get("$id") == schema_id:
                    if schema_id.rsplit("/", 1)[-1] == path.name:
                        expected_id = schema_id
                        break
            if expected_id is None:
                metadata_problems.append(
                    _entry_problem(
                        "SCHEMA_VALIDATION_ERROR",
                        path.relative_to(root).as_posix(),
                        "schemaRegistry",
                    )
                )
                continue
            schema = registry.schemas[expected_id]
            if not isinstance(schema, Mapping) or schema.get("$schema") != draft:
                metadata_problems.append(
                    _entry_problem(
                        "SCHEMA_VALIDATION_ERROR",
                        path.relative_to(root).as_posix(),
                        "draft202012Metadata",
                        pointer="/$schema",
                        expected="Draft 2020-12",
                        actual_type="string",
                    )
                )
            for reference in _walk_refs(schema):
                resolved_base = urljoin(expected_id, reference).split("#", 1)[0]
                if resolved_base not in schema_ids:
                    metadata_problems.append(
                        _entry_problem(
                            "SCHEMA_VALIDATION_ERROR",
                            path.relative_to(root).as_posix(),
                            "localReference",
                            expected="preloaded local schema reference",
                            actual_type="reference",
                        )
                    )
        return {
            "schema_count": len(schema_paths),
            "registry": registry,
            "problems": tuple(metadata_problems),
        }

    def run_unittest_discovery(self, root: Path) -> Mapping[str, object]:
        loader = unittest.TestLoader()
        try:
            suite = loader.discover(
                start_dir=str(root / "tests"),
                pattern="test*.py",
                top_level_dir=str(root),
            )
            capture = io.StringIO()
            result = unittest.TextTestRunner(
                stream=capture,
                verbosity=2,
            ).run(suite)
        except Exception as error:
            raise ValidatorInternalError("unittest discovery failed") from error
        return {
            "tests": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "problems": (),
        }

    def check_fixtures(
        self,
        root: Path,
        registry: object,
    ) -> Mapping[str, object]:
        fixture_root = root / "fixtures"
        case_paths = tuple(sorted(fixture_root.glob("fixture_*/case.json")))
        problems: list[ValidationProblem] = []
        closures: list[str] = []
        roots: list[str] = []
        documents = 0
        dirty_cases = 0
        for case_path in case_paths:
            loaded = load_document(case_path)
            if loaded.problems or loaded.value is None:
                problems.extend(loaded.problems)
                continue
            manifest = loaded.value.data
            if not isinstance(manifest, Mapping):
                problems.append(
                    _entry_problem(
                        "FIXTURE_SCHEMA_VALIDATION_ERROR",
                        case_path.relative_to(root).as_posix(),
                        "type",
                        expected="object",
                        actual_type="non-object",
                    )
                )
                continue
            result = validate_fixture_manifest(manifest, registry)
            if result.problems or result.value is None:
                problems.extend(result.problems)
                continue
            closure = manifest.get("bundle_closure")
            root_artifact_id = manifest.get("root_artifact_id")
            if closure != "closed" or root_artifact_id != result.value.root_artifact_id:
                problems.append(
                    _entry_problem(
                        "ENTRY_FIXTURE_CONTRACT_MISMATCH",
                        case_path.relative_to(root).as_posix(),
                        "closedFixtureRoot",
                        expected="closed fixture with explicit actual root",
                        actual_type="fixture-manifest",
                    )
                )
                continue
            closures.append(str(closure))
            roots.append(result.value.root_artifact_id)
            documents += result.value.document_count
            dirty_cases += result.value.dirty_case_count
        directory = validate_fixture_directory(fixture_root, registry)
        if directory.problems or directory.value is None:
            problems.extend(directory.problems)
        elif (
            directory.value.fixture_count != len(case_paths)
            or directory.value.document_count != documents
            or directory.value.dirty_case_count != dirty_cases
        ):
            problems.append(
                _entry_problem(
                    "ENTRY_FIXTURE_CONTRACT_MISMATCH",
                    "fixtures",
                    "fixtureDirectorySummary",
                    expected="per-fixture and directory summaries match",
                    actual_type="fixture-summary",
                )
            )
        return {
            "fixtures": len(case_paths),
            "documents": documents,
            "dirty_cases": dirty_cases,
            "closures": tuple(closures),
            "root_artifact_ids": tuple(roots),
            "problems": tuple(problems),
        }

    def _git_lines(
        self,
        root: Path,
        arguments: Sequence[str],
    ) -> tuple[str, ...]:
        result = _command(("git", *arguments), cwd=root)
        if result.returncode != 0:
            raise ValidatorInternalError("Git verification failed")
        return tuple(line for line in result.stdout.splitlines() if line)

    def scope_snapshot(self, root: Path) -> Mapping[str, object]:
        original = self._git_lines(
            root,
            ("diff", "--name-only", f"{WU1_START}..{WU1_FINAL}"),
        )
        remediation = self._git_lines(
            root,
            ("diff", "--name-only", f"{WU1_FINAL}..HEAD"),
        )
        status_lines = self._git_lines(
            root,
            ("status", "--porcelain=v1", "--untracked-files=all"),
        )
        worktree: list[str] = []
        untracked: list[str] = []
        for line in status_lines:
            if len(line) < 4:
                raise ValidatorInternalError("Git status output is invalid")
            code = line[:2]
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            path = path.strip('"')
            worktree.append(path)
            if code == "??":
                untracked.append(path)
        return {
            "original_paths": original,
            "remediation_paths": remediation,
            "worktree_paths": tuple(worktree),
            "untracked_paths": tuple(untracked),
        }

    def source_files(self, root: Path) -> Mapping[str, str]:
        tracked = set(self._git_lines(root, ("ls-files",)))
        status = self.scope_snapshot(root)
        candidates = tracked | set(status["worktree_paths"]) | set(
            status["untracked_paths"]
        )
        values: dict[str, str] = {}
        for relative in sorted(candidates):
            path = root / relative
            if not path.is_file():
                raise _InputSurfaceError(
                    _entry_problem("INPUT_READ_ERROR", relative, "file")
                )
            try:
                raw = path.read_bytes()
                if raw.startswith(b"\xef\xbb\xbf"):
                    raise UnicodeError("BOM")
                values[relative] = raw.decode("utf-8", errors="strict")
            except (OSError, UnicodeError) as error:
                raise _InputSurfaceError(
                    _entry_problem("INVALID_UTF8", relative, "utf8")
                ) from error
        return values

    def frozen_hashes(
        self,
        root: Path,
        expected_paths: tuple[str, ...],
    ) -> Mapping[str, str]:
        values: dict[str, str] = {}
        for relative in expected_paths:
            path = root / relative
            try:
                values[relative] = hashlib.sha256(path.read_bytes()).hexdigest().upper()
            except OSError as error:
                raise _InputSurfaceError(
                    _entry_problem("INPUT_READ_ERROR", relative, "file")
                ) from error
        return values


def main() -> int:
    """Run the real WU1 verification entry without bypasses or repair."""

    return run_verification(
        Path.cwd(),
        dependencies=RealVerificationDependencies(),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
