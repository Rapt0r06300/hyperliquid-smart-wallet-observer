"""[ALL #93] RESTART RECONCILIATION : au démarrage, RESTAURER les executors terminés, les positions détenues et le
PnL depuis la persistance AVANT de produire la moindre nouvelle décision. Décider sans avoir rechargé l'état réel
reviendrait à ignorer des positions ouvertes (double engagement, PnL faux). Tant que la réconciliation n'est pas
faite, aucune nouvelle décision. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class Reconciliateur:
    """Porte de démarrage : bloque les nouvelles décisions tant que l'état persistant n'a pas été rechargé."""

    def __init__(self) -> None:
        self._pret = False
        self.executors: list[Any] = []
        self.positions: dict[str, Any] = {}
        self.pnl_realise = 0.0

    def restaurer(self, *, executors: Any = None, positions: Mapping[str, Any] | None = None,
                  pnl_realise: Any = 0.0) -> dict[str, Any]:
        """Recharge l'état depuis la persistance. Rend le moteur prêt à décider."""
        self.executors = list(executors or [])
        self.positions = dict(positions or {})
        self.pnl_realise = float(pnl_realise) if isinstance(pnl_realise, (int, float)) else 0.0
        self._pret = True
        return {"pret": True, "n_executors": len(self.executors), "n_positions": len(self.positions)}

    def peut_decider(self) -> dict[str, Any]:
        """Aucune nouvelle décision avant réconciliation complète."""
        return {"ok": bool(self._pret), "raison": ("OK" if self._pret else "RECONCILIATION_NON_FAITE")}


__all__ = ["Reconciliateur"]
