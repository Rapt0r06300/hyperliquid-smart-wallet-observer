from __future__ import annotations

from pathlib import Path

from hyper_smart_observer.agent_tools.readonly_manifest import (
    READONLY_TOOL_NAMES,
    build_readonly_manifest,
    validate_readonly_manifest,
)


FUSION_DOCS = [
    Path("docs/research/HYPERSMART_GITHUB_FUSION_MASTER.md"),
    Path("docs/research/HYPERSMART_REPO_IDEA_MATRIX_FUSION.md"),
    Path("docs/HYPERSMART_HYPERLIQUID_SCAN_STRATEGY_FUSION.md"),
    Path("docs/HYPERSMART_COMMON_DATA_MODEL_FUSION.md"),
    Path("docs/HYPERSMART_MARKET_SIGNAL_FEATURES_FUSION.md"),
    Path("docs/HYPERSMART_WALLET_INTELLIGENCE_FUSION.md"),
    Path("docs/HYPERSMART_RISK_ENGINE_FUSION.md"),
    Path("docs/HYPERSMART_DASHBOARD_FUSION.md"),
    Path("docs/HYPERSMART_BACKTEST_RUNTIME_PARITY_FUSION.md"),
    Path("docs/HYPERSMART_AGENT_SAFE_READONLY_TOOLS_FUSION.md"),
    Path("docs/HYPERSMART_NO_FAKE_DATA_NO_HYPE_NO_EXECUTION_POLICY.md"),
    Path("docs/HYPERSMART_LICENSE_SAFETY_POLICY.md"),
]

REPO_MARKERS = [
    "CloddsBot",
    "Harrier",
    "MrFadiAi",
    "polymarket_lp_tool",
    "PolyWeather",
    "Composio",
    "Awesome Prediction Market Tools",
    "PolyTerm",
    "mlmodelpoly",
    "polyrec",
    "prediction-market-backtesting",
    "polybot",
    "Polymarket agents",
    "Lightweight Charts",
]


def test_github_fusion_docs_exist_and_have_required_sections():
    required_sections = [
        "## Objectif",
        "## Source GitHub inspiratrice",
        "## Adaptation Hyperliquid",
        "## Modules cibles",
        "## Donnees Hyperliquid utilisees",
        "## Tests requis",
        "## Statut DONE / PARTIAL / TODO / DEFER / BAN",
    ]

    for path in FUSION_DOCS:
        assert path.exists(), f"missing fusion doc: {path}"
        text = path.read_text(encoding="utf-8")
        for section in required_sections:
            assert section in text, f"{path} missing {section}"


def test_repo_idea_matrix_has_keep_adapt_ban_defer():
    text = Path("docs/research/HYPERSMART_REPO_IDEA_MATRIX_FUSION.md").read_text(
        encoding="utf-8"
    )

    for marker in REPO_MARKERS:
        assert marker in text
    for decision in ["KEEP", "ADAPT_TO_HYPERLIQUID", "BAN", "DEFER"]:
        assert decision in text
    assert "openOrders" in text
    assert "PaperIntent" in text


def test_no_external_code_copy_license_markers():
    text = Path("docs/HYPERSMART_LICENSE_SAFETY_POLICY.md").read_text(encoding="utf-8")

    assert "sources d'idees only" in text
    assert "No external code copy" in text
    assert "no external code was copied" in text
    assert "license review" in text


def test_start_script_preserves_calibrated_freshness_guard():
    ps1 = Path("tools/start_hypersmart_simulation.ps1").read_text(encoding="utf-8")
    cmd = Path("LANCER_HYPERSMART.cmd").read_text(encoding="utf-8")

    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS" "15000"' in ps1
    assert "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=15000" in cmd
    assert "DYDX_MAX_SIGNAL_AGE_MS" not in cmd
    assert "DYDX_" not in cmd


def test_start_script_min_edge_bps_guard():
    ps1 = Path("tools/start_hypersmart_simulation.ps1").read_text(encoding="utf-8")
    cmd = Path("LANCER_HYPERSMART.cmd").read_text(encoding="utf-8")

    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SIMULATION_MIN_EDGE_BPS" "15"' in ps1
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS" "28"' in ps1
    assert "HYPERSMART_SIMULATION_MIN_EDGE_BPS=15" in cmd


def test_agent_safe_manifest_readonly_only():
    manifest = build_readonly_manifest()
    validate_readonly_manifest(manifest)

    assert manifest.mode == "read_only"
    assert manifest.custody == "zero_custody"
    assert manifest.simulation == "paper_mock_usdc_only"
    assert manifest.tool_names() == READONLY_TOOL_NAMES
    assert all(tool.mode == "read" for tool in manifest.tools)
    assert all(
        tool.name
        in {
            "status.read",
            "wallet.leaderboard",
            "decision_ledger.search",
            "dashboard.export",
            "source_health.read",
        }
        for tool in manifest.tools
    )


def test_agent_safe_manifest_has_no_trade_or_write_tools():
    manifest = build_readonly_manifest()
    tool_text = "\n".join(f"{tool.name} {tool.description}" for tool in manifest.tools).lower()

    for forbidden in ["buy", "sell", "order", "trade", "write", "sign", "wallet connect"]:
        assert forbidden not in tool_text


def test_no_profit_promise_policy_is_explicitly_banned():
    policy = Path("docs/HYPERSMART_NO_FAKE_DATA_NO_HYPE_NO_EXECUTION_POLICY.md").read_text(
        encoding="utf-8"
    )

    assert "Forbidden language and features" in policy
    assert "profit guaranteed" in policy
    assert "risk-free profit" in policy
    assert "empty states" in policy


def test_no_polymarket_clob_or_execution_dependency_added_to_agent_tools():
    agent_sources = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in Path("hyper_smart_observer/agent_tools").rglob("*.py")
    ).lower()

    assert "@polymarket/clob-client" not in agent_sources
    assert "tradingenabled" not in agent_sources
    assert "buy_polymarket" not in agent_sources
    assert "executor-service" not in agent_sources
