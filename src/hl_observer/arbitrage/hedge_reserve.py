"""[CROSS-VENUE #15] HEDGE RESERVE : garder une réserve de capital DISTINCTE, dédiée EXCLUSIVEMENT à fermer
une jambe orpheline (débouclage d'urgence). Elle ne peut jamais servir à OUVRIR une nouvelle position — sinon,
en cas de hedge raté, il ne resterait rien pour se déboucler. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class ReserveHedge:
    """Sépare capital ouvrable et réserve d'unwind. `peut_ouvrir` refuse tout ce qui empiéterait sur la réserve."""

    def __init__(self, capital_total_usd: float, *, reserve_unwind_usd: float) -> None:
        self.capital_total_usd = float(capital_total_usd)
        self.reserve_unwind_usd = float(reserve_unwind_usd)
        self._ouvert = 0.0
        self._unwind_utilise = 0.0

    def capital_ouvrable(self) -> float:
        return round(self.capital_total_usd - self.reserve_unwind_usd - self._ouvert, 8)

    def peut_ouvrir(self, montant: float) -> dict[str, Any]:
        """Autorise l'ouverture seulement si elle NE touche PAS la réserve d'unwind."""
        ok = float(montant) <= self.capital_ouvrable() + 1e-9
        return {"ok": bool(ok), "capital_ouvrable": self.capital_ouvrable(),
                "reserve_unwind_usd": self.reserve_unwind_usd,
                "raison": ("OK" if ok else "EMPIETE_SUR_RESERVE_UNWIND")}

    def ouvrir(self, montant: float) -> bool:
        if self.peut_ouvrir(montant)["ok"]:
            self._ouvert += float(montant)
            return True
        return False

    def utiliser_pour_unwind(self, montant: float) -> dict[str, Any]:
        """La réserve ne sert QU'À déboucler une jambe orpheline."""
        dispo = self.reserve_unwind_usd - self._unwind_utilise
        pris = max(0.0, min(float(montant), dispo))
        self._unwind_utilise += pris
        return {"pris": round(pris, 8), "reste_reserve": round(dispo - pris, 8),
                "refuse": round(max(0.0, float(montant) - pris), 8)}


__all__ = ["ReserveHedge"]
