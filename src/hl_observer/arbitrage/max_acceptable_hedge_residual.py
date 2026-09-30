"""[ARB pépite 228] MAXIMUM ACCEPTABLE HEDGE RESIDUAL : refuser l'épisode lorsque le résidu STRUCTUREL après arrondi
(prévu par #227) dépasse un seuil, MÊME si le spread affiché semble excellent. Un beau spread ne compense pas une
exposition nue résiduelle garantie ; le résidu est un risque, pas un détail. Résidu non mesurable → refus (prudence).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def accepter(residu: Any, taille_cible: Any, *, residu_max_bps: float = 20.0) -> dict[str, Any]:
    """Accepte l'épisode seulement si le résidu structurel ≤ residu_max_bps de la taille cible. Au-delà → refus,
    quel que soit le spread. Résidu/taille non mesurable → refus."""
    if not all(isinstance(x, (int, float)) for x in (residu, taille_cible)) or float(taille_cible) <= 0:
        return {"accepter": False, "raison": "RESIDU_NON_MESURABLE"}
    residu_bps = abs(float(residu)) / float(taille_cible) * 1e4
    ok = residu_bps <= float(residu_max_bps)
    return {"accepter": bool(ok), "residu_bps": round(residu_bps, 4), "residu_max_bps": float(residu_max_bps),
            "raison": ("OK" if ok else "RESIDU_STRUCTUREL_TROP_GRAND")}


__all__ = ["accepter"]
