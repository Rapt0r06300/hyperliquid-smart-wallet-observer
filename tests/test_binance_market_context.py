from __future__ import annotations

import asyncio

import httpx

from hl_observer.collection.binance_market_context import (
    BinanceMarketContextCollector,
    instrument_metadata,
    parse_market_frame,
)


def test_parse_mark_funding_and_liquidation_frames() -> None:
    mark = parse_market_frame(
        {
            "data": {
                "e": "markPriceUpdate",
                "E": 1_000,
                "s": "BTCUSDT",
                "p": "100.5",
                "i": "100.4",
                "r": "0.0001",
                "T": 2_000,
                "ap": "100.45",
            }
        }
    )
    assert mark is not None
    assert mark["channel"] == "mark_funding"
    assert mark["summary"]["mark_price"] == 100.5
    assert mark["summary"]["index_price"] == 100.4
    assert mark["summary"]["funding_rate"] == 0.0001

    liquidation = parse_market_frame(
        {
            "data": {
                "e": "forceOrder",
                "E": 1_100,
                "o": {
                    "s": "BTCUSDT",
                    "S": "SELL",
                    "o": "LIMIT",
                    "f": "IOC",
                    "q": "2",
                    "p": "99",
                    "ap": "98.9",
                    "X": "FILLED",
                    "l": "2",
                    "z": "2",
                    "T": 1_095,
                },
            }
        }
    )
    assert liquidation is not None
    assert liquidation["channel"] == "liquidations"
    assert liquidation["exchange_ts_ms"] == 1_095
    assert liquidation["summary"]["side"] == "SELL"
    assert liquidation["summary"]["quantity"] == 2.0


def test_exchange_info_extracts_replay_critical_constraints() -> None:
    rows = instrument_metadata(
        {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "pair": "BTCUSDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                    "baseAsset": "BTC",
                    "quoteAsset": "USDT",
                    "marginAsset": "USDT",
                    "pricePrecision": 1,
                    "quantityPrecision": 3,
                    "filters": [
                        {
                            "filterType": "PRICE_FILTER",
                            "tickSize": "0.1",
                            "minPrice": "0.1",
                            "maxPrice": "1000000",
                        },
                        {
                            "filterType": "LOT_SIZE",
                            "stepSize": "0.001",
                            "minQty": "0.001",
                            "maxQty": "1000",
                        },
                        {
                            "filterType": "MIN_NOTIONAL",
                            "notional": "5",
                        },
                    ],
                }
            ]
        },
        wanted_symbols=["BTCUSDT"],
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["tick_size"] == 0.1
    assert row["lot_size"] == 0.001
    assert row["min_qty"] == 0.001
    assert row["min_notional"] == 5.0
    assert row["status"] == "TRADING"


def test_open_interest_and_metadata_rest_samples_are_taped() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/fapi/v1/openInterest":
                return httpx.Response(
                    200,
                    json={
                        "symbol": request.url.params["symbol"],
                        "openInterest": "123.4",
                        "time": 1_000,
                    },
                )
            if request.url.path == "/fapi/v1/exchangeInfo":
                return httpx.Response(
                    200,
                    json={
                        "serverTime": 1_100,
                        "symbols": [
                            {
                                "symbol": "BTCUSDT",
                                "status": "TRADING",
                                "contractType": "PERPETUAL",
                                "filters": [
                                    {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                                    {
                                        "filterType": "LOT_SIZE",
                                        "stepSize": "0.001",
                                        "minQty": "0.001",
                                    },
                                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                                ],
                            }
                        ],
                    },
                )
            raise AssertionError(request.url)

        client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        ticks = []
        collector = BinanceMarketContextCollector(
            ["BTCUSDT"],
            http_client=client,
            tick_sink=ticks.append,
        )
        assert await collector.poll_open_interest_once() == 1
        assert await collector.poll_metadata_once() == 1
        assert [tick.channel for tick in ticks] == [
            "open_interest",
            "instrument_metadata",
        ]
        assert collector.latest["BTCUSDT"]["open_interest"] == 123.4
        assert (
            collector.latest["BTCUSDT"]["instrument_metadata"]["tick_size"]
            == 0.1
        )
        await client.aclose()

    asyncio.run(scenario())
