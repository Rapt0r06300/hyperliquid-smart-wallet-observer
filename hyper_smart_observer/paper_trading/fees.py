from __future__ import annotations


def calculate_fee(notional: float, fee_rate_bps: float) -> float:
    if notional < 0:
        raise ValueError("notional must be non-negative")
    if fee_rate_bps < 0:
        raise ValueError("fee_rate_bps must be non-negative")
    return notional * fee_rate_bps / 10_000.0
