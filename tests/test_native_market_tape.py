from __future__ import annotations

from hl_observer.collection.native_market_tape import native_tick_envelope


def _transport() -> dict:
    return {
        "connection_id": "conn-1",
        "receive_wall_ts_ms": 2_000,
        "receive_mono_ns": 123_456,
        "transport_rtt_ms": 12.5,
        "clock_offset_ms": -3.0,
    }


def test_bybit_trade_batch_preserves_raw_and_matching_time() -> None:
    payload = {
        "topic": "publicTrade.BTCUSDT",
        "type": "snapshot",
        "ts": 1_999,
        "_alina_transport": _transport(),
        "data": [
            {
                "T": 1_990,
                "s": "BTCUSDT",
                "S": "Buy",
                "v": "0.1",
                "p": "100",
                "i": "trade-a",
                "seq": 10,
            },
            {
                "T": 1_995,
                "s": "BTCUSDT",
                "S": "Sell",
                "v": "0.2",
                "p": "101",
                "i": "trade-b",
                "seq": 10,
            },
        ],
    }
    envelope = native_tick_envelope("bybit", payload)
    assert envelope is not None
    assert envelope.channel == "trades"
    assert envelope.instrument == "BTCUSDT"
    assert envelope.exchange_ts_ms == 1_995
    assert envelope.received_ts_ms == 2_000
    assert envelope.local_monotonic_ns == 123_456
    assert envelope.sequence == 10
    assert envelope.parsed_summary["event_count"] == 2
    assert envelope.parsed_summary["data_gate_ready"] is False
    assert "_alina_transport" not in envelope.raw_payload


def test_bybit_liquidations_are_kept_as_distinct_family() -> None:
    envelope = native_tick_envelope(
        "bybit",
        {
            "topic": "allLiquidation.ETHUSDT",
            "type": "snapshot",
            "ts": 1_999,
            "_alina_transport": _transport(),
            "data": [
                {
                    "T": 1_995,
                    "s": "ETHUSDT",
                    "S": "Sell",
                    "v": "3",
                    "p": "2000",
                }
            ],
        },
    )
    assert envelope is not None
    assert envelope.channel == "liquidations"
    assert envelope.instrument == "ETHUSDT"
    assert envelope.exchange_ts_ms == 1_995


def test_okx_trade_frame_carries_sequence_and_provenance() -> None:
    envelope = native_tick_envelope(
        "okx",
        {
            "arg": {"channel": "trades", "instId": "BTC-USDT-SWAP"},
            "_alina_transport": _transport(),
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "tradeId": "42",
                    "px": "100",
                    "sz": "1",
                    "side": "buy",
                    "ts": "1995",
                    "seqId": 77,
                }
            ],
        },
    )
    assert envelope is not None
    assert envelope.channel == "trades"
    assert envelope.sequence == 77
    assert envelope.provenance["access"] == "read_only"
    assert envelope.provenance["authenticated"] is False


def test_native_tape_refuses_frame_without_receive_clock() -> None:
    assert (
        native_tick_envelope(
            "bybit",
            {
                "topic": "publicTrade.BTCUSDT",
                "data": [{"T": 1_000, "s": "BTCUSDT", "seq": 1}],
            },
        )
        is None
    )


def test_okx_index_price_is_taped() -> None:
    envelope = native_tick_envelope(
        "okx",
        {
            "arg": {"channel": "index-tickers", "instId": "BTC-USDT-SWAP"},
            "data": [{"instId": "BTC-USDT-SWAP", "idxPx": "65000", "ts": "1700000000000"}],
            "_alina_transport": {
                "receive_wall_ts_ms": 1700000000010,
                "receive_mono_ns": 123,
                "connection_id": "okx-1",
            },
        },
    )
    assert envelope is not None
    record = envelope.as_record(written_ts_ms=1700000000020)
    assert record["channel"] == "index_price"
    assert record["instrument"] == "BTC-USDT-SWAP"


def test_okx_instrument_rule_change_is_taped() -> None:
    envelope = native_tick_envelope(
        "okx",
        {
            "arg": {"channel": "instruments", "instType": "SWAP"},
            "data": [
                {
                    "instType": "SWAP",
                    "instId": "BTC-USDT-SWAP",
                    "tickSz": "0.1",
                    "lotSz": "0.01",
                    "minSz": "0.01",
                    "state": "live",
                    "ts": "1700000000000",
                }
            ],
            "_alina_transport": {
                "receive_wall_ts_ms": 1700000000010,
                "receive_mono_ns": 123,
                "connection_id": "okx-1",
            },
        },
    )
    assert envelope is not None
    record = envelope.as_record(written_ts_ms=1700000000020)
    assert record["channel"] == "instrument_metadata"
    assert record["instrument"] == "BTC-USDT-SWAP"
    assert record["raw_payload"]["data"][0]["tickSz"] == "0.1"
