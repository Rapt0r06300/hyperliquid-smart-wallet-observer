"""ALPHA P27 — METAORDER HAZARD : P(prochaine slice | état) et FLUX RÉSIDUEL attendu.

But : prédire le flux RÉSIDUEL d'un métaordre (ce qu'il reste à exécuter, qui poussera le prix), pas copier
une slice déjà publique. Features : stade (EARLY/MIDDLE/LATE), cadence régulière, fraction exécutée, résidu,
catch-up, reconstitution de profondeur, crowding. Sorties : remaining_flow_probability, expected_remaining_notional.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def flux_residuel(total_size: Any, executed_fraction: Any) -> Any:
    """Notional résiduel attendu = total × (1 − fraction exécutée). UNMEASURABLE si inconnu."""
    if not isinstance(total_size, (int, float)) or not isinstance(executed_fraction, (int, float)):
        return UNMEASURABLE
    return round(float(total_size) * max(0.0, 1.0 - float(executed_fraction)), 6)


def remaining_flow_probability(*, stade: str, executed_fraction: Any, cadence_reguliere: bool = True,
                               crowding: Any = 0.0, depth_replenishment: Any = 0.5) -> dict[str, Any]:
    """P(continuation du métaordre) ∈ [0,1] : haute si EARLY + faible fraction + cadence + peu de crowding."""
    if not isinstance(executed_fraction, (int, float)):
        return {"p_continuation": UNMEASURABLE}
    base = {"FIRST_SLICE": 0.85, "EARLY": 0.8, "MIDDLE": 0.5, "CONTINUATION": 0.55, "LATE": 0.2}.get(str(stade).upper(), 0.5)
    p = base * (1.0 - float(executed_fraction))
    if not cadence_reguliere:
        p *= 0.7
    if isinstance(crowding, (int, float)):
        p *= (1.0 - 0.5 * max(0.0, min(1.0, crowding)))     # crowding réduit notre part du résidu
    p = max(0.0, min(1.0, p))
    favorable = bool(str(stade).upper() in ("FIRST_SLICE", "EARLY") and float(executed_fraction) < 0.4
                     and (isinstance(crowding, (int, float)) and crowding < 0.3))
    return {"p_continuation": round(p, 4), "favorable_EARLY_LARGE_RESIDUAL_LOW_CROWDING": favorable}


__all__ = ["flux_residuel", "remaining_flow_probability", "UNMEASURABLE"]
