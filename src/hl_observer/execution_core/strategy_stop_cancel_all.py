"""[ALL lot2 #95] STRATEGY STOP = CANCEL-ALL DE SES CHILD ORDERS : l'arrêt d'une stratégie DOIT annuler TOUS ses
child orders. Laisser des ordres actifs orphelins après l'arrêt d'une stratégie (bugs répétés dans VeighNa) expose à
des fills fantômes sur une stratégie censée être éteinte. On produit la liste des ordres à annuler et on garantit
qu'il n'en reste aucun d'actif. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class GestionnaireChildOrders:
    """Suit les child orders par stratégie. `arreter` renvoie tous les ordres à annuler et vide l'état."""

    def __init__(self) -> None:
        self._ordres: dict[str, set] = {}

    def enregistrer(self, strategie: str, order_id: str) -> None:
        self._ordres.setdefault(str(strategie), set()).add(str(order_id))

    def retirer(self, strategie: str, order_id: str) -> None:
        self._ordres.get(str(strategie), set()).discard(str(order_id))

    def actifs(self, strategie: str) -> list[str]:
        return sorted(self._ordres.get(str(strategie), set()))

    def arreter(self, strategie: str) -> dict[str, Any]:
        """Annule TOUS les child orders de la stratégie ; après, il n'en reste aucun d'actif (invariant vérifié)."""
        a_annuler = sorted(self._ordres.pop(str(strategie), set()))
        return {"a_annuler": a_annuler, "n": len(a_annuler), "reste_actifs": len(self.actifs(strategie)),
                "aucun_orphelin": len(self.actifs(strategie)) == 0}


__all__ = ["GestionnaireChildOrders"]
