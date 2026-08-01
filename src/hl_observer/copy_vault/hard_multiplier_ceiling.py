"""[COPY-VAULT #54] HARD MULTIPLIER CEILING : même un vault excellent ne peut PAS voir sa taille copiée multipliée
arbitrairement. La taille paper est plafonnée en dur à leader_fill × multiplier_max, quelle que soit la confiance.
Un plafond dur borne le pire cas (bug de sizing, score aberrant). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def plafonner(taille_demandee: Any, *, leader_fill: Any, multiplier_max: float = 3.0) -> dict[str, Any]:
    """Borne la taille demandée à leader_fill × multiplier_max. Entrées invalides → UNMEASURABLE (jamais laisser
    passer une taille non bornée)."""
    if not all(isinstance(x, (int, float)) for x in (taille_demandee, leader_fill)) or float(multiplier_max) < 0:
        return {"taille": UNMEASURABLE, "refuse": True, "raison": "ENTREE_INVALIDE"}
    plafond = abs(float(leader_fill)) * float(multiplier_max)
    demandee = float(taille_demandee)
    capee = min(abs(demandee), plafond)
    signe = -1.0 if demandee < 0 else 1.0
    return {"taille": round(signe * capee, 12), "plafond": round(plafond, 12),
            "plafonnee": bool(abs(demandee) > plafond), "refuse": False}


__all__ = ["plafonner", "UNMEASURABLE"]
