from __future__ import annotations

import random
import time
from typing import Any


def correlated_count_reason(observer: Any, market: str, side: str) -> str | None:
    if not getattr(observer.config, "correlation_gate_enabled", True):
        return None
    from hyper_smart_observer.dydx_v4.market_regime import correlation_group

    group = correlation_group(market)
    count = 0
    notional = 0.0
    for pos in observer._open_positions.values():
        if str(pos.side).upper() != str(side).upper():
            continue
        if correlation_group(pos.market_id) != group:
            continue
        count += 1
        notional += abs(float(pos.size or 0.0))
    max_count = int(getattr(observer.config, "max_correlated_same_side", 5) or 5)
    if count >= max_count:
        return f"CORRELATED_COUNT group={group} side={side} count={count}>={max_count} notional={notional:.2f}"
    max_notional = float(getattr(observer.config, "max_correlated_exposure_usdc", 0.0) or 0.0)
    if max_notional > 0 and notional >= max_notional:
        return f"CORRELATED_NOTIONAL group={group} side={side} notional={notional:.2f}>={max_notional:.2f} count={count}"
    return None


def neutral_demo_price(existing: float, base: float, seed_seconds: int | None = None) -> float:
    rng = random.Random(seed_seconds if seed_seconds is not None else int(time.time()) // 5)
    price = float(existing or base) * (1.0 + rng.uniform(-0.0015, 0.0015))
    if abs(price - base) / base > 0.05:
        price = base * (1.0 + rng.uniform(-0.02, 0.02))
    return round(price, 4)


def next_pyramid_index(open_positions: dict, market: str, side: str) -> int:
    prefix = f"{market}:{side}:add"
    used: set[int] = set()
    for key in open_positions:
        text = str(key)
        if text.startswith(prefix):
            try:
                used.add(int(text[len(prefix):]))
            except ValueError:
                continue
    idx = 1
    while idx in used:
        idx += 1
    return idx


__all__ = ["correlated_count_reason", "neutral_demo_price", "next_pyramid_index"]
