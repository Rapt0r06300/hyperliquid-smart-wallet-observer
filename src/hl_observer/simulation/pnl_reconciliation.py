from __future__ import annotations

import math
from dataclasses import dataclass, field

from hl_observer.economics.numeric import (
    USD_RECONCILIATION_ABS_TOLERANCE,
    decimal_value,
    float_not_above,
)


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
    tolerance_usdc: float = float(USD_RECONCILIATION_ABS_TOLERANCE),
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
    parsed = tuple(decimal_value(value) for value in values)
    if any(value is None for value in parsed) or parsed[-1] < 0:
        return PnlReconciliation(False, 0.0, 0.0, 0.0, ("PNL_EVIDENCE_NONFINITE",))

    starting, realized, unrealized, fees, funding, actual, tolerance = parsed
    if tolerance > USD_RECONCILIATION_ABS_TOLERANCE:
        return PnlReconciliation(
            False,
            0.0,
            0.0,
            0.0,
            ("PNL_TOLERANCE_OUT_OF_BOUNDS",),
        )
    expected = starting + realized + unrealized - fees + funding
    diff = actual - expected
    warnings: list[str] = []
    if abs(diff) > tolerance:
        warnings.append("PNL_RECONCILIATION_MISMATCH")
    expected_float = float_not_above(expected)
    actual_float = float_not_above(actual)
    diff_float = float(diff)
    if (
        expected_float is None
        or actual_float is None
        or not all(math.isfinite(value) for value in (expected_float, actual_float, diff_float))
    ):
        return PnlReconciliation(False, 0.0, 0.0, 0.0, ("PNL_EVIDENCE_NONFINITE",))
    return PnlReconciliation(
        ok=not warnings,
        expected_equity_usdc=expected_float,
        actual_equity_usdc=actual_float,
        diff_usdc=diff_float,
        warnings=tuple(warnings),
    )


__all__ = ["PnlReconciliation", "reconcile_pnl"]
