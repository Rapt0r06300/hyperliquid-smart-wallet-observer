from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PnlReconciliation:
    ok: bool
    expected_equity_usdc: float
    actual_equity_usdc: float
    diff_usdc: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


def reconcile_pnl(
    *,
    starting_balance_usdc: float,
    realized_pnl_usdc: float,
    unrealized_pnl_usdc: float,
    fees_paid_usdc: float,
    funding_net_usdc: float,
    actual_equity_usdc: float,
    tolerance_usdc: float = 0.0001,
) -> PnlReconciliation:
    expected = (
        float(starting_balance_usdc)
        + float(realized_pnl_usdc)
        + float(unrealized_pnl_usdc)
        - float(fees_paid_usdc)
        + float(funding_net_usdc)
    )
    diff = float(actual_equity_usdc) - expected
    warnings: list[str] = []
    if abs(diff) > float(tolerance_usdc):
        warnings.append("PNL_RECONCILIATION_MISMATCH")
    return PnlReconciliation(
        ok=not warnings,
        expected_equity_usdc=round(expected, 10),
        actual_equity_usdc=round(float(actual_equity_usdc), 10),
        diff_usdc=round(diff, 10),
        warnings=tuple(warnings),
    )


__all__ = ["PnlReconciliation", "reconcile_pnl"]
