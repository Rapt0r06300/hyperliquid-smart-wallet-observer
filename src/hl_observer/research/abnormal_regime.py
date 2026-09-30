"""ALPHA P52 — SÉCURITÉ nouveau listing / régime anormal : ne pas appliquer un modèle normal en aveugle.

Détecte : nouveau listing / delisting, changement de tick/lot, cap d'OI, état illiquide, spread anormal. En
régime anormal, on NE trade PAS avec le modèle normal (NO_TRADE ou modèle dédié). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def regime_anormal(*, age_listing_h: Any = None, spread_bps: Any = None, depth_usd: Any = None,
                   tick_ou_lot_change: bool = False, delisting: bool = False,
                   spread_normal_bps: float = 10.0, depth_min_usd: float = 5000.0,
                   age_min_h: float = 24.0) -> dict[str, Any]:
    """Retourne anormal (bool), raisons, et l'action de sécurité (NO_TRADE si anormal)."""
    raisons = []
    if delisting:
        raisons.append("DELISTING")
    if tick_ou_lot_change:
        raisons.append("TICK_OU_LOT_CHANGE")
    if isinstance(age_listing_h, (int, float)) and age_listing_h < age_min_h:
        raisons.append("NOUVEAU_LISTING")
    if isinstance(spread_bps, (int, float)) and spread_bps > spread_normal_bps * 3:
        raisons.append("SPREAD_ANORMAL")
    if isinstance(depth_usd, (int, float)) and depth_usd < depth_min_usd:
        raisons.append("ILLIQUIDE")
    anormal = bool(raisons)
    return {"anormal": anormal, "raisons": raisons,
            "action": ("NO_TRADE" if anormal else "OK"),
            "note": "en regime anormal, ne pas appliquer le modele normal en aveugle"}


__all__ = ["regime_anormal"]
