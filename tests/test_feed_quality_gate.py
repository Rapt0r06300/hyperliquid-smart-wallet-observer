from __future__ import annotations

from hl_observer.realtime.feed_quality import (
    FeedMode,
    FeedQualityConfig,
    FeedQualityGate,
)


def _config(**overrides: object) -> FeedQualityConfig:
    values: dict[str, object] = {
        "max_age_ms": 500,
        "heartbeat_max_age_ms": 1_000,
        "max_gap_ms": 2_000,
        "max_latency_ms": 500,
        "max_jitter_ms": 500,
        "min_coherent_events": 2,
        "min_score": 70,
    }
    values.update(overrides)
    return FeedQualityConfig(**values)


def _full_book_gate(**config: object) -> FeedQualityGate:
    return FeedQualityGate(
        source_id="hyperliquid_mainnet_readonly",
        channel="l2Book",
        instrument="BTC",
        mode=FeedMode.FULL_SNAPSHOT,
        config=_config(**config),
    )


def test_full_snapshot_feed_requires_coherent_snapshots_and_heartbeat() -> None:
    gate = _full_book_gate()
    gate.mark_heartbeat(received_ts_ms=1_010)

    first = gate.ingest_book_snapshot(
        bids=[{"px": "100", "sz": "2"}],
        asks=[{"px": "101", "sz": "3"}],
        exchange_ts_ms=1_000,
        received_ts_ms=1_010,
        event_id="book-1",
    )
    assert not first.ready
    assert first.synchronized is False

    second = gate.ingest_book_snapshot(
        bids=[{"px": "100.2", "sz": "2.5"}],
        asks=[{"px": "101.2", "sz": "3.5"}],
        exchange_ts_ms=1_020,
        received_ts_ms=1_030,
        event_id="book-2",
    )
    assert second.ready
    assert second.synchronized
    assert second.feed_quality_score >= 70
    assert gate.bids == {100.2: 2.5}
    assert gate.asks == {101.2: 3.5}


def test_incremental_feed_rejects_update_before_snapshot() -> None:
    gate = FeedQualityGate(
        source_id="test",
        channel="incremental-book",
        instrument="ETH",
        mode=FeedMode.SNAPSHOT_THEN_INCREMENTAL,
        config=_config(min_coherent_events=1),
    )
    gate.mark_heartbeat(received_ts_ms=1_000)
    rejected = gate.ingest_book_incremental(
        bid_updates=[("100", "1")],
        ask_updates=[("101", "1")],
        exchange_ts_ms=990,
        received_ts_ms=1_000,
        event_id="early",
        sequence=1,
    )
    assert not rejected.ready
    assert "INCREMENTAL_BEFORE_SNAPSHOT" in rejected.reasons

    gate.ingest_book_snapshot(
        bids=[("100", "1")],
        asks=[("101", "1")],
        exchange_ts_ms=1_010,
        received_ts_ms=1_020,
        event_id="snapshot",
        sequence=2,
    )
    accepted = gate.ingest_book_incremental(
        bid_updates=[("100", "0"), ("100.5", "2")],
        ask_updates=[],
        exchange_ts_ms=1_030,
        received_ts_ms=1_040,
        event_id="incremental",
        sequence=3,
    )
    gate.mark_heartbeat(received_ts_ms=1_040)
    accepted = gate.snapshot(now_ms=1_040)
    assert accepted.ready
    assert gate.bids == {100.5: 2.0}


def test_stale_duplicate_crossed_and_outlier_events_are_measured() -> None:
    gate = _full_book_gate(min_coherent_events=1)
    gate.mark_heartbeat(received_ts_ms=5_000)
    stale = gate.ingest_book_snapshot(
        bids=[("100", "1")],
        asks=[("101", "1")],
        exchange_ts_ms=1_000,
        received_ts_ms=5_000,
        event_id="stale",
    )
    assert not stale.ready
    assert stale.stale_events == 1
    assert "STALE_EVENT" in stale.reasons

    gate = _full_book_gate(min_coherent_events=1)
    gate.mark_heartbeat(received_ts_ms=1_010)
    gate.ingest_book_snapshot(
        bids=[("100", "1")],
        asks=[("101", "1")],
        exchange_ts_ms=1_000,
        received_ts_ms=1_010,
        event_id="same",
    )
    duplicate = gate.ingest_book_snapshot(
        bids=[("100", "1")],
        asks=[("101", "1")],
        exchange_ts_ms=1_020,
        received_ts_ms=1_030,
        event_id="same",
    )
    assert duplicate.duplicates == 1
    assert "DUPLICATE_EVENT" in duplicate.reasons

    crossed = gate.ingest_book_snapshot(
        bids=[("102", "1")],
        asks=[("101", "1")],
        exchange_ts_ms=1_040,
        received_ts_ms=1_050,
        event_id="crossed",
    )
    assert crossed.crossed_books == 1
    assert "CROSSED_OR_LOCKED_BOOK" in crossed.reasons


def test_reconnect_resets_readiness_until_a_new_coherent_baseline() -> None:
    gate = _full_book_gate()
    gate.mark_heartbeat(received_ts_ms=1_000)
    for index in range(2):
        gate.ingest_book_snapshot(
            bids=[("100", "1")],
            asks=[("101", "1")],
            exchange_ts_ms=990 + index * 10,
            received_ts_ms=1_000 + index * 10,
            event_id=f"before-{index}",
        )
    assert gate.snapshot(now_ms=1_010).ready

    gate.mark_reconnect(received_ts_ms=2_000, connection_id="hl-2")
    gate.mark_heartbeat(received_ts_ms=2_000)
    assert not gate.snapshot(now_ms=2_000).ready

    gate.ingest_book_snapshot(
        bids=[("100", "1")],
        asks=[("101", "1")],
        exchange_ts_ms=2_000,
        received_ts_ms=2_010,
        event_id="after-1",
    )
    assert not gate.snapshot(now_ms=2_010).ready
    gate.ingest_book_snapshot(
        bids=[("100.1", "1")],
        asks=[("101.1", "1")],
        exchange_ts_ms=2_020,
        received_ts_ms=2_030,
        event_id="after-2",
    )
    gate.mark_heartbeat(received_ts_ms=2_030)
    assert gate.snapshot(now_ms=2_030).ready


def test_event_stream_gap_blocks_readiness_until_explicit_recovery() -> None:
    gate = FeedQualityGate(
        source_id="hyperliquid_mainnet_readonly",
        channel="trades",
        instrument="SOL",
        mode=FeedMode.EVENT_STREAM,
        config=_config(min_coherent_events=1, max_gap_ms=100),
    )
    gate.mark_heartbeat(received_ts_ms=1_000)
    first = gate.ingest_event(
        payload={"tid": 1},
        exchange_ts_ms=990,
        received_ts_ms=1_000,
        event_id="trade-1",
    )
    assert first.ready
    gap = gate.ingest_event(
        payload={"tid": 2},
        exchange_ts_ms=1_190,
        received_ts_ms=1_200,
        event_id="trade-2",
    )
    assert not gap.ready
    assert gap.unresolved_gap
    assert "TEMPORAL_GAP" in gap.reasons
