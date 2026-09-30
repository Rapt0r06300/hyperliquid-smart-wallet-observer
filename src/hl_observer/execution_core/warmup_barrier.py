"""[ALL lot2 #71] WARM-UP BARRIER GLOBAL : aucune stratégie ne démarre tant que TOUTES ses données nécessaires n'ont
pas atteint leur fenêtre minimale (buffers remplis). Trader avant le warm-up, c'est décider sur des indicateurs
calculés sur trop peu de points — bruités et faux. La barrière bloque tant qu'un buffer requis est sous son minimum.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class BarriereWarmup:
    """Suit le remplissage des buffers requis par stratégie ; `pret` seulement quand TOUS atteignent leur minimum."""

    def __init__(self) -> None:
        self._requis: dict[str, dict[str, int]] = {}     # strategie -> {buffer: min}
        self._compte: dict[str, dict[str, int]] = {}     # strategie -> {buffer: n}

    def exiger(self, strategie: str, *, buffer: str, minimum: int) -> None:
        self._requis.setdefault(str(strategie), {})[str(buffer)] = int(minimum)
        self._compte.setdefault(str(strategie), {}).setdefault(str(buffer), 0)

    def observer(self, strategie: str, *, buffer: str, n: int = 1) -> None:
        c = self._compte.setdefault(str(strategie), {})
        c[str(buffer)] = c.get(str(buffer), 0) + int(n)

    def pret(self, strategie: str) -> dict[str, Any]:
        """Prêt seulement si chaque buffer requis a atteint son minimum. Stratégie sans exigence connue → non
        prête (on ne démarre pas une stratégie dont on ignore les besoins)."""
        req = self._requis.get(str(strategie))
        if not req:
            return {"pret": False, "raison": "AUCUNE_EXIGENCE_DECLAREE"}
        c = self._compte.get(str(strategie), {})
        manquants = {b: {"n": c.get(b, 0), "min": m} for b, m in req.items() if c.get(b, 0) < m}
        pret = not manquants
        return {"pret": bool(pret), "buffers_insuffisants": manquants,
                "raison": ("OK" if pret else "WARMUP_INCOMPLET")}


__all__ = ["BarriereWarmup"]
