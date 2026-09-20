from __future__ import annotations

from pathlib import Path

from hl_observer.collection.native_venue_market import NativeMarketSnapshot
from hl_observer.ops.collecteur_registry import (
    COLLECTEURS_CORE,
    COLLECTEURS_HARVEST,
    REGISTRE,
)
from tools.collecter_native_venues import (
    RecordingNativeVenueCoordinator,
    envelope_from_snapshot,
    snapshot_summary,
)


def test_native_venues_is_harvest_not_core() -> None:
    assert "native-venues" in COLLECTEURS_HARVEST
    assert "native-venues" not in COLLECTEURS_CORE
    row = next(item for item in REGISTRE if item["nom"] == "native-venues")
    assert row["script"] == "tools/collecter_native_venues.py"
    assert row["heartbeat"] == "runtime/data/native_venues_heartbeat.json"


def test_snapshot_summary_is_explicitly_read_only() -> None:
    snap = NativeMarketSnapshot.build(
        venue="bybit",
        coin="BTC",
        exchange_symbol="BTCUSDT",
        bid=100.0,
        ask=100.1,
        exchange_ts_ms=1_700_000_000_000,
        receive_ts_ms=1_700_000_000_010,
        now_ms=1_700_000_000_010,
    )
    summary = snapshot_summary(snap)
    assert summary["venue"] == "bybit"
    assert summary["coin"] == "BTC"
    assert summary["mid"] > 0
    assert summary["read_only"] is True
    assert summary["real_execution"] is False

    envelope = envelope_from_snapshot(
        snap,
        {"topic": "orderbook.1.BTCUSDT", "type": "snapshot"},
        monotonic_ns=123,
    )
    record = envelope.as_record(written_ts_ms=1_700_000_000_020)
    assert record["source_id"] == "bybit_public_readonly"
    assert record["local_monotonic_ns"] == 123
    assert record["read_only"] is True
    assert record["real_execution"] is False


def test_recording_coordinator_emits_normalized_bybit_snapshot() -> None:
    captured = []
    coordinator = RecordingNativeVenueCoordinator(
        on_snapshot=captured.append,
        ccxt_snapshot_path=None,
        stale_after_ms=1_000,
    )
    payload = {
        "topic": "orderbook.50.BTCUSDT",
        "type": "snapshot",
        "ts": 1_700_000_000_010,
        "data": {
            "s": "BTCUSDT",
            "b": [["65000.0", "2.5"]],
            "a": [["65001.0", "1.5"]],
            "u": 42,
            "seq": 100,
            "cts": 1_700_000_000_000,
        },
    }
    snap = coordinator.ingest_bybit(
        payload,
        receive_ts_ms=1_700_000_000_015,
        now_ms=1_700_000_000_015,
    )
    assert snap is not None
    assert snap.venue == "bybit"
    assert captured
    record = captured[0].as_record(written_ts_ms=1_700_000_000_020)
    assert record["parsed_summary"]["bid"] == 65000.0
    assert record["parsed_summary"]["ask"] == 65001.0


def test_native_collector_has_no_execution_surface() -> None:
    text = Path("tools/collecter_native_venues.py").read_text(encoding="utf-8").lower()
    assert "/exchange" not in text
    assert "private_key" not in text
    assert "place_order" not in text
    assert "cancel_order" not in text
