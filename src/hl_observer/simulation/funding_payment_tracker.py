from __future__ import annotations

import math


def compute_funding_payment_usdc(
    *,
    side: str,
    notional_usdc: float,
    funding_rate: float,
    intervals: float = 1.0,
) -> float:
    """Return cash impact for the paper account.

    Positive value means funding received. Negative value means funding paid.
    Hyperliquid sign conventions can vary by source, so callers must pass the
    funding rate already normalized as long-pays when positive.
    """

    gross = max(0.0, float(notional_usdc)) * float(funding_rate) * max(0.0, float(intervals))
    if str(side).upper() == "LONG":
        return round(-gross, 10)
    if str(side).upper() == "SHORT":
        return round(gross, 10)
    return 0.0


def funding_boundary_receipt(
    *,
    side: object,
    notional_usdc: object,
    funding_rate: object,
    opened_at_ms: object,
    settlement_at_ms: object,
    closed_at_ms: object | None,
) -> dict[str, object]:
    """Charge only a documented settlement boundary crossed by the position."""
    values = (notional_usdc, funding_rate, opened_at_ms, settlement_at_ms)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values):
        return {"status": "UNMEASURABLE", "reason": "FUNDING_BOUNDARY_INPUT_INVALID"}
    if closed_at_ms is not None and (isinstance(closed_at_ms, bool) or not isinstance(closed_at_ms, (int, float)) or not math.isfinite(float(closed_at_ms))):
        return {"status": "UNMEASURABLE", "reason": "CLOSE_TIMESTAMP_INVALID"}
    if float(notional_usdc) < 0 or float(funding_rate) < 0 or float(settlement_at_ms) < float(opened_at_ms):
        return {"status": "UNMEASURABLE", "reason": "FUNDING_BOUNDARY_ORDER_INVALID"}
    if closed_at_ms is not None and float(closed_at_ms) <= float(opened_at_ms):
        return {"status": "UNMEASURABLE", "reason": "CLOSE_BEFORE_OPEN"}
    if str(side).upper() not in {"LONG", "SHORT"}:
        return {"status": "UNMEASURABLE", "reason": "SIDE_INVALID"}
    crossed = closed_at_ms is None or float(settlement_at_ms) < float(closed_at_ms)
    payment = compute_funding_payment_usdc(side=str(side), notional_usdc=float(notional_usdc), funding_rate=float(funding_rate), intervals=1.0 if crossed else 0.0)
    return {"status": "PROVEN", "crossed_settlement": crossed, "payment_usdc": payment, "settlement_at_ms": float(settlement_at_ms)}


__all__ = ["compute_funding_payment_usdc", "funding_boundary_receipt"]
