"""[CROSS-VENUE #14] DOUBLE BUDGET RESERVATION : réserver SIMULTANÉMENT capital jambe A + capital jambe B +
frais AVANT d'ouvrir un épisode. Si les trois ne tiennent pas d'un coup dans le disponible, l'épisode est
refusé (jamais ouvrir la jambe A sans garantir de quoi ouvrir la jambe B). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class ReservationBudget:
    """Réserve atomique capital_a + capital_b + frais par épisode ; libération à la fermeture."""

    def __init__(self, capital_total_usd: float) -> None:
        self.capital_total_usd = float(capital_total_usd)
        self._reserve: dict[str, float] = {}

    def disponible(self) -> float:
        return round(self.capital_total_usd - sum(self._reserve.values()), 8)

    def reserver_episode(self, episode_id: str, *, capital_a: float, capital_b: float,
                         frais: float) -> dict[str, Any]:
        """Réserve A+B+frais d'un bloc. Refuse (rien réservé) si ça dépasse le disponible OU si déjà réservé."""
        besoin = float(capital_a) + float(capital_b) + float(frais)
        if episode_id in self._reserve:
            return {"ok": False, "raison": "EPISODE_DEJA_RESERVE", "disponible": self.disponible()}
        if besoin > self.disponible() + 1e-9:
            return {"ok": False, "raison": "BUDGET_INSUFFISANT", "besoin": round(besoin, 8),
                    "disponible": self.disponible()}
        self._reserve[episode_id] = round(besoin, 8)
        return {"ok": True, "reserve": round(besoin, 8), "disponible": self.disponible()}

    def liberer(self, episode_id: str) -> bool:
        return self._reserve.pop(episode_id, None) is not None


__all__ = ["ReservationBudget"]
