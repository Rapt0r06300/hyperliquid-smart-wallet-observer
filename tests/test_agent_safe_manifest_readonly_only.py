"""The agent-safe manifest exposes ONLY read-only tools, zero custody."""

import pytest

from hyper_smart_observer.agent_tools.readonly_manifest import (
    FORBIDDEN_CAPABILITIES,
    READONLY_TOOL_NAMES,
    build_readonly_manifest,
    validate_readonly_manifest,
)


def test_manifest_is_read_only_and_validates():
    manifest = build_readonly_manifest()
    validate_readonly_manifest(manifest)  # must not raise
    assert manifest.tool_names() == READONLY_TOOL_NAMES
    assert manifest.mode == "read_only"
    assert manifest.custody == "zero_custody"
    assert manifest.simulation == "paper_mock_usdc_only"
    assert all(tool.mode == "read" for tool in manifest.tools)


def test_manifest_declares_forbidden_execution_capabilities():
    for cap in (
        "real_order", "signature", "private_credential", "wallet_connect",
        "live_toggle", "executor_service", "polymarket_clob", "mainnet_execution",
    ):
        assert cap in FORBIDDEN_CAPABILITIES


def test_schema_rejects_non_readonly_tool_action():
    from hyper_smart_observer.agent_tools.schemas import AgentToolSchema

    with pytest.raises(Exception):
        AgentToolSchema(name="order.place", description="place a real order")
