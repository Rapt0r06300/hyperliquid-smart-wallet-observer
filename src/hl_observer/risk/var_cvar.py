"""VaR / CVaR, volatility regime and Kelly fraction (S7 — V9, CloddsBot A2).

Historical (non-parametric) VaR and CVaR from a realised return series,
a volatility-regime classifier, and a capped Kelly fraction for sizing.

SAFETY: pure statistics over real/paper returns. Fewer than 2 samples ->
``None``; never fabricated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskMetrics:
    var: float | None
    cvar: float | None
    confidence: float
    samples: int
    regime: str


def _clean(returns: list[float]) -> list[float]:
    out: list[float] = []
    for r in returns:
        if isinstance(r, bool) or not isinstance(r, (int, float)):
            continue
        value = float(r)
        if not math.isnan(value) and not math.isinf(value):
            out.append(value)
    return out


def historical_var(returns: list[float], *, confidence: float = 0.95) -> float | None:
    clean = _clean(returns)
    if len(clean) < 2:
        return None
    conf = min(0.999, max(0.5, confidence))
    ordered = sorted(clean)
    n = len(ordered)
    index = int(round((1.0 - conf) * (n - 1)))
    index = min(max(index, 0), n - 1)
    return max(0.0, -ordered[index])


def historical_cvar(returns: list[float], *, confidence: float = 0.95) -> float | None:
    clean = _clean(returns)
    if len(clean) < 2:
        return None
    conf = min(0.999, max(0.5, confidence))
    ordered = sorted(clean)
    n = len(ordered)
    cutoff = max(1, int(round((1.0 - conf) * n)))
    cutoff = min(cutoff, n)
    tail = ordered[:cutoff]
    return max(0.0, -(sum(tail) / len(tail)))


def classify_regime(sigma_bps, *, low=15.0, high=45.0, extreme=80.0):
    if sigma_bps is None:
        return "UNKNOWN"
    if sigma_bps < low:
        return "LOW"
    if sigma_bps < high:
        return "NORMAL"
    if sigma_bps < extreme:
        return "HIGH"
    return "EXTREME"


def kelly_fraction(win_prob: float, win_loss_ratio: float, *, cap: float = 0.25) -> float:
    p = min(1.0, max(0.0, win_prob))
    b = win_loss_ratio
    if b <= 0:
        return 0.0
    f = p - (1.0 - p) / b
    return min(cap, max(0.0, f))


def compute_risk_metrics(returns, *, confidence=0.95, sigma_bps=None) -> RiskMetrics:
    return RiskMetrics(
        var=historical_var(returns, confidence=confidence),
        cvar=historical_cvar(returns, confidence=confidence),
        confidence=confidence,
        samples=len(returns),
        regime=classify_regime(sigma_bps),
    )
