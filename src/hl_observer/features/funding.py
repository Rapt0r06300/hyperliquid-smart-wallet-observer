"""V15 #194 — Funding filter + funding carry in paper PnL (Hyperliquid carry).

Avoid paying a very adverse funding rate; fold the funding carry into paper PnL honestly
(longs pay when funding>0, shorts receive, and vice-versa). Pure; rates are per funding
interval (HL ~hourly/8h depending on config) — the caller supplies the interval count.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FundingFilter:
    ok: bool
    reason: str | None
    pays_funding: bool          # True if our side PAYS at this rate


def funding_filter(
    *,
    funding_rate: float,        # per interval, fraction (e.g. 0.0001 = 1 bp)
    side: str,
    max_adverse_rate: float = 0.0005,
) -> FundingFilter:
    s = str(side or "").upper()
    # long pays when rate>0; short pays when rate<0
    pays = (s in {"LONG", "BUY"} and funding_rate > 0) or (s in {"SHORT", "SELL"} and funding_rate < 0)
    if pays and abs(float(funding_rate)) > float(max_adverse_rate):
        return FundingFilter(False, "FUNDING_TOO_ADVERSE", True)
    return FundingFilter(True, None, pays)


def funding_carry_usd(
    *,
    funding_rate: float,
    notional_usd: float,
    side: str,
    intervals: float = 1.0,
) -> float:
    """Carry added to paper PnL. Positive = we RECEIVE, negative = we PAY."""
    s = str(side or "").upper()
    pay_per_interval = float(funding_rate) * float(notional_usd)   # what a long pays when rate>0
    if s in {"LONG", "BUY"}:
        carry = -pay_per_interval * float(intervals)
    else:
        carry = +pay_per_interval * float(intervals)
    return round(carry, 6)


__all__ = ["FundingFilter", "funding_filter", "funding_carry_usd"]
