"""Local blacklist helper for paper-only universe filtering."""

from __future__ import annotations

from typing import Iterable


def filter_blacklisted(coins: Iterable[str], blacklist: Iterable[str]) -> tuple[str, ...]:
    blocked = {str(coin).upper() for coin in blacklist}
    return tuple(coin for coin in (str(coin).upper() for coin in coins) if coin and coin not in blocked)


__all__ = ["filter_blacklisted"]
