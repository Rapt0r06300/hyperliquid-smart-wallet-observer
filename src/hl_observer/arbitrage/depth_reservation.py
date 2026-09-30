"""[CROSS-VENUE #19] DEPTH RESERVATION : deux opportunités simultanées ne peuvent PAS toutes deux consommer
virtuellement les mêmes $5 000 affichés dans le carnet. On tient un registre de profondeur réservée par
(venue, coin, niveau) ; le disponible = affiché − réservé ; une seconde réservation ne peut pas dépasser ce
qui reste. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class ReservationCarnet:
    """Registre de profondeur réservée. Empêche la double consommation de la même liquidité affichée."""

    def __init__(self) -> None:
        self._reserve: dict[tuple, float] = {}

    def _cle(self, venue: str, coin: str, niveau: Any) -> tuple:
        return (str(venue).upper(), str(coin).upper(), round(float(niveau), 10))

    def disponible(self, venue: str, coin: str, niveau: Any, *, affiche_usd: float) -> float:
        return round(max(0.0, float(affiche_usd) - self._reserve.get(self._cle(venue, coin, niveau), 0.0)), 8)

    def reserver(self, venue: str, coin: str, niveau: Any, montant_usd: float, *,
                 affiche_usd: float) -> dict[str, Any]:
        """Réserve au plus le disponible ; le surplus est REFUSÉ (jamais deux fois la même profondeur)."""
        cle = self._cle(venue, coin, niveau)
        dispo = self.disponible(venue, coin, niveau, affiche_usd=affiche_usd)
        pris = max(0.0, min(float(montant_usd), dispo))
        self._reserve[cle] = self._reserve.get(cle, 0.0) + pris
        return {"pris_usd": round(pris, 8), "refuse_usd": round(max(0.0, float(montant_usd) - pris), 8),
                "restant_usd": round(dispo - pris, 8)}


__all__ = ["ReservationCarnet"]
