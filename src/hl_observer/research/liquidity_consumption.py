"""ALPHA P25 — LEDGER de consommation de liquidité : une quantité affichée ne peut être remplie qu'UNE fois.

Erreur classique de sur-optimisme : croire pouvoir remplir plusieurs fois la même taille affichée à un
niveau. Ici on tient un ledger par (snapshot, prix) : chaque consommation décrémente le disponible ; on ne
reconstitue QU'APRÈS une vraie update de carnet (nouveau snapshot). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import math


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


def size_impact_receipt(levels: Mapping[float, float], request_notionals: list[float] | tuple[float, ...]) -> dict[str, object]:
    """Compare observed depth consumption for several paper request sizes."""

    if not levels or not request_notionals:
        return {"status": "UNMEASURABLE", "reason": "OBSERVATIONS_INSUFFICIENT"}
    clean_levels = []
    for price, size in levels.items():
        try:
            px, qty = float(price), float(size)
        except (TypeError, ValueError, OverflowError):
            return {"status": "UNMEASURABLE", "reason": "LEVEL_INVALID"}
        if not math.isfinite(px) or not math.isfinite(qty) or px <= 0.0 or qty <= 0.0:
            return {"status": "UNMEASURABLE", "reason": "LEVEL_INVALID"}
        clean_levels.append((px, qty))
    results = []
    for raw_request in request_notionals:
        try:
            request = float(raw_request)
        except (TypeError, ValueError, OverflowError):
            return {"status": "UNMEASURABLE", "reason": "REQUEST_INVALID"}
        if not math.isfinite(request) or request <= 0.0:
            return {"status": "UNMEASURABLE", "reason": "REQUEST_INVALID"}
        remaining, consumed = request, 0.0
        for px, qty in clean_levels:
            take = min(remaining, px * qty)
            consumed += take
            remaining -= take
            if remaining <= 0.0:
                break
        results.append({"requested": request, "consumed": round(consumed, 10), "unfilled": round(max(0.0, remaining), 10)})
    return {"status": "PROVEN", "results": results}


__all__ = ["LiquidityLedger", "size_impact_receipt"]
