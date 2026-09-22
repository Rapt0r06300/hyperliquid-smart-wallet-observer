from __future__ import annotations

import asyncio

import httpx

from hl_observer.collection.hyperliquid_funding_history import (
    fetch_hyperliquid_funding_settlements,
)


def test_funding_history_is_bounded_deduped_and_timestamped() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = __import__("json").loads(request.content.decode())
            assert body["type"] == "fundingHistory"
            assert body["startTime"] == 1_000
            assert body["endTime"] == 5_000
            return httpx.Response(
                200,
                json=[
                    {
                        "coin": body["coin"],
                        "fundingRate": "0.0001",
                        "premium": "0.0002",
                        "time": 2_000,
                    },
                    {
                        "coin": body["coin"],
                        "fundingRate": "0.0001",
                        "premium": "0.0002",
                        "time": 2_000,
                    },
                    {
                        "coin": body["coin"],
                        "fundingRate": "-0.00005",
                        "premium": "0.0001",
                        "time": 4_000,
                    },
                    {
                        "coin": body["coin"],
                        "fundingRate": "0.5",
                        "time": 6_000,
                    },
                    {"coin": body["coin"], "fundingRate": None, "time": 3_000},
                ],
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        rows = await fetch_hyperliquid_funding_settlements(
            ["BTC"],
            start_ms=1_000,
            end_ms=5_000,
            http_client=client,
        )
        await client.aclose()

        assert len(rows) == 2
        assert [row.exchange_ts_ms for row in rows] == [2_000, 4_000]
        assert all(row.channel == "funding_settlement" for row in rows)
        assert all(row.provenance["authenticated"] is False for row in rows)
        assert rows[0].parsed_summary["funding_rate"] == 0.0001
        assert rows[1].parsed_summary["funding_rate"] == -0.00005
        assert rows[0].parsed_summary["authoritative_history"] is True

    asyncio.run(scenario())


def test_invalid_or_empty_window_returns_no_rows() -> None:
    assert asyncio.run(
        fetch_hyperliquid_funding_settlements(
            ["BTC"],
            start_ms=5_000,
            end_ms=5_000,
        )
    ) == []
