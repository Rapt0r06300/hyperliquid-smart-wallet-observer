"""Fee model for paper/backtest paths."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    """Explicit venue fee schedule; missing tiers remain unmeasurable."""

    maker_bps: float | None = None
    taker_bps: float | None = None
    source: str = ""

    def round_trip_bps(self, execution_style: str) -> float | None:
        style = str(execution_style or "").strip().lower()
        if style not in {"maker", "taker"}:
            return None
        value = self.maker_bps if style == "maker" else self.taker_bps
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(value) or value < 0.0:
            return None
        return round(value * 2.0, 10)

def calculate_fee_usdt(notional_usdt: float, *, fee_bps: float) -> float:
    return round(abs(float(notional_usdt)) * float(fee_bps) / 10_000.0, 10)


__all__ = ["FeeSchedule", "calculate_fee_usdt"]
