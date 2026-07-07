"""Track paper funding payments."""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.features.funding import funding_carry_usd


@dataclass(frozen=True, slots=True)
class FundingPayment:
    coin: str
    side: str
    notional_usdt: float
    funding_rate: float
    intervals: float
    pnl_usdt: float


def compute_funding_payment(*, coin: str, side: str, notional_usdt: float, funding_rate: float, intervals: float = 1.0) -> FundingPayment:
    pnl = funding_carry_usd(funding_rate=funding_rate, notional_usd=notional_usdt, side=side, intervals=intervals)
    return FundingPayment(str(coin).upper(), str(side).upper(), round(float(notional_usdt or 0.0), 8), float(funding_rate or 0.0), float(intervals or 0.0), pnl)


__all__ = ["FundingPayment", "compute_funding_payment"]
