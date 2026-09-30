"""[RISK lot2 #92] MISSING-MARK-PRICE BLOCKER : si un instrument DÉTENU n'a pas de mark price fiable, aucune equity,
ROI ou mesure de risque global ne peut être déclarée COMPLÈTE. Calculer une equity en ignorant un instrument sans
mark (ou en lui mettant 0) donne un chiffre faux et dangereux. On liste les instruments sans mark et on bloque tout
verdict global tant qu'il en reste (Nautilus : missing_price_instruments). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def equity_complete(positions: Mapping[str, Any], marks: Mapping[str, Any]) -> dict[str, Any]:
    """Vérifie qu'un mark valide existe pour CHAQUE instrument détenu (position non nulle). Un mark manquant/
    invalide rend l'equity INCOMPLÈTE (non déclarable). Renvoie la liste des instruments sans mark."""
    manquants = []
    for coin, taille in positions.items():
        if not isinstance(taille, (int, float)) or abs(float(taille)) <= 1e-12:
            continue                                     # position nulle : pas besoin de mark
        m = marks.get(coin)
        if not isinstance(m, (int, float)) or float(m) <= 0:
            manquants.append(str(coin).upper())
    complete = not manquants
    return {"complete": bool(complete), "instruments_sans_mark": sorted(manquants),
            "raison": ("OK" if complete else "MARK_MANQUANT_EQUITY_NON_DECLARABLE")}


__all__ = ["equity_complete"]
