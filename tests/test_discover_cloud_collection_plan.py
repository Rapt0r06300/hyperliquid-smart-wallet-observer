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
    monkeypatch.setattr(module, "_liquidity_hints", lambda _venues: ({}, {}))

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


def test_partial_discovery_errors_do_not_stop_healthy_collection() -> None:
    module = _module()
    plan = {
        "selected_coin_count": 12,
        "errors": {"binance": "HTTPStatusError", "bybit": "HTTPStatusError"},
    }
    assert module._plan_exit_code(plan) == 0


def test_discovery_still_fails_when_no_collectable_universe_exists() -> None:
    module = _module()
    assert module._plan_exit_code({"selected_coin_count": 0, "errors": {"binance": "HTTPStatusError"}}) == 2



def test_liquidity_priority_reorders_only_inside_frozen_selection() -> None:
    module = _module()
    ranked = [
        ("BTC", {"hyperliquid": "BTC", "binance": "BTCUSDT"}),
        ("ETH", {"hyperliquid": "ETH", "binance": "ETHUSDT"}),
        ("SOL", {"hyperliquid": "SOL", "binance": "SOLUSDT"}),
    ]
    liquidity = {
        "BTC": {"hyperliquid": 10.0, "binance": 10.0},
        "ETH": {"hyperliquid": 1000.0, "binance": 1000.0},
        "SOL": {"hyperliquid": 100.0, "binance": 100.0},
    }

    prioritized, active = module._prioritize_without_filtering(ranked, liquidity)

    assert active is True
    assert [coin for coin, _symbols in prioritized] == ["ETH", "SOL", "BTC"]
    assert {coin for coin, _symbols in prioritized} == {coin for coin, _symbols in ranked}


def test_liquidity_priority_exactly_falls_back_with_insufficient_sources() -> None:
    module = _module()
    ranked = [
        ("BTC", {"hyperliquid": "BTC", "binance": "BTCUSDT"}),
        ("ETH", {"hyperliquid": "ETH", "binance": "ETHUSDT"}),
    ]

    prioritized, active = module._prioritize_without_filtering(
        ranked,
        {"ETH": {"binance": 999999.0}},
    )

    assert active is False
    assert prioritized == ranked


def test_liquidity_cannot_change_legacy_max_coins_selection(monkeypatch) -> None:
    module = _module()
    coins = {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL"}
    monkeypatch.setattr(module, "_hl_markets", lambda: dict(coins))
    monkeypatch.setattr(
        module,
        "_binance_markets",
        lambda: {coin: f"{coin}USDT" for coin in coins},
    )

    class Client:
        def __init__(self, suffix: str) -> None:
            self.suffix = suffix

        def discover_usdt_perpetuals(self):
            return [(coin, f"{coin}{self.suffix}") for coin in coins]

    monkeypatch.setattr(module, "BybitPublicClient", lambda: Client("USDT"))
    monkeypatch.setattr(module, "OkxPublicClient", lambda: Client("-USDT-SWAP"))
    monkeypatch.setattr(module, "GatePublicClient", lambda: Client("_USDT"))
    monkeypatch.setattr(module, "BitgetPublicClient", lambda: Client("USDT"))
    monkeypatch.setattr(
        module,
        "_liquidity_hints",
        lambda _venues: (
            {
                "SOL": {"binance": 1_000_000_000.0, "bybit": 1_000_000_000.0},
                "ETH": {"binance": 100.0, "bybit": 100.0},
                "BTC": {"binance": 10.0, "bybit": 10.0},
            },
            {},
        ),
    )

    plan = module.discover_cloud_universe(min_venues=2, max_coins=2, batch_size=8)

    assert {row["coin"] for row in plan["selected"]} == {"BTC", "ETH"}
    assert plan["priority"]["selection_set_preserved"] is True
    assert plan["priority"]["non_destructive"] is True
