"""Normalize/match market symbols across sources."""

from __future__ import annotations


ALIASES = {
    "BTC-PERP": "BTC",
    "BTC-USD": "BTC",
    "BTC/USDC": "BTC",
    "ETH-PERP": "ETH",
    "ETH-USD": "ETH",
    "ETH/USDC": "ETH",
}


def match_market_symbol(symbol: str, aliases: dict[str, str] | None = None) -> str:
    raw = str(symbol or "").upper().strip()
    table = {**ALIASES, **(aliases or {})}
    if raw in table:
        return table[raw].upper()
    for sep in ("-", "/", "_"):
        if sep in raw:
            return raw.split(sep)[0].upper()
    return raw


__all__ = ["ALIASES", "match_market_symbol"]
