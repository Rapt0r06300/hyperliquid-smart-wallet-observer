from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "collect_cloud_window",
        ROOT / "tools" / "collect_cloud_window.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_hyperliquid_l2_frame_becomes_replay_tick() -> None:
    m = _module()
    tick = m._hyperliquid_envelope(
        {
            "channel": "l2Book",
            "data": {
                "coin": "BTC",
                "time": 1000,
                "levels": [
                    [{"px": "100", "sz": "1"}],
                    [{"px": "101", "sz": "2"}],
                ],
            },
        },
        received_ts_ms=1010,
        receive_mono_ns=123456,
        connection_id="hl-test",
    )
    assert tick is not None
    assert tick.source_id == "hyperliquid_public_ws"
    assert tick.channel == "l2Book"
    assert tick.instrument == "BTC"
    assert tick.exchange_ts_ms == 1000
    assert tick.received_ts_ms == 1010
    assert tick.local_monotonic_ns == 123456


def test_binance_bbo_keeps_update_id_and_transport_clock() -> None:
    m = _module()
    tick = m._binance_bbo_envelope(
        {
            "data": {
                "s": "BTCUSDT",
                "b": "100",
                "a": "101",
                "B": "2",
                "A": "3",
                "T": 1000,
                "u": 77,
            }
        },
        received_ts_ms=1010,
        receive_mono_ns=999,
        connection_id="bin-test",
    )
    assert tick is not None
    assert tick.channel == "bbo"
    assert tick.sequence == 77
    assert tick.exchange_ts_ms == 1000
    assert tick.connection_id == "bin-test"


def test_binance_trade_preserves_exchange_trade_id() -> None:
    m = _module()
    tick = m._binance_trade_envelope(
        {
            "data": {
                "e": "trade",
                "s": "ETHUSDT",
                "p": "2000",
                "q": "0.5",
                "T": 1000,
                "t": 123,
                "m": True,
            }
        },
        received_ts_ms=1005,
        receive_mono_ns=100,
        connection_id="bin-trade-test",
    )
    assert tick is not None
    assert tick.channel == "trades"
    assert tick.sequence == 123
    assert tick.parsed_summary["aggressor_side"] == "SELL"
