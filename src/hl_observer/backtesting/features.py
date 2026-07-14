"""Features de marché — pures, testées. realized_vol/atr (IMPROVE-31), time_features (IMPROVE-32).
Briques pour prédicteurs et gates. No-lookahead (n'utilisent que le passé). Aucun ordre."""
from __future__ import annotations

import math
import time


def realized_vol(prices, *, window: int | None = None) -> float:
    """Volatilité réalisée (écart-type des log-returns)."""
    xs = [float(p) for p in prices if float(p) > 0]
    if window:
        xs = xs[-(window + 1):]
    if len(xs) < 3:
        return 0.0
    rets = [math.log(xs[i] / xs[i - 1]) for i in range(1, len(xs))]
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / len(rets)
    return math.sqrt(var)


def atr(highs, lows, closes, *, window: int = 14) -> float:
    """Average True Range (si OHLC dispo)."""
    n = min(len(highs), len(lows), len(closes))
    if n < 2:
        return 0.0
    trs = []
    for i in range(1, n):
        tr = max(float(highs[i]) - float(lows[i]),
                 abs(float(highs[i]) - float(closes[i - 1])),
                 abs(float(lows[i]) - float(closes[i - 1])))
        trs.append(tr)
    w = trs[-window:] if window else trs
    return sum(w) / len(w) if w else 0.0


def time_features(ts_seconds) -> dict:
    """Encodage cyclique de l'heure/jour (saisonnalité)."""
    t = time.gmtime(float(ts_seconds))
    hour, dow = t.tm_hour, t.tm_wday
    return {
        "hour": hour,
        "day_of_week": dow,
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "dow_sin": math.sin(2 * math.pi * dow / 7),
        "dow_cos": math.cos(2 * math.pi * dow / 7),
        "is_weekend": 1 if dow >= 5 else 0,
    }
