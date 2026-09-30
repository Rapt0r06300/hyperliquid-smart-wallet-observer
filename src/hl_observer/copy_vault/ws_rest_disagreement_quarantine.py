"""[COPY-VAULT lot2 #50] WS/REST DISAGREEMENT QUARANTINE : tant qu'une divergence entre la vue WS et la vue REST
d'un vault n'est pas RÉSOLUE, AUCUN OPEN/ADD n'est autorisé (on ne prend pas de nouveau risque sur un état
contradictoire). Les réductions restent permises (réduire le risque est toujours sûr). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class Quarantaine:
    """Marque un vault en quarantaine tant qu'un désaccord WS/REST n'est pas levé. Bloque OPEN/ADD, pas REDUCE/CLOSE."""

    def __init__(self, *, tolerance: float = 1e-6) -> None:
        self.tolerance = float(tolerance)
        self._quarantaine: set[str] = set()

    def evaluer(self, vault: str, *, valeur_ws: Any, valeur_rest: Any) -> dict[str, Any]:
        """Met en quarantaine si |ws − rest| > tolérance ou données manquantes ; sinon lève la quarantaine."""
        if not all(isinstance(x, (int, float)) for x in (valeur_ws, valeur_rest)):
            self._quarantaine.add(str(vault))
            return {"quarantaine": True, "raison": "DONNEE_MANQUANTE"}
        if abs(float(valeur_ws) - float(valeur_rest)) > self.tolerance:
            self._quarantaine.add(str(vault))
            return {"quarantaine": True, "raison": "DIVERGENCE_WS_REST"}
        self._quarantaine.discard(str(vault))
        return {"quarantaine": False, "raison": "ACCORD_WS_REST"}

    def peut_open_add(self, vault: str) -> dict[str, Any]:
        bloque = str(vault) in self._quarantaine
        return {"peut_open_add": (not bloque), "peut_reduce": True,
                "raison": ("OK" if not bloque else "QUARANTAINE_WS_REST")}


__all__ = ["Quarantaine"]
