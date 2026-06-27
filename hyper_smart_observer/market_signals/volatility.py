"""Read-only volatility context from candles or trades (no fabrication).

If candles/trades are unavailable, returns None and the caller marks the feature
data_quality degraded. Metrics are simple and explainable:
- range_bps: (max high - min low) / last close, in bps
- realized_vol_bps: stdev of close-to-close log returns, in bps
- atr_bps: average true range / last close, in bps
- bucket: LOW / NORMAL / HIGH / EXTREME
No network. No LLM.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from hyper_smart_observer.market_signals.mid_stability import safe_float


@dataclass(frozen=True)
class VolatilityContext:
    range_bps: float | None
    realized_vol_bps: float | None
    atr_bps: float | None
    bucket: str
    samples: int
    data_quality: str
    source_ts: int | None = None


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
        value = candle.get(key)
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def compute_volatility_context(candles: list[Any] | None, *, max_candles: int = 200) -> VolatilityContext:
    """Compute a simple realized-volatility context from candleSnapshot rows."""
    if not candles:
        return VolatilityContext(None, None, None, "UNKNOWN", 0, "MISSING")
    rows = list(candles)[-max_candles:]
    closes = [c for c in (_candle_close(r) for r in rows) if c is not None and c > 0]
    source_ts = next((ts for ts in (_candle_ts(r) for r in reversed(rows)) if ts is not None), None)
    if len(closes) < 2:
        return VolatilityContext(None, None, None, "UNKNOWN", len(closes), "DEGRADED", source_ts)

    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        realized_vol_bps = math.sqrt(var) * 10_000.0
    else:
        realized_vol_bps = None

    highs = [h for h, _ in (_candle_high_low(r) for r in rows) if h]
    lows = [low for _, low in (_candle_high_low(r) for r in rows) if low]
    last_close = closes[-1]
    if highs and lows and last_close > 0:
        range_bps = (max(highs) - min(lows)) / last_close * 10_000.0
    else:
        range_bps = None

    highs_lows = [_candle_high_low(row) for row in rows]
    true_ranges: list[float] = []
    previous_close: float | None = None
    for close, (high, low) in zip((_candle_close(row) for row in rows), highs_lows, strict=False):
        if high is None or low is None or close is None or close <= 0:
            previous_close = close if close and close > 0 else previous_close
            continue
        candidates = [high - low]
        if previous_close is not None and previous_close > 0:
            candidates.extend([abs(high - previous_close), abs(low - previous_close)])
        true_ranges.append(max(candidates))
        previous_close = close
    if true_ranges and last_close > 0:
        atr_bps = (sum(true_ranges) / len(true_ranges)) / last_close * 10_000.0
    else:
        atr_bps = None

    metric = max(value for value in (realized_vol_bps, atr_bps, range_bps, 0.0) if value is not None)
    if metric < 10:
        bucket = "LOW"
    elif metric < 40:
        bucket = "NORMAL"
    elif metric < 120:
        bucket = "HIGH"
    else:
        bucket = "EXTREME"
    return VolatilityContext(range_bps, realized_vol_bps, atr_bps, bucket, len(closes), "OK", source_ts)
