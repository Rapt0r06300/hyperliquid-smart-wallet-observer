"""Event-conditioned market-state feature deltas.

These features are descriptive only. They measure how market microstructure changes
around an external event and never infer trade direction by themselves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class MarketStateObservation:
    ts_ms: int
    venue: str
    asset: str
    bid: float | None = None
    ask: float | None = None
    bid_depth_usd: float | None = None
    ask_depth_usd: float | None = None
    aggressive_buy_usd: float | None = None
    aggressive_sell_usd: float | None = None
    open_interest_usd: float | None = None
    funding_rate: float | None = None
    liquidation_long_usd: float | None = None
    liquidation_short_usd: float | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        if self.bid <= 0 or self.ask <= 0 or self.ask < self.bid:
            return None
        return (float(self.bid) + float(self.ask)) / 2.0

    @property
    def spread_bps(self) -> float | None:
        mid = self.mid
        if mid is None:
            return None
        return (float(self.ask) - float(self.bid)) / mid * 10_000.0

    @property
    def total_depth_usd(self) -> float | None:
        values = (self.bid_depth_usd, self.ask_depth_usd)
        if any(value is None for value in values):
            return None
        return float(self.bid_depth_usd) + float(self.ask_depth_usd)

    @property
    def order_flow_imbalance(self) -> float | None:
        buy = self.aggressive_buy_usd
        sell = self.aggressive_sell_usd
        if buy is None or sell is None:
            return None
        total = float(buy) + float(sell)
        if total <= 0:
            return None
        return (float(buy) - float(sell)) / total


@dataclass(frozen=True, slots=True)
class EventMarketFeatureDelta:
    event_ts_ms: int
    venue: str
    asset: str
    pre_ts_ms: int
    post_ts_ms: int
    spread_expansion_bps: float | None
    depth_change_usd: float | None
    depth_withdrawal_ratio: float | None
    order_flow_imbalance_change: float | None
    aggressive_volume_change_usd: float | None
    open_interest_change_usd: float | None
    funding_change: float | None
    liquidation_long_change_usd: float | None
    liquidation_short_change_usd: float | None


def measure_event_market_features(
    observations: Iterable[MarketStateObservation],
    *,
    event_ts_ms: int,
    venue: str,
    asset: str,
    pre_window_ms: int = 5_000,
    post_window_ms: int = 5_000,
) -> EventMarketFeatureDelta | None:
    target_venue = str(venue).lower()
    target_asset = str(asset).upper()
    rows = sorted(
        (
            row
            for row in observations
            if row.venue.lower() == target_venue and row.asset.upper() == target_asset
        ),
        key=lambda row: int(row.ts_ms),
    )
    pre = [
        row
        for row in rows
        if int(event_ts_ms) - int(pre_window_ms) <= row.ts_ms <= int(event_ts_ms)
    ]
    post = [
        row
        for row in rows
        if int(event_ts_ms) <= row.ts_ms <= int(event_ts_ms) + int(post_window_ms)
    ]
    if not pre or not post:
        return None
    before = pre[-1]
    after = post[-1]

    depth_before = before.total_depth_usd
    depth_after = after.total_depth_usd
    depth_change = _delta(depth_after, depth_before)
    withdrawal = None
    if depth_before is not None and depth_before > 0 and depth_after is not None:
        withdrawal = max(0.0, (depth_before - depth_after) / depth_before)

    aggressive_before = _sum_optional(
        before.aggressive_buy_usd,
        before.aggressive_sell_usd,
    )
    aggressive_after = _sum_optional(
        after.aggressive_buy_usd,
        after.aggressive_sell_usd,
    )
    return EventMarketFeatureDelta(
        event_ts_ms=int(event_ts_ms),
        venue=target_venue,
        asset=target_asset,
        pre_ts_ms=int(before.ts_ms),
        post_ts_ms=int(after.ts_ms),
        spread_expansion_bps=_delta(after.spread_bps, before.spread_bps),
        depth_change_usd=depth_change,
        depth_withdrawal_ratio=withdrawal,
        order_flow_imbalance_change=_delta(
            after.order_flow_imbalance,
            before.order_flow_imbalance,
        ),
        aggressive_volume_change_usd=_delta(aggressive_after, aggressive_before),
        open_interest_change_usd=_delta(after.open_interest_usd, before.open_interest_usd),
        funding_change=_delta(after.funding_rate, before.funding_rate),
        liquidation_long_change_usd=_delta(
            after.liquidation_long_usd,
            before.liquidation_long_usd,
        ),
        liquidation_short_change_usd=_delta(
            after.liquidation_short_usd,
            before.liquidation_short_usd,
        ),
    )


def _sum_optional(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    values = (float(a), float(b))
    if any(not math.isfinite(value) for value in values):
        return None
    return sum(values)


def _delta(after: float | None, before: float | None) -> float | None:
    if after is None or before is None:
        return None
    a = float(after)
    b = float(before)
    if not math.isfinite(a) or not math.isfinite(b):
        return None
    return a - b


__all__ = [
    "EventMarketFeatureDelta",
    "MarketStateObservation",
    "measure_event_market_features",
]
