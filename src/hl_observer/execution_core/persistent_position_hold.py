"""[ALL #92] PERSISTENT PositionHold : toute exposition qui SURVIT à l'arrêt d'un executor est stockée
EXPLICITEMENT — avec prix d'entrée, frais, PnL réalisé et non réalisé. Une position qui reste ouverte quand son
executor s'arrête ne doit pas disparaître des comptes : elle est persistée pour être reprise/débouclée. Champs
incomplets → refus (on ne stocke pas un hold à moitié chiffré). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_REQUIS = ("taille", "entry_price", "fees", "realized_pnl", "unrealized_pnl")


class StockPositionHold:
    """Stockage (persistance simulée) des expositions résiduelles avec leur comptabilité complète."""

    def __init__(self) -> None:
        self._holds: dict[str, dict[str, Any]] = {}

    def stocker(self, coin: str, **champs: Any) -> dict[str, Any]:
        """Persiste un hold. Tous les champs comptables requis doivent être numériques, sinon refus."""
        manquants = [k for k in _REQUIS if not isinstance(champs.get(k), (int, float))]
        if manquants:
            return {"ok": False, "manquants": manquants, "raison": "HOLD_INCOMPLET"}
        self._holds[str(coin).upper()] = {k: float(champs[k]) for k in _REQUIS}
        return {"ok": True, "coin": str(coin).upper()}

    def charger(self, coin: str) -> Any:
        return dict(self._holds[str(coin).upper()]) if str(coin).upper() in self._holds else None

    def lister(self) -> list[str]:
        return sorted(self._holds.keys())


__all__ = ["StockPositionHold"]
