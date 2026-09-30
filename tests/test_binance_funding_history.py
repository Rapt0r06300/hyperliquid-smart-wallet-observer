from __future__ import annotations

import asyncio

import httpx

from hl_observer.collection.binance_funding_history import (
    fetch_binance_funding_settlements,
)


def test_binance_funding_history_is_bounded_and_deduped() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/fapi/v1/fundingRate"
            assert request.url.params["symbol"] == "BTCUSDT"
            assert request.url.params["startTime"] == "1000"
            assert request.url.params["endTime"] == "5000"
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": "BTCUSDT",
                        "fundingTime": 2000,
                        "fundingRate": "0.0001",
                        "markPrice": "100.5",
                        "rateType": "FUNDING",
                    },
                    {
                        "symbol": "BTCUSDT",
                        "fundingTime": 2000,
                        "fundingRate": "0.0001",
                        "markPrice": "100.5",
                    },
                    {
                        "symbol": "BTCUSDT",
                        "fundingTime": 4000,
                        "fundingRate": "-0.00005",
                        "markPrice": "101.0",
                    },
                    {
                        "symbol": "BTCUSDT",
                        "fundingTime": 6000,
                        "fundingRate": "0.1",
                    },
                ],
            )

        client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        rows = await fetch_binance_funding_settlements(
            ["BTCUSDT"],
            start_ms=1000,
            end_ms=5000,
            http_client=client,
        )
        await client.aclose()

        assert len(rows) == 2
        assert [row.exchange_ts_ms for row in rows] == [2000, 4000]
        assert all(row.channel == "funding_settlement" for row in rows)
        assert all(row.provenance["authenticated"] is False for row in rows)
        assert rows[0].parsed_summary["funding_rate"] == 0.0001
        assert rows[0].parsed_summary["mark_price"] == 100.5
        assert rows[1].parsed_summary["funding_rate"] == -0.00005

    asyncio.run(scenario())


def test_invalid_window_returns_no_rows() -> None:
    assert asyncio.run(
        fetch_binance_funding_settlements(
            ["BTCUSDT"],
            start_ms=5000,
            end_ms=5000,
        )
    ) == []
