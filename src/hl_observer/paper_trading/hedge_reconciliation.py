"""Reconcile two paper hedge legs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HedgeReconciliation:
    ok: bool
    skew_bps: float
    reason: str | None


def reconcile_hedge_legs(*, leg_a_notional: float, leg_b_notional: float, max_skew_bps: float = 25.0) -> HedgeReconciliation:
    a = max(0.0, float(leg_a_notional or 0.0))
    b = max(0.0, float(leg_b_notional or 0.0))
    if a <= 0 or b <= 0:
        return HedgeReconciliation(False, 0.0, "HEDGE_LEG_MISSING")
    avg = (a + b) / 2.0
    skew = abs(a - b) / avg * 10_000.0
    if skew > float(max_skew_bps):
        return HedgeReconciliation(False, round(skew, 8), "HEDGE_LEG_SKEW_TOO_HIGH")
    return HedgeReconciliation(True, round(skew, 8), None)


__all__ = ["HedgeReconciliation", "reconcile_hedge_legs"]
