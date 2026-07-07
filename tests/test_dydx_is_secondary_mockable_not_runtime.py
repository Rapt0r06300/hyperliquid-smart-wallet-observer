"""dYdX is preserved (not deleted) but is NOT imported by the Hyperliquid runtime."""

from __future__ import annotations

from pathlib import Path

RUNTIME_FILES = [
    "hyper_smart_observer/copy_mode/copy_loop.py",
    "hyper_smart_observer/copy_mode/copy_signal_detector.py",
    "hyper_smart_observer/market_signals/market_signal_features.py",
    "hyper_smart_observer/market_signals/orderbook_features.py",
    "hyper_smart_observer/market_signals/mid_stability.py",
    "hyper_smart_observer/hyperliquid_client/info_client.py",
    "hyper_smart_observer/paper_trading/simulator.py",
    "hyper_smart_observer/dashboard/exporter.py",
]


def test_hl_runtime_source_does_not_import_dydx():
    for f in RUNTIME_FILES:
        text = Path(f).read_text(encoding="utf-8")
        assert "dydx_v4" not in text and "import dydx" not in text, f"{f} references dYdX"


def test_dydx_package_preserved_but_launcher_is_hyperliquid_first():
    assert Path("hyper_smart_observer/dydx_v4").is_dir()  # preserved, not deleted
    cmd = Path("LANCER_HYPERSMART.cmd").read_text(encoding="utf-8")
    assert "start_hypersmart_simulation.ps1" in cmd  # Hyperliquid-first entrypoint
    assert "DYDX_" not in cmd


def test_ui_runtime_entrypoints_do_not_mount_dydx_or_call_dydx_api():
    app = Path("src/hl_observer/ui/app.py").read_text(encoding="utf-8")
    simulation = Path("src/hl_observer/ui/static/simulation_v2.html").read_text(encoding="utf-8")
    metagraph_v1 = Path("src/hl_observer/ui/static/metagraph_smooth.js").read_text(encoding="utf-8")
    metagraph_v2 = Path("src/hl_observer/ui/static/metagraph_smooth_v2.js").read_text(encoding="utf-8")

    assert "create_dydx_router" not in app
    assert "dydx_v4.engine" not in app
    assert "/api/dydx" not in simulation
    assert "/api/dydx" not in metagraph_v1
    assert "/api/dydx" not in metagraph_v2
    assert "/api/simulation/overview" in simulation
    assert "/api/simulation/overview" in metagraph_v1
    assert "/api/simulation/overview" in metagraph_v2
