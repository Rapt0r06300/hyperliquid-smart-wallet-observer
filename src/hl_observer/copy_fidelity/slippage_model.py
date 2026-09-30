"""V15 #204 — Per-coin slippage model (worse for bigger size / thinner liquidity)."""

from __future__ import annotations


def slippage_bps(
    *,
    notional_usd: float,
    liquidity_score: float,     # 0..1 (1 = very liquid)
    base_bps: float = 1.0,
    impact_coef: float = 8.0,
    size_ref_usd: float = 1_000.0,
) -> float:
    """Slippage grows with size/size_ref and as liquidity falls toward 0.

    illiquidity = (1 - liquidity_score) clamped; impact = coef * illiquidity * (size/ref).
    """
    liq = max(0.0, min(1.0, float(liquidity_score)))
    illiquidity = 1.0 - liq
    size_factor = max(0.0, float(notional_usd)) / max(1.0, float(size_ref_usd))
    impact = float(impact_coef) * illiquidity * size_factor
    return round(float(base_bps) + impact, 6)


__all__ = ["slippage_bps"]
