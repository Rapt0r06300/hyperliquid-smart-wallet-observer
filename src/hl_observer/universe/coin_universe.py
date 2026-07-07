"""Whitelist/blacklist coin universe for paper strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True, slots=True)
class CoinUniverse:
    selected: tuple[str, ...]
    rejected: tuple[dict[str, object], ...] = field(default_factory=tuple)


def build_coin_universe(
    coins: Iterable[str],
    *,
    whitelist: Iterable[str] | None = None,
    blacklist: Iterable[str] | None = None,
    max_coins: int | None = None,
) -> CoinUniverse:
    white = {str(c).upper() for c in whitelist or ()}
    black = {str(c).upper() for c in blacklist or ()}
    selected: list[str] = []
    rejected: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in coins:
        coin = str(raw or "").upper().strip()
        if not coin:
            continue
        if coin in seen:
            rejected.append({"coin": coin, "reason": "DUPLICATE_COIN"})
            continue
        seen.add(coin)
        if white and coin not in white:
            rejected.append({"coin": coin, "reason": "NOT_IN_WHITELIST"})
            continue
        if coin in black:
            rejected.append({"coin": coin, "reason": "BLACKLISTED_COIN"})
            continue
        if max_coins is not None and len(selected) >= int(max_coins):
            rejected.append({"coin": coin, "reason": "COIN_UNIVERSE_LIMIT"})
            continue
        selected.append(coin)
    return CoinUniverse(selected=tuple(selected), rejected=tuple(rejected))


__all__ = ["CoinUniverse", "build_coin_universe"]
