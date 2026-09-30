"""[ALL lot2 #22] INVALIDATION AUTOMATIQUE DU FEE-CACHE : le cache de frais est invalidé DÈS qu'un changement de
tier ou de volume (qui peut faire changer de palier de frais) est détecté. Continuer à utiliser un taux mis en
cache après un changement de tier chiffre l'edge avec un frais périmé. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class CacheFrais:
    """Cache taux par venue, invalidé au changement de tier ou de volume franchissant un palier."""

    def __init__(self) -> None:
        self._taux: dict[str, float] = {}
        self._tier: dict[str, Any] = {}

    def poser(self, venue: str, *, taux_bps: float, tier: Any) -> None:
        self._taux[str(venue).upper()] = float(taux_bps)
        self._tier[str(venue).upper()] = tier

    def obtenir(self, venue: str) -> Any:
        return self._taux.get(str(venue).upper())

    def signaler_tier(self, venue: str, *, tier_courant: Any) -> dict[str, Any]:
        """Si le tier courant diffère du tier mis en cache → invalider (le taux caché est périmé)."""
        v = str(venue).upper()
        if v not in self._tier:
            return {"invalide": False, "raison": "PAS_DE_CACHE"}
        if self._tier[v] != tier_courant:
            self._taux.pop(v, None)
            self._tier.pop(v, None)
            return {"invalide": True, "raison": "CHANGEMENT_TIER"}
        return {"invalide": False, "raison": "TIER_INCHANGE"}


__all__ = ["CacheFrais"]
