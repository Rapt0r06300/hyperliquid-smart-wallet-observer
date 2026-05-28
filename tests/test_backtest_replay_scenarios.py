from __future__ import annotations

import pytest
from dataclasses import dataclass
from hl_observer.backtest.replay_engine import replay_events, run_scenario_comparison
from hl_observer.execution.decision_engine import SimulationConfig
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

def test_replay_latency_simulation():
    risk_cfg = RealtimeCopyRiskConfig(min_edge_required_bps=1.0, max_signal_age_ms=1000)

    # 1. WS-like Replay (50ms latency) -> Entry should pass
    ws_cfg = SimulationConfig(risk_config=risk_cfg, mode="WS_LIKE")
    delta = MockDelta(wallet_address="0x1", coin="BTC", price=50000.0, exchange_ts=1000)

    state_ws = replay_events([delta], {"BTC": 50000.0}, ws_cfg)
    assert state_ws.executed_entries == 1

    # 2. Polling 300s Replay -> Delta at 1000ms is seen at 300,000ms -> Should be rejected as stale
    poll_cfg = SimulationConfig(risk_config=risk_cfg, mode="POLLING_300S")
    state_poll = replay_events([delta], {"BTC": 50000.0}, poll_cfg)
    assert state_poll.executed_entries == 0
    assert state_poll.missed_fills_count == 1

def test_run_scenario_comparison():
    risk_cfg = RealtimeCopyRiskConfig(min_edge_required_bps=1.0)
    base_cfg = SimulationConfig(risk_config=risk_cfg)

    delta = MockDelta(wallet_address="0x1", coin="BTC", price=50000.0, exchange_ts=1000)

    results = run_scenario_comparison([delta], {"BTC": 50000.0}, base_cfg)

    assert "WS_LIKE" in results
    assert "POLLING_300S" in results
    assert "STRICT_EDGE" in results
    assert "LOOSE_EDGE" in results

    # Verify that different configs produce different results if applicable
    # WS_LIKE should have 1 entry
    assert results["WS_LIKE"].executed_entries == 1
    # POLLING_300S should have 0 entries due to default max_signal_age_ms in RealtimeCopyRiskConfig
    assert results["POLLING_300S"].executed_entries == 0
