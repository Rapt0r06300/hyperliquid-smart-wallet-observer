"""L1 — MOTEUR DE DÉCISION MAKER / TAKER : poster (passif) vs prendre (agressif) vs s'abstenir.

Compose D17 (EV maker = fill×rebate − sélection adverse) et la logique d'urgence :
  * pas urgent + EV maker > 0 -> POSTER_MAKER (on économise les frais, on encaisse le rebate) ;
  * urgent (le signal s'éteint vite) ET l'edge survit au coût taker -> PRENDRE_TAKER ;
  * sinon -> NE_PAS_TRADER (ni edge au maker, ni edge après taker). Deny-by-default. PAPER only.
"""
from __future__ import annotations

from hl_observer.backtesting.maker_rebate_decision import ev_maker_bps

POSTER_MAKER = "POSTER_MAKER"
PRENDRE_TAKER = "PRENDRE_TAKER"
NE_PAS_TRADER = "NE_PAS_TRADER"


def decision_maker_taker(*, edge_bps: float, prob_fill: float, rebate_bps: float,
                         selection_adverse_bps: float, cout_taker_bps: float,
                         urgent: bool = False, min_edge_bps: float = 30.0) -> str:
    edge_apres_taker = float(edge_bps) - max(0.0, float(cout_taker_bps))
    ev_maker = ev_maker_bps(prob_fill, rebate_bps, selection_adverse_bps)
    if urgent:
        return PRENDRE_TAKER if edge_apres_taker >= float(min_edge_bps) else NE_PAS_TRADER
    # pas urgent : préférer le maker s'il a une espérance positive ET que l'edge tient
    if ev_maker > 0.0 and float(edge_bps) >= float(min_edge_bps):
        return POSTER_MAKER
    if edge_apres_taker >= float(min_edge_bps):
        return PRENDRE_TAKER
    return NE_PAS_TRADER


__all__ = ["POSTER_MAKER", "PRENDRE_TAKER", "NE_PAS_TRADER", "decision_maker_taker"]
