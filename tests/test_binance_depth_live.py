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
        raw_ticks = [tick for tick in ticks if tick.channel == "l2Book_snapshot"]
        capacity_ticks = [tick for tick in ticks if tick.channel == "capacity_tape"]
        assert len(raw_ticks) == 1
        assert raw_ticks[0].event_kind.value == "SNAPSHOT"
        assert raw_ticks[0].source_id == "binance_usdm_public"
        assert len(capacity_ticks) == 1
        assert capacity_ticks[0].source_id == "binance_derived_capacity"
        assert capacity_ticks[0].parsed_summary["raw_l2_source_of_truth"] is True
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


def test_rest_snapshot_uses_separate_partition_and_zero_event_gap() -> None:
    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "lastUpdateId": 100,
                    "E": 1000,
                    "T": 999,
                    "bids": [["100", "1"]],
                    "asks": [["101", "1"]],
                },
            )

        client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        ticks = []
        collector = BinanceDepthLiveCollector(
            ["BTCUSDT"],
            http_client=client,
            tick_sink=ticks.append,
        )
        await collector.resync_symbol("BTCUSDT", connection_id="bin-test")
        raw_ticks = [tick for tick in ticks if tick.channel == "l2Book_snapshot"]
        capacity_ticks = [tick for tick in ticks if tick.channel == "capacity_tape"]
        assert len(raw_ticks) == 1
        assert len(capacity_ticks) == 1
        tick = raw_ticks[0]
        assert tick.gap_count == 0
        assert tick.provenance["gap_count_semantics"] == "event_delta"
        assert capacity_ticks[0].gap_count == 0
        assert capacity_ticks[0].provenance["derived_from_family"] == "l2Book"
        await client.aclose()

    asyncio.run(scenario())

def test_partial_depth_fallback_preserves_real_ws_depth_but_stays_fail_closed() -> None:
    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                451,
                json={"msg": "Service unavailable from a restricted location"},
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
            partial_fallback_levels=20,
        )

        assert await collector.resync_symbol("BTCUSDT", connection_id="bin-partial") is None
        assert "BTCUSDT" in collector.health()["rest_unavailable_symbols"]
        assert "btcusdt@depth20@100ms" in collector.websocket_url()

        frame = parse_depth_frame(
            {
                "stream": "btcusdt@depth20@100ms",
                "data": {
                    "e": "depthUpdate",
                    "E": 2_010,
                    "T": 2_005,
                    "s": "BTCUSDT",
                    "U": 201,
                    "u": 203,
                    "pu": 200,
                    "b": [["100", "2"], ["99", "3"]],
                    "a": [["101", "4"], ["102", "5"]],
                },
            }
        )
        assert frame is not None
        collector._emit_partial_fallback(
            "BTCUSDT",
            frame,
            connection_id="bin-partial",
            receive_wall_ms=2_020,
            receive_mono_ns=20_000,
        )

        assert publications[-1][1]["quality"] == "PARTIAL_L2_FALLBACK"
        assert publications[-1][1]["data_gate_ready"] is False
        raw = [tick for tick in ticks if tick.channel == "l2Book_partial_snapshot"]
        assert len(raw) == 1
        assert raw[0].parsed_summary["data_gate_ready"] is False
        assert collector.health()["partial_fallback_publications"] == 1
        await client.aclose()

    asyncio.run(scenario())

def test_rest_resync_failure_is_rate_limited_by_cooldown() -> None:
    async def scenario() -> None:
        calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(451, json={"msg": "restricted location"})

        client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        collector = BinanceDepthLiveCollector(
            ["BTCUSDT"],
            http_client=client,
            rest_retry_cooldown_s=60.0,
        )

        assert await collector.resync_symbol("BTCUSDT", connection_id="cooldown") is None
        assert calls == 1
        assert "BTCUSDT" in collector.health()["rest_retry_deferred_symbols"]

        collector._schedule_resync("BTCUSDT", "cooldown")
        await asyncio.sleep(0)
        assert calls == 1
        assert "BTCUSDT" not in collector._resync_pending
        await client.aclose()

    asyncio.run(scenario())

