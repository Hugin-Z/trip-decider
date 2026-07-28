"""WU1C deterministic contract-compatibility cases.

Source: synthetic deterministic structures written from the approved WU1C
Plan and docs/real-world-contract-extension.md.
Coverage: provider metadata, explicit CRS, source-policy combinations, and
fixture-source metadata.
Non-coverage: provider connectivity, real POIs, license validity, coordinate
correctness or conversion, evidence truth, feasibility, routing, planning,
and any real Jiangxi itinerary.

The expected values in this module are handwritten from the contract. They
are not generated from validator output.
"""

from __future__ import annotations

import copy

from trip_decider.fixture_validation import (
    ValidatedFixtureManifest,
    validate_fixture_manifest,
)
from trip_decider.schema_validation import ValidationProblem
from tests.test_fixture_validation import artifact_only_manifest
from tests.test_schema_validation import (
    ContractTestCase,
    locator,
    make_candidates,
    make_request,
    refresh_hash,
)


CHECKED_AT = "2026-07-28T00:00:00+08:00"
TERMS_URL = "https://provider.example/terms"


def commercial_live_policy() -> dict[str, object]:
    return {
        "source_class": "commercial",
        "capture_mode": "live",
        "storage_policy": "prohibited",
        "replay_allowed": False,
        "fixture_allowed": False,
        "policy_checked_at": CHECKED_AT,
        "terms_url": TERMS_URL,
        "authorization_ref": None,
        "license": None,
    }


def temporary_capture_policy() -> dict[str, object]:
    return {
        "source_class": "commercial",
        "capture_mode": "temporary_capture",
        "storage_policy": "temporary_only",
        "replay_allowed": False,
        "fixture_allowed": False,
        "policy_checked_at": CHECKED_AT,
        "terms_url": TERMS_URL,
        "authorization_ref": None,
        "license": None,
    }


def open_data_anchor_policy() -> dict[str, object]:
    return {
        "source_class": "open_data",
        "capture_mode": "persistent_anchor",
        "storage_policy": "persistent_allowed",
        "replay_allowed": True,
        "fixture_allowed": True,
        "policy_checked_at": CHECKED_AT,
        "terms_url": "https://www.openstreetmap.org/copyright",
        "authorization_ref": None,
        "license": {
            "identifier": "ODbL-1.0",
            "url": "https://opendatacommons.org/licenses/odbl/1-0/",
            "attribution": "© OpenStreetMap contributors",
        },
    }


def provider_authorized_anchor_policy() -> dict[str, object]:
    return {
        "source_class": "commercial",
        "capture_mode": "persistent_anchor",
        "storage_policy": "persistent_authorized",
        "replay_allowed": True,
        "fixture_allowed": True,
        "policy_checked_at": CHECKED_AT,
        "terms_url": TERMS_URL,
        "authorization_ref": "authorization_fixture_scope_001",
        "license": None,
    }


def synthetic_fixture_policy() -> dict[str, object]:
    return {
        "source_class": "synthetic",
        "capture_mode": "persistent_anchor",
        "storage_policy": "persistent_allowed",
        "replay_allowed": True,
        "fixture_allowed": True,
        "policy_checked_at": CHECKED_AT,
        "terms_url": None,
        "authorization_ref": None,
        "license": None,
    }


def user_supplied_anchor_policy() -> dict[str, object]:
    return {
        "source_class": "user_supplied",
        "capture_mode": "persistent_anchor",
        "storage_policy": "user_controlled",
        "replay_allowed": True,
        "fixture_allowed": True,
        "policy_checked_at": CHECKED_AT,
        "terms_url": None,
        "authorization_ref": "user_control_fixture_scope_001",
        "license": None,
    }


def provider_metadata(
    *,
    policy: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "name": "provider_name",
        "record_id": "provider-record-001",
        "record_type": "scenic_poi",
        "categories": [
            {
                "code": "category-001",
                "label": "Scenic place",
            }
        ],
        "external_status": {
            "kind": "reported",
            "code": "open",
            "label": "Reported open",
        },
        "data_policy": copy.deepcopy(
            policy if policy is not None else temporary_capture_policy()
        ),
    }


def coordinate_location(crs: str = "GCJ-02") -> dict[str, object]:
    return {
        "kind": "coordinates",
        "latitude": 28.0,
        "longitude": 117.0,
        "crs": crs,
        "source_refs": [
            {
                "kind": "provider_item",
                "value": "provider-record-001",
            }
        ],
    }


def provider_candidate_document(
    *,
    provider: dict[str, object] | None = None,
    location: dict[str, object] | None = None,
) -> dict[str, object]:
    request = make_request()
    document = make_candidates(request)
    candidate = document["payload"]["candidates"][0]
    candidate["provider"] = copy.deepcopy(
        provider if provider is not None else provider_metadata()
    )
    candidate["location"] = copy.deepcopy(
        location if location is not None else coordinate_location()
    )
    refresh_hash(document)
    return document


class WU1CContractCase(ContractTestCase):
    def assert_artifact_success(
        self,
        document: dict[str, object],
    ) -> dict[str, object]:
        result = self.artifact_result(document)
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)
        self.assertEqual(result.value.artifact_type, "candidates")
        self.assertEqual(result.value.artifact_id, document["artifact_id"])
        candidate = document["payload"]["candidates"][0]
        self.assertEqual(candidate["candidate_kind"], "destination")
        return candidate

    def assert_schema_problem(
        self,
        document: dict[str, object],
        pointer: str,
        rule: str,
    ) -> ValidationProblem:
        result = self.artifact_result(document)
        self.assertIsNone(result.value)
        matches = [
            problem
            for problem in result.problems
            if problem.error_code == "SCHEMA_VALIDATION_ERROR"
            and problem.json_pointer == pointer
            and problem.schema_rule == rule
        ]
        self.assertEqual(
            len(matches),
            1,
            msg=f"expected one {pointer} {rule} problem, got {result.problems!r}",
        )
        self.assertEqual(matches[0].message, "Document does not satisfy its schema.")
        return matches[0]

    def assert_manifest_success(
        self,
        manifest: dict[str, object],
    ) -> None:
        result = validate_fixture_manifest(manifest, self.registry())
        self.assertEqual(result.problems, ())
        self.assertIsInstance(result.value, ValidatedFixtureManifest)
        self.assertEqual(result.value.case_id, manifest["case_id"])
        self.assertEqual(result.value.root_artifact_id, manifest["root_artifact_id"])
        self.assertEqual(result.value.document_count, 1)
        self.assertEqual(result.value.dirty_case_count, 1)

    def assert_manifest_invalid(self, manifest: dict[str, object]) -> None:
        result = validate_fixture_manifest(manifest, self.registry())
        self.assertIsNone(result.value)
        self.assertGreaterEqual(len(result.problems), 1)
        self.assertEqual(
            result.problems[0].error_code,
            "FIXTURE_SCHEMA_VALIDATION_ERROR",
        )


class TestCandidateProviderContract(WU1CContractCase):
    def test_cp_01_legacy_candidate_without_provider_remains_valid(self) -> None:
        request = make_request()
        document = make_candidates(request)
        candidate = self.assert_artifact_success(document)
        self.assertNotIn("provider", candidate)
        self.assertEqual(
            candidate["location"],
            {"kind": "coordinates", "latitude": 28.0, "longitude": 117.0},
        )

    def test_cp_02_nested_provider_metadata_is_valid(self) -> None:
        document = provider_candidate_document()
        candidate = self.assert_artifact_success(document)
        provider = candidate["provider"]
        self.assertEqual(provider["name"], "provider_name")
        self.assertEqual(provider["record_id"], "provider-record-001")
        self.assertEqual(provider["record_type"], "scenic_poi")
        self.assertEqual(provider["categories"][0]["code"], "category-001")

    def test_cp_03_provider_categories_must_be_nonempty(self) -> None:
        provider = provider_metadata()
        provider["categories"] = []
        document = provider_candidate_document(provider=provider)
        self.assert_schema_problem(
            document,
            "/payload/candidates/0/provider/categories",
            "minItems",
        )

    def test_cp_04_provider_category_rejects_extra_field(self) -> None:
        provider = provider_metadata()
        provider["categories"][0]["planner_kind"] = "poi"
        document = provider_candidate_document(provider=provider)
        self.assert_schema_problem(
            document,
            "/payload/candidates/0/provider/categories/0",
            "additionalProperties",
        )

    def test_cp_05_provider_requires_external_status(self) -> None:
        provider = provider_metadata()
        del provider["external_status"]
        document = provider_candidate_document(provider=provider)
        self.assert_schema_problem(
            document,
            "/payload/candidates/0/provider",
            "required",
        )

    def test_cp_06_reported_external_status_requires_code(self) -> None:
        provider = provider_metadata()
        del provider["external_status"]["code"]
        document = provider_candidate_document(provider=provider)
        self.assert_schema_problem(
            document,
            "/payload/candidates/0/provider/external_status",
            "required",
        )

    def test_cp_07_not_reported_status_forbids_code(self) -> None:
        provider = provider_metadata()
        provider["external_status"] = {
            "kind": "not_reported",
            "code": "invented",
        }
        document = provider_candidate_document(provider=provider)
        self.assert_schema_problem(
            document,
            "/payload/candidates/0/provider/external_status",
            "additionalProperties",
        )

    def test_cp_08_provider_requires_data_policy(self) -> None:
        provider = provider_metadata()
        del provider["data_policy"]
        document = provider_candidate_document(provider=provider)
        self.assert_schema_problem(
            document,
            "/payload/candidates/0/provider",
            "required",
        )

    def test_cp_09_provider_native_top_level_field_is_rejected(self) -> None:
        request = make_request()
        document = make_candidates(request)
        document["payload"]["candidates"][0]["provider_id"] = "provider-record-001"
        refresh_hash(document)
        result = self.artifact_result(document)
        self.assertIsNone(result.value)
        self.assertGreaterEqual(len(result.problems), 1)
        self.assertEqual(result.problems[0].error_code, "SCHEMA_VALIDATION_ERROR")
        self.assertEqual(result.problems[0].schema_rule, "additionalProperties")

    def test_cp_10_provider_name_uses_closed_token_pattern(self) -> None:
        provider = provider_metadata()
        provider["name"] = "Provider Name"
        document = provider_candidate_document(provider=provider)
        self.assert_schema_problem(
            document,
            "/payload/candidates/0/provider/name",
            "pattern",
        )


class TestLocationCRSContract(WU1CContractCase):
    def test_loc_01_provider_coordinates_accept_wgs84(self) -> None:
        document = provider_candidate_document(location=coordinate_location("WGS84"))
        candidate = self.assert_artifact_success(document)
        self.assertEqual(candidate["location"]["crs"], "WGS84")
        self.assertEqual(candidate["location"]["latitude"], 28.0)
        self.assertEqual(candidate["location"]["longitude"], 117.0)

    def test_loc_02_provider_coordinates_accept_gcj02(self) -> None:
        document = provider_candidate_document(location=coordinate_location("GCJ-02"))
        candidate = self.assert_artifact_success(document)
        self.assertEqual(candidate["location"]["crs"], "GCJ-02")
        self.assertEqual(candidate["location"]["source_refs"][0]["kind"], "provider_item")
        self.assertEqual(candidate["location"]["source_refs"][0]["value"], "provider-record-001")

    def test_loc_03_provider_coordinates_accept_bd09(self) -> None:
        document = provider_candidate_document(location=coordinate_location("BD-09"))
        candidate = self.assert_artifact_success(document)
        self.assertEqual(candidate["location"]["crs"], "BD-09")
        self.assertEqual(len(candidate["location"]["source_refs"]), 1)
        self.assertEqual(candidate["location"]["kind"], "coordinates")

    def test_loc_04_provider_coordinates_require_crs(self) -> None:
        location = coordinate_location()
        del location["crs"]
        document = provider_candidate_document(location=location)
        result = self.artifact_result(document)
        self.assertIsNone(result.value)
        self.assertEqual(
            [
                (problem.json_pointer, problem.schema_rule)
                for problem in result.problems
                if problem.json_pointer == "/payload/candidates/0/location"
            ],
            [("/payload/candidates/0/location", "required")],
        )
        self.assertTrue(
            any(
                problem.error_code == "SCHEMA_VALIDATION_ERROR"
                for problem in result.problems
            )
        )

    def test_loc_05_unknown_crs_is_rejected(self) -> None:
        document = provider_candidate_document(
            location=coordinate_location("unknown"),
        )
        self.assert_schema_problem(
            document,
            "/payload/candidates/0/location/crs",
            "enum",
        )

    def test_loc_06_provider_coordinates_require_local_source_refs(self) -> None:
        location = coordinate_location()
        del location["source_refs"]
        document = provider_candidate_document(location=location)
        result = self.artifact_result(document)
        self.assertIsNone(result.value)
        self.assertEqual(
            [
                (problem.json_pointer, problem.schema_rule)
                for problem in result.problems
                if problem.json_pointer == "/payload/candidates/0/location"
            ],
            [("/payload/candidates/0/location", "required")],
        )
        self.assertTrue(
            any(
                problem.error_code == "SCHEMA_VALIDATION_ERROR"
                for problem in result.problems
            )
        )

    def test_loc_07_provider_coordinate_source_refs_are_nonempty(self) -> None:
        location = coordinate_location()
        location["source_refs"] = []
        document = provider_candidate_document(location=location)
        self.assert_schema_problem(
            document,
            "/payload/candidates/0/location/source_refs",
            "minItems",
        )

    def test_loc_08_unknown_crs_uses_unresolved_location(self) -> None:
        location = {
            "kind": "unresolved",
            "query": "provider location text",
            "reason": "crs_unknown",
            "source_refs": [
                {
                    "kind": "provider_item",
                    "value": "provider-record-001",
                }
            ],
        }
        document = provider_candidate_document(location=location)
        candidate = self.assert_artifact_success(document)
        self.assertEqual(candidate["location"]["kind"], "unresolved")
        self.assertEqual(candidate["location"]["reason"], "crs_unknown")
        self.assertNotIn("latitude", candidate["location"])
        self.assertNotIn("longitude", candidate["location"])

    def test_loc_09_provider_unresolved_location_requires_reason(self) -> None:
        location = {
            "kind": "unresolved",
            "query": "provider location text",
            "source_refs": [
                {
                    "kind": "provider_item",
                    "value": "provider-record-001",
                }
            ],
        }
        document = provider_candidate_document(location=location)
        result = self.artifact_result(document)
        self.assertIsNone(result.value)
        self.assertEqual(
            [
                (problem.json_pointer, problem.schema_rule)
                for problem in result.problems
                if problem.json_pointer == "/payload/candidates/0/location"
            ],
            [("/payload/candidates/0/location", "required")],
        )
        self.assertTrue(
            any(
                problem.error_code == "SCHEMA_VALIDATION_ERROR"
                for problem in result.problems
            )
        )


class TestDataPolicyContract(WU1CContractCase):
    def assert_policy_valid(self, policy: dict[str, object]) -> dict[str, object]:
        document = provider_candidate_document(provider=provider_metadata(policy=policy))
        candidate = self.assert_artifact_success(document)
        self.assertEqual(candidate["provider"]["data_policy"], policy)
        self.assertEqual(candidate["location"]["crs"], "GCJ-02")
        return candidate

    def test_pol_01_commercial_live_policy_is_explicit(self) -> None:
        candidate = self.assert_policy_valid(commercial_live_policy())
        policy = candidate["provider"]["data_policy"]
        self.assertFalse(policy["replay_allowed"])
        self.assertFalse(policy["fixture_allowed"])

    def test_pol_02_temporary_capture_policy_is_explicit(self) -> None:
        candidate = self.assert_policy_valid(temporary_capture_policy())
        policy = candidate["provider"]["data_policy"]
        self.assertEqual(policy["storage_policy"], "temporary_only")
        self.assertEqual(policy["capture_mode"], "temporary_capture")

    def test_pol_03_open_data_anchor_policy_is_valid(self) -> None:
        candidate = self.assert_policy_valid(open_data_anchor_policy())
        policy = candidate["provider"]["data_policy"]
        self.assertEqual(policy["license"]["identifier"], "ODbL-1.0")
        self.assertTrue(policy["fixture_allowed"])

    def test_pol_04_provider_authorized_anchor_policy_is_valid(self) -> None:
        candidate = self.assert_policy_valid(provider_authorized_anchor_policy())
        policy = candidate["provider"]["data_policy"]
        self.assertEqual(policy["storage_policy"], "persistent_authorized")
        self.assertEqual(
            policy["authorization_ref"],
            "authorization_fixture_scope_001",
        )

    def test_pol_05_synthetic_fixture_policy_is_valid(self) -> None:
        candidate = self.assert_policy_valid(synthetic_fixture_policy())
        policy = candidate["provider"]["data_policy"]
        self.assertEqual(policy["source_class"], "synthetic")
        self.assertIsNone(policy["terms_url"])

    def test_pol_06_user_supplied_anchor_policy_is_valid(self) -> None:
        candidate = self.assert_policy_valid(user_supplied_anchor_policy())
        policy = candidate["provider"]["data_policy"]
        self.assertEqual(policy["storage_policy"], "user_controlled")
        self.assertEqual(
            policy["authorization_ref"],
            "user_control_fixture_scope_001",
        )

    def test_pol_07_temporary_capture_cannot_enable_replay(self) -> None:
        policy = temporary_capture_policy()
        policy["replay_allowed"] = True
        document = provider_candidate_document(provider=provider_metadata(policy=policy))
        self.assert_schema_problem(
            document,
            "/payload/candidates/0/provider/data_policy/replay_allowed",
            "const",
        )

    def test_pol_08_open_data_anchor_requires_license(self) -> None:
        policy = open_data_anchor_policy()
        del policy["license"]
        document = provider_candidate_document(provider=provider_metadata(policy=policy))
        self.assert_schema_problem(
            document,
            "/payload/candidates/0/provider/data_policy",
            "required",
        )


class TestFixtureSourceContract(WU1CContractCase):
    def test_fxsrc_01_open_data_anchor_is_replayable(self) -> None:
        manifest = artifact_only_manifest()
        manifest["fixture_type"] = "real_anchor"
        manifest["source"] = {
            "kind": "open_data_anchor",
            "description": "Licensed deterministic open-data structure.",
            "origin_url": "https://www.openstreetmap.org/",
            "data_policy": open_data_anchor_policy(),
        }
        self.assert_manifest_success(manifest)
        self.assertEqual(manifest["source"]["kind"], "open_data_anchor")
        self.assertTrue(manifest["source"]["data_policy"]["replay_allowed"])

    def test_fxsrc_02_provider_authorized_anchor_is_replayable(self) -> None:
        manifest = artifact_only_manifest()
        manifest["fixture_type"] = "real_anchor"
        manifest["source"] = {
            "kind": "provider_authorized_anchor",
            "description": "Explicitly authorized provider structure.",
            "provider_name": "provider_name",
            "data_policy": provider_authorized_anchor_policy(),
        }
        self.assert_manifest_success(manifest)
        self.assertEqual(manifest["source"]["provider_name"], "provider_name")
        self.assertTrue(manifest["source"]["data_policy"]["fixture_allowed"])

    def test_fxsrc_03_synthetic_fixture_has_specification_ref(self) -> None:
        manifest = artifact_only_manifest()
        manifest["source"] = {
            "kind": "synthetic_fixture",
            "description": "Deterministic contract structure.",
            "specification_ref": "docs/real-world-contract-extension.md",
            "data_policy": synthetic_fixture_policy(),
        }
        self.assert_manifest_success(manifest)
        self.assertEqual(
            manifest["source"]["specification_ref"],
            "docs/real-world-contract-extension.md",
        )
        self.assertEqual(
            manifest["source"]["data_policy"]["source_class"],
            "synthetic",
        )

    def test_fxsrc_04_user_supplied_anchor_has_control_ref(self) -> None:
        manifest = artifact_only_manifest()
        manifest["fixture_type"] = "real_anchor"
        manifest["source"] = {
            "kind": "user_supplied_anchor",
            "description": "User-controlled contract structure.",
            "user_control_ref": "user_control_fixture_scope_001",
            "data_policy": user_supplied_anchor_policy(),
        }
        self.assert_manifest_success(manifest)
        self.assertEqual(
            manifest["source"]["user_control_ref"],
            "user_control_fixture_scope_001",
        )
        self.assertEqual(
            manifest["source"]["data_policy"]["storage_policy"],
            "user_controlled",
        )

    def test_fxsrc_05_commercial_live_is_not_a_fixture_kind(self) -> None:
        manifest = artifact_only_manifest()
        manifest["source"] = {
            "kind": "commercial_live",
            "description": "Forbidden live source.",
            "data_policy": commercial_live_policy(),
        }
        self.assert_manifest_invalid(manifest)
        self.assertEqual(manifest["source"]["kind"], "commercial_live")
        self.assertFalse(manifest["source"]["data_policy"]["fixture_allowed"])

    def test_fxsrc_06_temporary_capture_is_not_a_fixture_kind(self) -> None:
        manifest = artifact_only_manifest()
        manifest["source"] = {
            "kind": "temporary_capture",
            "description": "Forbidden temporary source.",
            "data_policy": temporary_capture_policy(),
        }
        self.assert_manifest_invalid(manifest)
        self.assertEqual(manifest["source"]["kind"], "temporary_capture")
        self.assertFalse(manifest["source"]["data_policy"]["replay_allowed"])
