"""[ARB lot2 #11] CANCEL-CONFIRMATION POLICY VENUE-SPECIFIC : certaines venues exigent une CONFIRMATION d'annulation
avant de pouvoir remplacer un ordre (sinon on risque un double ordre), d'autres non. La politique dépend de la
venue ; une venue inconnue exige la confirmation par défaut (prudence). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# venue -> confirmation requise avant remplacement ?
POLITIQUE_DEFAUT: dict[str, bool] = {
    "HL": True,
    "BINANCE": False,
}


def doit_confirmer(venue: Any, *, politique: Mapping[str, bool] | None = None) -> dict[str, Any]:
    """Renvoie si une confirmation d'annulation est requise avant remplacement. Venue inconnue → confirmation
    requise (on ne remplace pas à l'aveugle, risque de double ordre)."""
    p = politique if politique is not None else POLITIQUE_DEFAUT
    v = str(venue).upper()
    if v not in p:
        return {"confirmer": True, "raison": "VENUE_INCONNUE_PRUDENCE"}
    return {"confirmer": bool(p[v]), "raison": ("CONFIRMATION_REQUISE" if p[v] else "REMPLACEMENT_DIRECT_OK")}


__all__ = ["doit_confirmer", "POLITIQUE_DEFAUT"]
