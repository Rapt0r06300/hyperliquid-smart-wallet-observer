import pytest
from hyper_smart_observer.copy_mode.edge import compute_edge_remaining_bps
from hyper_smart_observer.copy_mode.copy_models import EdgeInputs, NoTradeReason

def test_edge_remaining_bps_positive():
    inputs = EdgeInputs(
        leader_expected_edge_bps=20.0,
        leader_consistency_factor=1.0,
        signal_freshness_factor=1.0,
        delay_cost_bps=2.0,
        spread_bps=1.0,
        slippage_bps=2.0,
        fee_bps=1.0,
        liquidity_penalty_bps=0.0,
        adverse_selection_penalty_bps=0.0,
        crowding_penalty_bps=0.0,
        funding_penalty_bps=0.0
    )
    edge, degradation, reasons = compute_edge_remaining_bps(inputs, min_required_bps=8.0)
    assert edge == 14.0
    assert degradation == 6.0
    assert len(reasons) == 0

def test_edge_remaining_too_low():
    inputs = EdgeInputs(
        leader_expected_edge_bps=10.0,
        leader_consistency_factor=1.0,
        signal_freshness_factor=1.0,
        delay_cost_bps=2.0,
        spread_bps=1.0,
        slippage_bps=2.0,
        fee_bps=1.0,
        liquidity_penalty_bps=0.0,
        adverse_selection_penalty_bps=0.0,
        crowding_penalty_bps=0.0,
        funding_penalty_bps=0.0
    )
    edge, degradation, reasons = compute_edge_remaining_bps(inputs, min_required_bps=8.0)
    assert edge == 4.0
    assert NoTradeReason.EDGE_REMAINING_TOO_LOW.value in reasons

def test_edge_unmeasurable():
    inputs = EdgeInputs(
        leader_expected_edge_bps=None,
        leader_consistency_factor=1.0,
        signal_freshness_factor=1.0,
        delay_cost_bps=2.0,
        spread_bps=1.0,
        slippage_bps=2.0,
        fee_bps=1.0,
        liquidity_penalty_bps=0.0,
        adverse_selection_penalty_bps=0.0,
        crowding_penalty_bps=0.0,
        funding_penalty_bps=0.0
    )
    edge, degradation, reasons = compute_edge_remaining_bps(inputs, min_required_bps=8.0)
    assert edge is None
    assert NoTradeReason.EDGE_UNMEASURABLE.value in reasons
