"""[DATA pépite 273] CRITICAL OVERFLOW = FAIL CLOSED : si une file critique (BBO/L2) déborde, l'état de marché
n'est plus fiable — donc AUCUN nouveau trade paper n'est autorisé jusqu'à un resync complet. On préfère ne rien
faire (fail-closed) plutôt que décider sur un carnet potentiellement faux. Le trade ne redevient possible
qu'après resync explicite. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class GardeOverflowCritique:
    """Au départ le trade est autorisé. Un overflow critique bascule en resync-requis (trade interdit). Seul un
    resync() explicite ré-autorise : on ne « suppose » jamais que l'état est revenu bon tout seul."""

    def __init__(self) -> None:
        self._resync_requis = False
        self._overflows = 0

    def signaler_overflow(self, file: str = "BBO") -> dict[str, Any]:
        self._resync_requis = True
        self._overflows += 1
        return {"resync_requis": True, "file": file, "overflows_total": self._overflows}

    def trade_autorise(self) -> dict[str, Any]:
        autorise = not self._resync_requis
        return {"autorise": autorise, "raison": None if autorise else "OVERFLOW_CRITIQUE_RESYNC_REQUIS"}

    def resync(self) -> dict[str, Any]:
        self._resync_requis = False
        return {"resync_requis": False, "trade_reautorise": True}


__all__ = ["GardeOverflowCritique"]
