"""[CROSS-VENUE lot2 #76] HANGING-ORDER DISTANCE CANCELLATION : ne conserver un ordre hanging que TANT QU'IL RESTE
dans une distance maximale du marché. Une quote laissée trop loin du prix courant ne se remplira plus utilement et
ne fait qu'occuper du risque/marge ; au-delà d'une distance seuil, on l'annule. Distance inconnue → annuler
(prudence). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

GARDER = "GARDER"
ANNULER = "ANNULER"


def decision(prix_ordre: Any, prix_marche: Any, *, distance_max_bps: float = 30.0) -> dict[str, Any]:
    """Garde l'ordre tant que sa distance au marché ≤ distance_max ; au-delà → ANNULER. Prix invalide → ANNULER
    (on ne garde pas un ordre dont on ne peut pas situer la distance)."""
    if not all(isinstance(x, (int, float)) for x in (prix_ordre, prix_marche)) or float(prix_marche) <= 0:
        return {"decision": ANNULER, "raison": "PRIX_INVALIDE"}
    distance_bps = abs(float(prix_ordre) - float(prix_marche)) / float(prix_marche) * 1e4
    garder = distance_bps <= float(distance_max_bps)
    return {"decision": (GARDER if garder else ANNULER), "distance_bps": round(distance_bps, 4),
            "distance_max_bps": float(distance_max_bps),
            "raison": ("DANS_LA_DISTANCE" if garder else "TROP_LOIN_DU_MARCHE")}


__all__ = ["decision", "GARDER", "ANNULER"]
