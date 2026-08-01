"""[COPY-VAULT #85] FILL BATCHING WINDOW : une rafale de micro-fills issue du MÊME ordre leader (oid) peut être
compressée sur une courte fenêtre temporelle AVANT réplication, pour éviter de payer le spread/les coûts N fois.
On accumule les partials d'un oid tant que la fenêtre n'est pas écoulée, puis on émet un seul fill agrégé (VWAP).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class FenetreBatch:
    """Regroupe les partials d'un oid dans une fenêtre `fenetre_ms` ; `prete` émet l'agrégat une fois écoulée."""

    def __init__(self, *, fenetre_ms: float = 250.0) -> None:
        self.fenetre_ms = float(fenetre_ms)
        self._lots: dict[str, dict[str, float]] = {}

    def ajouter(self, oid: Any, qte: Any, prix: Any, *, now_ms: Any) -> dict[str, Any]:
        """Ajoute un partial à la fenêtre de son oid. Entrée invalide → ignorée."""
        if oid is None or not all(isinstance(x, (int, float)) for x in (qte, prix, now_ms)) or float(qte) <= 0:
            return {"ok": False, "raison": "FILL_INVALIDE"}
        k = str(oid)
        lot = self._lots.setdefault(k, {"qte": 0.0, "notional": 0.0, "ouvert_ms": float(now_ms)})
        lot["qte"] += float(qte)
        lot["notional"] += float(qte) * float(prix)
        return {"ok": True, "qte_accumulee": round(lot["qte"], 12)}

    def prete(self, oid: Any, *, now_ms: Any) -> dict[str, Any]:
        """Si la fenêtre de l'oid est écoulée, renvoie l'agrégat (qté, VWAP) et vide le lot ; sinon en attente."""
        lot = self._lots.get(str(oid))
        if lot is None or not isinstance(now_ms, (int, float)):
            return {"prete": False, "raison": "OID_INCONNU_OU_TEMPS_INVALIDE"}
        if float(now_ms) - lot["ouvert_ms"] < self.fenetre_ms:
            return {"prete": False, "raison": "FENETRE_EN_COURS"}
        agg = {"prete": True, "qte": round(lot["qte"], 12), "vwap": round(lot["notional"] / lot["qte"], 10)}
        del self._lots[str(oid)]
        return agg


__all__ = ["FenetreBatch"]
