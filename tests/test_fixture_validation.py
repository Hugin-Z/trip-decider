from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trip_decider import fixture_validation
from trip_decider.fixture_validation import (
    FixtureDirectorySummary,
    ValidatedFixtureManifest,
    validate_fixture_directory,
    validate_fixture_manifest,
)
from trip_decider.schema_validation import (
    BundleClosure,
    SchemaRegistry,
    ValidatedBundle,
    ValidationProblem,
    ValidationResult,
    validate_schema_registry,
)
from tests.test_schema_validation import (
    SCHEMA_IDS,
    SCHEMA_PATHS,
    entity_id,
    make_candidates,
    make_request,
)


def document_entry(
    document: dict[str, object],
    relative_path: str,
) -> dict[str, object]:
    content = json.dumps(
        document,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    encoded = content.encode("utf-8")
    artifact_type = str(document["artifact_type"])
    return {
        "relative_path": relative_path,
        "media_type": "application/json",
        "content_utf8": content,
        "file_sha256": hashlib.sha256(encoded).hexdigest(),
        "expected_schema_id": SCHEMA_IDS[artifact_type],
    }


def dirty_remove_natural_language(
    target_document: str = "request.json",
) -> dict[str, object]:
    return {
        "dirty_case_id": "remove-natural-language",
        "target_document": target_document,
        "operation": "remove",
        "json_pointer": "/payload/natural_language",
        "expected_error": {
            "error_code": "SCHEMA_VALIDATION_ERROR",
            "json_pointer": "/payload",
            "schema_rule": "required",
        },
    }


def artifact_only_manifest() -> dict[str, object]:
    request = make_request()
    return {
        "case_id": entity_id("case", 1),
        "case_version": "0.1.0",
        "fixture_type": "synthetic_deterministic",
        "bundle_closure": "artifact_only",
        "root_artifact_id": request["artifact_id"],
        "source": {
            "kind": "frozen_contract",
            "description": "Synthetic request fixed by the WU1 structural contract.",
        },
        "coverage": ["fixture manifest structural validation"],
        "non_coverage": ["travel feasibility"],
        "documents": [document_entry(request, "request.json")],
        "dirty_cases": [dirty_remove_natural_language()],
        "behavior_expected": {
            "deferred_to": "WU4",
            "spec": "No business behavior is executed in WU1.",
        },
    }


def closed_manifest(*, reverse_documents: bool = False) -> dict[str, object]:
    request = make_request()
    candidates = make_candidates(request)
    documents = [
        document_entry(request, "request.json"),
        document_entry(candidates, "candidates.json"),
    ]
    if reverse_documents:
        documents.reverse()
    manifest = artifact_only_manifest()
    manifest.update(
        {
            "case_id": entity_id("case", 2),
            "bundle_closure": "closed",
            "root_artifact_id": candidates["artifact_id"],
            "coverage": ["explicit closed root and root-reachable documents"],
            "documents": documents,
        }
    )
    return manifest


class FixtureContractTestCase(unittest.TestCase):
    registry: SchemaRegistry

    @classmethod
    def setUpClass(cls) -> None:
        result = validate_schema_registry(SCHEMA_PATHS)
        if result.value is None or result.problems:
            raise AssertionError(f"schema registry setup failed: {result.problems!r}")
        cls.registry = result.value

    def assert_manifest_success(
        self,
        result: ValidationResult[ValidatedFixtureManifest],
        *,
        case_id: str,
        root_artifact_id: str,
        document_count: int,
        dirty_case_count: int,
    ) -> None:
        self.assertEqual(result.problems, ())
        self.assertIsInstance(result.value, ValidatedFixtureManifest)
        self.assertEqual(result.value.case_id, case_id)
        self.assertEqual(result.value.root_artifact_id, root_artifact_id)
        self.assertEqual(result.value.document_count, document_count)
        self.assertEqual(result.value.dirty_case_count, dirty_case_count)

    def assert_problem(
        self,
        result: ValidationResult[object],
        code: str,
        pointer: str,
        rule: str,
    ) -> ValidationProblem:
        self.assertIsNone(result.value)
        self.assertGreaterEqual(len(result.problems), 1)
        problem = result.problems[0]
        self.assertEqual(problem.error_code, code)
        self.assertEqual(problem.json_pointer, pointer)
        self.assertEqual(problem.schema_rule, rule)
        return problem


class TestManifestSchemaAndEmbeddedBytes(FixtureContractTestCase):
    def test_fx_01_artifact_only_manifest_is_valid(self) -> None:
        manifest = artifact_only_manifest()
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_manifest_success(
            result,
            case_id=manifest["case_id"],
            root_artifact_id=manifest["root_artifact_id"],
            document_count=1,
            dirty_case_count=1,
        )

    def test_fx_02_missing_root_field_fails_manifest_schema(self) -> None:
        manifest = artifact_only_manifest()
        del manifest["root_artifact_id"]
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_problem(
            result,
            "FIXTURE_SCHEMA_VALIDATION_ERROR",
            "",
            "required",
        )

    def test_fx_03_invalid_closure_fails_manifest_schema(self) -> None:
        manifest = artifact_only_manifest()
        manifest["bundle_closure"] = "automatic"
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_problem(
            result,
            "FIXTURE_SCHEMA_VALIDATION_ERROR",
            "/bundle_closure",
            "enum",
        )

    def test_fx_04_root_must_exist_in_documents(self) -> None:
        manifest = artifact_only_manifest()
        manifest["root_artifact_id"] = "urn:uuid:ffffffff-ffff-4fff-8fff-ffffffffffff"
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_problem(
            result,
            "UNRESOLVED_BUNDLE_ROOT",
            "",
            "bundleRoot",
        )

    def test_fx_05_parent_segments_are_not_safe_relative_paths(self) -> None:
        manifest = artifact_only_manifest()
        manifest["documents"][0]["relative_path"] = "docs/../request.json"
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_problem(
            result,
            "UNSAFE_FIXTURE_PATH",
            "/documents/0/relative_path",
            "safeRelativePath",
        )

    def test_fx_06_exact_file_hash_is_required(self) -> None:
        manifest = artifact_only_manifest()
        manifest["documents"][0]["file_sha256"] = "0" * 64
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_problem(
            result,
            "FIXTURE_FILE_HASH_MISMATCH",
            "/documents/0/file_sha256",
            "fileHash",
        )

    def test_fx_07_expected_schema_id_must_match_artifact_type(self) -> None:
        manifest = artifact_only_manifest()
        manifest["documents"][0]["expected_schema_id"] = SCHEMA_IDS["candidates"]
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_problem(
            result,
            "FIXTURE_SCHEMA_ID_MISMATCH",
            "/documents/0/expected_schema_id",
            "schemaIdentity",
        )

    def test_fx_08_utf8_bom_is_rejected_in_embedded_content(self) -> None:
        manifest = artifact_only_manifest()
        item = manifest["documents"][0]
        item["content_utf8"] = "\ufeff" + item["content_utf8"]
        item["file_sha256"] = hashlib.sha256(item["content_utf8"].encode("utf-8")).hexdigest()
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_problem(
            result,
            "FIXTURE_CONTENT_NOT_CANONICAL",
            "/documents/0/content_utf8",
            "canonicalUtf8",
        )

    def test_fx_09_crlf_is_rejected_in_embedded_content(self) -> None:
        manifest = artifact_only_manifest()
        item = manifest["documents"][0]
        item["content_utf8"] = item["content_utf8"].replace("\n", "\r\n")
        item["file_sha256"] = hashlib.sha256(item["content_utf8"].encode("utf-8")).hexdigest()
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_problem(
            result,
            "FIXTURE_CONTENT_NOT_CANONICAL",
            "/documents/0/content_utf8",
            "canonicalUtf8",
        )


class TestClosureAndExplicitRoot(FixtureContractTestCase):
    def bundle_result_for(
        self,
        manifest: dict[str, object],
        closure: BundleClosure,
    ) -> tuple[ValidationResult[ValidatedFixtureManifest], object]:
        clean = ValidatedBundle(
            closure=closure,
            root_artifact_id=manifest["root_artifact_id"],
            validated_artifact_ids=(manifest["root_artifact_id"],),
            resolved_artifact_ids=(),
        )
        dirty_problem = ValidationProblem(
            error_code="SCHEMA_VALIDATION_ERROR",
            artifact_path="request.json",
            json_pointer="/payload",
            schema_rule="required",
            expected="required",
            actual_type="object",
            message="Structural validation failed.",
        )
        with patch.object(
            fixture_validation,
            "validate_bundle",
            create=True,
            side_effect=(
                ValidationResult(clean, ()),
                ValidationResult(None, (dirty_problem,)),
            ),
        ) as mocked:
            return validate_fixture_manifest(manifest, self.registry), mocked

    def test_fx_10_artifact_only_closure_and_root_are_forwarded_verbatim(self) -> None:
        manifest = artifact_only_manifest()
        result, mocked = self.bundle_result_for(manifest, BundleClosure.ARTIFACT_ONLY)
        self.assert_manifest_success(
            result,
            case_id=manifest["case_id"],
            root_artifact_id=manifest["root_artifact_id"],
            document_count=1,
            dirty_case_count=1,
        )
        self.assertEqual(mocked.call_count, 2)
        for call in mocked.call_args_list:
            self.assertEqual(call.kwargs["closure"], BundleClosure.ARTIFACT_ONLY)
            self.assertEqual(call.kwargs["root_artifact_id"], manifest["root_artifact_id"])

    def test_fx_11_closed_closure_and_root_are_forwarded_verbatim(self) -> None:
        manifest = closed_manifest(reverse_documents=True)
        result, mocked = self.bundle_result_for(manifest, BundleClosure.CLOSED)
        self.assert_manifest_success(
            result,
            case_id=manifest["case_id"],
            root_artifact_id=manifest["root_artifact_id"],
            document_count=2,
            dirty_case_count=1,
        )
        self.assertEqual(mocked.call_count, 2)
        for call in mocked.call_args_list:
            self.assertEqual(call.kwargs["closure"], BundleClosure.CLOSED)
            self.assertEqual(call.kwargs["root_artifact_id"], manifest["root_artifact_id"])

    def test_fx_12_document_order_does_not_select_or_change_root(self) -> None:
        forward = closed_manifest()
        reverse = closed_manifest(reverse_documents=True)
        forward_result = validate_fixture_manifest(forward, self.registry)
        reverse_result = validate_fixture_manifest(reverse, self.registry)
        self.assert_manifest_success(
            forward_result,
            case_id=forward["case_id"],
            root_artifact_id=forward["root_artifact_id"],
            document_count=2,
            dirty_case_count=1,
        )
        self.assert_manifest_success(
            reverse_result,
            case_id=reverse["case_id"],
            root_artifact_id=reverse["root_artifact_id"],
            document_count=2,
            dirty_case_count=1,
        )
        self.assertEqual(
            forward_result.value.root_artifact_id,
            reverse_result.value.root_artifact_id,
        )


class TestSingleMutationAndExpectedError(FixtureContractTestCase):
    def test_fx_13_remove_mutation_matches_exact_expected_error(self) -> None:
        manifest = artifact_only_manifest()
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_manifest_success(
            result,
            case_id=manifest["case_id"],
            root_artifact_id=manifest["root_artifact_id"],
            document_count=1,
            dirty_case_count=1,
        )

    def test_fx_14_add_mutation_matches_exact_expected_error(self) -> None:
        manifest = artifact_only_manifest()
        manifest["dirty_cases"] = [
            {
                "dirty_case_id": "add-unknown-payload-field",
                "target_document": "request.json",
                "operation": "add",
                "json_pointer": "/payload/unexpected",
                "value": "forbidden",
                "expected_error": {
                    "error_code": "SCHEMA_VALIDATION_ERROR",
                    "json_pointer": "/payload",
                    "schema_rule": "additionalProperties",
                },
            }
        ]
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_manifest_success(
            result,
            case_id=manifest["case_id"],
            root_artifact_id=manifest["root_artifact_id"],
            document_count=1,
            dirty_case_count=1,
        )

    def test_fx_15_replace_mutation_matches_exact_expected_error(self) -> None:
        manifest = artifact_only_manifest()
        manifest["dirty_cases"] = [
            {
                "dirty_case_id": "replace-natural-language-type",
                "target_document": "request.json",
                "operation": "replace",
                "json_pointer": "/payload/natural_language",
                "value": 42,
                "expected_error": {
                    "error_code": "SCHEMA_VALIDATION_ERROR",
                    "json_pointer": "/payload/natural_language",
                    "schema_rule": "type",
                },
            }
        ]
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_manifest_success(
            result,
            case_id=manifest["case_id"],
            root_artifact_id=manifest["root_artifact_id"],
            document_count=1,
            dirty_case_count=1,
        )

    def test_fx_16_expected_error_mismatch_fails_explicitly(self) -> None:
        manifest = artifact_only_manifest()
        manifest["dirty_cases"][0]["expected_error"]["json_pointer"] = "/payload/wrong"
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_problem(
            result,
            "FIXTURE_EXPECTATION_MISMATCH",
            "/dirty_cases/0/expected_error",
            "expectedError",
        )

    def test_fx_17_mutation_target_must_name_an_embedded_document(self) -> None:
        manifest = artifact_only_manifest()
        manifest["dirty_cases"][0]["target_document"] = "missing.json"
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_problem(
            result,
            "FIXTURE_MUTATION_TARGET_NOT_FOUND",
            "/dirty_cases/0/target_document",
            "mutationTarget",
        )

    def test_fx_18_remove_pointer_must_resolve(self) -> None:
        manifest = artifact_only_manifest()
        manifest["dirty_cases"][0]["json_pointer"] = "/payload/missing"
        result = validate_fixture_manifest(manifest, self.registry)
        self.assert_problem(
            result,
            "FIXTURE_MUTATION_ERROR",
            "/dirty_cases/0/json_pointer",
            "jsonPointerMutation",
        )


class TestFixtureDirectoryDiscovery(FixtureContractTestCase):
    def test_fx_19_immediate_case_directories_are_discovered_and_counted(self) -> None:
        first = artifact_only_manifest()
        second = artifact_only_manifest()
        second["case_id"] = entity_id("case", 2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, manifest in (("fixture_b", second), ("fixture_a", first)):
                directory = root / name
                directory.mkdir()
                (directory / "case.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
            result = validate_fixture_directory(root, self.registry)
        self.assertEqual(result.problems, ())
        self.assertIsInstance(result.value, FixtureDirectorySummary)
        self.assertEqual(result.value.fixture_count, 2)
        self.assertEqual(result.value.document_count, 2)
        self.assertEqual(result.value.dirty_case_count, 2)


if __name__ == "__main__":
    unittest.main()
