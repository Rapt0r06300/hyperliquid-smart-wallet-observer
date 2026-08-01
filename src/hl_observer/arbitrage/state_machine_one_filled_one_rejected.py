"""[ARB #46] STATE MACHINE ONE-FILLED/ONE-REJECTED : le cas « une jambe remplie, l'autre rejetée » est traité
EXPLICITEMENT et testé, au lieu de tomber dans une exception générique. Chaque combinaison des deux jambes
(FILLED / REJECTED / PENDING) mappe vers un état et une action déterministes. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

FILLED = "FILLED"
REJECTED = "REJECTED"
PENDING = "PENDING"

# états résultants
HEDGED = "HEDGED"
FLAT = "FLAT"
RESIDUAL_UNHEDGED = "RESIDUAL_UNHEDGED"
EN_ATTENTE = "EN_ATTENTE"

# actions
AUCUNE = "AUCUNE"
UNWIND_OU_RETRY_HEDGE = "UNWIND_OU_RETRY_HEDGE"
ATTENDRE = "ATTENDRE"
REVALIDER = "REVALIDER"

_NORM = {"FILL": FILLED, "FILLED": FILLED, "OK": FILLED,
         "REJECT": REJECTED, "REJECTED": REJECTED, "FAIL": REJECTED,
         "PENDING": PENDING, "PARTIAL": PENDING}

# table complète des 9 combinaisons (jambe1, jambe2) -> (etat, action)
_TABLE = {
    (FILLED, FILLED): (HEDGED, AUCUNE),
    (REJECTED, REJECTED): (FLAT, AUCUNE),                    # rien n'est passé : plat
    (FILLED, REJECTED): (RESIDUAL_UNHEDGED, UNWIND_OU_RETRY_HEDGE),
    (REJECTED, FILLED): (RESIDUAL_UNHEDGED, UNWIND_OU_RETRY_HEDGE),
    (FILLED, PENDING): (EN_ATTENTE, ATTENDRE),
    (PENDING, FILLED): (EN_ATTENTE, ATTENDRE),
    (REJECTED, PENDING): (EN_ATTENTE, REVALIDER),            # une jambe morte, l'autre pas confirmée
    (PENDING, REJECTED): (EN_ATTENTE, REVALIDER),
    (PENDING, PENDING): (EN_ATTENTE, ATTENDRE),
}


def transition(etat_jambe1: Any, etat_jambe2: Any) -> dict[str, Any]:
    """Mappe (jambe1, jambe2) vers (état, action) de façon déterministe. Statut non reconnu → EN_ATTENTE/REVALIDER
    (jamais d'exception silencieuse ni de supposition de succès)."""
    j1 = _NORM.get(str(etat_jambe1).upper())
    j2 = _NORM.get(str(etat_jambe2).upper())
    if j1 is None or j2 is None:
        return {"etat": EN_ATTENTE, "action": REVALIDER, "raison": "STATUT_JAMBE_NON_RECONNU"}
    etat, action = _TABLE[(j1, j2)]
    return {"etat": etat, "action": action, "jambes": [j1, j2]}


__all__ = ["transition", "FILLED", "REJECTED", "PENDING", "HEDGED", "FLAT", "RESIDUAL_UNHEDGED", "EN_ATTENTE",
           "AUCUNE", "UNWIND_OU_RETRY_HEDGE", "ATTENDRE", "REVALIDER"]
