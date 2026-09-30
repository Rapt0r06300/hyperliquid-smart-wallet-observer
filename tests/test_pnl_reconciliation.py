from __future__ import annotations

from hl_observer.simulation.pnl_reconciliation import reconcile_pnl


def test_pnl_reconciliation_accepts_exact_equation():
    result = reconcile_pnl(
        starting_balance_usdc=1000,
        realized_pnl_usdc=12,
        unrealized_pnl_usdc=-3,
        fees_paid_usdc=1.5,
        funding_net_usdc=0.25,
        actual_equity_usdc=1007.75,
    )

    assert result.ok
    assert result.diff_usdc == 0


def test_pnl_reconciliation_warns_on_mismatch():
    result = reconcile_pnl(
        starting_balance_usdc=1000,
        realized_pnl_usdc=1,
        unrealized_pnl_usdc=1,
        fees_paid_usdc=0,
        funding_net_usdc=0,
        actual_equity_usdc=1000,
    )

    assert not result.ok
    assert result.warnings == ("PNL_RECONCILIATION_MISMATCH",)
