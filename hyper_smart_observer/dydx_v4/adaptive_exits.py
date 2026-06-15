"""
Exits adaptatifs — ATR, trailing stop, time-stop funding-aware.

La recherche copy-trading montre que le timing de SORTIE explique 60-80%
de l'écart de PnL entre le copieur et le wallet source. Des SL/TP fixes
en % traitent BTC et un alt 5× plus volatil pareil → faux stops ou
stops trop larges. Ici: distances en multiples d'ATR par marché.

Priorité des exits (ordre):
1. LEADER_EXIT (le leader ferme → on ferme)   — géré par live_observer
2. STOP_LOSS / TRAILING_STOP (ATR)
3. TAKE_PROFIT (ATR)
4. TIME_STOP (durée max, raccourcie si funding adverse)

PAPER-ONLY. Aucun ordre réel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_ATR_PERIOD = 14
DEFAULT_STOP_MULT = 1.5
DEFAULT_TP_MULT = 3.0
DEFAULT_TRAIL_MULT = 1.0
DEFAULT_MAX_HOLDING_HOURS = 48.0
# Funding horaire adverse au-delà duquel on raccourcit la durée max (0.01%/h)
DEFAULT_FUNDING_ADVERSE_HOURLY = 0.0001


def compute_atr(candles: list[dict], period: int = DEFAULT_ATR_PERIOD) -> float:
    """
    ATR simple depuis les candles Indexer (champs 'high','low','close',
    'startedAt'). Retourne 0.0 si données insuffisantes (→ fallback % fixe).
    """
    rows: list[tuple[str, float, float, float]] = []
    for c in candles or []:
        try:
            rows.append((
                str(c.get("startedAt", "")),
                float(c["high"]), float(c["low"]), float(c["close"]),
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
    """Plan de sortie figé à l'ouverture d'une position paper."""

    stop_price: float
    take_profit_price: float
    trail_distance: float        # distance trailing en prix (0 = désactivé)
    trail_arm_price: float       # le trailing s'arme quand le prix atteint ce niveau
    max_holding_ms: int
    atr: float
    method: str  # "ATR" | "FIXED_PCT_FALLBACK"


def build_exit_plan(
    entry_price: float,
    side: str,
    atr: float,
    *,
    stop_mult: float = DEFAULT_STOP_MULT,
    tp_mult: float = DEFAULT_TP_MULT,
    trail_mult: float = DEFAULT_TRAIL_MULT,
    max_holding_hours: float = DEFAULT_MAX_HOLDING_HOURS,
    funding_rate_hourly: float = 0.0,
    funding_adverse_threshold: float = DEFAULT_FUNDING_ADVERSE_HOURLY,
    fallback_stop_pct: float = 1.5,
    fallback_tp_pct: float = 2.5,
) -> ExitPlan:
    """
    Construit le plan de sortie. Si atr<=0 → fallback % fixes (comportement
    existant préservé, rien n'est dégradé).

    funding_rate_hourly: taux funding horaire SIGNÉ du point de vue de NOTRE
    position (positif = on paie). S'il dépasse le seuil, la durée max est
    divisée par 2 (le carry ronge l'edge).
    """
    side_u = side.upper()
    is_long = side_u == "LONG"

    if atr > 0 and entry_price > 0:
        stop_d = stop_mult * atr
        tp_d = tp_mult * atr
        trail_d = trail_mult * atr
        if is_long:
            stop = entry_price - stop_d
            tp = entry_price + tp_d
            arm = entry_price + trail_d
        else:
            stop = entry_price + stop_d
            tp = entry_price - tp_d
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
        arm = tp  # jamais armé avant TP → trailing inactif en fallback
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
    )


@dataclass
class TrailingState:
    """État mutable du trailing stop d'une position paper."""

    side: str
    trail_distance: float
    trail_arm_price: float
    armed: bool = False
    best_price: float = 0.0
    trail_stop_price: float = 0.0
    # Breakeven stop — protège les gains acquis
    breakeven_armed: bool = False
    breakeven_trigger_price: float = 0.0  # prix au-delà duquel on arme le breakeven
    breakeven_stop_price: float = 0.0     # nouveau SL = entry + micro-profit

    def update(self, mark_price: float) -> float | None:
        """
        Mettre à jour avec le dernier prix. Retourne le prix de déclenchement
        si le trailing stop est touché, sinon None.
        """
        if self.trail_distance <= 0 or mark_price <= 0:
            return None
        is_long = self.side.upper() == "LONG"

        # Breakeven check — armer quand le prix dépasse le trigger
        if not self.breakeven_armed and self.breakeven_trigger_price > 0:
            if (is_long and mark_price >= self.breakeven_trigger_price) or (
                not is_long and mark_price <= self.breakeven_trigger_price
            ):
                self.breakeven_armed = True
                logger.info(
                    "BREAKEVEN ARMED %s at %.6f → SL moved to %.6f",
                    self.side, mark_price, self.breakeven_stop_price,
                )

        if not self.armed:
            if (is_long and mark_price >= self.trail_arm_price) or (
                not is_long and mark_price <= self.trail_arm_price
            ):
                self.armed = True
                self.best_price = mark_price
                self.trail_stop_price = (
                    mark_price - self.trail_distance if is_long
                    else mark_price + self.trail_distance
                )
            return None

        # Armé: suivre le meilleur prix, remonter le stop
        if is_long:
            if mark_price > self.best_price:
                self.best_price = mark_price
                self.trail_stop_price = mark_price - self.trail_distance
            if mark_price <= self.trail_stop_price:
                return self.trail_stop_price
        else:
            if mark_price < self.best_price:
                self.best_price = mark_price
                self.trail_stop_price = mark_price + self.trail_distance
            if mark_price >= self.trail_stop_price:
                return self.trail_stop_price
        return None


def is_time_stop_hit(opened_at_ms: int, now_ms: int, max_holding_ms: int) -> bool:
    """Time-stop: la position a dépassé sa durée de vie maximale."""
    return max_holding_ms > 0 and (now_ms - opened_at_ms) >= max_holding_ms
