"""[ARB lot2 #15] RECOVERY PAR FILL WS : un fill reçu via WebSocket AVANT la réponse REST/WS de soumission doit
pouvoir RATTACHER et résoudre un ordre resté UNKNOWN. Les fills arrivent parfois avant l'accusé de soumission ;
un fill orphelin qui correspond à un ordre UNKNOWN le confirme (FILLED) au lieu de le laisser en suspens. Pur, 0 réseau.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def rattacher_fill(fill: Mapping[str, Any], ordres_unknown: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Cherche parmi les ordres UNKNOWN celui qui correspond au fill (même client_order_id, ou même coin+côté).
    Trouvé → l'ordre passe FILLED (résolu). Aucune correspondance → fill reste orphelin (à réconcilier), jamais
    attribué de force à un ordre au hasard."""
    coid = fill.get("client_order_id")
    if coid is not None and str(coid) in ordres_unknown:
        return {"resolu": True, "order_id": str(coid), "statut": "FILLED", "methode": "CLIENT_ORDER_ID"}
    fcoin, fcote = str(fill.get("coin", "")).upper(), str(fill.get("cote", "")).upper()
    for oid, o in ordres_unknown.items():
        if str(o.get("coin", "")).upper() == fcoin and str(o.get("cote", "")).upper() == fcote and fcoin:
            return {"resolu": True, "order_id": str(oid), "statut": "FILLED", "methode": "COIN_COTE"}
    return {"resolu": False, "statut": "FILL_ORPHELIN", "raison": "AUCUN_ORDRE_UNKNOWN_CORRESPONDANT"}


__all__ = ["rattacher_fill"]
