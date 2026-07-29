"""WU4-UC deterministic contract cases.

Source: synthetic structures written independently from the approved WU4-UC
specification. Coverage: legacy timed compatibility, explicit day assignment,
conditional Plan acceptance, and rejection of missing, partial, mixed, null,
or empty timing representations. Non-coverage: time ordering, planning,
feasibility, routes, opening hours, real-world truth, network, and LLM use.
"""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from trip_decider.schema_validation import (
    LoadedDocument,
    SchemaRegistry,
    ValidationProblem,
    validate_artifact,
    validate_schema_registry,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATHS = tuple(sorted((ROOT / "schemas").glob("*.schema.json")))


def entity_id(kind: str, number: int) -> str:
    return f"{kind}_{number:08x}-0000-4000-8000-{number:012x}"


def artifact_id(number: int) -> str:
    return f"urn:uuid:{number:08x}-0000-4000-8000-{number:012x}"


def payload_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def artifact_ref(artifact_type: str, number: int) -> dict[str, object]:
    return {
        "artifact_id": artifact_id(number),
        "artifact_type": artifact_type,
        "schema_version": "0.1.0",
        "payload_sha256": f"{number:064x}",
    }


def envelope(
    artifact_type: str,
    payload: dict[str, object],
    number: int,
) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "artifact_id": artifact_id(number),
        "artifact_type": artifact_type,
        "created_at": "2026-07-29T08:00:00+08:00",
        "producer": {
            "name": "wu4-contract-test",
            "version": "0.1.0",
            "run_id": entity_id("run", number),
        },
        "provenance": {
            "parent_artifact_ids": [],
            "input_hashes": [],
            "pipeline_stage": "wu4-unscheduled-activity-contract",
        },
        "integrity": {
            "payload_sha256": payload_sha256(payload),
            "canonicalization": "canonical-json-v1",
        },
        "payload": payload,
    }


def activity(**timing: object) -> dict[str, object]:
    value: dict[str, object] = {
        "activity_id": entity_id("activity", 1),
        "candidate_ref": entity_id("candidate", 1),
        "constraint_refs": [entity_id("constraint", 1)],
        "evidence_fact_refs": [entity_id("fact", 1)],
    }
    value.update(timing)
    return value


def day(value: dict[str, object]) -> dict[str, object]:
    return {
        "day_id": entity_id("day", 1),
        "date": "2026-08-05",
        "activities": [value],
        "legs": [],
    }


def previous_plan(value: dict[str, object]) -> dict[str, object]:
    payload = {
        "previous_plan_id": entity_id("plan", 1),
        "previous_plan_artifact_ref": artifact_ref("plan", 1),
        "baseline_constraint_set_id": entity_id("constraint_set", 1),
        "snapshot": {
            "base_selections": [],
            "days": [day(value)],
        },
        "snapshot_created_at": "2026-07-29T08:00:00+08:00",
    }
    return envelope("previous-plan", payload, 9)


def conditional_plan(value: dict[str, object]) -> dict[str, object]:
    payload = {
        "plan_id": entity_id("plan", 2),
        "request_ref": artifact_ref("request", 1),
        "constraint_set_ref": artifact_ref("constraints", 2),
        "candidate_set_ref": artifact_ref("candidates", 3),
        "evidence_set_ref": artifact_ref("evidence", 4),
        "plan_status": "conditionally_feasible",
        "conditions": [
            {
                "condition_id": "condition_unscheduled_time",
                "description": "Activity time remains unscheduled.",
                "constraint_refs": [entity_id("constraint", 1)],
                "evidence_fact_refs": [entity_id("fact", 1)],
            }
        ],
        "base_selections": [],
        "days": [day(value)],
        "excluded_candidates": [],
        "constraint_evaluations": [
            {
                "constraint_ref": entity_id("constraint", 1),
                "result": "conditional",
            }
        ],
        "objective_breakdown": {
            "components": [{"name": "day_assignment", "value": 1}]
        },
        "proof_refs": [],
    }
    return envelope("plan", payload, 10)


class UnscheduledActivityContractCase(unittest.TestCase):
    """Six independent structural behaviors over synthetic documents."""

    registry: SchemaRegistry

    @classmethod
    def setUpClass(cls) -> None:
        result = validate_schema_registry(SCHEMA_PATHS)
        if result.problems or result.value is None:
            raise AssertionError(f"schema registry failed: {result.problems!r}")
        cls.registry = result.value

    def validate(
        self,
        document: dict[str, object],
        name: str,
    ) -> tuple[ValidationProblem, ...]:
        result = validate_artifact(
            LoadedDocument(path=Path(name), data=document),
            self.registry,
        )
        return result.problems

    def assert_schema_invalid(
        self,
        document: dict[str, object],
        name: str,
    ) -> None:
        problems = self.validate(document, name)
        self.assertGreaterEqual(len(problems), 1)
        self.assertTrue(
            all(problem.error_code == "SCHEMA_VALIDATION_ERROR" for problem in problems)
        )

    def test_uc01_legacy_timed_activity_remains_valid(self) -> None:
        document = previous_plan(
            activity(
                start_at="2026-08-05T09:00:00+08:00",
                end_at="2026-08-05T11:00:00+08:00",
            )
        )
        self.assertEqual(self.validate(document, "uc01.json"), ())

    def test_uc02_day_assigned_unscheduled_activity_becomes_valid(self) -> None:
        document = previous_plan(
            activity(timing_status="day_assigned_unscheduled")
        )
        self.assertEqual(self.validate(document, "uc02.json"), ())

        snapshot = document["payload"]["snapshot"]
        assigned_day = snapshot["days"][0]
        assigned_activity = assigned_day["activities"][0]
        self.assertEqual(assigned_day["date"], "2026-08-05")
        self.assertEqual(
            assigned_activity["timing_status"],
            "day_assigned_unscheduled",
        )
        self.assertNotIn("start_at", assigned_activity)
        self.assertNotIn("end_at", assigned_activity)

    def test_uc03_conditionally_feasible_plan_accepts_unscheduled_activity(
        self,
    ) -> None:
        document = conditional_plan(
            activity(timing_status="day_assigned_unscheduled")
        )
        self.assertEqual(self.validate(document, "uc03.json"), ())

        payload = document["payload"]
        self.assertEqual(payload["plan_status"], "conditionally_feasible")
        self.assertEqual(len(payload["conditions"]), 1)
        self.assertEqual(len(payload["days"]), 1)
        self.assertEqual(len(payload["days"][0]["activities"]), 1)

    def test_uc04_missing_both_timing_modes_remains_invalid(self) -> None:
        self.assert_schema_invalid(
            previous_plan(activity()),
            "uc04.json",
        )

    def test_uc05_mixed_or_partial_timing_remains_invalid(self) -> None:
        variants = (
            activity(start_at="2026-08-05T09:00:00+08:00"),
            activity(end_at="2026-08-05T11:00:00+08:00"),
            activity(
                timing_status="timed",
                start_at="2026-08-05T09:00:00+08:00",
            ),
            activity(
                timing_status="timed",
                end_at="2026-08-05T11:00:00+08:00",
            ),
            activity(
                timing_status="day_assigned_unscheduled",
                start_at="2026-08-05T09:00:00+08:00",
            ),
            activity(
                timing_status="day_assigned_unscheduled",
                start_at="2026-08-05T09:00:00+08:00",
                end_at="2026-08-05T11:00:00+08:00",
            ),
            activity(
                timing_status="unknown",
                start_at="2026-08-05T09:00:00+08:00",
                end_at="2026-08-05T11:00:00+08:00",
            ),
        )
        for index, value in enumerate(variants):
            with self.subTest(index=index):
                self.assert_schema_invalid(
                    previous_plan(copy.deepcopy(value)),
                    f"uc05-{index}.json",
                )

    def test_uc06_null_and_empty_placeholders_remain_invalid(self) -> None:
        variants = (
            activity(
                start_at=None,
                end_at="2026-08-05T11:00:00+08:00",
            ),
            activity(
                start_at="2026-08-05T09:00:00+08:00",
                end_at=None,
            ),
            activity(
                start_at="",
                end_at="2026-08-05T11:00:00+08:00",
            ),
            activity(
                start_at="2026-08-05T09:00:00+08:00",
                end_at="",
            ),
            activity(
                timing_status="day_assigned_unscheduled",
                start_at=None,
                end_at=None,
            ),
        )
        for index, value in enumerate(variants):
            with self.subTest(index=index):
                self.assert_schema_invalid(
                    previous_plan(copy.deepcopy(value)),
                    f"uc06-{index}.json",
                )
