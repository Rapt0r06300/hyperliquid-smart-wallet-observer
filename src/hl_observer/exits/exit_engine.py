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


# ─────────────────────────────────────────────────────────────────────────────
# Compat rétro pour les modules legacy `copying/` (viral_bot_engine,
# pipeline_integrator). Le scaffold initial exposait `ExitPlan` +
# `build_default_exit_plan` ici ; ces orphelins importaient EN PLUS
# `ExitReason`, `select_exit_plan`, `evaluate_exit` (jamais définis → import
# cassé dès l'origine). On restaure les deux premiers (régression de réécriture)
# et on complète la surface minimale pour que le paquet importe à 100 %.
# NOTE: `copying/` n'est PAS câblé au runtime actif (src/hl_observer/edge,
# paper_trading, signals). Aucune activation en dur ; logique déterministe.
# ─────────────────────────────────────────────────────────────────────────────
from enum import Enum

from pydantic import BaseModel


class ExitReason(str, Enum):
    HARD_STOP = "HARD_STOP"
    PARTIAL_TP = "PARTIAL_TP"
    TRAILING_STOP = "TRAILING_STOP"
    MAX_HOLD = "MAX_HOLD"
    LEADER_REDUCE = "LEADER_REDUCE"
    KILL_SWITCH = "KILL_SWITCH"
    HOLD = "HOLD"


class ExitPlan(BaseModel):
    id: str
    hard_stop_bps: float
    partial_take_profit_bps: float
    trailing_stop_bps: float
    max_hold_ms: int
    leader_reduce_exit: bool = True
    kill_switch_exit: bool = True


def build_default_exit_plan(signal_id: str) -> ExitPlan:
    return ExitPlan(
        id=f"exit-{signal_id}",
        hard_stop_bps=25,
        partial_take_profit_bps=35,
        trailing_stop_bps=18,
        max_hold_ms=3_600_000,
    )


def select_exit_plan(
    signal_id: str,
    *,
    edge_remaining_bps: float = 0.0,
    consensus_wallets: int = 0,
    leader_score: float = 0.0,
) -> ExitPlan:
    """Plan d'exit adaptatif (legacy copying/): plus d'edge restant et de
    consensus → stop plus large et hold plus long ; sinon plan par défaut serré.
    Déterministe, borné, aucune I/O."""
    plan = build_default_exit_plan(signal_id)
    edge = max(0.0, float(edge_remaining_bps))
    conf = max(0.0, float(consensus_wallets)) + max(0.0, float(leader_score))
    hard = min(60.0, plan.hard_stop_bps + edge * 0.25)
    tp = min(90.0, plan.partial_take_profit_bps + edge * 0.5)
    trail = min(45.0, plan.trailing_stop_bps + edge * 0.15)
    hold = plan.max_hold_ms + int(min(4, conf) * 600_000)
    return ExitPlan(
        id=plan.id,
        hard_stop_bps=hard,
        partial_take_profit_bps=tp,
        trailing_stop_bps=trail,
        max_hold_ms=hold,
    )


def evaluate_exit(
    plan: ExitPlan,
    *,
    pnl_bps: float,
    peak_pnl_bps: float = 0.0,
    age_ms: int = 0,
    leader_reduced: bool = False,
    kill_switch: bool = False,
) -> "ExitReason | None":
    """Évalue un ExitPlan contre l'état courant → ExitReason ou None (hold).
    Legacy copying/ ; logique pure et bornée."""
    if kill_switch and plan.kill_switch_exit:
        return ExitReason.KILL_SWITCH
    if leader_reduced and plan.leader_reduce_exit:
        return ExitReason.LEADER_REDUCE
    if pnl_bps <= -abs(plan.hard_stop_bps):
        return ExitReason.HARD_STOP
    if age_ms >= plan.max_hold_ms:
        return ExitReason.MAX_HOLD
    if peak_pnl_bps >= plan.partial_take_profit_bps and (peak_pnl_bps - pnl_bps) >= plan.trailing_stop_bps:
        return ExitReason.TRAILING_STOP
    if pnl_bps >= plan.partial_take_profit_bps:
        return ExitReason.PARTIAL_TP
    return None


__all__ = [
    "ExitDecision",
    "decide_exit",
    "ExitPlan",
    "ExitReason",
    "build_default_exit_plan",
    "select_exit_plan",
    "evaluate_exit",
]
