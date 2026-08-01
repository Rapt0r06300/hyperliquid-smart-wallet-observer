"""[ARB #37] CONNECTOR RELIABILITY PREMIUM : une venue historiquement instable (fills manqués, déconnexions)
doit exiger un edge SUPÉRIEUR avant d'être sélectionnée — l'instabilité est un coût espéré (résidus, unwind) qui
mange l'edge. Le premium croît quand la fiabilité baisse. Fiabilité inconnue → pire cas. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def premium_bps(fiabilite: Any, *, premium_max_bps: float = 50.0) -> float:
    """Premium d'edge exigé en bps = premium_max × (1 − fiabilite). fiabilite∈[0,1] ; inconnue → premium max
    (on ne récompense JAMAIS une venue dont on ignore la fiabilité)."""
    if not isinstance(fiabilite, (int, float)):
        return float(premium_max_bps)
    f = max(0.0, min(1.0, float(fiabilite)))
    return round(float(premium_max_bps) * (1.0 - f), 4)


def venue_admissible(edge_courant_bps: Any, *, edge_base_bps: float, fiabilite: Any,
                     premium_max_bps: float = 50.0) -> dict[str, Any]:
    """La venue n'est retenue que si edge_courant ≥ edge_base + premium(fiabilite)."""
    if not isinstance(edge_courant_bps, (int, float)):
        return {"admissible": False, "raison": "EDGE_NON_MESURABLE", "seuil_bps": UNMEASURABLE}
    prem = premium_bps(fiabilite, premium_max_bps=premium_max_bps)
    seuil = float(edge_base_bps) + prem
    ok = float(edge_courant_bps) >= seuil
    return {"admissible": bool(ok), "premium_bps": prem, "seuil_bps": round(seuil, 4),
            "raison": ("OK" if ok else "EDGE_SOUS_SEUIL_FIABILITE")}


__all__ = ["premium_bps", "venue_admissible", "UNMEASURABLE"]
