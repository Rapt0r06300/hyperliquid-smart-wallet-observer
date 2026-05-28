from __future__ import annotations

import pytest
from hl_observer.execution.decision_engine import UnifiedDecisionEngine, SimulationConfig, SimulationState
from hl_observer.copying.realtime_magic_score import RealtimeCopyRiskConfig

class MockRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items(): setattr(self, k, v)

def test_engine_equity_update():
    cfg = SimulationConfig(
        risk_config=RealtimeCopyRiskConfig(min_edge_required_bps=1.0),
        starting_equity_usdt=1000.0,
    )
    engine = UnifiedDecisionEngine(cfg)
    state = SimulationState(equity_usdt=1000.0, starting_equity_usdt=1000.0)

    # Entry
    entry = MockRow(wallet_address="0x1", coin="BTC", price=50000.0, exchange_ts=1000, delta_type="open", delta_size=1.0, confidence_score=1.0)
    engine.process_delta(entry, 1050, {"BTC": 50000.0}, state, [entry])

    # Exit at higher price
    exit_row = MockRow(wallet_address="0x1", coin="BTC", price=60000.0, exchange_ts=2000, delta_type="close", delta_size=1.0, confidence_score=1.0, previous_size=1.0)
    engine.process_delta(exit_row, 2050, {"BTC": 60000.0}, state, [entry, exit_row])

    # Equity should be significantly higher than 1000
    assert state.equity_usdt > 1000.0
    assert state.executed_entries == 1
    assert state.executed_exits == 1

def test_engine_partial_reduction_costs():
    cfg = SimulationConfig(
        risk_config=RealtimeCopyRiskConfig(min_edge_required_bps=1.0),
        cost_bps=100.0  # High cost for visibility
    )
    engine = UnifiedDecisionEngine(cfg)
    state = SimulationState()

    # Open 10 BTC position
    entry = MockRow(wallet_address="0x1", coin="BTC", price=50000.0, exchange_ts=1000, delta_type="open", delta_size=10.0, confidence_score=1.0)
    # We want 10 units at 50000. simulated_notional must be 500000
    metrics = {"simulated_notional_usdt": 500000.0, "decision_reason": "EDGE_OK_FOR_LOCAL_SIMULATION"}
    engine._execute_entry(entry, "OPEN_LONG", "LONG", engine._encode_position_key("0x1", "BTC", "LONG"), metrics, state)

    pos_key = engine._encode_position_key("0x1", "BTC", "LONG")
    initial_costs = state.virtual_positions[pos_key]["entry_costs"]
    assert initial_costs > 0

    # Partial reduction by exactly half of the units
    # Initial size was calculated with pessimistic fill: 500000 / 50040 = 9.992006394884093
    # We close exactly half of THAT size to avoid precision issues in the test
    half_size = state.virtual_positions[pos_key]["size"] / 2
    reduce_row = MockRow(wallet_address="0x1", coin="BTC", price=50000.0, exchange_ts=2000, delta_type="reduce", delta_size=half_size)
    engine._execute_exit(reduce_row, "REDUCE", "LONG", pos_key, metrics, state)

    # Remaining entry costs should be exactly half
    assert state.virtual_positions[pos_key]["entry_costs"] == pytest.approx(initial_costs / 2, rel=1e-5)
