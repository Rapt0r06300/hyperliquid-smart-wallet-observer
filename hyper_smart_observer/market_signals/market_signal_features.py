from __future__ import annotations

import json
from hashlib import sha256
from dataclasses import asdict, dataclass
from typing import Any

from hyper_smart_observer.market_signals.mid_stability import MarketMid, derive_market_mid, safe_float
from hyper_smart_observer.market_signals.orderbook_features import (
    OrderBookFeatures,
    compute_orderbook_features,
    extract_l2_levels,
)
from hyper_smart_observer.market_signals.volatility import VolatilityContext


@dataclass(frozen=True)
class MarketSignalFeatures:
    timestamp_ms: int
    source_ts: int | None
    wallet: str | None
    symbol: str
    current_mid: float | None
    mid_source: str
    mid_source_endpoint: str
    all_mids_current_mid: float | None
    best_bid: float | None
    best_ask: float | None
    spread_bps: float | None
    bid_depth_usdc: float
    ask_depth_usdc: float
    microprice: float | None
    depth_imbalance: float | None
    depth_slope: float | None
    l2_levels_per_side: int
    l2_bid_levels_json: str
    l2_ask_levels_json: str
    volatility_context: float | None
    volatility_range_bps: float | None
    volatility_realized_bps: float | None
    volatility_atr_bps: float | None
    volatility_bucket: str
    volatility_samples: int
    volatility_data_quality: str
    volatility_source_ts: int | None
    liquidity_score: float
    leader_delta: str | None
    leader_reference_price: float | None
    copy_degradation_bps: float | None
    edge_remaining_bps: float | None
    data_quality: str
    source_health: str
    is_stale: bool
    feature_hash: str = ""
    schema_version: str = "market_signal_features.v1"
    adapter_version: str = "hyperliquid-readonly.v1"

    def to_export_row(self) -> dict[str, Any]:
        return asdict(self)


def build_market_signal_features(
    *,
    timestamp_ms: int,
    symbol: str,
    l2_book: dict[str, Any],
    all_mids: dict[str, Any] | None = None,
    source_ts: int | None = None,
    wallet: str | None = None,
    leader_delta: str | None = None,
    leader_reference_price: float | None = None,
    copy_degradation_bps: float | None = None,
    edge_remaining_bps: float | None = None,
    volatility_context: float | VolatilityContext | None = None,
    source_health: str = "OK",
    last_trade_price: Any = None,
    is_stale: bool = False,
) -> MarketSignalFeatures:
    orderbook = compute_orderbook_features(symbol, l2_book)
    bid_levels, ask_levels = extract_l2_levels(l2_book)
    normalized_symbol = symbol.upper()
    mid = derive_market_mid(
        normalized_symbol,
        all_mids=all_mids,
        best_bid=orderbook.best_bid,
        best_ask=orderbook.best_ask,
        last_trade_price=last_trade_price,
        is_stale=is_stale,
    )
    quality = _combined_quality(mid, orderbook, source_health)
    vol = _normalize_volatility_context(volatility_context)
    feature_hash = "feat:" + sha256(
        f"{normalized_symbol}|{mid.mid}|{mid.mid_source}|{orderbook.spread_bps}|"
        f"{orderbook.liquidity_score}|{vol['realized_bps']}|{vol['atr_bps']}|"
        f"{vol['bucket']}|{quality}|{timestamp_ms}|{source_ts}".encode("utf-8")
    ).hexdigest()[:32]
    return MarketSignalFeatures(
        timestamp_ms=timestamp_ms,
        source_ts=source_ts,
        wallet=wallet,
        symbol=normalized_symbol,
        current_mid=mid.mid,
        mid_source=mid.mid_source,
        mid_source_endpoint=mid.source_endpoint,
        all_mids_current_mid=safe_float((all_mids or {}).get(normalized_symbol)),
        best_bid=orderbook.best_bid,
        best_ask=orderbook.best_ask,
        spread_bps=orderbook.spread_bps,
        bid_depth_usdc=orderbook.bid_depth_usdc,
        ask_depth_usdc=orderbook.ask_depth_usdc,
        microprice=orderbook.microprice,
        depth_imbalance=orderbook.depth_imbalance,
        depth_slope=orderbook.depth_slope,
        l2_levels_per_side=orderbook.levels_per_side,
        l2_bid_levels_json=_levels_json(bid_levels),
        l2_ask_levels_json=_levels_json(ask_levels),
        volatility_context=vol["context"],
        volatility_range_bps=vol["range_bps"],
        volatility_realized_bps=vol["realized_bps"],
        volatility_atr_bps=vol["atr_bps"],
        volatility_bucket=vol["bucket"],
        volatility_samples=vol["samples"],
        volatility_data_quality=vol["data_quality"],
        volatility_source_ts=vol["source_ts"],
        liquidity_score=orderbook.liquidity_score,
        leader_delta=leader_delta,
        leader_reference_price=leader_reference_price,
        copy_degradation_bps=copy_degradation_bps,
        edge_remaining_bps=edge_remaining_bps,
        data_quality=quality,
        source_health=source_health,
        is_stale=mid.is_stale,
        feature_hash=feature_hash,
    )


def _combined_quality(mid: MarketMid, orderbook: OrderBookFeatures, source_health: str) -> str:
    if source_health != "OK":
        return "SOURCE_DEGRADED"
    if mid.is_stale:
        return "STALE"
    if mid.data_quality == "MISSING" or orderbook.data_quality.startswith("MISSING"):
        return "MISSING"
    if mid.data_quality == "DEGRADED" or orderbook.data_quality != "OK":
        return "DEGRADED"
    return "OK"


def _normalize_volatility_context(value: float | VolatilityContext | None) -> dict[str, Any]:
    if isinstance(value, VolatilityContext):
        context = value.realized_vol_bps if value.realized_vol_bps is not None else value.range_bps
        return {
            "context": context,
            "range_bps": value.range_bps,
            "realized_bps": value.realized_vol_bps,
            "atr_bps": value.atr_bps,
            "bucket": value.bucket,
            "samples": value.samples,
            "data_quality": value.data_quality,
            "source_ts": value.source_ts,
        }
    if value is None:
        return {
            "context": None,
            "range_bps": None,
            "realized_bps": None,
            "atr_bps": None,
            "bucket": "UNKNOWN",
            "samples": 0,
            "data_quality": "MISSING",
            "source_ts": None,
        }
    numeric = safe_float(value)
    return {
        "context": numeric,
        "range_bps": None,
        "realized_bps": numeric,
        "atr_bps": None,
        "bucket": "UNKNOWN",
        "samples": 0,
        "data_quality": "LEGACY_NUMERIC",
        "source_ts": None,
    }


def _levels_json(levels: list[tuple[float, float]]) -> str:
    payload = [{"px": px, "sz": sz} for px, sz in levels]
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
