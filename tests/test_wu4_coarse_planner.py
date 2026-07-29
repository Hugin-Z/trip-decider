"""Fixture-first cases for the WU4 conditional coarse planner.

Source: Recovery and Evidence inputs are produced offline from the committed
``jiangxi_multi_identity_smoke`` open-data anchor.  The planning request,
constraint parse, normalized constraints, and every expected value are
independently written in this test from the approved WU4-CP contract.

Coverage: explicit constraint projection, eligible-candidate admission,
blocked identity preservation, one-per-day unscheduled allocation,
conditional/no-plan status, deterministic output, and atomic installation.

Non-coverage: natural-language parsing, identity resolution, route or opening
hours evidence, activity duration, optimization, recommendation, or UI.
"""

from __future__ import annotations

import copy
import json
import os
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import yaml

from trip_decider.adapters.contracts import (
    stable_artifact_id,
    stable_identifier,
)
from trip_decider.coarse_planner import run_coarse_planner
from trip_decider.evidence_runtime import run_evidence_runtime
from trip_decider.recovery import run_wu2_recovery
from trip_decider.schema_validation import (
    BundleClosure,
    canonical_payload_sha256,
    load_document,
    validate_bundle,
    validate_schema_registry,
)


ROOT = Path(__file__).resolve().parents[1]
ANCHOR = ROOT / "fixtures" / "jiangxi_multi_identity_smoke"
SCHEMA_PATHS = tuple(sorted((ROOT / "schemas").glob("*.schema.json")))

REQUEST_ARTIFACT_ID = "urn:uuid:20000001-0000-4000-8000-000000000001"
REQUEST_ID = "request_20000001-0000-4000-8000-000000000001"
REQUEST_PAYLOAD_SHA256 = (
    "b49538aa6aea6526e4154e7aa18053ec343c3c5fa7a2436bdfb4f43143593823"
)
JIANGLING_REF = "candidate_0cc67cb5-47b2-4fae-a1ab-68fad0735027"
LIKENG_REF = "candidate_cf7475fc-463a-48cd-a0e9-8c8726ee3f2c"
HUANGLING_REFS = (
    "candidate_1f482f01-0110-4805-8b33-0481d2022674",
    "candidate_31943b34-149b-46c1-a53f-50abde1d000d",
)
TIME_CONSTRAINT_ID = "constraint_40000001-0000-4000-8000-000000000001"
MUST_CONSTRAINT_ID = "constraint_40000002-0000-4000-8000-000000000002"


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("expected JSON object")
    return value


def _artifact_ref(document: dict[str, object]) -> dict[str, object]:
    return {
        "artifact_id": document["artifact_id"],
        "artifact_type": document["artifact_type"],
        "schema_version": document["schema_version"],
        "payload_sha256": document["integrity"]["payload_sha256"],
    }


def _envelope(
    artifact_type: str,
    payload: dict[str, object],
    *,
    created_at: str,
    run_identity: str,
) -> dict[str, object]:
    payload_hash = canonical_payload_sha256(payload)
    return {
        "schema_version": "0.1.0",
        "artifact_id": stable_artifact_id(artifact_type, payload_hash),
        "artifact_type": artifact_type,
        "created_at": created_at,
        "producer": {
            "name": "wu4-coarse-planner-test-input",
            "version": "0.1.0",
            "run_id": stable_identifier(
                "run",
                "trip-decider:test:wu4-planning-input",
                run_identity,
            ),
        },
        "provenance": {
            "parent_artifact_ids": [],
            "input_hashes": [],
            "pipeline_stage": "wu4-coarse-planner-test-input",
        },
        "integrity": {
            "payload_sha256": payload_hash,
            "canonicalization": "canonical-json-v1",
        },
        "payload": payload,
    }


def _request_document() -> dict[str, object]:
    payload = {
        "explicit": {
            "destination": {
                "name": "婺源县",
                "selection_mode": "fixed",
            },
            "origin": {
                "kind": "user_input",
                "value": "wu2r-resume-anchor:origin-unspecified",
            },
            "party": {"count": 1},
            "preferences_raw": [
                "WU2R真实开放数据锚点；不代表推荐、路线或可行行程。"
            ],
            "transport_modes": ["walking"],
            "travel_window": {
                "end": "2026-08-05T20:00:00+08:00",
                "start": "2026-08-05T08:00:00+08:00",
                "timezone": "Asia/Shanghai",
            },
        },
        "natural_language": (
            "固定婺源县作为开放数据锚点范围；仅回放候选池，不执行推荐或规划。"
        ),
        "request_id": REQUEST_ID,
        "user_input_refs": [
            {
                "kind": "user_input",
                "value": "wu2r-resume-anchor:request",
            }
        ],
    }
    if canonical_payload_sha256(payload) != REQUEST_PAYLOAD_SHA256:
        raise AssertionError("handwritten request payload drifted")
    return {
        "artifact_id": REQUEST_ARTIFACT_ID,
        "artifact_type": "request",
        "created_at": "2026-07-28T08:40:51.708Z",
        "integrity": {
            "canonicalization": "canonical-json-v1",
            "payload_sha256": REQUEST_PAYLOAD_SHA256,
        },
        "payload": payload,
        "producer": {
            "name": "trip-decider-wu2r-resume-fixture",
            "run_id": "run_20000001-0000-4000-8000-000000000001",
            "version": "0.1.0",
        },
        "provenance": {
            "input_hashes": [
                {
                    "name": "approved-resume-plan",
                    "sha256": (
                        "aae5da96f11c367e450522cbafdd1a764"
                        "8ad527b42fbfc642c0fcdf355699674"
                    ),
                }
            ],
            "parent_artifact_ids": [],
            "pipeline_stage": "wu2r-resume-fixture-request",
        },
        "schema_version": "0.1.0",
    }


def _planning_documents(day_count: int) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    if day_count not in {1, 2}:
        raise AssertionError("test supports one or two explicit days")
    request = _request_document()
    parsed_payload = {
        "request_id": REQUEST_ID,
        "request_ref": _artifact_ref(request),
        "parser": {
            "name": "wu4-structured-test-input",
            "version": "0.1.0",
            "kind": "user_structured",
        },
        "parsed_constraints": [],
        "parse_notes": [
            "Planning constraints are explicit user edits; no NL parse ran."
        ],
        "needs_confirmation": False,
    }
    parsed = _envelope(
        "constraint-parse",
        parsed_payload,
        created_at="2026-07-29T08:00:00+08:00",
        run_identity=f"parse-{day_count}",
    )
    end_date = "2026-08-06" if day_count == 2 else "2026-08-05"
    edit_locator = {
        "kind": "user_input",
        "value": f"wu4-test:explicit-{day_count}-day-constraints",
    }
    constraints_payload = {
        "constraint_set_id": stable_identifier(
            "constraint_set",
            "trip-decider:test:wu4-constraint-set",
            str(day_count),
        ),
        "request_ref": _artifact_ref(request),
        "parse_ref": _artifact_ref(parsed),
        "revision": 1,
        "constraints": [
            {
                "constraint_id": TIME_CONSTRAINT_ID,
                "layer": "hard",
                "category": "time_window",
                "operator": "within",
                "target_refs": [
                    {
                        "target_type": "request_scope",
                        "request_id": REQUEST_ID,
                        "scope_kind": "travel_window",
                    }
                ],
                "value": f"2026-08-05/{end_date}",
                "unit": None,
                "origin": {
                    "kind": "user_edited",
                    "replaced_value": "2026-08-05/2026-08-05",
                    "edited_at": "2026-07-29T08:00:00+08:00",
                    "locator": edit_locator,
                },
                "enabled": True,
            },
            {
                "constraint_id": MUST_CONSTRAINT_ID,
                "layer": "hard",
                "category": "must_visit",
                "operator": "include",
                "target_refs": [
                    {
                        "target_type": "request_scope",
                        "request_id": REQUEST_ID,
                        "scope_kind": "must_visit",
                    }
                ],
                "value": ["江岭", "李坑", "篁岭", "庆源"],
                "unit": None,
                "origin": {
                    "kind": "user_edited",
                    "replaced_value": [],
                    "edited_at": "2026-07-29T08:00:00+08:00",
                    "locator": edit_locator,
                },
                "enabled": True,
            },
        ],
        "user_edit_policy": {
            "constraints_are_solver_ssot": True,
            "request_auto_overwrite": False,
        },
    }
    constraints = _envelope(
        "constraints",
        constraints_payload,
        created_at="2026-07-29T08:00:00+08:00",
        run_identity=f"constraints-{day_count}",
    )
    return request, parsed, constraints


def _write_planning_root(root: Path, day_count: int) -> None:
    request, parsed, constraints = _planning_documents(day_count)
    root.mkdir()
    (root / "request.yaml").write_text(
        yaml.safe_dump(
            request,
            allow_unicode=True,
            sort_keys=True,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (root / "constraint-parse.json").write_text(
        json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / "constraints.yaml").write_text(
        yaml.safe_dump(
            constraints,
            allow_unicode=True,
            sort_keys=True,
        ),
        encoding="utf-8",
        newline="\n",
    )


class CoarsePlannerCase(unittest.TestCase):
    """Six independent behaviors over real offline upstream outputs."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            prefix="trip-decider-wu4-cp-"
        )
        self.temp_root = Path(self.temporary.name)
        self.recovery_root = self.temp_root / "recovery"
        recovery = run_wu2_recovery(ANCHOR, self.recovery_root)
        self.assertEqual(recovery.problems, ())
        self.assertIsNotNone(recovery.value)
        self.evidence_root = self.temp_root / "evidence"
        evidence = run_evidence_runtime(
            self.recovery_root,
            self.evidence_root,
        )
        self.assertEqual(evidence.problems, ())
        self.assertIsNotNone(evidence.value)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _planning_root(self, name: str, day_count: int = 2) -> Path:
        root = self.temp_root / name
        _write_planning_root(root, day_count)
        return root

    def _run(
        self,
        name: str,
        *,
        day_count: int = 2,
        output_root: Path | None = None,
    ):
        planning_root = self._planning_root(
            f"{name}-planning",
            day_count,
        )
        destination = output_root or self.temp_root / f"{name}-output"
        with (
            patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("network forbidden"),
            ) as socket_mock,
            patch.object(
                urllib.request,
                "urlopen",
                side_effect=AssertionError("network forbidden"),
            ) as urlopen_mock,
        ):
            try:
                result = run_coarse_planner(
                    self.recovery_root,
                    self.evidence_root,
                    planning_root,
                    destination,
                )
            except NotImplementedError:
                self.assertEqual(socket_mock.call_count, 0)
                self.assertEqual(urlopen_mock.call_count, 0)
                raise
        self.assertEqual(socket_mock.call_count, 0)
        self.assertEqual(urlopen_mock.call_count, 0)
        return planning_root, destination, result

    def _formal_documents(
        self,
        planning_root: Path,
        output_root: Path,
        *,
        include_violations: bool,
    ):
        paths = [
            planning_root / "request.yaml",
            planning_root / "constraint-parse.json",
            planning_root / "constraints.yaml",
            self.recovery_root / "candidates.json",
            self.evidence_root / "evidence.json",
            output_root / "plan.json",
        ]
        if include_violations:
            paths.append(output_root / "violations.json")
        documents = []
        for path in paths:
            loaded = load_document(path)
            self.assertEqual(loaded.problems, ())
            self.assertIsNotNone(loaded.value)
            documents.append(loaded.value)
        return documents

    def test_cp01_two_days_produce_conditional_unscheduled_plan(self) -> None:
        planning_root, output_root, result = self._run("cp01")
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)

        plan = _json(output_root / "plan.json")
        self.assertEqual(
            plan["payload"]["plan_status"],
            "conditionally_feasible",
        )
        days = plan["payload"]["days"]
        self.assertEqual(
            [day["date"] for day in days],
            ["2026-08-05", "2026-08-06"],
        )
        self.assertEqual(
            [
                day["activities"][0]["candidate_ref"]
                for day in days
            ],
            [JIANGLING_REF, LIKENG_REF],
        )
        for day in days:
            self.assertEqual(day["legs"], [])
            self.assertEqual(len(day["activities"]), 1)
            self.assertEqual(
                day["activities"][0]["timing_status"],
                "day_assigned_unscheduled",
            )

        registry = validate_schema_registry(SCHEMA_PATHS)
        self.assertEqual(registry.problems, ())
        self.assertIsNotNone(registry.value)
        plan_documents = self._formal_documents(
            planning_root,
            output_root,
            include_violations=False,
        )
        plan_bundle = validate_bundle(
            plan_documents,
            registry.value,
            closure=BundleClosure.CLOSED,
            root_artifact_id=plan["artifact_id"],
        )
        self.assertEqual(plan_bundle.problems, ())
        violations = _json(output_root / "violations.json")
        violations_bundle = validate_bundle(
            self._formal_documents(
                planning_root,
                output_root,
                include_violations=True,
            ),
            registry.value,
            closure=BundleClosure.CLOSED,
            root_artifact_id=violations["artifact_id"],
        )
        self.assertEqual(violations_bundle.problems, ())

    def test_cp02_blocked_seeds_remain_outside_activities(self) -> None:
        _, output_root, result = self._run("cp02")
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)

        plan = _json(output_root / "plan.json")
        activity_refs = [
            activity["candidate_ref"]
            for day in plan["payload"]["days"]
            for activity in day["activities"]
        ]
        self.assertEqual(activity_refs, [JIANGLING_REF, LIKENG_REF])
        self.assertTrue(set(activity_refs).isdisjoint(HUANGLING_REFS))

        gate = _json(output_root / "planning-gate.json")
        blocked = {item["seed"]: item for item in gate["blocked_seeds"]}
        self.assertEqual(
            blocked["篁岭"]["generation_status"],
            "BLOCKED_IDENTITY_AMBIGUOUS",
        )
        self.assertEqual(
            blocked["篁岭"]["candidate_refs"],
            list(HUANGLING_REFS),
        )
        self.assertEqual(
            blocked["篁岭"]["block_reasons"],
            ["identity_ambiguous"],
        )
        self.assertEqual(
            blocked["庆源"]["generation_status"],
            "BLOCKED_IDENTITY_UNMATCHED",
        )
        self.assertEqual(blocked["庆源"]["candidate_refs"], [])
        self.assertEqual(
            blocked["庆源"]["block_reasons"],
            ["identity_unmatched"],
        )
        evaluations = {
            item["constraint_ref"]: item["result"]
            for item in plan["payload"]["constraint_evaluations"]
        }
        self.assertEqual(evaluations[MUST_CONSTRAINT_ID], "conditional")

    def test_cp03_partial_draft_does_not_raise_generation_gate(self) -> None:
        _, output_root, result = self._run("cp03")
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)

        input_gate = _json(self.evidence_root / "evidence-gate.json")
        output_gate = _json(output_root / "planning-gate.json")
        self.assertFalse(input_gate["generation_allowed"])
        self.assertFalse(output_gate["generation_allowed_input"])
        self.assertTrue(output_gate["draft_created"])
        self.assertFalse(output_gate["publishable"])
        self.assertEqual(
            output_gate["planning_status"],
            "conditionally_feasible",
        )
        self.assertEqual(
            output_gate["scheduled_candidate_refs"],
            [JIANGLING_REF, LIKENG_REF],
        )

    def test_cp04_insufficient_days_returns_no_plan_found(self) -> None:
        _, output_root, result = self._run("cp04", day_count=1)
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)

        plan = _json(output_root / "plan.json")
        self.assertEqual(plan["payload"]["plan_status"], "no_plan_found")
        self.assertEqual(plan["payload"]["days"], [])
        self.assertEqual(plan["payload"]["proof_refs"], [])
        gate = _json(output_root / "planning-gate.json")
        self.assertFalse(gate["draft_created"])
        self.assertFalse(gate["publishable"])
        self.assertEqual(gate["scheduled_candidate_refs"], [])
        self.assertEqual(
            gate["unscheduled_eligible_candidate_refs"],
            [JIANGLING_REF, LIKENG_REF],
        )
        self.assertEqual(
            gate["no_plan_reason"],
            "INSUFFICIENT_DAY_CAPACITY_FOR_ONE_PER_DAY_ALLOCATOR",
        )
        violations = _json(output_root / "violations.json")
        self.assertEqual(
            violations["payload"]["plan_status"],
            "no_plan_found",
        )
        self.assertEqual(violations["payload"]["proofs"], [])
        self.assertEqual(
            violations["payload"]["violations"][0]["kind"],
            "conditional",
        )
        message = violations["payload"]["violations"][0]["message"].lower()
        self.assertIn("not prove infeasibility", message)
        self.assertNotIn("proven infeasible", message)

    def test_cp05_plan_contains_no_fabricated_operational_values(self) -> None:
        _, output_root, result = self._run("cp05")
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)

        plan = _json(output_root / "plan.json")
        self.assertEqual(plan["payload"]["base_selections"], [])
        self.assertEqual(
            plan["payload"]["objective_breakdown"]["components"],
            [],
        )
        for day in plan["payload"]["days"]:
            self.assertEqual(day["legs"], [])
            for activity in day["activities"]:
                self.assertEqual(
                    set(activity),
                    {
                        "activity_id",
                        "candidate_ref",
                        "constraint_refs",
                        "evidence_fact_refs",
                        "timing_status",
                    },
                )
                self.assertNotIn("start_at", activity)
                self.assertNotIn("end_at", activity)
        serialized = json.dumps(plan, ensure_ascii=False, sort_keys=True)
        for forbidden_key in (
            '"duration_minutes"',
            '"distance"',
            '"opening_hours"',
            '"ranking"',
            '"recommendation"',
        ):
            self.assertNotIn(forbidden_key, serialized)

    def test_cp06_output_is_deterministic_offline_and_atomic(self) -> None:
        _, first_root, first = self._run("cp06-first")
        _, second_root, second = self._run("cp06-second")
        self.assertEqual(first.problems, ())
        self.assertEqual(second.problems, ())
        self.assertIsNotNone(first.value)
        self.assertIsNotNone(second.value)
        filenames = (
            "plan.json",
            "violations.json",
            "planning-gate.json",
            "run-summary.json",
        )
        self.assertEqual(
            [first_root.joinpath(name).read_bytes() for name in filenames],
            [second_root.joinpath(name).read_bytes() for name in filenames],
        )
        self.assertEqual(first.value.network_attempts, 0)
        self.assertEqual(first.value.llm_calls, 0)

        nonempty = self.temp_root / "cp06-nonempty"
        nonempty.mkdir()
        marker = nonempty / "marker.txt"
        marker.write_text("preserve", encoding="utf-8")
        _, _, rejected = self._run(
            "cp06-nonempty-run",
            output_root=nonempty,
        )
        self.assertIsNone(rejected.value)
        self.assertEqual(
            rejected.problems[0].error_code,
            "COARSE_PLANNER_OUTPUT_ROOT_INVALID",
        )
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

        rollback_root = self.temp_root / "cp06-rollback"
        real_replace = os.replace
        replace_calls = 0

        def fail_second_replace(source, target):
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 2:
                raise OSError("injected install failure")
            return real_replace(source, target)

        planning_root = self._planning_root("cp06-rollback-planning")
        with patch(
            "trip_decider.coarse_planner.os.replace",
            side_effect=fail_second_replace,
        ):
            rollback = run_coarse_planner(
                self.recovery_root,
                self.evidence_root,
                planning_root,
                rollback_root,
            )
        self.assertIsNone(rollback.value)
        self.assertEqual(
            rollback.problems[0].error_code,
            "COARSE_PLANNER_OUTPUT_ROOT_INVALID",
        )
        self.assertFalse(rollback_root.exists())
