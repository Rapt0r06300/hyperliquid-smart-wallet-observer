"""[ARB #20] LIQUIDITY OWNERSHIP : lorsqu'une opportunité RÉSERVE un niveau du carnet, réduire IMMÉDIATEMENT la
liquidité disponible pour les AUTRES simulations. Chaque réservation est attribuée à un propriétaire (owner) et
libérée à la fermeture de son épisode ; le disponible « pour les autres » exclut les réservations d'autrui.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class ProprieteLiquidite:
    """Réservations attribuées par owner. `disponible_pour(owner)` = affiché − réservations des AUTRES owners."""

    def __init__(self) -> None:
        self._par_owner: dict[str, dict[tuple, float]] = {}

    def _cle(self, venue: str, coin: str, niveau: Any) -> tuple:
        return (str(venue).upper(), str(coin).upper(), round(float(niveau), 10))

    def _reserve_autres(self, owner: str, cle: tuple) -> float:
        return sum(res.get(cle, 0.0) for o, res in self._par_owner.items() if o != owner)

    def disponible_pour(self, owner: str, venue: str, coin: str, niveau: Any, *, affiche_usd: float) -> float:
        cle = self._cle(venue, coin, niveau)
        return round(max(0.0, float(affiche_usd) - self._reserve_autres(owner, cle)), 8)

    def reserver(self, owner: str, venue: str, coin: str, niveau: Any, montant_usd: float, *,
                 affiche_usd: float) -> dict[str, Any]:
        cle = self._cle(venue, coin, niveau)
        dispo = self.disponible_pour(owner, venue, coin, niveau, affiche_usd=affiche_usd)
        deja = self._par_owner.get(owner, {}).get(cle, 0.0)
        pris = max(0.0, min(float(montant_usd), dispo - deja))
        self._par_owner.setdefault(owner, {})[cle] = deja + pris
        return {"owner": owner, "pris_usd": round(pris, 8),
                "refuse_usd": round(max(0.0, float(montant_usd) - pris), 8)}

    def liberer(self, owner: str) -> bool:
        """À la fermeture de l'épisode : la liquidité de cet owner redevient dispo pour les autres."""
        return self._par_owner.pop(owner, None) is not None


__all__ = ["ProprieteLiquidite"]
