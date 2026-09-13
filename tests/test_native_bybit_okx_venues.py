from __future__ import annotations

import asyncio

from hl_observer.markets.venues.bybit import (
    BybitPublicClient,
    parse_bybit_bbo,
    parse_bybit_instrument,
    parse_bybit_metrics,
)
from hl_observer.markets.venues.models import VenueInstrument
from hl_observer.markets.venues.multi_venue import discover_native_venue_candidates
from hl_observer.markets.venues.okx import (
    OkxPublicClient,
    parse_okx_bbo,
    parse_okx_instrument,
    parse_okx_metrics,
)
from hl_observer.markets.venues.symbols import (
    canonical_bybit_symbol,
    canonical_okx_symbol,
    canonical_symbol,
)


def test_symbol_normalization_is_cross_venue_stable() -> None:
    assert canonical_symbol("btc", "usdt") == "BTC-USDT"
    assert canonical_bybit_symbol("BTCUSDT") == "BTC-USDT"
    assert canonical_bybit_symbol("1000PEPEUSDT") == "1000PEPE-USDT"
    assert canonical_okx_symbol("BTC-USDT-SWAP") == "BTC-USDT"


def test_bybit_public_parsers_cover_instrument_bbo_and_metrics() -> None:
    instrument = parse_bybit_instrument(
        {
            "symbol": "BTCUSDT",
            "contractType": "LinearPerpetual",
            "status": "Trading",
            "baseCoin": "BTC",
            "quoteCoin": "USDT",
            "settleCoin": "USDT",
            "priceFilter": {"tickSize": "0.10"},
            "lotSizeFilter": {"minOrderQty": "0.001"},
        }
    )
    assert instrument is not None
    assert instrument.canonical_symbol == "BTC-USDT"
    assert instrument.tick_size == 0.1

    quote = parse_bybit_bbo(
        {
            "topic": "orderbook.1.BTCUSDT",
            "type": "snapshot",
            "ts": 1_700_000_000_010,
            "data": {
                "s": "BTCUSDT",
                "b": [["65000.0", "2.5"]],
                "a": [["65001.0", "1.5"]],
                "u": 42,
                "seq": 100,
                "cts": 1_700_000_000_000,
            },
        },
        received_ts_ms=1_700_000_000_015,
    )
    assert quote is not None
    assert quote.bid_price == 65000.0
    assert quote.ask_price == 65001.0
    assert quote.age_ms == 15
    assert quote.sequence == 100
    assert 0 < quote.spread_bps < 1

    metrics = parse_bybit_metrics(
        {
            "symbol": "BTCUSDT",
            "lastPrice": "65000",
            "markPrice": "65002",
            "indexPrice": "65001",
            "volume24h": "123.4",
            "turnover24h": "8000000",
            "openInterest": "456.7",
            "openInterestValue": "29000000",
            "fundingRate": "0.0001",
            "nextFundingTime": "1700003600000",
        }
    )
    assert metrics is not None
    assert metrics.funding_rate == 0.0001
    assert metrics.open_interest == 456.7


def test_okx_public_parsers_cover_instrument_bbo_and_metrics() -> None:
    instrument = parse_okx_instrument(
        {
            "instId": "BTC-USDT-SWAP",
            "instType": "SWAP",
            "state": "live",
            "ctType": "linear",
            "settleCcy": "USDT",
            "tickSz": "0.1",
            "minSz": "0.01",
        }
    )
    assert instrument is not None
    assert instrument.canonical_symbol == "BTC-USDT"

    quote = parse_okx_bbo(
        {
            "arg": {"channel": "bbo-tbt", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "asks": [["65001", "3", "0", "1"]],
                    "bids": [["65000", "4", "0", "1"]],
                    "ts": "1700000000000",
                    "seqId": "77",
                }
            ],
        },
        received_ts_ms=1_700_000_000_012,
    )
    assert quote is not None
    assert quote.canonical_symbol == "BTC-USDT"
    assert quote.age_ms == 12
    assert quote.sequence == 77

    metrics = parse_okx_metrics(
        {"instId": "BTC-USDT-SWAP", "last": "65000", "vol24h": "111", "volCcy24h": "7200000", "ts": "1700000000000"},
        funding={"fundingRate": "0.0002", "nextFundingTime": "1700003600000"},
        open_interest={"oi": "999"},
    )
    assert metrics is not None
    assert metrics.funding_rate == 0.0002
    assert metrics.open_interest == 999.0


def test_subscription_payloads_use_public_bbo_channels() -> None:
    assert BybitPublicClient.subscription_payload(["BTCUSDT"]) == {
        "op": "subscribe",
        "args": ["orderbook.1.BTCUSDT"],
    }
    assert OkxPublicClient.subscription_payload(["BTC-USDT-SWAP"]) == {
        "op": "subscribe",
        "args": [{"channel": "bbo-tbt", "instId": "BTC-USDT-SWAP"}],
    }


class _FakeVenue:
    def __init__(self, venue: str, instruments: list[VenueInstrument]) -> None:
        self.venue = venue
        self.instruments = instruments

    async def discover_instruments(self, *, include_prelaunch: bool = False) -> list[VenueInstrument]:
        if include_prelaunch:
            return self.instruments
        return [item for item in self.instruments if not item.is_prelaunch]


def test_multi_venue_discovery_finds_shared_and_hyperliquid_candidates() -> None:
    bybit_btc = VenueInstrument(
        venue="bybit",
        symbol="BTCUSDT",
        base="BTC",
        quote="USDT",
        canonical_symbol="BTC-USDT",
        status="Trading",
    )
    bybit_sol = VenueInstrument(
        venue="bybit",
        symbol="SOLUSDT",
        base="SOL",
        quote="USDT",
        canonical_symbol="SOL-USDT",
        status="Trading",
    )
    okx_btc = VenueInstrument(
        venue="okx",
        symbol="BTC-USDT-SWAP",
        base="BTC",
        quote="USDT",
        canonical_symbol="BTC-USDT",
        status="live",
    )
    result = asyncio.run(
        discover_native_venue_candidates(
            ["bybit", "okx"],
            hyperliquid_coins=["BTC", "ETH", "SOL"],
            clients={
                "bybit": _FakeVenue("bybit", [bybit_btc, bybit_sol]),
                "okx": _FakeVenue("okx", [okx_btc]),
            },
        )
    )
    assert result.errors == {}
    assert result.cross_venue_candidates == ["BTC-USDT"]
    assert result.hyperliquid_overlap == ["BTC-USDT", "SOL-USDT"]
    assert result.canonical_venues["BTC-USDT"] == ["bybit", "okx"]
