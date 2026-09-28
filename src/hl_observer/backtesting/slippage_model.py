"""Slippage model for paper/backtest paths."""

from __future__ import annotations

import math


def apply_slippage(price: float, *, side: str, slippage_bps: float) -> float:
    if (isinstance(price, bool) or not math.isfinite(float(price)) or float(price) <= 0.0
            or isinstance(slippage_bps, bool) or not math.isfinite(float(slippage_bps))
            or float(slippage_bps) < 0.0):
        raise ValueError("price and slippage_bps must be finite and non-negative")
    side_u = str(side).upper()
    if side_u not in {"LONG", "SHORT", "BUY", "SELL"}:
        raise ValueError("unsupported side")
    mult = 1.0 + float(slippage_bps) / 10_000.0
    if side_u in {"SHORT", "SELL"}:
        mult = 1.0 - float(slippage_bps) / 10_000.0
    return round(float(price) * mult, 10)


__all__ = ["apply_slippage"]
