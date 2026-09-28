from __future__ import annotations

import math


def compute_fee_usdc(notional_usdc: float, fee_bps: float) -> float:
    try:
        notional = float(notional_usdc)
        fee = float(fee_bps)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("fee inputs must be numeric") from exc
    if not math.isfinite(notional) or not math.isfinite(fee) or notional < 0.0 or fee < 0.0:
        raise ValueError("fee inputs must be finite and non-negative")
    return round(notional * fee / 10_000.0, 10)


__all__ = ["compute_fee_usdc"]
