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


def maker_rebate_receipt(*, execution_style: object, rebate_bps: object, source: object) -> dict[str, object]:
    """Refuse maker rebates unless the observed fee source explicitly supports them."""
    if str(execution_style).strip().lower() != "maker":
        return {"status": "UNMEASURABLE", "reason": "NOT_MAKER_EXECUTION"}
    if isinstance(rebate_bps, bool) or not isinstance(rebate_bps, (int, float)) or not math.isfinite(float(rebate_bps)) or float(rebate_bps) < 0:
        return {"status": "UNMEASURABLE", "reason": "REBATE_VALUE_INVALID"}
    if not isinstance(source, str) or not source.strip():
        return {"status": "UNMEASURABLE", "reason": "REBATE_SOURCE_MISSING"}
    return {"status": "PROVEN", "rebate_bps": round(float(rebate_bps), 10), "source": source.strip(), "real_execution": False}


__all__ = ["FeeSchedule", "calculate_fee_usdt", "maker_rebate_receipt"]
