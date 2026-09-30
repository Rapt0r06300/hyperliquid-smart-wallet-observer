"""[ARB lot2 #12] ÉTAT CANCEL_PENDING BLOQUANT : tant qu'une annulation n'est pas DÉFINITIVEMENT résolue, aucune
nouvelle quote CONTRADICTOIRE ne peut être posée sur le même (coin, côté). Poser une nouvelle quote alors que
l'ancienne est peut-être encore vivante = risque de double exposition. L'état CANCEL_PENDING bloque. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any


class EtatCancelPending:
    """Suit les annulations en cours par (coin, côté) et bloque toute nouvelle quote contradictoire jusqu'à résolution."""

    def __init__(self) -> None:
        self._pending: set[tuple] = set()

    def _cle(self, coin: str, cote: str) -> tuple:
        return (str(coin).upper(), str(cote).upper())

    def marquer_cancel_pending(self, coin: str, cote: str) -> None:
        self._pending.add(self._cle(coin, cote))

    def resoudre(self, coin: str, cote: str) -> None:
        """L'annulation est confirmée définitivement : on débloque."""
        self._pending.discard(self._cle(coin, cote))

    def peut_poser(self, coin: str, cote: str) -> dict[str, Any]:
        """Refuse une nouvelle quote tant qu'un cancel du même (coin, côté) est en cours."""
        bloque = self._cle(coin, cote) in self._pending
        return {"peut_poser": (not bloque),
                "raison": ("OK" if not bloque else "CANCEL_PENDING_BLOQUANT")}


__all__ = ["EtatCancelPending"]
