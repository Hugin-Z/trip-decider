"""Local two-stage Discover -> Plan web product."""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from trip_decider.destination_runtime import (
    collect_map_evidence,
    collect_railway_evidence,
    revise_destination_result,
    unavailable_web_evidence,
)
from trip_decider.dynamic_discovery import collect_live_destination_profile
from trip_decider.guided_discovery import (
    build_guided_comparison,
)
from trip_decider.agent_actions import (
    execute_registered_action,
    get_next_actions,
    restart_action_loop_for_intent,
    run_until_blocked,
    start_action_loop,
    submit_evidence,
)
from trip_decider.travel_agent import (
    AgentRuntimeMode,
    DEFAULT_AGENT_STORE,
    EvidenceItem,
    EvidenceStatus,
    Revision,
    RunStatus,
    TaskMode,
    TravelIntent,
    TravelAgentError,
    confirm_intent,
    continue_run_with_intent,
    create_run,
    revise_run,
    runtime_status,
)


_WEB_ROOT = Path(__file__).with_name("web")
_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
_MAX_REQUEST_BYTES = 1_000_000
_GUIDED_CANCELLATIONS: dict[str, threading.Event] = {}
_GUIDED_CANCELLATIONS_LOCK = threading.RLock()


class ProductRequestError(ValueError):
    """Raised for malformed local product API input."""


def _client_configuration() -> dict[str, object]:
    js_key = os.environ.get("AMAP_JS_API_KEY", "").strip()
    security_code = os.environ.get("AMAP_JS_SECURITY_CODE", "").strip()
    map_configured = bool(js_key and security_code)
    contract_status = runtime_status()
    return {
        "ai": {
            **contract_status,
            "configured": False,
            "display": "本地结构化提取",
            "missing": [],
            "available_modes": [
                AgentRuntimeMode.CODEX_HOSTED.value,
                AgentRuntimeMode.STANDALONE_WEB.value,
            ],
            "web_natural_language_enabled": True,
        },
        "amap_js": {
            "configured": map_configured,
            "display": (
                "高德 JS API 已配置"
                if map_configured
                else "地图未配置"
            ),
            "missing": [
                name
                for name, value in (
                    ("AMAP_JS_API_KEY", js_key),
                    ("AMAP_JS_SECURITY_CODE", security_code),
                )
                if not value
            ],
            "key": js_key if map_configured else None,
            "security_js_code": security_code if map_configured else None,
            "web_service_key_separate": True,
        },
    }


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def _guided_evidence_path(run_id: str) -> Path | None:
    run_directory = DEFAULT_AGENT_STORE.run_directory(run_id)
    return (
        run_directory / "evidence" / "guided-comparison.json"
        if run_directory is not None
        else None
    )


def _guided_evidence_read_path(run_id: str) -> Path | None:
    path = _guided_evidence_path(run_id)
    if path is None or path.is_file():
        return path
    run_directory = DEFAULT_AGENT_STORE.run_directory(run_id)
    legacy = (
        run_directory / "guided-evidence.json"
        if run_directory is not None
        else None
    )
    return legacy if legacy is not None and legacy.is_file() else path


def _persist_guided_evidence(
    run_id: str,
    evidence_by_destination: Mapping[str, object],
) -> None:
    path = _guided_evidence_path(run_id)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_bytes(
        _json_bytes(
            {
                "version": 1,
                "destinations": dict(evidence_by_destination),
            }
        )
    )
    os.replace(temporary, path)


def _guided_evidence_for_selection(
    run_id: str,
    destination_id: str,
) -> dict[str, EvidenceItem]:
    path = _guided_evidence_read_path(run_id)
    if path is None or not path.is_file():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProductRequestError(
            "区域比较证据无法安全恢复。"
        ) from error
    destinations = (
        document.get("destinations")
        if isinstance(document, Mapping)
        else None
    )
    selected = (
        destinations.get(destination_id)
        if isinstance(destinations, Mapping)
        else None
    )
    if not isinstance(selected, Mapping):
        return {}
    evidence: dict[str, EvidenceItem] = {}
    for domain, raw_item in selected.items():
        if domain not in {"railway", "map", "web"}:
            raise ProductRequestError(
                "区域比较证据包含未知领域。"
            )
        if not isinstance(raw_item, Mapping):
            raise ProductRequestError(
                "区域比较证据格式无效。"
            )
        evidence[domain] = EvidenceItem.from_mapping(raw_item)
    return evidence


def _run_response(run_id: str) -> dict[str, object]:
    run = DEFAULT_AGENT_STORE.get_run(run_id)
    session = DEFAULT_AGENT_STORE.get_session(run.session_id)
    run_value = run.to_dict()
    events = [
        event.to_dict()
        for event in DEFAULT_AGENT_STORE.events_after(
            run.session_id,
            0,
        )
        if event.run_id == run.run_id
    ]
    installed = _current_plan_payload(run_id)
    plan_version = (
        installed.get("plan_version")
        if isinstance(installed, Mapping)
        and isinstance(installed.get("plan_version"), int)
        else None
    )
    read_run_value = deepcopy(run_value)
    current_result = run_value.get("result")
    if isinstance(installed, Mapping) and isinstance(
        installed.get("plan"),
        Mapping,
    ):
        read_run_value["result"] = {
            "plan": deepcopy(installed["plan"]),
            "context": deepcopy(installed.get("context", {})),
        }
    elif isinstance(current_result, Mapping) and (
        "planning_draft" in current_result or "plan" in current_result
    ):
        read_run_value["result"] = (
            None
        )
    presentation = _presentation_contract(read_run_value, events)
    presentation["plan_version"] = plan_version
    if not isinstance(installed, Mapping):
        presentation["budget_summary"] = None
    presentation["planning_draft"] = _planning_draft_read_model(
        run_value
    )
    presentation["map_payload"] = _map_payload_contract(
        read_run_value,
        plan_version=plan_version,
    )
    response = {
        "session": session.to_dict(),
        "run": read_run_value,
        "presentation": presentation,
        "events": events,
    }
    if run.status is RunStatus.RUNNING:
        try:
            action_loop = get_next_actions(run_id)
            response["action_loop"] = action_loop
            draft_source = {
                "result": action_loop.get("result")
                if isinstance(action_loop, Mapping)
                else None
            }
            draft_read_model = _planning_draft_read_model(draft_source)
            if draft_read_model is not None:
                presentation["planning_draft"] = draft_read_model
        except TravelAgentError:
            pass
    return response


def _trip_list_response() -> dict[str, object]:
    runs = DEFAULT_AGENT_STORE.list_runs()
    return {
        "runs": [
            {
                "run_id": run.run_id,
                "created_at": run.created_at,
                "status": run.status.value,
                "task_mode": run.intent.task_mode.value,
                "origin": run.intent.origin,
                "destination": run.intent.destination_anchor,
                "themes": list(run.intent.themes),
            }
            for run in runs
        ],
        "continue_run_id": runs[0].run_id if runs else None,
    }


def _candidate_response(run_id: str) -> dict[str, object]:
    run = DEFAULT_AGENT_STORE.get_run(run_id)
    result = run.result
    if isinstance(result, Mapping) and result.get("stage") in {
        "open_discovery",
        "guided_discovery",
    }:
        options = result.get("options")
        if not isinstance(options, list):
            raise ProductRequestError("candidate comparison omitted options")
        stage = result.get("stage")
        comparison_completed = True
    elif (
        run.status is RunStatus.RUNNING
        and run.intent.task_mode in {
            TaskMode.OPEN_DISCOVERY,
            TaskMode.GUIDED_DISCOVERY,
        }
    ):
        session = DEFAULT_AGENT_STORE.get_session(run.session_id)
        by_id: dict[str, dict[str, object]] = {}
        for event in DEFAULT_AGENT_STORE.events_after(session.session_id, 0):
            if (
                event.run_id != run_id
                or not event.event_type.endswith(".candidate.completed")
            ):
                continue
            option = event.details.get("option")
            destination_id = (
                option.get("destination_id")
                if isinstance(option, Mapping)
                else None
            )
            if isinstance(destination_id, str):
                by_id[destination_id] = deepcopy(dict(option))
        options = list(by_id.values())
        stage = "candidate_comparison"
        comparison_completed = False
    else:
        raise ProductRequestError(
            "candidate comparison is not available for this run"
        )
    return {
        "run_id": run_id,
        "task_mode": run.intent.task_mode.value,
        "stage": stage,
        "comparison_completed": comparison_completed,
        "selection_required": True,
        "candidates": deepcopy(options),
    }


def _current_plan_response(run_id: str) -> dict[str, object]:
    value = _current_plan_payload(run_id)
    if value is None:
        raise ProductRequestError("current plan does not exist")
    return value


def _current_plan_version(run_id: str) -> int | None:
    value = _current_plan_payload(run_id)
    version = value.get("plan_version") if isinstance(value, Mapping) else None
    return (
        version
        if isinstance(version, int) and not isinstance(version, bool)
        else None
    )


def _current_plan_payload(run_id: str) -> dict[str, object] | None:
    run_directory = DEFAULT_AGENT_STORE.run_directory(run_id)
    if run_directory is None:
        return None
    path = run_directory / "plan-version.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, Mapping):
        return None
    plan = value.get("plan")
    planning_state = value.get("planning_state")
    if (
        planning_state not in {"PARTIAL_READY", "PLAN_READY"}
        or not isinstance(plan, Mapping)
        or plan.get("artifact_kind") != "PlanVersion"
        or plan.get("planning_state") != planning_state
        or plan.get("displayable") is not True
    ):
        return None
    return deepcopy(dict(value))


def _planning_draft_read_model(
    run: Mapping[str, object],
) -> dict[str, object] | None:
    """Expose draft progress without exposing draft itinerary projections."""

    result = run.get("result")
    draft = (
        result.get("planning_draft")
        if isinstance(result, Mapping)
        and isinstance(result.get("planning_draft"), Mapping)
        else None
    )
    if not isinstance(draft, Mapping):
        return None
    requirements = draft.get("display_requirements")
    missing = draft.get("missing_requirements")
    blockers = draft.get("conditional_blockers")
    planning_input = (
        draft.get("planning_input")
        if isinstance(draft.get("planning_input"), Mapping)
        else {}
    )
    return {
        "planning_state": result.get("planning_state"),
        "missing_requirements": (
            deepcopy(missing) if isinstance(missing, list) else []
        ),
        "collected_information": {
            "destination_resolved": (
                requirements.get("destination_resolved") is True
                if isinstance(requirements, Mapping)
                else False
            ),
            "outbound_transport": (
                requirements.get("outbound_transport") is True
                if isinstance(requirements, Mapping)
                else False
            ),
            "return_transport": (
                requirements.get("return_transport") is True
                if isinstance(requirements, Mapping)
                else False
            ),
            "attraction_count": len(
                planning_input.get("attraction_events", [])
                if isinstance(planning_input.get("attraction_events"), list)
                else []
            ),
            "local_transit_count": len(
                planning_input.get("local_transit_events", [])
                if isinstance(planning_input.get("local_transit_events"), list)
                else []
            ),
            "accommodation_base": (
                requirements.get("accommodation_base") is True
                if isinstance(requirements, Mapping)
                else False
            ),
        },
        "blockers": (
            [
                deepcopy(dict(item))
                for item in blockers
                if isinstance(item, Mapping)
            ]
            if isinstance(blockers, list)
            else []
        ),
    }


def _map_position(value: object) -> dict[str, object] | None:
    """Normalize an explicitly supplied GCJ-02 point without geocoding."""

    if isinstance(value, Mapping):
        nested = next(
            (
                value.get(key)
                for key in ("position", "coordinates", "center", "location")
                if key in value
            ),
            None,
        )
        if nested is not None:
            point = _map_position(nested)
            if point is not None:
                return point
        longitude = value.get("longitude", value.get("lon"))
        latitude = value.get("latitude", value.get("lat"))
        coordinate_system = value.get(
            "coordinate_system",
            value.get("crs", "GCJ-02"),
        )
    elif (
        isinstance(value, (list, tuple))
        and len(value) == 2
    ):
        longitude, latitude = value
        coordinate_system = "GCJ-02"
    else:
        return None
    if (
        not isinstance(longitude, (int, float))
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or isinstance(latitude, bool)
        or not -180 <= float(longitude) <= 180
        or not -90 <= float(latitude) <= 90
    ):
        return None
    return {
        "longitude": float(longitude),
        "latitude": float(latitude),
        "coordinate_system": str(coordinate_system or "GCJ-02"),
    }


def _map_polyline(value: object) -> list[dict[str, object]]:
    """Return only explicitly persisted route points."""

    raw_points: object = value
    if isinstance(value, Mapping):
        raw_points = next(
            (
                value.get(key)
                for key in ("polyline", "path", "points")
                if key in value
            ),
            None,
        )
    if isinstance(raw_points, str):
        parsed: list[list[float]] = []
        for pair in raw_points.split(";"):
            values = pair.split(",")
            if len(values) != 2:
                return []
            try:
                parsed.append([float(values[0]), float(values[1])])
            except ValueError:
                return []
        raw_points = parsed
    if not isinstance(raw_points, (list, tuple)):
        return []
    points = [
        point
        for item in raw_points
        if (point := _map_position(item)) is not None
    ]
    return points if len(points) >= 2 else []


def _map_payload_contract(
    run: Mapping[str, object],
    *,
    plan_version: int | None,
) -> dict[str, object]:
    """Project the current plan into a map-only, read-only contract.

    The projection never geocodes a name and never requests or reconstructs a
    route. Missing coordinates and geometry remain explicit.
    """

    result = run.get("result")
    plan = (
        result.get("plan")
        if isinstance(result, Mapping)
        and isinstance(result.get("plan"), Mapping)
        else {}
    )
    context = (
        result.get("context")
        if isinstance(result, Mapping)
        and isinstance(result.get("context"), Mapping)
        else {}
    )
    raw_evidence = (
        context.get("evidence")
        if isinstance(context.get("evidence"), list)
        else []
    )
    evidence = {
        str(item.get("domain")): item
        for item in raw_evidence
        if isinstance(item, Mapping)
        and isinstance(item.get("domain"), str)
    }

    def evidence_value(domain: str) -> Mapping[str, object]:
        item = evidence.get(domain)
        value = item.get("value") if isinstance(item, Mapping) else None
        return value if isinstance(value, Mapping) else {}

    def retrieved_at(domain: str) -> str | None:
        item = evidence.get(domain)
        value = evidence_value(domain)
        snapshot = value.get("snapshot")
        if (
            isinstance(snapshot, Mapping)
            and isinstance(snapshot.get("retrieved_at"), str)
        ):
            return str(snapshot["retrieved_at"])
        if isinstance(value.get("retrieved_at"), str):
            return str(value["retrieved_at"])
        sources = item.get("sources") if isinstance(item, Mapping) else None
        values = [
            str(source["retrieved_at"])
            for source in (sources if isinstance(sources, list) else [])
            if isinstance(source, Mapping)
            and isinstance(source.get("retrieved_at"), str)
        ]
        return max(values) if values else None

    def snapshot_status(domain: str) -> str:
        value = evidence_value(domain)
        snapshot = value.get("snapshot")
        status = (
            snapshot.get("status")
            if isinstance(snapshot, Mapping)
            else value.get("snapshot_status")
        )
        return (
            str(status).upper()
            if isinstance(status, str)
            and str(status).upper() in {"LIVE", "STALE"}
            else "LIVE"
            if domain in evidence
            else "MISSING"
        )

    map_value = evidence_value("map")
    web_value = evidence_value("web")
    days = (
        plan.get("days")
        if isinstance(plan.get("days"), list)
        else []
    )
    event_days: dict[str, int] = {}
    event_values: list[Mapping[str, object]] = []
    for day in days:
        if not isinstance(day, Mapping):
            continue
        day_number = day.get("day")
        if not isinstance(day_number, int) or isinstance(day_number, bool):
            continue
        raw_events = (
            day.get("events")
            if isinstance(day.get("events"), list)
            else []
        )
        for event in raw_events:
            if not isinstance(event, Mapping):
                continue
            event_values.append(event)
            event_id = event.get("event_id")
            if isinstance(event_id, str):
                event_days[event_id] = day_number

    point_by_name: dict[str, dict[str, object]] = {}
    point_by_event_id: dict[str, dict[str, object]] = {}

    def remember_point(name: object, value: object) -> None:
        if not isinstance(name, str) or not name.strip():
            return
        point = _map_position(value)
        if point is not None:
            point_by_name[name.strip()] = point

    planning_input = (
        plan.get("planning_input")
        if isinstance(plan.get("planning_input"), Mapping)
        else {}
    )
    raw_plan_points = (
        planning_input.get("map_points")
        if isinstance(planning_input.get("map_points"), list)
        else []
    )
    raw_places = (
        raw_plan_points
        if raw_plan_points
        else map_value.get("map_points")
        if isinstance(map_value.get("map_points"), list)
        else map_value.get("places")
    )
    if isinstance(raw_places, list):
        for item in raw_places:
            if isinstance(item, Mapping):
                remember_point(item.get("name"), item)
                aliases = (
                    item.get("aliases")
                    if isinstance(item.get("aliases"), list)
                    else []
                )
                for alias in aliases:
                    remember_point(alias, item)
                point = _map_position(item)
                event_ids = (
                    item.get("event_ids")
                    if isinstance(item.get("event_ids"), list)
                    else []
                )
                if point is not None:
                    for event_id in event_ids:
                        if isinstance(event_id, str) and event_id:
                            point_by_event_id[event_id] = point
    raw_resolutions = map_value.get("local_transit_place_resolutions")
    if isinstance(raw_resolutions, Mapping):
        for name, item in raw_resolutions.items():
            remember_point(name, item)
    hotel_area = (
        web_value.get("hotel_area")
        if isinstance(web_value.get("hotel_area"), Mapping)
        else {}
    )
    remember_point(hotel_area.get("name"), hotel_area)
    for event in event_values:
        remember_point(event.get("name"), event.get("location"))
        remember_point(event.get("from"), event.get("from_location"))
        remember_point(event.get("to"), event.get("to_location"))

    markers_by_name: dict[str, dict[str, object]] = {}

    def add_marker(
        name: object,
        *,
        kind: str,
        display_name: str | None = None,
        event_id: object = None,
        day: int | None = None,
        position: object = None,
        status: str = "MISSING",
        collected_at: str | None = None,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            return
        normalized_name = name.strip()
        remember_point(normalized_name, position)
        marker = markers_by_name.setdefault(
            normalized_name,
            {
                "marker_id": f"place-{len(markers_by_name) + 1}",
                "name": normalized_name,
                "display_name": display_name or normalized_name,
                "kind": kind,
                "event_ids": [],
                "days": [],
                "position": point_by_name.get(normalized_name),
                "evidence_status": status,
                "retrieved_at": collected_at,
            },
        )
        kind_priority = {
            "station": 3,
            "accommodation": 2,
            "attraction": 1,
        }
        if kind_priority.get(kind, 0) > kind_priority.get(
            str(marker.get("kind")),
            0,
        ):
            marker["kind"] = kind
        if display_name:
            marker["display_name"] = display_name
        if marker.get("position") is None:
            marker["position"] = point_by_name.get(normalized_name)
        if isinstance(event_id, str) and event_id not in marker["event_ids"]:
            marker["event_ids"].append(event_id)
        if isinstance(day, int) and day not in marker["days"]:
            marker["days"].append(day)
        if marker.get("evidence_status") == "MISSING" and status != "MISSING":
            marker["evidence_status"] = status
            marker["retrieved_at"] = collected_at

    railway_status = snapshot_status("railway")
    map_status = snapshot_status("map")
    web_status = snapshot_status("web")
    rail_origin_name: str | None = None
    rail_destination_name: str | None = None
    if isinstance(raw_places, list):
        for item in raw_places:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name")
            event_ids = (
                item.get("event_ids")
                if isinstance(item.get("event_ids"), list)
                else []
            )
            status = str(item.get("evidence_status") or map_status).upper()
            collected_at = (
                str(item.get("retrieved_at"))
                if isinstance(item.get("retrieved_at"), str)
                else retrieved_at("map")
            )
            for event_id in event_ids or [None]:
                add_marker(
                    name,
                    kind=str(item.get("kind") or "place"),
                    display_name=(
                        str(item.get("display_name"))
                        if isinstance(item.get("display_name"), str)
                        else None
                    ),
                    event_id=event_id,
                    day=(
                        event_days.get(str(event_id))
                        if isinstance(event_id, str)
                        else None
                    ),
                    position=item,
                    status=status,
                    collected_at=collected_at,
                )
            if item.get("rail_role") == "origin" and isinstance(name, str):
                rail_origin_name = name
            if item.get("rail_role") == "destination" and isinstance(name, str):
                rail_destination_name = name

    for event in event_values:
        event_id = event.get("event_id")
        day = event_days.get(str(event_id))
        if isinstance(event_id, str) and event_id in point_by_event_id:
            continue
        if (
            event.get("type") == "transit"
            and str(event_id or "").startswith("rail-")
        ):
            add_marker(
                event.get("from"),
                kind="station",
                display_name=(
                    f"{event.get('from')}站"
                    if isinstance(event.get("from"), str)
                    and not str(event.get("from")).endswith("站")
                    else None
                ),
                event_id=event_id,
                day=day,
                position=(
                    event.get("from_location")
                    or point_by_event_id.get(str(event_id))
                ),
                status=railway_status,
                collected_at=retrieved_at("railway"),
            )
            add_marker(
                event.get("to"),
                kind="station",
                display_name=(
                    f"{event.get('to')}站"
                    if isinstance(event.get("to"), str)
                    and not str(event.get("to")).endswith("站")
                    else None
                ),
                event_id=event_id,
                day=day,
                position=(
                    event.get("to_location")
                    or point_by_event_id.get(str(event_id))
                ),
                status=railway_status,
                collected_at=retrieved_at("railway"),
            )
        elif event.get("type") == "attraction":
            add_marker(
                event.get("name"),
                kind="attraction",
                display_name=str(event.get("name")).removesuffix("·游览"),
                event_id=event_id,
                day=day,
                position=(
                    event.get("location")
                    or point_by_event_id.get(str(event_id))
                ),
                status=web_status,
                collected_at=retrieved_at("web"),
            )
        elif event.get("type") in {"hotel", "rest"}:
            add_marker(
                event.get("location"),
                kind="accommodation",
                event_id=event_id,
                day=day,
                position=(
                    event.get("location")
                    or point_by_event_id.get(str(event_id))
                ),
                status=web_status,
                collected_at=retrieved_at("web"),
            )
    if hotel_area:
        add_marker(
            hotel_area.get("name"),
            kind="accommodation",
            position=hotel_area,
            status=web_status,
            collected_at=retrieved_at("web"),
        )

    raw_routes = (
        planning_input.get("local_transit_events")
        if isinstance(planning_input.get("local_transit_events"), list)
        else []
    )
    raw_map_routes = (
        map_value.get("local_transit")
        if isinstance(map_value.get("local_transit"), list)
        else []
    )
    map_route_by_id = {
        str(route.get("route_id")): route
        for route in raw_map_routes
        if isinstance(route, Mapping)
        and isinstance(route.get("route_id"), str)
    }
    attraction_day_by_name = {
        str(event.get("name")).removesuffix("·游览"): event_days.get(
            str(event.get("event_id")),
        )
        for event in event_values
        if event.get("type") == "attraction"
        and isinstance(event.get("name"), str)
    }
    route_polylines: list[dict[str, object]] = []
    for index, route in enumerate(raw_routes, start=1):
        if not isinstance(route, Mapping):
            continue
        route_id = str(route.get("event_id") or route.get("route_id") or (
            f"map-route-{index}"
        ))
        source_route = map_route_by_id.get(route_id, {})
        origin_name = route.get("from")
        destination_name = route.get("to")
        route_day = event_days.get(route_id)
        if route_day is None and isinstance(destination_name, str):
            route_day = attraction_day_by_name.get(
                destination_name.removesuffix("景区"),
            )
        status = (
            "STALE"
            if route.get("schedule_status") == "STALE"
            or map_status == "STALE"
            else "LIVE"
            if map_status != "MISSING"
            else "MISSING"
        )
        add_marker(
            origin_name,
            kind="transit_stop",
            event_id=route_id,
            day=route_day,
            position=route.get("from_location"),
            status=status,
            collected_at=retrieved_at("map"),
        )
        add_marker(
            destination_name,
            kind="transit_stop",
            event_id=route_id,
            day=route_day,
            position=route.get("to_location"),
            status=status,
            collected_at=retrieved_at("map"),
        )
        geometry = _map_polyline(
            route.get("polyline")
            or route.get("path")
            or source_route.get("polyline")
            or source_route.get("path")
        )
        origin_marker = markers_by_name.get(str(origin_name or ""))
        destination_marker = markers_by_name.get(
            str(destination_name or "")
        )
        has_endpoints = bool(
            origin_marker
            and origin_marker.get("position")
            and destination_marker
            and destination_marker.get("position")
        )
        route_polylines.append(
            {
                "route_id": route_id,
                "event_id": route_id,
                "day": route_day,
                "from_marker_id": (
                    origin_marker.get("marker_id")
                    if origin_marker
                    else None
                ),
                "to_marker_id": (
                    destination_marker.get("marker_id")
                    if destination_marker
                    else None
                ),
                "from": origin_name,
                "to": destination_name,
                "transport_mode": (
                    route.get("transport_mode")
                    or route.get("mode")
                    or source_route.get("mode")
                    or "unknown"
                ),
                "evidence_status": status,
                "retrieved_at": retrieved_at("map"),
                "geometry_status": (
                    "EXISTING_POLYLINE"
                    if geometry
                    else "ENDPOINTS_ONLY"
                    if has_endpoints
                    else "MISSING_GEOMETRY"
                ),
                "polyline": geometry,
                "distance_meters": route.get("distance_meters"),
                "duration_seconds": route.get("duration_seconds"),
                "route_kind": "local",
            }
        )

    if rail_origin_name and rail_destination_name:
        origin_marker = markers_by_name.get(rail_origin_name)
        destination_marker = markers_by_name.get(rail_destination_name)
        origin_position = (
            origin_marker.get("position") if origin_marker else None
        )
        destination_position = (
            destination_marker.get("position")
            if destination_marker
            else None
        )
        if origin_position is not None and destination_position is not None:
            for event_id in ("rail-outbound", "rail-return"):
                route_polylines.append(
                    {
                        "route_id": f"railway-schematic-{event_id}",
                        "event_id": event_id,
                        "day": event_days.get(event_id),
                        "from_marker_id": origin_marker.get("marker_id"),
                        "to_marker_id": destination_marker.get("marker_id"),
                        "from": rail_origin_name,
                        "to": rail_destination_name,
                        "transport_mode": "railway",
                        "evidence_status": railway_status,
                        "retrieved_at": retrieved_at("railway"),
                        "geometry_status": "SCHEMATIC",
                        "polyline": [origin_position, destination_position],
                        "distance_meters": None,
                        "duration_seconds": None,
                        "route_kind": "railway_schematic",
                    }
                )

    markers = list(markers_by_name.values())
    for marker in markers:
        marker["event_id"] = sorted(marker.pop("event_ids"))
        marker["day"] = sorted(marker.pop("days"))
    return {
        "plan_version": plan_version,
        "day": [
            {
                "day": day.get("day"),
                "date": day.get("date"),
            }
            for day in days
            if isinstance(day, Mapping)
        ],
        "markers": markers,
        "route_polylines": route_polylines,
    }


def _presentation_contract(
    run: Mapping[str, object],
    event_values: list[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Project runtime facts into a read-only Web presentation contract."""

    intent_value = run.get("intent")
    guided_confirmation: dict[str, object] = {
        "show_guided_action": False,
    }
    if (
        isinstance(intent_value, Mapping)
        and intent_value.get("task_mode")
        == TaskMode.GUIDED_DISCOVERY.value
    ):
        guided_confirmation = {
            "show_guided_action": True,
        }
    result = run.get("result")
    plan = result.get("plan") if isinstance(result, Mapping) else None
    context = (
        result.get("context")
        if isinstance(result, Mapping)
        and isinstance(result.get("context"), Mapping)
        else {}
    )
    context_evidence = (
        context.get("evidence")
        if isinstance(context.get("evidence"), list)
        else []
    )
    evidence_by_domain = {
        str(item.get("domain")): item
        for item in context_evidence
        if isinstance(item, Mapping)
        and isinstance(item.get("domain"), str)
    }

    def context_snapshot_status(domain: str) -> str | None:
        item = evidence_by_domain.get(domain)
        value = item.get("value") if isinstance(item, Mapping) else None
        if not isinstance(value, Mapping):
            return None
        snapshot = value.get("snapshot")
        if isinstance(snapshot, Mapping) and isinstance(
            snapshot.get("status"),
            str,
        ):
            return str(snapshot["status"])
        status = value.get("snapshot_status")
        return str(status) if isinstance(status, str) else None

    def context_retrieved_at(domain: str) -> str | None:
        item = evidence_by_domain.get(domain)
        value = item.get("value") if isinstance(item, Mapping) else None
        if isinstance(value, Mapping):
            snapshot = value.get("snapshot")
            if isinstance(snapshot, Mapping) and isinstance(
                snapshot.get("retrieved_at"),
                str,
            ):
                return str(snapshot["retrieved_at"])
            if isinstance(value.get("retrieved_at"), str):
                return str(value["retrieved_at"])
        sources = item.get("sources") if isinstance(item, Mapping) else None
        timestamps = [
            str(source["retrieved_at"])
            for source in (sources if isinstance(sources, list) else [])
            if isinstance(source, Mapping)
            and isinstance(source.get("retrieved_at"), str)
        ]
        return max(timestamps) if timestamps else None

    days = plan.get("days") if isinstance(plan, Mapping) else None
    safe_days = days if isinstance(days, list) else []
    events = [
        event
        for day in safe_days
        if isinstance(day, Mapping)
        for event in (
            day.get("events")
            if isinstance(day.get("events"), list)
            else []
        )
        if isinstance(event, Mapping)
    ]
    rail_events = [
        event
        for event in events
        if str(event.get("event_id", "")).startswith("rail-")
    ]
    attraction_events = [
        event for event in events if event.get("type") == "attraction"
    ]
    timeline_local_transit = [
        event
        for event in events
        if event.get("type") == "transit"
        and not str(event.get("event_id", "")).startswith("rail-")
    ]
    planning_input = (
        plan.get("planning_input")
        if isinstance(plan, Mapping)
        and isinstance(plan.get("planning_input"), Mapping)
        else {}
    )
    planned_local_transit = (
        plan.get("local_transit_events")
        if isinstance(plan, Mapping)
        and isinstance(plan.get("local_transit_events"), list)
        else planning_input.get("local_transit_events")
        if isinstance(planning_input.get("local_transit_events"), list)
        else timeline_local_transit
    )
    local_transit_events = [
        event
        for event in planned_local_transit
        if isinstance(event, Mapping)
    ]
    requirements = (
        plan.get("display_requirements")
        if isinstance(plan, Mapping)
        and isinstance(plan.get("display_requirements"), Mapping)
        else {}
    )
    railway_status = "MISSING"
    if rail_events:
        railway_status = (
            "STALE"
            if any(
                event.get("snapshot_status") == "STALE"
                or event.get("schedule_status") == "STALE"
                for event in rail_events
            )
            else "LIVE"
        )
    attraction_status = (
        "STALE"
        if attraction_events
        and context_snapshot_status("web") == "STALE"
        else "LIVE"
        if attraction_events
        else "MISSING"
    )
    local_transit_status = (
        "STALE"
        if local_transit_events
        and any(
            event.get("schedule_status") == "STALE"
            for event in local_transit_events
        )
        else "LIVE"
        if local_transit_events
        else "MISSING"
    )
    accommodation_status = (
        "STALE"
        if requirements.get("accommodation_base") is True
        and context_snapshot_status("web") == "STALE"
        else "LIVE"
        if requirements.get("accommodation_base") is True
        else "MISSING"
    )
    detailed_ready = (
        len(safe_days) > 0
        and len(attraction_events) >= 3
        and len(local_transit_events) >= len(attraction_events)
        and railway_status in {"LIVE", "STALE"}
        and accommodation_status in {"LIVE", "STALE"}
    )
    blockers = (
        plan.get("conditional_blockers")
        if isinstance(plan, Mapping)
        and isinstance(plan.get("conditional_blockers"), list)
        else []
    )
    budget_events = list(events)
    budget_event_ids = {
        str(event.get("event_id"))
        for event in budget_events
        if event.get("event_id") is not None
    }
    for event in local_transit_events:
        event_id = str(event.get("event_id"))
        if event_id not in budget_event_ids:
            budget_events.append(event)
            budget_event_ids.add(event_id)
    web_item = evidence_by_domain.get("web")
    web_value = (
        web_item.get("value")
        if isinstance(web_item, Mapping)
        and isinstance(web_item.get("value"), Mapping)
        else {}
    )
    return {
        "day_count": len(safe_days),
        "event_count": len(events),
        "attraction_count": len(attraction_events),
        "local_transit_count": len(local_transit_events),
        "detailed_itinerary_ready": detailed_ready,
        "detail_gate": {
            "minimum_attractions": 3,
            "minimum_local_transit": "one base-to-attraction segment plus "
            "the attraction chain",
        },
        "evidence_statuses": [
            {
                "domain": "railway",
                "label": "跨城铁路",
                "status": railway_status,
                "count": len(rail_events),
                "retrieved_at": context_retrieved_at("railway"),
            },
            {
                "domain": "attraction",
                "label": "景点",
                "status": attraction_status,
                "count": len(attraction_events),
                "retrieved_at": context_retrieved_at("web"),
            },
            {
                "domain": "local_transit",
                "label": "当地交通",
                "status": local_transit_status,
                "count": len(local_transit_events),
                "retrieved_at": context_retrieved_at("map"),
            },
            {
                "domain": "accommodation",
                "label": "住宿基地",
                "status": accommodation_status,
                "count": (
                    1
                    if accommodation_status in {"LIVE", "STALE"}
                    else 0
                ),
                "retrieved_at": context_retrieved_at("web"),
            },
        ],
        "blockers": [dict(item) for item in blockers if isinstance(item, Mapping)],
        "guided_confirmation": guided_confirmation,
        "compact_progress": _compact_progress_contract(
            run,
            event_values or [],
        ),
        "planning_handoff": _planning_handoff_contract(run),
        "budget_summary": _budget_summary(
            budget_events,
            (
                int(intent_value.get("travelers"))
                if isinstance(intent_value, Mapping)
                and isinstance(intent_value.get("travelers"), int)
                and not isinstance(intent_value.get("travelers"), bool)
                else 1
            ),
        ),
        "accommodation_choices": {
            "budget_total_cny": (
                intent_value.get("accommodation_budget_total_cny")
                if isinstance(intent_value, Mapping)
                else None
            ),
            "budget_per_night_cny": (
                intent_value.get("accommodation_budget_per_night_cny")
                if isinstance(intent_value, Mapping)
                else None
            ),
            "rooms": (
                intent_value.get("rooms")
                if isinstance(intent_value, Mapping)
                else None
            ),
            "price_filter_status": (
                "UNAVAILABLE_NO_PRICE_SOURCE"
                if web_value.get("hotel_price_status") == "UNKNOWN"
                else "AVAILABLE"
            ),
            "current_base": deepcopy(web_value.get("hotel_area")),
            "candidates": deepcopy(
                web_value.get("hotel_candidates", [])
            ),
            "retrieved_at": context_retrieved_at("web"),
        },
    }


def _planning_handoff_contract(
    run: Mapping[str, object],
) -> dict[str, object] | None:
    intent = run.get("intent")
    result = run.get("result")
    if (
        not isinstance(intent, Mapping)
        or intent.get("task_mode") != TaskMode.DIRECT_PLAN.value
        or not isinstance(result, Mapping)
        or result.get("stage") != "guided_discovery"
    ):
        return None
    destination = intent.get("destination_anchor")
    options = result.get("options")
    if not isinstance(destination, str) or not isinstance(options, list):
        return None
    selected = next(
        (
            option
            for option in options
            if isinstance(option, Mapping)
            and option.get("destination_anchor") == destination
        ),
        None,
    )
    if not isinstance(selected, Mapping):
        return None
    live = _current_run_evidence(str(run.get("run_id") or ""))
    railway = live.get("railway")
    web = live.get("web")
    map_item = live.get("map")
    web_value = (
        web.get("value")
        if isinstance(web, Mapping)
        and isinstance(web.get("value"), Mapping)
        else {}
    )
    map_value = (
        map_item.get("value")
        if isinstance(map_item, Mapping)
        and isinstance(map_item.get("value"), Mapping)
        else {}
    )
    railway_value = (
        railway.get("value")
        if isinstance(railway, Mapping)
        and isinstance(railway.get("value"), Mapping)
        else {}
    )
    attractions = [
        {
            "attraction_id": item.get("attraction_id") or item.get("id"),
            "name": item.get("name"),
            "features": list(item.get("features", []))
            if isinstance(item.get("features"), list)
            else [],
            "scheduling_traits": list(item.get("scheduling_traits", []))
            if isinstance(item.get("scheduling_traits"), list)
            else [],
            "opening_hours": dict(item.get("opening_hours", {}))
            if isinstance(item.get("opening_hours"), Mapping)
            else {"status": "unknown"},
            "ticket": dict(item.get("ticket", {}))
            if isinstance(item.get("ticket"), Mapping)
            else {"status": "unknown"},
        }
        for item in (
            web_value.get("attractions")
            if isinstance(web_value.get("attractions"), list)
            else []
        )
        if isinstance(item, Mapping)
        and isinstance(item.get("name"), str)
    ]
    local_transit = [
        {
            key: item.get(key)
            for key in (
                "from",
                "to",
                "duration_seconds",
                "distance_meters",
                "fare",
            )
        }
        for item in (
            map_value.get("local_transit")
            if isinstance(map_value.get("local_transit"), list)
            else []
        )
        if isinstance(item, Mapping)
    ]
    dates = _intent_day_skeleton(intent)
    return {
        "destination_anchor": destination,
        "feasibility_status": selected.get("feasibility_status"),
        "roundtrip_transport": dict(
            selected.get("roundtrip_transport")
            if isinstance(selected.get("roundtrip_transport"), Mapping)
            else {}
        ),
        "playable_time_seconds": selected.get("playable_time_seconds"),
        "budget_headroom_after_known_transport_cny": selected.get(
            "budget_headroom_after_known_transport_cny"
        ),
        "evidence_statuses": [
            dict(item)
            for item in (
                selected.get("evidence_statuses")
                if isinstance(selected.get("evidence_statuses"), list)
                else []
            )
            if isinstance(item, Mapping)
        ],
        "evidence_missing": [
            str(item)
            for item in (
                selected.get("evidence_missing")
                if isinstance(selected.get("evidence_missing"), list)
                else []
            )
        ],
        "railway": {
            "status": (
                railway_value.get("snapshot", {}).get("status")
                if isinstance(railway_value.get("snapshot"), Mapping)
                else "MISSING"
            ),
            "retrieved_at": (
                railway_value.get("snapshot", {}).get("retrieved_at")
                if isinstance(railway_value.get("snapshot"), Mapping)
                else None
            ),
            "outbound": dict(railway_value.get("outbound", {}))
            if isinstance(railway_value.get("outbound"), Mapping)
            else None,
            "return": dict(railway_value.get("return", {}))
            if isinstance(railway_value.get("return"), Mapping)
            else None,
            "roundtrip_fare_cny": railway_value.get(
                "roundtrip_fare_cny"
            ),
        },
        "hotel_area": (
            dict(web_value.get("hotel_area", {}))
            if isinstance(web_value.get("hotel_area"), Mapping)
            else None
        ),
        "attractions": attractions,
        "local_transit": local_transit,
        "days": dates,
    }


def _current_run_evidence(
    run_id: str,
) -> dict[str, Mapping[str, object]]:
    if not run_id:
        return {}
    run_directory = DEFAULT_AGENT_STORE.run_directory(run_id)
    if run_directory is None:
        return {}
    path = run_directory / "evidence" / "current.json"
    legacy = run_directory / "evidence.json"
    if not path.is_file() and legacy.is_file():
        path = legacy
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    current = document.get("current") if isinstance(document, Mapping) else None
    if not isinstance(current, list):
        return {}
    return {
        str(item["domain"]): item
        for item in current
        if isinstance(item, Mapping)
        and isinstance(item.get("domain"), str)
    }


def _intent_day_skeleton(
    intent: Mapping[str, object],
) -> list[dict[str, object]]:
    earliest = intent.get("earliest_departure_at")
    latest = intent.get("latest_return_at")
    if not isinstance(earliest, str) or not isinstance(latest, str):
        return []
    try:
        first = datetime.fromisoformat(earliest).date()
        last = datetime.fromisoformat(latest).date()
    except ValueError:
        return []
    days: list[dict[str, object]] = []
    cursor = first
    while cursor <= last:
        days.append(
            {
                "day": len(days) + 1,
                "date": cursor.isoformat(),
            }
        )
        cursor = cursor.fromordinal(cursor.toordinal() + 1)
    return days


def _budget_summary(
    events: list[Mapping[str, object]],
    travelers: int,
) -> list[dict[str, object]]:
    rows = {
        "railway": {
            "label": "铁路",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": False,
        },
        "local_transit": {
            "label": "当地交通",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": False,
        },
        "accommodation": {
            "label": "住宿",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": True,
        },
        "tickets": {
            "label": "门票",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": False,
        },
        "meals": {
            "label": "餐饮",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": True,
        },
        "contingency": {
            "label": "机动",
            "known_cny": 0.0,
            "estimated_cny": 0.0,
            "unknown": True,
        },
    }
    for event in events:
        event_id = str(event.get("event_id") or "")
        fare = event.get("fare")
        amount = (
            fare.get("amount_cny")
            if isinstance(fare, Mapping)
            else None
        )
        if event_id in {"rail-outbound", "rail-return"}:
            if isinstance(amount, (int, float)) and not isinstance(
                amount,
                bool,
            ):
                rows["railway"]["known_cny"] += float(amount) * travelers
            else:
                rows["railway"]["unknown"] = True
        elif event.get("type") == "transit":
            if isinstance(amount, (int, float)) and not isinstance(
                amount,
                bool,
            ):
                rows["local_transit"]["estimated_cny"] += (
                    float(amount) * travelers
                )
            else:
                rows["local_transit"]["unknown"] = True
        elif event.get("type") == "attraction":
            ticket = event.get("ticket")
            ticket_amount = (
                ticket.get("amount_cny")
                if isinstance(ticket, Mapping)
                else None
            )
            if isinstance(ticket_amount, (int, float)) and not isinstance(
                ticket_amount,
                bool,
            ):
                rows["tickets"]["known_cny"] += (
                    float(ticket_amount) * travelers
                )
            else:
                rows["tickets"]["unknown"] = True
    return list(rows.values())


def _compact_progress_contract(
    run: Mapping[str, object],
    events: list[Mapping[str, object]],
) -> dict[str, object] | None:
    guided = _guided_progress_contract(run, events)
    if guided is not None:
        candidate_count = max(1, int(guided["candidate_count"]))
        completed_count = min(
            candidate_count,
            int(guided["completed_count"]),
        )
        return {
            "kind": "guided_comparison",
            "state": (
                "running"
                if guided["running"]
                else "completed"
                if guided["completed"]
                else "waiting"
            ),
            "total_count": candidate_count,
            "completed_count": completed_count,
            "percent_complete": min(
                50,
                25 + int(25 * completed_count / candidate_count),
            ),
            "current_task": "比较目的地方案",
            "elapsed_seconds": guided["elapsed_seconds"],
            "last_progress_at": guided["last_progress_at"],
            "partial_options": guided["partial_options"],
        }
    intent = run.get("intent")
    if (
        not isinstance(intent, Mapping)
        or intent.get("task_mode") != TaskMode.DIRECT_PLAN.value
        or run.get("status") == RunStatus.AWAITING_CONFIRMATION.value
    ):
        return None
    phase_events: list[Mapping[str, object]] = []
    phase_started_at = run.get("started_at")
    for index, event in enumerate(events):
        if event.get("event_type") in {
            "discovery.option_selected",
            "revision.started",
        }:
            phase_events = events[index:]
            phase_started_at = event.get("occurred_at")
    if not phase_events:
        phase_events = events
    completed: set[str] = set()
    pending: list[str] = []
    current_task = "查询交通与景点"
    last_progress_at: str | None = None
    planner_started = False
    total_count = len(("railway", "web", "map", "planner"))
    tool_labels = {
        "railway": "正在核验跨城铁路",
        "web": "正在补充网页事实",
        "map": "正在补充当地地图与交通",
        "planner": "正在生成详细行程",
    }
    for event in phase_events:
        occurred_at = event.get("occurred_at")
        if isinstance(occurred_at, str):
            last_progress_at = occurred_at
        details = event.get("details")
        if not isinstance(details, Mapping):
            details = {}
        event_type = event.get("event_type")
        tool = details.get("tool")
        if event_type == "planning.actions.initialized":
            initialized_total = details.get("total_actions")
            if isinstance(initialized_total, int) and not isinstance(
                initialized_total,
                bool,
            ):
                total_count = initialized_total
            completed.update(
                str(item)
                for item in details.get("completed_actions", [])
                if str(item) in tool_labels
            )
            pending = [
                str(item)
                for item in details.get("pending_actions", [])
                if str(item) in tool_labels
            ]
            if pending:
                current_task = (
                    "生成详细行程"
                    if pending[0] == "planner"
                    else "查询交通与景点"
                )
        elif (
            event_type in {"planning.evidence.reused", "tool.completed"}
            and str(tool) in tool_labels
        ):
            completed.add(str(tool))
            if str(tool) == "planner":
                current_task = "生成详细行程"
        elif event_type == "tool.started" and str(tool) in tool_labels:
            planner_started = planner_started or str(tool) == "planner"
            current_task = (
                "生成详细行程"
                if planner_started
                else "查询交通与景点"
            )
    status = run.get("status")
    state = (
        "completed"
        if status == RunStatus.COMPLETED.value
        else "blocked"
        if status in {RunStatus.BLOCKED.value, RunStatus.FAILED.value}
        else "running"
        if status == RunStatus.RUNNING.value
        else "waiting"
    )
    if state == "completed":
        current_task = "生成详细行程"
        completed.add("planner")
    evidence_completed = len(completed & {"railway", "web", "map"})
    percent_complete = 50 + int(25 * evidence_completed / 3)
    if planner_started or "planner" in completed:
        percent_complete = max(percent_complete, 75)
    if state == "completed":
        percent_complete = 100
    else:
        percent_complete = min(percent_complete, 99)
    elapsed_seconds = _elapsed_seconds(phase_started_at)
    return {
        "kind": "detailed_planning",
        "state": state,
        "total_count": total_count,
        "completed_count": min(total_count, len(completed)),
        "percent_complete": percent_complete,
        "current_task": current_task,
        "elapsed_seconds": elapsed_seconds,
        "last_progress_at": last_progress_at,
        "partial_options": [],
    }


def _elapsed_seconds(started_at: object) -> int:
    if not isinstance(started_at, str):
        return 0
    try:
        return max(
            0,
            int(
                (
                    datetime.now().astimezone()
                    - datetime.fromisoformat(started_at)
                ).total_seconds()
            ),
        )
    except ValueError:
        return 0


def _guided_progress_contract(
    run: Mapping[str, object],
    events: list[Mapping[str, object]],
) -> dict[str, object] | None:
    intent = run.get("intent")
    if (
        not isinstance(intent, Mapping)
        or intent.get("task_mode") not in {
            TaskMode.OPEN_DISCOVERY.value,
            TaskMode.GUIDED_DISCOVERY.value,
        }
    ):
        return None
    result = run.get("result")
    final_options = (
        result.get("options")
        if isinstance(result, Mapping)
        and result.get("stage") in {
            "open_discovery",
            "guided_discovery",
        }
        and isinstance(result.get("options"), list)
        else []
    )
    streamed: dict[str, dict[str, object]] = {}
    expected_count = 0
    current_task = "等待开始比较"
    last_progress_at: str | None = None
    for event in events:
        event_type = event.get("event_type")
        occurred_at = event.get("occurred_at")
        details = event.get("details")
        if not isinstance(details, Mapping):
            details = {}
        if isinstance(occurred_at, str):
            last_progress_at = occurred_at
        if event_type == "guided.comparison.started":
            count = details.get("candidate_count")
            if isinstance(count, int) and not isinstance(count, bool):
                expected_count = count
            current_task = "正在启动并行核验"
        elif event_type == "guided.candidate.started":
            count = details.get("candidate_count")
            if isinstance(count, int) and not isinstance(count, bool):
                expected_count = count
            current_task = "正在并行核验候选方案"
        elif event_type == "guided.domain.started":
            current_task = _guided_domain_label(details.get("domain"))
        elif event_type == "guided.domain.timeout":
            current_task = "部分数据源超时，继续处理其他方案"
        elif event_type == "guided.candidate.completed":
            option = details.get("option")
            destination_id = details.get("destination_id")
            if isinstance(option, Mapping) and isinstance(
                destination_id,
                str,
            ):
                streamed[destination_id] = dict(option)
            current_task = "已返回一个方案，继续核验其余方案"
    for option in final_options:
        if not isinstance(option, Mapping):
            continue
        destination_id = option.get("destination_id")
        if isinstance(destination_id, str):
            streamed[destination_id] = dict(option)
    if isinstance(result, Mapping):
        expected = result.get("expected_option_count")
        if isinstance(expected, int) and not isinstance(expected, bool):
            expected_count = expected
    started_at = run.get("started_at")
    elapsed_seconds = _elapsed_seconds(started_at)
    status = run.get("status")
    if status == RunStatus.COMPLETED.value:
        current_task = (
            "比较已取消，以下为已取得的部分结果"
            if isinstance(result, Mapping) and result.get("cancelled") is True
            else "区域方案比较完成"
        )
    return {
        "candidate_count": expected_count,
        "completed_count": len(streamed),
        "current_task": current_task,
        "elapsed_seconds": elapsed_seconds,
        "last_progress_at": last_progress_at,
        "running": status == RunStatus.RUNNING.value,
        "completed": status == RunStatus.COMPLETED.value,
        "partial_options": list(streamed.values()),
    }


def _guided_domain_label(value: object) -> str:
    return {
        "railway": "正在核验往返铁路",
        "map": "正在核验目的地地图信息",
        "web": "正在核验网页事实",
    }.get(str(value), "正在核验真实数据")


def _intent_from_trip_text(text: str) -> dict[str, object]:
    """Extract explicit Chinese trip fields without inventing facts."""

    normalized = " ".join(text.strip().split())
    if not normalized:
        raise ProductRequestError("旅行需求不能为空。")
    origin_match = re.search(
        r"(?:从)?([^,，。；;\s]{2,12}?)(?:出发|走)",
        normalized,
    )
    origin = origin_match.group(1) if origin_match else None
    guided_match = re.search(
        r"(倾向|优先|大概想去|考虑)([^,，。；;]{2,24})",
        normalized,
    )
    direct_match = re.search(
        r"(确定去?|就去|已经订了)([^,，。；;]{2,20})",
        normalized,
    )
    destination: str | None = None
    expression: str | None = None
    audit_requested = any(
        token in normalized
        for token in ("审计行程", "审核攻略", "检查已有计划")
    )
    mode = (
        TaskMode.PLAN_AUDIT
        if audit_requested
        else TaskMode.OPEN_DISCOVERY
    )
    if audit_requested:
        expression = "已有计划审计"
    elif direct_match:
        expression = direct_match.group(0).strip()
        destination = _trim_destination_phrase(direct_match.group(2))
        mode = TaskMode.DIRECT_PLAN
    elif guided_match:
        expression = guided_match.group(0).strip()
        destination = _trim_destination_phrase(guided_match.group(2))
        mode = TaskMode.GUIDED_DISCOVERY

    date_matches = list(
        re.finditer(r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日", normalized)
    )
    earliest: str | None = None
    latest: str | None = None
    if date_matches:
        first = date_matches[0]
        year = int(first.group(1) or datetime.now().year)
        hour, minute = _clock_after(normalized[first.end():], default=9)
        earliest = datetime(
            year,
            int(first.group(2)),
            int(first.group(3)),
            hour,
            minute,
        ).isoformat(timespec="minutes")
    if len(date_matches) >= 2:
        last = date_matches[-1]
        year = int(last.group(1) or date_matches[0].group(1) or datetime.now().year)
        hour, minute = _clock_after(normalized[last.end():], default=22)
        latest = datetime(
            year,
            int(last.group(2)),
            int(last.group(3)),
            hour,
            minute,
        ).isoformat(timespec="minutes")

    travelers_match = re.search(
        r"([1-9]\d*|[一二两三四五六七八九十])(?:个)?人",
        normalized,
    )
    budget_match = re.search(
        r"(?:总预算|预算)?\s*([1-9]\d*(?:\.\d+)?)\s*元",
        normalized,
    )
    room_match = re.search(r"([1-9]\d*)\s*间房", normalized)
    accommodation_total_match = re.search(
        r"住宿总预算\s*([1-9]\d*(?:\.\d+)?)",
        normalized,
    )
    accommodation_nightly_match = re.search(
        r"(?:住宿)?每晚\s*([1-9]\d*(?:\.\d+)?)",
        normalized,
    )
    pace = (
        "relaxed"
        if any(token in normalized for token in ("轻松", "休闲", "慢一点"))
        else "intensive"
        if any(token in normalized for token in ("紧凑", "特种兵", "尽量多玩"))
        else "standard"
        if any(token in normalized for token in ("适中", "标准"))
        else None
    )
    transport = []
    for token, value in (
        ("高铁", "high_speed_rail"),
        ("火车", "rail"),
        ("自驾", "driving"),
        ("飞机", "flight"),
    ):
        if token in normalized and value not in transport:
            transport.append(value)
    themes = [
        theme
        for token, theme in (
            ("海边", "海边"),
            ("海岛", "海边"),
            ("山水", "山水"),
            ("爬山", "山"),
            ("古村", "古村"),
            ("城市", "城市"),
        )
        if token in normalized
    ]
    return {
        "task_mode": mode.value,
        "origin": origin,
        "destination_anchor": destination,
        "earliest_departure_at": earliest,
        "latest_return_at": latest,
        "travelers": (
            _explicit_count(travelers_match.group(1))
            if travelers_match else None
        ),
        "total_budget_cny": (
            float(budget_match.group(1)) if budget_match else None
        ),
        "pace": pace,
        "transport_preferences": transport,
        "themes": list(dict.fromkeys(themes)),
        "needs_confirmation": [],
        "missing_fields": [],
        "interpretation": normalized,
        "classification_basis": "standalone_explicit_text_extraction",
        "destination_expression": expression,
        "accommodation_budget_total_cny": (
            float(accommodation_total_match.group(1))
            if accommodation_total_match
            else None
        ),
        "accommodation_budget_per_night_cny": (
            float(accommodation_nightly_match.group(1))
            if accommodation_nightly_match
            else None
        ),
        "rooms": int(room_match.group(1)) if room_match else None,
    }


def _trim_destination_phrase(value: str) -> str:
    result = value.strip()
    result = re.sub(r"^(?:就去|去)", "", result).strip()
    result = re.split(r"(?:那块|一带)?\s*(?:高铁|火车|自驾|飞机)", result)[0]
    result = re.sub(r"(?:那块|一带)$", "", result).strip()
    return result


def _explicit_count(value: str) -> int:
    if value.isdigit():
        return int(value)
    mapping = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return mapping[value]


def _clock_after(value: str, *, default: int) -> tuple[int, int]:
    sample = value[:20]
    explicit = re.search(r"(\d{1,2})(?::(\d{1,2})|点(?:(\d{1,2})分)?)", sample)
    if explicit:
        return int(explicit.group(1)), int(explicit.group(2) or explicit.group(3) or 0)
    if "中午" in sample:
        return 12, 0
    if "晚上" in sample or "夜里" in sample:
        return 22 if default >= 18 else 18, 0
    if "下午" in sample:
        return 14, 0
    if "早上" in sample or "上午" in sample:
        return 9, 0
    return default, 0


def _start_candidate_comparison(
    run_id: str,
    *,
    mode: TaskMode,
) -> dict[str, object]:
    """Start candidate generation and coarse comparison for one mode."""

    run = DEFAULT_AGENT_STORE.get_run(run_id)
    if run.intent.task_mode is not mode:
        raise ProductRequestError(
            f"{mode.value} handler received another task mode"
        )
    DEFAULT_AGENT_STORE.start(run_id)
    with _GUIDED_CANCELLATIONS_LOCK:
        _GUIDED_CANCELLATIONS[run_id] = threading.Event()
    background = (
        _open_discovery_background
        if mode is TaskMode.OPEN_DISCOVERY
        else _guided_discovery_background
    )
    thread = threading.Thread(
        target=background,
        args=(run_id,),
        name=f"trip-decider-{mode.value.lower()}-{run_id}",
        daemon=True,
    )
    thread.start()
    return {
        "run_id": run_id,
        "status": "CANDIDATE_COMPARISON_RUNNING",
        "task_mode": mode.value,
        "pipeline": [
            "candidate_generation",
            "coarse_feasibility",
            "candidate_comparison",
            "user_selection",
        ],
    }


def _execute_open_discovery(run_id: str) -> dict[str, object]:
    return _start_candidate_comparison(
        run_id,
        mode=TaskMode.OPEN_DISCOVERY,
    )


def _execute_guided_discovery(run_id: str) -> dict[str, object]:
    return _start_candidate_comparison(
        run_id,
        mode=TaskMode.GUIDED_DISCOVERY,
    )


def _execute_direct_plan(run_id: str) -> dict[str, object]:
    run = DEFAULT_AGENT_STORE.get_run(run_id)
    if run.intent.task_mode is not TaskMode.DIRECT_PLAN:
        raise ProductRequestError(
            "DIRECT_PLAN handler received another task mode"
        )
    action_state = start_action_loop(run_id)
    thread = threading.Thread(
        target=_run_action_loop_background,
        args=(run_id,),
        name=f"trip-decider-actions-{run_id}",
        daemon=True,
    )
    thread.start()
    return action_state


def _audit_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    try:
        if "T" in normalized:
            return datetime.fromisoformat(normalized)
        parsed = datetime.strptime(normalized, "%H:%M")
        return parsed
    except ValueError:
        return None


def _audit_plan_document(value: Mapping[str, object]) -> dict[str, object]:
    """Perform structural plan checks without invoking the Planner."""

    conflicts: list[dict[str, object]] = []
    suggestions: list[dict[str, str]] = []
    days = value.get("days")
    event_count = 0
    if not isinstance(days, list) or not days:
        conflicts.append(
            {
                "code": "AUDIT_DAYS_MISSING",
                "path": "/days",
                "message": "已有Plan没有可审计的每日安排。",
            }
        )
    else:
        for day_index, day in enumerate(days):
            day_path = f"/days/{day_index}"
            if not isinstance(day, Mapping):
                conflicts.append(
                    {
                        "code": "AUDIT_DAY_INVALID",
                        "path": day_path,
                        "message": "每日安排必须是对象。",
                    }
                )
                continue
            events = day.get("events", day.get("activities"))
            if not isinstance(events, list):
                conflicts.append(
                    {
                        "code": "AUDIT_EVENTS_MISSING",
                        "path": f"{day_path}/events",
                        "message": "该日没有结构化事件列表。",
                    }
                )
                continue
            previous_end: datetime | None = None
            for event_index, event in enumerate(events):
                event_count += 1
                event_path = f"{day_path}/events/{event_index}"
                if not isinstance(event, Mapping):
                    conflicts.append(
                        {
                            "code": "AUDIT_EVENT_INVALID",
                            "path": event_path,
                            "message": "行程事件必须是对象。",
                        }
                    )
                    continue
                start = _audit_time(
                    event.get("start_at", event.get("start"))
                )
                end = _audit_time(event.get("end_at", event.get("end")))
                if start is not None and end is not None and end <= start:
                    conflicts.append(
                        {
                            "code": "AUDIT_TIME_ORDER_INVALID",
                            "path": event_path,
                            "message": "事件结束时间不晚于开始时间。",
                        }
                    )
                if (
                    previous_end is not None
                    and start is not None
                    and start < previous_end
                ):
                    conflicts.append(
                        {
                            "code": "AUDIT_EVENT_OVERLAP",
                            "path": event_path,
                            "message": "该事件与前一事件时间重叠。",
                        }
                    )
                if end is not None:
                    previous_end = end
                event_type = event.get("type")
                location = event.get("location", event.get("place"))
                if (
                    event_type in {"transit", "attraction", "hotel"}
                    and not location
                ):
                    conflicts.append(
                        {
                            "code": "AUDIT_LOCATION_MISSING",
                            "path": event_path,
                            "message": "该事件缺少明确地点。",
                        }
                    )
    if conflicts:
        suggestions.append(
            {
                "code": "RESOLVE_AUDIT_CONFLICTS",
                "message": "先补齐缺失字段并消除时间重叠，再修改原计划。",
            }
        )
    else:
        suggestions.append(
            {
                "code": "RETAIN_EXISTING_PLAN",
                "message": "当前结构检查未发现冲突；仍需核验事实来源。",
            }
        )
    return {
        "input_kind": "structured_plan",
        "parsed": {
            "day_count": len(days) if isinstance(days, list) else 0,
            "event_count": event_count,
        },
        "validation_status": (
            "CONFLICTS_FOUND" if conflicts else "STRUCTURALLY_VALID"
        ),
        "conflicts": conflicts,
        "modification_suggestions": suggestions,
    }


def _audit_guide_content(value: str) -> dict[str, object]:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        raise ProductRequestError("攻略内容不能为空")
    timed_lines = [
        index + 1
        for index, line in enumerate(lines)
        if re.search(r"(?:[01]?\d|2[0-3]):[0-5]\d", line)
    ]
    conflicts: list[dict[str, object]] = []
    if not timed_lines:
        conflicts.append(
            {
                "code": "AUDIT_TIMELINE_UNSTRUCTURED",
                "path": "/content",
                "message": "攻略未提供可验证的明确时间安排。",
            }
        )
    return {
        "input_kind": "guide_text",
        "parsed": {
            "nonempty_line_count": len(lines),
            "timed_line_count": len(timed_lines),
        },
        "validation_status": (
            "INSUFFICIENT_STRUCTURE" if conflicts else "PARSED_FOR_REVIEW"
        ),
        "conflicts": conflicts,
        "modification_suggestions": [
            {
                "code": "STRUCTURE_GUIDE_TIMELINE",
                "message": (
                    "请补充每日时间、地点和交通衔接后再核验可行性。"
                    if conflicts
                    else "请继续核验交通、开放时间和费用来源。"
                ),
            }
        ],
    }


def _execute_plan_audit(
    run_id: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    run = DEFAULT_AGENT_STORE.get_run(run_id)
    if run.intent.task_mode is not TaskMode.PLAN_AUDIT:
        raise ProductRequestError(
            "audit endpoint only accepts PLAN_AUDIT runs"
        )
    if run.status is not RunStatus.CONFIRMED:
        raise ProductRequestError("audit run must be confirmed")
    raw_plan = payload.get("plan")
    raw_content = payload.get("content")
    if isinstance(raw_plan, Mapping) and raw_content is None:
        audit = _audit_plan_document(raw_plan)
    elif isinstance(raw_content, str) and raw_plan is None:
        audit = _audit_guide_content(raw_content)
    else:
        raise ProductRequestError(
            "audit requires exactly one of plan or content"
        )
    DEFAULT_AGENT_STORE.start(run_id)
    DEFAULT_AGENT_STORE.append_event(
        run_id,
        event_type="audit.completed",
        status="completed",
        message="已有计划审计完成。",
        details={"planner_invoked": False},
    )
    DEFAULT_AGENT_STORE.complete(
        run_id,
        {
            "stage": "plan_audit",
            "task_mode": TaskMode.PLAN_AUDIT.value,
            "audit": audit,
            "planner_invoked": False,
        },
    )
    return {
        "status": "AUDIT_COMPLETED",
        "planner_invoked": False,
    }


_MODE_EXECUTION_HANDLERS = {
    TaskMode.OPEN_DISCOVERY: _execute_open_discovery,
    TaskMode.GUIDED_DISCOVERY: _execute_guided_discovery,
    TaskMode.DIRECT_PLAN: _execute_direct_plan,
}


def _trip_post(
    path: str,
    payload: dict[str, object],
) -> tuple[HTTPStatus, dict[str, object]]:
    if path == "/api/trips":
        intent = payload.get("intent")
        text = payload.get("text")
        if isinstance(text, str):
            intent = _intent_from_trip_text(text)
        if not isinstance(intent, Mapping):
            raise ProductRequestError("请输入旅行需求。")
        run = create_run(intent)
        return HTTPStatus.CREATED, _run_response(run.run_id)
    parts = [unquote(part) for part in path.split("/") if part]
    if len(parts) < 4 or parts[:2] != ["api", "trips"]:
        raise ProductRequestError("unknown trip API path")
    run_id = parts[2]
    if (
        len(parts) == 6
        and parts[3] == "candidates"
        and parts[5] == "select"
    ):
        action = "select-candidate"
        payload = {**payload, "destination_id": parts[4]}
    elif (
        len(parts) == 6
        and parts[3] == "actions"
        and parts[5] == "retry"
    ):
        action = "retry-action"
        payload = {**payload, "action_id": parts[4]}
    elif len(parts) == 4:
        action = parts[3]
    else:
        raise ProductRequestError("unknown trip API path")
    if action == "confirm":
        intent = payload.get("intent")
        if intent is not None and not isinstance(intent, Mapping):
            raise ProductRequestError("intent must be an object")
        run = confirm_intent(run_id, intent)
        return HTTPStatus.OK, _run_response(run.run_id)
    if action == "execute":
        run = DEFAULT_AGENT_STORE.get_run(run_id)
        if run.status is RunStatus.RUNNING:
            action_id = payload.get("action_id")
            action_state = (
                execute_registered_action(run_id, action_id)
                if isinstance(action_id, str)
                else run_until_blocked(run_id)
            )
            response = _run_response(run_id)
            response["action_loop"] = action_state
            return HTTPStatus.OK, response
        if (
            run.status in {RunStatus.COMPLETED, RunStatus.BLOCKED}
            and run.intent.task_mode is TaskMode.DIRECT_PLAN
            and isinstance(run.result, Mapping)
        ):
            action_state = restart_action_loop_for_intent(
                run_id,
                run.intent,
            )
            thread = threading.Thread(
                target=_run_action_loop_background,
                args=(run_id,),
                name=f"trip-decider-continue-{run_id}",
                daemon=True,
            )
            thread.start()
            response = _run_response(run_id)
            response["action_loop"] = action_state
            return HTTPStatus.ACCEPTED, response
        if run.status is not RunStatus.CONFIRMED:
            raise ProductRequestError(
                "run must be confirmed before execution"
            )
        if run.intent.blocking_missing_fields:
            raise ProductRequestError(
                "旅行条件不完整，不能执行。"
            )
        if run.intent.task_mode is TaskMode.PLAN_AUDIT:
            raise ProductRequestError(
                "PLAN_AUDIT must use /api/trips/<id>/audit with plan or content"
            )
        handler = _MODE_EXECUTION_HANDLERS[run.intent.task_mode]
        action_state = handler(run_id)
        response = _run_response(run_id)
        response["action_loop"] = action_state
        return HTTPStatus.ACCEPTED, response
    if action == "select-candidate":
        destination_id = payload.get("destination_id")
        if not isinstance(destination_id, str) or not destination_id:
            raise ProductRequestError("destination_id must be text")
        previous = DEFAULT_AGENT_STORE.get_run(run_id)
        result = previous.result
        options = (
            result.get("options")
            if isinstance(result, Mapping)
            and result.get("stage") in {
                "open_discovery",
                "guided_discovery",
            }
            else None
        )
        if (
            previous.status is not RunStatus.COMPLETED
            or not isinstance(options, list)
        ):
            raise ProductRequestError(
                "guided comparison must complete before selection"
            )
        selected = next(
            (
                option
                for option in options
                if isinstance(option, Mapping)
                and option.get("destination_id") == destination_id
            ),
            None,
        )
        if not isinstance(selected, Mapping):
            raise ProductRequestError(
                "destination_id is not in this comparison"
            )
        destination = selected.get("destination_anchor")
        if not isinstance(destination, str) or not destination:
            raise ProductRequestError(
                "selected option omitted destination_anchor"
            )
        intent_value = previous.intent.to_dict()
        intent_value.update(
            {
                "task_mode": TaskMode.DIRECT_PLAN.value,
                "destination_anchor": destination,
                "destination_expression": f"确定{destination}",
                "classification_basis": "guided_option_selected",
            }
        )
        continue_run_with_intent(run_id, intent_value)
        action_state = start_action_loop(
            run_id,
            initial_evidence=_guided_evidence_for_selection(
                run_id,
                destination_id,
            ),
        )
        response = _run_response(run_id)
        response["action_loop"] = action_state
        return HTTPStatus.ACCEPTED, response
    if action == "retry-action":
        action_id = payload.get("action_id")
        if action_id not in {"railway", "map", "web", "planner"}:
            raise ProductRequestError("action is not retryable")
        previous = DEFAULT_AGENT_STORE.get_run(run_id)
        if previous.intent.task_mode is not TaskMode.DIRECT_PLAN:
            raise ProductRequestError(
                "only DIRECT_PLAN tool actions can be retried"
            )
        if previous.status in {
            RunStatus.COMPLETED,
            RunStatus.BLOCKED,
            RunStatus.FAILED,
        }:
            restart_action_loop_for_intent(run_id, previous.intent)
        action_state = execute_registered_action(run_id, action_id)
        response = _run_response(run_id)
        response["action_loop"] = action_state
        return HTTPStatus.OK, response
    if action == "evidence" and isinstance(payload.get("hotel_id"), str):
        hotel_id = payload.get("hotel_id")
        if not isinstance(hotel_id, str) or not hotel_id:
            raise ProductRequestError("hotel_id must be text")
        previous = DEFAULT_AGENT_STORE.get_run(run_id)
        evidence = _current_run_evidence(run_id)
        web = evidence.get("web")
        value = (
            deepcopy(dict(web.get("value")))
            if isinstance(web, Mapping)
            and isinstance(web.get("value"), Mapping)
            else None
        )
        if value is None:
            raise ProductRequestError("当前没有可选住宿候选。")
        hotels = value.get("hotel_candidates")
        selected = next(
            (
                item
                for item in hotels
                if isinstance(item, Mapping)
                and item.get("hotel_id") == hotel_id
            ),
            None,
        ) if isinstance(hotels, list) else None
        if not isinstance(selected, Mapping):
            raise ProductRequestError("住宿候选不属于当前run。")
        value["hotel_area"] = {
            "name": selected.get("name"),
            "route_query_name": selected.get("name"),
            "kind": "selected_hotel",
            "temporary_base": False,
            "specific_hotel_selected": True,
            "location": deepcopy(selected.get("location")),
            "longitude": (
                selected.get("location", {}).get("longitude")
                if isinstance(selected.get("location"), Mapping)
                else None
            ),
            "latitude": (
                selected.get("location", {}).get("latitude")
                if isinstance(selected.get("location"), Mapping)
                else None
            ),
            "coordinate_system": "GCJ-02",
            "price": deepcopy(selected.get("price")),
            "source": selected.get("source"),
        }
        attractions = value.get("attractions")
        value["route_sequence"] = [
            str(selected.get("name")),
            *[
                str(item.get("route_query_name") or item.get("name"))
                for item in (
                    attractions if isinstance(attractions, list) else []
                )[:3]
                if isinstance(item, Mapping)
                and isinstance(
                    item.get("route_query_name") or item.get("name"),
                    str,
                )
            ],
        ]
        restart_action_loop_for_intent(run_id, previous.intent)
        action_state = submit_evidence(
            run_id,
            {
                "action_id": "web",
                "evidence_id": str(web.get("evidence_id")),
                "domain": "web",
                "status": "sourced",
                "value": value,
                "sources": deepcopy(web.get("sources", [])),
            },
        )
        thread = threading.Thread(
            target=_run_action_loop_background,
            args=(run_id,),
            name=f"trip-decider-hotel-{run_id}",
            daemon=True,
        )
        thread.start()
        response = _run_response(run_id)
        response["action_loop"] = action_state
        return HTTPStatus.ACCEPTED, response
    if action == "evidence":
        evidence = payload.get("evidence")
        if not isinstance(evidence, Mapping):
            raise ProductRequestError("evidence must be an object")
        action_state = submit_evidence(run_id, evidence)
        response = _run_response(run_id)
        response["action_loop"] = action_state
        return HTTPStatus.OK, response
    if action == "revisions" and "intent" not in payload:
        revision = payload.get("revision")
        previous = DEFAULT_AGENT_STORE.get_run(run_id)
        text = payload.get("text")
        if isinstance(text, str):
            revision = _revision_from_user_text(text)
        if not isinstance(revision, Mapping):
            raise ProductRequestError(
                "请输入可识别的修改，或提供结构化 Revision。"
            )
        contract = Revision.from_mapping(revision)
        revised = revise_run(
            run_id,
            contract,
            executor=revise_destination_result,
        )
        return HTTPStatus.OK, _run_response(revised.run_id)
    if action == "revisions":
        intent = payload.get("intent")
        if not isinstance(intent, Mapping):
            raise ProductRequestError("intent must be an object")
        previous = DEFAULT_AGENT_STORE.get_run(run_id)
        corrected = TravelIntent.from_mapping(intent)
        changed_fields = {
            field_name
            for field_name, value in corrected.to_dict().items()
            if value != previous.intent.to_dict().get(field_name)
        }
        if not changed_fields or changed_fields <= {"pace"}:
            revision = Revision(
                pace=(
                    corrected.pace
                    if corrected.pace != previous.intent.pace
                    else None
                ),
                user_message=(
                    "用户再次确认旅行条件，条件未改变。"
                    if not changed_fields
                    else "用户修改旅行节奏。"
                ),
            )
            revised = revise_run(
                run_id,
                revision,
                executor=revise_destination_result,
                intent=corrected,
            )
            return HTTPStatus.OK, _run_response(revised.run_id)
        action_state = restart_action_loop_for_intent(
            run_id,
            corrected,
        )
        thread = threading.Thread(
            target=_run_action_loop_background,
            args=(run_id,),
            name=f"trip-decider-revision-{run_id}",
            daemon=True,
        )
        thread.start()
        response = _run_response(run_id)
        response["action_loop"] = action_state
        return HTTPStatus.ACCEPTED, response
    if action == "audit":
        audit_state = _execute_plan_audit(run_id, payload)
        response = _run_response(run_id)
        response["audit_execution"] = audit_state
        return HTTPStatus.OK, response
    raise ProductRequestError("unknown trip run action")


def _revision_from_user_text(text: str) -> dict[str, object]:
    normalized = text.strip()
    if not normalized:
        raise ProductRequestError("修改内容不能为空。")
    day_tokens = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
    }
    hour_tokens = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
        "十一": 11,
        "十二": 12,
    }
    match = re.search(
        r"第([一二三四五六七]|[1-9]\d*)天"
        r".*?([一二三四五六七八九十]{1,2}|\d{1,2})"
        r"[点:时](?:(\d{1,2})分?)?"
        r"(?:以后|之后|后)",
        normalized,
    )
    if match is None:
        raise ProductRequestError(
            "目前可直接识别“第二天九点以后出发”这类明确时间修改；"
            "其他修改请使用页面中的地点操作。"
        )
    raw_day = match.group(1)
    day = day_tokens.get(raw_day, int(raw_day) if raw_day.isdigit() else 0)
    raw_hour = match.group(2)
    hour = hour_tokens.get(
        raw_hour,
        int(raw_hour) if raw_hour.isdigit() else -1,
    )
    minute = int(match.group(3) or 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ProductRequestError("修改中的时间无效。")
    return {
        "day_start_times": {
            str(day): f"{hour:02d}:{minute:02d}",
        },
        "user_message": normalized,
    }


def _open_discovery_background(run_id: str) -> None:
    _candidate_comparison_background(
        run_id,
        expected_mode=TaskMode.OPEN_DISCOVERY,
    )


def _guided_discovery_background(run_id: str) -> None:
    _candidate_comparison_background(
        run_id,
        expected_mode=TaskMode.GUIDED_DISCOVERY,
    )


def _candidate_comparison_background(
    run_id: str,
    *,
    expected_mode: TaskMode,
) -> None:
    event_prefix = (
        "open" if expected_mode is TaskMode.OPEN_DISCOVERY else "guided"
    )

    def progress(
        status: str,
        destination: str,
        details: Mapping[str, object] | None,
    ) -> None:
        event_type = {
            "comparison_started": f"{event_prefix}.comparison.started",
            "candidate_started": f"{event_prefix}.candidate.started",
            "domain_started": f"{event_prefix}.domain.started",
            "domain_completed": f"{event_prefix}.domain.completed",
            "domain_timeout": f"{event_prefix}.domain.timeout",
            "candidate_completed": f"{event_prefix}.candidate.completed",
        }.get(status, f"{event_prefix}.progress")
        message = {
            "comparison_started": "开始并行比较倾向区域内的方案。",
            "candidate_started": "候选方案进入并行核验。",
            "domain_started": "开始核验一项真实数据。",
            "domain_completed": "一项真实数据核验完成。",
            "domain_timeout": "一项真实数据超时，继续其他核验。",
            "candidate_completed": "一个候选方案已可展示。",
        }.get(status, "区域方案比较有新进展。")
        DEFAULT_AGENT_STORE.append_event(
            run_id,
            event_type=event_type,
            status=(
                "completed"
                if status in {
                    "domain_completed",
                    "domain_timeout",
                    "candidate_completed",
                }
                else "started"
            ),
            message=message,
            details={
                "tool": (
                    str(details.get("domain"))
                    if isinstance(details, Mapping)
                    and details.get("domain") in {"railway", "map", "web"}
                    else "destination_context"
                ),
                "destination_label": destination,
                **dict(details or {}),
            },
        )

    try:
        run = DEFAULT_AGENT_STORE.get_run(run_id)
        if run.intent.task_mode is not expected_mode:
            raise TravelAgentError(
                f"{expected_mode.value} comparison received another mode"
            )
        with _GUIDED_CANCELLATIONS_LOCK:
            cancellation = _GUIDED_CANCELLATIONS.get(run_id)
        result = build_guided_comparison(
            run.intent,
            railway_collector=collect_railway_evidence,
            map_collector=collect_map_evidence,
            web_collector=collect_live_destination_profile,
            run_id=run_id,
            initial_evidence=None,
            progress=progress,
            should_cancel=(
                cancellation.is_set
                if cancellation is not None
                else None
            ),
        )
        reusable_evidence = result.pop("reusable_evidence", {})
        if not isinstance(reusable_evidence, Mapping):
            raise TravelAgentError(
                "guided comparison omitted reusable evidence"
            )
        _persist_guided_evidence(run_id, reusable_evidence)
        DEFAULT_AGENT_STORE.append_event(
            run_id,
            event_type=f"{event_prefix}.comparison.completed",
            status="completed",
            message="区域方案均已完成粗粒度可行性检查。",
            details={
                "tool": "validator",
                "option_count": result["option_count"],
            },
        )
        DEFAULT_AGENT_STORE.complete(run_id, result)
    except Exception as error:
        current = DEFAULT_AGENT_STORE.get_run(run_id)
        if current.status is RunStatus.RUNNING:
            DEFAULT_AGENT_STORE.block(
                run_id,
                {
                    "stage": (
                        "open_discovery"
                        if expected_mode is TaskMode.OPEN_DISCOVERY
                        else "guided_discovery"
                    ),
                    "task_mode": current.intent.task_mode.value,
                    "options": [],
                    "selection_required": True,
                    "blockers": [
                        {
                            "code": "GUIDED_COMPARISON_UNAVAILABLE",
                            "reason": type(error).__name__,
                        }
                    ],
                },
                "GUIDED_COMPARISON_UNAVAILABLE",
            )
    finally:
        with _GUIDED_CANCELLATIONS_LOCK:
            _GUIDED_CANCELLATIONS.pop(run_id, None)


def _run_action_loop_background(run_id: str) -> None:
    """Drive one local action loop and close any non-executable pause."""

    try:
        snapshot = run_until_blocked(
            run_id,
            max_wait_seconds=30.0,
        )
        if snapshot.get("status") != "NEED_USER_INPUT":
            return
        run = DEFAULT_AGENT_STORE.get_run(run_id)
        if run.status is not RunStatus.RUNNING:
            return
        actions = snapshot.get("actions")
        action_types = [
            str(action.get("action_type"))
            for action in actions
            if isinstance(action, Mapping)
        ] if isinstance(actions, list) else []
        reason = (
            "WEB_EVIDENCE_REQUIRED"
            if any(value.startswith("codex") for value in action_types)
            else "USER_INPUT_REQUIRED"
        )
        snapshot_result = snapshot.get("result")
        retained = (
            deepcopy(dict(snapshot_result))
            if isinstance(snapshot_result, Mapping)
            else run.result
            if isinstance(run.result, Mapping)
            else {
                "action_loop_status": "BLOCKED",
                "blocked_domains": [],
            }
        )
        DEFAULT_AGENT_STORE.block(
            run_id,
            retained,
            reason,
        )
    except Exception as error:
        current = DEFAULT_AGENT_STORE.get_run(run_id)
        if current.status is RunStatus.RUNNING:
            DEFAULT_AGENT_STORE.block(
                run_id,
                (
                    current.result
                    if isinstance(current.result, Mapping)
                    else {
                        "action_loop_status": "BLOCKED",
                        "blocked_domains": [],
                    }
                ),
                f"ACTION_LOOP_{type(error).__name__.upper()}",
            )


def _revise_agent_background(
    run_id: str,
    revision: Revision,
) -> None:
    try:
        revise_run(
            run_id,
            revision,
            executor=revise_destination_result,
        )
    except Exception:
        # The runtime has already persisted a stable failure event.
        return


def _sse_event(event: Mapping[str, object]) -> bytes:
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True)
    return (
        f"id: {event['sequence']}\n"
        "event: agent_event\n"
        f"data: {payload}\n\n"
    ).encode("utf-8")


class ProductHandler(BaseHTTPRequestHandler):
    server_version = "trip-decider-local/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the local log concise; request bodies and credentials are never
        # included.
        super().log_message(format, *args)

    def _send(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
    ) -> None:
        self.send_response(status.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(
        self,
        status: HTTPStatus,
        value: object,
    ) -> None:
        self._send(
            status,
            _json_bytes(value),
            "application/json; charset=utf-8",
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/trips":
            self._send_json(HTTPStatus.OK, _trip_list_response())
            return
        if path.startswith("/api/trips/"):
            parts = [unquote(part) for part in path.split("/") if part]
            if len(parts) >= 3 and parts[:2] == ["api", "trips"]:
                run_id = parts[2]
                try:
                    if len(parts) == 3:
                        result = _run_response(run_id)
                    elif len(parts) == 4 and parts[3] == "events":
                        self._send_trip_events(
                            path,
                            parse_qs(parsed.query),
                        )
                        return
                    elif len(parts) == 4 and parts[3] == "candidates":
                        result = _candidate_response(run_id)
                    elif (
                        len(parts) == 5
                        and parts[3:] == ["plans", "current"]
                    ):
                        result = _current_plan_response(run_id)
                    else:
                        self._send_json(
                            HTTPStatus.NOT_FOUND,
                            {"error": "not_found"},
                        )
                        return
                    self._send_json(HTTPStatus.OK, result)
                except (TravelAgentError, ProductRequestError) as error:
                    self._send_json(
                        HTTPStatus.NOT_FOUND,
                        {
                            "error": "trip_resource_not_found",
                            "message": str(error),
                        },
                    )
                return
        if path == "/api/client-config":
            self._send_json(HTTPStatus.OK, _client_configuration())
            return
        static = _STATIC_FILES.get(path)
        if static is None:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "not_found"},
            )
            return
        filename, content_type = static
        path = _WEB_ROOT / filename
        try:
            body = path.read_bytes()
        except OSError:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "static_asset_unavailable"},
            )
            return
        self._send(HTTPStatus.OK, body, content_type)

    def _send_trip_events(
        self,
        path: str,
        query: Mapping[str, list[str]],
    ) -> None:
        parts = [unquote(part) for part in path.split("/") if part]
        if (
            len(parts) != 4
            or parts[:2] != ["api", "trips"]
            or parts[3] != "events"
        ):
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "not_found"},
            )
            return
        run_id = parts[2]
        raw_after = query.get("after", ["0"])[0]
        header_after = self.headers.get("Last-Event-ID")
        try:
            after = int(header_after or raw_after)
            if after < 0:
                raise ValueError
            run = DEFAULT_AGENT_STORE.get_run(run_id)
            session_id = run.session_id
        except ValueError:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_event_cursor"},
            )
            return
        except TravelAgentError:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "agent_session_not_found"},
            )
            return
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        deadline = time.monotonic() + 30
        try:
            while time.monotonic() < deadline:
                events = DEFAULT_AGENT_STORE.wait_for_events(
                    session_id,
                    after,
                    timeout=3,
                )
                if not events:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                for event in events:
                    if event.run_id == run_id:
                        self.wfile.write(_sse_event(event.to_dict()))
                        after = event.sequence
                self.wfile.flush()
                session = DEFAULT_AGENT_STORE.get_session(session_id)
                current = DEFAULT_AGENT_STORE.get_run(
                    session.current_run_id
                )
                if current.status in {
                    RunStatus.COMPLETED,
                    RunStatus.BLOCKED,
                    RunStatus.FAILED,
                }:
                    return
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self) -> None:
        length_text = self.headers.get("Content-Length")
        try:
            length = int(length_text) if length_text is not None else -1
        except ValueError:
            length = -1
        if not 0 <= length <= _MAX_REQUEST_BYTES:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_content_length"},
            )
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "invalid_json"},
            )
            return
        if not isinstance(payload, dict):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "request_body_must_be_object"},
            )
            return
        try:
            if self.path == "/api/trips" or self.path.startswith(
                "/api/trips/"
            ):
                response_status, result = _trip_post(
                    self.path,
                    payload,
                )
            else:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": "not_found"},
                )
                return
        except ProductRequestError as error:
            self._send_json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {"error": type(error).__name__, "message": str(error)},
            )
            return
        except TravelAgentError as error:
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": "travel_agent_failed", "message": str(error)},
            )
            return
        except Exception:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal_error"},
            )
            return
        self._send_json(response_status, result)


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), ProductHandler)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local trip-decider Discover -> Plan product."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    server = make_server(arguments.host, arguments.port)
    host, port = server.server_address
    print(f"trip-decider local product: http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
