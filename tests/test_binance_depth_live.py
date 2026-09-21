from __future__ import annotations

import asyncio

import httpx

from hl_observer.collection.binance_depth_live import (
    BinanceDepthLiveCollector,
    parse_depth_frame,
)


def test_parse_binance_combined_depth_frame() -> None:
    frame = parse_depth_frame(
        {
            "stream": "btcusdt@depth@100ms",
            "data": {
                "e": "depthUpdate",
                "E": 1_010,
                "T": 1_005,
                "s": "BTCUSDT",
                "U": 101,
                "u": 103,
                "pu": 100,
                "b": [["100", "2"]],
                "a": [["101", "3"]],
            },
        }
    )
    assert frame is not None
    assert frame["symbol"] == "BTCUSDT"
    assert frame["U"] == 101
    assert frame["u"] == 103
    assert frame["pu"] == 100
    assert frame["transaction_ts_ms"] == 1_005


def test_rest_snapshot_replays_buffered_diff_and_publishes_deep_book() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/fapi/v1/depth"
            assert request.url.params["symbol"] == "BTCUSDT"
            return httpx.Response(
                200,
                json={
                    "lastUpdateId": 100,
                    "E": 1_000,
                    "T": 999,
                    "bids": [["100", "1"], ["99", "2"]],
                    "asks": [["101", "1"], ["102", "2"]],
                },
            )

        client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        ticks = []
        publications = []
        collector = BinanceDepthLiveCollector(
            ["BTCUSDT"],
            http_client=client,
            tick_sink=ticks.append,
            publication_sink=lambda symbol, row: publications.append((symbol, dict(row))),
            publication_depth=200,
        )
        state = collector.state("BTCUSDT")
        assert (
            state.sur_diff(
                U=101,
                u=103,
                pu=100,
                bids=[["100", "3"]],
                asks=[["101", "0"], ["101.5", "4"]],
                exchange_ts_ms=1_020,
                receive_ts_ms=1_025,
                receive_mono_ns=10_000,
                connection_id="bin-depth-test",
            )
            == "BUFFERISE"
        )

        publication = await collector.resync_symbol(
            "BTCUSDT",
            connection_id="bin-depth-test",
        )
        assert publication is not None
        assert publication["quality"] == "EXPLOITABLE"
        assert publication["needs_resnapshot"] is False
        assert publication["sequence"] == 103
        assert publication["best_bid"] == 100.0
        assert publication["best_ask"] == 101.5
        assert publication["bids"][0] == [100.0, 3.0]
        assert ticks and ticks[-1].event_kind.value == "SNAPSHOT"
        assert ticks[-1].source_id == "binance_usdm_public"
        assert publications[-1][0] == "BTCUSDT"
        await client.aclose()

    asyncio.run(scenario())


def test_snapshot_from_old_connection_never_reanchors_new_epoch() -> None:
    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(0)
            return httpx.Response(
                200,
                json={
                    "lastUpdateId": 100,
                    "bids": [["100", "1"]],
                    "asks": [["101", "1"]],
                },
            )

        client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        collector = BinanceDepthLiveCollector(["BTCUSDT"], http_client=client)
        state = collector.state("BTCUSDT")
        state.sur_diff(
            U=101,
            u=101,
            pu=100,
            receive_ts_ms=1_010,
            receive_mono_ns=1,
            connection_id="new-connection",
        )
        result = await collector.resync_symbol(
            "BTCUSDT",
            connection_id="old-connection",
        )
        assert result is None
        assert state.besoin_resnapshot()
        await client.aclose()

    asyncio.run(scenario())
