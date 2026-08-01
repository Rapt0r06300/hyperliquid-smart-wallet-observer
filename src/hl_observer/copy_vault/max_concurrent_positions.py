"""[COPY-VAULT #57] MAXIMUM CONCURRENT POSITIONS : le copy-vault a sa PROPRE limite de positions ouvertes
simultanées, indépendante des autres stratégies. Copier tout ce que fait un leader très actif peut exploser le
nombre de positions ; le plafond protège le vault, pas le portefeuille global. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class LimiteurPositions:
    """Suit les coins actuellement ouverts pour le vault et plafonne leur nombre. Idempotent par coin."""

    def __init__(self, *, max_positions: int = 10) -> None:
        self.max_positions = int(max_positions)
        self._ouverts: set[str] = set()

    def peut_ouvrir(self, coin: str) -> dict[str, Any]:
        """Autorise si le coin est déjà ouvert (pas de nouvelle position) ou si on est sous le plafond."""
        c = str(coin).upper()
        if c in self._ouverts:
            return {"ok": True, "raison": "DEJA_OUVERT", "n_ouverts": len(self._ouverts)}
        ok = len(self._ouverts) < self.max_positions
        return {"ok": bool(ok), "n_ouverts": len(self._ouverts), "max": self.max_positions,
                "raison": ("OK" if ok else "PLAFOND_POSITIONS_ATTEINT")}

    def ouvrir(self, coin: str) -> bool:
        if not self.peut_ouvrir(coin)["ok"]:
            return False
        self._ouverts.add(str(coin).upper())
        return True

    def fermer(self, coin: str) -> None:
        self._ouverts.discard(str(coin).upper())


__all__ = ["LimiteurPositions"]
