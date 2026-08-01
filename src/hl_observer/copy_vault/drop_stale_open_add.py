"""[COPY-VAULT lot2 #46] DROP DES OPEN/ADD TROP VIEUX DANS LA QUEUE CPU : un OPEN/ADD qui a trop vieilli dans la file
de traitement est DROPPÉ (l'opportunité d'ouverture est probablement périmée), mais on ENREGISTRE la missed
opportunity (pour la mesurer). Un CLOSE/REDUCE, lui, n'est jamais droppé : réduire le risque reste valable même
tard. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

TRAITER = "TRAITER"
DROP = "DROP"
_AUGMENTE = ("OPEN", "ADD")


def decision(action: Any, age_ms: Any, *, ttl_ms: float) -> dict[str, Any]:
    """OPEN/ADD au-delà du ttl → DROP + missed_opportunity=True. CLOSE/REDUCE → toujours TRAITER. Âge inconnu sur
    un OPEN/ADD → DROP (prudence, on ne poste pas une ouverture d'âge incertain)."""
    a = str(action).upper()
    if a not in _AUGMENTE:
        return {"decision": TRAITER, "raison": "REDUCTION_JAMAIS_DROP"}
    if not isinstance(age_ms, (int, float)):
        return {"decision": DROP, "missed_opportunity": True, "raison": "AGE_INCONNU"}
    if float(age_ms) > float(ttl_ms):
        return {"decision": DROP, "missed_opportunity": True, "age_ms": round(float(age_ms), 3),
                "raison": "OPEN_ADD_TROP_VIEUX"}
    return {"decision": TRAITER, "age_ms": round(float(age_ms), 3), "raison": "DANS_LE_TTL"}


__all__ = ["decision", "TRAITER", "DROP"]
