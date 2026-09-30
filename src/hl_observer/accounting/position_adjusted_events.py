"""[ACCOUNTING pépite 219] PositionAdjusted EVENTS : les commissions en base, les corrections et les ajustements
externes deviennent des ÉVÉNEMENTS COMPTABLES DISTINCTS des trades (modèle Nautilus). Mélanger un ajustement de
commission avec un fill fausse le prix moyen et le PnL réalisé ; un événement PositionAdjusted séparé garde la
comptabilité traçable (chaque mouvement a une cause typée). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

TRADE = "TRADE"
COMMISSION_BASE = "COMMISSION_BASE"
CORRECTION = "CORRECTION"
AJUSTEMENT_EXTERNE = "AJUSTEMENT_EXTERNE"
_TYPES_AJUST = (COMMISSION_BASE, CORRECTION, AJUSTEMENT_EXTERNE)


class LedgerPositions:
    """Journal d'événements typés. Les ajustements sont distincts des trades ; la position agrège les deux."""

    def __init__(self) -> None:
        self._evenements: list[dict[str, Any]] = []

    def trade(self, *, coin: str, delta_qty: float) -> None:
        self._evenements.append({"type": TRADE, "coin": str(coin).upper(), "delta_qty": float(delta_qty)})

    def ajuster(self, *, coin: str, delta_qty: float, cause: str) -> dict[str, Any]:
        """Enregistre un PositionAdjusted (commission base / correction / ajustement externe), distinct d'un trade.
        Cause hors taxonomie → refus (un ajustement doit avoir une cause typée, jamais anonyme)."""
        c = str(cause).upper()
        if c not in _TYPES_AJUST:
            return {"ok": False, "raison": "CAUSE_AJUSTEMENT_INCONNUE"}
        self._evenements.append({"type": c, "coin": str(coin).upper(), "delta_qty": float(delta_qty)})
        return {"ok": True, "type": c}

    def position(self, coin: str) -> float:
        c = str(coin).upper()
        return round(sum(e["delta_qty"] for e in self._evenements if e["coin"] == c), 12)

    def part_ajustements(self, coin: str) -> float:
        """Somme des delta issus d'ajustements (hors trades) — visible séparément, pas noyée dans les trades."""
        c = str(coin).upper()
        return round(sum(e["delta_qty"] for e in self._evenements
                         if e["coin"] == c and e["type"] in _TYPES_AJUST), 12)


__all__ = ["LedgerPositions", "TRADE", "COMMISSION_BASE", "CORRECTION", "AJUSTEMENT_EXTERNE"]
