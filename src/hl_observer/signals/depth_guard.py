"""V13 #155 — Depth Guard (Harrier): validate REAL orderbook liquidity BEFORE each entry."""

from __future__ import annotations


def depth_guard(*, bid_depth_usd: float, ask_depth_usd: float, side: str,
                needed_usd: float, min_depth_usd: float = 200.0,
                max_consume_fraction: float = 0.25) -> tuple[bool, str | None]:
    """Block an entry if the side we must hit is too thin to absorb our size cleanly."""
    s = str(side or "").upper()
    book_usd = float(ask_depth_usd if s in {"LONG", "BUY"} else bid_depth_usd)
    if book_usd < float(min_depth_usd):
        return False, "DEPTH_TOO_LOW"
    if float(needed_usd) > book_usd * float(max_consume_fraction):
        return False, "SIZE_EXCEEDS_DEPTH"      # our order would eat too much of the book
    return True, None


__all__ = ["depth_guard"]
