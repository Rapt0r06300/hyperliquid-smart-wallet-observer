from hl_observer.copy_wallet.slippage_budget import evaluate_slippage_budget
from hl_observer.copy_wallet.wallet_tier import tier_for_wallet_score


def test_slippage_budget_accepts_clean_execution_costs() -> None:
    tier = tier_for_wallet_score(0.95, 0.95)
    decision = evaluate_slippage_budget(
        requested_budget_bps=18,
        tier=tier,
        spread_bps=1.0,
        estimated_slippage_bps=2.0,
        latency_penalty_bps=1.0,
    )

    assert decision.accepted is True
    assert decision.total_degradation_bps == 4.0


def test_slippage_budget_rejects_copy_degradation() -> None:
    tier = tier_for_wallet_score(0.95, 0.95)
    decision = evaluate_slippage_budget(
        requested_budget_bps=18,
        tier=tier,
        spread_bps=20.0,
        estimated_slippage_bps=18.0,
        latency_penalty_bps=8.0,
    )

    assert decision.accepted is False
    assert "SLIPPAGE_BUDGET_EXCEEDED" in decision.reason_codes
    assert "COPY_DEGRADATION_TOO_HIGH" in decision.reason_codes
