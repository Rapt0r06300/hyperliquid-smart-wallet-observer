from __future__ import annotations


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


__all__ = ["compute_funding_payment_usdc"]
