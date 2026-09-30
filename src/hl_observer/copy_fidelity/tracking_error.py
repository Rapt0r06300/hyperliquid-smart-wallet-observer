"""Copy tracking error (S5 — V9, pm-backtest A1 / polybot).

Measures how far our paper entries drift from the leader's real entries:
per-trade signed price gap (bps), timing lag (ms) and size ratio, plus an
aggregate RMS tracking error over a sequence of copied trades.

SAFETY: pure measurement over real leader data vs paper intents.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CopyTrade:
    side: str                 # "long" / "short"
    leader_price: float
    copy_price: float
    leader_ts_ms: int | None = None
    copy_ts_ms: int | None = None
    leader_size: float | None = None
    copy_size: float | None = None


@dataclass(frozen=True, slots=True)
class CopyTradeFidelity:
    gap_bps: float
    lag_ms: int | None
    size_ratio: float | None


@dataclass(frozen=True, slots=True)
class TrackingError:
    rms_gap_bps: float | None
    mean_gap_bps: float | None
    mean_lag_ms: float | None
    samples: int
    per_trade: tuple[CopyTradeFidelity, ...] = field(default_factory=tuple)


def trade_gap_bps(trade: CopyTrade) -> float:
    """Signed copy gap in bps: positive = we paid worse than the leader."""
    if trade.leader_price <= 0:
        raise ValueError("leader_price must be positive")
    direction = 1.0 if trade.side.lower() == "long" else -1.0
    return direction * (trade.copy_price - trade.leader_price) / trade.leader_price * 10_000.0


def trade_fidelity(trade: CopyTrade) -> CopyTradeFidelity:
    gap = trade_gap_bps(trade)
    lag = None
    if trade.leader_ts_ms is not None and trade.copy_ts_ms is not None:
        lag = max(0, trade.copy_ts_ms - trade.leader_ts_ms)
    ratio = None
    if trade.leader_size and trade.leader_size > 0 and trade.copy_size is not None:
        ratio = trade.copy_size / trade.leader_size
    return CopyTradeFidelity(gap_bps=gap, lag_ms=lag, size_ratio=ratio)


def tracking_error(trades: list[CopyTrade]) -> TrackingError:
    if not trades:
        return TrackingError(None, None, None, 0, ())
    per_trade = [trade_fidelity(t) for t in trades]
    gaps = [f.gap_bps for f in per_trade]
    lags = [f.lag_ms for f in per_trade if f.lag_ms is not None]
    rms = math.sqrt(sum(g * g for g in gaps) / len(gaps))
    mean_gap = sum(gaps) / len(gaps)
    mean_lag = (sum(lags) / len(lags)) if lags else None
    return TrackingError(
        rms_gap_bps=rms,
        mean_gap_bps=mean_gap,
        mean_lag_ms=mean_lag,
        samples=len(trades),
        per_trade=tuple(per_trade),
    )
