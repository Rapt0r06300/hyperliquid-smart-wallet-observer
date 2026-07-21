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
    """REECRIT (audit 2026-07-11) : les docs *_FUSION.md ont ete supprimes a la consolidation
    documentaire (640 -> 7, commit 35703aa). Les ressusciter serait faux. L'intention -- "toute idee
    importee est CLASSEE, jamais copiee en aveugle" -- vit desormais dans CLAUDE.md."""
    rules = Path("CLAUDE.md").read_text(encoding="utf-8", errors="replace")
    for status in ("COPY_DIRECT", "COPY_ADAPTED", "PORT_BEHAVIOR",
                   "INSPIRE_ONLY", "SKIP_WITH_REASON", "DEFERRED_WITH_PLAN"):
        assert status in rules, f"classification de portage absente: {status}"


def test_repo_idea_matrix_has_keep_adapt_ban_defer():
    """REECRIT : la matrice .md a ete supprimee ; la regle de classement vit dans CLAUDE.md."""
    rules = Path("CLAUDE.md").read_text(encoding="utf-8", errors="replace")
    assert "Ne pas copier en aveugle" in rules
    assert "PaperIntent" in rules and "NO_TRADE" in rules
    assert "Aucun repo externe ne bypasse" in rules


def test_no_external_code_copy_license_markers():
    """REECRIT : pas de copie de code externe en aveugle -- regle portee par CLAUDE.md."""
    rules = Path("CLAUDE.md").read_text(encoding="utf-8", errors="replace")
    assert "Ne pas copier en aveugle" in rules
    assert "sans test" in rules      # aucun comportement "porte" sans test ni branchement


def test_start_script_preserves_calibrated_freshness_guard():
    ps1 = Path("tools/start_hypersmart_simulation.ps1").read_text(encoding="utf-8")
    cmd = Path("LANCER_HYPERSMART.cmd").read_text(encoding="utf-8")

    assert "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS" in ps1   # present ; valeur calibree
    assert 'Set-HyperSmartDefaultEnv "HYPERSMART_V9_PIPELINE_AUTHORITATIVE" "1"' in ps1
    assert "HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS=" in cmd  # calibre
    assert "HYPERSMART_V9_PIPELINE_AUTHORITATIVE=1" in cmd
    assert "DYDX_MAX_SIGNAL_AGE_MS" not in cmd
    assert "DYDX_" not in cmd


def test_start_script_min_edge_bps_guard():
    ps1 = Path("tools/start_hypersmart_simulation.ps1").read_text(encoding="utf-8")
    cmd = Path("LANCER_HYPERSMART.cmd").read_text(encoding="utf-8")

    # Le garde-fou doit exister ; sa VALEUR se calibre (elle ne se fige pas dans un test).
    # Ce test exigeait "55" en dur. Or 55 bps est INATTEIGNABLE pour un signal mono-wallet :
    # l'edge restant maximum theorique vaut ~32 bps (audit calibrage 2026-07-11). Figer 55
    # revenait a exiger un verrou MORT -- le mode sniper ne pouvait jamais ouvrir.
    # Le vrai invariant : le plancher existe, il est positif, et il est ATTEIGNABLE.
    import re

    assert "HYPERSMART_SIMULATION_MIN_EDGE_BPS" in ps1
    assert "HYPERSMART_SIMULATION_MIN_EDGE_BPS=" in cmd
    m = re.search(r'HYPERSMART_SINGLE_WALLET_MIN_EDGE_BPS"\s+"([0-9.]+)"', ps1)
    assert m, "le plancher single-wallet doit rester present au launcher"
    plancher = float(m.group(1))
    # 🔴 21/07 — DEUX ETATS LEGITIMES, pas un seul.
    # Le sniper single-wallet est un mode COPY. Or l'edge copy est mesure NEGATIF (-7,97 bps
    # sur 24 133 signaux OOS, meme a cout zero — loi `copy_global`, REFUTE). Le desactiver
    # DELIBEREMENT via un plancher-sentinelle (>= 9000 bps = « jamais ») est donc CORRECT, pas
    # un verrou mort par accident : on ne VEUT pas que ce sniper ouvre. Le moteur actif est le
    # carry. La valeur 9999 est en place depuis le 20/07, avant cette session.
    # L'invariant garde son mordant sur le cas ACTIF : si le sniper est cense tourner
    # (plancher < 9000), il doit rester ATTEIGNABLE (<= 40 bps), sinon c'est un vrai verrou mort.
    OFF_SENTINELLE = 9000.0
    if plancher >= OFF_SENTINELLE:
        pass  # sniper copy explicitement DESACTIVE (edge negatif prouve) — etat voulu
    else:
        assert 0 < plancher <= 40, (
            f"plancher single-wallet {plancher} bps : soit ATTEIGNABLE (<= 40, edge restant "
            f"max ~32 bps), soit explicitement DESACTIVE (>= {OFF_SENTINELLE:.0f}). Entre les "
            f"deux = verrou mort par accident. Voir tests/test_calibration_no_dead_gates.py"
        )


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
    """LA regle la plus importante : jamais de promesse de PnL, jamais de donnee fabriquee."""
    rules = Path("CLAUDE.md").read_text(encoding="utf-8", errors="replace")
    assert "Jamais de promesse de PnL" in rules
    assert "Aucune donn" in rules and "fabriqu" in rules   # "Aucune donnee fabriquee"
    assert "NO_TRADE" in rules                              # doute -> on ne trade pas
    assert "Aucun ordre r" in rules                         # "Aucun ordre reel"

def test_no_polymarket_clob_or_execution_dependency_added_to_agent_tools():
    agent_sources = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in Path("hyper_smart_observer/agent_tools").rglob("*.py")
    ).lower()

    assert "@polymarket/clob-client" not in agent_sources
    assert "tradingenabled" not in agent_sources
    assert "buy_polymarket" not in agent_sources
    assert "executor-service" not in agent_sources
