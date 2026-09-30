"""[COPY-VAULT lot2 #40] AUTO-REBOOTSTRAP COMPLET SOUS SEUIL SYNC : lorsque le sync_confidence (#39) d'un vault
passe SOUS un seuil, on déclenche un rebootstrap COMPLET (re-télécharger tout l'état, repartir propre) plutôt que de
continuer à copier depuis un état douteux. Mieux vaut une pause de resync qu'une réplication fausse. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any


def doit_rebootstrap(sync_confidence: Any, *, seuil: float = 0.6) -> dict[str, Any]:
    """Déclenche le rebootstrap si sync_confidence < seuil. Score inconnu → rebootstrap (prudence : on ne copie
    pas depuis un état dont on ignore la fiabilité)."""
    if not isinstance(sync_confidence, (int, float)):
        return {"rebootstrap": True, "raison": "SYNC_CONFIDENCE_INCONNU"}
    if float(sync_confidence) < float(seuil):
        return {"rebootstrap": True, "sync_confidence": float(sync_confidence), "seuil": float(seuil),
                "raison": "SOUS_SEUIL_SYNC"}
    return {"rebootstrap": False, "sync_confidence": float(sync_confidence), "raison": "SYNC_SUFFISANT"}


__all__ = ["doit_rebootstrap"]
