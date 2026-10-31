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


def test_default_reconciliation_rejects_economic_mismatch_above_decimal_tolerance():
    result = reconcile_pnl(
        starting_balance_usdc=1_000.0,
        realized_pnl_usdc=0.0,
        unrealized_pnl_usdc=0.0,
        fees_paid_usdc=0.0,
        funding_net_usdc=0.0,
        actual_equity_usdc=1_000.00005,
    )

    assert result.ok is False
    assert result.warnings == ("PNL_RECONCILIATION_MISMATCH",)


def test_reconciliation_cannot_widen_the_canonical_economic_tolerance():
    result = reconcile_pnl(
        starting_balance_usdc=1_000.0,
        realized_pnl_usdc=0.0,
        unrealized_pnl_usdc=0.0,
        fees_paid_usdc=0.0,
        funding_net_usdc=0.0,
        actual_equity_usdc=1_000.01,
        tolerance_usdc=0.02,
    )

    assert result.ok is False
    assert result.warnings == ("PNL_TOLERANCE_OUT_OF_BOUNDS",)


def test_reconciliation_does_not_round_subthreshold_equity_up_to_five():
    result = reconcile_pnl(
        starting_balance_usdc=0.0,
        realized_pnl_usdc=4.99999999996,
        unrealized_pnl_usdc=0.0,
        fees_paid_usdc=0.0,
        funding_net_usdc=0.0,
        actual_equity_usdc=4.99999999996,
    )

    assert result.ok is True
    assert result.expected_equity_usdc < 5.0
    assert result.actual_equity_usdc < 5.0
