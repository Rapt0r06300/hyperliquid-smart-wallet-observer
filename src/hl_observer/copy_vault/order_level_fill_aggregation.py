"""[COPY-VAULT #63] ORDER-LEVEL FILL AGGREGATION : plusieurs partial fills du même oid appartiennent au MÊME ordre
source. On les agrège (quantité cumulée + VWAP) au lieu de traiter chaque partial comme un ordre distinct — sinon
on sur-copie (N intents pour 1 ordre). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class AgregateurOrdres:
    """Agrège les partial fills par oid en un ordre unique (qté cumulée, prix moyen pondéré)."""

    def __init__(self) -> None:
        self._ordres: dict[str, dict[str, float]] = {}

    def ajouter_fill(self, oid: Any, qte: Any, prix: Any) -> dict[str, Any]:
        """Ajoute un partial fill à son oid. Entrée invalide → ignorée (jamais comptée comme un ordre)."""
        if oid is None or not all(isinstance(x, (int, float)) for x in (qte, prix)) or float(qte) <= 0:
            return {"ok": False, "raison": "FILL_INVALIDE"}
        k = str(oid)
        o = self._ordres.setdefault(k, {"qte": 0.0, "notional": 0.0})
        o["qte"] += float(qte)
        o["notional"] += float(qte) * float(prix)
        return {"ok": True, "oid": k, "qte_cumulee": round(o["qte"], 12)}

    def ordre(self, oid: Any) -> dict[str, Any]:
        """Vue agrégée d'un oid : quantité totale et VWAP. Inconnu → None."""
        o = self._ordres.get(str(oid))
        if o is None or o["qte"] <= 0:
            return {"qte": None, "vwap": None, "raison": "OID_INCONNU"}
        return {"qte": round(o["qte"], 12), "vwap": round(o["notional"] / o["qte"], 10)}

    def nombre_ordres(self) -> int:
        """Nombre d'ordres DISTINCTS (les partials du même oid ne comptent qu'une fois)."""
        return len(self._ordres)


__all__ = ["AgregateurOrdres"]
