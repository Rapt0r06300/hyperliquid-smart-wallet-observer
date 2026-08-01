"""[ALL lot2 #94] VIRTUAL SUBACCOUNTS PAR MODULE : Cross-Venue, Copy-Vault et les autres stratégies possèdent leurs
budgets/equities INTERNES ISOLÉS avant consolidation du portefeuille. Un sous-compte virtuel par module empêche
qu'une stratégie consomme le capital d'une autre et rend l'attribution PnL propre (Nautilus : exécution
multi-account). La consolidation somme les sous-comptes. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class SousComptesVirtuels:
    """Un budget/equity isolé par module. Un module ne peut dépenser que SON solde ; consolidation = somme."""

    def __init__(self) -> None:
        self._solde: dict[str, float] = {}

    def crediter(self, module: str, montant: float) -> None:
        self._solde[str(module)] = self._solde.get(str(module), 0.0) + float(montant)

    def solde(self, module: str) -> float:
        return round(self._solde.get(str(module), 0.0), 8)

    def peut_depenser(self, module: str, montant: Any) -> dict[str, Any]:
        """Autorise seulement si le montant tient dans le solde ISOLÉ du module (pas le total consolidé)."""
        if not isinstance(montant, (int, float)) or float(montant) < 0:
            return {"ok": False, "raison": "MONTANT_INVALIDE"}
        dispo = self.solde(module)
        ok = float(montant) <= dispo + 1e-9
        return {"ok": bool(ok), "solde_module": dispo,
                "raison": ("OK" if ok else "SOLDE_MODULE_INSUFFISANT")}

    def consolider(self) -> float:
        """Equity consolidée = somme des sous-comptes."""
        return round(sum(self._solde.values()), 8)


__all__ = ["SousComptesVirtuels"]
