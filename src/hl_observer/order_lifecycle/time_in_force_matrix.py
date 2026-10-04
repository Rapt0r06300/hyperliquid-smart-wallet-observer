"""Fail-closed time-in-force compatibility matrix for paper simulation.

Hyperliquid's canonical limit-order TIF values are GTC, IOC and ALO. POST_ONLY is
kept as a compatibility spelling and normalizes to ALO. GTD/FOK remain available
for other venue models, but are not silently claimed as Hyperliquid capabilities.
Pure/deterministic: zero network and zero order execution.
"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any

GTC, GTD, IOC, FOK, ALO, POST_ONLY = "GTC", "GTD", "IOC", "FOK", "ALO", "POST_ONLY"
TIFS = (GTC, GTD, IOC, FOK, ALO, POST_ONLY)
MATRICE_DEFAUT: dict[str, set[str]] = {
    "HL": {GTC, IOC, ALO},
    "BINANCE": {GTC, IOC, FOK, POST_ONLY},
}
_ALIASES_PAR_VENUE = {"HL": {POST_ONLY: ALO}}


def normaliser_tif(venue: Any, tif: Any) -> str:
    v = str(venue).upper()
    t = str(tif).upper()
    return _ALIASES_PAR_VENUE.get(v, {}).get(t, t)


def tif_autorise(venue: Any, tif: Any, *, matrice: Mapping[str, set[str]] | None = None) -> dict[str, Any]:
    m = matrice if matrice is not None else MATRICE_DEFAUT
    v = str(venue).upper()
    raw = str(tif).upper()
    if v not in m:
        return {"autorise": False, "raison": "VENUE_INCONNUE", "tif_normalise": raw}
    if raw not in TIFS:
        return {"autorise": False, "raison": "TIF_INCONNU", "tif_normalise": raw}
    normalise = normaliser_tif(v, raw)
    ok = normalise in m[v]
    return {"autorise": bool(ok), "raison": "OK" if ok else "TIF_INTERDIT_SUR_CETTE_VENUE",
            "tif_normalise": normalise}


__all__ = ["tif_autorise", "normaliser_tif", "MATRICE_DEFAUT", "TIFS",
           "GTC", "GTD", "IOC", "FOK", "ALO", "POST_ONLY"]
