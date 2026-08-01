"""Local two-stage Discover -> Plan web product."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections.abc import Mapping
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from trip_decider.agent_actions import (
    get_next_actions,  # compatibility export for existing local callers
    start_action_loop,
)
from trip_decider.trip_application import (
    DEFAULT_TRIP_APPLICATION_SERVICE,
    TripApplicationError,
    TripApplicationService,
)
from trip_decider.trip_query import (
    DEFAULT_TRIP_QUERY_SERVICE,
    TripQueryError,
    TripQueryService,
)
from trip_decider.trip_read_model import (
    _budget_summary,
    _compact_progress_contract,
    _elapsed_seconds,
    _guided_domain_label,
    _guided_progress_contract,
    _intent_day_skeleton,
    _map_payload_contract,
    _map_polyline,
    _map_position,
    _planning_draft_read_model,
    _planning_handoff_contract,
    _presentation_contract,
)
from trip_decider.travel_agent import (
    AgentRuntimeMode,
    DEFAULT_AGENT_STORE,
    TaskMode,
    TravelIntent,
    TravelAgentError,
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


class ProductRequestError(ValueError):
    """Raised for malformed local product API input."""


def _application_service() -> TripApplicationService:
    """Return the one application service over the active authoritative store."""

    if DEFAULT_TRIP_APPLICATION_SERVICE.store is DEFAULT_AGENT_STORE:
        return DEFAULT_TRIP_APPLICATION_SERVICE
    return TripApplicationService(store=DEFAULT_AGENT_STORE)


def _query_service() -> TripQueryService:
    """Return the query facade over the same authoritative runtime."""

    application = _application_service()
    if (
        DEFAULT_TRIP_QUERY_SERVICE.store is DEFAULT_AGENT_STORE
        and DEFAULT_TRIP_QUERY_SERVICE.application_service is application
    ):
        return DEFAULT_TRIP_QUERY_SERVICE
    return TripQueryService(
        store=DEFAULT_AGENT_STORE,
        application_service=application,
    )


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


def _persist_guided_evidence(
    run_id: str,
    evidence_by_destination: Mapping[str, object],
) -> None:
    try:
        _application_service().persist_guided_evidence(
            run_id,
            evidence_by_destination,
        )
    except TripApplicationError as error:
        raise ProductRequestError(str(error)) from error


def _run_response(run_id: str) -> dict[str, object]:
    return _query_service().trip(run_id)


def _trip_list_response() -> dict[str, object]:
    return _query_service().trips()


def _candidate_response(run_id: str) -> dict[str, object]:
    try:
        return _query_service().candidates(run_id)
    except TripQueryError as error:
        raise ProductRequestError(str(error)) from error


def _current_plan_response(run_id: str) -> dict[str, object]:
    try:
        return _query_service().current_plan(run_id)
    except TripQueryError as error:
        raise ProductRequestError(str(error)) from error


def _current_plan_version(run_id: str) -> int | None:
    return _query_service().current_plan_version(run_id)


def _current_plan_payload(run_id: str) -> dict[str, object] | None:
    try:
        return _query_service().current_plan(run_id)
    except TripQueryError:
        return None




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
    try:
        outcome = (
            _application_service().execute_open_discovery(run_id)
            if mode is TaskMode.OPEN_DISCOVERY
            else _application_service().execute_guided_discovery(run_id)
        )
    except TripApplicationError as error:
        raise ProductRequestError(str(error)) from error
    return dict(outcome.action_loop or {})


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
    try:
        outcome = _application_service().execute_direct_plan(run_id)
    except TripApplicationError as error:
        raise ProductRequestError(str(error)) from error
    return dict(outcome.action_loop or {})


def _execute_plan_audit(
    run_id: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    raw_plan = payload.get("plan")
    raw_content = payload.get("content")
    try:
        outcome = _application_service().audit_trip(
            run_id,
            plan=(raw_plan if isinstance(raw_plan, Mapping) else None),
            content=(raw_content if isinstance(raw_content, str) else None),
        )
    except TripApplicationError as error:
        raise ProductRequestError(str(error)) from error
    return dict(outcome.audit_execution or {})


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
        run = _application_service().create_trip(intent)
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
        run = _application_service().confirm_trip(run_id, intent)
        return HTTPStatus.OK, _run_response(run.run_id)
    if action == "execute":
        action_id = payload.get("action_id")
        try:
            outcome = _application_service().execute_trip(
                run_id,
                action_id=(action_id if isinstance(action_id, str) else None),
            )
        except TripApplicationError as error:
            raise ProductRequestError(str(error)) from error
        response = _run_response(run_id)
        if outcome.action_loop is not None:
            response["action_loop"] = dict(outcome.action_loop)
        return (
            HTTPStatus.ACCEPTED if outcome.accepted else HTTPStatus.OK,
            response,
        )
    if action == "select-candidate":
        destination_id = payload.get("destination_id")
        if not isinstance(destination_id, str) or not destination_id:
            raise ProductRequestError("destination_id must be text")
        try:
            outcome = _application_service().select_candidate(
                run_id,
                destination_id,
            )
        except TripApplicationError as error:
            raise ProductRequestError(str(error)) from error
        response = _run_response(run_id)
        response["action_loop"] = dict(outcome.action_loop or {})
        return HTTPStatus.ACCEPTED, response
    if action == "retry-action":
        action_id = payload.get("action_id")
        if not isinstance(action_id, str):
            raise ProductRequestError("action is not retryable")
        try:
            outcome = _application_service().retry_action(
                run_id,
                action_id,
            )
        except TripApplicationError as error:
            raise ProductRequestError(str(error)) from error
        response = _run_response(run_id)
        response["action_loop"] = dict(outcome.action_loop or {})
        return HTTPStatus.OK, response
    if action == "evidence" and isinstance(payload.get("hotel_id"), str):
        hotel_id = payload.get("hotel_id")
        if not isinstance(hotel_id, str) or not hotel_id:
            raise ProductRequestError("hotel_id must be text")
        try:
            outcome = _application_service().select_hotel(run_id, hotel_id)
        except TripApplicationError as error:
            raise ProductRequestError(str(error)) from error
        response = _run_response(run_id)
        response["action_loop"] = dict(outcome.action_loop or {})
        return HTTPStatus.ACCEPTED, response
    if action == "evidence":
        evidence = payload.get("evidence")
        if not isinstance(evidence, Mapping):
            raise ProductRequestError("evidence must be an object")
        try:
            outcome = _application_service().submit_run_evidence(
                run_id,
                evidence,
            )
        except TripApplicationError as error:
            raise ProductRequestError(str(error)) from error
        response = _run_response(run_id)
        response["action_loop"] = dict(outcome.action_loop or {})
        return HTTPStatus.OK, response
    if action == "revisions" and "intent" not in payload:
        revision = payload.get("revision")
        text = payload.get("text")
        if isinstance(text, str):
            revision = _revision_from_user_text(text)
        if not isinstance(revision, Mapping):
            raise ProductRequestError(
                "请输入可识别的修改，或提供结构化 Revision。"
            )
        try:
            outcome = _application_service().revise_trip(
                run_id,
                revision=revision,
            )
        except TripApplicationError as error:
            raise ProductRequestError(str(error)) from error
        return HTTPStatus.OK, _run_response(outcome.run_id)
    if action == "revisions":
        intent = payload.get("intent")
        if not isinstance(intent, Mapping):
            raise ProductRequestError("intent must be an object")
        try:
            outcome = _application_service().revise_trip(
                run_id,
                intent=intent,
            )
        except TripApplicationError as error:
            raise ProductRequestError(str(error)) from error
        if not outcome.accepted:
            return HTTPStatus.OK, _run_response(outcome.run_id)
        response = _run_response(run_id)
        response["action_loop"] = dict(outcome.action_loop or {})
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
            query_service = _query_service()
            query_service.events(run_id, after_sequence=after)
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
                batch = query_service.wait_for_events(
                    run_id,
                    after_sequence=after,
                    timeout=3,
                )
                events = batch["events"]
                if not events:
                    if batch["terminal"]:
                        return
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                for event in events:
                    self.wfile.write(_sse_event(event))
                    sequence = event.get("sequence")
                    if isinstance(sequence, int):
                        after = sequence
                self.wfile.flush()
                if batch["terminal"]:
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
