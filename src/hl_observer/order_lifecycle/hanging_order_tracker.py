"""[CROSS-VENUE lot2 #75] HANGING-ORDER TRACKER : conserver certaines quotes PARTIELLEMENT remplies encore
ÉCONOMIQUEMENT BONNES (leur edge résiduel reste positif) au lieu de les cancel/recreate mécaniquement. Annuler une
quote encore bonne détruit sa priorité de file et paie du churn pour rien. On garde tant que l'edge courant reste
au-dessus d'un seuil. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

GARDER = "GARDER"
ANNULER = "ANNULER"


class TrackerHanging:
    """Suit les quotes partiellement remplies (hanging) et décide de les garder tant qu'elles restent rentables."""

    def __init__(self, *, seuil_edge_bps: float = 5.0) -> None:
        self.seuil_edge_bps = float(seuil_edge_bps)
        self._hanging: dict[str, dict[str, Any]] = {}

    def enregistrer(self, order_id: str, *, reste_qte: float) -> None:
        self._hanging[str(order_id)] = {"reste_qte": float(reste_qte)}

    def evaluer(self, order_id: str, *, edge_courant_bps: Any) -> dict[str, Any]:
        """Garde la quote hanging tant que son edge courant ≥ seuil ; sinon annule. Edge non mesurable → ANNULER
        (on ne garde pas une exposition dont on ne sait plus si elle est rentable)."""
        if str(order_id) not in self._hanging:
            return {"decision": ANNULER, "raison": "ORDRE_INCONNU"}
        if not isinstance(edge_courant_bps, (int, float)):
            return {"decision": ANNULER, "raison": "EDGE_NON_MESURABLE"}
        garder = float(edge_courant_bps) >= self.seuil_edge_bps
        return {"decision": (GARDER if garder else ANNULER), "edge_bps": float(edge_courant_bps),
                "seuil_bps": self.seuil_edge_bps, "raison": ("ENCORE_RENTABLE" if garder else "EDGE_SOUS_SEUIL")}


__all__ = ["TrackerHanging", "GARDER", "ANNULER"]
