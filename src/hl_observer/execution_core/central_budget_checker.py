"""Centralized fail-closed paper capital reservations."""
from __future__ import annotations

import math
from typing import Any


class BudgetCentral:
    """Reservations share one finite paper-capital budget."""

    def __init__(self, capital_total: float) -> None:
        try:
            capital = float(capital_total)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("capital_total must be a finite non-negative number") from exc
        if not math.isfinite(capital) or capital < 0:
            raise ValueError("capital_total must be a finite non-negative number")
        self.capital_total = capital
        self._reserves: dict[str, float] = {}

    def disponible(self) -> float:
        available = self.capital_total - sum(self._reserves.values())
        if not math.isfinite(available):
            raise RuntimeError("capital reservation state is non-finite")
        return round(available, 8)

    def reserver(self, id_reservation: str, montant: Any) -> dict[str, Any]:
        """Reserve only a finite non-negative amount without mutating on failure."""
        reservation_id = str(id_reservation).strip()
        try:
            amount = float(montant)
        except (TypeError, ValueError, OverflowError):
            return {"ok": False, "raison": "MONTANT_INVALIDE"}
        if not reservation_id or not math.isfinite(amount) or amount < 0:
            return {"ok": False, "raison": "MONTANT_INVALIDE"}
        if reservation_id in self._reserves:
            return {"ok": False, "raison": "ID_DEJA_RESERVE", "disponible": self.disponible()}
        available = self.disponible()
        if amount > available + 1e-9:
            return {"ok": False, "raison": "BUDGET_INSUFFISANT", "disponible": available}
        self._reserves[reservation_id] = amount
        return {"ok": True, "reserve": amount, "disponible": self.disponible()}

    def liberer(self, id_reservation: str) -> bool:
        return self._reserves.pop(str(id_reservation), None) is not None


__all__ = ["BudgetCentral"]
