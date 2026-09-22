from __future__ import annotations

import asyncio

import httpx

from hl_observer.collection.native_funding_history import (
    fetch_bybit_funding_settlements,
    fetch_okx_funding_settlements,
)


def test_bybit_funding_history_is_bounded() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v5/market/funding/history"
            assert request.url.params["category"] == "linear"
            assert request.url.params["symbol"] == "BTCUSDT"
            return httpx.Response(
                200,
                json={
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "category": "linear",
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "fundingRate": "0.0001",
                                "fundingRateTimestamp": "2000",
                            },
                            {
                                "symbol": "BTCUSDT",
                                "fundingRate": "-0.00005",
                                "fundingRateTimestamp": "4000",
                            },
                            {
                                "symbol": "BTCUSDT",
                                "fundingRate": "0.2",
                                "fundingRateTimestamp": "6000",
                            },
                        ],
                    },
                },
            )

        client = httpx.AsyncClient(
            base_url="https://api.bybit.com",
            transport=httpx.MockTransport(handler),
        )
        rows = await fetch_bybit_funding_settlements(
            ["BTCUSDT"],
            start_ms=1000,
            end_ms=5000,
            http_client=client,
        )
        await client.aclose()
        assert [row.exchange_ts_ms for row in rows] == [2000, 4000]
        assert all(row.channel == "funding_settlement" for row in rows)
        assert rows[0].source_id == "bybit_public_rest"

    asyncio.run(scenario())


def test_okx_funding_history_preserves_realized_rate() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v5/public/funding-rate-history"
            assert request.url.params["instId"] == "BTC-USDT-SWAP"
            return httpx.Response(
                200,
                json={
                    "code": "0",
                    "msg": "",
                    "data": [
                        {
                            "instId": "BTC-USDT-SWAP",
                            "fundingRate": "0.0001",
                            "realizedRate": "0.00009",
                            "fundingTime": "2000",
                        },
                        {
                            "instId": "BTC-USDT-SWAP",
                            "fundingRate": "-0.00005",
                            "realizedRate": "-0.00004",
                            "fundingTime": "4000",
                        },
                    ],
                },
            )

        client = httpx.AsyncClient(
            base_url="https://www.okx.com",
            transport=httpx.MockTransport(handler),
        )
        rows = await fetch_okx_funding_settlements(
            ["BTC-USDT-SWAP"],
            start_ms=1000,
            end_ms=5000,
            http_client=client,
        )
        await client.aclose()
        assert [row.exchange_ts_ms for row in rows] == [2000, 4000]
        assert rows[0].parsed_summary["realized_rate"] == 0.00009
        assert rows[1].parsed_summary["realized_rate"] == -0.00004
        assert rows[0].source_id == "okx_public_rest"

    asyncio.run(scenario())
