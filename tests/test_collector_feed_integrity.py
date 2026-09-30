from __future__ import annotations

from hl_observer.collection.feed_integrity import FeedIntegrityState, estimate_clock_sync


def test_sequence_gap_and_duplicate_are_measured() -> None:
    state = FeedIntegrityState(strict_consecutive_sequence=True)
    ok, reasons = state.observe(
        sequence=10, exchange_ts_ms=1_000, receive_ts_ms=1_010, receive_mono_ns=100
    )
    assert ok
    assert not reasons

    ok, reasons = state.observe(
        sequence=12, exchange_ts_ms=1_020, receive_ts_ms=1_030, receive_mono_ns=200
    )
    assert not ok
    assert "SEQUENCE_GAP" in reasons
    assert state.gaps == 1

    _ok, reasons = state.observe(
        sequence=12, exchange_ts_ms=1_021, receive_ts_ms=1_031, receive_mono_ns=201
    )
    assert "DUPLICATE_SEQUENCE" in reasons
    assert state.duplicates == 1


def test_clock_sync_uses_request_midpoint() -> None:
    sample = estimate_clock_sync(
        venue="bybit",
        server_ts_ms=1_015,
        send_wall_ts_ms=1_000,
        receive_wall_ts_ms=1_020,
    )
    assert sample.rtt_ms == 20.0
    assert sample.offset_ms == 5.0
