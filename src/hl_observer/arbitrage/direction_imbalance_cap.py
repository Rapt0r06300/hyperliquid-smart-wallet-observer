"""[CROSS-VENUE #27] DIRECTION IMBALANCE CAP : limiter le nombre d'exécuteurs SIMULTANÉS qui peuvent accumuler
le MÊME risque directionnel (long ou short sur un même coin), façon contrôle multi-level XEMM. Sans plafond,
plusieurs boucles empilent la même exposition et transforment un arb « neutre » en pari directionnel.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class CapImbalanceDirection:
    """Plafonne les exécuteurs actifs par (coin, sens). +1/−1 = long/short."""

    def __init__(self, *, cap_par_direction: int = 2) -> None:
        self.cap = int(cap_par_direction)
        self._actifs: dict[tuple, int] = {}

    def _cle(self, coin: str, sens: int) -> tuple:
        return (str(coin).upper(), 1 if float(sens) > 0 else -1)

    def peut_ajouter(self, coin: str, sens: int) -> dict[str, Any]:
        cle = self._cle(coin, sens)
        n = self._actifs.get(cle, 0)
        ok = n < self.cap
        return {"ok": bool(ok), "actifs": n, "cap": self.cap,
                "raison": ("OK" if ok else "CAP_DIRECTION_ATTEINT")}

    def ajouter(self, coin: str, sens: int) -> bool:
        if not self.peut_ajouter(coin, sens)["ok"]:
            return False
        self._actifs[self._cle(coin, sens)] = self._actifs.get(self._cle(coin, sens), 0) + 1
        return True

    def retirer(self, coin: str, sens: int) -> None:
        cle = self._cle(coin, sens)
        self._actifs[cle] = max(0, self._actifs.get(cle, 0) - 1)


__all__ = ["CapImbalanceDirection"]
