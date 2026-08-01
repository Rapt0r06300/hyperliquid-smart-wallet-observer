"""[CABLAGE étage C] CROSS-VENUE STAGE : à partir d'un EDGE cross-venue MESURÉ (bps, après coûts), émettre une
intention de HEDGE de sens opposé sur la venue de couverture — ce qui rend la copie plus proche du neutre au
marché. Honnêteté dure : sans edge mesuré (donnée absente) ou sous le seuil, AUCUN hedge n'est fabriqué. Le
hedge est sur une venue DIFFÉRENTE (même coin) : le self-trade-prevention (qui clé sur venue+coin) ne le
confondra donc pas avec un auto-croisement. 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def intent_hedge(*, coin: Any, notional_copie_signe: Any, edge_cross_venue_bps: Any,
                 venue_hedge: str = "BINANCE", module: str = "CROSS_VENUE",
                 seuil_edge_bps: float = 1.0) -> dict[str, Any]:
    """Retourne {hedge: intent|None, raison, edge_bps?}. Le hedge a un montant signé opposé à la copie (même
    |notional|) sur venue_hedge. Émis SEULEMENT si l'edge mesuré ≥ seuil (sinon None, honnête)."""
    if not coin:
        return {"hedge": None, "raison": "COIN_MANQUANT"}
    if not isinstance(edge_cross_venue_bps, (int, float)) or isinstance(edge_cross_venue_bps, bool) \
            or not isinstance(notional_copie_signe, (int, float)) or isinstance(notional_copie_signe, bool):
        return {"hedge": None, "raison": "DONNEE_INSUFFISANTE"}      # jamais de hedge fabriqué
    if float(edge_cross_venue_bps) < float(seuil_edge_bps):
        return {"hedge": None, "raison": "EDGE_SOUS_SEUIL", "edge_bps": float(edge_cross_venue_bps)}
    hedge = {"module": module, "venue": str(venue_hedge).upper(), "coin": str(coin).upper(),
             "montant_signe": round(-float(notional_copie_signe), 8), "type": "ARB_HEDGE"}
    return {"hedge": hedge, "raison": "OK", "edge_bps": float(edge_cross_venue_bps)}


__all__ = ["intent_hedge"]
