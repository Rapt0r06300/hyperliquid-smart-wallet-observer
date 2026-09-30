"""[ARB pépite 225] MARKET-ORDER PRICE PROTECTION : même une jambe URGENTE (débouclage, hedge) reçoit un prix
MAXIMUM (achat) / MINIMUM (vente) d'exécution acceptable, pour empêcher un SWEEP catastrophique du carnet (un market
illimité peut manger toute la profondeur à un prix absurde). Au-delà du prix protégé, la partie non remplie reste
non exécutée. Prix invalide → refus (pas de market non protégé). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def prix_limite_protege(prix_reference: Any, sens: Any, *, tolerance_bps: float = 50.0) -> dict[str, Any]:
    """Convertit un market urgent en limit protégé : achat plafonné à ref×(1+tol), vente planchée à ref×(1-tol).
    Prix invalide / sens inconnu → refus (jamais de market illimité)."""
    if not isinstance(prix_reference, (int, float)) or float(prix_reference) <= 0:
        return {"ok": False, "raison": "PRIX_REFERENCE_INVALIDE"}
    s = str(sens).upper()
    f = float(tolerance_bps) / 1e4
    if s in ("ACHAT", "BUY", "LONG"):
        return {"ok": True, "prix_max": round(float(prix_reference) * (1.0 + f), 10), "sens": "ACHAT"}
    if s in ("VENTE", "SELL", "SHORT"):
        return {"ok": True, "prix_min": round(float(prix_reference) * (1.0 - f), 10), "sens": "VENTE"}
    return {"ok": False, "raison": "SENS_INCONNU"}


def remplissable(prix_niveau: Any, *, sens: Any, borne: Any) -> bool:
    """Un niveau du carnet est remplissable seulement s'il ne dépasse pas la borne protégée."""
    if not all(isinstance(x, (int, float)) for x in (prix_niveau, borne)):
        return False
    s = str(sens).upper()
    if s in ("ACHAT", "BUY", "LONG"):
        return float(prix_niveau) <= float(borne)
    return float(prix_niveau) >= float(borne)


__all__ = ["prix_limite_protege", "remplissable"]
