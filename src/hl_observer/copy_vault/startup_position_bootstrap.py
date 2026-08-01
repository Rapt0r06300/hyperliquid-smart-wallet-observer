"""[COPY-VAULT #58] STARTUP POSITION BOOTSTRAP : télécharger l'état COMPLET du vault (positions ouvertes) AVANT de
traiter le premier fill live. Sans baseline, un premier fill « réduction » serait interprété comme une ouverture
(delta calculé contre une position supposée nulle). Tant que le bootstrap n'est pas fait, aucun fill n'est traité.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class Bootstrap:
    """Porte d'entrée : bloque le traitement des fills tant que l'état initial du vault n'est pas chargé."""

    def __init__(self) -> None:
        self._pret = False
        self._positions: dict[str, float] = {}

    def charger_etat(self, positions: Mapping[str, Any]) -> dict[str, Any]:
        """Charge la baseline (coin → taille signée). Rend le bootstrap prêt."""
        self._positions = {str(k).upper(): float(v) for k, v in dict(positions).items()
                           if isinstance(v, (int, float))}
        self._pret = True
        return {"pret": True, "n_positions": len(self._positions)}

    def pret(self) -> bool:
        return self._pret

    def position_initiale(self, coin: str) -> float:
        return self._positions.get(str(coin).upper(), 0.0)

    def peut_traiter_fill(self) -> dict[str, Any]:
        """Un fill live n'est traité qu'après bootstrap (sinon delta calculé contre une baseline inconnue)."""
        return {"ok": bool(self._pret), "raison": ("OK" if self._pret else "BOOTSTRAP_NON_FAIT")}


__all__ = ["Bootstrap"]
