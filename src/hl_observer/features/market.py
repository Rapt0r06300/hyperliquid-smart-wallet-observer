from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Literal


MidSource = Literal["MID_FROM_BOOK", "MID_FROM_ALL_MIDS", "MID_FROM_LAST_TRADE_FALLBACK", "MID_MISSING"]
QualityMode = Literal["TRADEABLE", "NO_TRADE"]


@dataclass(frozen=True, slots=True)
class MarketMid:
    coin: str
    mid: float | None
    mid_source: MidSource
    source_endpoint: str
    data_quality: str
    is_stale: bool = False


@dataclass(frozen=True, slots=True)
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
    levels_per_side: int
    data_quality: str


@dataclass(frozen=True, slots=True)
class VolatilityContext:
    range_bps: float | None
    realized_vol_bps: float | None
    atr_bps: float | None
    bucket: str
    samples: int
    data_quality: str
    source_ts_ms: int | None = None


@dataclass(frozen=True, slots=True)
class MarketQualityDecision:
    mode: QualityMode
    reasons: tuple[str, ...]
    severity: int
    min_edge_bps_addon: float
    feature_hash: str


@dataclass(frozen=True, slots=True)
class MarketFeatureVector:
    timestamp_ms: int
    source_ts_ms: int | None
    coin: str
    current_mid: float | None
    mid_source: str
    mid_endpoint: str
    best_bid: float | None
    best_ask: float | None
    spread_bps: float | None
    bid_depth_usdc: float
    ask_depth_usdc: float
    depth_imbalance: float | None
    microprice: float | None
    depth_slope: float | None
    liquidity_score: float
    volatility_realized_bps: float | None
    volatility_range_bps: float | None
    volatility_atr_bps: float | None
    volatility_bucket: str
    volatility_samples: int
    quality_mode: QualityMode
    quality_reasons: tuple[str, ...]
    min_edge_bps_addon: float
    bid_levels_json: str
    ask_levels_json: str
    feature_hash: str
    schema_version: str = "hl_observer.market_features.v1"
    runtime: str = "hyperliquid_read_only"

    def to_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["quality_reasons"] = "|".join(self.quality_reasons)
        return row


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def derive_market_mid(
    coin: str,
    *,
    best_bid: float | None = None,
    best_ask: float | None = None,
    all_mids: dict[str, Any] | None = None,
    last_trade_price: Any = None,
    is_stale: bool = False,
) -> MarketMid:
    normalized_coin = coin.upper()
    if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask > 0:
        return MarketMid(
            normalized_coin,
            (best_bid + best_ask) / 2.0,
            "MID_FROM_BOOK",
            "l2Book",
            "STALE" if is_stale else "OK",
            is_stale,
        )
    all_mid = safe_float((all_mids or {}).get(normalized_coin))
    if all_mid is not None and all_mid > 0:
        return MarketMid(
            normalized_coin,
            all_mid,
            "MID_FROM_ALL_MIDS",
            "allMids",
            "STALE" if is_stale else "OK",
            is_stale,
        )
    fallback = safe_float(last_trade_price)
    if fallback is not None and fallback > 0:
        return MarketMid(normalized_coin, fallback, "MID_FROM_LAST_TRADE_FALLBACK", "trades", "DEGRADED", is_stale)
    return MarketMid(normalized_coin, None, "MID_MISSING", "none", "MISSING", True)


def compute_orderbook_features(
    coin: str,
    l2_book: dict[str, Any] | None,
    *,
    levels_count: int = 10,
    min_depth_usdc: float = 10_000.0,
) -> OrderBookFeatures:
    bids, asks = extract_l2_levels(l2_book or {}, levels_count=levels_count)
    best_bid = bids[0][0] if bids else None
    best_ask = asks[0][0] if asks else None
    bid_depth = sum(px * sz for px, sz in bids)
    ask_depth = sum(px * sz for px, sz in asks)
    total_depth = bid_depth + ask_depth
    spread_bps = _spread_bps(best_bid, best_ask)
    depth_imbalance = None if total_depth <= 0 else (bid_depth - ask_depth) / total_depth
    microprice = _microprice(best_bid, best_ask, bids, asks)
    depth_slope = _depth_slope(bids, asks)
    liquidity_score = 0.0 if min_depth_usdc <= 0 else min(100.0, total_depth / min_depth_usdc * 100.0)
    if not bids or not asks:
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
        levels_per_side=min(len(bids), len(asks)),
        data_quality=quality,
    )


def extract_l2_levels(
    l2_book: dict[str, Any],
    *,
    levels_count: int = 10,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    levels = l2_book.get("levels")
    if not isinstance(levels, list) or len(levels) < 2:
        return [], []
    return _parse_levels(levels[0])[:levels_count], _parse_levels(levels[1])[:levels_count]


def compute_volatility_context(candles: list[Any] | None, *, max_candles: int = 200) -> VolatilityContext:
    if not candles:
        return VolatilityContext(None, None, None, "UNKNOWN", 0, "MISSING")
    rows = list(candles)[-max_candles:]
    closes = [value for value in (_candle_close(row) for row in rows) if value is not None and value > 0]
    source_ts = next((ts for ts in (_candle_ts(row) for row in reversed(rows)) if ts is not None), None)
    if len(closes) < 2:
        return VolatilityContext(None, None, None, "UNKNOWN", len(closes), "DEGRADED", source_ts)

    log_returns = [math.log(closes[index] / closes[index - 1]) for index in range(1, len(closes))]
    realized = _sample_stdev(log_returns) * 10_000.0 if len(log_returns) >= 2 else None
    highs = [high for high, _ in (_candle_high_low(row) for row in rows) if high is not None and high > 0]
    lows = [low for _, low in (_candle_high_low(row) for row in rows) if low is not None and low > 0]
    last_close = closes[-1]
    range_bps = ((max(highs) - min(lows)) / last_close * 10_000.0) if highs and lows and last_close > 0 else None
    atr_bps = _atr_bps(rows, last_close)
    metric = max([value for value in (realized, range_bps, atr_bps, 0.0) if value is not None])
    if metric < 10:
        bucket = "LOW"
    elif metric < 40:
        bucket = "NORMAL"
    elif metric < 120:
        bucket = "HIGH"
    else:
        bucket = "EXTREME"
    return VolatilityContext(range_bps, realized, atr_bps, bucket, len(closes), "OK", source_ts)


def build_market_feature_vector(
    *,
    timestamp_ms: int,
    coin: str,
    l2_book: dict[str, Any] | None = None,
    all_mids: dict[str, Any] | None = None,
    candles: list[Any] | None = None,
    source_ts_ms: int | None = None,
    last_trade_price: Any = None,
    is_stale: bool = False,
    max_spread_bps: float = 80.0,
    min_liquidity_score: float = 20.0,
) -> MarketFeatureVector:
    orderbook = compute_orderbook_features(coin, l2_book)
    bid_levels, ask_levels = extract_l2_levels(l2_book or {})
    mid = derive_market_mid(
        coin,
        best_bid=orderbook.best_bid,
        best_ask=orderbook.best_ask,
        all_mids=all_mids,
        last_trade_price=last_trade_price,
        is_stale=is_stale,
    )
    volatility = compute_volatility_context(candles)
    feature_hash = _feature_hash(timestamp_ms, source_ts_ms, coin, mid, orderbook, volatility)
    quality = evaluate_market_quality(
        mid=mid,
        orderbook=orderbook,
        volatility=volatility,
        feature_hash=feature_hash,
        max_spread_bps=max_spread_bps,
        min_liquidity_score=min_liquidity_score,
    )
    return MarketFeatureVector(
        timestamp_ms=timestamp_ms,
        source_ts_ms=source_ts_ms,
        coin=coin.upper(),
        current_mid=mid.mid,
        mid_source=mid.mid_source,
        mid_endpoint=mid.source_endpoint,
        best_bid=orderbook.best_bid,
        best_ask=orderbook.best_ask,
        spread_bps=orderbook.spread_bps,
        bid_depth_usdc=orderbook.bid_depth_usdc,
        ask_depth_usdc=orderbook.ask_depth_usdc,
        depth_imbalance=orderbook.depth_imbalance,
        microprice=orderbook.microprice,
        depth_slope=orderbook.depth_slope,
        liquidity_score=orderbook.liquidity_score,
        volatility_realized_bps=volatility.realized_vol_bps,
        volatility_range_bps=volatility.range_bps,
        volatility_atr_bps=volatility.atr_bps,
        volatility_bucket=volatility.bucket,
        volatility_samples=volatility.samples,
        quality_mode=quality.mode,
        quality_reasons=quality.reasons,
        min_edge_bps_addon=quality.min_edge_bps_addon,
        bid_levels_json=_levels_json(bid_levels),
        ask_levels_json=_levels_json(ask_levels),
        feature_hash=feature_hash,
    )


def evaluate_market_quality(
    *,
    mid: MarketMid,
    orderbook: OrderBookFeatures,
    volatility: VolatilityContext,
    feature_hash: str,
    max_spread_bps: float = 80.0,
    min_liquidity_score: float = 20.0,
) -> MarketQualityDecision:
    reasons: list[str] = []
    severity = 0
    addon = 0.0
    if mid.mid is None:
        reasons.append("MID_MISSING")
        severity = max(severity, 100)
    if mid.is_stale:
        reasons.append("MARKET_DATA_STALE")
        severity = max(severity, 80)
        addon += 20.0
    if orderbook.data_quality != "OK":
        reasons.append(orderbook.data_quality)
        severity = max(severity, 75)
        addon += 15.0
    if orderbook.spread_bps is None:
        reasons.append("SPREAD_UNMEASURABLE")
        severity = max(severity, 70)
        addon += 10.0
    elif orderbook.spread_bps > max_spread_bps:
        reasons.append("SPREAD_TOO_WIDE")
        severity = max(severity, 60)
        addon += min(40.0, orderbook.spread_bps / 4.0)
    if orderbook.liquidity_score < min_liquidity_score:
        reasons.append("LIQUIDITY_TOO_LOW")
        severity = max(severity, 60)
        addon += 15.0
    if volatility.bucket == "EXTREME":
        reasons.append("VOLATILITY_EXTREME")
        severity = max(severity, 50)
        addon += 12.0
    if volatility.data_quality in {"MISSING", "DEGRADED"}:
        reasons.append(f"VOLATILITY_{volatility.data_quality}")
        addon += 3.0
    mode: QualityMode = "NO_TRADE" if severity >= 60 else "TRADEABLE"
    if not reasons:
        reasons.append("MARKET_FEATURES_OK")
    return MarketQualityDecision(mode, tuple(dict.fromkeys(reasons)), severity, addon, feature_hash)


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


def _depth_slope(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> float | None:
    if len(bids) < 2 or len(asks) < 2:
        return None
    bid_slope = abs(bids[0][0] - bids[-1][0]) / max(1, len(bids) - 1)
    ask_slope = abs(asks[-1][0] - asks[0][0]) / max(1, len(asks) - 1)
    return (bid_slope + ask_slope) / 2.0


def _candle_close(candle: Any) -> float | None:
    if isinstance(candle, dict):
        return safe_float(candle.get("c") or candle.get("close"))
    if isinstance(candle, (list, tuple)) and candle:
        return safe_float(candle[-1])
    return None


def _candle_high_low(candle: Any) -> tuple[float | None, float | None]:
    if isinstance(candle, dict):
        return safe_float(candle.get("h") or candle.get("high")), safe_float(candle.get("l") or candle.get("low"))
    return None, None


def _candle_ts(candle: Any) -> int | None:
    if not isinstance(candle, dict):
        return None
    for key in ("T", "t", "time", "timestamp", "closeTime", "startTime"):
        try:
            return int(candle.get(key))
        except (TypeError, ValueError):
            continue
    return None


def _sample_stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _atr_bps(rows: list[Any], last_close: float) -> float | None:
    true_ranges: list[float] = []
    previous_close: float | None = None
    for row in rows:
        close = _candle_close(row)
        high, low = _candle_high_low(row)
        if high is None or low is None or close is None or close <= 0:
            previous_close = close if close and close > 0 else previous_close
            continue
        candidates = [high - low]
        if previous_close is not None and previous_close > 0:
            candidates.extend([abs(high - previous_close), abs(low - previous_close)])
        true_ranges.append(max(candidates))
        previous_close = close
    if not true_ranges or last_close <= 0:
        return None
    return (sum(true_ranges) / len(true_ranges)) / last_close * 10_000.0


def _levels_json(levels: list[tuple[float, float]]) -> str:
    return json.dumps([{"px": px, "sz": sz} for px, sz in levels], separators=(",", ":"), sort_keys=True)


def _feature_hash(
    timestamp_ms: int,
    source_ts_ms: int | None,
    coin: str,
    mid: MarketMid,
    orderbook: OrderBookFeatures,
    volatility: VolatilityContext,
) -> str:
    payload = {
        "timestamp_ms": timestamp_ms,
        "source_ts_ms": source_ts_ms,
        "coin": coin.upper(),
        "mid": mid.mid,
        "mid_source": mid.mid_source,
        "spread_bps": orderbook.spread_bps,
        "liquidity_score": orderbook.liquidity_score,
        "depth_imbalance": orderbook.depth_imbalance,
        "volatility_bucket": volatility.bucket,
        "volatility_realized_bps": volatility.realized_vol_bps,
    }
    return "feat:" + sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:32]
