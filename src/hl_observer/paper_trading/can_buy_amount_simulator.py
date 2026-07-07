"""Estimate how much notional can be filled from available book depth."""

from __future__ import annotations


def can_buy_amount_usdt(*, asks: tuple[tuple[float, float], ...], max_slippage_price: float) -> float:
    total = 0.0
    for price, size in asks:
        p = float(price or 0.0)
        s = float(size or 0.0)
        if p <= 0 or s <= 0 or p > float(max_slippage_price):
            continue
        total += p * s
    return round(total, 8)


def can_sell_amount_usdt(*, bids: tuple[tuple[float, float], ...], min_slippage_price: float) -> float:
    total = 0.0
    for price, size in bids:
        p = float(price or 0.0)
        s = float(size or 0.0)
        if p <= 0 or s <= 0 or p < float(min_slippage_price):
            continue
        total += p * s
    return round(total, 8)


__all__ = ["can_buy_amount_usdt", "can_sell_amount_usdt"]
