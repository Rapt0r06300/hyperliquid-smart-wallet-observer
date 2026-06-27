import json

from hl_observer.agent_tools.manifest import READ_TOOLS
from hl_observer.agent_tools.mcp_readonly import (
    READONLY_TOOL_IMPLS,
    build_readonly_mcp_manifest,
)


def test_manifest_is_read_only_and_agent_safe():
    m = build_readonly_mcp_manifest()
    assert m["read_only"] is True and m["venue_default"] == "Hyperliquid"
    assert set(m["implemented_read_tools"]).issubset(set(READ_TOOLS))
    # no write/external surface leaked into the read manifest
    blob = json.dumps(m).lower()
    for bad in ("real_order", "private_key", "wallet_connect", "signature_real"):
        assert bad not in " ".join(m["implemented_read_tools"]).lower()
    assert "real_order" in [a.lower() for a in m["forbidden_external_actions"]]
    json.dumps(m)


def test_impls_have_no_execution_surface():
    for name in READONLY_TOOL_IMPLS:
        assert all(b not in name.lower() for b in ("submit", "place", "order", "sign", "send"))
