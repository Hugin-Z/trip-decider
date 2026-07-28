"""Fixture-first contract cases for the WU3 candidate Evidence Runtime."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from trip_decider.evidence_runtime import (
    REQUIRED_EVIDENCE_SLOTS,
    run_evidence_runtime,
)
from trip_decider.recovery import run_wu2_recovery
from trip_decider.schema_validation import (
    load_document,
    validate_artifact,
    validate_schema_registry,
)


ROOT = Path(__file__).resolve().parents[1]
ANCHOR = ROOT / "fixtures" / "jiangxi_multi_identity_smoke"
SCHEMA_PATHS = tuple(sorted((ROOT / "schemas").glob("*.schema.json")))

HUANGLING_REFS = (
    "candidate_1f482f01-0110-4805-8b33-0481d2022674",
    "candidate_31943b34-149b-46c1-a53f-50abde1d000d",
)
JIANGLING_REF = "candidate_0cc67cb5-47b2-4fae-a1ab-68fad0735027"
LIKENG_REF = "candidate_cf7475fc-463a-48cd-a0e9-8c8726ee3f2c"


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("expected JSON object")
    return value


class EvidenceRuntimeCase(unittest.TestCase):
    """Six independent behaviors over the committed open-data anchor."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp_root = Path(self.temporary.name)
        self.recovery_root = self.temp_root / "recovery"
        recovery = run_wu2_recovery(ANCHOR, self.recovery_root)
        self.assertEqual(recovery.problems, ())
        self.assertIsNotNone(recovery.value)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run(self, name: str):
        output_root = self.temp_root / name
        with (
            patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("network forbidden"),
            ) as urlopen_mock,
            patch(
                "http.client.HTTPConnection.request",
                side_effect=AssertionError("network forbidden"),
            ) as http_mock,
            patch(
                "socket.socket.connect",
                side_effect=AssertionError("network forbidden"),
            ) as socket_mock,
        ):
            result = run_evidence_runtime(self.recovery_root, output_root)
        self.assertEqual(urlopen_mock.call_count, 0)
        self.assertEqual(http_mock.call_count, 0)
        self.assertEqual(socket_mock.call_count, 0)
        return output_root, result

    def test_er01_candidate_local_facts_produce_valid_evidence(self) -> None:
        output_root, result = self._run("er01")
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)

        evidence_path = output_root / "evidence.json"
        loaded = load_document(
            evidence_path,
            expected_artifact_type="evidence",
        )
        self.assertEqual(loaded.problems, ())
        self.assertIsNotNone(loaded.value)
        registry = validate_schema_registry(SCHEMA_PATHS)
        self.assertEqual(registry.problems, ())
        self.assertIsNotNone(registry.value)
        validated = validate_artifact(loaded.value, registry.value)
        self.assertEqual(validated.problems, ())

        evidence = _json(evidence_path)
        payload = evidence["payload"]
        self.assertIsInstance(payload, dict)
        facts = payload["facts"]
        self.assertEqual(len(facts), 28)
        self.assertEqual(
            Counter(fact["field"] for fact in facts),
            Counter({slot: 7 for slot in REQUIRED_EVIDENCE_SLOTS}),
        )
        for fact in facts:
            self.assertEqual(fact["support_status"], "unknown")
            self.assertEqual(fact["derivation"], "rule_derived")
            self.assertEqual(fact["freshness"]["status"], "unknown")
            self.assertEqual(fact["sources"], [])
            self.assertEqual(fact["display_status"], "unknown")
            self.assertEqual(fact["conflict_source_refs"], [])
            self.assertEqual(
                fact["derivation_detail"]["input_fact_ids"],
                [],
            )

    def test_er02_subjects_and_source_references_resolve(self) -> None:
        output_root, result = self._run("er02")
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)

        candidates = _json(self.recovery_root / "candidates.json")
        candidate_items = candidates["payload"]["candidates"]
        candidate_by_id = {
            item["candidate_id"]: item for item in candidate_items
        }
        facts = _json(output_root / "evidence.json")["payload"]["facts"]
        self.assertEqual(len(candidate_by_id), 7)
        self.assertEqual(len(facts), 28)

        subject_counts: Counter[str] = Counter()
        source_fact_count = 0
        for fact in facts:
            subject = fact["subject"]
            self.assertEqual(subject["subject_type"], "entity")
            self.assertEqual(subject["entity_kind"], "candidate")
            candidate_id = subject["entity_id"]
            self.assertIn(candidate_id, candidate_by_id)
            subject_counts[candidate_id] += 1
            if fact["field"] == "source_reference":
                source_fact_count += 1
                self.assertEqual(
                    fact["value"],
                    candidate_by_id[candidate_id]["source_refs"],
                )
        self.assertEqual(set(subject_counts.values()), {4})
        self.assertEqual(source_fact_count, 7)

    def test_er03_matched_complete_seeds_are_eligible(self) -> None:
        output_root, result = self._run("er03")
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)

        gate = _json(output_root / "evidence-gate.json")
        seeds = {
            item["seed"]: item for item in gate["seed_results"]
        }
        self.assertEqual(seeds["江岭"]["identity_status"], "matched")
        self.assertEqual(seeds["江岭"]["candidate_refs"], [JIANGLING_REF])
        self.assertEqual(seeds["江岭"]["generation_status"], "ELIGIBLE")
        self.assertEqual(seeds["江岭"]["block_reasons"], [])
        self.assertEqual(seeds["李坑"]["identity_status"], "matched")
        self.assertEqual(seeds["李坑"]["candidate_refs"], [LIKENG_REF])
        self.assertEqual(seeds["李坑"]["generation_status"], "ELIGIBLE")
        self.assertEqual(seeds["李坑"]["block_reasons"], [])
        self.assertEqual(
            sum(
                item["generation_status"] == "ELIGIBLE"
                for item in gate["seed_results"]
            ),
            2,
        )

    def test_er04_ambiguous_seed_preserves_all_alternatives(self) -> None:
        output_root, result = self._run("er04")
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)

        gate = _json(output_root / "evidence-gate.json")
        huangling = next(
            item
            for item in gate["seed_results"]
            if item["seed"] == "篁岭"
        )
        self.assertEqual(huangling["identity_status"], "ambiguous")
        self.assertEqual(
            huangling["candidate_refs"],
            list(HUANGLING_REFS),
        )
        self.assertEqual(
            huangling["generation_status"],
            "BLOCKED_IDENTITY_AMBIGUOUS",
        )
        self.assertEqual(
            huangling["block_reasons"],
            ["identity_ambiguous"],
        )
        self.assertFalse(gate["generation_allowed"])

    def test_er05_unmatched_seed_has_no_placeholder(self) -> None:
        output_root, result = self._run("er05")
        self.assertEqual(result.problems, ())
        self.assertIsNotNone(result.value)

        gate = _json(output_root / "evidence-gate.json")
        qingyuan = next(
            item
            for item in gate["seed_results"]
            if item["seed"] == "庆源"
        )
        self.assertEqual(qingyuan["identity_status"], "unmatched")
        self.assertEqual(qingyuan["candidate_refs"], [])
        self.assertEqual(
            qingyuan["generation_status"],
            "BLOCKED_IDENTITY_UNMATCHED",
        )
        self.assertEqual(
            qingyuan["block_reasons"],
            ["identity_unmatched"],
        )
        evidence_text = (output_root / "evidence.json").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("placeholder", evidence_text.lower())

    def test_er06_outputs_are_deterministic_offline_and_atomic(self) -> None:
        first_root, first = self._run("er06-first")
        second_root, second = self._run("er06-second")
        self.assertEqual(first.problems, ())
        self.assertEqual(second.problems, ())
        self.assertIsNotNone(first.value)
        self.assertIsNotNone(second.value)

        filenames = ("evidence.json", "evidence-gate.json", "run-summary.json")
        self.assertEqual(
            [first_root.joinpath(name).read_bytes() for name in filenames],
            [second_root.joinpath(name).read_bytes() for name in filenames],
        )
        self.assertEqual(first.value.network_attempts, 0)
        self.assertEqual(second.value.network_attempts, 0)

        nonempty = self.temp_root / "er06-nonempty"
        nonempty.mkdir()
        marker = nonempty / "marker.txt"
        marker.write_text("preserve", encoding="utf-8")
        rejected = run_evidence_runtime(self.recovery_root, nonempty)
        self.assertIsNone(rejected.value)
        self.assertEqual(
            rejected.problems[0].error_code,
            "EVIDENCE_RUNTIME_OUTPUT_ROOT_INVALID",
        )
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

        rollback = self.temp_root / "er06-rollback"
        real_replace = os.replace
        calls = 0

        def fail_second_replace(source, target):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected installation failure")
            return real_replace(source, target)

        with patch("os.replace", side_effect=fail_second_replace):
            failed = run_evidence_runtime(self.recovery_root, rollback)
        self.assertIsNone(failed.value)
        self.assertFalse(rollback.exists())


if __name__ == "__main__":
    unittest.main()
