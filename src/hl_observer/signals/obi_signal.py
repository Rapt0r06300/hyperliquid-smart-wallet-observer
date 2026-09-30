"""V13 #155 — Orderbook Imbalance (OBI) as a standalone signal (Harrier A2)."""

from __future__ import annotations


def order_book_imbalance(bid_sizes: list[float], ask_sizes: list[float]) -> float:
    """OBI in [-1, +1]: +1 = all bids (buy pressure), -1 = all asks (sell pressure)."""
    b = sum(max(0.0, float(x)) for x in (bid_sizes or []))
    a = sum(max(0.0, float(x)) for x in (ask_sizes or []))
    tot = b + a
    if tot <= 0.0:
        return 0.0
    return round((b - a) / tot, 6)


def obi_signal(obi: float, *, threshold: float = 0.2) -> str:
    if obi >= threshold:
        return "LONG"
    if obi <= -threshold:
        return "SHORT"
    return "FLAT"


__all__ = ["order_book_imbalance", "obi_signal"]
