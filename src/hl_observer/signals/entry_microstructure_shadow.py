"""V14 #179 — OBI + eat-flow as SHADOW confirmation in entry scoring.

Composes the existing OBI signal with an eat-flow (aggressor imbalance) ratio to produce a
context-only microstructure read: does fast order-flow CONFIRM the intended side? It decides
nothing alone (shadow); the scorer/gate keep the final say. Pure / read-only.
"""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.signals.obi_signal import order_book_imbalance, obi_signal


def eat_flow_ratio(aggressive_buy_usd: float, aggressive_sell_usd: float) -> float:
    """Aggressor imbalance in [-1, +1]: +1 = buyers lifting offers, -1 = sellers hitting bids."""
    b = max(0.0, float(aggressive_buy_usd))
    s = max(0.0, float(aggressive_sell_usd))
    tot = b + s
    if tot <= 0.0:
        return 0.0
    return round((b - s) / tot, 6)


@dataclass(frozen=True, slots=True)
class MicrostructureShadow:
    obi: float
    obi_signal: str           # LONG | SHORT | FLAT
    eat_flow: float
    micro_side: str           # net microstructure side
    aligned: bool | None      # confirms the intended side? None if side unknown
    context_only: bool = True


def entry_microstructure_shadow(
    *,
    bid_sizes: list[float] | None,
    ask_sizes: list[float] | None,
    aggressive_buy_usd: float = 0.0,
    aggressive_sell_usd: float = 0.0,
    side: str | None = None,
    obi_threshold: float = 0.2,
) -> MicrostructureShadow:
    obi = order_book_imbalance(bid_sizes or [], ask_sizes or [])
    obi_sig = obi_signal(obi, threshold=obi_threshold)
    eat = eat_flow_ratio(aggressive_buy_usd, aggressive_sell_usd)
    blend = (obi + eat) / 2.0
    micro_side = "LONG" if blend >= obi_threshold else ("SHORT" if blend <= -obi_threshold else "FLAT")
    aligned: bool | None = None
    s = str(side or "").upper()
    if s in {"LONG", "BUY"}:
        aligned = micro_side == "LONG"
    elif s in {"SHORT", "SELL"}:
        aligned = micro_side == "SHORT"
    return MicrostructureShadow(
        obi=obi, obi_signal=obi_sig, eat_flow=eat, micro_side=micro_side, aligned=aligned,
    )


__all__ = ["eat_flow_ratio", "MicrostructureShadow", "entry_microstructure_shadow"]
