"""[CROSS-VENUE #23] PROFIT HYSTERESIS : une petite oscillation autour du seuil ne doit pas provoquer
ouverture/annulation/ouverture en boucle. On sépare le seuil d'ENTRÉE (haut) du seuil de SORTIE (bas) : on
ouvre au-dessus de l'entrée, on ne ferme qu'en dessous de la sortie, et entre les deux on MAINTIENT l'état.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

OUVRIR = "OUVRIR"
FERMER = "FERMER"
MAINTENIR = "MAINTENIR"


class Hysteresis:
    """Bande d'hystérésis : seuil_entree > seuil_sortie. Évite le battement autour d'un seuil unique."""

    def __init__(self, *, seuil_entree_bps: float, seuil_sortie_bps: float) -> None:
        if float(seuil_entree_bps) <= float(seuil_sortie_bps):
            raise ValueError("hystérésis invalide : seuil_entree doit être > seuil_sortie")
        self.seuil_entree_bps = float(seuil_entree_bps)
        self.seuil_sortie_bps = float(seuil_sortie_bps)

    def action(self, edge_bps: Any, *, ouvert: bool) -> str:
        """OUVRIR si fermé et edge ≥ entrée ; FERMER si ouvert et edge ≤ sortie ; MAINTENIR dans la bande."""
        if not isinstance(edge_bps, (int, float)):
            return FERMER if ouvert else MAINTENIR       # edge non mesurable : ne pas ouvrir, fermer si exposé
        if not ouvert:
            return OUVRIR if edge_bps >= self.seuil_entree_bps else MAINTENIR
        return FERMER if edge_bps <= self.seuil_sortie_bps else MAINTENIR


__all__ = ["Hysteresis", "OUVRIR", "FERMER", "MAINTENIR"]
