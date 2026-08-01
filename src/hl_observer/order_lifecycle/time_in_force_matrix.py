"""[ARB lot2 #9] MATRICE TIME-IN-FORCE PAR VENUE : GTC/GTD/IOC/FOK/post-only sont compatibles ou INTERDITS
explicitement selon la venue. On ne suppose jamais qu'un TIF est supporté : une combinaison absente de la matrice
est refusée (fail-closed), sinon on simulerait un ordre que la venue rejetterait. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

GTC, GTD, IOC, FOK, POST_ONLY = "GTC", "GTD", "IOC", "FOK", "POST_ONLY"
TIFS = (GTC, GTD, IOC, FOK, POST_ONLY)

# matrice par défaut (illustrative, paper) : venue -> ensemble des TIF autorisés
MATRICE_DEFAUT: dict[str, set] = {
    "HL": {GTC, IOC, FOK, POST_ONLY, GTD},
    "BINANCE": {GTC, IOC, FOK, POST_ONLY},
}


def tif_autorise(venue: Any, tif: Any, *, matrice: Mapping[str, set] | None = None) -> dict[str, Any]:
    """Autorisé seulement si (venue, tif) est explicitement présent dans la matrice. Venue inconnue ou TIF non
    listé → INTERDIT (jamais supposé compatible)."""
    m = matrice if matrice is not None else MATRICE_DEFAUT
    v = str(venue).upper()
    t = str(tif).upper()
    if v not in m:
        return {"autorise": False, "raison": "VENUE_INCONNUE"}
    if t not in TIFS:
        return {"autorise": False, "raison": "TIF_INCONNU"}
    ok = t in m[v]
    return {"autorise": bool(ok), "raison": ("OK" if ok else "TIF_INTERDIT_SUR_CETTE_VENUE")}


__all__ = ["tif_autorise", "MATRICE_DEFAUT", "TIFS", "GTC", "GTD", "IOC", "FOK", "POST_ONLY"]
