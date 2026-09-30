"""[ARB lot2 #19] EXPIRATION D'ORDRE LIBÈRE BUDGET/MARGE IMMÉDIATEMENT : quand un ordre expire (GTD, IOC non
rempli), le budget/la marge qu'il réservait est libéré TOUT DE SUITE, sans attendre un cycle de réconciliation.
Attendre bloque du capital utilisable pour d'autres opportunités. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class BudgetAvecExpiration:
    """Réservations par ordre ; l'expiration libère immédiatement (pas au prochain cycle de réconciliation)."""

    def __init__(self, capital_total: float) -> None:
        self.capital_total = float(capital_total)
        self._reserves: dict[str, float] = {}

    def disponible(self) -> float:
        return round(self.capital_total - sum(self._reserves.values()), 8)

    def reserver(self, order_id: str, montant: Any) -> dict[str, Any]:
        if not isinstance(montant, (int, float)) or float(montant) < 0:
            return {"ok": False, "raison": "MONTANT_INVALIDE"}
        if float(montant) > self.disponible() + 1e-9:
            return {"ok": False, "raison": "BUDGET_INSUFFISANT", "disponible": self.disponible()}
        self._reserves[str(order_id)] = float(montant)
        return {"ok": True, "disponible": self.disponible()}

    def expirer(self, order_id: str) -> dict[str, Any]:
        """Libère IMMÉDIATEMENT le budget réservé par l'ordre expiré. Ordre inconnu → rien à libérer."""
        libere = self._reserves.pop(str(order_id), None)
        if libere is None:
            return {"libere": 0.0, "raison": "ORDRE_INCONNU", "disponible": self.disponible()}
        return {"libere": round(libere, 8), "immediat": True, "disponible": self.disponible()}


__all__ = ["BudgetAvecExpiration"]
