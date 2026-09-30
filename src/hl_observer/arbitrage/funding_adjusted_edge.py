"""Funding-adjusted edge for paper-only simulations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FundingAdjustedEdge:
    gross_edge_bps: float
    funding_carry_bps: float
    adjusted_edge_bps: float
    reason: str


def funding_adjusted_edge_bps(
    *,
    gross_edge_bps: float,
    funding_rate: float,
    side: str,
    intervals: float = 1.0,
) -> FundingAdjustedEdge:
    """Convert funding rate into bps carry and add it to directional edge.

    Positive adjusted edge means funding helps the paper position; negative
    carry means funding is a cost. The caller still applies full risk gates.
    """

    s = str(side or "").upper()
    rate_bps = float(funding_rate or 0.0) * 10_000.0 * float(intervals or 0.0)
    if s in {"LONG", "BUY"}:
        carry = -rate_bps
    elif s in {"SHORT", "SELL"}:
        carry = rate_bps
    else:
        return FundingAdjustedEdge(float(gross_edge_bps or 0.0), 0.0, float(gross_edge_bps or 0.0), "SIDE_UNKNOWN")
    adjusted = float(gross_edge_bps or 0.0) + carry
    return FundingAdjustedEdge(round(float(gross_edge_bps or 0.0), 8), round(carry, 8), round(adjusted, 8), "OK")


__all__ = ["FundingAdjustedEdge", "funding_adjusted_edge_bps"]
