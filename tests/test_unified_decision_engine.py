from __future__ import annotations

import pytest
from dataclasses import dataclass
from hl_observer.execution.decision_engine import UnifiedDecisionEngine, SimulationConfig, SimulationState
from hl_observer.copying.realtime_magic_score import RealtimeCopyRiskConfig

@dataclass
class MockDelta:
    wallet_address: str
    coin: str
    price: float
    exchange_ts: int
    delta_type: str = "open"
    delta_size: float = 1.0
    previous_size: float = 0.0
    new_size: float = 1.0
    side: str = "long"
    confidence_score: float = 1.0

def test_unified_engine_entry_exit():
    cfg = SimulationConfig(
        risk_config=RealtimeCopyRiskConfig(min_edge_required_bps=1.0),
        starting_equity_usdt=1000.0,
        max_position_notional_usdt=100.0
    )
    engine = UnifiedDecisionEngine(cfg)
    state = SimulationState()

    # 1. Test Entry
    entry = MockDelta(wallet_address="0x1", coin="BTC", price=50000.0, exchange_ts=1000)
    engine.process_delta(entry, 1050, {"BTC": 50000.0}, state, [entry])

    assert state.executed_entries == 1
    assert len(state.virtual_positions) == 1
    key = engine._encode_position_key("0x1", "BTC", "LONG")
    assert key in state.virtual_positions

    # 2. Test Exit
    exit_delta = MockDelta(wallet_address="0x1", coin="BTC", price=51000.0, exchange_ts=2000, delta_type="close", previous_size=1.0, new_size=0.0)
    engine.process_delta(exit_delta, 2050, {"BTC": 51000.0}, state, [entry, exit_delta])

    assert state.executed_exits == 1
    assert len(state.virtual_positions) == 0

    # Check PnL (Pessimistic fill applies slippage/spread)
    ledger = state.ledger_events
    exit_event = ledger[-1]
    assert exit_event["status"] == "LOCAL_REPLAY"
    assert exit_event["gross_pnl_usdc"] > 0

def test_engine_rejection_stale():
    cfg = SimulationConfig(
        risk_config=RealtimeCopyRiskConfig(min_edge_required_bps=1.0, max_signal_age_ms=1000),
    )
    engine = UnifiedDecisionEngine(cfg)
    state = SimulationState()

    # Delta is 2 seconds old
    stale = MockDelta(wallet_address="0x1", coin="ETH", price=2000.0, exchange_ts=1000)
    engine.process_delta(stale, 3001, {"ETH": 2000.0}, state, [stale])

    assert state.executed_entries == 0
    assert state.refused_signals == 1
    assert state.missed_fills_count == 1
    assert "STALE_SIGNAL" in state.ledger_events[0]["reason"]

def test_engine_consensus_requirement():
    cfg = SimulationConfig(
        risk_config=RealtimeCopyRiskConfig(min_edge_required_bps=1.0),
        consensus_required=True
    )
    engine = UnifiedDecisionEngine(cfg)
    state = SimulationState()

    # Single wallet delta
    delta = MockDelta(wallet_address="0x1", coin="SOL", price=100.0, exchange_ts=1000)
    engine.process_delta(delta, 1050, {"SOL": 100.0}, state, [delta])

    assert state.executed_entries == 0
    assert state.ledger_events[0]["reason"] == "CONSENSUS_REQUIRED"

    # Two wallets delta
    delta2 = MockDelta(wallet_address="0x2", coin="SOL", price=100.1, exchange_ts=1010)
    all_deltas = [delta, delta2]
    engine.process_delta(delta2, 1060, {"SOL": 100.0}, state, all_deltas)

    assert state.executed_entries == 1
