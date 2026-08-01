"""[EXEC pépite 217] MONOTONIC ORDER-STATE VERSION : un vieux PARTIAL arrivé EN RETARD ne peut JAMAIS remplacer un
état FILLED (ou plus avancé). Les états d'ordre progressent (NEW < PARTIAL < FILLED/CANCELED) ; un message retardé
d'un état antérieur doit être ignoré, jamais appliqué (sinon régression : un ordre rempli redeviendrait partiel).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_RANG = {"NEW": 0, "ACCEPTED": 1, "PARTIAL": 2, "PARTIALLY_FILLED": 2, "FILLED": 3,
         "CANCELED": 3, "CANCELLED": 3, "REJECTED": 3, "EXPIRED": 3}
APPLIQUER = "APPLIQUER"
IGNORER = "IGNORER"


def decision(etat_courant: Any, etat_entrant: Any) -> dict[str, Any]:
    """Applique l'état entrant seulement si son rang ≥ rang courant. Un état antérieur (retardé) → IGNORER.
    État non reconnu → IGNORER (prudence : on ne régresse jamais)."""
    rc = _RANG.get(str(etat_courant).upper())
    re = _RANG.get(str(etat_entrant).upper())
    if rc is None or re is None:
        return {"action": IGNORER, "raison": "ETAT_NON_RECONNU"}
    if re >= rc:
        return {"action": APPLIQUER, "raison": "ETAT_NON_REGRESSIF"}
    return {"action": IGNORER, "raison": "ETAT_ANTERIEUR_RETARDE"}


__all__ = ["decision", "APPLIQUER", "IGNORER"]
