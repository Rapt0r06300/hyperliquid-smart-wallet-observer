"""Read-only MCP exposure (V12 capability T) — agent-safe manifest + dispatch.

Builds the agent-safe read-only manifest (from agent_tools.manifest) and maps the
declared read tools to the pure inspector implementations. FastMCP is OPTIONAL: if
installed, this manifest can back a FastMCP server; otherwise it is a pure, auditable
description. No write tool, no external action, no order — read-only by construction.
"""

from __future__ import annotations

import importlib.util

from hl_observer.agent_tools.manifest import (
    READ_TOOLS,
    build_agent_tool_manifest,
    validate_agent_tool_manifest,
)
from hl_observer.agent_tools.readonly_inspectors import (
    dashboard_export,
    source_health_read,
)

# Manifest read-tool name -> pure inspector callable (read-only).
READONLY_TOOL_IMPLS = {
    "source_health.read": source_health_read,
    "dashboard.export": dashboard_export,
}


def fastmcp_available() -> bool:
    return (
        importlib.util.find_spec("fastmcp") is not None
        or importlib.util.find_spec("mcp") is not None
    )


def build_readonly_mcp_manifest() -> dict:
    validate_agent_tool_manifest()  # raises if any tool is not local/read-only
    m = build_agent_tool_manifest()
    return {
        "server": m.name,
        "version": m.version,
        "venue_default": m.venue_default,
        "runtime_default": m.runtime_default,
        "read_tools": list(READ_TOOLS),
        "implemented_read_tools": sorted(READONLY_TOOL_IMPLS),
        "forbidden_external_actions": list(m.forbidden_external_actions),
        "transport": "fastmcp" if fastmcp_available() else "manifest_only",
        "read_only": True,
    }


__all__ = ["READONLY_TOOL_IMPLS", "fastmcp_available", "build_readonly_mcp_manifest"]
