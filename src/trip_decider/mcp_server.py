"""STDIO MCP transport for the trip-decider application service.

The server is a thin transport adapter.  Tool implementations delegate to
``TripMCPAdapter``, which in turn calls only ``TripApplicationService`` and
``TripQueryService``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import threading
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from trip_decider.mcp_adapter import TripMCPAdapter
from trip_decider.mcp_app import (
    TRIP_MCP_APP_MIME_TYPE,
    TRIP_MCP_APP_URI,
    load_trip_mcp_app_html,
)
from trip_decider.trip_services import (
    default_trip_services,
    TripServices,
    build_trip_services,
)


_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
_MUTATING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
_ADVANCING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)

_APP_CALLABLE_META = {
    "ui": {"visibility": ["model", "app"]},
    "openai/widgetAccessible": True,
}
_APP_RENDER_META = {
    "ui": {
        "resourceUri": TRIP_MCP_APP_URI,
        "visibility": ["model", "app"],
    },
    "openai/outputTemplate": TRIP_MCP_APP_URI,
    "openai/widgetAccessible": True,
}


def build_mcp_server(adapter: TripMCPAdapter) -> MCPServer:
    """Create the headless tool server around an injected application bundle."""

    server = MCPServer(
        name="trip-decider",
        title="Trip Decider",
        description=(
            "Create, resume, inspect, revise, and audit durable travel "
            "decision tasks."
        ),
        instructions=(
            "Create a trip, confirm the structured intent, then advance it. "
            "Keep using the returned run_id for candidate selection, evidence, "
            "and revisions. Never invent factual evidence: sourced evidence "
            "must include its source. Read canonical user views with read_trip. "
            "When the client renders MCP Apps, use show_trip_candidates after "
            "comparison and show_trip_plan after a PlanVersion is installed. "
            "Clients without Apps can complete the same workflow with the "
            "structured headless tools."
        ),
        version="0.1.0",
    )

    @server.resource(
        TRIP_MCP_APP_URI,
        name="trip-decider-workspace",
        title="Trip Decider 交互工作台",
        description=(
            "Render destination comparison and installed trip plan read "
            "models without owning business state."
        ),
        mime_type=TRIP_MCP_APP_MIME_TYPE,
        meta={"ui": {"prefersBorder": True}},
    )
    def trip_decider_workspace() -> str:
        return load_trip_mcp_app_html()

    @server.tool(
        name="create_trip_task",
        title="创建旅行任务",
        description="Create one new durable trip run from structured intent.",
        annotations=_MUTATING,
        structured_output=True,
    )
    def create_trip_task(intent: dict[str, Any]) -> dict[str, Any]:
        return adapter.create_trip_task(intent)

    @server.tool(
        name="confirm_trip_intent",
        title="确认旅行需求",
        description=(
            "Confirm the current structured intent, optionally replacing it "
            "with an explicitly corrected intent."
        ),
        annotations=_MUTATING,
        structured_output=True,
    )
    def confirm_trip_intent(
        run_id: str,
        intent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return adapter.confirm_trip_intent(run_id, intent)

    @server.tool(
        name="advance_trip_task",
        title="推进旅行任务",
        description=(
            "Advance a confirmed/running task to candidates, a plan/partial "
            "result, or a user/evidence checkpoint."
        ),
        annotations=_ADVANCING,
        meta=_APP_CALLABLE_META,
        structured_output=True,
    )
    def advance_trip_task(
        run_id: str,
        wait_seconds: float = 10.0,
    ) -> dict[str, Any]:
        return adapter.advance_trip_task(
            run_id,
            wait_seconds=wait_seconds,
        )

    @server.tool(
        name="read_trip",
        title="读取旅行任务",
        description=(
            "Read one canonical query view: overview, candidates, plan, "
            "missing, map, or audit."
        ),
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def read_trip(
        run_id: str,
        view: str = "overview",
    ) -> dict[str, Any]:
        return adapter.read_trip(run_id, view=view)

    @server.tool(
        name="show_trip_candidates",
        title="展示目的地比较",
        description=(
            "Render the canonical candidate comparison for an existing run. "
            "Call after candidates are ready. The structured result remains "
            "complete for clients that do not render MCP Apps."
        ),
        annotations=_READ_ONLY,
        meta={
            **_APP_RENDER_META,
            "openai/toolInvocation/invoking": "正在展示目的地方案…",
            "openai/toolInvocation/invoked": "目的地方案已展示",
        },
        structured_output=True,
    )
    def show_trip_candidates(run_id: str) -> dict[str, Any]:
        return adapter.render_trip_candidates(run_id)

    @server.tool(
        name="show_trip_plan",
        title="展示当前行程",
        description=(
            "Render the currently installed PlanVersion, timeline, budget, "
            "missing items, route summary, and revision controls for one run. "
            "The structured result remains complete without MCP Apps UI."
        ),
        annotations=_READ_ONLY,
        meta={
            **_APP_RENDER_META,
            "openai/toolInvocation/invoking": "正在展示行程…",
            "openai/toolInvocation/invoked": "行程已展示",
        },
        structured_output=True,
    )
    def show_trip_plan(run_id: str) -> dict[str, Any]:
        return adapter.render_trip_plan(run_id)

    @server.tool(
        name="select_trip_candidate",
        title="选择目的地候选",
        description=(
            "Select one compared destination and continue on the same run."
        ),
        annotations=_MUTATING,
        meta=_APP_CALLABLE_META,
        structured_output=True,
    )
    def select_trip_candidate(
        run_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        return adapter.select_trip_candidate(run_id, candidate_id)

    @server.tool(
        name="submit_trip_evidence",
        title="提交旅行证据",
        description=(
            "Submit explicit sourced, missing, or conflicting evidence to a "
            "waiting action on the same run."
        ),
        annotations=_MUTATING,
        meta=_APP_CALLABLE_META,
        structured_output=True,
    )
    def submit_trip_evidence(
        run_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        return adapter.submit_trip_evidence(run_id, evidence)

    @server.tool(
        name="revise_trip_plan",
        title="修改当前行程",
        description=(
            "Apply a structured revision and atomically install the next plan "
            "version on the same run."
        ),
        annotations=_MUTATING,
        meta=_APP_CALLABLE_META,
        structured_output=True,
    )
    def revise_trip_plan(
        run_id: str,
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        return adapter.revise_trip_plan(run_id, revision)

    @server.tool(
        name="audit_trip_plan",
        title="审计已有攻略或计划",
        description=(
            "Audit exactly one existing Plan object or guide text without "
            "invoking the normal itinerary planner."
        ),
        annotations=_MUTATING,
        structured_output=True,
    )
    def audit_trip_plan(
        run_id: str | None = None,
        plan: dict[str, Any] | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        return adapter.audit_trip_plan(
            run_id=run_id,
            plan=plan,
            content=content,
        )

    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the trip-decider headless MCP server over STDIO."
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        help=(
            "Explicit sessions directory. Omit to use the same default "
            "runtime as Standalone Web."
        ),
    )
    parser.add_argument(
        "--with-web",
        action="store_true",
        help="Also serve Standalone Web from the exact same in-process runtime.",
    )
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=8765)
    return parser


def _services_for(arguments: argparse.Namespace) -> TripServices:
    if arguments.runtime_root is None:
        return default_trip_services()
    return build_trip_services(arguments.runtime_root)


def main() -> int:
    arguments = _parser().parse_args()
    services = _services_for(arguments)
    web_server = None
    web_thread = None
    if arguments.with_web:
        from trip_decider import product_web

        product_web.configure_services(
            services.application,
            services.query,
        )
        web_server = product_web.make_server(
            arguments.web_host,
            arguments.web_port,
        )
        web_thread = threading.Thread(
            target=web_server.serve_forever,
            name="trip-decider-shared-web",
            daemon=True,
        )
        web_thread.start()
        host, port = web_server.server_address
        print(
            f"trip-decider shared web: http://{host}:{port}/",
            file=sys.stderr,
            flush=True,
        )
    server = build_mcp_server(
        TripMCPAdapter(services.application, services.query)
    )
    try:
        server.run("stdio")
    finally:
        if web_server is not None:
            web_server.shutdown()
            web_server.server_close()
        if web_thread is not None:
            web_thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_mcp_server", "main"]
