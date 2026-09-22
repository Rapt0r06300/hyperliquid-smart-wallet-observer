from __future__ import annotations

import asyncio
import gzip
import json

import httpx

from hl_observer.collection.trade_reconciliation import (
    live_trade_ids,
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
