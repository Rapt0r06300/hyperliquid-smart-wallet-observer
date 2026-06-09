import pytest
from hyper_smart_observer.simulation.simulation_models import (
    SimulationIntent, SimulationAction, SimulationSide, SimulationRunMode, SimulationSourceQuality
)
from hyper_smart_observer.simulation.simulation_engine import SimulationEngine
from src.hl_observer.copying.realtime_magic_score import (
    score_realtime_copy_candidate, RealtimeCopyScoreInput, RealtimeCopyRiskConfig
)

def test_stale_signal_rejection():
    # Test strict freshness gate (4s/8s)
    config = RealtimeCopyRiskConfig(max_signal_age_ms=4000, hard_max_signal_age_ms=8000, min_edge_required_bps=10.0)

    # 0.4s signal -> ACCEPT (freshness = 0.9)
    inputs_fresh = RealtimeCopyScoreInput(
        action_type="OPEN_LONG", direction="LONG", leader_expected_edge_bps=100.0,
        leader_consistency_factor=1.0, signal_age_ms=400, consensus_wallets=2, # consensus 2+ avoids single wallet penalty
        liquidity_score=1.0, leader_score=80.0, leader_reference_price=100.0,
        current_mid=100.0, leader_notional_usdt=10.0, current_open_exposure_usdt=0.0,
        current_open_positions=0, max_open_positions=3
    )
    score_fresh = score_realtime_copy_candidate(inputs_fresh, config=config)
    assert score_fresh.accepted is True, f"Reasons: {score_fresh.refusal_reasons}"

    # 5s signal -> REJECT (STALE_SIGNAL)
    inputs_stale = RealtimeCopyScoreInput(
        action_type="OPEN_LONG", direction="LONG", leader_expected_edge_bps=100.0,
        leader_consistency_factor=1.0, signal_age_ms=5000, consensus_wallets=2,
        liquidity_score=1.0, leader_score=80.0, leader_reference_price=100.0,
        current_mid=100.0, leader_notional_usdt=10.0, current_open_exposure_usdt=0.0,
        current_open_positions=0, max_open_positions=3
    )
    score_stale = score_realtime_copy_candidate(inputs_stale, config=config)
    assert score_stale.accepted is False
    assert "STALE_SIGNAL" in score_stale.refusal_reasons

    # 9s signal -> REJECT (HARD_STALE_SIGNAL)
    inputs_hard_stale = RealtimeCopyScoreInput(
        action_type="OPEN_LONG", direction="LONG", leader_expected_edge_bps=100.0,
        leader_consistency_factor=1.0, signal_age_ms=9000, consensus_wallets=2,
        liquidity_score=1.0, leader_score=80.0, leader_reference_price=100.0,
        current_mid=100.0, leader_notional_usdt=10.0, current_open_exposure_usdt=0.0,
        current_open_positions=0, max_open_positions=3
    )
    score_hard_stale = score_realtime_copy_candidate(inputs_hard_stale, config=config)
    assert score_hard_stale.accepted is False
    assert "HARD_STALE_SIGNAL" in score_hard_stale.refusal_reasons

def test_fee_drag_prevention():
    # Test edge requirement: max(30 bps, 3x costs)
    config = RealtimeCopyRiskConfig(min_edge_required_bps=30.0, fee_bps=4.0, spread_bps=3.0, slippage_bps=5.0)
    # Total costs approx: 4+3+5+2(penalty) = 14 bps. 3x = 42 bps.

    # Edge 35 bps < 42 bps -> REJECT
    inputs_low_edge = RealtimeCopyScoreInput(
        action_type="OPEN_LONG", direction="LONG", leader_expected_edge_bps=35.0,
        leader_consistency_factor=1.0, signal_age_ms=0, consensus_wallets=2,
        liquidity_score=1.0, leader_score=80.0, leader_reference_price=100.0,
        current_mid=100.0, leader_notional_usdt=10.0, current_open_exposure_usdt=0.0,
        current_open_positions=0, max_open_positions=3
    )
    score_low_edge = score_realtime_copy_candidate(inputs_low_edge, config=config)
    assert score_low_edge.accepted is False
    assert "EDGE_REMAINING_TOO_LOW_VS_COSTS" in score_low_edge.refusal_reasons

    # Edge 60 bps > 42 bps -> ACCEPT
    inputs_high_edge = RealtimeCopyScoreInput(
        action_type="OPEN_LONG", direction="LONG", leader_expected_edge_bps=60.0,
        leader_consistency_factor=1.0, signal_age_ms=0, consensus_wallets=2,
        liquidity_score=1.0, leader_score=80.0, leader_reference_price=100.0,
        current_mid=100.0, leader_notional_usdt=10.0, current_open_exposure_usdt=0.0,
        current_open_positions=0, max_open_positions=3
    )
    score_high_edge = score_realtime_copy_candidate(inputs_high_edge, config=config)
    assert score_high_edge.accepted is True

def test_asset_blacklist():
    engine = SimulationEngine()
    intent = SimulationIntent(
        wallet_address="0x123", coin="CASH:WTI", side=SimulationSide.LONG,
        action=SimulationAction.OPEN, reference_price=100.0, requested_notional=50.0,
        observed_at_ms=1000, signal_id="sig1", run_mode=SimulationRunMode.LIVE
    )
    decision = engine.apply(intent)
    assert decision.accepted is False
    assert "COIN_BLACKLISTED" in decision.reason

def test_pnl_accounting_short():
    engine = SimulationEngine()
    # Use REPLAY mode to avoid now_ms() freshness check in tests
    # Open SHORT at 100
    intent_open = SimulationIntent(
        wallet_address="0x123", coin="BTC", side=SimulationSide.SHORT,
        action=SimulationAction.OPEN, reference_price=100.0, requested_notional=100.0,
        observed_at_ms=1000, signal_id="sig1", run_mode=SimulationRunMode.REPLAY
    )
    engine.apply(intent_open)

    # Close SHORT at 90 (Profit)
    intent_close = SimulationIntent(
        wallet_address="0x123", coin="BTC", side=SimulationSide.SHORT,
        action=SimulationAction.CLOSE, reference_price=90.0, requested_notional=100.0,
        observed_at_ms=2000, signal_id="sig2", run_mode=SimulationRunMode.REPLAY
    )
    decision = engine._reduce_or_close(intent_close)
    assert decision.accepted is True
    fill = engine.fills[-1]
    assert fill.realized_pnl > 0
