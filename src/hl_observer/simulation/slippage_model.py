from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SlippageEstimate:
    average_price: float | None
    filled_notional_usdc: float
    missed_notional_usdc: float
    slippage_bps: float
    fill_ratio: float
    partial: bool
    missed: bool
    levels_consumed: int


def estimate_orderbook_slippage(
    *,
    side: str,
    notional_usdc: float,
    mid_price: float,
    asks: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
    bids: list[tuple[float, float]] | tuple[tuple[float, float], ...] = (),
    min_fill_ratio: float = 0.85,
) -> SlippageEstimate:
    requested = max(0.0, float(notional_usdc))
    mid = float(mid_price or 0.0)
    if requested <= 0 or mid <= 0:
        return SlippageEstimate(None, 0.0, requested, 0.0, 0.0, False, True, 0)

    use_asks = str(side).upper() in {"BUY", "LONG"}
    raw_levels = asks if use_asks else bids
    levels = _clean_levels(raw_levels, reverse=not use_asks)
    remaining = requested
    filled_notional = 0.0
    filled_qty = 0.0
    consumed = 0
    for price, size in levels:
        available = price * size
        if available <= 0:
            continue
        take = min(remaining, available)
        filled_notional += take
        filled_qty += take / price
        remaining -= take
        consumed += 1
        if remaining <= 1e-9:
            break

    if filled_notional <= 0 or filled_qty <= 0:
        return SlippageEstimate(None, 0.0, requested, 0.0, 0.0, False, True, 0)

    avg = filled_notional / filled_qty
    fill_ratio = min(1.0, filled_notional / requested)
    if use_asks:
        slippage = max(0.0, (avg / mid - 1.0) * 10_000.0)
    else:
        slippage = max(0.0, (1.0 - avg / mid) * 10_000.0)
    return SlippageEstimate(
        average_price=round(avg, 10),
        filled_notional_usdc=round(filled_notional, 10),
        missed_notional_usdc=round(max(0.0, requested - filled_notional), 10),
        slippage_bps=round(slippage, 10),
        fill_ratio=round(fill_ratio, 10),
        partial=fill_ratio < 0.999999,
        missed=fill_ratio < max(0.0, float(min_fill_ratio)),
        levels_consumed=consumed,
    )


def _clean_levels(raw_levels: object, *, reverse: bool) -> list[tuple[float, float]]:
    levels: list[tuple[float, float]] = []
    for item in raw_levels or ():
        if isinstance(item, dict):
            price = item.get("px", item.get("price", 0.0))
            size = item.get("sz", item.get("size", 0.0))
        else:
            price, size = item
        p = float(price or 0.0)
        s = float(size or 0.0)
        if p > 0 and s > 0:
            levels.append((p, s))
    return sorted(levels, key=lambda pair: pair[0], reverse=reverse)


__all__ = ["SlippageEstimate", "estimate_orderbook_slippage"]
