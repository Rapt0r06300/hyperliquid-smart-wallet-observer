"""[CROSS-VENUE lot2 #97] FAST-PATH INTERNE POUR COORDINATION DES JAMBES : quand deux sous-moteurs du MÊME spread
doivent communiquer à TRÈS FAIBLE LATENCE (une jambe remplie doit déclencher le hedge immédiatement), on évite le bus
d'événements générique et on emprunte un canal direct (VeighNa a retiré certains événements spread de son event
engine pour réduire la latence). Le fast-path n'est autorisé qu'entre jambes APPARIÉES du même épisode. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any


class FastPathJambes:
    """Canal direct entre jambes appariées d'un même épisode ; sinon on retombe sur le bus générique (plus lent)."""

    def __init__(self, *, latence_fastpath_ms: float = 0.5, latence_bus_ms: float = 5.0) -> None:
        self.latence_fastpath_ms = float(latence_fastpath_ms)
        self.latence_bus_ms = float(latence_bus_ms)
        self._paires: set[frozenset] = set()

    def apparier(self, jambe_a: str, jambe_b: str) -> None:
        self._paires.add(frozenset((str(jambe_a), str(jambe_b))))

    def appariees(self, jambe_a: str, jambe_b: str) -> bool:
        return frozenset((str(jambe_a), str(jambe_b))) in self._paires

    def envoyer(self, jambe_from: str, jambe_to: str) -> dict[str, Any]:
        """Emprunte le fast-path (faible latence) si les jambes sont appariées ; sinon le bus générique. Deux
        jambes non appariées ne peuvent PAS utiliser le fast-path (isolation entre épisodes)."""
        if self.appariees(jambe_from, jambe_to):
            return {"voie": "FAST_PATH", "latence_ms": self.latence_fastpath_ms}
        return {"voie": "BUS_GENERIQUE", "latence_ms": self.latence_bus_ms, "raison": "JAMBES_NON_APPARIEES"}


__all__ = ["FastPathJambes"]
