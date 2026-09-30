from __future__ import annotations

from hyper_smart_observer.agent_tools.schemas import AgentToolSchema, ReadonlyManifest


READONLY_TOOL_NAMES = {
    "status.read",
    "wallet.leaderboard",
    "decision_ledger.search",
    "dashboard.export",
    "source_health.read",
}

FORBIDDEN_CAPABILITIES = [
    "real_order",
    "signature",
    "private_credential",
    "wallet_connect",
    "live_toggle",
    "executor_service",
    "polymarket_clob",
    "mainnet_execution",
]


def build_readonly_manifest() -> ReadonlyManifest:
    """Return the fixed read-only tool manifest for local agent use."""

    tools = [
        AgentToolSchema(
            name="status.read",
            description="Read local scanner and runtime status.",
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={"type": "object"},
            data_sources=["local_runtime", "source_health"],
        ),
        AgentToolSchema(
            name="wallet.leaderboard",
            description="Read the local wallet leaderboard and labels.",
            input_schema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                "additionalProperties": False,
            },
            output_schema={"type": "array"},
            data_sources=["sqlite_wallet_scores"],
        ),
        AgentToolSchema(
            name="decision_ledger.search",
            description="Search local decision ledger entries by reason, wallet or symbol.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "additionalProperties": False,
            },
            output_schema={"type": "array"},
            data_sources=["decision_ledger"],
        ),
        AgentToolSchema(
            name="dashboard.export",
            description="Export the local read-only dashboard snapshot.",
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={"type": "object"},
            data_sources=["dashboard_payload", "sqlite_snapshots"],
        ),
        AgentToolSchema(
            name="source_health.read",
            description="Read local source freshness and consistency state.",
            input_schema={"type": "object", "additionalProperties": False},
            output_schema={"type": "object"},
            data_sources=["source_health"],
        ),
    ]
    return ReadonlyManifest(tools=tools, forbidden_capabilities=FORBIDDEN_CAPABILITIES)


def validate_readonly_manifest(manifest: ReadonlyManifest | None = None) -> None:
    """Raise ValueError if a manifest exposes non-read-only capabilities."""

    manifest = manifest or build_readonly_manifest()
    tool_names = manifest.tool_names()
    if tool_names != READONLY_TOOL_NAMES:
        raise ValueError(f"Unexpected tool set: {sorted(tool_names)}")
    for tool in manifest.tools:
        if tool.mode != "read":
            raise ValueError(f"Tool is not read mode: {tool.name}")
        lowered = " ".join([tool.name, tool.description]).lower()
        for forbidden in ("buy", "sell", "order", "trade", "write", "sign", "wallet connect"):
            if forbidden in lowered:
                raise ValueError(f"Forbidden capability in tool description: {tool.name}")
    if manifest.mode != "read_only":
        raise ValueError("Manifest mode must be read_only")

