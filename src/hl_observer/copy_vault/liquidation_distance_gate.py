"""[COPY-VAULT lot2 #54] LIQUIDATION-DISTANCE GATE : un leader PROCHE de sa liquidation ne doit pas entraîner
automatiquement une nouvelle augmentation d'exposition copiée. Copier un « add » d'un trader au bord du gouffre,
c'est hériter de son risque de liquidation imminent. En dessous d'une distance seuil, on bloque les OPEN/ADD (mais
pas les réductions). Distance inconnue → bloqué (prudence). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def peut_augmenter(distance_liquidation_pct: Any, *, seuil_pct: float = 5.0) -> dict[str, Any]:
    """Autorise une augmentation d'exposition seulement si la distance à la liquidation ≥ seuil. Proche ou
    inconnu → bloqué (réduction toujours permise)."""
    if not isinstance(distance_liquidation_pct, (int, float)):
        return {"peut_augmenter": False, "peut_reduire": True, "raison": "DISTANCE_LIQ_INCONNUE"}
    ok = float(distance_liquidation_pct) >= float(seuil_pct)
    return {"peut_augmenter": bool(ok), "peut_reduire": True,
            "distance_pct": float(distance_liquidation_pct), "seuil_pct": float(seuil_pct),
            "raison": ("OK" if ok else "TROP_PROCHE_LIQUIDATION")}


__all__ = ["peut_augmenter"]
