from __future__ import annotations

import importlib.util
from enum import Enum
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]
realtime_package = types.ModuleType("hl_observer.realtime")
realtime_package.__path__ = [str(ROOT / "src" / "hl_observer" / "realtime")]
sys.modules["hl_observer.realtime"] = realtime_package
feed_quality = types.ModuleType("hl_observer.realtime.feed_quality")


class FeedEventKind(str, Enum):
    SNAPSHOT = "SNAPSHOT"
    INCREMENTAL = "INCREMENTAL"
    EVENT = "EVENT"


feed_quality.FeedEventKind = FeedEventKind
sys.modules["hl_observer.realtime.feed_quality"] = feed_quality
collection_package = types.ModuleType("hl_observer.collection")
collection_package.__path__ = [str(ROOT / "src" / "hl_observer" / "collection")]
sys.modules["hl_observer.collection"] = collection_package
for module_name in ("tick_dataset", "native_market_tape"):
    qualified = f"hl_observer.collection.{module_name}"
    spec = importlib.util.spec_from_file_location(
        qualified,
        ROOT / "src" / "hl_observer" / "collection" / f"{module_name}.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)

native_tick_envelopes = sys.modules[
    "hl_observer.collection.native_market_tape"
].native_tick_envelopes


def _transport() -> dict[str, object]:
    return {
        "connection_id": "batch-test",
        "receive_wall_ts_ms": 2_000,
        "receive_mono_ns": 123_456,
    }


@pytest.mark.parametrize(
    ("venue", "payload", "rows_key", "identity_key", "identities"),
    [
        (
            "bybit",
            {
                "topic": "publicTrade.BTCUSDT",
                "data": [
                    {"i": "bybit-1", "s": "BTCUSDT", "T": 1_990, "p": "100", "v": "1"},
                    {"i": "bybit-2", "s": "BTCUSDT", "T": 1_991, "p": "101", "v": "2"},
                ],
                "_alina_transport": _transport(),
            },
            "data",
            "i",
            ["bybit-1", "bybit-2"],
        ),
        (
            "okx",
            {
                "arg": {"channel": "trades-all", "instId": "BTC-USDT-SWAP"},
                "data": [
                    {"tradeId": "okx-1", "instId": "BTC-USDT-SWAP", "ts": "1990"},
                    {"tradeId": "okx-2", "instId": "BTC-USDT-SWAP", "ts": "1991"},
                ],
                "_alina_transport": _transport(),
            },
            "data",
            "tradeId",
            ["okx-1", "okx-2"],
        ),
        (
            "gate",
            {
                "channel": "futures.trades",
                "event": "update",
                "result": [
                    {"id": "gate-1", "contract": "BTC_USDT", "create_time_ms": 1_990},
                    {"id": "gate-2", "contract": "BTC_USDT", "create_time_ms": 1_991},
                ],
                "_alina_transport": _transport(),
            },
            "result",
            "id",
            ["gate-1", "gate-2"],
        ),
        (
            "bitget",
            {
                "arg": {"channel": "trade", "instId": "BTCUSDT"},
                "data": [
                    {"tradeId": "bitget-1", "instId": "BTCUSDT", "ts": "1990"},
                    {"tradeId": "bitget-2", "instId": "BTCUSDT", "ts": "1991"},
                ],
                "_alina_transport": _transport(),
            },
            "data",
            "tradeId",
            ["bitget-1", "bitget-2"],
        ),
    ],
)
def test_native_trade_batches_preserve_every_trade_exactly_once(
    venue, payload, rows_key, identity_key, identities
):
    envelopes = native_tick_envelopes(venue, payload)

    assert len(envelopes) == 2
    assert [row.parsed_summary["source_batch_index"] for row in envelopes] == [0, 1]
    assert {row.parsed_summary["source_batch_size"] for row in envelopes} == {2}
    assert len({row.parsed_summary["source_batch_sha256"] for row in envelopes}) == 1
    assert [
        row.raw_payload[rows_key][0][identity_key] for row in envelopes
    ] == identities
    assert all(len(row.raw_payload[rows_key]) == 1 for row in envelopes)
