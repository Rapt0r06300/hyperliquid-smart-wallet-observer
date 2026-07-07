from __future__ import annotations


def compute_fee_usdc(notional_usdc: float, fee_bps: float) -> float:
    return round(max(0.0, float(notional_usdc)) * max(0.0, float(fee_bps)) / 10_000.0, 10)


__all__ = ["compute_fee_usdc"]
