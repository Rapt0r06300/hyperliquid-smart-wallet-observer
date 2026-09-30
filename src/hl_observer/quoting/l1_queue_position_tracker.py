"""[EXECUTION lot2 #86] L1 QUOTE-BASED QUEUE-POSITION TRACKER (2ᵉ simu) : un tracker de position dans la file basé
sur les quotes L1 (volume au meilleur niveau), comme SECOND simulateur INDÉPENDANT du simulateur de fills principal.
Deux estimateurs indépendants qui divergent signalent un modèle faux. On modélise notre position en file : le volume
DEVANT nous ne diminue que par les trades ; nos ajouts vont derrière. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class TrackerQueueL1:
    """Suit le volume devant nous à un niveau L1. On est rempli quand le volume devant tombe à 0."""

    def __init__(self, *, volume_devant: float) -> None:
        self.volume_devant = max(0.0, float(volume_devant))
        self.notre_qte = 0.0

    def entrer(self, notre_qte: float) -> None:
        """On rejoint la file : notre quantité se place DERRIÈRE le volume déjà présent."""
        self.notre_qte = max(0.0, float(notre_qte))

    def trade_consomme(self, volume: Any) -> dict[str, Any]:
        """Un trade au niveau consomme d'abord le volume devant nous, puis nous remplit. Volume invalide → ignoré."""
        if not isinstance(volume, (int, float)) or float(volume) < 0:
            return {"ok": False, "raison": "VOLUME_INVALIDE"}
        v = float(volume)
        consomme_devant = min(self.volume_devant, v)
        self.volume_devant -= consomme_devant
        reste = v - consomme_devant
        notre_fill = min(self.notre_qte, reste)
        self.notre_qte -= notre_fill
        return {"notre_fill": round(notre_fill, 12), "volume_devant": round(self.volume_devant, 12),
                "reste_notre_qte": round(self.notre_qte, 12)}

    def position(self) -> float:
        """Volume restant devant nous (0 = prochain à être rempli)."""
        return round(self.volume_devant, 12)


__all__ = ["TrackerQueueL1"]
