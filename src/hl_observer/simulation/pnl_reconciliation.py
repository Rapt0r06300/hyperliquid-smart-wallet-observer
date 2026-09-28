from __future__ import annotations

from dataclasses import dataclass, field
import math


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
    values = (
        starting_balance_usdc,
        realized_pnl_usdc,
        unrealized_pnl_usdc,
        fees_paid_usdc,
        funding_net_usdc,
        actual_equity_usdc,
        tolerance_usdc,
    )
    try:
        parsed = tuple(float(value) for value in values)
    except (TypeError, ValueError, OverflowError):
        parsed = ()
    if len(parsed) != len(values) or any(not math.isfinite(value) for value in parsed) or parsed[-1] < 0.0:
        return PnlReconciliation(False, 0.0, 0.0, 0.0, ("PNL_EVIDENCE_NONFINITE",))

    starting, realized, unrealized, fees, funding, actual, tolerance = parsed
    expected = starting + realized + unrealized - fees + funding
    diff = actual - expected
    warnings: list[str] = []
    if abs(diff) > tolerance:
        warnings.append("PNL_RECONCILIATION_MISMATCH")
    return PnlReconciliation(
        ok=not warnings,
        expected_equity_usdc=round(expected, 10),
        actual_equity_usdc=round(actual, 10),
        diff_usdc=round(diff, 10),
        warnings=tuple(warnings),
    )


__all__ = ["PnlReconciliation", "reconcile_pnl"]
