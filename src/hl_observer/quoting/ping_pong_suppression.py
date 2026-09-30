"""[CROSS-VENUE lot2 #81] PING-PONG SUPPRESSION : après des fills RÉPÉTÉS d'un même côté (on se fait remplir en
boucle côté achat, par exemple), on réduit/supprime temporairement les nouvelles quotes de CE côté jusqu'au
rééquilibrage. Continuer à reposter du côté qui se fait manger, c'est accumuler une exposition directionnelle non
voulue. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class SuppressionPingPong:
    """Compte les fills récents par (coin, côté) ; supprime les nouvelles quotes d'un côté au-delà d'un seuil."""

    def __init__(self, *, seuil_fills: int = 3, fenetre_ms: float = 10_000.0) -> None:
        self.seuil = int(seuil_fills)
        self.fenetre_ms = float(fenetre_ms)
        self._fills: dict[tuple, list[float]] = {}

    def _cle(self, coin: str, side: str) -> tuple:
        return (str(coin).upper(), str(side).upper())

    def enregistrer_fill(self, coin: str, side: str, *, now_ms: float) -> None:
        cle = self._cle(coin, side)
        xs = [t for t in self._fills.get(cle, []) if now_ms - t <= self.fenetre_ms]
        xs.append(float(now_ms))
        self._fills[cle] = xs

    def peut_quoter(self, coin: str, side: str, *, now_ms: float) -> dict[str, Any]:
        """Autorise une nouvelle quote de ce côté sauf si trop de fills récents du même côté (déséquilibre)."""
        cle = self._cle(coin, side)
        n = len([t for t in self._fills.get(cle, []) if now_ms - t <= self.fenetre_ms])
        ok = n < self.seuil
        return {"peut_quoter": bool(ok), "fills_recents": n, "seuil": self.seuil,
                "raison": ("OK" if ok else "PING_PONG_SUPPRIME_CE_COTE")}


__all__ = ["SuppressionPingPong"]
