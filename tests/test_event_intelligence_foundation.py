from __future__ import annotations

import pytest

from hl_observer.collection.native_venue_market import NativeMarketSnapshot
from hl_observer.event_intelligence import (
    ExternalEvent,
    ExternalEventReplayGuard,
    ExternalEventType,
    SourceTier,
    measure_event_price_discovery,
)


def _event(*, ingest_ts_ms: int = 1_000) -> ExternalEvent:
    return ExternalEvent(
        event_id="wm:test:1",
        source="worldmonitor",
        event_type=ExternalEventType.GEOPOLITICAL,
        source_tier=SourceTier.AGGREGATOR,
        publication_ts_ms=900,
        retrieval_ts_ms=950,
        ingest_ts_ms=ingest_ts_ms,
        event_ts_ms=850,
        methodology_version="wm-v1",
        raw_evidence_ref="sha256:" + "1" * 64,
        source_link="https://example.invalid/event/1",
        country_codes=("IR",),
        regions=("MENA",),
        entities=("oil infrastructure",),
        severity=0.8,
        classification_confidence=0.9,
        corroboration_count=3,
    )


def _snap(
    venue: str,
    *,
    mid: float,
    receive_ts_ms: int,
    coin: str = "BTC",
) -> NativeMarketSnapshot:
    return NativeMarketSnapshot.build(
        venue=venue,
        coin=coin,
        exchange_symbol=coin,
        bid=mid - 0.01,
        ask=mid + 0.01,
        exchange_ts_ms=receive_ts_ms - 1,
        receive_ts_ms=receive_ts_ms,
        now_ms=receive_ts_ms,
        stale_after_ms=5_000,
    )


def test_external_event_uses_ingest_time_as_causal_clock() -> None:
    event = _event()
    assert event.available_ts_ms == 1_000
    assert event.is_available_at(999) is False
    assert event.is_available_at(1_000) is True

    guard = ExternalEventReplayGuard()
    early = guard.observe(event, decision_ts_ms=999)
    assert early.accepted is False
    assert early.reason == "FUTURE_INFORMATION"

    accepted = guard.observe(event, decision_ts_ms=1_000)
    assert accepted.accepted is True
    assert accepted.reason == "ACCEPT"

    duplicate = guard.observe(event, decision_ts_ms=1_001)
    assert duplicate.accepted is False
    assert duplicate.reason == "DUPLICATE_EVENT"


def test_external_event_rejects_non_causal_or_unsafe_contracts() -> None:
    with pytest.raises(ValueError, match="retrieval_ts_ms"):
        ExternalEvent(
            event_id="bad",
            source="source",
            event_type=ExternalEventType.NEWS,
            source_tier=SourceTier.WIRE,
            retrieval_ts_ms=2_000,
            ingest_ts_ms=1_000,
            methodology_version="v1",
            raw_evidence_ref="ref",
        )

    with pytest.raises(ValueError, match="publication_ts_ms"):
        ExternalEvent(
            event_id="bad",
            source="source",
            event_type=ExternalEventType.NEWS,
            source_tier=SourceTier.WIRE,
            publication_ts_ms=1_100,
            retrieval_ts_ms=1_000,
            ingest_ts_ms=1_000,
            methodology_version="v1",
            raw_evidence_ref="ref",
        )

    with pytest.raises(ValueError, match="real_execution"):
        ExternalEvent(
            event_id="bad",
            source="source",
            event_type=ExternalEventType.NEWS,
            source_tier=SourceTier.WIRE,
            retrieval_ts_ms=1_000,
            ingest_ts_ms=1_000,
            methodology_version="v1",
            raw_evidence_ref="ref",
            real_execution=True,
        )


def test_r2_record_contains_structured_facts_not_source_text() -> None:
    record = _event().to_r2_record()
    assert record["schema"] == "alina.external_event.v1"
    assert record["event_type"] == "GEOPOLITICAL"
    assert record["real_execution"] is False
    forbidden = {"headline", "summary", "body", "text", "content", "article"}
    assert forbidden.isdisjoint(record)


def test_price_discovery_measures_information_to_venue_to_hyperliquid() -> None:
    event = _event()
    snapshots = [
        _snap("binance", mid=100.0, receive_ts_ms=990),
        _snap("bybit", mid=100.0, receive_ts_ms=990),
        _snap("hyperliquid", mid=100.0, receive_ts_ms=990),
        _snap("binance", mid=100.10, receive_ts_ms=1_100),
        _snap("bybit", mid=100.04, receive_ts_ms=1_150),
        _snap("hyperliquid", mid=100.06, receive_ts_ms=1_250),
    ]

    result = measure_event_price_discovery(
        event,
        snapshots,
        coin="BTC",
        threshold_bps=5.0,
        horizon_ms=1_000,
    )

    assert result.status == "LEADER_THEN_HYPERLIQUID"
    assert result.external_event_led_market is True
    assert result.first_venue == "binance"
    assert result.first_reaction_latency_ms == 100
    assert result.hyperliquid_reaction_latency_ms == 250
    assert result.leader_to_hyperliquid_lag_ms == 150
    assert result.reaction_gap_half_life_ms == 150
    assert result.initial_leader_hl_gap_bps == pytest.approx(10.0, abs=0.05)
    assert result.first_move_bps == pytest.approx(10.0, abs=0.05)
    assert result.hyperliquid_move_bps == pytest.approx(6.0, abs=0.05)
    assert result.peak_dispersion_bps >= 9.9
    assert result.real_execution is False


def test_market_move_before_event_ingest_is_not_counted_as_event_led() -> None:
    event = _event(ingest_ts_ms=1_000)
    snapshots = [
        _snap("binance", mid=100.0, receive_ts_ms=900),
        _snap("hyperliquid", mid=100.0, receive_ts_ms=900),
        _snap("binance", mid=100.20, receive_ts_ms=970),
        _snap("hyperliquid", mid=100.20, receive_ts_ms=980),
        _snap("binance", mid=100.20, receive_ts_ms=1_100),
        _snap("hyperliquid", mid=100.20, receive_ts_ms=1_100),
    ]

    result = measure_event_price_discovery(
        event,
        snapshots,
        coin="BTC",
        threshold_bps=5.0,
        horizon_ms=1_000,
    )

    assert result.status == "NO_REACTION"
    assert result.first_venue is None
    assert result.first_reaction_latency_ms is None


def test_price_discovery_fails_closed_without_pre_event_baseline() -> None:
    result = measure_event_price_discovery(
        _event(),
        [_snap("binance", mid=100.10, receive_ts_ms=1_100)],
        coin="BTC",
    )
    assert result.status == "NO_BASELINE"
    assert result.baseline_venues == ()
    assert result.real_execution is False
