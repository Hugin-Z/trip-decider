from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch

from trip_decider.evidence_runtime import run_evidence_runtime
from trip_decider.live_place_resolution import (
    StructuredTripInput,
    SyntheticProviderRequest,
    replay_synthetic_normalized_snapshot,
    run_synthetic_live_place_resolution,
)
from trip_decider.schema_validation import (
    BundleClosure,
    load_document,
    validate_bundle,
    validate_schema_registry,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPOSITORY_ROOT / "schemas"
SENTINEL_KEY = "wu7-sentinel-key-must-never-persist"


def _input(
    *,
    must_visit: tuple[str, ...] = ("景点甲",),
    excluded: tuple[str, ...] = (),
    interactive: bool = False,
) -> StructuredTripInput:
    return StructuredTripInput(
        city="测试市",
        city_adcode="990100",
        start_at="2026-08-05T08:00:00+08:00",
        end_at="2026-08-06T20:00:00+08:00",
        input_recorded_at="2026-07-29T12:00:00+08:00",
        party_count=2,
        transport_modes=("walking", "transit"),
        must_visit=must_visit,
        excluded=excluded,
        locale="zh-CN",
        interactive=interactive,
    )


def _poi(
    record_id: str,
    name: str,
    *,
    location: str,
    typecode: str,
) -> dict[str, object]:
    return {
        "id": record_id,
        "name": name,
        "location": location,
        "type": "synthetic attraction",
        "typecode": typecode,
        "address": "synthetic address",
        "pname": "synthetic province",
        "cityname": "测试市",
        "adname": "synthetic district",
        "pcode": "990000",
        "citycode": "990100",
        "adcode": "990101",
    }


class FakeSyntheticTransport:
    def __init__(
        self,
        poi_responses: Mapping[str, tuple[Mapping[str, object], ...]],
        *,
        fail_seed: str | None = None,
    ) -> None:
        self.poi_responses = poi_responses
        self.fail_seed = fail_seed
        self.requests: list[SyntheticProviderRequest] = []
        self.network_attempts = 0

    def __call__(
        self,
        request: SyntheticProviderRequest,
    ) -> Mapping[str, object]:
        self.requests.append(request)
        self.assert_dekeyed(request)
        if request.operation == "district":
            return {
                "synthetic_test_data": True,
                "status": "1",
                "info": "SYNTHETIC_OK",
                "infocode": "10000",
                "count": "1",
                "districts": [
                    {
                        "name": "测试市",
                        "adcode": "990100",
                        "level": "city",
                    }
                ],
            }
        seed = str(request.parameters["keywords"])
        if seed == self.fail_seed:
            raise RuntimeError(
                "synthetic provider failure " + SENTINEL_KEY
            )
        pois = [dict(item) for item in self.poi_responses.get(seed, ())]
        return {
            "synthetic_test_data": True,
            "status": "1",
            "info": "SYNTHETIC_OK",
            "infocode": "10000",
            "count": str(len(pois)),
            "pois": pois,
        }

    @staticmethod
    def assert_dekeyed(request: SyntheticProviderRequest) -> None:
        flattened = json.dumps(
            {
                "operation": request.operation,
                "endpoint_path": request.endpoint_path,
                "parameters": dict(request.parameters),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if "key" in request.parameters or SENTINEL_KEY in flattened:
            raise AssertionError("synthetic descriptor contains a secret")


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("expected JSON object")
    return value


def _all_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class LivePlaceResolutionCase(unittest.TestCase):
    def test_ap01_structured_input_builds_closed_solver_bundle(self) -> None:
        transport = FakeSyntheticTransport(
            {
                "景点甲": (
                    _poi(
                        "SYNTH-AMAP-POI-0001",
                        "景点甲",
                        location="120.100000,30.100000",
                        typecode="110000",
                    ),
                ),
                "排除点": (),
            }
        )
        with tempfile.TemporaryDirectory(prefix="trip-decider-wu7-ap01-") as temp:
            output_root = Path(temp) / "output"
            result = run_synthetic_live_place_resolution(
                _input(excluded=("排除点",)),
                output_root,
                transport,
            )

            self.assertFalse(result.problems)
            planning_root = output_root / "planning-input"
            registry = validate_schema_registry(
                tuple(sorted(SCHEMA_ROOT.glob("*.schema.json")))
            )
            self.assertFalse(registry.problems)
            documents = tuple(
                load_document(planning_root / filename).value
                for filename in (
                    "request.yaml",
                    "constraint-parse.json",
                    "constraints.yaml",
                )
            )
            self.assertTrue(all(document is not None for document in documents))
            constraints = documents[2]
            self.assertIsNotNone(constraints)
            closed = validate_bundle(
                documents,
                registry.value,
                closure=BundleClosure.CLOSED,
                root_artifact_id=constraints.data["artifact_id"],
            )
            self.assertFalse(closed.problems)
            request = documents[0].data
            constraints_payload = constraints.data["payload"]
            self.assertEqual(request["payload"]["explicit"]["must_visit"], ["景点甲"])
            self.assertEqual(request["payload"]["explicit"]["excluded"], ["排除点"])
            self.assertTrue(
                constraints_payload["user_edit_policy"][
                    "constraints_are_solver_ssot"
                ]
            )
            self.assertFalse(
                constraints_payload["user_edit_policy"][
                    "request_auto_overwrite"
                ]
            )
            self.assertEqual(
                [
                    item["category"]
                    for item in constraints_payload["constraints"]
                ],
                ["time_window", "must_visit", "excluded"],
            )
            self.assertEqual(transport.network_attempts, 0)
            self.assertEqual(result.value.llm_calls, 0)

    def test_ap02_synthetic_run_never_reads_or_leaks_environment_key(self) -> None:
        transport = FakeSyntheticTransport(
            {
                "景点甲": (
                    _poi(
                        "SYNTH-AMAP-POI-0001",
                        "景点甲",
                        location="120.100000,30.100000",
                        typecode="110000",
                    ),
                )
            }
        )
        with tempfile.TemporaryDirectory(prefix="trip-decider-wu7-ap02-") as temp:
            output_root = Path(temp) / "output"
            with patch.dict(
                os.environ,
                {"AMAP_WEB_SERVICE_KEY": SENTINEL_KEY},
                clear=False,
            ):
                result = run_synthetic_live_place_resolution(
                    _input(),
                    output_root,
                    transport,
                )

            self.assertFalse(result.problems)
            self.assertEqual(transport.network_attempts, 0)
            self.assertEqual(result.value.network_attempts, 0)
            self.assertNotIn(
                SENTINEL_KEY.encode("utf-8"),
                b"".join(_all_files(output_root).values()),
            )
            self.assertNotIn(
                SENTINEL_KEY,
                repr(result.value) + repr(result.problems),
            )
            for request in transport.requests:
                self.assertNotIn("key", request.parameters)

    def test_ap03_exact_match_maps_gcj02_and_passes_evidence_runtime(self) -> None:
        transport = FakeSyntheticTransport(
            {
                "景点甲": (
                    _poi(
                        "SYNTH-AMAP-POI-0001",
                        " 景点甲 ",
                        location="120.100000,30.100000",
                        typecode="110000",
                    ),
                ),
                "未匹配": (),
            }
        )
        with tempfile.TemporaryDirectory(prefix="trip-decider-wu7-ap03-") as temp:
            temp_root = Path(temp)
            output_root = temp_root / "output"
            result = run_synthetic_live_place_resolution(
                _input(must_visit=("景点甲", "未匹配")),
                output_root,
                transport,
            )

            self.assertFalse(result.problems)
            candidate = _load_json(
                output_root / "resolution" / "candidates.json"
            )["payload"]["candidates"][0]
            self.assertEqual(candidate["provider"]["name"], "amap")
            self.assertEqual(candidate["provider"]["record_type"], "poi")
            self.assertEqual(
                candidate["provider"]["record_id"],
                "SYNTH-AMAP-POI-0001",
            )
            self.assertEqual(candidate["location"]["crs"], "GCJ-02")
            self.assertTrue(
                candidate["provider"]["data_policy"]["fixture_allowed"]
            )
            accounting = _load_json(
                output_root / "resolution" / "seed-accounting.json"
            )
            self.assertEqual(
                [item["status"] for item in accounting["seed_matches"]],
                ["matched", "unmatched"],
            )
            evidence_root = temp_root / "evidence"
            evidence = run_evidence_runtime(
                output_root / "resolution",
                evidence_root,
            )
            self.assertFalse(evidence.problems)
            self.assertEqual(evidence.value.candidate_count, 1)
            self.assertFalse(evidence.value.generation_allowed)
            evidence_document = _load_json(
                evidence_root / "evidence.json"
            )
            for fact in evidence_document["payload"]["facts"]:
                self.assertEqual(fact["support_status"], "unknown")
                self.assertEqual(fact["derivation"], "rule_derived")
                self.assertEqual(fact["display_status"], "unknown")
                self.assertEqual(fact["sources"], [])
            self.assertEqual(transport.network_attempts, 0)

    def test_ap04_ambiguity_requires_explicit_candidate_selection(self) -> None:
        responses = {
            "同名点": (
                _poi(
                    "SYNTH-AMAP-POI-0002",
                    "同名点",
                    location="120.200000,30.200000",
                    typecode="110001",
                ),
                _poi(
                    "SYNTH-AMAP-POI-0003",
                    "同名点",
                    location="120.300000,30.300000",
                    typecode="110002",
                ),
            )
        }
        with tempfile.TemporaryDirectory(prefix="trip-decider-wu7-ap04-") as temp:
            temp_root = Path(temp)
            first_root = temp_root / "non-interactive"
            first = run_synthetic_live_place_resolution(
                _input(must_visit=("同名点",)),
                first_root,
                FakeSyntheticTransport(responses),
            )

            selections: list[tuple[str, tuple[tuple[str, str], ...]]] = []

            def choose_second(
                seed: str,
                alternatives: tuple[tuple[str, str], ...],
            ) -> str:
                selections.append((seed, alternatives))
                return alternatives[1][0]

            second_root = temp_root / "interactive"
            second = run_synthetic_live_place_resolution(
                _input(must_visit=("同名点",), interactive=True),
                second_root,
                FakeSyntheticTransport(responses),
                selection_reader=choose_second,
            )

            self.assertFalse(first.problems)
            self.assertFalse(second.problems)
            first_accounting = _load_json(
                first_root / "resolution" / "seed-accounting.json"
            )
            second_accounting = _load_json(
                second_root / "resolution" / "seed-accounting.json"
            )
            self.assertEqual(first_accounting["seed_matches"][0]["status"], "ambiguous")
            self.assertEqual(
                len(first_accounting["seed_matches"][0]["candidate_refs"]),
                2,
            )
            self.assertEqual(second_accounting["seed_matches"][0]["status"], "matched")
            self.assertEqual(
                second_accounting["seed_matches"][0]["candidate_refs"],
                [selections[0][1][1][0]],
            )
            self.assertEqual(
                (
                    first_root / "resolution" / "candidates.json"
                ).read_bytes(),
                (
                    second_root / "resolution" / "candidates.json"
                ).read_bytes(),
            )
            selection = _load_json(second_root / "selection.json")
            self.assertEqual(len(selection["selections"][0]["alternatives"]), 2)
            self.assertEqual(
                selection["selections"][0]["selection_source"],
                "user_explicit",
            )

    def test_ap05_provider_failure_uses_fer_without_partial_success(self) -> None:
        transport = FakeSyntheticTransport({}, fail_seed="景点甲")
        with tempfile.TemporaryDirectory(prefix="trip-decider-wu7-ap05-") as temp:
            output_root = Path(temp) / "output"
            result = run_synthetic_live_place_resolution(
                _input(),
                output_root,
                transport,
            )

            self.assertIsNone(result.value)
            self.assertEqual(len(result.problems), 1)
            self.assertEqual(
                result.problems[0].error_code,
                "LIVE_PLACE_PROVIDER_FAILURE",
            )
            self.assertFalse(output_root.exists())
            evidence_path = (
                Path(temp)
                / "output.failure-evidence"
                / "acquisition-evidence.json"
            )
            evidence = _load_json(evidence_path)
            self.assertEqual(evidence["status"], "failed")
            self.assertEqual(
                evidence["terminal_failure_code"],
                "ACQUISITION_INTERNAL_FAILURE",
            )
            self.assertTrue(evidence["persistence"]["primary_status"], "succeeded")
            self.assertNotIn(
                SENTINEL_KEY.encode("utf-8"),
                evidence_path.read_bytes(),
            )
            self.assertEqual(transport.network_attempts, 0)

    def test_ap06_synthetic_replay_is_deterministic_and_transactional(self) -> None:
        transport = FakeSyntheticTransport(
            {
                "景点甲": (
                    _poi(
                        "SYNTH-AMAP-POI-0001",
                        "景点甲",
                        location="120.100000,30.100000",
                        typecode="110000",
                    ),
                )
            }
        )
        with tempfile.TemporaryDirectory(prefix="trip-decider-wu7-ap06-") as temp:
            temp_root = Path(temp)
            original_environment = os.environ.get("PYTHONPATH")
            first_root = temp_root / "first"
            first = run_synthetic_live_place_resolution(
                _input(),
                first_root,
                transport,
            )
            replay_root = temp_root / "replay"
            replay = replay_synthetic_normalized_snapshot(
                first_root / "provider-observation",
                replay_root,
            )

            self.assertFalse(first.problems)
            self.assertFalse(replay.problems)
            self.assertEqual(_all_files(first_root), _all_files(replay_root))
            self.assertEqual(os.environ.get("PYTHONPATH"), original_environment)

            occupied_root = temp_root / "occupied"
            occupied_root.mkdir()
            marker = occupied_root / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            refused = replay_synthetic_normalized_snapshot(
                first_root / "provider-observation",
                occupied_root,
            )
            self.assertIsNone(refused.value)
            self.assertEqual(
                refused.problems[0].error_code,
                "LIVE_PLACE_OUTPUT_ROOT_INVALID",
            )
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
            self.assertEqual(
                [
                    path.name
                    for path in temp_root.iterdir()
                    if ".staging-" in path.name
                ],
                [],
            )
            self.assertEqual(transport.network_attempts, 0)


if __name__ == "__main__":
    unittest.main()
