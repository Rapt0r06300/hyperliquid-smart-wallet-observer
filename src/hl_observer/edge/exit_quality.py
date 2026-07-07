"""Qualite d'exit — metriques + trailing-stop discipline (levier PnL n1).

Pur, sans I/O. Long ET short. Port de comportement freqtrade
(trailing_stop_positive + offset d'armement) adapte au perp Hyperliquid.
Aucune action reelle : ces helpers decident d'un exit PAPER, jamais d'un ordre.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


def exit_capture_ratio(realized_profit_bps: float, mfe_bps: float) -> float:
    if mfe_bps <= 0:
        return 0.0
    return realized_profit_bps / mfe_bps


def profit_giveback_bps(realized_profit_bps: float, mfe_bps: float) -> float:
    return max(0.0, mfe_bps - realized_profit_bps)


def _bps(a: float, b: float) -> float:
    if b <= 0:
        return 0.0
    return (a - b) / b * 10000.0


@dataclass(frozen=True, slots=True)
class TrailingState:
    """Etat de suivi d'une position paper. side: 'long' ou 'short'."""

    entry_price: float
    side: str = "long"
    peak_price: float = 0.0
    trough_price: float = 0.0
    armed: bool = False
    mfe_bps: float = 0.0
    mae_bps: float = 0.0

    @staticmethod
    def open(entry_price: float, side: str = "long") -> "TrailingState":
        return TrailingState(
            entry_price=float(entry_price),
            side=("short" if str(side).lower() == "short" else "long"),
            peak_price=float(entry_price),
            trough_price=float(entry_price),
        )


def update_trailing(state: TrailingState, mark_price: float, *, arm_bps: float = 50.0) -> TrailingState:
    """Met a jour peak/trough, MFE/MAE et l'armement. Ne decide pas l'exit."""
    mark = float(mark_price)
    if state.side == "long":
        fav_bps = _bps(mark, state.entry_price)
    else:
        fav_bps = _bps(state.entry_price, mark)
    adv_bps = -fav_bps
    peak = max(state.peak_price, mark)
    trough = min(state.trough_price or mark, mark)
    mfe = max(state.mfe_bps, fav_bps)
    mae = max(state.mae_bps, adv_bps)
    armed = state.armed or (mfe >= arm_bps)
    return replace(state, peak_price=peak, trough_price=trough, mfe_bps=mfe, mae_bps=mae, armed=armed)


def trailing_stop_price(state: TrailingState, *, trail_bps: float = 30.0) -> float | None:
    """Prix de stop courant une fois le trailing arme, sinon None."""
    if not state.armed:
        return None
    if state.side == "long":
        return state.peak_price * (1.0 - trail_bps / 10000.0)
    return state.trough_price * (1.0 + trail_bps / 10000.0)


def should_exit_trailing(state: TrailingState, mark_price: float, *, trail_bps: float = 30.0) -> bool:
    """Vrai si le mark a rebrousse au-dela du trailing stop arme."""
    stop = trailing_stop_price(state, trail_bps=trail_bps)
    if stop is None:
        return False
    mark = float(mark_price)
    return mark <= stop if state.side == "long" else mark >= stop


def exit_quality_score(realized_profit_bps: float, mfe_bps: float, mae_bps: float = 0.0) -> float:
    """Score 0..1 : recompense le capture ratio, penalise le giveback."""
    capture = max(0.0, min(1.0, exit_capture_ratio(realized_profit_bps, mfe_bps)))
    giveback = profit_giveback_bps(realized_profit_bps, mfe_bps)
    denom = mfe_bps if mfe_bps > 0 else max(1.0, abs(realized_profit_bps))
    giveback_frac = max(0.0, min(1.0, giveback / denom))
    return round(max(0.0, min(1.0, 0.7 * capture + 0.3 * (1.0 - giveback_frac))), 6)


__all__ = [
    "exit_capture_ratio",
    "profit_giveback_bps",
    "TrailingState",
    "update_trailing",
    "trailing_stop_price",
    "should_exit_trailing",
    "exit_quality_score",
]
