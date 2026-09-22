from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "discover_cloud_collection_plan_test",
        ROOT / "tools" / "discover_cloud_collection_plan.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cloud_plan_joins_six_native_venues(monkeypatch) -> None:
    module = _module()
    monkeypatch.setattr(module, "_hl_markets", lambda: {"BTC": "BTC"})
    monkeypatch.setattr(module, "_binance_markets", lambda: {"BTC": "BTCUSDT"})

    class Client:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

        def discover_usdt_perpetuals(self):
            return [("BTC", self.symbol)]

    monkeypatch.setattr(module, "BybitPublicClient", lambda: Client("BTCUSDT"))
    monkeypatch.setattr(module, "OkxPublicClient", lambda: Client("BTC-USDT-SWAP"))
    monkeypatch.setattr(module, "GatePublicClient", lambda: Client("BTC_USDT"))
    monkeypatch.setattr(module, "BitgetPublicClient", lambda: Client("BTCUSDT"))

    plan = module.discover_cloud_universe(
        min_venues=2,
        max_coins=10,
        batch_size=8,
    )
    assert plan["errors"] == {}
    assert plan["selected_coin_count"] == 1
    row = plan["selected"][0]
    assert row["venue_count"] == 6
    assert set(row["symbols"]) == {
        "hyperliquid",
        "binance",
        "bybit",
        "okx",
        "gate",
        "bitget",
    }
