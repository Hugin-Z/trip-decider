"""Versioned MCP App resource for trip-decider user read models.

The resource is presentation-only.  It receives canonical query results from
MCP render tools and calls the existing mutation tools for user actions.  It
does not own run, evidence, candidate, or plan state.
"""

from __future__ import annotations

from importlib.resources import files


TRIP_MCP_APP_URI = "ui://trip-decider/workspace/v1.html"
TRIP_MCP_APP_MIME_TYPE = "text/html;profile=mcp-app"


def load_trip_mcp_app_html() -> str:
    """Load the self-contained, versioned MCP App document."""

    return (
        files("trip_decider")
        .joinpath("mcp_app_workspace_v1.html")
        .read_text(encoding="utf-8")
    )


__all__ = [
    "TRIP_MCP_APP_MIME_TYPE",
    "TRIP_MCP_APP_URI",
    "load_trip_mcp_app_html",
]
