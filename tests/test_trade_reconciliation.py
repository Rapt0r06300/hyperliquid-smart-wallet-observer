from __future__ import annotations

import asyncio
import gzip
import json

import httpx

from hl_observer.collection.trade_reconciliation import (
    HyperliquidTradeReferenceSampler,
    live_trade_ids,
    safe_hyperliquid_reference_interval_s,
    reconcile_binance_aggtrade_shard,
    reconcile_bybit_trade_shard,
    reconcile_okx_trade_shard,
)


def _write_shard(path, *, venue: str, rows: list[dict]) -> None:
    if venue == "bybit":
        raw = {
            "topic": "publicTrade.BTCUSDT",
            "data": [
                {
                    "i": row["id"],
                    "T": row["ts"],
                    "s": "BTCUSDT",
                    "p": "100",
                    "v": "1",
                }
                for row in rows
            ],
        }
    elif venue == "binance":
        # One aggregate trade per envelope, matching collect_cloud_window.
        raw = {
            "e": "aggTrade",
            "s": "BTCUSDT",
            "a": rows[0]["id"],
            "T": rows[0]["ts"],
            "p": "100",
            "q": "1",
            "f": rows[0]["id"],
            "l": rows[0]["id"],
            "m": False,
        }
    else:
        raw = {
            "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "tradeId": row["id"],
                    "ts": str(row["ts"]),
                    "instId": "BTC-USDT-SWAP",
                    "px": "100",
                    "sz": "1",
                }
                for row in rows
            ],
        }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"raw_payload": raw}) + "\n")


def test_live_trade_ids_extracts_exact_exchange_ids(tmp_path) -> None:
    path = tmp_path / "bybit.jsonl.gz"
    _write_shard(
        path,
        venue="bybit",
        rows=[{"id": "a", "ts": 1000}, {"id": "b", "ts": 1010}],
    )
    ids, count = live_trade_ids(path, venue="bybit")
    assert ids == {"a", "b"}
    assert count == 2


def test_bybit_exact_match_requires_reference_to_cover_window_start(tmp_path) -> None:
    path = tmp_path / "bybit.jsonl.gz"
    _write_shard(
        path,
        venue="bybit",
        rows=[{"id": "a", "ts": 1000}, {"id": "b", "ts": 1010}],
    )

    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [
                            {"execId": "b", "time": "1010"},
                            {"execId": "a", "time": "1000"},
                            {"execId": "old", "time": "900"},
                        ]
                    },
                },
            )

        client = httpx.AsyncClient(
            base_url="https://api.bybit.com",
            transport=httpx.MockTransport(handler),
        )
        report = await reconcile_bybit_trade_shard(
            path,
            symbol="BTCUSDT",
            start_ms=1000,
            end_ms=1020,
            client=client,
        )
        await client.aclose()
        assert report["status"] == "MATCHED"
        assert report["matched_count"] == 2
        assert report["missing_from_live"] == 0
        assert report["live_only"] == 0

    asyncio.run(scenario())


def test_bybit_truncated_reference_stays_partial(tmp_path) -> None:
    path = tmp_path / "bybit.jsonl.gz"
    _write_shard(path, venue="bybit", rows=[{"id": "a", "ts": 1000}])

    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "retCode": 0,
                    "result": {
                        "list": [
                            {"execId": "new", "time": "1100"},
                            {"execId": "a", "time": "1050"},
                        ]
                    },
                },
            )

        client = httpx.AsyncClient(
            base_url="https://api.bybit.com",
            transport=httpx.MockTransport(handler),
        )
        report = await reconcile_bybit_trade_shard(
            path,
            symbol="BTCUSDT",
            start_ms=1000,
            end_ms=1100,
            client=client,
        )
        await client.aclose()
        assert report["status"] == "PARTIAL"
        assert report["reason"] == "REFERENCE_DOES_NOT_COVER_WINDOW_START"

    asyncio.run(scenario())


def test_okx_paginates_until_window_start_then_matches(tmp_path) -> None:
    path = tmp_path / "okx.jsonl.gz"
    _write_shard(
        path,
        venue="okx",
        rows=[{"id": "a", "ts": 1050}, {"id": "b", "ts": 1080}],
    )

    async def scenario() -> None:
        calls = []

        async def handler(request: httpx.Request) -> httpx.Response:
            cursor = int(request.url.params["after"])
            calls.append(cursor)
            if len(calls) == 1:
                data = [
                    {"tradeId": "b", "ts": "1080"},
                    {"tradeId": "a", "ts": "1050"},
                ]
            else:
                data = [{"tradeId": "old", "ts": "900"}]
            return httpx.Response(200, json={"code": "0", "msg": "", "data": data})

        client = httpx.AsyncClient(
            base_url="https://www.okx.com",
            transport=httpx.MockTransport(handler),
        )
        report = await reconcile_okx_trade_shard(
            path,
            symbol="BTC-USDT-SWAP",
            start_ms=1000,
            end_ms=1100,
            client=client,
        )
        await client.aclose()
        assert len(calls) == 2
        assert report["status"] == "MATCHED"
        assert report["matched_count"] == 2

    asyncio.run(scenario())


def test_reference_mismatch_is_explicit(tmp_path) -> None:
    path = tmp_path / "bybit.jsonl.gz"
    _write_shard(path, venue="bybit", rows=[{"id": "live-only", "ts": 1000}])

    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "retCode": 0,
                    "result": {
                        "list": [
                            {"execId": "ref-only", "time": "1000"},
                            {"execId": "old", "time": "900"},
                        ]
                    },
                },
            )

        client = httpx.AsyncClient(
            base_url="https://api.bybit.com",
            transport=httpx.MockTransport(handler),
        )
        report = await reconcile_bybit_trade_shard(
            path,
            symbol="BTCUSDT",
            start_ms=1000,
            end_ms=1010,
            client=client,
        )
        await client.aclose()
        assert report["status"] == "MISMATCH"
        assert report["missing_from_live"] == 1
        assert report["live_only"] == 1

    asyncio.run(scenario())


def test_live_trade_ids_parses_canonical_raw_payload_text(tmp_path) -> None:
    path = tmp_path / "okx-canonical.jsonl.gz"
    raw = {
        "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
        "data": [
            {"tradeId": "9001", "ts": "1000", "instId": "BTC-USDT-SWAP"},
            {"tradeId": "9002", "ts": "1010", "instId": "BTC-USDT-SWAP"},
        ],
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"raw_payload": json.dumps(raw, separators=(",", ":"))}) + "\n")
    ids, count = live_trade_ids(path, venue="okx")
    assert ids == {"9001", "9002"}
    assert count == 2


def test_binance_aggtrade_ids_are_extracted_from_raw_envelopes(tmp_path) -> None:
    path = tmp_path / "binance.jsonl.gz"
    _write_shard(path, venue="binance", rows=[{"id": 10, "ts": 1000}])
    ids, count = live_trade_ids(path, venue="binance")
    assert ids == {"10"}
    assert count == 1


def test_binance_aggtrade_exact_rest_match(tmp_path) -> None:
    path = tmp_path / "binance.jsonl.gz"
    # Write two envelopes because Binance aggregate stream emits one event/frame.
    _write_shard(path, venue="binance", rows=[{"id": 10, "ts": 1000}])
    with gzip.open(path, "at", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "raw_payload": {
                        "e": "aggTrade",
                        "s": "BTCUSDT",
                        "a": 11,
                        "T": 1010,
                        "p": "100",
                        "q": "1",
                        "f": 11,
                        "l": 11,
                        "m": False,
                    }
                }
            )
            + "\n"
        )

    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/fapi/v1/aggTrades"
            return httpx.Response(
                200,
                json=[
                    {"a": 10, "T": 1000, "p": "100", "q": "1"},
                    {"a": 11, "T": 1010, "p": "100", "q": "1"},
                ],
            )

        client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        report = await reconcile_binance_aggtrade_shard(
            path,
            symbol="BTCUSDT",
            start_ms=1000,
            end_ms=1020,
            client=client,
            throttle_s=0,
        )
        await client.aclose()
        assert report["status"] == "MATCHED"
        assert report["matched_count"] == 2
        assert report["reference_coverage"] == "EXPLICIT_BOUNDED_REST_WINDOW"

    asyncio.run(scenario())


def test_binance_full_reference_page_is_split_before_match(tmp_path) -> None:
    path = tmp_path / "binance.jsonl.gz"
    _write_shard(path, venue="binance", rows=[{"id": 10, "ts": 1000}])
    with gzip.open(path, "at", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "raw_payload": {
                        "e": "aggTrade",
                        "s": "BTCUSDT",
                        "a": 11,
                        "T": 1020,
                        "p": "100",
                        "q": "1",
                        "f": 11,
                        "l": 11,
                        "m": False,
                    }
                }
            )
            + "\n"
        )

    async def scenario() -> None:
        calls = []

        async def handler(request: httpx.Request) -> httpx.Response:
            left = int(request.url.params["startTime"])
            right = int(request.url.params["endTime"])
            calls.append((left, right))
            if left == 1000 and right == 1020:
                # Saturated page proves only that this interval needs refinement.
                return httpx.Response(
                    200,
                    json=[
                        {"a": 10, "T": 1000},
                        {"a": 11, "T": 1020},
                    ],
                )
            if right <= 1010:
                return httpx.Response(200, json=[{"a": 10, "T": 1000}])
            return httpx.Response(200, json=[{"a": 11, "T": 1020}])

        client = httpx.AsyncClient(
            base_url="https://fapi.binance.com",
            transport=httpx.MockTransport(handler),
        )
        report = await reconcile_binance_aggtrade_shard(
            path,
            symbol="BTCUSDT",
            start_ms=1000,
            end_ms=1020,
            client=client,
            limit=2,
            throttle_s=0,
        )
        await client.aclose()
        assert len(calls) == 3
        assert report["status"] == "MATCHED"
        assert report["matched_count"] == 2

    asyncio.run(scenario())


def test_hyperliquid_reference_sampler_scales_poll_interval_to_ip_weight_budget() -> None:
    assert safe_hyperliquid_reference_interval_s(1, 5.0) == 5.0
    assert safe_hyperliquid_reference_interval_s(3, 5.0) == 8.0
    assert safe_hyperliquid_reference_interval_s(6, 5.0) == 15.0
    assert safe_hyperliquid_reference_interval_s(12, 5.0) == 30.0

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=[])))
    sampler = HyperliquidTradeReferenceSampler(
        ["BTC", "ETH", "SOL", "HYPE", "AAVE", "ADA"],
        interval_s=5.0,
        client=client,
    )
    stats = sampler.stats()
    assert stats["requested_interval_s"] == 5.0
    assert stats["effective_interval_s"] == 15.0
    assert stats["estimated_base_weight_per_min"] <= stats["base_weight_budget_per_min"]
    asyncio.run(client.aclose())


def test_hyperliquid_reference_sampler_matches_exact_tids_from_canonical_shard(tmp_path) -> None:
    path = tmp_path / "hl.jsonl.gz"
    raw = {
        "channel": "trades",
        "data": [
            {"coin": "BTC", "tid": 101, "time": 1000, "px": "100", "sz": "1"},
            {"coin": "BTC", "tid": 102, "time": 1010, "px": "101", "sz": "2"},
        ],
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"raw_payload": json.dumps(raw, separators=(",", ":"))}
            )
            + "\n"
        )

    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            assert body == {"type": "recentTrades", "coin": "BTC"}
            return httpx.Response(
                200,
                json=[
                    {"coin": "BTC", "tid": 99, "time": 900},
                    {"coin": "BTC", "tid": 101, "time": 1000},
                    {"coin": "BTC", "tid": 102, "time": 1010},
                    {"coin": "BTC", "tid": 103, "time": 1100},
                ],
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        sampler = HyperliquidTradeReferenceSampler(
            ["BTC"],
            client=client,
            interval_s=1.0,
        )
        await sampler.sample_once()
        report = sampler.reconcile(
            path,
            symbol="BTC",
            start_ms=1000,
            end_ms=1010,
        )
        assert report["status"] == "MATCHED"
        assert report["matched_count"] == 2
        assert report["missing_from_live"] == 0
        assert report["live_only"] == 0
        assert sampler.stats()["reference_trade_ids"]["BTC"] == 4
        await client.aclose()

    asyncio.run(scenario())


def test_hyperliquid_reference_sampler_fails_closed_without_window_coverage(tmp_path) -> None:
    path = tmp_path / "hl-partial.jsonl.gz"
    raw = {
        "channel": "trades",
        "data": [{"coin": "BTC", "tid": 101, "time": 1000}],
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"raw_payload": json.dumps(raw)}) + "\n")

    async def scenario() -> None:
        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {"coin": "BTC", "tid": 101, "time": 1000},
                    {"coin": "BTC", "tid": 102, "time": 1005},
                ],
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        sampler = HyperliquidTradeReferenceSampler(["BTC"], client=client)
        await sampler.sample_once()
        report = sampler.reconcile(
            path,
            symbol="BTC",
            start_ms=900,
            end_ms=1010,
        )
        assert report["status"] == "PARTIAL"
        assert report["reason"] == "REFERENCE_DOES_NOT_COVER_WINDOW"
        await client.aclose()

    asyncio.run(scenario())
