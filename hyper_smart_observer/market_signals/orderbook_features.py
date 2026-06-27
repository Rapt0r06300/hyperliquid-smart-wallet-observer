from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hyper_smart_observer.market_signals.mid_stability import safe_float


@dataclass(frozen=True)
class OrderBookFeatures:
    coin: str
    best_bid: float | None
    best_ask: float | None
    spread_bps: float | None
    bid_depth_usdc: float
    ask_depth_usdc: float
    depth_imbalance: float | None
    microprice: float | None
    depth_slope: float | None
    liquidity_score: float
    data_quality: str
    levels_per_side: int


def compute_orderbook_features(
    coin: str,
    l2_book: dict[str, Any],
    *,
    levels_count: int = 10,
    min_depth_usdc: float = 10_000.0,
) -> OrderBookFeatures:
    bids, asks = _extract_sides(l2_book)
    bid_levels = bids[:levels_count]
    ask_levels = asks[:levels_count]
    best_bid = bid_levels[0][0] if bid_levels else None
    best_ask = ask_levels[0][0] if ask_levels else None

    bid_depth = sum(px * sz for px, sz in bid_levels)
    ask_depth = sum(px * sz for px, sz in ask_levels)
    total_depth = bid_depth + ask_depth
    spread_bps = _spread_bps(best_bid, best_ask)
    depth_imbalance = None if total_depth <= 0 else (bid_depth - ask_depth) / total_depth
    microprice = _microprice(best_bid, best_ask, bid_levels, ask_levels)
    depth_slope = _depth_slope(bid_levels, ask_levels)
    liquidity_score = 0.0 if min_depth_usdc <= 0 else min(100.0, total_depth / min_depth_usdc * 100.0)

    if not bid_levels or not ask_levels:
        quality = "MISSING_BOOK_SIDE"
    elif spread_bps is None or spread_bps < 0:
        quality = "INVALID_SPREAD"
    else:
        quality = "OK"

    return OrderBookFeatures(
        coin=coin.upper(),
        best_bid=best_bid,
        best_ask=best_ask,
        spread_bps=spread_bps,
        bid_depth_usdc=bid_depth,
        ask_depth_usdc=ask_depth,
        depth_imbalance=depth_imbalance,
        microprice=microprice,
        depth_slope=depth_slope,
        liquidity_score=liquidity_score,
        data_quality=quality,
        levels_per_side=min(len(bid_levels), len(ask_levels)),
    )


def extract_l2_levels(
    l2_book: dict[str, Any],
    *,
    levels_count: int = 10,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    bids, asks = _extract_sides(l2_book)
    return bids[:levels_count], asks[:levels_count]


def _extract_sides(l2_book: dict[str, Any]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    levels = l2_book.get("levels")
    if not isinstance(levels, list) or len(levels) < 2:
        return [], []
    return _parse_levels(levels[0]), _parse_levels(levels[1])


def _parse_levels(raw_levels: Any) -> list[tuple[float, float]]:
    parsed: list[tuple[float, float]] = []
    if not isinstance(raw_levels, list):
        return parsed
    for raw in raw_levels:
        if isinstance(raw, dict):
            px = safe_float(raw.get("px"))
            sz = safe_float(raw.get("sz"))
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            px = safe_float(raw[0])
            sz = safe_float(raw[1])
        else:
            continue
        if px is not None and sz is not None and px > 0 and sz >= 0:
            parsed.append((px, sz))
    return parsed


def _spread_bps(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
        return None
    mid = (best_bid + best_ask) / 2.0
    if mid <= 0:
        return None
    return (best_ask - best_bid) / mid * 10_000.0


def _microprice(
    best_bid: float | None,
    best_ask: float | None,
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
) -> float | None:
    if best_bid is None or best_ask is None or not bids or not asks:
        return None
    bid_size = bids[0][1]
    ask_size = asks[0][1]
    total_size = bid_size + ask_size
    if total_size <= 0:
        return None
    return (best_bid * ask_size + best_ask * bid_size) / total_size


def _depth_slope(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
) -> float | None:
    if len(bids) < 2 or len(asks) < 2:
        return None
    bid_slope = abs(bids[0][0] - bids[-1][0]) / max(1, len(bids) - 1)
    ask_slope = abs(asks[-1][0] - asks[0][0]) / max(1, len(asks) - 1)
    return (bid_slope + ask_slope) / 2.0
