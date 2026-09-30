from hl_observer.edge.edge_remaining import compute_edge_remaining
from hl_observer.hyperliquid.schemas import EdgeRemainingInputs, SignalDecision


def test_edge_remaining_negative_rejected():
    edge = compute_edge_remaining(
        EdgeRemainingInputs(
            leader_expected_move_bps=5,
            taker_fee_bps=4,
            spread_cost_bps=3,
            estimated_slippage_bps=4,
        ),
        min_edge_required_bps=8,
    )

    assert edge.edge_remaining_bps <= 0
    assert edge.decision == SignalDecision.REJECT_EDGE_NEGATIVE


def test_edge_remaining_too_small_rejected():
    edge = compute_edge_remaining(
        EdgeRemainingInputs(
            leader_expected_move_bps=12,
            taker_fee_bps=2,
            spread_cost_bps=1,
            estimated_slippage_bps=2,
        ),
        min_edge_required_bps=10,
    )

    assert 0 < edge.edge_remaining_bps < 10
    assert edge.decision == SignalDecision.REJECT_EDGE_TOO_SMALL
