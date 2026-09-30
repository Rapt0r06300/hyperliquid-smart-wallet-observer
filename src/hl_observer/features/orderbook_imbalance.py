"""Order Book Imbalance (OBI) as an autonomous signal (S4 — V9 fusion).

"The signal IS the book": compute top-of-book and multi-level depth
imbalance, then map to a directional bias with an explicit threshold.
Refresh cadence (~500 ms) is an operational concern handled by the caller;
this module is a pure transform.

SAFETY: pure. Missing/one-sided book -> NEUTRAL + low ``data_quality``.
A bias is never an order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hl_observer.features.market import extract_l2_levels, safe_float

Levels = list[tuple[float, float]]


@dataclass(frozen=True, slots=True)
class OrderBookImbalance:
    imbalance: float | None          # depth imbalance in [-1, 1]
    top_imbalance: float | None      # best bid vs best ask size, [-1, 1]
    weighted_imbalance: float | None # distance-weighted, [-1, 1]
    signal: str                      # LONG_BIAS / SHORT_BIAS / NEUTRAL
    strength: float                  # |imbalance| in [0, 1]
    levels_used: int
    data_quality: str


def _imbalance(bid: float, ask: float) -> float | None:
    total = bid + ask
    if total <= 0:
        return None
    return (bid - ask) / total


def _weighted_depth(levels: Levels, ref_price: float) -> float:
    if ref_price <= 0:
        return 0.0
    total = 0.0
    for px, sz in levels:
        if px <= 0 or sz <= 0:
            continue
        distance = abs(px - ref_price) / ref_price
        weight = 1.0 / (1.0 + distance * 100.0)
        total += px * sz * weight
    return total


def compute_obi(
    bids: Levels | None,
    asks: Levels | None,
    *,
    threshold: float = 0.2,
) -> OrderBookImbalance:
    bids = [(px, sz) for px, sz in (bids or []) if px > 0 and sz > 0]
    asks = [(px, sz) for px, sz in (asks or []) if px > 0 and sz > 0]
    if not bids or not asks:
        return OrderBookImbalance(None, None, None, "NEUTRAL", 0.0, 0, "MISSING_BOOK_SIDE")

    bid_depth = sum(px * sz for px, sz in bids)
    ask_depth = sum(px * sz for px, sz in asks)
    imbalance = _imbalance(bid_depth, ask_depth)

    top_imbalance = _imbalance(bids[0][1], asks[0][1])

    mid = (bids[0][0] + asks[0][0]) / 2.0
    w_bid = _weighted_depth(bids, mid)
    w_ask = _weighted_depth(asks, mid)
    weighted = _imbalance(w_bid, w_ask)

    primary = imbalance if imbalance is not None else 0.0
    if primary >= threshold:
        signal = "LONG_BIAS"
    elif primary <= -threshold:
        signal = "SHORT_BIAS"
    else:
        signal = "NEUTRAL"

    return OrderBookImbalance(
        imbalance=imbalance,
        top_imbalance=top_imbalance,
        weighted_imbalance=weighted,
        signal=signal,
        strength=abs(primary),
        levels_used=min(len(bids), len(asks)),
        data_quality="OK",
    )


def compute_obi_from_l2(
    l2_book: dict[str, Any] | None,
    *,
    levels_count: int = 10,
    threshold: float = 0.2,
) -> OrderBookImbalance:
    """Convenience wrapper that parses a raw Hyperliquid l2Book payload."""
    bids, asks = extract_l2_levels(l2_book or {}, levels_count=levels_count)
    return compute_obi(bids, asks, threshold=threshold)


def _coerce_levels(raw: Any) -> Levels:
    out: Levels = []
    for item in raw or []:
        if isinstance(item, dict):
            px = safe_float(item.get("px"))
            sz = safe_float(item.get("sz"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            px = safe_float(item[0])
            sz = safe_float(item[1])
        else:
            continue
        if px is not None and sz is not None:
            out.append((px, sz))
    return out
