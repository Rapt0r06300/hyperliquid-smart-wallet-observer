"""Fee model for paper/backtest paths."""

from __future__ import annotations


def calculate_fee_usdt(notional_usdt: float, *, fee_bps: float) -> float:
    return round(abs(float(notional_usdt)) * float(fee_bps) / 10_000.0, 10)


__all__ = ["calculate_fee_usdt"]
