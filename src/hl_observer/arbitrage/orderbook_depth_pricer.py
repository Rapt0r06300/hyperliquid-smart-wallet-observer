"""Average price estimation from depth levels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class DepthPriceResult:
    average_price: float | None
    filled_notional_usdt: float
    partial: bool


def price_from_depth(levels: Iterable[dict[str, float]], *, target_notional_usdt: float) -> DepthPriceResult:
    remaining = float(target_notional_usdt)
    cost = 0.0
    filled = 0.0
    for level in levels:
        price = float(level.get("price") or level.get("px") or 0.0)
        size = float(level.get("size") or level.get("sz") or 0.0)
        if price <= 0 or size <= 0 or remaining <= 0:
            continue
        level_notional = price * size
        take = min(level_notional, remaining)
        cost += take
        filled += take / price
        remaining -= take
    if filled <= 0:
        return DepthPriceResult(average_price=None, filled_notional_usdt=0.0, partial=True)
    return DepthPriceResult(average_price=round(cost / filled, 10), filled_notional_usdt=round(cost, 8), partial=remaining > 1e-9)


__all__ = ["DepthPriceResult", "price_from_depth"]
