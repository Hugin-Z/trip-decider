"""Local Codex-facing tools for the trip-decider web process.

These functions send structured contracts to the local product server.  They
do not parse natural language, load a model, or inspect model credentials.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from trip_decider.travel_agent import Revision, TravelIntent


DEFAULT_PRODUCT_URL = "http://127.0.0.1:8765"


class CodexHostError(RuntimeError):
    """Raised when the local product server rejects a tool request."""


def create_trip_run(
    intent: TravelIntent | Mapping[str, object],
    *,
    base_url: str = DEFAULT_PRODUCT_URL,
) -> dict[str, object]:
    """Create an unconfirmed run from a structured ``TravelIntent``."""

    payload = intent.to_dict() if isinstance(intent, TravelIntent) else dict(intent)
    return _post_json(base_url, "/api/agent/runs", {"intent": payload})


def confirm_trip_run(
    run_id: str,
    *,
    base_url: str = DEFAULT_PRODUCT_URL,
) -> dict[str, object]:
    """Confirm a complete run; missing required fields remain blocking."""

    return _post_json(
        base_url,
        f"/api/agent/runs/{_run_id(run_id)}/confirm",
        {},
    )


def execute_trip_run(
    run_id: str,
    *,
    base_url: str = DEFAULT_PRODUCT_URL,
) -> dict[str, object]:
    """Start tool execution for a previously confirmed run."""

    return _post_json(
        base_url,
        f"/api/agent/runs/{_run_id(run_id)}/execute",
        {},
    )


def get_next_actions(
    run_id: str,
    *,
    base_url: str = DEFAULT_PRODUCT_URL,
) -> dict[str, object]:
    """Return structured actions until the run reaches a terminal state."""

    return _get_json(
        base_url,
        f"/api/agent/runs/{_run_id(run_id)}/actions",
    )


def execute_trip_action(
    run_id: str,
    action_id: str,
    *,
    base_url: str = DEFAULT_PRODUCT_URL,
) -> dict[str, object]:
    """Execute one action backed by the local tool registry."""

    if action_id not in {"railway", "map", "planner"}:
        raise CodexHostError("action_id is not a registered local tool")
    return _post_json(
        base_url,
        f"/api/agent/runs/{_run_id(run_id)}/run-action",
        {"action_id": action_id},
        timeout=120,
    )


def run_trip_until_blocked(
    run_id: str,
    *,
    base_url: str = DEFAULT_PRODUCT_URL,
) -> dict[str, object]:
    """Execute local railway/map/planner actions until external input is due."""

    return _post_json(
        base_url,
        f"/api/agent/runs/{_run_id(run_id)}/run-until-blocked",
        {},
        timeout=180,
    )


def submit_evidence(
    run_id: str,
    evidence: Mapping[str, object],
    *,
    base_url: str = DEFAULT_PRODUCT_URL,
) -> dict[str, object]:
    """Submit structured Codex evidence for the current action."""

    return _post_json(
        base_url,
        f"/api/agent/runs/{_run_id(run_id)}/evidence",
        {"evidence": dict(evidence)},
    )


def revise_trip_run(
    run_id: str,
    revision: Revision | Mapping[str, object],
    *,
    base_url: str = DEFAULT_PRODUCT_URL,
) -> dict[str, object]:
    """Submit a structured revision for a completed run."""

    payload = (
        revision.to_dict()
        if isinstance(revision, Revision)
        else dict(revision)
    )
    return _post_json(
        base_url,
        f"/api/agent/runs/{_run_id(run_id)}/revise",
        {"revision": payload},
    )


def _run_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CodexHostError("run_id is required")
    if any(character not in "0123456789abcdef-" for character in value.lower()):
        raise CodexHostError("run_id is invalid")
    return value


def _post_json(
    base_url: str,
    path: str,
    payload: Mapping[str, object],
    *,
    timeout: int = 15,
) -> dict[str, object]:
    request = Request(
        base_url.rstrip("/") + path,
        data=(json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
    except HTTPError as error:
        body = error.read()
        message = _safe_error_message(body)
        raise CodexHostError(
            f"local product rejected the request ({error.code}): {message}"
        ) from None
    except URLError:
        raise CodexHostError("local product is not reachable") from None
    try:
        value: Any = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise CodexHostError("local product returned invalid JSON") from None
    if not isinstance(value, dict):
        raise CodexHostError("local product returned a non-object response")
    return value


def _get_json(base_url: str, path: str) -> dict[str, object]:
    request = Request(
        base_url.rstrip("/") + path,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read()
    except HTTPError as error:
        body = error.read()
        message = _safe_error_message(body)
        raise CodexHostError(
            f"local product rejected the request ({error.code}): {message}"
        ) from None
    except URLError:
        raise CodexHostError("local product is not reachable") from None
    try:
        value: Any = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise CodexHostError("local product returned invalid JSON") from None
    if not isinstance(value, dict):
        raise CodexHostError("local product returned a non-object response")
    return value


def _safe_error_message(body: bytes) -> str:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return "request failed"
    if not isinstance(value, dict):
        return "request failed"
    message = value.get("message")
    return message if isinstance(message, str) and message else "request failed"


__all__ = [
    "CodexHostError",
    "confirm_trip_run",
    "create_trip_run",
    "execute_trip_action",
    "execute_trip_run",
    "get_next_actions",
    "revise_trip_run",
    "run_trip_until_blocked",
    "submit_evidence",
]
