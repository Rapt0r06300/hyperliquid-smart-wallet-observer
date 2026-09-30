"""Exit paper hedge/copy when price divergence becomes too large."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PriceDivergenceExitDecision:
    should_exit: bool
    divergence_pct: float
    reason: str | None


def price_divergence_exit(
    *,
    reference_price: float,
    current_price: float,
    max_divergence_pct: float = 2.0,
) -> PriceDivergenceExitDecision:
    ref = float(reference_price or 0.0)
    cur = float(current_price or 0.0)
    if ref <= 0 or cur <= 0:
        return PriceDivergenceExitDecision(True, 0.0, "PRICE_DIVERGENCE_INPUT_INVALID")
    div = abs(cur / ref - 1.0) * 100.0
    if div >= float(max_divergence_pct):
        return PriceDivergenceExitDecision(True, round(div, 8), "PRICE_DIVERGENCE_EXIT")
    return PriceDivergenceExitDecision(False, round(div, 8), None)


__all__ = ["PriceDivergenceExitDecision", "price_divergence_exit"]
