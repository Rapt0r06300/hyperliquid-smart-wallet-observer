"""Event-window microstructure context around native venue snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.collection.native_venue_market import NativeMarketSnapshot


@dataclass(frozen=True, slots=True)
class AuxMarketMetrics:
    aggressive_buy_usd: float | None = None
    aggressive_sell_usd: float | None = None
    liquidation_usd: float | None = None


@dataclass(frozen=True, slots=True)
class EventMarketContextDelta:
    venue: str
    coin: str
    pre_ts_ms: int
    post_ts_ms: int
    spread_delta_bps: float | None
    bid_depth_delta_usd: float | None
    ask_depth_delta_usd: float | None
    obi_pre: float | None
    obi_post: float | None
    obi_delta: float | None
    volume_24h_delta: float | None
    open_interest_delta: float | None
    funding_rate_delta: float | None
    aggressive_flow_delta_usd: float | None
    liquidation_delta_usd: float | None


def compare_event_market_context(
    pre: NativeMarketSnapshot,
    post: NativeMarketSnapshot,
    *,
    pre_aux: AuxMarketMetrics = AuxMarketMetrics(),
    post_aux: AuxMarketMetrics = AuxMarketMetrics(),
    depth_levels: int = 5,
) -> EventMarketContextDelta:
    if pre.venue != post.venue or pre.coin != post.coin:
        raise ValueError("pre/post snapshots must refer to same venue and coin")
    if post.receive_ts_ms < pre.receive_ts_ms:
        raise ValueError("post snapshot cannot predate pre snapshot")

    pre_bid_depth = _depth_usd(pre.bids, depth_levels)
    post_bid_depth = _depth_usd(post.bids, depth_levels)
    pre_ask_depth = _depth_usd(pre.asks, depth_levels)
    post_ask_depth = _depth_usd(post.asks, depth_levels)

    obi_pre = _obi(pre_bid_depth, pre_ask_depth)
    obi_post = _obi(post_bid_depth, post_ask_depth)

    pre_flow = _aggressive_flow(pre_aux)
    post_flow = _aggressive_flow(post_aux)

    return EventMarketContextDelta(
        venue=pre.venue,
        coin=pre.coin,
        pre_ts_ms=pre.receive_ts_ms,
        post_ts_ms=post.receive_ts_ms,
        spread_delta_bps=post.spread_bps - pre.spread_bps,
        bid_depth_delta_usd=_delta(post_bid_depth, pre_bid_depth),
        ask_depth_delta_usd=_delta(post_ask_depth, pre_ask_depth),
        obi_pre=obi_pre,
        obi_post=obi_post,
        obi_delta=_delta(obi_post, obi_pre),
        volume_24h_delta=_delta(post.volume_24h, pre.volume_24h),
        open_interest_delta=_delta(post.open_interest, pre.open_interest),
        funding_rate_delta=_delta(post.funding_rate, pre.funding_rate),
        aggressive_flow_delta_usd=_delta(post_flow, pre_flow),
        liquidation_delta_usd=_delta(
            post_aux.liquidation_usd,
            pre_aux.liquidation_usd,
        ),
    )


def _depth_usd(levels, max_levels: int) -> float | None:
    selected = tuple(levels)[: max(0, int(max_levels))]
    if not selected:
        return None
    return sum(float(level.price) * float(level.size) for level in selected)


def _obi(bid_depth: float | None, ask_depth: float | None) -> float | None:
    if bid_depth is None or ask_depth is None:
        return None
    total = bid_depth + ask_depth
    if total <= 0:
        return None
    return (bid_depth - ask_depth) / total


def _aggressive_flow(metrics: AuxMarketMetrics) -> float | None:
    if metrics.aggressive_buy_usd is None or metrics.aggressive_sell_usd is None:
        return None
    return float(metrics.aggressive_buy_usd) - float(metrics.aggressive_sell_usd)


def _delta(after: float | None, before: float | None) -> float | None:
    if after is None or before is None:
        return None
    return float(after) - float(before)


__all__ = [
    "AuxMarketMetrics",
    "EventMarketContextDelta",
    "compare_event_market_context",
]
