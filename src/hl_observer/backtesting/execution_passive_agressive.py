"""D20 — EXÉCUTION PASSIVE-PUIS-AGRESSIVE : poster maker, ne CHASSER que si l'edge survit au move.

La leçon « course-poursuite » (LANCER_HYPERSMART) : chasser un prix déjà parti = payer le taker
POUR un edge déjà mangé par le mouvement = pertes en série. La discipline honnête :
  1. poster MAKER au prix cible (économise les frais, pas d'impact) ;
  2. si le prix bouge CONTRE nous avant le fill, l'edge restant = edge_initial − mouvement_adverse ;
  3. ne CROISER (taker) que si, APRÈS le coût taker, l'edge restant tient encore le plancher ;
  4. sinon ANNULER — un non-fill n'est pas une perte ; chasser dans un edge mort, si.

Module PUR. Une décision d'exécution n'est pas un ordre ; le noyau garde l'autorité. PAPER only.
"""
from __future__ import annotations

import math

RESTER_MAKER = "RESTER_MAKER"
CHASSER_TAKER = "CHASSER_TAKER"
ANNULER = "ANNULER"


def decision_execution(edge_initial_bps: float, mouvement_adverse_bps: float, *,
                       cout_taker_bps: float, min_edge_bps: float = 30.0) -> str:
    """Après avoir posté maker et vu le prix bouger de `mouvement_adverse_bps` CONTRE nous :
      * CHASSER_TAKER si l'edge restant APRÈS le coût taker tient encore le plancher ;
      * sinon RESTER_MAKER si l'edge restant (sans chasser) tient le plancher ;
      * sinon ANNULER (l'edge est mort -> on ne chasse pas)."""
    edge_restant = float(edge_initial_bps) - max(0.0, float(mouvement_adverse_bps))
    edge_si_chasse = edge_restant - max(0.0, float(cout_taker_bps))
    if edge_si_chasse >= float(min_edge_bps):
        return CHASSER_TAKER
    if edge_restant >= float(min_edge_bps):
        return RESTER_MAKER
    return ANNULER


def same_context_execution_receipt(*, edge_bps: object, adverse_move_bps: object, maker_cost_bps: object, taker_cost_bps: object) -> dict[str, object]:
    """Compare passive/aggressive choices using the same observed context."""

    try:
        edge, move, maker, taker = (float(value) for value in (edge_bps, adverse_move_bps, maker_cost_bps, taker_cost_bps))
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "CONTEXT_INVALID"}
    if not all(math.isfinite(value) for value in (edge, move, maker, taker)) or min(edge, move, maker, taker) < 0.0:
        return {"status": "UNMEASURABLE", "reason": "CONTEXT_INVALID"}
    return {"status": "PROVEN", "maker_edge_bps": round(edge - move - maker, 8), "taker_edge_bps": round(edge - move - taker, 8)}


__all__ = ["RESTER_MAKER", "CHASSER_TAKER", "ANNULER", "decision_execution", "same_context_execution_receipt"]
