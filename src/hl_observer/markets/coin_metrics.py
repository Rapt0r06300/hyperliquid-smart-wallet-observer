from __future__ import annotations

from pydantic import BaseModel

from hl_observer.config.settings import Settings
from hl_observer.markets.liquidity import calculate_orderbook_depth_usdc, is_liquid, liquidity_score
from hl_observer.markets.spread import calculate_spread_bps, spread_is_scannable
from hl_observer.utils.time import now_ms


class MarketMetricRecord(BaseModel):
    coin: str
    computed_at_ms: int
    mid_price: float | None = None
    spread_bps: float | None = None
    depth_usdc: float | None = None
    volume_hint_usdc: float | None = None
    open_interest_hint_usdc: float | None = None
    funding_hint: float | None = None
    liquidity_score: float = 0.0
    is_scannable: bool = False
    rejection_reason: str | None = None


class CoinOpportunityRecord(BaseModel):
    coin: str
    wallets_active: int = 0
    wallets_positive_pnl: int = 0
    wallets_positive_roi: int = 0
    avg_wallet_score: float | None = None
    best_wallet_address: str | None = None
    best_wallet_score: float | None = None
    liquidity_score: float = 0.0
    spread_bps: float | None = None
    opportunity_score: float = 0.0
    status: str = "observed"
    notes: str | None = None


def build_market_metric(
    coin: str,
    *,
    settings: Settings,
    mid_price: float | None = None,
    orderbook: dict | None = None,
    active_asset_ctx: dict | None = None,
) -> MarketMetricRecord:
    depth = calculate_orderbook_depth_usdc(orderbook or {}) if orderbook else None
    spread = calculate_spread_bps(orderbook or {}) if orderbook else None
    score = liquidity_score(depth, settings.market_universe.min_orderbook_depth_usdc)
    active_ctx = active_asset_ctx or {}
    volume_hint = _float_from(active_ctx, "dayNtlVlm", "volume", "volumeUsd")
    open_interest_hint = _float_from(active_ctx, "openInterest", "openInterestUsd")
    funding_hint = _float_from(active_ctx, "funding", "fundingRate")
    rejection_reason = None
    if depth is not None and not is_liquid(depth, settings.market_universe.min_orderbook_depth_usdc):
        rejection_reason = "liquidity_too_low"
    if spread is not None and not spread_is_scannable(spread, settings.market_universe.max_spread_bps):
        rejection_reason = "spread_too_wide"
    return MarketMetricRecord(
        coin=coin.upper(),
        computed_at_ms=now_ms(),
        mid_price=mid_price,
        spread_bps=spread,
        depth_usdc=depth,
        volume_hint_usdc=volume_hint,
        open_interest_hint_usdc=open_interest_hint,
        funding_hint=funding_hint,
        liquidity_score=score,
        is_scannable=rejection_reason is None,
        rejection_reason=rejection_reason,
    )


def _float_from(payload: dict, *keys: str) -> float | None:
    for key in keys:
        if key not in payload:
            continue
        try:
            return float(payload[key])
        except (TypeError, ValueError):
            continue
    return None

