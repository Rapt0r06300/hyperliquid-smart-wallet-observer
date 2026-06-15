from __future__ import annotations

from hyper_smart_observer.dydx_v4.decision_intelligence_v2 import (
    BudgetState,
    SessionHealth,
    decision_intelligence_v2,
)
from hyper_smart_observer.dydx_v4.tremor_engine import TremorObservation
from hyper_smart_observer.dydx_v4.tuned_decision import TunedDecisionContext


def _strong_obs() -> TremorObservation:
    return TremorObservation(
        market_id="ETH-USD",
        direction="LONG",
        price_move_bps=35.0,
        volume_zscore=3.0,
        flow_imbalance=0.74,
        flow_volume_usdc=50_000.0,
        flow_trade_count=14,
        leading_wallets=4,
        consensus_wallets=4,
        signal_age_ms=900,
        edge_remaining_bps=15.0,
        market_regime="TRENDING",
        market_confidence=0.82,
        source="stream",
    )


def test_decision_v2_includes_director_payload() -> None:
    result = decision_intelligence_v2(
        _strong_obs(),
        health=SessionHealth(closed_trades=12, winrate=0.55, profit_factor=1.4),
        budget_state=BudgetState(),
        ctx=TunedDecisionContext(spread_bps=3.0, slippage_bps=4.0, open_positions=0),
    )

    data = result.to_dict()

    assert "director" in data
    assert data["director"]["opportunity_score"] > 0
    assert data["director"]["risk_score"] >= 0
    assert any(str(note).startswith("director_net=") for note in result.notes)


def test_director_blocks_no_edge_setup() -> None:
    obs = _strong_obs()
    obs.edge_remaining_bps = 0.0
    result = decision_intelligence_v2(
        obs,
        health=SessionHealth(closed_trades=12, winrate=0.55, profit_factor=1.4),
        budget_state=BudgetState(),
        ctx=TunedDecisionContext(spread_bps=3.0, slippage_bps=4.0, open_positions=0),
    )

    assert not result.can_open
    assert "DIRECTOR_HARD_BLOCK" in result.reasons or "DIRECTOR_NO_EDGE" in result.reasons


def test_director_reduces_under_weak_session() -> None:
    result = decision_intelligence_v2(
        _strong_obs(),
        health=SessionHealth(closed_trades=12, winrate=0.35, profit_factor=0.8, consecutive_losses=4, daily_pnl_usdc=-20.0),
        budget_state=BudgetState(),
        ctx=TunedDecisionContext(spread_bps=5.0, slippage_bps=6.0, open_positions=1),
    )

    assert result.to_dict()["director"]["risk_score"] > 0
    assert result.notional_usdc <= 100.0
