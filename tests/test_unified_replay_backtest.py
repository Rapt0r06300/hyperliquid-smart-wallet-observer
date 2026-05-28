import pytest
from hl_observer.backtest.replay_engine import ReplayEngine
from hl_observer.config.settings import Settings

def test_unified_replay_basic():
    settings = Settings()
    engine = ReplayEngine(settings)

    # Just verify it can be instantiated and called without error
    result = engine.replay_wallet_deltas([])
    assert result["final_equity"] == 1000.0
    assert result["deltas_processed"] == 0
