from __future__ import annotations

from types import SimpleNamespace

import pytest

from hl_observer.realtime import feed_quality as fq


def _cfg(**overrides: object) -> fq.FeedQualityConfig:
    values: dict[str, object] = {
        "max_age_ms": 100.0,
        "max_future_skew_ms": 10.0,
        "heartbeat_max_age_ms": 100.0,
        "max_gap_ms": 50.0,
        "max_jitter_ms": 100.0,
        "max_latency_ms": 100.0,
        "max_spread_bps": 1_000.0,
        "max_mid_jump_fraction": 0.10,
        "min_coherent_events": 1,
        "min_score": 0.0,
        "sample_window": 8,
        "seen_event_window": 2,
    }
    values.update(overrides)
    return fq.FeedQualityConfig(**values)


def _gate(mode: fq.FeedMode = fq.FeedMode.EVENT_STREAM, **cfg: object) -> fq.FeedQualityGate:
    return fq.FeedQualityGate(
        source_id="unit",
        channel="events" if mode is fq.FeedMode.EVENT_STREAM else "book",
        instrument="BTC",
        mode=mode,
        config=_cfg(**cfg),
    )


def test_config_percentile_hash_and_level_validation() -> None:
    with pytest.raises(ValueError, match="min_coherent_events"):
        fq.FeedQualityConfig(min_coherent_events=0)
    with pytest.raises(ValueError, match="min_score"):
        fq.FeedQualityConfig(min_score=-1)
    with pytest.raises(ValueError, match="min_score"):
        fq.FeedQualityConfig(min_score=101)
    with pytest.raises(ValueError, match="windows"):
        fq.FeedQualityConfig(sample_window=1)
    with pytest.raises(ValueError, match="windows"):
        fq.FeedQualityConfig(seen_event_window=1)

    assert fq._percentile([], 0.5) is None
    assert fq._percentile([7], 0.5) == 7
    assert fq._percentile([0, 10], 0.25) == 2.5
    assert fq.stable_event_id({"b": 2, "a": 1}) == fq.stable_event_id({"a": 1, "b": 2})
    assert fq.stable_event_id({"a": 1}) != fq.stable_event_id({"a": 2})

    assert fq._normalise_levels([{"px": "100", "sz": "2"}, (101, 0)]) == {100.0: 2.0}
    assert fq._normalise_levels([(100, 1), (100, 3)]) == {100.0: 3.0}
    for bad in (["bad"], [{"px": 0, "sz": 1}], [{"px": 1, "sz": -1}], [(float("nan"), 1)]):
        with pytest.raises((TypeError, ValueError)):
            fq._normalise_levels(bad)


def test_book_rejection_paths_and_incremental_validation() -> None:
    full = _gate(fq.FeedMode.FULL_SNAPSHOT, min_score=0)
    full.mark_heartbeat(received_ts_ms=10)
    invalid = full.ingest_book_snapshot(
        bids=[("bad", 1)], asks=[(101, 1)], exchange_ts_ms=10, received_ts_ms=10, event_id="bad-level"
    )
    assert "INVALID_BOOK_LEVEL" in invalid.reasons and invalid.invalid_bbo == 1

    empty = full.ingest_book_snapshot(
        bids=[], asks=[(101, 1)], exchange_ts_ms=11, received_ts_ms=11, event_id="empty"
    )
    assert "EMPTY_BOOK_SIDE" in empty.reasons

    wide = _gate(fq.FeedMode.FULL_SNAPSHOT, max_spread_bps=5.0)
    wide.mark_heartbeat(received_ts_ms=20)
    snap = wide.ingest_book_snapshot(
        bids=[(100, 1)], asks=[(101, 1)], exchange_ts_ms=20, received_ts_ms=20, event_id="wide"
    )
    assert "SPREAD_OUTLIER" in snap.reasons

    jump = _gate(fq.FeedMode.FULL_SNAPSHOT, max_mid_jump_fraction=0.01)
    jump.mark_heartbeat(received_ts_ms=30)
    jump.ingest_book_snapshot(
        bids=[(100, 1)], asks=[(101, 1)], exchange_ts_ms=30, received_ts_ms=30, event_id="base"
    )
    outlier = jump.ingest_book_snapshot(
        bids=[(120, 1)], asks=[(121, 1)], exchange_ts_ms=31, received_ts_ms=31, event_id="jump"
    )
    assert "MID_PRICE_OUTLIER" in outlier.reasons and outlier.outliers == 1

    unsupported = full.ingest_book_incremental(
        bid_updates=[(100, 1)], exchange_ts_ms=40, received_ts_ms=40, event_id="unsupported"
    )
    assert "INCREMENTAL_UNSUPPORTED_FOR_FULL_SNAPSHOT_FEED" in unsupported.reasons

    inc = _gate(fq.FeedMode.SNAPSHOT_THEN_INCREMENTAL)
    inc.mark_heartbeat(received_ts_ms=50)
    inc.ingest_book_snapshot(
        bids=[(100, 1)], asks=[(101, 1)], exchange_ts_ms=50, received_ts_ms=50, event_id="s", sequence=1
    )
    bad_update = inc.ingest_book_incremental(
        bid_updates=[("bad", 1)], exchange_ts_ms=51, received_ts_ms=51, event_id="u", sequence=2
    )
    assert "INVALID_BOOK_LEVEL" in bad_update.reasons


def test_event_modes_snapshot_incremental_and_batch(monkeypatch) -> None:
    full = _gate(fq.FeedMode.FULL_SNAPSHOT)
    with pytest.raises(ValueError, match="ingest_book_snapshot"):
        full.ingest_event(payload={"x": 1}, exchange_ts_ms=1, received_ts_ms=1)

    gate = _gate(fq.FeedMode.SNAPSHOT_THEN_INCREMENTAL)
    gate.mark_heartbeat(received_ts_ms=100)
    early = gate.ingest_event(payload={"x": 1}, exchange_ts_ms=100, received_ts_ms=100, event_id="early")
    assert "INCREMENTAL_BEFORE_SNAPSHOT" in early.reasons
    baseline = gate.ingest_event(
        payload={"x": 2}, exchange_ts_ms=101, received_ts_ms=101, event_id="baseline", is_snapshot=True
    )
    assert baseline.snapshots == 1
    accepted = gate.ingest_event(payload={"x": 3}, exchange_ts_ms=102, received_ts_ms=102, event_id="inc")
    assert accepted.synchronized is True and accepted.accepted_events >= 2

    batch_gate = _gate(fq.FeedMode.SNAPSHOT_THEN_INCREMENTAL)
    batch_gate.mark_heartbeat(received_ts_ms=200)
    events = [
        SimpleNamespace(exchange_ts_ms=199, stable_event_id="a"),
        SimpleNamespace(exchange_ts_ms=None, stable_event_id="b"),
    ]
    monkeypatch.setattr(fq, "canonicalize_frame", lambda *args, **kwargs: events)
    rows = batch_gate.ingest_event_batch(payloads=[{"a": 1}], received_ts_ms=200, frame_sequence=1, is_snapshot=True)
    assert len(rows) == 2 and batch_gate._snapshot_seen is True

    monkeypatch.setattr(
        fq,
        "canonicalize_frame",
        lambda *args, **kwargs: [SimpleNamespace(exchange_ts_ms=201, stable_event_id="c")],
    )
    rows = batch_gate.ingest_event_batch(payloads=[{"c": 1}], received_ts_ms=201, frame_sequence=2)
    assert rows[-1].synchronized is True and batch_gate.incrementals == 1

    monkeypatch.setattr(
        fq,
        "canonicalize_frame",
        lambda *args, **kwargs: [SimpleNamespace(exchange_ts_ms=202, stable_event_id="c")],
    )
    duplicate = batch_gate.ingest_event_batch(payloads=[{"c": 2}], received_ts_ms=202, frame_sequence=3)
    assert "DUPLICATE_EVENT" in duplicate[-1].reasons

    monkeypatch.setattr(fq, "canonicalize_frame", lambda *args, **kwargs: [])
    assert batch_gate.ingest_event_batch(payloads=[], received_ts_ms=203) == []


def test_snapshot_temporal_sequence_future_and_quality_metrics() -> None:
    gate = _gate(fq.FeedMode.EVENT_STREAM, min_score=99.0)
    empty = gate.snapshot(now_ms=0)
    assert empty.stale_rate is None and empty.duplicate_rate is None
    assert "LATEST_EVENT_STALE" in empty.reasons and "HEARTBEAT_STALE" in empty.reasons
    as_dict = empty.as_dict()
    assert isinstance(as_dict["reasons"], list) and isinstance(as_dict["reason_counts"], dict)

    gate.mark_heartbeat(received_ts_ms=100)
    assert gate._start_observation(exchange_ts_ms=90, received_ts_ms=100, event_id="a", sequence=1) == []
    second = gate._start_observation(exchange_ts_ms=80, received_ts_ms=90, event_id="b", sequence=1)
    assert "NON_MONOTONIC_EXCHANGE_TIMESTAMP" in second
    assert "NON_MONOTONIC_RECEIVE_TIMESTAMP" in second
    assert "NON_MONOTONIC_SEQUENCE" in second

    future = gate._start_observation(exchange_ts_ms=200, received_ts_ms=100, event_id="future", sequence=2)
    assert "EXCHANGE_TIMESTAMP_IN_FUTURE" in future

    gap = gate._start_observation(exchange_ts_ms=200, received_ts_ms=200, event_id="gap", sequence=5)
    assert "TEMPORAL_GAP" in gap and "SEQUENCE_GAP" in gap
    assert gate.gaps >= 2 and gate.unresolved_gap if hasattr(gate, "unresolved_gap") else True

    metrics = gate.snapshot(now_ms=200)
    assert metrics.non_monotonic >= 3
    assert metrics.gap_duration_ms > 0
    assert metrics.feed_quality_score < 100


def test_update_book_event_eviction_gap_mark_and_score_penalties() -> None:
    book = {100.0: 1.0}
    fq.FeedQualityGate._apply_updates(book, [{"px": 100, "sz": 0}, (101, 2)])
    assert book == {101.0: 2.0}
    for bad in (["bad"], [(0, 1)], [(1, -1)], [(1, float("nan"))]):
        with pytest.raises((TypeError, ValueError)):
            fq.FeedQualityGate._apply_updates({}, bad)

    gate = _gate(fq.FeedMode.EVENT_STREAM)
    assert gate._remember_event("a") is True
    assert gate._remember_event("a") is False
    assert gate._remember_event("b") is True
    assert gate._remember_event("c") is True
    assert gate._remember_event("a") is True  # evicted by seen_event_window=2

    gate.mark_gap(reason="UNIT_GAP")
    gate.mark_reconnect(received_ts_ms=10, connection_id="new")
    gate._latencies.extend([10.0, 100.0])
    gate._jitters.extend([5.0, 90.0])
    gate.total_events = max(gate.total_events, 2)
    gate.stale_events = 1
    gate.duplicates = 1
    gate.non_monotonic = 1
    gate.invalid_bbo = 1
    gate.outliers = 1
    score = gate._score()
    assert 0.0 <= score < 100.0
    assert gate._contains_hard_rejection(["STALE_EVENT"]) is True
    assert gate._contains_hard_rejection(["TEMPORAL_GAP"]) is False
