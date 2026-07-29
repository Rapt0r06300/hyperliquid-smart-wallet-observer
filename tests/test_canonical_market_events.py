from __future__ import annotations

import hashlib
import json

from hl_observer.normalization.market_events import (
    CanonicalEventWriter,
    canonicalize_tick_record,
)


def _tick_record(*, gate_ready: bool = True, channel: str = "bbo") -> dict:
    raw = json.dumps({"channel": channel, "data": {"coin": "BTC"}})
    return {
        "schema_version": "hypersmart.tick.v1",
        "source_id": "hyperliquid_mainnet_readonly",
        "channel": channel,
        "instrument": "BTC",
        "event_kind": "SNAPSHOT",
        "exchange_ts_ms": 900,
        "received_ts_ms": 1_000,
        "written_ts_ms": 1_010,
        "raw_payload": raw,
        "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "parsed_summary": {
            "feed_quality_score": 96.5,
            "data_gate_ready": gate_ready,
        },
        "provenance": {"access": "read_only", "network": "mainnet"},
    }


def test_canonical_event_uses_durable_observable_time_and_tick_reference() -> None:
    result = canonicalize_tick_record(_tick_record())
    assert result.accepted
    assert result.event is not None
    assert result.event.observable_at_ms == 1_010
    assert result.event.exchange_ts_ms == 900
    assert result.event.source_tick_ref.startswith("tick:")
    assert result.event.signal_eligible
    assert result.event.data_gate_ready


def test_market_event_is_rejected_until_data_quality_gate_is_ready() -> None:
    result = canonicalize_tick_record(_tick_record(gate_ready=False))
    assert not result.accepted
    assert result.event is None
    assert "DATA_QUALITY_GATE_NOT_READY" in result.reasons


def test_canonicalizer_detects_tampered_raw_payload() -> None:
    record = _tick_record()
    record["raw_payload"] = '{"tampered":true}'
    result = canonicalize_tick_record(record)
    assert not result.accepted
    assert "RAW_HASH_MISMATCH" in result.reasons


def test_canonical_writer_deduplicates_and_replays(tmp_path) -> None:
    event = canonicalize_tick_record(_tick_record()).event
    assert event is not None
    writer = CanonicalEventWriter(tmp_path / "canonical.jsonl")
    assert writer.append([event, event]) == 1
    assert writer.duplicates == 1
    [row] = list(writer.iter_events())
    assert row["event_id"] == event.event_id
    assert row["observable_at_ms"] == 1_010
