"""Agent tool manifest for V12 local collaboration.

This is not an MCP server implementation. It is the auditable contract that says
which tool-shaped operations are allowed for local agents. Read tools do not
mutate; local_write tools may write only local files/SQLite state and must never
touch a venue, wallet, key, signature or real-money endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field


READ_TOOLS = (
    "status.read",
    "source_health.read",
    "wallet.leaderboard",
    "wallet.detail",
    "market.features.read",
    "decision_ledger.search",
    "evidence_chain.read",
    "paper_portfolio.read",
    "paper_trade.search",
    "backtest.report.read",
    "dashboard.export",
)

LOCAL_WRITE_TOOLS = (
    "research.rescan_sources",
    "simulation.start_local",
    "simulation.stop_local",
    "paper_position.close_local",
    "backtest.run",
    "archive.create_clean",
)

FORBIDDEN_EXTERNAL_ACTIONS = (
    "real_order",
    "external_order",
    "venue_mutation",
    "private_key",
    "wallet_connect",
    "signature_real",
    "exchange_endpoint",
    "real_deposit",
    "real_withdrawal",
)


@dataclass(frozen=True, slots=True)
class AgentToolContract:
    name: str
    mode: str
    description: str
    local_only: bool = True
    external_action: bool = False
    simulation_only: bool = True
    data_sources: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class AgentToolManifest:
    name: str
    version: str
    venue_default: str
    runtime_default: str
    tools: tuple[AgentToolContract, ...]
    forbidden_external_actions: tuple[str, ...]

    def tool_names(self) -> tuple[str, ...]:
        return tuple(t.name for t in self.tools)


def build_agent_tool_manifest() -> AgentToolManifest:
    tools: list[AgentToolContract] = []
    for name in READ_TOOLS:
        tools.append(
            AgentToolContract(
                name=name,
                mode="read",
                description=f"Read local {name} data.",
                data_sources=("local_sqlite", "local_exports", "runtime_state"),
            )
        )
    for name in LOCAL_WRITE_TOOLS:
        tools.append(
            AgentToolContract(
                name=name,
                mode="local_write",
                description=f"Run local-only {name} action.",
                data_sources=("local_files", "local_sqlite"),
            )
        )
    return AgentToolManifest(
        name="hypersmart-v12-local-agent-tools",
        version="1.0",
        venue_default="Hyperliquid",
        runtime_default="LOCAL_PAPER_SIMULATION_ONLY",
        tools=tuple(tools),
        forbidden_external_actions=FORBIDDEN_EXTERNAL_ACTIONS,
    )


def validate_agent_tool_manifest(manifest: AgentToolManifest | None = None) -> None:
    manifest = manifest or build_agent_tool_manifest()
    expected = set(READ_TOOLS) | set(LOCAL_WRITE_TOOLS)
    actual = set(manifest.tool_names())
    if actual != expected:
        raise ValueError(f"unexpected tool names: missing={expected - actual} extra={actual - expected}")
    if manifest.venue_default != "Hyperliquid":
        raise ValueError("Hyperliquid must remain the default runtime venue")
    for tool in manifest.tools:
        if tool.mode not in {"read", "local_write"}:
            raise ValueError(f"unsupported tool mode: {tool.name} -> {tool.mode}")
        if not tool.local_only:
            raise ValueError(f"tool is not local-only: {tool.name}")
        if tool.external_action:
            raise ValueError(f"tool exposes external action: {tool.name}")
        lowered = f"{tool.name} {tool.description}".lower()
        for forbidden in ("private_key", "wallet_connect", "/" + "exchange", "mainnet"):
            if forbidden in lowered:
                raise ValueError(f"forbidden external capability in tool contract: {tool.name}")


__all__ = [
    "AgentToolContract",
    "AgentToolManifest",
    "FORBIDDEN_EXTERNAL_ACTIONS",
    "LOCAL_WRITE_TOOLS",
    "READ_TOOLS",
    "build_agent_tool_manifest",
    "validate_agent_tool_manifest",
]
