"""[COPY-VAULT pépite 295] BURST SIZING SNAPSHOT : une séquence de partial fills issue du MÊME ordre doit
utiliser un equity snapshot COHÉRENT, au lieu de recalculer un ratio de sizing différent sur chaque micro-fill.
Sinon, si notre equity bouge pendant la rafale (autre position marquée au marché), chaque bout du même ordre
serait dimensionné différemment — incohérent. Le premier fill de l'ordre fige l'equity ; les suivants la
réutilisent. equity invalide au premier fill → UNMEASURABLE. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


class SnapshotEquityRafale:
    """Fige l'equity au premier micro-fill d'un order_id et la réutilise pour tous les fills suivants du même
    ordre. Garantit un ratio de sizing identique sur toute la rafale de partial fills."""

    def __init__(self) -> None:
        self._snap: dict[Any, float] = {}

    def equity_pour(self, order_id: Any, equity_courante: Any) -> dict[str, Any]:
        if order_id in self._snap:
            return {"equity": self._snap[order_id], "nouveau_snapshot": False}
        if not (isinstance(equity_courante, (int, float)) and not isinstance(equity_courante, bool)
                and math.isfinite(equity_courante)) or equity_courante <= 0:
            return {"equity": UNMEASURABLE, "raison": "EQUITY_INVALIDE"}
        self._snap[order_id] = float(equity_courante)
        return {"equity": self._snap[order_id], "nouveau_snapshot": True}

    def ratio_sizing(self, order_id: Any, notional_cible: Any, equity_courante: Any) -> dict[str, Any]:
        """Ratio = notional_cible / equity_snapshot (l'equity figée du premier fill, pas l'equity live)."""
        e = self.equity_pour(order_id, equity_courante)
        if e["equity"] == UNMEASURABLE:
            return {"ratio": UNMEASURABLE, "raison": e.get("raison")}
        if not (isinstance(notional_cible, (int, float)) and not isinstance(notional_cible, bool)
                and math.isfinite(notional_cible)) or notional_cible < 0:
            return {"ratio": UNMEASURABLE, "raison": "NOTIONAL_INVALIDE"}
        return {"ratio": round(float(notional_cible) / e["equity"], 8),
                "equity_snapshot": e["equity"], "nouveau_snapshot": e["nouveau_snapshot"]}


__all__ = ["SnapshotEquityRafale", "UNMEASURABLE"]
