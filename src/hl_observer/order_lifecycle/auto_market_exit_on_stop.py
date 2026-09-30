"""[ALL lot2 #18] AUTO MARKET-EXIT AU STOP DU MOTEUR : à l'arrêt du moteur, on planifie une sortie de marché
REDUCE-ONLY de chaque position ouverte, avec un TIF adapté à la venue. On ne laisse jamais des positions ouvertes
sans supervision quand le moteur s'arrête. Chaque ordre de sortie est du sens OPPOSÉ à la position, reduce-only.
Pur, 0 réseau, 0 ordre réel (planification seulement).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_TOL = 1e-12


def _sens_sortie(taille: float) -> str:
    return "SELL" if taille > 0 else "BUY"


def plan_exit_au_stop(positions: Mapping[str, Any], *, tif_par_venue: Mapping[str, str] | None = None,
                      tif_defaut: str = "IOC") -> dict[str, Any]:
    """Pour chaque position non nulle, produit un ordre reduce-only de sens opposé, TIF adapté à la venue.
    `positions` = {coin: {taille, venue}}. Position nulle → ignorée."""
    tif_par_venue = tif_par_venue or {}
    ordres = []
    for coin, p in positions.items():
        taille = (p or {}).get("taille")
        if not isinstance(taille, (int, float)) or abs(float(taille)) <= _TOL:
            continue
        venue = str((p or {}).get("venue", "")).upper()
        ordres.append({"coin": str(coin).upper(), "sens": _sens_sortie(float(taille)),
                       "quantite": round(abs(float(taille)), 12), "reduce_only": True,
                       "tif": tif_par_venue.get(venue, tif_defaut)})
    return {"ordres_sortie": ordres, "n": len(ordres), "reduce_only": True}


__all__ = ["plan_exit_au_stop"]
