from __future__ import annotations

import asyncio

import httpx

from hl_observer.collection.binance_clock_sync import BinanceClockSyncProbe


def test_binance_clock_probe_estimates_public_server_offset(monkeypatch) -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/fapi/v1/time"
            return httpx.Response(200, json={"serverTime": 1_015})

        client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        values = iter([1.000, 1.020])
        probe = BinanceClockSyncProbe(
            http_client=client,
            wall_time=lambda: next(values),
        )
        sample = await probe.sample_once()
        assert sample is not None
        assert sample.rtt_ms == 20.0
        assert sample.offset_ms == 5.0
        assert probe.evidence()["clock_offset_ms"] == 5.0
        assert probe.evidence()["clock_probe_rtt_ms"] == 20.0
        await client.aclose()

    asyncio.run(scenario())


def test_binance_clock_probe_failure_stays_unavailable() -> None:
    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"msg": "down"})

        client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        probe = BinanceClockSyncProbe(http_client=client)
        assert await probe.sample_once() is None
        assert probe.evidence() == {}
        assert probe.health()["status"] == "UNAVAILABLE"
        assert probe.health()["failures"] == 1
        await client.aclose()

    asyncio.run(scenario())
