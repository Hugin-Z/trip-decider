from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch

import trip_decider.live_place_resolution as live_place_resolution
from trip_decider.live_place_resolution import (
    AmapObservationMode,
    StructuredTripInput,
    SyntheticProviderRequest,
    bind_amap_observation_policy,
    parse_amap_district_response,
    parse_amap_poi_response,
    project_amap_candidates,
    run_synthetic_live_place_resolution,
)


PRE_REFACTOR_TREE_SHA256 = (
    "2F0EF9F8FDB9A8FE732A37BBCBA2408958412F7540ACF6F93BEAD41F6A071BA8"
)
PRE_REFACTOR_CANDIDATE_SHA256 = (
    "D3718AD0B5D2AE259E4FE54D6B4FA0F658862700D4E6E98DD5FFFB86A8A1874C"
)


def _structured_input(
    *,
    must_visit: tuple[str, ...] = ("景点甲",),
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


def _district_response(*, synthetic_marker: object = True) -> dict[str, object]:
    document: dict[str, object] = {
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
    if synthetic_marker != "absent":
        document = {
            "synthetic_test_data": synthetic_marker,
            **document,
        }
    return document


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


def _poi_response(
    pois: tuple[Mapping[str, object], ...],
    *,
    synthetic_marker: object = True,
) -> dict[str, object]:
    document: dict[str, object] = {
        "status": "1",
        "info": "SYNTHETIC_OK",
        "infocode": "10000",
        "count": str(len(pois)),
        "pois": [dict(item) for item in pois],
    }
    if synthetic_marker != "absent":
        document = {
            "synthetic_test_data": synthetic_marker,
            **document,
        }
    return document


class _SyntheticTransport:
    def __init__(
        self,
        poi_responses: Mapping[str, tuple[Mapping[str, object], ...]],
    ) -> None:
        self.poi_responses = poi_responses
        self.network_attempts = 0

    def __call__(
        self,
        request: SyntheticProviderRequest,
    ) -> Mapping[str, object]:
        if request.operation == "district":
            return _district_response()
        seed = str(request.parameters["keywords"])
        return _poi_response(self.poi_responses.get(seed, ()))


def _unwrap(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _unwrap(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_unwrap(item) for item in value]
    return value


def _tree_sha256(root: Path) -> tuple[int, str]:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return len(files), digest.hexdigest().upper()


def _bound_observations(
    *,
    mode: AmapObservationMode,
    seeds: tuple[str, ...],
    responses: Mapping[str, dict[str, object]],
) -> tuple[object, tuple[tuple[str, object], ...]]:
    marker = True if mode is AmapObservationMode.SYNTHETIC_TEST else "absent"
    district_parsed = parse_amap_district_response(
        _district_response(synthetic_marker=marker)
    )
    if district_parsed.problems or district_parsed.value is None:
        raise AssertionError(district_parsed.problems)
    district = bind_amap_observation_policy(
        district_parsed.value,
        mode=mode,
        policy_checked_at="2026-07-29T12:00:00+08:00",
    )
    if district.problems or district.value is None:
        raise AssertionError(district.problems)
    pois: list[tuple[str, object]] = []
    for seed in seeds:
        parsed = parse_amap_poi_response(responses[seed])
        if parsed.problems or parsed.value is None:
            raise AssertionError(parsed.problems)
        bound = bind_amap_observation_policy(
            parsed.value,
            mode=mode,
            policy_checked_at="2026-07-29T12:00:00+08:00",
        )
        if bound.problems or bound.value is None:
            raise AssertionError(bound.problems)
        pois.append((seed, bound.value))
    return district.value, tuple(pois)


class ProviderNeutralParserContractCase(unittest.TestCase):
    """Handwritten deterministic shape cases; no live-provider coverage."""

    def test_pn01_synthetic_public_path_preserves_wrapper_bytes(self) -> None:
        poi = _poi(
            "SYNTH-AMAP-POI-0001",
            " 景点甲 ",
            location="120.100000,30.100000",
            typecode="110000",
        )
        seeds = ("景点甲", "未匹配")
        responses = {
            "景点甲": _poi_response((poi,)),
            "未匹配": _poi_response(()),
        }
        district, poi_observations = _bound_observations(
            mode=AmapObservationMode.SYNTHETIC_TEST,
            seeds=seeds,
            responses=responses,
        )
        projection = project_amap_candidates(
            city="测试市",
            city_adcode="990100",
            seeds=seeds,
            district_observation=district,
            poi_observations=poi_observations,
        )
        self.assertFalse(projection.problems)
        self.assertEqual(projection.value.mode, AmapObservationMode.SYNTHETIC_TEST)
        self.assertEqual(len(projection.value.candidates), 1)
        self.assertEqual(
            projection.value.candidates[0]["provider"]["data_policy"][
                "source_class"
            ],
            "synthetic",
        )

        transport = _SyntheticTransport(
            {
                "景点甲": (poi,),
                "未匹配": (),
            }
        )
        with tempfile.TemporaryDirectory(
            prefix="trip-decider-wu7r-pn01-"
        ) as temp:
            output_root = Path(temp) / "output"
            with (
                patch(
                    "trip_decider.live_place_resolution."
                    "parse_amap_district_response",
                    wraps=parse_amap_district_response,
                ) as district_mock,
                patch(
                    "trip_decider.live_place_resolution."
                    "parse_amap_poi_response",
                    wraps=parse_amap_poi_response,
                ) as poi_mock,
                patch(
                    "trip_decider.live_place_resolution."
                    "project_amap_candidates",
                    wraps=project_amap_candidates,
                ) as projection_mock,
            ):
                wrapper = run_synthetic_live_place_resolution(
                    _structured_input(must_visit=seeds),
                    output_root,
                    transport,
                )
            self.assertFalse(wrapper.problems)
            self.assertGreaterEqual(district_mock.call_count, 1)
            self.assertGreaterEqual(poi_mock.call_count, 2)
            self.assertEqual(projection_mock.call_count, 1)
            file_count, tree_hash = _tree_sha256(output_root)
            self.assertEqual(file_count, 12)
            self.assertEqual(tree_hash, PRE_REFACTOR_TREE_SHA256)
            candidate_path = output_root / "resolution" / "candidates.json"
            self.assertEqual(
                hashlib.sha256(candidate_path.read_bytes()).hexdigest().upper(),
                PRE_REFACTOR_CANDIDATE_SHA256,
            )
            candidate_document = json.loads(
                candidate_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                _unwrap(projection.value.candidates[0]),
                candidate_document["payload"]["candidates"][0],
            )
            self.assertTrue(
                json.loads(
                    (
                        output_root
                        / "provider-observation"
                        / "normalized-snapshot.json"
                    ).read_text(encoding="utf-8")
                )["synthetic_test_data"]
            )
            self.assertEqual(transport.network_attempts, 0)

    def test_pn02_ephemeral_live_is_memory_only(self) -> None:
        poi = _poi(
            "LIVE-AMAP-POI-0001",
            "景点甲",
            location="120.100000,30.100000",
            typecode="110000",
        )
        district_bytes = json.dumps(
            _district_response(synthetic_marker="absent"),
            ensure_ascii=False,
        ).encode("utf-8")
        poi_bytes = json.dumps(
            _poi_response((poi,), synthetic_marker="absent"),
            ensure_ascii=False,
        ).encode("utf-8")
        with tempfile.TemporaryDirectory(
            prefix="trip-decider-wu7r-pn02-"
        ) as temp:
            temp_root = Path(temp)
            before = tuple(temp_root.iterdir())
            parsed_district = parse_amap_district_response(district_bytes)
            parsed_poi = parse_amap_poi_response(poi_bytes)
            self.assertFalse(parsed_district.problems)
            self.assertFalse(parsed_poi.problems)
            district = bind_amap_observation_policy(
                parsed_district.value,
                mode=AmapObservationMode.EPHEMERAL_LIVE,
                policy_checked_at="2026-07-29T12:00:00+08:00",
            )
            pois = bind_amap_observation_policy(
                parsed_poi.value,
                mode=AmapObservationMode.EPHEMERAL_LIVE,
                policy_checked_at="2026-07-29T12:00:00+08:00",
            )
            projection = project_amap_candidates(
                city="测试市",
                city_adcode="990100",
                seeds=("景点甲",),
                district_observation=district.value,
                poi_observations=(("景点甲", pois.value),),
            )
            self.assertFalse(projection.problems)
            self.assertEqual(
                projection.value.mode,
                AmapObservationMode.EPHEMERAL_LIVE,
            )
            candidate = projection.value.candidates[0]
            self.assertEqual(
                candidate["source_refs"][0]["value"],
                "ephemeral-amap:poi:LIVE-AMAP-POI-0001",
            )
            self.assertEqual(
                candidate["provider"]["data_policy"]["capture_mode"],
                "temporary_capture",
            )
            self.assertEqual(
                candidate["provider"]["data_policy"]["storage_policy"],
                "temporary_only",
            )
            self.assertFalse(
                candidate["provider"]["data_policy"]["replay_allowed"]
            )
            self.assertFalse(
                candidate["provider"]["data_policy"]["fixture_allowed"]
            )
            self.assertEqual(
                district.value.persistence_capability,
                "ephemeral_memory_only",
            )
            self.assertIsNone(parsed_poi.value.synthetic_test_data)
            forbidden = {
                "output_root",
                "path",
                "replay",
                "serialize",
                "snapshot",
                "write",
            }
            self.assertFalse(forbidden.intersection(dir(projection.value)))
            self.assertEqual(tuple(temp_root.iterdir()), before)

    def test_pn03_policy_mismatch_never_infers_or_corrects(self) -> None:
        cases = (
            (
                "synthetic_missing",
                "absent",
                AmapObservationMode.SYNTHETIC_TEST,
            ),
            (
                "synthetic_false",
                False,
                AmapObservationMode.SYNTHETIC_TEST,
            ),
            (
                "ephemeral_true",
                True,
                AmapObservationMode.EPHEMERAL_LIVE,
            ),
            ("non_enum", True, "synthetic_test"),
        )
        for name, marker, mode in cases:
            document = _poi_response((), synthetic_marker=marker)
            original = copy.deepcopy(document)
            parsed = parse_amap_poi_response(document)
            self.assertFalse(parsed.problems, name)
            result = bind_amap_observation_policy(
                parsed.value,
                mode=mode,  # type: ignore[arg-type]
                policy_checked_at="2026-07-29T12:00:00+08:00",
            )
            self.assertIsNone(result.value, name)
            self.assertEqual(len(result.problems), 1, name)
            self.assertEqual(
                result.problems[0].error_code,
                "OBSERVATION_POLICY_MISMATCH",
                name,
            )
            self.assertEqual(document, original, name)

    def test_pn04_modes_share_identity_matching_and_selection_core(self) -> None:
        seeds = ("Café",)
        pois = (
            _poi(
                "AMAP-POI-0002",
                " CAFÉ ",
                location="120.200000,30.200000",
                typecode="110001",
            ),
            _poi(
                "AMAP-POI-0003",
                "Cafe\u0301",
                location="120.300000,30.300000",
                typecode="110002",
            ),
        )
        projections = []
        for mode in (
            AmapObservationMode.SYNTHETIC_TEST,
            AmapObservationMode.EPHEMERAL_LIVE,
        ):
            marker = True if mode is AmapObservationMode.SYNTHETIC_TEST else "absent"
            responses = {
                "Café": _poi_response(pois, synthetic_marker=marker),
            }
            district, poi_observations = _bound_observations(
                mode=mode,
                seeds=seeds,
                responses=responses,
            )

            def choose_second(
                seed: str,
                alternatives: tuple[tuple[str, str], ...],
            ) -> str:
                self.assertEqual(seed, "Café")
                self.assertEqual(len(alternatives), 2)
                return alternatives[1][0]

            result = project_amap_candidates(
                city="测试市",
                city_adcode="990100",
                seeds=seeds,
                district_observation=district,
                poi_observations=poi_observations,
                selection_reader=choose_second,
            )
            self.assertFalse(result.problems)
            self.assertEqual(len(result.value.candidates), 2)
            self.assertEqual(
                result.value.seed_matches[0]["status"],
                "matched",
            )
            self.assertEqual(
                len(result.value.selections[0]["alternatives"]),
                2,
            )
            self.assertEqual(
                result.value.selections[0]["selection_source"],
                "user_explicit",
            )
            for candidate in result.value.candidates:
                self.assertEqual(candidate["provider"]["name"], "amap")
                self.assertEqual(candidate["provider"]["record_type"], "poi")
                self.assertEqual(candidate["location"]["crs"], "GCJ-02")
            projections.append(result.value)

        self.assertEqual(
            tuple(
                (
                    item["candidate_id"],
                    item["provider"]["record_id"],
                    item["location"]["latitude"],
                    item["location"]["longitude"],
                )
                for item in projections[0].candidates
            ),
            tuple(
                (
                    item["candidate_id"],
                    item["provider"]["record_id"],
                    item["location"]["latitude"],
                    item["location"]["longitude"],
                )
                for item in projections[1].candidates
            ),
        )
        self.assertEqual(
            projections[0].seed_matches[0]["candidate_refs"],
            projections[1].seed_matches[0]["candidate_refs"],
        )
        source = inspect.getsource(live_place_resolution)
        forbidden_import = re.compile(
            r"^\s*(?:from|import)\s+"
            r"(?:aiohttp|httpx|requests|socket|urllib)\b",
            re.MULTILINE,
        )
        self.assertIsNone(forbidden_import.search(source))
        self.assertNotIn("AMAP_WEB_SERVICE_KEY", source)
        self.assertNotIn("restapi.amap.com", source)
        self.assertEqual(source.count("def parse_amap_poi_response"), 1)
        self.assertEqual(source.count("def _candidate_from_poi"), 1)


if __name__ == "__main__":
    unittest.main()
