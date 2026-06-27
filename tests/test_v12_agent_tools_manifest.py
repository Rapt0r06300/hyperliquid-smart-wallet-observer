from hl_observer.agent_tools.manifest import (
    LOCAL_WRITE_TOOLS,
    READ_TOOLS,
    build_agent_tool_manifest,
    validate_agent_tool_manifest,
)


def test_v12_agent_tool_manifest_contains_read_and_local_write_tools():
    manifest = build_agent_tool_manifest()
    validate_agent_tool_manifest(manifest)

    names = set(manifest.tool_names())
    assert set(READ_TOOLS).issubset(names)
    assert set(LOCAL_WRITE_TOOLS).issubset(names)
    assert manifest.venue_default == "Hyperliquid"
    assert manifest.runtime_default == "LOCAL_PAPER_SIMULATION_ONLY"


def test_v12_agent_tools_never_expose_external_action():
    manifest = build_agent_tool_manifest()
    for tool in manifest.tools:
        assert tool.local_only is True
        assert tool.external_action is False
        assert tool.mode in {"read", "local_write"}
    assert "exchange_endpoint" in manifest.forbidden_external_actions
    assert "private_key" in manifest.forbidden_external_actions
