from __future__ import annotations

import asyncio

from hl_observer.collection.native_venue_coordinator import NativeVenueCoordinator
from hl_observer.markets.ccxt_universe import (
    CCXTUniverseScout,
    load_native_collection_candidates,
)


def _perp(symbol: str, base: str, *, active: bool = True) -> dict[str, object]:
    return {
        "id": symbol.replace("/", "").replace(":", ""),
        "symbol": symbol,
        "base": base,
        "quote": "USDT",
        "settle": "USDT",
        "type": "swap",
        "spot": False,
        "swap": True,
        "future": False,
        "contract": True,
        "linear": True,
        "inverse": False,
        "contractSize": 1.0,
        "active": active,
        "info": {},
    }


class FakeExchange:
    def __init__(self, markets: dict[str, dict[str, object]] | Exception) -> None:
        self.markets = markets
        self.closed = False

    def load_markets(self) -> dict[str, dict[str, object]]:
        if isinstance(self.markets, Exception):
            raise self.markets
        return self.markets

    def close(self) -> None:
        self.closed = True


def _scout(tmp_path, payloads: dict[str, object], **kwargs) -> CCXTUniverseScout:
    return CCXTUniverseScout(
        exchanges=list(payloads),
        exchange_factory=lambda venue: FakeExchange(payloads[venue]),
        snapshot_path=tmp_path / "ccxt_universe.json",
        timeout_seconds=0.5,
        max_attempts=1,
        **kwargs,
    )


def test_normalizes_linear_perpetual(tmp_path):
    scout = _scout(tmp_path, {"bybit": {"BTC/USDT:USDT": _perp("BTC/USDT:USDT", "btc")}})

    result = asyncio.run(scout.scan())

    market = result.markets[0]
    assert market.model_dump() == {
        "venue": "bybit",
        "exchange_symbol": "BTC/USDT:USDT",
        "canonical_base": "BTC",
        "quote": "USDT",
        "market_type": "perp",
        "active": True,
        "linear": True,
        "inverse": False,
        "settle_currency": "USDT",
        "contract_size": 1.0,
        "discovered_at": result.discovered_at,
        "source": "CCXT",
        "discovery_status": "NATIVE_ELIGIBLE",
    }


def test_aggregates_same_coin_across_venues(tmp_path):
    payloads = {
        "bybit": {"BTC/USDT:USDT": _perp("BTC/USDT:USDT", "BTC")},
        "gateio": {"BTC/USDT:USDT": _perp("BTC/USDT:USDT", "BTC")},
    }

    result = asyncio.run(_scout(tmp_path, payloads).scan())

    btc = result.universe["BTC"]
    assert btc.venues == ["bybit", "gateio"]
    assert btc.venue_count == 2
    assert [item.canonical_base for item in result.markets_on_at_least(2)] == ["BTC"]
    assert result.multi_venue_candidates_2 == ["BTC"]
    assert result.multi_venue_candidates_3 == []
    assert result.native_collection_candidates == ["BTC"]
    assert result.native_candidate_coins() == ["BTC"]
    assert load_native_collection_candidates(tmp_path / "ccxt_universe.json") == ["BTC"]
    coordinator = NativeVenueCoordinator(
        bybit_client=object(),
        okx_client=object(),
        ccxt_snapshot_path=tmp_path / "ccxt_universe.json",
    )
    coordinator.registry = {
        "ETH": {"bybit": "ETHUSDT"},
        "BTC": {"bybit": "BTCUSDT"},
    }
    assert coordinator.symbols_for("bybit") == ["BTCUSDT", "ETHUSDT"]


def test_detects_new_market_against_previous_snapshot(tmp_path):
    first = {"bybit": {"BTC/USDT:USDT": _perp("BTC/USDT:USDT", "BTC")}}
    asyncio.run(_scout(tmp_path, first).scan())
    second = {
        "bybit": {
            "BTC/USDT:USDT": _perp("BTC/USDT:USDT", "BTC"),
            "SOL/USDT:USDT": _perp("SOL/USDT:USDT", "SOL"),
        },
        "gateio": {"BTC/USDT:USDT": _perp("BTC/USDT:USDT", "BTC")},
    }

    result = asyncio.run(_scout(tmp_path, second).scan())

    assert {market.canonical_base for market in result.new_markets} == {"BTC", "SOL"}
    assert result.removed_markets == []
    assert result.new_venues_by_coin == {"BTC": ["gateio"]}


def test_venue_failure_does_not_fail_global_scan(tmp_path):
    payloads = {
        "bybit": {"BTC/USDT:USDT": _perp("BTC/USDT:USDT", "BTC")},
        "gateio": RuntimeError("temporarily unavailable"),
    }

    result = asyncio.run(_scout(tmp_path, payloads).scan())

    assert [market.canonical_base for market in result.markets] == ["BTC"]
    assert result.venue_status["bybit"].status == "OK"
    assert result.venue_status["gateio"].status == "ERROR"
    assert "temporarily unavailable" in result.errors_by_venue["gateio"]


def test_marks_market_discovery_only_without_native_collector(tmp_path):
    payloads = {"kucoinfutures": {"XYZ/USDT:USDT": _perp("XYZ/USDT:USDT", "XYZ")}}

    result = asyncio.run(_scout(tmp_path, payloads).scan())

    assert result.markets[0].discovery_status == "DISCOVERY_ONLY"
    assert result.universe["XYZ"].discovery_status == "DISCOVERY_ONLY"
    assert result.universe["XYZ"].native_venues == []
    assert result.native_candidate_coins() == []
    assert load_native_collection_candidates(tmp_path / "ccxt_universe.json") == []
