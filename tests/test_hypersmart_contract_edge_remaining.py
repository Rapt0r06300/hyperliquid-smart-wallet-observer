import pytest
from hyper_smart_observer.copy_mode.edge import compute_edge_remaining_bps
from hyper_smart_observer.copy_mode.copy_models import EdgeInputs, DeltaAction

@pytest.mark.contract
def test_contract_edge_remaining_formula():
    """
    Contract: Edge calculation must incorporate leader edge and degradation.
    """
    inputs = EdgeInputs(
        leader_expected_edge_bps=50.0,
        leader_consistency_factor=1.0,
        signal_freshness_factor=1.0,
        delay_cost_bps=5.0,
        spread_bps=2.0,
        slippage_bps=3.0,
        fee_bps=4.0,
        liquidity_penalty_bps=1.0,
        adverse_selection_penalty_bps=1.0,
        crowding_penalty_bps=1.0,
        funding_penalty_bps=1.0
    )
    edge, degradation, reasons = compute_edge_remaining_bps(inputs)
    assert edge is not None
    assert isinstance(edge, float)
    assert edge < 50.0, "Contract: Edge must be degraded by costs"
    assert degradation > 0, "Contract: Degradation should be positive"

@pytest.mark.contract
def test_contract_edge_unmeasurable_refusal():
    """
    Contract: A signal with unmeasurable leader edge must be refused.
    """
    from hyper_smart_observer.copy_mode.copy_models import NoTradeReason
    inputs = EdgeInputs(
        leader_expected_edge_bps=None,
        leader_consistency_factor=1.0,
        signal_freshness_factor=1.0
    )
    edge, degradation, reasons = compute_edge_remaining_bps(inputs)
    assert edge is None
    assert NoTradeReason.EDGE_UNMEASURABLE.value in reasons
