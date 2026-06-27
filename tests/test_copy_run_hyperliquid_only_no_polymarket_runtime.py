"""The runtime path is Hyperliquid-only: no active Polymarket package/import."""

from __future__ import annotations

import sys
from pathlib import Path

# Real Polymarket runtime packages we must never load.
POLYMARKET_PACKAGES = ("polymarket", "py_clob_client", "clob_client")


def test_runtime_loads_no_polymarket_package():
    import hyper_smart_observer.copy_mode.copy_loop  # noqa: F401
    import hyper_smart_observer.copy_mode.copy_signal_detector  # noqa: F401
    import hyper_smart_observer.market_signals.market_signal_features  # noqa: F401
    import hyper_smart_observer.hyperliquid_client.info_client  # noqa: F401

    # Compare on the TOP-LEVEL package name so our own test module name
    # (which literally contains "polymarket") is not a false positive.
    loaded = [
        m for m in sys.modules
        if m.split(".")[0].lower() in POLYMARKET_PACKAGES
    ]
    assert loaded == [], f"active polymarket packages loaded: {loaded}"


def test_runtime_source_has_no_polymarket_clob_or_buy():
    runtime_files = [
        "hyper_smart_observer/copy_mode/copy_loop.py",
        "hyper_smart_observer/copy_mode/copy_signal_detector.py",
        "hyper_smart_observer/market_signals/market_signal_features.py",
        "hyper_smart_observer/hyperliquid_client/info_client.py",
    ]
    for f in runtime_files:
        text = Path(f).read_text(encoding="utf-8").lower()
        assert "clob-client" not in text
        assert "@polymarket" not in text
        assert "buy_polymarket" not in text
