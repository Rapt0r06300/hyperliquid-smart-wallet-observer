from __future__ import annotations

import pytest

from hl_observer.collection.native_market_tape import native_tick_envelopes


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


def test_bitget_reverse_timestamp_batch_preserves_identity():
    source = {
        "arg": {"channel": "trade", "instId": "BTCUSDT"},
        "data": [
            {"tradeId": "later", "ts": "1992"},
            {"tradeId": "middle", "ts": "1991"},
            {"tradeId": "earlier", "ts": "1990"},
        ],
        "_alina_transport": _transport(),
    }
    events = native_tick_envelopes("bitget", source)
    assert [e.exchange_ts_ms for e in events] == [1990, 1991, 1992]
    assert [e.raw_payload["data"][0]["tradeId"] for e in events] == [
        "earlier", "middle", "later",
    ]
    assert [e.parsed_summary["source_batch_index"] for e in events] == [2, 1, 0]
    assert [e.parsed_summary["source_batch_chronological_index"] for e in events] == [0, 1, 2]
    assert len({e.parsed_summary["source_batch_sha256"] for e in events}) == 1
    assert source["data"][0]["tradeId"] == "later"


def test_bitget_missing_native_timestamp_does_not_get_fabricated_order():
    source = {
        "arg": {"channel": "trade", "instId": "BTCUSDT"},
        "data": [
            {"tradeId": "a", "ts": "1992"},
            {"tradeId": "b"},
            {"tradeId": "c", "ts": "1990"},
        ],
        "_alina_transport": _transport(),
    }
    events = native_tick_envelopes("bitget", source)
    assert [e.raw_payload["data"][0]["tradeId"] for e in events] == ["a", "b", "c"]
    assert all(e.parsed_summary["source_batch_chronology"] == "UNKNOWN" for e in events)
    assert all(e.parsed_summary["data_gate_ready"] is False for e in events)

