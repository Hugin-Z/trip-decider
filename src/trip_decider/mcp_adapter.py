"""Headless, protocol-neutral MCP-facing adapter.

This module intentionally knows only the application command boundary and the
query/read-model boundary.  It does not import HTTP, the run store, projection
helpers, planners, or provider tools.
"""

from __future__ import annotations

from collections.abc import Mapping
import time

from trip_decider.trip_application import (
    TripApplicationError,
    TripApplicationService,
)
from trip_decider.trip_query import TripQueryError, TripQueryService
from trip_decider.travel_agent import TravelAgentError


class TripMCPError(ValueError):
    """A stable host-facing trip tool error."""


class TripMCPAdapter:
    """User-goal operations over the one authoritative trip runtime."""

    _READ_VIEWS = {
        "overview",
        "candidates",
        "plan",
        "missing",
        "map",
        "audit",
    }
    _CHECKPOINT_STATUSES = {
        "AWAITING_CONFIRMATION",
        "COMPLETED",
        "BLOCKED",
        "FAILED",
    }

    def __init__(
        self,
        application: TripApplicationService,
        query: TripQueryService,
    ) -> None:
        if query.application_service is not application:
            raise ValueError(
                "MCP application and query boundaries must be the same bundle"
            )
        self._application = application
        self._query = query

    def create_trip_task(
        self,
        intent: Mapping[str, object],
    ) -> dict[str, object]:
        """Create a durable run and return its canonical read model."""

        return self._guard(
            lambda: self._query.trip(
                self._application.create_trip(intent).run_id
            )
        )

    def confirm_trip_intent(
        self,
        run_id: str,
        intent: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Confirm, or explicitly correct and confirm, one run's intent."""

        return self._guard(
            lambda: self._query.trip(
                self._application.confirm_trip(run_id, intent).run_id
            )
        )

    def advance_trip_task(
        self,
        run_id: str,
        *,
        wait_seconds: float = 10.0,
    ) -> dict[str, object]:
        """Advance until the next durable host/user checkpoint or timeout."""

        if (
            not isinstance(wait_seconds, (int, float))
            or isinstance(wait_seconds, bool)
            or not 0 <= float(wait_seconds) <= 30
        ):
            raise TripMCPError("wait_seconds must be between 0 and 30")

        def operation() -> dict[str, object]:
            before = self._query.trip(run_id)
            status = _run_status(before)
            if status not in self._CHECKPOINT_STATUSES:
                self._application.execute_trip(run_id)
            elif status == "COMPLETED":
                # A completed discovery run is already waiting for selection;
                # a completed plan/audit run is already a stable checkpoint.
                return self._checkpoint(run_id, before)
            elif status in {"BLOCKED", "FAILED"}:
                return self._checkpoint(run_id, before)
            else:
                return self._checkpoint(run_id, before)

            deadline = time.monotonic() + float(wait_seconds)
            current = self._query.trip(run_id)
            while (
                _run_status(current) not in self._CHECKPOINT_STATUSES
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
                current = self._query.trip(run_id)
            return self._checkpoint(run_id, current)

        return self._guard(operation)

    def read_trip(
        self,
        run_id: str,
        *,
        view: str = "overview",
    ) -> dict[str, object]:
        """Read one canonical query view without transport-specific projection."""

        if view not in self._READ_VIEWS:
            raise TripMCPError(
                "view must be overview, candidates, plan, missing, map, or audit"
            )
        readers = {
            "overview": self._query.trip,
            "candidates": self._query.candidates,
            "plan": self._query.current_plan,
            "missing": self._query.missing_information,
            "map": self._query.map_payload,
            "audit": self._query.audit_result,
        }
        return self._guard(lambda: readers[view](run_id))

    def render_trip_candidates(
        self,
        run_id: str,
    ) -> dict[str, object]:
        """Return the canonical candidate view in an MCP App envelope."""

        return self._guard(
            lambda: {
                "view": "candidates",
                "run_id": run_id,
                "current_version": None,
                "candidates": self._query.candidates(run_id),
            }
        )

    def render_trip_plan(
        self,
        run_id: str,
    ) -> dict[str, object]:
        """Return canonical trip and plan views in an MCP App envelope."""

        def operation() -> dict[str, object]:
            plan = self._query.current_plan(run_id)
            version = plan.get("plan_version")
            return {
                "view": "plan",
                "run_id": run_id,
                "current_version": version,
                "trip": self._query.trip(run_id),
                "plan": plan,
            }

        return self._guard(operation)

    def select_trip_candidate(
        self,
        run_id: str,
        candidate_id: str,
    ) -> dict[str, object]:
        """Select a compared destination while retaining the same run."""

        def operation() -> dict[str, object]:
            outcome = self._application.select_candidate(
                run_id,
                candidate_id,
            )
            return _with_outcome(self._query.trip(run_id), outcome)

        return self._guard(operation)

    def submit_trip_evidence(
        self,
        run_id: str,
        evidence: Mapping[str, object],
    ) -> dict[str, object]:
        """Submit explicit sourced/missing/conflicting evidence to one run."""

        def operation() -> dict[str, object]:
            outcome = self._application.submit_run_evidence(
                run_id,
                evidence,
            )
            return _with_outcome(self._query.trip(run_id), outcome)

        return self._guard(operation)

    def revise_trip_plan(
        self,
        run_id: str,
        revision: Mapping[str, object],
    ) -> dict[str, object]:
        """Atomically install a revised plan version on the same run."""

        def operation() -> dict[str, object]:
            outcome = self._application.revise_trip(
                run_id,
                revision=revision,
            )
            return {
                "trip": self._query.trip(outcome.run_id),
                "plan": self._query.current_plan(outcome.run_id),
            }

        return self._guard(operation)

    def audit_trip_plan(
        self,
        *,
        run_id: str | None = None,
        plan: Mapping[str, object] | None = None,
        content: str | None = None,
    ) -> dict[str, object]:
        """Audit an existing Plan or guide without invoking normal planning."""

        def operation() -> dict[str, object]:
            active_run_id = run_id
            if active_run_id is None:
                active_run_id = self._application.create_trip(
                    {"task_mode": "PLAN_AUDIT"}
                ).run_id
                self._application.confirm_trip(active_run_id)
            self._application.audit_trip(
                active_run_id,
                plan=plan,
                content=content,
            )
            return {
                "trip": self._query.trip(active_run_id),
                "audit": self._query.audit_result(active_run_id),
            }

        return self._guard(operation)

    def _checkpoint(
        self,
        run_id: str,
        trip: Mapping[str, object],
    ) -> dict[str, object]:
        status = _run_status(trip)
        response: dict[str, object] = {
            "trip": dict(trip),
            "checkpoint": _checkpoint_name(trip),
        }
        if status == "COMPLETED":
            try:
                response["plan"] = self._query.current_plan(run_id)
            except TripQueryError:
                try:
                    response["candidates"] = self._query.candidates(run_id)
                except TripQueryError:
                    pass
        if status in {"RUNNING", "BLOCKED", "FAILED"}:
            response["missing"] = self._query.missing_information(run_id)
        return response

    @staticmethod
    def _guard(operation: object) -> dict[str, object]:
        try:
            result = operation()
        except (TripApplicationError, TripQueryError, TravelAgentError) as error:
            raise TripMCPError(str(error)) from None
        if not isinstance(result, dict):
            raise TripMCPError("trip service returned a non-object result")
        return result


def _run_status(value: Mapping[str, object]) -> str:
    run = value.get("run")
    status = run.get("status") if isinstance(run, Mapping) else None
    return str(status) if status is not None else "UNKNOWN"


def _checkpoint_name(value: Mapping[str, object]) -> str:
    run = value.get("run")
    if not isinstance(run, Mapping):
        return "UNKNOWN"
    status = str(run.get("status", "UNKNOWN"))
    result = run.get("result")
    stage = result.get("stage") if isinstance(result, Mapping) else None
    if status == "AWAITING_CONFIRMATION":
        return "NEED_INTENT_CONFIRMATION"
    if status == "RUNNING":
        return "RUNNING"
    if status in {"BLOCKED", "FAILED"}:
        return "NEED_USER_INPUT_OR_EVIDENCE"
    if stage in {"open_discovery", "guided_discovery"}:
        return "CANDIDATES_READY"
    if stage == "plan_audit":
        return "AUDIT_READY"
    if status == "COMPLETED":
        return "PLAN_OR_PARTIAL_RESULT_READY"
    return status


def _with_outcome(
    trip: dict[str, object],
    outcome: object,
) -> dict[str, object]:
    action_loop = getattr(outcome, "action_loop", None)
    return {
        "trip": trip,
        "accepted": bool(getattr(outcome, "accepted", False)),
        "action_loop": dict(action_loop) if isinstance(action_loop, Mapping) else None,
    }


__all__ = ["TripMCPAdapter", "TripMCPError"]
