"""V15 #209 — Leader recent-form / hotness (copy hot leaders, avoid cooling ones).

Recency-weighted recent performance: recent wins/PnL count more than old ones (exponential
half-life). Returns hotness 0..1 + a trend label. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from typing import Sequence


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True, slots=True)
class LeaderHotness:
    hotness: float          # 0..1
    recent_winrate: float   # recency-weighted
    trend: str              # HOT | WARM | COOLING | COLD
    samples: int


def leader_hotness(
    recent_trades: Sequence[tuple[int, float]],   # (ts_ms, realized_pnl_usd)
    *,
    now_ms: int,
    halflife_ms: float = 86_400_000.0,            # 1 day
) -> LeaderHotness:
    if not recent_trades:
        return LeaderHotness(0.0, 0.0, "COLD", 0)
    lam = 0.6931471805599453 / max(1.0, float(halflife_ms))   # ln2 / halflife
    wsum = 0.0
    wwin = 0.0
    wpnl = 0.0
    for ts, pnl in recent_trades:
        age = max(0.0, float(now_ms) - float(ts))
        w = exp(-lam * age)
        wsum += w
        if pnl > 0:
            wwin += w
        wpnl += w * (1.0 if pnl > 0 else -1.0) * min(1.0, abs(float(pnl)) / 100.0)
    winrate = (wwin / wsum) if wsum > 0 else 0.0
    pnl_score = _clamp(0.5 + 0.5 * (wpnl / wsum if wsum > 0 else 0.0))
    hot = _clamp(0.6 * winrate + 0.4 * pnl_score)
    trend = "HOT" if hot >= 0.65 else ("WARM" if hot >= 0.5 else ("COOLING" if hot >= 0.35 else "COLD"))
    return LeaderHotness(round(hot, 6), round(winrate, 6), trend, len(recent_trades))


__all__ = ["LeaderHotness", "leader_hotness"]
