"""
Politique de risque — leviers anti-perte pour le paper trading dYdX v4.

READ-ONLY / PAPER-ONLY. Logique 100 % pure (aucun réseau, aucun ordre) afin
d'être testable de façon déterministe, puis câblée derrière un flag dans
DydxLiveObserver.

4 leviers (choisis par l'utilisateur) :
  1. Anti-churn      : hold minimum + cooldown de réouverture (stop le « 1-2 s »).
  2. Exits ATR       : stop / take-profit / trailing basés sur la volatilité.
  3. Coupe-circuit   : pause après N pertes consécutives ou perte journalière.
  4. Anti-scalper    : écarter les leaders à durée de détention trop courte.

Un signal/refus n'est jamais un ordre.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# --------------------------------------------------------------------------- #
# 1. Anti-churn
# --------------------------------------------------------------------------- #
def held_long_enough(opened_at_ms: int, now_ms: int, min_hold_s: float) -> bool:
    """True si la position est ouverte depuis ≥ min_hold_s (donc OK à fermer
    sur sortie leader). Empêche le flip-flop ouverture/fermeture en 1-2 s.
    NB: ne bloque PAS un vrai stop-loss (le risque prime sur l'anti-churn)."""
    if min_hold_s <= 0:
        return True
    return (now_ms - opened_at_ms) >= min_hold_s * 1000.0


def reopen_allowed(last_closed_at_ms: Optional[int], now_ms: int, cooldown_s: float) -> bool:
    """True si on peut rouvrir ce marché (cooldown écoulé depuis la dernière
    fermeture). Évite de re-rentrer immédiatement après une sortie."""
    if cooldown_s <= 0 or last_closed_at_ms is None:
        return True
    return (now_ms - last_closed_at_ms) >= cooldown_s * 1000.0


# --------------------------------------------------------------------------- #
# 4. Anti-scalper
# --------------------------------------------------------------------------- #
def is_scalper(median_hold_seconds: Optional[float], min_hold_seconds: float) -> bool:
    """True si le leader scalpe (détention médiane < seuil). On ne bat pas un
    scalper sur la latence : son edge se dissipe avant qu'on copie. Si la durée
    est inconnue (None), on ne filtre pas (graceful)."""
    if median_hold_seconds is None:
        return False
    return median_hold_seconds < min_hold_seconds


# --------------------------------------------------------------------------- #
# 2. Exits ATR (volatilité)
# --------------------------------------------------------------------------- #
def rolling_atr(prices: list[float], period: int = 14) -> float:
    """ATR proxy simple = moyenne des |Δ| sur les `period` derniers prix.
    Suffisant pour dimensionner stop/TP quand on n'a que des marks (pas d'OHLC)."""
    if not prices or len(prices) < 2:
        return 0.0
    deltas = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    recent = deltas[-period:]
    return sum(recent) / len(recent) if recent else 0.0


@dataclass
class ExitSignal:
    exit: bool
    reason: str
    peak: float          # meilleur prix favorable atteint (pour le trailing)
    armed: bool          # trailing armé ?


def atr_exit_decision(
    side: str,
    entry_price: float,
    mark_price: float,
    atr: float,
    *,
    stop_mult: float = 1.5,
    tp_mult: float = 3.0,
    trail_mult: float = 1.0,
    peak: Optional[float] = None,
    armed: bool = False,
) -> ExitSignal:
    """
    Décision de sortie basée ATR (pur). LONG/SHORT symétriques.

    - stop dur  : entry -/+ stop_mult*ATR
    - take profit: entry +/- tp_mult*ATR
    - trailing  : armé après +trail_mult*ATR de profit, suit le peak à trail_mult*ATR.

    Laisse courir les gagnants (TP loin + trailing) et coupe vite les perdants.
    """
    is_long = side.upper() == "LONG"
    if atr <= 0 or entry_price <= 0 or mark_price <= 0:
        return ExitSignal(False, "NO_ATR", peak if peak is not None else mark_price, armed)

    if peak is None:
        peak = mark_price
    peak = max(peak, mark_price) if is_long else min(peak, mark_price)

    stop = entry_price - stop_mult * atr if is_long else entry_price + stop_mult * atr
    take = entry_price + tp_mult * atr if is_long else entry_price - tp_mult * atr

    if (is_long and mark_price <= stop) or (not is_long and mark_price >= stop):
        return ExitSignal(True, "ATR_STOP", peak, armed)
    if (is_long and mark_price >= take) or (not is_long and mark_price <= take):
        return ExitSignal(True, "ATR_TAKE_PROFIT", peak, armed)

    profit = (mark_price - entry_price) if is_long else (entry_price - mark_price)
    if not armed and profit >= trail_mult * atr:
        armed = True
    if armed:
        trail_stop = peak - trail_mult * atr if is_long else peak + trail_mult * atr
        if (is_long and mark_price <= trail_stop) or (not is_long and mark_price >= trail_stop):
            return ExitSignal(True, "ATR_TRAILING", peak, armed)

    return ExitSignal(False, "HOLD", peak, armed)


# --------------------------------------------------------------------------- #
# 3. Coupe-circuit (drawdown / pertes consécutives)
# --------------------------------------------------------------------------- #
_DAY_MS = 86_400_000


class CircuitBreaker:
    """
    Bloque les NOUVELLES entrées après trop de pertes. Se réarme chaque jour.

    Trip si :
      - `consecutive_losses >= max_consecutive_losses`, ou
      - `daily_pnl <= -(max_daily_drawdown_pct * starting_equity)` (ou seuil USDC fixe).
    """

    def __init__(
        self,
        max_consecutive_losses: int = 4,
        starting_equity: float = 1000.0,
        max_daily_drawdown_pct: float = 0.05,
        max_daily_loss_usdc: Optional[float] = None,
    ) -> None:
        self.max_consecutive_losses = max(1, max_consecutive_losses)
        self.starting_equity = starting_equity
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self.max_daily_loss_usdc = max_daily_loss_usdc
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self._day: Optional[int] = None

    def _roll_day(self, now_ms: int) -> None:
        day = now_ms // _DAY_MS
        if self._day != day:
            self._day = day
            self.daily_pnl = 0.0
            self.consecutive_losses = 0

    @property
    def daily_loss_limit(self) -> float:
        if self.max_daily_loss_usdc is not None:
            return abs(self.max_daily_loss_usdc)
        return abs(self.starting_equity * self.max_daily_drawdown_pct)

    def record(self, net_pnl: float, now_ms: int) -> None:
        """Enregistrer un trade fermé (paper)."""
        self._roll_day(now_ms)
        self.daily_pnl += net_pnl
        if net_pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

    def status(self, now_ms: int) -> tuple[bool, Optional[str]]:
        """(tripped, reason). True ⇒ NE PAS ouvrir de nouvelle position."""
        self._roll_day(now_ms)
        if self.consecutive_losses >= self.max_consecutive_losses:
            return True, "CIRCUIT_MAX_CONSECUTIVE_LOSSES"
        if self.daily_pnl <= -self.daily_loss_limit:
            return True, "CIRCUIT_DAILY_LOSS_LIMIT"
        return False, None

    def is_tripped(self, now_ms: int) -> bool:
        return self.status(now_ms)[0]


__all__ = [
    "held_long_enough",
    "reopen_allowed",
    "is_scalper",
    "rolling_atr",
    "atr_exit_decision",
    "ExitSignal",
    "CircuitBreaker",
]
