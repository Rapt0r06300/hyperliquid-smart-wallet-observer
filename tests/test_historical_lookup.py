from __future__ import annotations

import pytest
from hl_observer.backtest.replay_engine import replay_events
from hl_observer.execution.decision_engine import SimulationConfig
from hl_observer.copying.realtime_magic_score import RealtimeCopyRiskConfig

class MockRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items(): setattr(self, k, v)

def test_replay_with_historical_snapshots():
    risk_cfg = RealtimeCopyRiskConfig(min_edge_required_bps=1.0)
    cfg = SimulationConfig(risk_config=risk_cfg)

    # Delta at T=1000
    delta = MockRow(wallet_address="0x1", coin="BTC", price=50000.0, exchange_ts=1000, delta_type="open", delta_size=1.0, confidence_score=1.0)

    # Snapshots: BTC price is 50k at T=0, but jumps to 100k at T=500
    snapshots = [
        {"timestamp_ms": 0, "mids": {"BTC": 50000.0}},
        {"timestamp_ms": 500, "mids": {"BTC": 100000.0}},
    ]

    # Replay should pick up the 100k mid price at T=1000 (latency makes it 1050)
    state = replay_events([delta], snapshots, cfg)

    last_event = state.ledger_events[0]
    # adverse_price_move_bps should be high because leader price (50k) vs mid price (100k)
    assert last_event["adverse_price_move_bps"] > 5000 # 100k vs 50k is 100% = 10000 bps
