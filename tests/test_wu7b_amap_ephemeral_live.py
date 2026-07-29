from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from collections.abc import Mapping
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

from trip_decider.amap_ephemeral_live import (
    AMAP_CREDENTIAL_MISSING,
    AMAP_PROVIDER_FAILURE,
    AMAP_P2_CLEANUP_FAILED,
    AmapEphemeralLiveConfig,
    AmapLiveRequest,
    run_amap_ephemeral_live,
)
from trip_decider.live_place_resolution import StructuredTripInput
from trip_decider.schema_validation import (
    BundleClosure,
    load_document,
    validate_artifact,
    validate_bundle,
    validate_schema_registry,
)


SENTINEL_KEY = "WU7B-SECRET-SENTINEL-DO-NOT-PERSIST"
PROVIDER_ID_A = "AMAP-LIVE-ID-0001"
PROVIDER_ID_B = "AMAP-LIVE-ID-0002"
PROVIDER_ADDRESS = "PROVIDER-ADDRESS-SECRET"
PROVIDER_LOCATION_A = "121.490317,31.241701"
PROVIDER_LOCATION_B = "121.491317,31.242701"
PROVIDER_CATEGORY = "PROVIDER-CATEGORY-SECRET"
PROVIDER_TYPECODE = "110000"
PROVIDER_ADCODE = "310101"
FINAL_FILES = {
    "planning-input/request.yaml",
    "planning-input/constraint-parse.json",
    "planning-input/constraints.yaml",
    "planning/plan.json",
    "planning/planning-gate.json",
    "planning/violations.json",
    "planning/run-summary.json",
    "report/index.html",
    "run-summary.json",
}


def _input(
    *,
    must_visit: tuple[str, ...] = ("景点甲", "未匹配"),
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
        excluded=(),
        locale="zh-CN",
        interactive=interactive,
    )


def _district_response() -> bytes:
    return json.dumps(
        {
            "status": "1",
            "info": "OK",
            "infocode": "10000",
            "count": "1",
            "districts": [
                {
                    "name": "测试市",
                    "adcode": "990100",
                    "level": "city",
                }
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")


def _poi(
    record_id: str,
    name: str,
    *,
    location: str,
) -> dict[str, object]:
    return {
        "id": record_id,
        "name": name,
        "location": location,
        "type": PROVIDER_CATEGORY,
        "typecode": PROVIDER_TYPECODE,
        "address": PROVIDER_ADDRESS,
        "pname": "测试省",
        "cityname": "测试市",
        "adname": "测试区",
        "pcode": "990000",
        "citycode": "990100",
        "adcode": PROVIDER_ADCODE,
    }


def _poi_response(pois: tuple[Mapping[str, object], ...]) -> bytes:
    return json.dumps(
        {
            "status": "1",
            "info": "OK",
            "infocode": "10000",
            "count": str(len(pois)),
            "pois": [dict(item) for item in pois],
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")


class FakeLiveTransport:
    def __init__(
        self,
        responses: Mapping[str, tuple[Mapping[str, object], ...]],
        *,
        failure: str | None = None,
    ) -> None:
        self.responses = responses
        self.failure = failure
        self.requests: list[AmapLiveRequest] = []
        self.credentials: list[str] = []
        self.network_attempts = 0

    def __call__(
        self,
        request: AmapLiveRequest,
        credential: str,
    ) -> bytes:
        self.network_attempts += 1
        self.requests.append(request)
        self.credentials.append(credential)
        failure_prefix = request.operation + "_"
        if self.failure == failure_prefix + "transport":
            raise OSError("sanitized fake transport failure")
        if self.failure == failure_prefix + "http":
            raise urllib.error.HTTPError(
                "https://provider.invalid/?key=" + SENTINEL_KEY,
                403,
                "provider detail must not escape",
                None,
                io.BytesIO(b'{"forbidden":"provider response body"}'),
            )
        if request.operation == "district":
            if self.failure == "district_api":
                return json.dumps(
                    {
                        "status": "0",
                        "info": "FAKE_FAILURE",
                        "infocode": "20000",
                        "count": "0",
                        "districts": [],
                    }
                ).encode("utf-8")
            if self.failure == "district_invalid_json":
                return b"{not-json"
            if self.failure == "district_invalid_shape":
                return json.dumps(
                    {
                        "status": "1",
                        "infocode": "10000",
                        "districts": {},
                    }
                ).encode("utf-8")
            return _district_response()
        seed = request.parameters["keywords"]
        if self.failure == "poi_api":
            return json.dumps(
                {
                    "status": "0",
                    "info": "FAKE_FAILURE",
                    "infocode": "20000",
                    "count": "0",
                    "pois": [],
                }
            ).encode("utf-8")
        if self.failure == "poi_invalid_json":
            return b"{not-json"
        if self.failure == "poi_invalid_shape":
            return json.dumps(
                {
                    "status": "1",
                    "infocode": "10000",
                    "count": "0",
                    "pois": {},
                }
            ).encode("utf-8")
        if self.failure == "result_window":
            return json.dumps(
                {
                    "status": "1",
                    "info": "OK",
                    "infocode": "10000",
                    "count": "2",
                    "pois": [],
                }
            ).encode("utf-8")
        return _poi_response(self.responses.get(seed, ()))


def _config(
    *,
    must_visit: tuple[str, ...] = ("景点甲", "未匹配"),
    interactive: bool = False,
    selections: Mapping[str, int] | None = None,
) -> AmapEphemeralLiveConfig:
    return AmapEphemeralLiveConfig(
        structured_input=_input(
            must_visit=must_visit,
            interactive=interactive,
        ),
        selection_ordinals=dict(selections or {}),
    )


def _result_code(result: object) -> str:
    problems = getattr(result, "problems")
    if len(problems) != 1:
        raise AssertionError(problems)
    return problems[0].error_code


def _tree_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def _tree_bytes(root: Path) -> bytes:
    return b"\n".join(
        path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


class AmapEphemeralLiveCase(unittest.TestCase):
    """Handwritten provider-shaped fixtures; no live-provider assertions."""

    def test_p201_structured_input_builds_closed_planning_bundle(self) -> None:
        transport = FakeLiveTransport(
            {
                "景点甲": (
                    _poi(
                        PROVIDER_ID_A,
                        "景点甲",
                        location=PROVIDER_LOCATION_A,
                    ),
                ),
                "未匹配": (),
            }
        )
        with tempfile.TemporaryDirectory(prefix="trip-decider-p201-") as temp:
            output_root = Path(temp) / "output"
            with patch.dict(
                os.environ,
                {"AMAP_WEB_SERVICE_KEY": SENTINEL_KEY},
                clear=False,
            ):
                result = run_amap_ephemeral_live(
                    _config(),
                    output_root,
                    transport=transport,
                )
            self.assertFalse(result.problems)
            registry = validate_schema_registry(
                tuple(sorted(Path("schemas").glob("*.schema.json")))
            )
            self.assertFalse(registry.problems)
            documents = tuple(
                load_document(output_root / "planning-input" / name).value
                for name in (
                    "request.yaml",
                    "constraint-parse.json",
                    "constraints.yaml",
                )
            )
            self.assertTrue(all(document is not None for document in documents))
            root_id = documents[2].data["artifact_id"]
            closed = validate_bundle(
                documents,
                registry.value,
                closure=BundleClosure.CLOSED,
                root_artifact_id=root_id,
            )
            self.assertFalse(closed.problems)
            self.assertEqual(_tree_files(output_root), FINAL_FILES)

    def test_p202_credential_gate_and_secret_secrecy(self) -> None:
        transport = FakeLiveTransport({})
        with tempfile.TemporaryDirectory(prefix="trip-decider-p202-") as temp:
            temp_root = Path(temp)
            missing_root = temp_root / "missing"
            with patch.dict(
                os.environ,
                {"AMAP_WEB_SERVICE_KEY": ""},
                clear=False,
            ):
                missing = run_amap_ephemeral_live(
                    _config(must_visit=("景点甲",)),
                    missing_root,
                    transport=transport,
                )
            self.assertEqual(_result_code(missing), AMAP_CREDENTIAL_MISSING)
            self.assertEqual(transport.network_attempts, 0)
            self.assertFalse(missing_root.exists())

            success_root = temp_root / "success"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {"AMAP_WEB_SERVICE_KEY": SENTINEL_KEY},
                    clear=False,
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                success = run_amap_ephemeral_live(
                    _config(must_visit=("未匹配",)),
                    success_root,
                    transport=transport,
                )
            self.assertFalse(success.problems)
            self.assertTrue(transport.credentials)
            descriptors = json.dumps(
                [
                    {
                        "operation": item.operation,
                        "endpoint_path": item.endpoint_path,
                        "parameters": dict(item.parameters),
                    }
                    for item in transport.requests
                ],
                ensure_ascii=False,
                sort_keys=True,
            )
            self.assertNotIn(SENTINEL_KEY, descriptors)
            self.assertNotIn(SENTINEL_KEY, stdout.getvalue())
            self.assertNotIn(SENTINEL_KEY, stderr.getvalue())
            self.assertNotIn(SENTINEL_KEY.encode(), _tree_bytes(success_root))

    def test_p203_ephemeral_chain_outputs_provider_free_safe_plan(self) -> None:
        transport = FakeLiveTransport(
            {
                "景点甲": (
                    _poi(
                        PROVIDER_ID_A,
                        "景点甲",
                        location=PROVIDER_LOCATION_A,
                    ),
                ),
                "未匹配": (),
            }
        )
        with tempfile.TemporaryDirectory(prefix="trip-decider-p203-") as temp:
            output_root = Path(temp) / "output"
            with patch.dict(
                os.environ,
                {"AMAP_WEB_SERVICE_KEY": SENTINEL_KEY},
                clear=False,
            ):
                result = run_amap_ephemeral_live(
                    _config(),
                    output_root,
                    transport=transport,
                )
            self.assertFalse(result.problems)
            self.assertEqual(result.value.planning_status, "conditionally_feasible")
            self.assertFalse(result.value.publishable)
            self.assertFalse(result.value.generation_allowed_input)
            self.assertEqual(result.value.scheduled_count, 1)
            self.assertEqual(result.value.blocked_count, 1)
            self.assertEqual(_tree_files(output_root), FINAL_FILES)
            flattened = _tree_bytes(output_root)
            for forbidden in (
                PROVIDER_ID_A,
                PROVIDER_ADDRESS,
                PROVIDER_LOCATION_A,
                PROVIDER_CATEGORY,
                PROVIDER_TYPECODE,
                PROVIDER_ADCODE,
                SENTINEL_KEY,
            ):
                self.assertNotIn(forbidden.encode("utf-8"), flattened)

            registry = validate_schema_registry(
                tuple(sorted(Path("schemas").glob("*.schema.json")))
            )
            for name in ("plan.json", "violations.json"):
                loaded = load_document(output_root / "planning" / name)
                self.assertFalse(loaded.problems)
                validated = validate_artifact(loaded.value, registry.value)
                self.assertFalse(validated.problems)

    def test_p204_ambiguity_and_selection_preserve_all_identities(self) -> None:
        responses = {
            "景点甲": (
                _poi(
                    PROVIDER_ID_A,
                    "景点甲",
                    location=PROVIDER_LOCATION_A,
                ),
                _poi(
                    PROVIDER_ID_B,
                    "景点甲",
                    location=PROVIDER_LOCATION_B,
                ),
            ),
            "未匹配": (),
        }
        with tempfile.TemporaryDirectory(prefix="trip-decider-p204-") as temp:
            temp_root = Path(temp)
            ambiguous_root = temp_root / "ambiguous"
            with patch.dict(
                os.environ,
                {"AMAP_WEB_SERVICE_KEY": SENTINEL_KEY},
                clear=False,
            ):
                ambiguous = run_amap_ephemeral_live(
                    _config(),
                    ambiguous_root,
                    transport=FakeLiveTransport(responses),
                )
            self.assertFalse(ambiguous.problems)
            first_seed = ambiguous.value.seed_results[0]
            self.assertEqual(first_seed.identity_status, "ambiguous")
            self.assertFalse(first_seed.explicitly_selected)
            self.assertIsNone(first_seed.day_number)

            selected_root = temp_root / "selected"
            with patch.dict(
                os.environ,
                {"AMAP_WEB_SERVICE_KEY": SENTINEL_KEY},
                clear=False,
            ):
                selected = run_amap_ephemeral_live(
                    _config(
                        interactive=True,
                        selections={"景点甲": 2},
                    ),
                    selected_root,
                    transport=FakeLiveTransport(responses),
                )
            self.assertFalse(selected.problems)
            chosen = selected.value.seed_results[0]
            self.assertEqual(chosen.identity_status, "matched")
            self.assertTrue(chosen.explicitly_selected)
            flattened = _tree_bytes(selected_root)
            self.assertNotIn(PROVIDER_ID_A.encode(), flattened)
            self.assertNotIn(PROVIDER_ID_B.encode(), flattened)
            self.assertNotIn(b"ephemeral-amap:poi:", flattened)

    def test_p205_provider_failures_use_fer_without_partial_output(self) -> None:
        cases = (
            (
                "district_transport",
                "district_transport",
                "transport_error",
                1,
                0,
                1,
                "unavailable",
                "unavailable",
                "unavailable",
                False,
            ),
            (
                "district_http",
                "district_http",
                "http_error",
                1,
                0,
                1,
                "4xx",
                "unavailable",
                "unavailable",
                False,
            ),
            (
                "district_api",
                "district_api_status",
                "provider_api_error",
                1,
                0,
                1,
                "2xx",
                "0",
                "20000",
                True,
            ),
            (
                "district_invalid_json",
                "district_parse",
                "invalid_json",
                1,
                0,
                1,
                "2xx",
                "unavailable",
                "unavailable",
                True,
            ),
            (
                "district_invalid_shape",
                "district_parse",
                "invalid_response_shape",
                1,
                0,
                1,
                "2xx",
                "unavailable",
                "unavailable",
                True,
            ),
            (
                "poi_transport",
                "poi_transport",
                "transport_error",
                1,
                1,
                2,
                "unavailable",
                "unavailable",
                "unavailable",
                False,
            ),
            (
                "poi_http",
                "poi_http",
                "http_error",
                1,
                1,
                2,
                "4xx",
                "unavailable",
                "unavailable",
                False,
            ),
            (
                "poi_api",
                "poi_api_status",
                "provider_api_error",
                1,
                1,
                2,
                "2xx",
                "0",
                "20000",
                True,
            ),
            (
                "poi_invalid_json",
                "poi_parse",
                "invalid_json",
                1,
                1,
                2,
                "2xx",
                "unavailable",
                "unavailable",
                True,
            ),
            (
                "poi_invalid_shape",
                "poi_parse",
                "invalid_response_shape",
                1,
                1,
                2,
                "2xx",
                "unavailable",
                "unavailable",
                True,
            ),
            (
                "result_window",
                "result_window",
                "result_window_exhausted",
                1,
                1,
                2,
                "2xx",
                "1",
                "10000",
                True,
            ),
        )
        expected_fields = {
            "failure_token",
            "failure_stage",
            "district_attempts",
            "poi_attempts",
            "total_network_attempts",
            "http_status_class",
            "amap_status",
            "amap_infocode",
            "safe_failure_class",
            "response_bytes_received",
            "fer_classification_completed",
            "final_output_installed",
            "raw_provider_residue",
            "normalized_provider_residue",
            "temporary_residue",
            "key_leakage_detected",
            "retry_count",
            "fallback_count",
        }
        with tempfile.TemporaryDirectory(prefix="trip-decider-p205-") as temp:
            temp_root = Path(temp)
            for (
                failure,
                stage,
                failure_class,
                district_attempts,
                poi_attempts,
                total_attempts,
                http_class,
                amap_status,
                amap_infocode,
                response_received,
            ) in cases:
                output_root = temp_root / failure
                transport = FakeLiveTransport({}, failure=failure)
                with patch.dict(
                    os.environ,
                    {"AMAP_WEB_SERVICE_KEY": SENTINEL_KEY},
                    clear=False,
                ):
                    result = run_amap_ephemeral_live(
                        _config(must_visit=("景点甲",)),
                        output_root,
                        transport=transport,
                    )
                self.assertEqual(_result_code(result), AMAP_PROVIDER_FAILURE)
                summary = result.value
                self.assertIsNotNone(summary)
                self.assertEqual(
                    {item.name for item in fields(summary)},
                    expected_fields,
                )
                actual = {
                    item.name: getattr(summary, item.name)
                    for item in fields(summary)
                }
                self.assertEqual(
                    actual,
                    {
                        "failure_token": AMAP_PROVIDER_FAILURE,
                        "failure_stage": stage,
                        "district_attempts": district_attempts,
                        "poi_attempts": poi_attempts,
                        "total_network_attempts": total_attempts,
                        "http_status_class": http_class,
                        "amap_status": amap_status,
                        "amap_infocode": amap_infocode,
                        "safe_failure_class": failure_class,
                        "response_bytes_received": response_received,
                        "fer_classification_completed": True,
                        "final_output_installed": False,
                        "raw_provider_residue": 0,
                        "normalized_provider_residue": 0,
                        "temporary_residue": 0,
                        "key_leakage_detected": False,
                        "retry_count": 0,
                        "fallback_count": 0,
                    },
                )
                serialized = json.dumps(actual, sort_keys=True)
                for forbidden in (
                    SENTINEL_KEY,
                    "provider.invalid",
                    "provider response body",
                    "provider detail must not escape",
                    PROVIDER_ID_A,
                    PROVIDER_ADDRESS,
                    PROVIDER_LOCATION_A,
                    PROVIDER_CATEGORY,
                    PROVIDER_TYPECODE,
                    PROVIDER_ADCODE,
                    str(temp_root),
                ):
                    self.assertNotIn(forbidden, serialized)
                self.assertFalse(output_root.exists())
            self.assertEqual(
                [path for path in temp_root.rglob("*") if path.is_file()],
                [],
            )

    def test_p206_safe_html_rollback_environment_and_cleanup_fault(self) -> None:
        seed = "<script>alert('unsafe')</script>"
        transport = FakeLiveTransport(
            {
                seed: (
                    _poi(
                        PROVIDER_ID_A,
                        seed,
                        location=PROVIDER_LOCATION_A,
                    ),
                ),
            }
        )
        with tempfile.TemporaryDirectory(prefix="trip-decider-p206-") as temp:
            temp_root = Path(temp)
            output_root = temp_root / "success"
            before_pythonpath = os.environ.get("PYTHONPATH")
            with patch.dict(
                os.environ,
                {"AMAP_WEB_SERVICE_KEY": SENTINEL_KEY},
                clear=False,
            ):
                success = run_amap_ephemeral_live(
                    _config(must_visit=(seed,)),
                    output_root,
                    transport=transport,
                )
            self.assertFalse(success.problems)
            html = (output_root / "report" / "index.html").read_text(
                encoding="utf-8"
            )
            self.assertIn("&lt;script&gt;", html)
            self.assertNotIn("<script>", html)
            self.assertNotIn(PROVIDER_ID_A, html)
            self.assertEqual(os.environ.get("PYTHONPATH"), before_pythonpath)

            nonempty_root = temp_root / "nonempty"
            nonempty_root.mkdir()
            (nonempty_root / "owned.txt").write_text("owned", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"AMAP_WEB_SERVICE_KEY": SENTINEL_KEY},
                clear=False,
            ):
                refused = run_amap_ephemeral_live(
                    _config(must_visit=(seed,)),
                    nonempty_root,
                    transport=FakeLiveTransport({seed: ()}),
                )
            self.assertTrue(refused.problems)
            self.assertEqual((nonempty_root / "owned.txt").read_text(), "owned")

            failed_root = temp_root / "cleanup-failed"
            with (
                patch.dict(
                    os.environ,
                    {"AMAP_WEB_SERVICE_KEY": SENTINEL_KEY},
                    clear=False,
                ),
                patch(
                    "trip_decider.amap_ephemeral_live.shutil.rmtree",
                    side_effect=OSError("synthetic cleanup fault"),
                ),
            ):
                cleanup = run_amap_ephemeral_live(
                    _config(must_visit=("未匹配",)),
                    failed_root,
                    transport=FakeLiveTransport({}),
                )
            self.assertEqual(_result_code(cleanup), AMAP_P2_CLEANUP_FAILED)
            self.assertFalse(failed_root.exists())


if __name__ == "__main__":
    unittest.main()
