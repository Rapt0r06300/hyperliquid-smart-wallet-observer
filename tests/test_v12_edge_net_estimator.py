from hl_observer.edge.edge_net_v12 import EdgeNetV12Inputs, estimate_edge_net_v12


def test_edge_net_v12_refuses_missing_required_market_data():
    result = estimate_edge_net_v12(
        EdgeNetV12Inputs(
            leader_reference_price=None,
            current_mid=None,
            leader_expected_edge_bps=None,
            spread_bps=None,
            slippage_bps=None,
            fee_bps=None,
        )
    )
    assert result.measurable is False
    assert result.accepted is False
    assert result.net_edge_bps is None
    assert "EDGE_UNMEASURABLE" in result.reason_codes
    assert "MID_MISSING" in result.reason_codes


def test_edge_net_v12_subtracts_all_costs_and_accepts_positive_edge():
    result = estimate_edge_net_v12(
        EdgeNetV12Inputs(
            leader_reference_price=100.0,
            current_mid=100.2,
            leader_expected_edge_bps=80.0,
            spread_bps=3.0,
            slippage_bps=4.0,
            fee_bps=4.5,
            latency_penalty_bps=2.0,
            copy_degradation_bps=5.0,
            liquidity_penalty_bps=1.0,
            volatility_penalty_bps=2.0,
            adverse_selection_penalty_bps=1.0,
            crowding_penalty_bps=1.0,
            funding_estimate_bps=1.0,
            min_edge_bps=30.0,
        )
    )
    assert result.measurable is True
    assert result.accepted is True
    assert result.total_cost_bps == 24.5
    assert result.net_edge_bps == 55.5
    assert result.reason_codes == ()


def test_edge_net_v12_rejects_low_edge_and_high_copy_degradation():
    result = estimate_edge_net_v12(
        EdgeNetV12Inputs(
            leader_reference_price=100.0,
            current_mid=101.0,
            leader_expected_edge_bps=60.0,
            spread_bps=4.0,
            slippage_bps=5.0,
            fee_bps=4.5,
            copy_degradation_bps=50.0,
            funding_estimate_bps=0.0,
            min_edge_bps=20.0,
            max_copy_degradation_bps=40.0,
        )
    )
    assert result.accepted is False
    assert result.net_edge_bps == -3.5
    assert "COPY_DEGRADATION_TOO_HIGH" in result.reason_codes
    assert "EDGE_REMAINING_TOO_LOW" in result.reason_codes
