"""
Adaptive paper exits: ATR stop, partial take-profit, tightened trailing stop,
momentum pullback, and funding-aware time-stop.

The module is deliberately simulation-only. It never places, signs, cancels, or
routes a real order. It only tells the local paper engine when a virtual position
would be reduced or closed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_ATR_PERIOD = 14
DEFAULT_STOP_MULT = 1.5
DEFAULT_TP_MULT = 3.0
DEFAULT_PARTIAL_TP_MULT = 1.5
DEFAULT_TRAIL_MULT = 1.0
DEFAULT_TRAIL_TIGHTEN_PROFIT_MULT = 2.0
DEFAULT_TRAIL_TIGHTEN_MULT = 1.0
DEFAULT_MOMENTUM_PULLBACK_MULT = 0.5
DEFAULT_MAX_HOLDING_HOURS = 48.0
# Adverse hourly funding threshold above which max holding time is halved.
DEFAULT_FUNDING_ADVERSE_HOURLY = 0.0001


def compute_atr(candles: list[dict], period: int = DEFAULT_ATR_PERIOD) -> float:
    """
    Compute a simple ATR from Indexer candle rows. Returns 0.0 when the sample
    is insufficient so the caller can keep the fixed-percent fallback.
    """
    rows: list[tuple[str, float, float, float]] = []
    for c in candles or []:
        try:
            rows.append((
                str(c.get("startedAt", "")),
                float(c["high"]),
                float(c["low"]),
                float(c["close"]),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda r: r[0])
    if len(rows) < period + 1:
        return 0.0

    trs: list[float] = []
    prev_close = rows[0][3]
    for _, high, low, close in rows[1:]:
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = close
    recent = trs[-period:]
    return sum(recent) / len(recent) if recent else 0.0


@dataclass
class ExitPlan:
    """Immutable exit plan created when a paper position opens."""

    stop_price: float
    take_profit_price: float
    trail_distance: float
    trail_arm_price: float
    max_holding_ms: int
    atr: float
    method: str  # "ATR" | "FIXED_PCT_FALLBACK"
    trail_tighten_distance: float = 0.0
    momentum_pullback_distance: float = 0.0
    partial_take_profit_fraction: float = 0.50


def build_exit_plan(
    entry_price: float,
    side: str,
    atr: float,
    *,
    stop_mult: float = DEFAULT_STOP_MULT,
    tp_mult: float = DEFAULT_TP_MULT,
    partial_tp_mult: float = DEFAULT_PARTIAL_TP_MULT,
    trail_mult: float = DEFAULT_TRAIL_MULT,
    trail_tighten_mult: float = DEFAULT_TRAIL_TIGHTEN_MULT,
    momentum_pullback_mult: float = DEFAULT_MOMENTUM_PULLBACK_MULT,
    max_holding_hours: float = DEFAULT_MAX_HOLDING_HOURS,
    funding_rate_hourly: float = 0.0,
    funding_adverse_threshold: float = DEFAULT_FUNDING_ADVERSE_HOURLY,
    fallback_stop_pct: float = 1.5,
    fallback_tp_pct: float = 2.5,
) -> ExitPlan:
    """
    Build a conservative paper exit plan.

    With ATR available, the first take-profit is at 1.5 ATR. The live observer
    already closes 50% there, then extends the remaining runner toward the old
    3 ATR target. Without ATR, the legacy fixed-percent fallback is preserved.
    """
    side_u = side.upper()
    is_long = side_u == "LONG"

    trail_tighten_distance = 0.0
    momentum_pullback_distance = 0.0
    if atr > 0 and entry_price > 0:
        stop_d = stop_mult * atr
        partial_tp_d = partial_tp_mult * atr
        trail_d = trail_mult * atr
        trail_tighten_distance = trail_tighten_mult * atr
        momentum_pullback_distance = momentum_pullback_mult * atr
        if is_long:
            stop = entry_price - stop_d
            tp = entry_price + partial_tp_d
            arm = entry_price + trail_d
        else:
            stop = entry_price + stop_d
            tp = entry_price - partial_tp_d
            arm = entry_price - trail_d
        method = "ATR"
    else:
        sl_f = fallback_stop_pct / 100.0
        tp_f = fallback_tp_pct / 100.0
        if is_long:
            stop = entry_price * (1 - sl_f)
            tp = entry_price * (1 + tp_f)
        else:
            stop = entry_price * (1 + sl_f)
            tp = entry_price * (1 - tp_f)
        trail_d = 0.0
        arm = tp
        method = "FIXED_PCT_FALLBACK"

    holding_h = max_holding_hours
    if funding_rate_hourly > funding_adverse_threshold:
        holding_h = max_holding_hours / 2.0

    return ExitPlan(
        stop_price=max(0.0, stop),
        take_profit_price=max(0.0, tp),
        trail_distance=trail_d,
        trail_arm_price=arm,
        max_holding_ms=int(holding_h * 3600 * 1000),
        atr=atr,
        method=method,
        trail_tighten_distance=trail_tighten_distance,
        momentum_pullback_distance=momentum_pullback_distance,
    )


@dataclass
class TrailingState:
    """Mutable trailing-stop state for a local paper position."""

    side: str
    trail_distance: float
    trail_arm_price: float
    armed: bool = False
    best_price: float = 0.0
    trail_stop_price: float = 0.0
    breakeven_armed: bool = False
    breakeven_trigger_price: float = 0.0
    breakeven_stop_price: float = 0.0
    entry_price: float = 0.0
    atr: float = 0.0
    trail_tighten_distance: float = 0.0
    trail_tighten_profit_mult: float = DEFAULT_TRAIL_TIGHTEN_PROFIT_MULT
    momentum_pullback_distance: float = 0.0

    def update(self, mark_price: float) -> float | None:
        """
        Update with the latest mark. Return the simulated trigger price when the
        virtual trailing/momentum exit is hit; otherwise return None.
        """
        if self.trail_distance <= 0 or mark_price <= 0:
            return None
        is_long = self.side.upper() == "LONG"

        if self.best_price <= 0:
            self.best_price = mark_price

        # Breakeven check: once armed, a separate stop-loss check in the paper
        # engine protects the entry plus a tiny profit buffer.
        if not self.breakeven_armed and self.breakeven_trigger_price > 0:
            if (is_long and mark_price >= self.breakeven_trigger_price) or (
                not is_long and mark_price <= self.breakeven_trigger_price
            ):
                self.breakeven_armed = True
                logger.info(
                    "BREAKEVEN ARMED %s at %.6f -> SL moved to %.6f",
                    self.side,
                    mark_price,
                    self.breakeven_stop_price,
                )

        if not self.armed:
            if (is_long and mark_price >= self.trail_arm_price) or (
                not is_long and mark_price <= self.trail_arm_price
            ):
                self.armed = True
                self.best_price = max(self.best_price, mark_price) if is_long else min(self.best_price, mark_price)
                self.trail_stop_price = (
                    self.best_price - self.trail_distance if is_long
                    else self.best_price + self.trail_distance
                )
                self._tighten_after_profit(mark_price, is_long)
            return None

        if is_long:
            if mark_price > self.best_price:
                self.best_price = mark_price
        else:
            if mark_price < self.best_price:
                self.best_price = mark_price

        self._tighten_after_profit(mark_price, is_long)

        if self.momentum_pullback_distance > 0 and self.entry_price > 0:
            momentum_trigger = (
                self.best_price - self.momentum_pullback_distance if is_long
                else self.best_price + self.momentum_pullback_distance
            )
            profitable_peak = self.best_price > self.entry_price if is_long else self.best_price < self.entry_price
            if profitable_peak:
                if is_long and mark_price <= momentum_trigger:
                    return momentum_trigger
                if not is_long and mark_price >= momentum_trigger:
                    return momentum_trigger

        if is_long:
            candidate_stop = self.best_price - self.trail_distance
            self.trail_stop_price = max(self.trail_stop_price, candidate_stop)
            if mark_price <= self.trail_stop_price:
                return self.trail_stop_price
        else:
            candidate_stop = self.best_price + self.trail_distance
            self.trail_stop_price = min(self.trail_stop_price or candidate_stop, candidate_stop)
            if mark_price >= self.trail_stop_price:
                return self.trail_stop_price
        return None

    def _tighten_after_profit(self, mark_price: float, is_long: bool) -> None:
        if self.entry_price <= 0 or self.atr <= 0:
            return
        profit = mark_price - self.entry_price if is_long else self.entry_price - mark_price
        if profit < self.trail_tighten_profit_mult * self.atr:
            return
        target_distance = self.trail_tighten_distance or self.atr
        if target_distance <= 0 or target_distance >= self.trail_distance:
            return
        self.trail_distance = target_distance
        if is_long:
            self.trail_stop_price = max(self.trail_stop_price, self.best_price - self.trail_distance)
        else:
            tightened_stop = self.best_price + self.trail_distance
            self.trail_stop_price = min(self.trail_stop_price or tightened_stop, tightened_stop)


def is_time_stop_hit(opened_at_ms: int, now_ms: int, max_holding_ms: int) -> bool:
    """Time-stop: the position has exceeded its maximum simulated lifetime."""
    return max_holding_ms > 0 and (now_ms - opened_at_ms) >= max_holding_ms
