import pytest
from pydantic import ValidationError

from hl_observer.backtest.ledger_replay_v9 import ReplayConfig
from hl_observer.edge.edge_remaining import compute_edge_remaining
from hl_observer.hyperliquid.schemas import EdgeRemainingInputs, SignalDecision


def test_edge_remaining_negative_rejected():
    edge = compute_edge_remaining(
        EdgeRemainingInputs(
            leader_expected_move_bps=5,
            taker_fee_bps=4,
            spread_cost_bps=3,
            estimated_slippage_bps=4,
            latency_decay_bps=0,
            adverse_selection_bps=0,
            funding_expected_cost_bps=0,
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
            latency_decay_bps=0,
            adverse_selection_bps=0,
            funding_expected_cost_bps=0,
        ),
        min_edge_required_bps=10,
    )

    assert 0 < edge.edge_remaining_bps < 10
    assert edge.decision == SignalDecision.REJECT_EDGE_TOO_SMALL


def test_edge_remaining_charges_round_trip_fee_and_slippage():
    edge = compute_edge_remaining(
        EdgeRemainingInputs(
            leader_expected_move_bps=30,
            taker_fee_bps=4.5,
            spread_cost_bps=3,
            estimated_slippage_bps=5,
            latency_decay_bps=2,
            adverse_selection_bps=2,
            funding_expected_cost_bps=0,
        ),
        min_edge_required_bps=0,
    )

    # Match ReplayConfig: two taker legs, one full spread crossing, two
    # per-leg slippage estimates, plus signal-specific latency/adverse costs.
    replay_costs = ReplayConfig(fee_bps=4.5, spread_bps=3, slippage_bps=5).round_trip_cost_bps
    assert edge.costs_bps == replay_costs + 2 + 2
    assert edge.edge_remaining_bps == 30 - edge.costs_bps


def test_edge_remaining_requires_explicit_funding_cost():
    with pytest.raises(ValidationError) as exc:
        EdgeRemainingInputs(leader_expected_move_bps=30)
    missing = {error["loc"][0] for error in exc.value.errors()}
    assert {
        "taker_fee_bps",
        "spread_cost_bps",
        "estimated_slippage_bps",
        "latency_decay_bps",
        "adverse_selection_bps",
        "funding_expected_cost_bps",
    } <= missing


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_edge_remaining_rejects_non_finite_funding_cost(value):
    with pytest.raises(ValidationError, match="funding_expected_cost_bps"):
        EdgeRemainingInputs(funding_expected_cost_bps=value)


@pytest.mark.parametrize("field", ["taker_fee_bps", "spread_cost_bps", "estimated_slippage_bps"])
def test_edge_remaining_rejects_negative_execution_costs(field):
    with pytest.raises(ValidationError):
        EdgeRemainingInputs(**{field: -1.0})
