"""Local two-stage Discover -> Plan web product."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from collections.abc import Mapping
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from trip_decider.destination_discovery import (
    DiscoveryInputError,
    destination_detail,
    load_destination_catalog,
    rank_destination_candidates,
)
from trip_decider.destination_runtime import (
    execute_destination_intent,
    revise_destination_result,
)
from trip_decider.travel_agent import (
    DEFAULT_AGENT_STORE,
    Revision,
    RunStatus,
    TravelAgentError,
    confirm_intent,
    create_run,
    execute_run,
    progress_contract,
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


class ProductRequestError(ValueError):
    """Raised for malformed local product API input."""


def _product_discovery_request(
    payload: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    earliest_text = payload.get("earliest_departure_at")
    latest_text = payload.get("latest_return_at")
    if not isinstance(earliest_text, str) or not isinstance(latest_text, str):
        raise ProductRequestError(
            "earliest_departure_at and latest_return_at are required"
        )
    try:
        earliest = datetime.fromisoformat(earliest_text)
        latest = datetime.fromisoformat(latest_text)
    except ValueError:
        raise ProductRequestError(
            "travel window must use datetime-local values"
        ) from None
    if earliest.tzinfo is not None or latest.tzinfo is not None:
        raise ProductRequestError("travel window must be local wall time")
    if latest <= earliest:
        raise ProductRequestError(
            "latest_return_at must be after earliest_departure_at"
        )
    duration_hours = (latest - earliest).total_seconds() / 3600
    if not 12 <= duration_hours <= 30 * 24:
        raise ProductRequestError(
            "available travel window must be between 12 hours and 30 days"
        )
    request = dict(payload)
    request["approximate_start_date"] = earliest.date().isoformat()
    request["days"] = duration_hours / 24
    window = {
        "earliest_departure_at": earliest.isoformat(timespec="minutes"),
        "latest_return_at": latest.isoformat(timespec="minutes"),
        "available_duration_hours": duration_hours,
    }
    return request, window


def _with_product_request(
    result: dict[str, object],
    window: Mapping[str, object],
) -> dict[str, object]:
    request = result.get("request")
    if not isinstance(request, dict):
        raise RuntimeError("discovery result omitted normalized request")
    request.update(window)
    return result


def _progress_result(
    *,
    ai_interpretation: str,
    intercity_status: str,
) -> list[dict[str, str]]:
    states = {
        "understand": ai_interpretation,
        "intercity": intercity_status,
        "local_route": "not_started",
        "facts": "not_started",
        "plan": "not_started",
    }
    result = progress_contract()
    for step in result:
        step["status"] = states[step["id"]]
    return result


def _client_configuration() -> dict[str, object]:
    js_key = os.environ.get("AMAP_JS_API_KEY", "").strip()
    security_code = os.environ.get("AMAP_JS_SECURITY_CODE", "").strip()
    map_configured = bool(js_key and security_code)
    contract_status = runtime_status()
    return {
        "ai": {
            **contract_status,
            "configured": False,
            "display": "模型适配器未加载",
            "missing": [],
            "codex_mode": "pass_structured_travel_intent",
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


def _api_response(path: str, payload: dict[str, object]) -> dict[str, object]:
    if path == "/api/interpret-intent":
        return {
            "status": "MODEL_ADAPTER_NOT_LOADED",
            "display": (
                "核心不解析自然语言；请由Codex或可选模型适配器传入"
                "结构化TravelIntent。"
            ),
        }
    if path == "/api/discover":
        discovery_payload, window = _product_discovery_request(payload)
        result = rank_destination_candidates(discovery_payload)
        ai_state = (
            "completed"
            if payload.get("ai_interpretation_status") == "COMPLETED"
            else "not_requested"
        )
        _with_product_request(result, window)
        result["agent"] = runtime_status()
        result["progress"] = _progress_result(
            ai_interpretation=ai_state,
            intercity_status="not_started",
        )
        return result
    if path == "/api/select-destination":
        destination_id = payload.get("destination_id")
        request = payload.get("request")
        if not isinstance(destination_id, str) or not isinstance(request, dict):
            raise ProductRequestError(
                "destination_id and request are required"
            )
        detail = destination_detail(destination_id, request)
        for field in (
            "earliest_departure_at",
            "latest_return_at",
            "available_duration_hours",
        ):
            if field in request:
                detail["request"][field] = request[field]
        detail["agent"] = runtime_status()
        detail["progress"] = _progress_result(
            ai_interpretation="completed",
            intercity_status="completed",
        )
        return detail
    raise ProductRequestError("unknown API path")


def _run_response(run_id: str) -> dict[str, object]:
    run = DEFAULT_AGENT_STORE.get_run(run_id)
    session = DEFAULT_AGENT_STORE.get_session(run.session_id)
    return {
        "session": session.to_dict(),
        "run": run.to_dict(),
        "events": [
            event.to_dict()
            for event in DEFAULT_AGENT_STORE.events_after(
                run.session_id,
                0,
            )
            if event.run_id == run.run_id
        ],
    }


def _agent_post(
    path: str,
    payload: dict[str, object],
) -> tuple[HTTPStatus, dict[str, object]]:
    if path == "/api/agent/runs":
        intent = payload.get("intent")
        if not isinstance(intent, Mapping):
            raise ProductRequestError(
                "intent must be a structured TravelIntent object"
            )
        run = create_run(intent)
        return HTTPStatus.CREATED, _run_response(run.run_id)
    parts = [part for part in path.split("/") if part]
    if len(parts) != 5 or parts[:3] != ["api", "agent", "runs"]:
        raise ProductRequestError("unknown agent API path")
    run_id = parts[3]
    action = parts[4]
    if action == "confirm":
        intent = payload.get("intent")
        if intent is not None and not isinstance(intent, Mapping):
            raise ProductRequestError("intent must be an object")
        run = confirm_intent(run_id, intent)
        return HTTPStatus.OK, _run_response(run.run_id)
    if action == "execute":
        run = DEFAULT_AGENT_STORE.get_run(run_id)
        if run.status is not RunStatus.CONFIRMED:
            raise ProductRequestError(
                "run must be confirmed before execution"
            )
        thread = threading.Thread(
            target=_execute_agent_background,
            args=(run_id,),
            name=f"trip-decider-run-{run_id}",
            daemon=True,
        )
        thread.start()
        return HTTPStatus.ACCEPTED, _run_response(run_id)
    if action == "revise":
        revision = payload.get("revision")
        if not isinstance(revision, Mapping):
            raise ProductRequestError(
                "revision must be a structured Revision object"
            )
        contract = Revision.from_mapping(revision)
        previous = DEFAULT_AGENT_STORE.get_run(run_id)
        if previous.status is not RunStatus.COMPLETED:
            raise ProductRequestError(
                "only a completed run can be revised"
            )
        thread = threading.Thread(
            target=_revise_agent_background,
            args=(run_id, contract),
            name=f"trip-decider-revision-{run_id}",
            daemon=True,
        )
        thread.start()
        return HTTPStatus.ACCEPTED, _run_response(run_id)
    raise ProductRequestError("unknown agent run action")


def _execute_agent_background(run_id: str) -> None:
    try:
        execute_run(run_id, executor=execute_destination_intent)
    except Exception:
        # The runtime has already persisted a stable failure event.
        return


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
        if path.startswith("/api/agent/sessions/") and path.endswith(
            "/events"
        ):
            self._send_agent_events(path, parse_qs(parsed.query))
            return
        if path.startswith("/api/agent/runs/"):
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4 and parts[:3] == ["api", "agent", "runs"]:
                try:
                    self._send_json(
                        HTTPStatus.OK,
                        _run_response(parts[3]),
                    )
                except TravelAgentError as error:
                    self._send_json(
                        HTTPStatus.NOT_FOUND,
                        {
                            "error": "agent_run_not_found",
                            "message": str(error),
                        },
                    )
                return
        if path.startswith("/api/agent/sessions/"):
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4 and parts[:3] == [
                "api",
                "agent",
                "sessions",
            ]:
                try:
                    session = DEFAULT_AGENT_STORE.get_session(parts[3])
                    current = DEFAULT_AGENT_STORE.get_run(
                        session.current_run_id
                    )
                    self._send_json(
                        HTTPStatus.OK,
                        {
                            "session": session.to_dict(),
                            "current_run": current.to_dict(),
                        },
                    )
                except TravelAgentError as error:
                    self._send_json(
                        HTTPStatus.NOT_FOUND,
                        {
                            "error": "agent_session_not_found",
                            "message": str(error),
                        },
                    )
                return
        if path == "/api/catalog":
            self._send_json(HTTPStatus.OK, load_destination_catalog())
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

    def _send_agent_events(
        self,
        path: str,
        query: Mapping[str, list[str]],
    ) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) != 5 or parts[:3] != [
            "api",
            "agent",
            "sessions",
        ]:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "not_found"},
            )
            return
        session_id = parts[3]
        raw_after = query.get("after", ["0"])[0]
        header_after = self.headers.get("Last-Event-ID")
        try:
            after = int(header_after or raw_after)
            if after < 0:
                raise ValueError
            DEFAULT_AGENT_STORE.get_session(session_id)
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
                    self.wfile.write(_sse_event(event.to_dict()))
                    after = event.sequence
                self.wfile.flush()
                session = DEFAULT_AGENT_STORE.get_session(session_id)
                current = DEFAULT_AGENT_STORE.get_run(
                    session.current_run_id
                )
                if current.status in {
                    RunStatus.COMPLETED,
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
            if self.path.startswith("/api/agent/"):
                response_status, result = _agent_post(
                    self.path,
                    payload,
                )
            else:
                response_status = HTTPStatus.OK
                result = _api_response(self.path, payload)
        except (DiscoveryInputError, ProductRequestError) as error:
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
