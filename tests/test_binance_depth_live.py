from __future__ import annotations

import asyncio
import json

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


def test_binance_depth_ws_candidates_stay_mainnet_only() -> None:
    async def scenario() -> None:
        client = httpx.AsyncClient()
        collector = BinanceDepthLiveCollector(
            ["BTCUSDT"],
            http_client=client,
        )
        assert collector._ws_candidates() == (
            "wss://fstream.binance.com/public/stream",
        )
        assert all(
            "binancefuture.com" not in endpoint
            for endpoint in collector._ws_candidates()
        )
        await client.aclose()

    asyncio.run(scenario())


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


def test_ws_api_snapshot_recovers_full_book_when_rest_is_restricted() -> None:
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
                connection_id="bin-ws-api",
            )
            == "BUFFERISE"
        )

        async def fake_ws_api_snapshot(_symbol: str):
            return (
                {
                    "lastUpdateId": 100,
                    "E": 1_000,
                    "T": 999,
                    "bids": [["100", "1"], ["99", "2"]],
                    "asks": [["101", "1"], ["102", "2"]],
                },
                990,
                1_010,
                9_000,
            )

        collector._fetch_ws_api_snapshot = fake_ws_api_snapshot
        publication = await collector.resync_symbol(
            "BTCUSDT",
            connection_id="bin-ws-api",
        )

        assert publication is not None
        assert publication["quality"] == "EXPLOITABLE"
        assert publication["sequence"] == 103
        assert publication["best_bid"] == 100.0
        assert publication["best_ask"] == 101.5
        health = collector.health()
        assert health["ws_api_snapshots_received"] == 1
        assert health["ws_api_failures"] == 0
        assert health["full_snapshot_unavailable_symbols"] == []
        assert health["rest_unavailable_symbols"] == ["BTCUSDT"]
        assert health["clock_sync"]["clock_offset_ms"] == 0.0
        assert health["clock_sync"]["clock_probe_rtt_ms"] == 20.0
        assert (
            health["clock_sync"]["clock_probe_source"]
            == "websocket_api_depth_roundtrip"
        )
        raw = [tick for tick in ticks if tick.channel == "l2Book_snapshot"]
        assert len(raw) == 1
        assert raw[0].provenance["snapshot_source"] == "websocket_api"
        assert raw[0].provenance["transport"] == "websocket"
        assert publications[-1][0] == "BTCUSDT"
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

        async def failing_ws_api_snapshot(_symbol: str):
            raise OSError("WS API unavailable")

        collector._fetch_ws_api_snapshot = failing_ws_api_snapshot
        assert await collector.resync_symbol("BTCUSDT", connection_id="bin-partial") is None
        health = collector.health()
        assert "BTCUSDT" in health["rest_unavailable_symbols"]
        assert "BTCUSDT" in health["full_snapshot_unavailable_symbols"]
        assert health["ws_api_failures"] == 1
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
        rest_calls = 0
        ws_calls = 0

        async def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal rest_calls
            rest_calls += 1
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

        async def failing_ws_api_snapshot(_symbol: str):
            nonlocal ws_calls
            ws_calls += 1
            raise OSError("temporary WS API failure")

        collector._fetch_ws_api_snapshot = failing_ws_api_snapshot

        assert await collector.resync_symbol("BTCUSDT", connection_id="cooldown") is None
        assert rest_calls == 1
        assert ws_calls == 1
        assert "BTCUSDT" in collector.health()["rest_retry_deferred_symbols"]

        # A second resync remains allowed immediately, but skips the blocked REST
        # endpoint and retries the public WebSocket API instead.
        assert await collector.resync_symbol("BTCUSDT", connection_id="cooldown") is None
        assert rest_calls == 1
        assert ws_calls == 2
        await client.aclose()

    asyncio.run(scenario())

def test_ws_api_error_status_is_not_masked_by_null_response_id(monkeypatch) -> None:
    class FakeSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send(self, raw: str) -> None:
            request = json.loads(raw)
            assert request["method"] == "depth"
            assert request["params"]["symbol"] == "BTCUSDT"

        async def recv(self) -> str:
            return json.dumps(
                {
                    "id": None,
                    "status": 451,
                    "error": {
                        "code": 0,
                        "msg": "restricted location",
                    },
                }
            )

    monkeypatch.setattr(
        "hl_observer.collection.binance_depth_live.websockets.connect",
        lambda *_args, **_kwargs: FakeSocket(),
    )
    collector = BinanceDepthLiveCollector(["BTCUSDT"])

    async def scenario() -> None:
        try:
            await collector._fetch_ws_api_snapshot("BTCUSDT")
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected Binance WS API error")
        assert "BINANCE_WS_API_DEPTH_STATUS_451" in message
        assert "restricted location" in message
        assert "ID_MISMATCH" not in message
        await collector.close()

    asyncio.run(scenario())

def test_ws_api_valid_depth_response_accepts_non_echoed_id(monkeypatch) -> None:
    sent = {}

    class FakeSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send(self, raw: str) -> None:
            request = json.loads(raw)
            sent.update(request)
            assert request["method"] == "depth"
            assert request["params"] == {"symbol": "BTCUSDT", "limit": 1000}

        async def recv(self) -> str:
            return json.dumps(
                {
                    "id": "51e2affb-0aba-4821-ba75-f2625006eb43",
                    "status": 200,
                    "result": {
                        "lastUpdateId": 1027024,
                        "E": 1589436922972,
                        "T": 1589436922959,
                        "bids": [["4.00000000", "431.00000000"]],
                        "asks": [["4.00000200", "12.00000000"]],
                    },
                    "rateLimits": [],
                }
            )

    monkeypatch.setattr(
        "hl_observer.collection.binance_depth_live.websockets.connect",
        lambda *_args, **_kwargs: FakeSocket(),
    )
    collector = BinanceDepthLiveCollector(["BTCUSDT"])

    async def scenario() -> None:
        payload, sent_ms, received_ms, received_mono_ns = (
            await collector._fetch_ws_api_snapshot("BTCUSDT")
        )
        assert payload["lastUpdateId"] == 1027024
        assert payload["bids"][0][0] == "4.00000000"
        assert sent_ms > 0
        assert received_ms >= sent_ms
        assert received_mono_ns > 0
        request_id = str(sent["id"])
        assert len(request_id) == 32
        assert all(char in "0123456789abcdef" for char in request_id)
        assert request_id != "51e2affb-0aba-4821-ba75-f2625006eb43"
        await collector.close()

    asyncio.run(scenario())

