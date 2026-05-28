from __future__ import annotations
import pytest
from unittest.mock import MagicMock
from hl_observer.config.settings import Settings, PaperSimulationSettings
from hl_observer.execution.decision_engine import UnifiedDecisionEngine, VirtualPosition
from hl_observer.storage.models import PositionDeltaModel

@pytest.fixture
def mock_settings():
    settings = MagicMock(spec=Settings)
    settings.paper_simulation = PaperSimulationSettings(
        starting_equity=1000.0,
        max_position_notional=50.0,
        max_total_exposure=200.0,
        max_open_trades=3,
        max_risk_per_trade_pct=1.0,
        max_drawdown_stop_pct=10.0
    )
    settings.risk = MagicMock()
    settings.risk.min_edge_required_bps = 10.0
    return settings

def test_proportional_exit_scaling(mock_settings):
    """Verify that a leader's partial close results in a proportional virtual close."""
    engine = UnifiedDecisionEngine(mock_settings)

    # 1. Manually establish a virtual position
    # wallet_address, coin, direction
    key = "0xleader|BTC|LONG"
    engine.positions[key] = VirtualPosition(
        wallet="0xleader",
        coin="BTC",
        direction="LONG",
        size=10.0, # Virtual size
        avg_price=50000.0,
        entry_costs=1.0,
        entry_at_ms=1000,
        source_delta_ids=["1"]
    )
    engine.running_equity = 1000.0

    # 2. Simulate a leader REDUCE delta: closed 50% of his size
    # Let's say leader had 2.0, and closed 1.0
    delta = PositionDeltaModel(
        wallet_address="0xleader",
        coin="BTC",
        action="REDUCE",
        previous_size=2.0,
        delta_size=1.0,
        price=55000.0,
        exchange_ts=2000
    )

    # We don't need mid_prices for pure exit logic
    engine.process_deltas([delta], mid_prices={}, now_ms=3000)

    # 3. Verify virtual position size is halved
    pos = engine.positions.get(key)
    assert pos is not None
    assert pos.size == 5.0 # 50% of 10.0

    # 4. Simulate leader CLOSE delta
    close_delta = PositionDeltaModel(
        wallet_address="0xleader",
        coin="BTC",
        action="CLOSE_LONG",
        previous_size=1.0,
        delta_size=1.0,
        price=56000.0,
        exchange_ts=4000
    )

    engine.process_deltas([close_delta], mid_prices={}, now_ms=5000)
    assert key not in engine.positions
