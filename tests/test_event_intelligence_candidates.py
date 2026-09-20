from __future__ import annotations

import pytest

from hl_observer.collection.native_venue_market import NativeMarketSnapshot
from hl_observer.event_intelligence import (
    ExternalEvent,
    ExternalEventType,
    SourceTier,
    WorldMonitorEvent,
)
from hl_observer.event_intelligence.candidates import (
    EventLeadLagConfig,
    evaluate_event_lead_lag_candidate,
)


def _event(
    *,
    kind: str = "news",
    ingest_ts_ms: int = 1_000,
    coverage_state: str = "complete",
    probability_delta_pp: float | None = None,
) -> WorldMonitorEvent:
    external = ExternalEvent(
        event_id=f"evt-{kind}",
        source=f"worldmonitor.{kind}",
        event_type=(
            ExternalEventType.PREDICTION
            if kind == "prediction"
            else ExternalEventType.NEWS
        ),
        source_tier=SourceTier.AGGREGATOR,
        retrieval_ts_ms=ingest_ts_ms,
        ingest_ts_ms=ingest_ts_ms,
        methodology_version="test-v1",
        raw_evidence_ref=f"ref:{kind}",
        classification_confidence=0.9,
        corroboration_count=2,
    )
    return WorldMonitorEvent(
        event=external,
        kind=kind,
        publisher="Reuters" if kind == "news" else "MARKET_SOURCE_POLYMARKET",
        importance_score=80.0 if kind == "news" else None,
        credibility_score=90.0 if kind == "news" else None,
        coverage_state=coverage_state,
        probability=0.55 if kind == "prediction" else None,
        probability_delta_pp=probability_delta_pp,
        prediction_source=(
            "MARKET_SOURCE_POLYMARKET" if kind == "prediction" else ""
        ),
    )


def _snap(
    venue: str,
    *,
    bid: float,
    ask: float,
    receive_ts_ms: int,
) -> NativeMarketSnapshot:
    return NativeMarketSnapshot.build(
        venue=venue,
        coin="BTC",
        exchange_symbol="BTCUSDT",
        bid=bid,
        ask=ask,
        exchange_ts_ms=receive_ts_ms - 1,
        receive_ts_ms=receive_ts_ms,
        now_ms=receive_ts_ms,
        stale_after_ms=10_000,
    )


def _upward_lag_tape() -> list[NativeMarketSnapshot]:
    return [
        _snap("binance", bid=99.99, ask=100.01, receive_ts_ms=990),
        _snap("bybit", bid=99.99, ask=100.01, receive_ts_ms=990),
        _snap("hyperliquid", bid=99.99, ask=100.01, receive_ts_ms=990),
        _snap("binance", bid=100.11, ask=100.13, receive_ts_ms=1_190),
        _snap("bybit", bid=100.09, ask=100.11, receive_ts_ms=1_190),
        _snap("hyperliquid", bid=100.02, ask=100.04, receive_ts_ms=1_190),
    ]


def test_news_candidate_requires_market_confirmation_and_executable_room() -> None:
    result = evaluate_event_lead_lag_candidate(
        _event(),
        _upward_lag_tape(),
        coin="BTC",
        decision_ts_ms=1_200,
        cost_floor_bps=4.0,
    )

    assert result.status == "CANDIDATE"
    assert result.reason == "EVENT_CONFIRMED_EXECUTABLE_LAG"
    assert result.leader_venue == "binance"
    assert result.confirming_venues == ("binance", "bybit")
    assert result.research_direction == "UPWARD_HL_LAG"
    assert result.leader_move_bps == pytest.approx(12.0, abs=0.05)
    assert result.hyperliquid_mid_move_bps == pytest.approx(3.0, abs=0.05)
    assert result.hyperliquid_executable_move_bps == pytest.approx(4.0, abs=0.05)
    assert result.gross_room_bps == pytest.approx(8.0, abs=0.05)
    assert result.net_room_bps == pytest.approx(4.0, abs=0.05)
    assert result.is_candidate is True
    assert result.economically_measurable is True
    assert result.real_execution is False


def test_unknown_costs_fail_closed_as_unmeasurable() -> None:
    result = evaluate_event_lead_lag_candidate(
        _event(),
        _upward_lag_tape(),
        coin="BTC",
        decision_ts_ms=1_200,
        cost_floor_bps=None,
    )

    assert result.status == "UNMEASURABLE"
    assert result.reason == "COST_FLOOR_MISSING"
    assert result.gross_room_bps == pytest.approx(8.0, abs=0.05)
    assert result.net_room_bps is None
    assert result.is_candidate is False


def test_cost_floor_can_erase_apparent_event_edge() -> None:
    result = evaluate_event_lead_lag_candidate(
        _event(),
        _upward_lag_tape(),
        coin="BTC",
        decision_ts_ms=1_200,
        cost_floor_bps=8.0,
    )

    assert result.status == "REJECTED"
    assert result.reason == "COSTS_ERASE_EDGE"
    assert result.gross_room_bps == pytest.approx(8.0, abs=0.05)
    assert result.net_room_bps == pytest.approx(0.0, abs=0.05)


def test_future_market_snapshot_cannot_create_a_candidate() -> None:
    tape = [
        _snap("binance", bid=99.99, ask=100.01, receive_ts_ms=990),
        _snap("hyperliquid", bid=99.99, ask=100.01, receive_ts_ms=990),
        _snap("hyperliquid", bid=99.99, ask=100.01, receive_ts_ms=1_190),
        _snap("binance", bid=100.19, ask=100.21, receive_ts_ms=1_300),
    ]

    result = evaluate_event_lead_lag_candidate(
        _event(),
        tape,
        coin="BTC",
        decision_ts_ms=1_200,
        cost_floor_bps=1.0,
    )

    assert result.status == "WATCH"
    assert result.reason == "NO_NON_HL_MARKET_CONFIRMATION"
    assert result.leader_venue is None


def test_decision_before_event_ingest_is_rejected() -> None:
    result = evaluate_event_lead_lag_candidate(
        _event(ingest_ts_ms=1_100),
        _upward_lag_tape(),
        coin="BTC",
        decision_ts_ms=1_050,
        cost_floor_bps=1.0,
    )
    assert result.status == "REJECTED"
    assert result.reason == "FUTURE_INFORMATION"


def test_stale_external_source_cannot_create_candidate() -> None:
    result = evaluate_event_lead_lag_candidate(
        _event(coverage_state="stale"),
        _upward_lag_tape(),
        coin="BTC",
        decision_ts_ms=1_200,
        cost_floor_bps=1.0,
    )
    assert result.status == "REJECTED"
    assert result.reason == "SOURCE_NOT_USABLE"


def test_prediction_leading_requires_material_probability_shift() -> None:
    weak = evaluate_event_lead_lag_candidate(
        _event(kind="prediction", probability_delta_pp=3.0),
        _upward_lag_tape(),
        coin="BTC",
        decision_ts_ms=1_200,
        cost_floor_bps=1.0,
    )
    assert weak.status == "REJECTED"
    assert weak.reason == "PREDICTION_DELTA_TOO_SMALL"

    strong = evaluate_event_lead_lag_candidate(
        _event(kind="prediction", probability_delta_pp=8.0),
        _upward_lag_tape(),
        coin="BTC",
        decision_ts_ms=1_200,
        cost_floor_bps=4.0,
    )
    assert strong.status == "CANDIDATE"
    assert strong.prediction_delta_pp == pytest.approx(8.0)


def test_downward_lag_uses_hyperliquid_bid_as_executable_side() -> None:
    tape = [
        _snap("binance", bid=99.99, ask=100.01, receive_ts_ms=990),
        _snap("hyperliquid", bid=99.99, ask=100.01, receive_ts_ms=990),
        _snap("binance", bid=99.87, ask=99.89, receive_ts_ms=1_190),
        _snap("hyperliquid", bid=99.96, ask=99.98, receive_ts_ms=1_190),
    ]
    result = evaluate_event_lead_lag_candidate(
        _event(),
        tape,
        coin="BTC",
        decision_ts_ms=1_200,
        cost_floor_bps=3.0,
    )

    assert result.status == "CANDIDATE"
    assert result.research_direction == "DOWNWARD_HL_LAG"
    assert result.leader_move_bps == pytest.approx(-12.0, abs=0.05)
    assert result.hyperliquid_executable_move_bps == pytest.approx(-4.0, abs=0.05)
    assert result.gross_room_bps == pytest.approx(8.0, abs=0.05)
    assert result.net_room_bps == pytest.approx(5.0, abs=0.05)


def test_requires_fresh_current_bbo_at_decision_time() -> None:
    config = EventLeadLagConfig(max_current_snapshot_age_ms=50)
    tape = _upward_lag_tape()

    result = evaluate_event_lead_lag_candidate(
        _event(),
        tape,
        coin="BTC",
        decision_ts_ms=1_300,
        cost_floor_bps=1.0,
        config=config,
    )
    assert result.status == "UNMEASURABLE"
    assert result.reason == "HYPERLIQUID_BASELINE_OR_CURRENT_MISSING"


def test_partial_coverage_is_fail_closed() -> None:
    result = evaluate_event_lead_lag_candidate(
        _event(coverage_state="partial"),
        _upward_lag_tape(),
        coin="BTC",
        decision_ts_ms=1_200,
        cost_floor_bps=1.0,
    )
    assert result.status == "REJECTED"
    assert result.reason == "SOURCE_NOT_USABLE"
