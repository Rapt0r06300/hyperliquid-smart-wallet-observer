"""[EXEC pépite 207] BALANCE RECONCILIATION : vérifier SÉPARÉMENT que le cash/equity DÉRIVÉS de notre ledger
correspondent aux reports d'accounting disponibles (venue). La position peut être juste alors que le cash dérive
(frais mal comptés, funding oublié) ; réconcilier la balance en plus de la position attrape ces écarts monétaires.
Données invalides → divergence présumée. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def reconcilier(*, cash_ledger: Any, cash_report: Any, tolerance_abs: float = 0.01) -> dict[str, Any]:
    """Compare le cash dérivé du ledger au cash rapporté par l'accounting. Écart > tolérance → divergence
    (frais/funding mal comptés), avec l'écart signé. Données invalides → divergence présumée (fail-closed)."""
    if not all(isinstance(x, (int, float)) for x in (cash_ledger, cash_report)):
        return {"coherent": False, "raison": "DONNEE_INVALIDE"}
    ecart = float(cash_report) - float(cash_ledger)
    if abs(ecart) > float(tolerance_abs):
        return {"coherent": False, "ecart": round(ecart, 8), "raison": "CASH_LEDGER_DIVERGE_DU_REPORT"}
    return {"coherent": True, "raison": "BALANCE_RECONCILIEE"}


__all__ = ["reconcilier"]
