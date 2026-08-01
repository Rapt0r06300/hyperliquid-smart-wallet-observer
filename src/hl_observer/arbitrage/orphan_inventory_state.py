"""[ARB #41] ORPHAN INVENTORY STATE : quand une jambe est remplie et l'autre non, l'épisode n'est PAS « terminé ».
On introduit un état explicite (UNHEDGED_RESIDUAL / POSITION_HOLD) au lieu de considérer l'arb clos et d'oublier
une exposition nue. L'état force un suivi (timeout, unwind) au lieu d'un silence. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

FLAT = "FLAT"                         # les deux jambes équilibrées à 0 : rien à suivre
HEDGED = "HEDGED"                     # jambes appariées : couvert
UNHEDGED_RESIDUAL = "UNHEDGED_RESIDUAL"   # résidu nu : exposition à suivre
POSITION_HOLD = "POSITION_HOLD"       # position conservée volontairement en attente de résolution

_TOL = 1e-9


def etat_inventaire(qte_jambe1: Any, qte_jambe2: Any, *, hold: bool = False) -> dict[str, Any]:
    """Compare les quantités des deux jambes. Écart > tolérance → UNHEDGED_RESIDUAL (jamais 'terminé').
    Quantité inconnue → UNHEDGED_RESIDUAL par prudence (on ne déclare pas couvert sans preuve)."""
    if not all(isinstance(x, (int, float)) for x in (qte_jambe1, qte_jambe2)):
        return {"etat": UNHEDGED_RESIDUAL, "residu": None, "raison": "QUANTITE_INCONNUE"}
    residu = round(abs(float(qte_jambe1)) - abs(float(qte_jambe2)), 12)
    if abs(residu) <= _TOL:
        etat = FLAT if abs(float(qte_jambe1)) <= _TOL else HEDGED
        return {"etat": etat, "residu": 0.0, "raison": "APPARIE"}
    etat = POSITION_HOLD if hold else UNHEDGED_RESIDUAL
    return {"etat": etat, "residu": residu, "raison": "RESIDU_NU", "termine": False}


__all__ = ["etat_inventaire", "FLAT", "HEDGED", "UNHEDGED_RESIDUAL", "POSITION_HOLD"]
