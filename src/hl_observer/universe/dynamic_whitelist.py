"""Dynamic whitelist based on liquidity and activity."""

from __future__ import annotations

from typing import Iterable


def build_dynamic_whitelist(markets: Iterable[dict[str, object]], *, min_volume_usdt: float = 100_000.0, min_depth_usdt: float = 10_000.0) -> tuple[str, ...]:
    coins = []
    for market in markets:
        if float(market.get("volume_usdt") or 0.0) >= min_volume_usdt and float(market.get("depth_usdt") or 0.0) >= min_depth_usdt:
            coins.append(str(market.get("coin") or "").upper())
    return tuple(sorted({coin for coin in coins if coin}))


__all__ = ["build_dynamic_whitelist"]
