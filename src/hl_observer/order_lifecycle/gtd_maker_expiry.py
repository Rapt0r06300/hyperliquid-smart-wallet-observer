"""[CROSS-VENUE lot2 #7] GTD MAKER EXPIRY : chaque quote maker porte une EXPIRATION économique stricte (Good-Til-
Date). Une quote qui traîne au-delà de sa raison d'être (l'edge qui la justifiait a disparu) doit expirer et être
annulée, pas rester indéfiniment à prendre un risque d'adverse selection. Horodatage inconnu → expirée (prudence).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

VALIDE = "VALIDE"
EXPIREE = "EXPIREE"


def etat_quote(pose_ms: Any, now_ms: Any, *, ttl_ms: float) -> dict[str, Any]:
    """VALIDE tant que l'âge ≤ ttl ; au-delà EXPIREE (à annuler). Horodatage invalide → EXPIREE (on n'entretient
    pas une quote dont on ignore l'âge)."""
    if not all(isinstance(x, (int, float)) for x in (pose_ms, now_ms)):
        return {"etat": EXPIREE, "raison": "HORODATAGE_INCONNU"}
    age = float(now_ms) - float(pose_ms)
    if age > float(ttl_ms):
        return {"etat": EXPIREE, "age_ms": round(age, 3), "raison": "TTL_DEPASSE", "a_annuler": True}
    return {"etat": VALIDE, "age_ms": round(age, 3), "reste_ms": round(float(ttl_ms) - age, 3)}


__all__ = ["etat_quote", "VALIDE", "EXPIREE"]
