"""[CROSS-VENUE #13] MINIMUM-NOTIONAL PREFLIGHT : rejeter l'opportunité si UNE des deux jambes tombe sous le
notional minimum de sa venue APRÈS arrondi tick/lot. Une jambe invalide = pas d'arbitrage complet (on se
retrouverait avec une jambe nue). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def preflight_min_notional(jambes: Mapping[str, Mapping[str, Any]], *,
                           min_notional_par_venue: Mapping[str, float]) -> dict[str, Any]:
    """`jambes` = {venue: {prix, taille}} (déjà arrondies). Rejette si notional = prix×taille < minimum de la venue.
    Une venue sans minimum connu OU des champs manquants invalident la jambe (jamais supposé OK)."""
    invalides = []
    notionals = {}
    for venue, j in jambes.items():
        prix, taille = (j or {}).get("prix"), (j or {}).get("taille")
        mn = min_notional_par_venue.get(venue)
        if not all(isinstance(x, (int, float)) for x in (prix, taille, mn)):
            invalides.append(venue)
            notionals[venue] = None
            continue
        n = float(prix) * float(taille)
        notionals[venue] = round(n, 8)
        if n < float(mn):
            invalides.append(venue)
    return {"ok": (not invalides and len(jambes) >= 2), "invalides": invalides, "notionals": notionals}


__all__ = ["preflight_min_notional"]
