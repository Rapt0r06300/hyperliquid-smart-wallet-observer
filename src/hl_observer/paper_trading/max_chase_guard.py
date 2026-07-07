"""Max-chase guard (V12, repo 04): refuse a copy when price has run too far from the leader.

If the current price has already moved more than max_chase_bps past the leader's entry (in
the trade direction), copying now chases a degraded price -> block. Pure / deterministic.
"""

from __future__ import annotations


def chase_bps(leader_entry_price: float, current_price: float, side: str) -> float | None:
    if leader_entry_price is None or current_price is None or leader_entry_price <= 0:
        return None
    move = (current_price - leader_entry_price) / leader_entry_price * 10_000.0
    # adverse chase = price already moved in the trade's favour beyond entry
    return move if str(side).upper() in {"LONG", "BUY"} else -move


def max_chase_exceeded(leader_entry_price: float, current_price: float, side: str, *, max_chase_bps: float = 18.0) -> bool:
    c = chase_bps(leader_entry_price, current_price, side)
    return c is not None and c > float(max_chase_bps)


__all__ = ["chase_bps", "max_chase_exceeded"]
