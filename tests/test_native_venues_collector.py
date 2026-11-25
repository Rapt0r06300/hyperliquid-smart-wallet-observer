from __future__ import annotations

import asyncio
from types import SimpleNamespace
from pathlib import Path

import pytest

from hl_observer.collection.native_venue_market import NativeMarketSnapshot
from hl_observer.collection.tick_dataset import TickEnvelope
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
from tools import collecter_native_venues as native_module


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
        clock_domain_id="test-clock-domain",
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
    assert record["parsed_summary"]["clock_domain_id"] == "test-clock-domain"


def test_native_collector_has_no_execution_surface() -> None:
    text = Path("tools/collecter_native_venues.py").read_text(encoding="utf-8").lower()
    assert "/exchange" not in text
    assert "private_key" not in text
    assert "place_order" not in text
    assert "cancel_order" not in text


def test_native_runner_publishes_canonical_harvest_heartbeat() -> None:
    text = Path("tools/collecter_native_venues.py").read_text(encoding="utf-8")
    assert 'HB.battre(' in text
    assert '"native-venues"' in text
    assert 'venue for venue in ("bybit", "okx") if venue in enabled_venues' in text
    assert '"required_venues_ready"' in text
    assert '"queue_estimated_bytes"' in text
    assert '"queue_oversized_drops"' in text
    assert "counts.get(venue, 0) > 0" in text
    assert "last_event_ms.get(venue, 0) > 0" in text
    assert "final_health = coordinator.health" in text
    assert '"coordinator_health": final_health' in text

def test_native_final_heartbeat_preserves_coordinator_health() -> None:
    text = Path("tools/collecter_native_venues.py").read_text(encoding="utf-8")
    assert "final_health = coordinator.health(" in text
    final_block = text.split("final = {", 1)[1]
    assert '"coordinator_health": final_health' in final_block

def test_native_heartbeat_exposes_per_channel_counts() -> None:
    text = Path("tools/collecter_native_venues.py").read_text(encoding="utf-8")
    assert "channel_counts: dict[str, dict[str, int]]" in text
    assert 'venue_counts[channel] = int(venue_counts.get(channel, 0)) + 1' in text
    assert '"channel_counts": {' in text


@pytest.mark.parametrize("reject_queue_event", [False, True])
def test_native_enqueue_records_each_envelope_once(
    monkeypatch, tmp_path, capsys, reject_queue_event
) -> None:
    class FakeCoordinator:
        def __init__(self, *, on_snapshot, **_kwargs):
            self.on_snapshot = on_snapshot
            self.bybit_client = SimpleNamespace(
                last_instrument_metadata=(),
                rest_base_url="https://api.bybit.com",
            )
            self.emitted = False

        def discover(self):
            return ["BTCUSDT"]

        def refresh_clock_sync(self):
            return None

        def symbols_for(self, venue):
            return ("BTCUSDT",) if venue == "bybit" else ()

        async def run_bybit(self):
            if not self.emitted:
                self.emitted = True
                now_ms = 1_700_000_000_000
                self.on_snapshot(TickEnvelope(
                    source_id="bybit_public_readonly",
                    channel="orderbook_snapshot",
                    instrument="BTCUSDT",
                    event_kind="L2_SNAPSHOT",
                    raw_payload='{"test":"real-shape"}',
                    received_ts_ms=now_ms,
                    exchange_ts_ms=now_ms,
                ))
            await asyncio.sleep(60)

        async def run_clock_sync(self):
            await asyncio.sleep(60)

        def health(self, *, now_ms):
            return {"checked_at_ms": now_ms}

    class FakeWriter:
        def __init__(self, *_args, **_kwargs):
            self.rows = []

        def append_batch(self, rows):
            self.rows.extend(rows)
            return len(rows)

        def rotate_all(self):
            return None

        def stats(self):
            return {"rows": len(self.rows)}

    writer = FakeWriter()
    heartbeats = []

    class RejectingQueue:
        max_estimated_bytes = 1
        estimated_bytes = 0

        def __init__(self, **_kwargs):
            pass

        def __len__(self):
            return 0

        def append(self, envelope, *, on_drop):
            on_drop(envelope)
            return False

        def pop_batch(self, **_kwargs):
            return []

    if reject_queue_event:
        monkeypatch.setattr(
            native_module, "BoundedTickEnvelopeQueue", RejectingQueue
        )
    monkeypatch.setattr(native_module, "RecordingNativeVenueCoordinator", FakeCoordinator)
    monkeypatch.setattr(native_module, "PartitionedTickDatasetWriter", lambda *a, **k: writer)
    monkeypatch.setattr(native_module, "build_bundle", lambda *a, **k: {})
    monkeypatch.setattr(
        native_module,
        "_atomic_json",
        lambda _path, payload, **_kwargs: heartbeats.append(payload),
    )
    monkeypatch.setattr(native_module.HB, "battre", lambda *a, **k: None)
    monkeypatch.setattr(native_module, "fetch_bybit_funding_settlements", _async_empty)

    result = asyncio.run(native_module._run(
        tmp_path,
        max_symbols=1,
        stale_after_ms=1_000,
        duration_s=0.01,
        universe_refresh_s=0,
        enabled_venues=("bybit",),
    ))

    assert result == 0
    assert len(writer.rows) == (0 if reject_queue_event else 1)
    assert heartbeats
    final = heartbeats[-1]
    assert final["required_venues_ready"] is (not reject_queue_event)
    assert final["channel_counts"]["bybit"].get("orderbook_snapshot", 0) == (
        0 if reject_queue_event else 1
    )
    assert final["last_event_ms"]["bybit"] == (
        0 if reject_queue_event else 1_700_000_000_000
    )
    assert "bybit reconnect #1" not in capsys.readouterr().out


async def _async_empty(*_args, **_kwargs):
    return []

