from __future__ import annotations

import pytest

from hl_observer.paper_trading.paper_engine import PaperEngine, PaperEngineConfig
from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta
from hl_observer.simulation.paper_event import PaperEvent, PaperEventType


def _delta_with_missing_receive_time() -> LeaderDelta:
    return LeaderDelta(
        delta_id="ld:causal-time",
        wallet="0x" + "a" * 40,
        coin="BTC",
        action=LifecycleAction.OPEN_LONG,
        previous_size=0.0,
        current_size=1.0,
        delta_size=1.0,
        observed_at_ms=0,
        leader_event_time_ms=1_000,
        source="test_fixture",
        confidence=0.9,
        evidence_ref="fill:causal-time",
    )


def test_paper_event_refuses_missing_causal_timestamp() -> None:
    with pytest.raises(ValueError, match="timestamp_ms"):
        PaperEvent.create(PaperEventType.NO_TRADE, reason="missing time")


def test_paper_engine_refusal_and_mark_use_supplied_observation_time() -> None:
    engine = PaperEngine(config=PaperEngineConfig(strict_execution_truth=True))
    observed_at_ms = 1_700_000_000_123

    result = engine.apply_delta(
        _delta_with_missing_receive_time(),
        market_price=100.0,
        observed_at_ms=observed_at_ms,
        edge_remaining_bps=50.0,
        spread_bps=2.0,
        estimated_slippage_bps=2.0,
        top_depth_usdt=10_000.0,
        wallet_score=90.0,
        signal_score=80.0,
        marks={"BTC": 100.0},
    )

    assert not result.accepted
    events_by_type = {event.event_type: event for event in engine.ledger.events}
    assert events_by_type[PaperEventType.NO_TRADE].timestamp_ms == observed_at_ms
    assert events_by_type[PaperEventType.EQUITY_UPDATED].timestamp_ms == observed_at_ms


def test_engine_mark_to_market_records_explicit_causal_time() -> None:
    engine = PaperEngine()

    engine.mark_to_market({"BTC": 101.0}, timestamp_ms=42_000)

    assert engine.ledger.events[-1].timestamp_ms == 42_000


@pytest.mark.parametrize("timestamp_ms", [0, -1, True, 1.5, None])
def test_paper_event_and_mark_reject_invalid_timestamps(timestamp_ms: object) -> None:
    with pytest.raises(ValueError, match="timestamp_ms"):
        PaperEvent.create(
            PaperEventType.NO_TRADE,
            timestamp_ms=timestamp_ms,
            reason="invalid time",
        )

    with pytest.raises(ValueError, match="timestamp_ms"):
        PaperEngine().mark_to_market({"BTC": 100.0}, timestamp_ms=timestamp_ms)
