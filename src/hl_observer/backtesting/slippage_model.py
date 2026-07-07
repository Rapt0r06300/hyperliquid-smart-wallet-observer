"""Slippage model for paper/backtest paths."""

from __future__ import annotations


def apply_slippage(price: float, *, side: str, slippage_bps: float) -> float:
    mult = 1.0 + float(slippage_bps) / 10_000.0
    side_u = str(side).upper()
    if side_u in {"SHORT", "SELL"}:
        mult = 1.0 - float(slippage_bps) / 10_000.0
    return round(float(price) * mult, 10)


__all__ = ["apply_slippage"]
