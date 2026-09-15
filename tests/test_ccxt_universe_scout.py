from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from typer.testing import CliRunner

from hl_observer import cli
from hl_observer.cli import app
from hl_observer.collection.native_venue_coordinator import NativeVenueCoordinator
from hl_observer.markets.ccxt_universe import (
    CCXTUniverseScout,
    load_native_collection_candidates,
)
from hl_observer.markets.universal_registry import AvailabilityStatus, UniversalMarketRegistry


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


def test_ccxt_result_ingests_full_metadata_into_universal_registry(tmp_path):
    payloads = {
        "bybit": {"BTC/USDT:USDT": _perp("BTC/USDT:USDT", "BTC")},
        "kucoinfutures": {"BTC/USDT:USDT": _perp("BTC/USDT:USDT", "BTC")},
    }
    result = asyncio.run(_scout(tmp_path, payloads).scan())
    registry = UniversalMarketRegistry(native_venues={"bybit"})

    registry.ingest_ccxt(result)

    bybit = registry.market("BTC").instruments_for_venue("bybit")[0]
    kucoin = registry.market("BTC").instruments_for_venue("kucoin")[0]
    assert bybit.status is AvailabilityStatus.NATIVE_LIVE
    assert kucoin.status is AvailabilityStatus.DISCOVERY_ONLY
    assert bybit.quote == "USDT"
    assert bybit.settle == "USDT"
    assert bybit.linear is True
    assert bybit.contract_size == 1.0


def test_registry_summary_exposes_requested_coverage_counts(tmp_path):
    payloads = {
        "bybit": {"BTC/USDT:USDT": _perp("BTC/USDT:USDT", "BTC")},
        "okx": {"BTC/USDT:USDT": _perp("BTC/USDT:USDT", "BTC")},
        "kucoinfutures": {"ETH/USDT:USDT": _perp("ETH/USDT:USDT", "ETH")},
    }
    result = asyncio.run(_scout(tmp_path, payloads).scan())
    registry = UniversalMarketRegistry(native_venues={"bybit", "okx"})
    registry.ingest_ccxt(result)

    assert registry.coins_at_least_venues(2) == ["BTC"]
    assert registry.coins_at_least_native_venues(2) == ["BTC"]
    assert registry.summary() == {
        "coins": 2,
        "instruments": 3,
        "native_live": 2,
        "discovery_only": 1,
        "historical_only": 0,
        "multi_venue_2+": 1,
        "hot_path_eligible": 1,
    }


def test_ccxt_cli_persists_registry_and_prints_compact_summary(tmp_path, monkeypatch):
    discovered = asyncio.run(
        _scout(
            tmp_path,
            {"bybit": {"BTC/USDT:USDT": _perp("BTC/USDT:USDT", "BTC")}},
        ).scan()
    )

    class StubScout:
        def __init__(self, **_kwargs):
            pass

        async def scan(self):
            return discovered

    config = SimpleNamespace(
        enabled=True,
        exchanges=("bybit",),
        snapshot_path=tmp_path / "ccxt.json",
        timeout_seconds=0.5,
        max_attempts=1,
        include_spot=False,
    )
    monkeypatch.setattr(cli, "_settings", lambda: SimpleNamespace(ccxt_universe=config))
    monkeypatch.setattr(cli, "CCXTUniverseScout", StubScout)
    monkeypatch.setattr(cli, "note_coins", lambda *_args, **_kwargs: None)
    registry_path = tmp_path / "universal.json"

    result = CliRunner().invoke(
        app,
        ["discover-ccxt-universe", "--registry", str(registry_path)],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["coins"] == 1
    assert output["native_live"] == 1
    assert output["registry"] == str(registry_path)
    restored = UniversalMarketRegistry.load(registry_path)
    assert restored.market("BTC").instruments_for_venue("bybit")[0].historical is True
