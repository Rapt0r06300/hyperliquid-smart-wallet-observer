"""P3 — ExitEngine distillé (TP partiel, trailing resserré, momentum, time-stop).

Distillé de tony-42069 (SL/TP/trailing/max-hold) + freqtrade (trailing positif) +
CODEX_GOAL item 1. Réutilise les helpers exits.partial_take_profit et
exits.leader_exit_monitor (orphelins) plutôt que de les réécrire.

PRUDENCE (mémoire projet): les SL/TP synthétiques sur entrées tardives ont déjà
produit 12,5% de winrate. Donc: sorties EXPLICABLES, bornées par l'ATR mesuré, et
tout profil d'exit passe par un replay A/B avant activation. Ici: logique pure et
déterministe, aucune activation en dur.
"""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.exits.leader_exit_monitor import leader_reduced_position
from hl_observer.exits.partial_take_profit import partial_take_profit_size


@dataclass(frozen=True, slots=True)
class ExitDecision:
    action: str            # HOLD | PARTIAL_CLOSE | CLOSE
    fraction: float        # part de la position à fermer (0..1)
    reason: str


def decide_exit(
    *,
    side: str,
    entry_price: float,
    current_price: float,
    peak_price: float,
    atr_abs: float,
    age_sec: float,
    leader_prev_size: float | None = None,
    leader_curr_size: float | None = None,
    partial_tp_atr: float = 1.5,
    trailing_tighten_atr: float = 2.0,
    momentum_giveback_atr: float = 0.5,
    max_hold_sec: float = 14_400.0,
    partial_done: bool = False,
) -> ExitDecision:
    """Décision de sortie explicable. Toutes les distances en unités d'ATR mesuré."""

    side = str(side).upper()
    if side not in {"LONG", "SHORT"} or entry_price <= 0 or atr_abs <= 0:
        return ExitDecision("HOLD", 0.0, "INVALID_INPUTS")

    # 1) Le leader a réduit sa position → on suit (priorité: le signal source).
    if leader_prev_size is not None and leader_curr_size is not None:
        if leader_reduced_position(float(leader_prev_size), float(leader_curr_size)):
            return ExitDecision("CLOSE", 1.0, "LEADER_REDUCED")

    # profit courant et pic, en unités d'ATR
    def _fav(p):
        return (p - entry_price) if side == "LONG" else (entry_price - p)
    profit_atr = _fav(current_price) / atr_abs
    peak_atr = _fav(peak_price) / atr_abs

    # 2) Time-stop dur.
    if age_sec >= max_hold_sec:
        return ExitDecision("CLOSE", 1.0, "TIME_STOP")

    # 3) Exit momentum: recul de momentum_giveback ATR depuis le pic (si on était en profit).
    if peak_atr >= partial_tp_atr and (peak_atr - profit_atr) >= momentum_giveback_atr:
        return ExitDecision("CLOSE", 1.0, "MOMENTUM_GIVEBACK")

    # 4) TP partiel: fermer 50% à partial_tp_atr, trailer le reste (une seule fois).
    if not partial_done and profit_atr >= partial_tp_atr:
        frac = partial_take_profit_size(1.0, 0.5)  # helper orphelin réutilisé
        return ExitDecision("PARTIAL_CLOSE", frac, "PARTIAL_TP_AT_1_5_ATR")

    # 5) Trailing resserré: au-delà de trailing_tighten ATR de profit, un recul
    #    de 1 ATR sous le pic ferme le reste.
    if peak_atr >= trailing_tighten_atr and (peak_atr - profit_atr) >= 1.0:
        return ExitDecision("CLOSE", 1.0, "TRAILING_TIGHTENED_1_ATR")

    return ExitDecision("HOLD", 0.0, "HOLD")


__all__ = ["ExitDecision", "decide_exit"]
