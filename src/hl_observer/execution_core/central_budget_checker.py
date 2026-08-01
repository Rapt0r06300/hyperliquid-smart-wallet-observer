"""[ALL #88] CENTRAL BudgetChecker : le capital est réservé au niveau EXÉCUTION (une seule source de vérité), pas
dans chaque stratégie séparément. Sans budget central, deux stratégies peuvent réserver le même capital et le
sur-engager. Abstraction présente dans Hummingbot. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class BudgetCentral:
    """Réservations de capital centralisées par id. `disponible` = total − somme des réservations."""

    def __init__(self, capital_total: float) -> None:
        self.capital_total = float(capital_total)
        self._reserves: dict[str, float] = {}

    def disponible(self) -> float:
        return round(self.capital_total - sum(self._reserves.values()), 8)

    def reserver(self, id_reservation: str, montant: Any) -> dict[str, Any]:
        """Réserve si le disponible suffit ET si l'id n'a pas déjà une réservation. Sinon refuse sans muter."""
        if not isinstance(montant, (int, float)) or float(montant) < 0:
            return {"ok": False, "raison": "MONTANT_INVALIDE"}
        if str(id_reservation) in self._reserves:
            return {"ok": False, "raison": "ID_DEJA_RESERVE", "disponible": self.disponible()}
        if float(montant) > self.disponible() + 1e-9:
            return {"ok": False, "raison": "BUDGET_INSUFFISANT", "disponible": self.disponible()}
        self._reserves[str(id_reservation)] = float(montant)
        return {"ok": True, "reserve": float(montant), "disponible": self.disponible()}

    def liberer(self, id_reservation: str) -> bool:
        return self._reserves.pop(str(id_reservation), None) is not None


__all__ = ["BudgetCentral"]
