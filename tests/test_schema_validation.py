"""WU1 C3 contract tests.

Source: synthetic deterministic inputs derived from the approved WU1 Plan.
Coverage: strict loading, schemas, hashes, explicit roots, closure modes,
definition/reference registries, fact-local sources, plan-version scope,
violations stages, and immutable candidate snapshots.
Non-coverage: semantic parsing, evidence truth, feasibility, proofs, routing,
optimization, rendering, and any real Jiangxi itinerary.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from trip_decider.schema_validation import (
    BundleClosure,
    LoadedDocument,
    SchemaRegistry,
    ValidationProblem,
    load_document,
    validate_artifact,
    validate_bundle,
    validate_schema_registry,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATHS = tuple(sorted((ROOT / "schemas").glob("*.schema.json")))
SCHEMA_IDS = {
    name: f"https://trip-decider.example/schemas/0.1.0/{name}.schema.json"
    for name in (
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
}


def entity_id(kind: str, number: int) -> str:
    return f"{kind}_{number:08x}-0000-4000-8000-{number:012x}"


def canonical_payload_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def artifact_id(number: int) -> str:
    return f"urn:uuid:{number:08x}-0000-4000-8000-{number:012x}"


def locator(value: str = "request:0") -> dict[str, object]:
    return {"kind": "user_input", "value": value}


def envelope(artifact_type: str, payload: dict[str, object], number: int) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "artifact_id": artifact_id(number),
        "artifact_type": artifact_type,
        "created_at": "2026-07-26T08:00:00+08:00",
        "producer": {
            "name": "contract-test",
            "version": "0.1.0",
            "run_id": entity_id("run", number),
        },
        "provenance": {
            "parent_artifact_ids": [],
            "input_hashes": [],
            "pipeline_stage": "wu1-test",
        },
        "integrity": {
            "payload_sha256": canonical_payload_sha256(payload),
            "canonicalization": "canonical-json-v1",
        },
        "payload": payload,
    }


def artifact_ref(document: dict[str, object]) -> dict[str, object]:
    integrity = document["integrity"]
    assert isinstance(integrity, dict)
    return {
        "artifact_id": document["artifact_id"],
        "artifact_type": document["artifact_type"],
        "schema_version": document["schema_version"],
        "payload_sha256": integrity["payload_sha256"],
    }


def as_document(name: str, data: dict[str, object]) -> LoadedDocument:
    return LoadedDocument(path=Path(name), data=data)


def refresh_hash(document: dict[str, object]) -> None:
    integrity = document["integrity"]
    assert isinstance(integrity, dict)
    integrity["payload_sha256"] = canonical_payload_sha256(document["payload"])


def make_request(number: int = 1) -> dict[str, object]:
    payload = {
        "request_id": entity_id("request", 1),
        "natural_language": "固定目的地，按给定约束排出结构方案。",
        "explicit": {
            "origin": locator(),
            "travel_window": {
                "start": "2026-08-05T08:00:00+08:00",
                "end": "2026-08-06T20:00:00+08:00",
                "timezone": "Asia/Shanghai",
            },
            "party": {"count": 1},
            "transport_modes": ["walking"],
            "destination": {"selection_mode": "fixed", "name": "synthetic-destination"},
            "preferences_raw": ["synthetic deterministic contract input"],
        },
        "user_input_refs": [locator()],
    }
    return envelope("request", payload, number)


def make_parse(request: dict[str, object], number: int = 2) -> dict[str, object]:
    payload = {
        "request_id": entity_id("request", 1),
        "request_ref": artifact_ref(request),
        "parser": {"name": "test-parser", "version": "0.1.0", "kind": "user_structured"},
        "parsed_constraints": [
            {
                "parse_item_id": entity_id("parse_item", 1),
                "constraint_id": entity_id("constraint", 1),
                "user_quote": "synthetic hard constraint",
                "user_quote_locator": locator("request:1"),
                "origin_kind": "explicit",
                "category": "time_window",
                "layer": "hard",
                "normalized_expression": {
                    "operator": "within",
                    "value": "travel_window",
                    "unit": None,
                },
                "explanation": "Deterministic normalization for a structural test.",
                "needs_confirmation": False,
            }
        ],
        "parse_notes": [],
        "needs_confirmation": False,
    }
    return envelope("constraint-parse", payload, number)


def make_constraints(
    request: dict[str, object],
    parsed: dict[str, object],
    number: int = 3,
    *,
    target: dict[str, object] | None = None,
) -> dict[str, object]:
    target = target or {
        "target_type": "request_scope",
        "request_id": entity_id("request", 1),
        "scope_kind": "travel_window",
    }
    payload = {
        "constraint_set_id": entity_id("constraint_set", 1),
        "request_ref": artifact_ref(request),
        "parse_ref": artifact_ref(parsed),
        "revision": 1,
        "constraints": [
            {
                "constraint_id": entity_id("constraint", 1),
                "layer": "hard",
                "category": "time_window",
                "operator": "within",
                "target_refs": [target],
                "value": "2026-08-05/2026-08-06",
                "unit": None,
                "origin": {
                    "kind": "explicit",
                    "refs": [
                        {
                            "parse_item_id": entity_id("parse_item", 1),
                            "locator": locator("request:1"),
                        }
                    ],
                },
                "enabled": True,
                "supersedes_constraint_id": None,
            }
        ],
        "user_edit_policy": {
            "constraints_are_solver_ssot": True,
            "request_auto_overwrite": False,
        },
    }
    return envelope("constraints", payload, number)


def candidate(
    number: int,
    kind: str,
    *,
    parent: str | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": entity_id("candidate", number),
        "candidate_kind": kind,
        "label": f"synthetic-{kind}-{number}",
        "parent_candidate_id": parent,
        "location": {"kind": "coordinates", "latitude": 28.0, "longitude": 117.0},
        "source_refs": [locator(f"candidate:{number}")],
        "evidence_fact_refs": [],
        "generation_reason": "Synthetic deterministic structure.",
    }


def make_candidates(
    request: dict[str, object],
    number: int = 4,
    *,
    candidate_items: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    candidate_items = candidate_items or [
        candidate(1, "destination"),
        candidate(2, "poi", parent=entity_id("candidate", 1)),
    ]
    payload = {
        "candidate_set_id": entity_id("candidate_set", number),
        "request_ref": artifact_ref(request),
        "generation_stage": "poi_discovery",
        "candidates": candidate_items,
        "rejected_inputs": [],
    }
    return envelope("candidates", payload, number)


def webpage_source(source_id: str = "source_official") -> dict[str, object]:
    return {
        "source_id": source_id,
        "source_type": "official_notice",
        "url": "https://example.invalid/official-notice",
        "publisher": "Synthetic official publisher",
        "published_at": "2026-07-01T00:00:00+08:00",
        "retrieved_at": "2026-07-26T08:00:00+08:00",
        "excerpt": "Synthetic excerpt fixed by the structural specification.",
        "locator": {"kind": "web_location", "value": "section-1"},
    }


def api_source(source_id: str = "source_route") -> dict[str, object]:
    return {
        "source_id": source_id,
        "source_type": "api_response",
        "provider": "synthetic-provider",
        "operation": "route",
        "retrieved_at": "2026-07-26T08:00:00+08:00",
        "request_fingerprint": "a" * 64,
        "response_locator": {"kind": "response_location", "value": "response:0"},
    }


def make_fact(
    number: int = 1,
    *,
    subject: dict[str, object] | None = None,
    sources: list[dict[str, object]] | None = None,
    conflict_refs: list[str] | None = None,
    derivation: str = "official_report",
) -> dict[str, object]:
    subject = subject or {
        "subject_type": "entity",
        "entity_kind": "candidate",
        "entity_id": entity_id("candidate", 2),
    }
    sources = sources if sources is not None else [webpage_source()]
    detail: dict[str, object] = {"input_fact_ids": []}
    if derivation in {"api_estimate", "model_estimate"}:
        detail["estimate"] = {"method": "synthetic", "value": 20, "unit": "minute"}
    return {
        "fact_id": entity_id("fact", number),
        "subject": subject,
        "field": "duration",
        "value": 20,
        "unit": "minute",
        "support_status": "sourced",
        "derivation": derivation,
        "freshness": {
            "retrieved_at": "2026-07-26T08:00:00+08:00",
            "effective_at": "2026-07-26T08:00:00+08:00",
            "expires_at": None,
            "status": "current",
        },
        "sources": sources,
        "normalization": {
            "original_value": "20 minutes",
            "normalized_value": 20,
            "rule_id": "duration-minute-v1",
        },
        "display_status": "sourced" if derivation == "official_report" else "estimated",
        "display_rule": "synthetic-display-rule-v1",
        "conflict_source_refs": conflict_refs or [],
        "derivation_detail": detail,
    }


def make_evidence(
    number: int = 5,
    *,
    facts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    facts = facts or [make_fact()]
    payload = {
        "evidence_set_id": entity_id("evidence_set", number),
        "facts": facts,
        "mapping_rule_version": "evidence-map-0.1.0",
    }
    return envelope("evidence", payload, number)


def make_plan(
    request: dict[str, object],
    constraints: dict[str, object],
    candidates: dict[str, object],
    evidence: dict[str, object],
    number: int = 6,
    *,
    status: str = "feasible",
    activity_id_value: str | None = None,
) -> dict[str, object]:
    conditions: list[dict[str, object]] = []
    days: list[dict[str, object]] = []
    base_selections: list[dict[str, object]] = []
    proof_refs: list[str] = []
    if status in {"feasible", "conditionally_feasible"}:
        base_selections = [
            {
                "base_selection_id": entity_id("base_selection", 1),
                "candidate_ref": entity_id("candidate", 1),
                "constraint_refs": [entity_id("constraint", 1)],
                "evidence_fact_refs": [entity_id("fact", 1)],
            }
        ]
        days = [
            {
                "day_id": entity_id("day", 1),
                "date": "2026-08-05",
                "activities": [
                    {
                        "activity_id": activity_id_value or entity_id("activity", 1),
                        "candidate_ref": entity_id("candidate", 2),
                        "start_at": "2026-08-05T09:00:00+08:00",
                        "end_at": "2026-08-05T10:00:00+08:00",
                        "constraint_refs": [entity_id("constraint", 1)],
                        "evidence_fact_refs": [entity_id("fact", 1)],
                    }
                ],
                "legs": [
                    {
                        "leg_id": entity_id("leg", 1),
                        "mode": "walking",
                        "duration_minutes": 20,
                        "derivation_fact_ref": entity_id("fact", 1),
                    }
                ],
            }
        ]
    if status == "conditionally_feasible":
        conditions = [
            {
                "condition_id": "condition_1",
                "description": "Requires the synthetic estimate to hold.",
                "constraint_refs": [entity_id("constraint", 1)],
                "evidence_fact_refs": [entity_id("fact", 1)],
            }
        ]
    if status == "proven_infeasible":
        proof_refs = [entity_id("proof", 1)]
    payload = {
        "plan_id": entity_id("plan", number),
        "request_ref": artifact_ref(request),
        "constraint_set_ref": artifact_ref(constraints),
        "candidate_set_ref": artifact_ref(candidates),
        "evidence_set_ref": artifact_ref(evidence),
        "plan_status": status,
        "conditions": conditions,
        "base_selections": base_selections,
        "days": days,
        "excluded_candidates": [],
        "constraint_evaluations": [],
        "objective_breakdown": {"components": [{"name": "structure", "value": 0}]},
        "proof_refs": proof_refs,
    }
    return envelope("plan", payload, number)


def make_violations_post(
    plan: dict[str, object],
    number: int = 7,
) -> dict[str, object]:
    plan_payload = plan["payload"]
    assert isinstance(plan_payload, dict)
    status = plan_payload["plan_status"]
    conditions = copy.deepcopy(plan_payload["conditions"])
    proofs = []
    if status == "proven_infeasible":
        proofs = [make_proof()]
    payload = {
        "evaluation_stage": "post_plan",
        "plan_status": status,
        "plan_ref": artifact_ref(plan),
        "violations": [],
        "conditions": conditions,
        "candidate_conflict_sets": [],
        "proofs": proofs,
    }
    return envelope("violations", payload, number)


def make_proof() -> dict[str, object]:
    return {
        "proof_id": entity_id("proof", 1),
        "proof_type": "duration_lower_bound",
        "rule_id": "duration-lower-bound-v1",
        "constraint_refs": [entity_id("constraint", 1)],
        "input_fact_ids": [entity_id("fact", 1)],
        "bounds": {"left": 120, "operator": ">", "right": 60, "unit": "minute"},
        "result": "conflict_proven",
    }


def make_violations_pre(
    request: dict[str, object],
    constraints: dict[str, object],
    candidates: dict[str, object],
    evidence: dict[str, object],
    number: int = 8,
) -> dict[str, object]:
    proof = make_proof()
    payload = {
        "evaluation_stage": "pre_plan",
        "plan_status": "proven_infeasible",
        "request_ref": artifact_ref(request),
        "constraint_set_ref": artifact_ref(constraints),
        "candidate_set_ref": artifact_ref(candidates),
        "evidence_set_ref": artifact_ref(evidence),
        "violations": [
            {
                "violation_id": entity_id("violation", 1),
                "kind": "hard",
                "message": "Synthetic deterministic lower-bound conflict.",
                "constraint_refs": [entity_id("constraint", 1)],
                "evidence_fact_refs": [entity_id("fact", 1)],
                "proof_refs": [entity_id("proof", 1)],
            }
        ],
        "conditions": [],
        "candidate_conflict_sets": [],
        "proofs": [proof],
    }
    return envelope("violations", payload, number)


def make_planning_bundle(status: str = "feasible") -> dict[str, dict[str, object]]:
    request = make_request()
    parsed = make_parse(request)
    constraints = make_constraints(request, parsed)
    candidates = make_candidates(request)
    evidence = make_evidence()
    plan = make_plan(request, constraints, candidates, evidence, status=status)
    violations = make_violations_post(plan)
    return {
        "request": request,
        "parse": parsed,
        "constraints": constraints,
        "candidates": candidates,
        "evidence": evidence,
        "plan": plan,
        "violations": violations,
    }


def make_previous_plan(plan: dict[str, object], number: int = 9) -> dict[str, object]:
    plan_payload = plan["payload"]
    assert isinstance(plan_payload, dict)
    payload = {
        "previous_plan_id": plan_payload["plan_id"],
        "previous_plan_artifact_ref": artifact_ref(plan),
        "baseline_constraint_set_id": entity_id("constraint_set", 1),
        "snapshot": {
            "base_selections": copy.deepcopy(plan_payload["base_selections"]),
            "days": copy.deepcopy(plan_payload["days"]),
        },
        "snapshot_created_at": "2026-07-26T09:00:00+08:00",
    }
    return envelope("previous-plan", payload, number)


def make_plan_diff(
    previous_plan: dict[str, object],
    new_plan: dict[str, object],
    number: int = 10,
    *,
    scope: str = "previous",
    entity_value: str | None = None,
) -> dict[str, object]:
    previous_payload = previous_plan["payload"]
    new_payload = new_plan["payload"]
    assert isinstance(previous_payload, dict)
    assert isinstance(new_payload, dict)
    payload = {
        "previous_plan_id": previous_payload["previous_plan_id"],
        "new_plan_id": new_payload["plan_id"],
        "change_score": 6,
        "weights": {
            "same_day_reorder": 1,
            "change_time_slot": 2,
            "move_day": 3,
            "change_base": 5,
            "remove_activity": 6,
            "add_activity": 4,
        },
        "changes": [
            {
                "change_id": entity_id("change", 1),
                "type": "remove_activity",
                "entity": {
                    "entity_kind": "activity",
                    "entity_id": entity_value or entity_id("activity", 1),
                    "resolution_scope": scope,
                },
                "from": {"day": "2026-08-05"},
                "to": None,
                "cost": 6,
                "reason": "Synthetic deterministic replan change.",
                "constraint_refs": [entity_id("constraint", 1)],
            }
        ],
        "unchanged_summary": {"activity_count": 0, "day_count": 0},
    }
    return envelope("plan-diff", payload, number)


class ContractTestCase(unittest.TestCase):
    def registry(self) -> SchemaRegistry:
        result = validate_schema_registry(SCHEMA_PATHS)
        self.assertEqual(result.problems, ())
        self.assertIsInstance(result.value, SchemaRegistry)
        return result.value

    def artifact_result(self, document: dict[str, object]):
        return validate_artifact(as_document(f"{document['artifact_type']}.json", document), self.registry())

    def bundle_result(
        self,
        documents: list[dict[str, object]],
        *,
        closure: BundleClosure,
        root: str,
    ):
        loaded = [
            as_document(f"{index:02d}-{document['artifact_type']}.json", document)
            for index, document in enumerate(documents)
        ]
        return validate_bundle(
            loaded,
            self.registry(),
            closure=closure,
            root_artifact_id=root,
        )

    def assert_success(self, result, *, root: str | None = None) -> None:
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)
        if root is not None:
            self.assertEqual(result.value.root_artifact_id, root)
            self.assertIn(root, result.value.validated_artifact_ids)

    def assert_problem(
        self,
        result,
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
        self.assertEqual(
            tuple(sorted(result.problems, key=lambda item: (item.artifact_path, item.json_pointer, item.error_code))),
            result.problems,
        )
        return problem


class TestC3Baseline(ContractTestCase):
    def test_00_interfaces_are_importable_with_explicit_root_parameters(self) -> None:
        parameters = inspect.signature(validate_bundle).parameters
        self.assertEqual(tuple(BundleClosure), (BundleClosure.ARTIFACT_ONLY, BundleClosure.CLOSED))
        self.assertEqual(parameters["closure"].default, inspect.Parameter.empty)
        self.assertEqual(parameters["root_artifact_id"].default, inspect.Parameter.empty)
        self.assertEqual(parameters["closure"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(parameters["root_artifact_id"].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_01_all_schema_json_is_parseable(self) -> None:
        parsed = [json.loads(path.read_text(encoding="utf-8")) for path in SCHEMA_PATHS]
        self.assertEqual(len(parsed), 11)
        self.assertTrue(all(item["$schema"].endswith("2020-12/schema") for item in parsed))
        self.assertTrue(all("$id" in item for item in parsed))

    def test_02_schema_ids_are_unique(self) -> None:
        ids = [json.loads(path.read_text(encoding="utf-8"))["$id"] for path in SCHEMA_PATHS]
        self.assertEqual(len(ids), 11)
        self.assertEqual(len(set(ids)), 11)
        self.assertEqual(sum(value.startswith("https://trip-decider.example/") for value in ids), 11)

    def test_03_constraint_parse_has_single_payload_hash_authority(self) -> None:
        schema = json.loads((ROOT / "schemas/constraint-parse.schema.json").read_text(encoding="utf-8"))
        serialized = json.dumps(schema, sort_keys=True)
        self.assertNotIn("output_payload_sha256", serialized)
        self.assertIn("integrity", json.dumps(json.loads((ROOT / "schemas/common.schema.json").read_text(encoding="utf-8"))))


class TestStrictLoadingAndEnvelope(ContractTestCase):
    def write_bytes(self, suffix: str, content: bytes) -> Path:
        temporary = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        temporary.write(content)
        temporary.close()
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        return Path(temporary.name)

    def test_load_01_valid_json(self) -> None:
        request = make_request()
        path = self.write_bytes(".json", json.dumps(request).encode("utf-8"))
        result = load_document(path, expected_artifact_type="request")
        self.assert_success(result)
        self.assertEqual(result.value.data["artifact_type"], "request")

    def test_load_02_duplicate_json_key_rejected(self) -> None:
        path = self.write_bytes(".json", b'{"artifact_type":"request","artifact_type":"plan"}')
        result = load_document(path)
        self.assert_problem(result, "DUPLICATE_MAPPING_KEY", "", "uniqueKeys")

    def test_load_03_nonfinite_json_number_rejected(self) -> None:
        path = self.write_bytes(".json", b'{"value":NaN}')
        result = load_document(path)
        self.assert_problem(result, "INVALID_JSON_CONSTANT", "/value", "finiteNumber")

    def test_load_04_invalid_utf8_rejected(self) -> None:
        path = self.write_bytes(".json", b"\xff\xfe")
        result = load_document(path)
        self.assert_problem(result, "INVALID_UTF8", "", "utf8")

    def test_load_05_utf8_bom_rejected(self) -> None:
        path = self.write_bytes(".json", b"\xef\xbb\xbf{}")
        result = load_document(path)
        self.assert_problem(result, "UTF8_BOM_NOT_ALLOWED", "", "utf8")

    def test_load_06_duplicate_yaml_key_rejected(self) -> None:
        path = self.write_bytes(".yaml", b"artifact_type: request\nartifact_type: plan\n")
        result = load_document(path)
        self.assert_problem(result, "DUPLICATE_MAPPING_KEY", "", "uniqueKeys")

    def test_load_07_nonstring_yaml_key_rejected(self) -> None:
        path = self.write_bytes(".yaml", b"1: value\n")
        result = load_document(path)
        self.assert_problem(result, "NON_STRING_MAPPING_KEY", "", "stringKeys")

    def test_env_01_unknown_major_rejected(self) -> None:
        request = make_request()
        request["schema_version"] = "1.0.0"
        refresh_hash(request)
        result = self.artifact_result(request)
        self.assert_problem(result, "UNKNOWN_SCHEMA_MAJOR", "/schema_version", "supportedMajor")

    def test_env_02_hash_mismatch_rejected(self) -> None:
        request = make_request()
        request["integrity"]["payload_sha256"] = "0" * 64
        result = self.artifact_result(request)
        self.assert_problem(result, "PAYLOAD_HASH_MISMATCH", "/integrity/payload_sha256", "payloadHash")

    def test_env_03_missing_required_rejected(self) -> None:
        request = make_request()
        del request["payload"]["natural_language"]
        refresh_hash(request)
        result = self.artifact_result(request)
        self.assert_problem(result, "SCHEMA_VALIDATION_ERROR", "/payload", "required")

    def test_env_04_unknown_property_rejected(self) -> None:
        request = make_request()
        request["payload"]["unexpected"] = True
        refresh_hash(request)
        result = self.artifact_result(request)
        self.assert_problem(result, "SCHEMA_VALIDATION_ERROR", "/payload", "additionalProperties")

    def test_env_05_invalid_datetime_rejected(self) -> None:
        request = make_request()
        request["created_at"] = "2026-07-26"
        result = self.artifact_result(request)
        self.assert_problem(result, "SCHEMA_VALIDATION_ERROR", "/created_at", "format")


class TestPlanSection111BaseCases(ContractTestCase):
    def test_base_01_repeated_candidate_references_are_legal(self) -> None:
        bundle = make_planning_bundle()
        result = self.bundle_result(
            list(bundle.values()),
            closure=BundleClosure.CLOSED,
            root=bundle["violations"]["artifact_id"],
        )
        self.assert_success(result, root=bundle["violations"]["artifact_id"])
        self.assertEqual(len(result.value.resolved_artifact_ids), 7)

    def test_base_02_duplicate_candidate_definition_fails(self) -> None:
        candidates = make_candidates(make_request())
        candidates["payload"]["candidates"].append(copy.deepcopy(candidates["payload"]["candidates"][0]))
        refresh_hash(candidates)
        result = self.bundle_result(
            [candidates],
            closure=BundleClosure.ARTIFACT_ONLY,
            root=candidates["artifact_id"],
        )
        self.assert_problem(result, "DUPLICATE_DEFINITION_ID", "/payload/candidates/2/candidate_id", "uniqueDefinition")

    def test_base_03_artifact_only_defers_future_entity_resolution(self) -> None:
        bundle = make_planning_bundle()
        plan = bundle["plan"]
        result = self.bundle_result(
            [plan],
            closure=BundleClosure.ARTIFACT_ONLY,
            root=plan["artifact_id"],
        )
        self.assert_success(result, root=plan["artifact_id"])
        self.assertEqual(result.value.closure, BundleClosure.ARTIFACT_ONLY)

    def test_base_04_closed_rejects_missing_future_entity(self) -> None:
        bundle = make_planning_bundle()
        plan = bundle["plan"]
        result = self.bundle_result(
            [plan],
            closure=BundleClosure.CLOSED,
            root=plan["artifact_id"],
        )
        self.assert_problem(result, "UNRESOLVED_REFERENCE", "/payload/request_ref", "closedReference")

    def test_base_05_candidate_source_refs_are_provenance(self) -> None:
        request = make_request()
        candidates = make_candidates(request)
        result = self.bundle_result(
            [candidates],
            closure=BundleClosure.ARTIFACT_ONLY,
            root=candidates["artifact_id"],
        )
        self.assert_success(result, root=candidates["artifact_id"])
        source_ref = candidates["payload"]["candidates"][0]["source_refs"][0]
        self.assertEqual(source_ref["kind"], "user_input")

    def test_base_06_duplicate_source_inside_fact_fails(self) -> None:
        fact = make_fact(sources=[webpage_source(), webpage_source()])
        evidence = make_evidence(facts=[fact])
        result = self.artifact_result(evidence)
        self.assert_problem(result, "DUPLICATE_LOCAL_SOURCE_ID", "/payload/facts/0/sources/1/source_id", "uniqueLocalSource")

    def test_base_07_same_source_id_across_facts_is_legal(self) -> None:
        first = make_fact(1, sources=[webpage_source()])
        second = make_fact(2, sources=[webpage_source()])
        evidence = make_evidence(facts=[first, second])
        result = self.artifact_result(evidence)
        self.assert_success(result)
        self.assertEqual(result.value.artifact_type, "evidence")

    def test_base_08_conflict_source_is_fact_local(self) -> None:
        first = make_fact(1, sources=[webpage_source("source_first")])
        second = make_fact(
            2,
            sources=[webpage_source("source_second")],
            conflict_refs=["source_first"],
        )
        evidence = make_evidence(facts=[first, second])
        result = self.artifact_result(evidence)
        self.assert_problem(result, "UNRESOLVED_LOCAL_SOURCE_REFERENCE", "/payload/facts/1/conflict_source_refs/0", "localSourceReference")

    def test_base_09_parse_constraint_id_resolves_to_constraints_definition(self) -> None:
        request = make_request()
        parsed = make_parse(request)
        constraints = make_constraints(request, parsed)
        result = self.bundle_result(
            [request, parsed, constraints],
            closure=BundleClosure.CLOSED,
            root=constraints["artifact_id"],
        )
        self.assert_success(result, root=constraints["artifact_id"])
        self.assertEqual(len(result.value.resolved_artifact_ids), 3)

    def test_base_10_provenance_locator_needs_no_entity(self) -> None:
        request = make_request()
        result = self.bundle_result(
            [request],
            closure=BundleClosure.CLOSED,
            root=request["artifact_id"],
        )
        self.assert_success(result, root=request["artifact_id"])
        self.assertEqual(request["payload"]["user_input_refs"][0]["value"], "request:0")


class TestConstraintTargets(ContractTestCase):
    def test_ct_01_request_scope_resolves_without_future_plan_entity(self) -> None:
        request = make_request()
        parsed = make_parse(request)
        constraints = make_constraints(request, parsed)
        result = self.bundle_result(
            [constraints, request, parsed],
            closure=BundleClosure.CLOSED,
            root=constraints["artifact_id"],
        )
        self.assert_success(result, root=constraints["artifact_id"])
        target = constraints["payload"]["constraints"][0]["target_refs"][0]
        self.assertEqual(target["scope_kind"], "travel_window")

    def test_ct_02_entity_target_uses_sibling_kind(self) -> None:
        request = make_request()
        parsed = make_parse(request)
        target = {
            "target_type": "entity",
            "entity_kind": "candidate",
            "entity_id": entity_id("candidate", 2),
        }
        constraints = make_constraints(request, parsed, target=target)
        candidates = make_candidates(request)
        result = self.bundle_result(
            [request, parsed, constraints, candidates],
            closure=BundleClosure.CLOSED,
            root=constraints["artifact_id"],
        )
        self.assert_success(result, root=constraints["artifact_id"])
        self.assertEqual(target["entity_kind"], "candidate")


class TestEvidenceSubjects(ContractTestCase):
    def test_es_01_candidate_entity_subject_is_legal(self) -> None:
        request = make_request()
        candidates = make_candidates(request)
        evidence = make_evidence()
        result = self.bundle_result(
            [evidence, candidates, request],
            closure=BundleClosure.CLOSED,
            root=evidence["artifact_id"],
        )
        self.assert_success(result, root=evidence["artifact_id"])
        self.assertEqual(evidence["payload"]["facts"][0]["subject"]["subject_type"], "entity")

    def test_es_02_relation_with_both_endpoints_is_legal(self) -> None:
        subject = {
            "subject_type": "relation",
            "relation_type": "route",
            "from_candidate_ref": entity_id("candidate", 1),
            "to_candidate_ref": entity_id("candidate", 2),
            "mode": "walking",
        }
        request = make_request()
        candidates = make_candidates(request)
        evidence = make_evidence(facts=[make_fact(subject=subject, derivation="api_estimate", sources=[api_source()])])
        result = self.bundle_result(
            [request, candidates, evidence],
            closure=BundleClosure.CLOSED,
            root=evidence["artifact_id"],
        )
        self.assert_success(result, root=evidence["artifact_id"])
        self.assertEqual(subject["from_candidate_ref"], entity_id("candidate", 1))
        self.assertEqual(subject["to_candidate_ref"], entity_id("candidate", 2))

    def test_es_03_relation_missing_endpoint_fails_schema(self) -> None:
        subject = {
            "subject_type": "relation",
            "relation_type": "route",
            "to_candidate_ref": entity_id("candidate", 2),
            "mode": "walking",
        }
        evidence = make_evidence(facts=[make_fact(subject=subject)])
        result = self.artifact_result(evidence)
        self.assert_problem(result, "SCHEMA_VALIDATION_ERROR", "/payload/facts/0/subject", "required")

    def test_es_04_closed_relation_missing_target_fails(self) -> None:
        subject = {
            "subject_type": "relation",
            "relation_type": "route",
            "from_candidate_ref": entity_id("candidate", 1),
            "to_candidate_ref": entity_id("candidate", 99),
            "mode": "walking",
        }
        request = make_request()
        candidates = make_candidates(request)
        evidence = make_evidence(facts=[make_fact(subject=subject)])
        result = self.bundle_result(
            [request, candidates, evidence],
            closure=BundleClosure.CLOSED,
            root=evidence["artifact_id"],
        )
        self.assert_problem(result, "UNRESOLVED_REFERENCE", "/payload/facts/0/subject/to_candidate_ref", "closedReference")

    def test_es_05_artifact_only_defers_candidate_artifact(self) -> None:
        evidence = make_evidence()
        result = self.bundle_result(
            [evidence],
            closure=BundleClosure.ARTIFACT_ONLY,
            root=evidence["artifact_id"],
        )
        self.assert_success(result, root=evidence["artifact_id"])
        self.assertEqual(result.value.resolved_artifact_ids, ())


class TestPlanVersionResolution(ContractTestCase):
    def diff_bundle(self, *, scope: str = "previous", entity_value: str | None = None):
        bundle = make_planning_bundle()
        previous = make_previous_plan(bundle["plan"])
        new_plan = copy.deepcopy(bundle["plan"])
        new_plan["artifact_id"] = artifact_id(16)
        new_plan["payload"]["plan_id"] = entity_id("plan", 16)
        refresh_hash(new_plan)
        diff = make_plan_diff(previous, new_plan, scope=scope, entity_value=entity_value)
        documents = [
            bundle["request"],
            bundle["parse"],
            bundle["constraints"],
            bundle["candidates"],
            bundle["evidence"],
            previous,
            new_plan,
            diff,
        ]
        return documents, previous, new_plan, diff

    def test_pv_01_plan_base_selection_has_definition(self) -> None:
        bundle = make_planning_bundle()
        plan = bundle["plan"]
        result = self.artifact_result(plan)
        self.assert_success(result)
        selection = plan["payload"]["base_selections"][0]
        self.assertEqual(selection["base_selection_id"], entity_id("base_selection", 1))

    def test_pv_02_previous_scope_resolves_snapshot_entity(self) -> None:
        documents, _, _, diff = self.diff_bundle(scope="previous")
        result = self.bundle_result(documents, closure=BundleClosure.CLOSED, root=diff["artifact_id"])
        self.assert_success(result, root=diff["artifact_id"])
        self.assertEqual(diff["payload"]["changes"][0]["entity"]["resolution_scope"], "previous")

    def test_pv_03_new_scope_resolves_new_plan_entity(self) -> None:
        documents, _, _, diff = self.diff_bundle(scope="new")
        result = self.bundle_result(documents, closure=BundleClosure.CLOSED, root=diff["artifact_id"])
        self.assert_success(result, root=diff["artifact_id"])
        self.assertEqual(diff["payload"]["changes"][0]["entity"]["resolution_scope"], "new")

    def test_pv_04_missing_previous_target_fails(self) -> None:
        documents, _, _, diff = self.diff_bundle(scope="previous", entity_value=entity_id("activity", 99))
        result = self.bundle_result(documents, closure=BundleClosure.CLOSED, root=diff["artifact_id"])
        self.assert_problem(result, "UNRESOLVED_PLAN_VERSION_ENTITY", "/payload/changes/0/entity/entity_id", "planVersionReference")

    def test_pv_05_missing_new_target_fails(self) -> None:
        documents, _, _, diff = self.diff_bundle(scope="new", entity_value=entity_id("activity", 99))
        result = self.bundle_result(documents, closure=BundleClosure.CLOSED, root=diff["artifact_id"])
        self.assert_problem(result, "UNRESOLVED_PLAN_VERSION_ENTITY", "/payload/changes/0/entity/entity_id", "planVersionReference")

    def test_pv_06_either_missing_on_both_sides_fails(self) -> None:
        documents, _, _, diff = self.diff_bundle(scope="either", entity_value=entity_id("activity", 99))
        result = self.bundle_result(documents, closure=BundleClosure.CLOSED, root=diff["artifact_id"])
        self.assert_problem(result, "UNRESOLVED_PLAN_VERSION_ENTITY", "/payload/changes/0/entity/entity_id", "planVersionReference")

    def test_pv_07_same_id_across_versions_is_not_global_duplicate(self) -> None:
        documents, previous, new_plan, diff = self.diff_bundle(scope="either")
        old_activity = previous["payload"]["snapshot"]["days"][0]["activities"][0]["activity_id"]
        new_activity = new_plan["payload"]["days"][0]["activities"][0]["activity_id"]
        self.assertEqual(old_activity, new_activity)
        result = self.bundle_result(documents, closure=BundleClosure.CLOSED, root=diff["artifact_id"])
        self.assert_success(result, root=diff["artifact_id"])
        self.assertEqual(result.value.closure, BundleClosure.CLOSED)


class TestViolationsStages(ContractTestCase):
    def pre_bundle(self):
        request = make_request()
        parsed = make_parse(request)
        constraints = make_constraints(request, parsed)
        candidates = make_candidates(request)
        evidence = make_evidence()
        violations = make_violations_pre(request, constraints, candidates, evidence)
        return [request, parsed, constraints, candidates, evidence, violations], violations

    def test_vs_01_pre_plan_proof_without_plan_ref_is_legal(self) -> None:
        documents, violations = self.pre_bundle()
        result = self.bundle_result(documents, closure=BundleClosure.CLOSED, root=violations["artifact_id"])
        self.assert_success(result, root=violations["artifact_id"])
        self.assertNotIn("plan_ref", violations["payload"])
        self.assertEqual(len(violations["payload"]["proofs"]), 1)

    def test_vs_02_pre_plan_without_proof_fails_schema(self) -> None:
        documents, violations = self.pre_bundle()
        violations["payload"]["proofs"] = []
        refresh_hash(violations)
        result = self.artifact_result(violations)
        self.assert_problem(result, "SCHEMA_VALIDATION_ERROR", "/payload/proofs", "minItems")

    def test_vs_03_pre_plan_no_plan_found_fails_schema(self) -> None:
        documents, violations = self.pre_bundle()
        violations["payload"]["plan_status"] = "no_plan_found"
        violations["payload"]["proofs"] = []
        refresh_hash(violations)
        result = self.artifact_result(violations)
        self.assert_problem(result, "SCHEMA_VALIDATION_ERROR", "/payload/plan_status", "const")

    def test_vs_04_post_plan_without_plan_ref_fails_schema(self) -> None:
        bundle = make_planning_bundle()
        violations = bundle["violations"]
        del violations["payload"]["plan_ref"]
        refresh_hash(violations)
        result = self.artifact_result(violations)
        self.assert_problem(result, "SCHEMA_VALIDATION_ERROR", "/payload", "required")

    def test_vs_05_post_plan_missing_plan_target_fails_closed(self) -> None:
        bundle = make_planning_bundle()
        violations = bundle["violations"]
        result = self.bundle_result(
            [violations],
            closure=BundleClosure.CLOSED,
            root=violations["artifact_id"],
        )
        self.assert_problem(result, "UNRESOLVED_REFERENCE", "/payload/plan_ref", "closedReference")

    def test_vs_06_post_plan_status_matches_referenced_plan(self) -> None:
        bundle = make_planning_bundle(status="conditionally_feasible")
        result = self.bundle_result(
            list(bundle.values()),
            closure=BundleClosure.CLOSED,
            root=bundle["violations"]["artifact_id"],
        )
        self.assert_success(result, root=bundle["violations"]["artifact_id"])
        self.assertEqual(
            bundle["plan"]["payload"]["plan_status"],
            bundle["violations"]["payload"]["plan_status"],
        )


class TestCandidateSnapshots(ContractTestCase):
    def test_cs_01_parent_in_current_snapshot_is_legal(self) -> None:
        request = make_request()
        candidates = make_candidates(request)
        result = self.artifact_result(candidates)
        self.assert_success(result)
        self.assertEqual(
            candidates["payload"]["candidates"][1]["parent_candidate_id"],
            candidates["payload"]["candidates"][0]["candidate_id"],
        )

    def test_cs_02_parent_only_in_history_fails(self) -> None:
        request = make_request()
        candidates = make_candidates(
            request,
            candidate_items=[
                candidate(2, "poi", parent=entity_id("candidate", 1)),
            ],
        )
        result = self.artifact_result(candidates)
        self.assert_problem(result, "UNRESOLVED_REFERENCE", "/payload/candidates/0/parent_candidate_id", "localReference")

    def test_cs_03_planner_closed_uses_explicit_candidate_snapshot(self) -> None:
        bundle = make_planning_bundle()
        result = self.bundle_result(
            [
                bundle["request"],
                bundle["parse"],
                bundle["constraints"],
                bundle["candidates"],
                bundle["evidence"],
                bundle["plan"],
            ],
            closure=BundleClosure.CLOSED,
            root=bundle["plan"]["artifact_id"],
        )
        self.assert_success(result, root=bundle["plan"]["artifact_id"])
        self.assertIn(bundle["candidates"]["artifact_id"], result.value.resolved_artifact_ids)


class TestHashAuthority(ContractTestCase):
    def test_hash_01_parse_without_output_payload_hash_is_legal(self) -> None:
        request = make_request()
        parsed = make_parse(request)
        result = self.artifact_result(parsed)
        self.assert_success(result)
        self.assertNotIn("output_payload_sha256", parsed["payload"])

    def test_hash_02_parse_output_payload_hash_is_unknown_property(self) -> None:
        request = make_request()
        parsed = make_parse(request)
        parsed["payload"]["output_payload_sha256"] = "0" * 64
        refresh_hash(parsed)
        result = self.artifact_result(parsed)
        self.assert_problem(result, "SCHEMA_VALIDATION_ERROR", "/payload", "additionalProperties")

    def test_hash_03_envelope_payload_hash_mismatch_fails(self) -> None:
        request = make_request()
        parsed = make_parse(request)
        parsed["integrity"]["payload_sha256"] = "f" * 64
        result = self.artifact_result(parsed)
        self.assert_problem(result, "PAYLOAD_HASH_MISMATCH", "/integrity/payload_sha256", "payloadHash")

    def test_hash_04_constraints_parse_ref_matches_parse_envelope_hash(self) -> None:
        request = make_request()
        parsed = make_parse(request)
        constraints = make_constraints(request, parsed)
        result = self.bundle_result(
            [request, parsed, constraints],
            closure=BundleClosure.CLOSED,
            root=constraints["artifact_id"],
        )
        self.assert_success(result, root=constraints["artifact_id"])
        self.assertEqual(
            constraints["payload"]["parse_ref"]["payload_sha256"],
            parsed["integrity"]["payload_sha256"],
        )


class TestExplicitBundleRoot(ContractTestCase):
    def test_root_01_existing_unique_root_is_legal(self) -> None:
        request = make_request()
        result = self.bundle_result(
            [request],
            closure=BundleClosure.CLOSED,
            root=request["artifact_id"],
        )
        self.assert_success(result, root=request["artifact_id"])
        self.assertEqual(result.value.resolved_artifact_ids, (request["artifact_id"],))

    def test_root_02_missing_root_fails(self) -> None:
        request = make_request()
        result = self.bundle_result(
            [request],
            closure=BundleClosure.ARTIFACT_ONLY,
            root=artifact_id(99),
        )
        self.assert_problem(result, "UNRESOLVED_BUNDLE_ROOT", "", "bundleRoot")

    def test_root_03_duplicate_artifact_id_precedes_root_resolution(self) -> None:
        request = make_request()
        duplicate = copy.deepcopy(request)
        result = self.bundle_result(
            [request, duplicate],
            closure=BundleClosure.ARTIFACT_ONLY,
            root=request["artifact_id"],
        )
        self.assert_problem(result, "DUPLICATE_ARTIFACT_ID", "/artifact_id", "uniqueArtifact")

    def test_root_04_closed_rejects_root_unreachable_artifact(self) -> None:
        request = make_request()
        extra = make_request(number=88)
        extra["payload"]["request_id"] = entity_id("request", 88)
        refresh_hash(extra)
        result = self.bundle_result(
            [request, extra],
            closure=BundleClosure.CLOSED,
            root=request["artifact_id"],
        )
        self.assert_problem(result, "UNEXPECTED_BUNDLE_ARTIFACT", "/artifact_id", "rootReachability")

    def test_root_05_artifact_only_records_root_without_closure_claim(self) -> None:
        request = make_request()
        extra = make_request(number=88)
        extra["payload"]["request_id"] = entity_id("request", 88)
        refresh_hash(extra)
        result = self.bundle_result(
            [request, extra],
            closure=BundleClosure.ARTIFACT_ONLY,
            root=request["artifact_id"],
        )
        self.assert_success(result, root=request["artifact_id"])
        self.assertEqual(result.value.resolved_artifact_ids, ())

    def test_root_06_post_plan_root_follows_selected_candidate_snapshot(self) -> None:
        bundle = make_planning_bundle()
        result = self.bundle_result(
            list(bundle.values()),
            closure=BundleClosure.CLOSED,
            root=bundle["violations"]["artifact_id"],
        )
        self.assert_success(result, root=bundle["violations"]["artifact_id"])
        self.assertIn(bundle["candidates"]["artifact_id"], result.value.resolved_artifact_ids)
        self.assertEqual(len([item for item in result.value.resolved_artifact_ids if item == bundle["candidates"]["artifact_id"]]), 1)

    def test_root_07_extra_historical_candidate_snapshot_fails(self) -> None:
        bundle = make_planning_bundle()
        historical = make_candidates(
            bundle["request"],
            number=77,
            candidate_items=[candidate(77, "destination")],
        )
        result = self.bundle_result(
            [*bundle.values(), historical],
            closure=BundleClosure.CLOSED,
            root=bundle["violations"]["artifact_id"],
        )
        self.assert_problem(result, "UNEXPECTED_BUNDLE_ARTIFACT", "/artifact_id", "rootReachability")

    def test_root_08_plan_diff_root_selects_both_versions(self) -> None:
        documents, previous, new_plan, diff = TestPlanVersionResolution.diff_bundle(self)
        result = self.bundle_result(documents, closure=BundleClosure.CLOSED, root=diff["artifact_id"])
        self.assert_success(result, root=diff["artifact_id"])
        self.assertIn(previous["artifact_id"], result.value.resolved_artifact_ids)
        self.assertIn(new_plan["artifact_id"], result.value.resolved_artifact_ids)

    def test_root_09_manifest_requires_root_artifact_id(self) -> None:
        fixture_schema = json.loads((ROOT / "schemas/fixture-case.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(fixture_schema)
        errors = tuple(Draft202012Validator(fixture_schema).iter_errors({}))
        required = {item for error in errors if error.validator == "required" for item in error.validator_value}
        self.assertIn("root_artifact_id", required)
        self.assertIn("bundle_closure", required)
        self.assertIn("documents", required)

    def test_root_10_document_order_does_not_change_explicit_root(self) -> None:
        first = make_request()
        second = make_request(number=88)
        second["payload"]["request_id"] = entity_id("request", 88)
        refresh_hash(second)
        forward = self.bundle_result(
            [first, second],
            closure=BundleClosure.ARTIFACT_ONLY,
            root=second["artifact_id"],
        )
        reverse = self.bundle_result(
            [second, first],
            closure=BundleClosure.ARTIFACT_ONLY,
            root=second["artifact_id"],
        )
        self.assert_success(forward, root=second["artifact_id"])
        self.assert_success(reverse, root=second["artifact_id"])
        self.assertEqual(forward.value.root_artifact_id, reverse.value.root_artifact_id)


if __name__ == "__main__":
    unittest.main()
