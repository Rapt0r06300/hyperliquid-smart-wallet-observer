from hl_observer.edge.edge_remaining import compute_edge_remaining
from hl_observer.hyperliquid.schemas import EdgeRemainingInputs, SignalDecision


def test_edge_remaining_negative_rejected():
    # edge_leader=5, fees=4, spread=3, slippage=4 => 5 - 11 = -6
    edge = compute_edge_remaining(
        EdgeRemainingInputs(
            edge_leader_bps=5,
            fees_bps=4,
            spread_bps=3,
            slippage_bps=4,
            observed_price=100.0,
        ),
        min_edge_required_bps=8,
    )

    assert edge.edge_remaining_bps <= 0
    assert edge.decision == SignalDecision.REJECT_EDGE_NEGATIVE
    assert any("edge_remaining_bps non-positive" in r for r in edge.reasons)


def test_edge_remaining_too_small_rejected():
    # edge_leader=12, fees=2, spread=1, slippage=2 => 12 - 5 = 7
    edge = compute_edge_remaining(
        EdgeRemainingInputs(
            edge_leader_bps=12,
            fees_bps=2,
            spread_bps=1,
            slippage_bps=2,
            observed_price=100.0,
        ),
        min_edge_required_bps=10,
    )

    assert 0 < edge.edge_remaining_bps < 10
    assert edge.decision == SignalDecision.REJECT_EDGE_TOO_SMALL
    assert any("below minimum" in r for r in edge.reasons)


def test_edge_remaining_multiplicative_factors():
    # edge_leader=20, consistency=0.5, freshness=0.8 => 20 * 0.5 * 0.8 = 8
    # fees=2 => 8 - 2 = 6
    edge = compute_edge_remaining(
        EdgeRemainingInputs(
            edge_leader_bps=20,
            consistency_factor=0.5,
            freshness_factor=0.8,
            fees_bps=2,
            observed_price=100.0,
        ),
        min_edge_required_bps=5,
    )

    assert edge.expected_edge_bps == 8
    assert edge.edge_remaining_bps == 6
    assert edge.decision == SignalDecision.PAPER_CANDIDATE


def test_reject_missing_leader_edge():
    edge = compute_edge_remaining(
        EdgeRemainingInputs(edge_leader_bps=0, observed_price=100.0),
        min_edge_required_bps=5,
    )
    assert edge.decision == SignalDecision.REJECT_EDGE_NEGATIVE
    assert any("missing_leader_edge" in r for r in edge.reasons)


def test_reject_stale_signal():
    edge = compute_edge_remaining(
        EdgeRemainingInputs(edge_leader_bps=20, freshness_factor=0, observed_price=100.0),
        min_edge_required_bps=5,
    )
    assert edge.decision == SignalDecision.REJECT_TOO_LATE
    assert any("signal_stale" in r for r in edge.reasons)


def test_reject_invalid_price():
    edge = compute_edge_remaining(
        EdgeRemainingInputs(edge_leader_bps=20, observed_price=0),
        min_edge_required_bps=5,
    )
    assert edge.decision == SignalDecision.REJECT_INVALID_PRICE
    assert any("invalid_price" in r for r in edge.reasons)


def test_reject_low_liquidity():
    edge = compute_edge_remaining(
        EdgeRemainingInputs(edge_leader_bps=100, liquidity_penalty_bps=51, observed_price=100.0),
        min_edge_required_bps=5,
    )
    assert edge.decision == SignalDecision.REJECT_TOO_ILLIQUID
    assert any("low_liquidity" in r for r in edge.reasons)


def test_reject_high_costs():
    # edge_leader=150, consistency=1.0, freshness=1.0 => 150
    # fees=101 => 150 - 101 = 49 (which is > min_edge_required_bps=5)
    # But costs_bps > 100 should trigger REJECT_COSTS_TOO_HIGH
    edge = compute_edge_remaining(
        EdgeRemainingInputs(edge_leader_bps=150, fees_bps=101, observed_price=100.0),
        min_edge_required_bps=5,
    )
    assert edge.decision == SignalDecision.REJECT_COSTS_TOO_HIGH
    assert any("costs_too_high" in r for r in edge.reasons)
