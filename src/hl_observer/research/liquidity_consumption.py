"""ALPHA P25 — LEDGER de consommation de liquidité : une quantité affichée ne peut être remplie qu'UNE fois.

Erreur classique de sur-optimisme : croire pouvoir remplir plusieurs fois la même taille affichée à un
niveau. Ici on tient un ledger par (snapshot, prix) : chaque consommation décrémente le disponible ; on ne
reconstitue QU'APRÈS une vraie update de carnet (nouveau snapshot). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class LiquidityLedger:
    """Suit la liquidité restante par (snapshot_id, prix). Remplissage borné par l'affiché."""

    def __init__(self) -> None:
        self._snap: Any = None
        self._restant: dict[float, float] = {}

    def nouvelle_update(self, snapshot_id: Any, niveaux: Mapping[float, float]) -> None:
        """Une VRAIE update de carnet : on repart de l'affiché (reconstitution seulement ici)."""
        self._snap = snapshot_id
        self._restant = {float(px): float(sz) for px, sz in niveaux.items()}

    def consommer(self, prix: float, qty: float) -> dict[str, Any]:
        """Consomme jusqu'à l'affiché restant à ce prix. Retourne rempli/refusé (jamais plus que dispo)."""
        px = float(prix)
        dispo = self._restant.get(px, 0.0)
        rempli = max(0.0, min(float(qty), dispo))
        self._restant[px] = round(dispo - rempli, 12)
        return {"snapshot": self._snap, "prix": px, "demande": float(qty), "rempli": round(rempli, 12),
                "refuse": round(float(qty) - rempli, 12), "restant": self._restant[px]}


__all__ = ["LiquidityLedger"]
