"""I2 + I7 — signaux de flux : déséquilibre des AGRESSEURS et variation d'OPEN INTEREST.

I2 : le déséquilibre des takers (volume acheteur agressif − vendeur agressif) mesure la PRESSION
directionnelle réelle du flux qui BOUGE le prix. I7 : la variation d'open interest, combinée au
mouvement de prix, distingue une tendance SAINE d'une accumulation de LEVIER FRAGILE (risque de
cascade, cf. cluster B). Signaux PURS, à valider au markout. PAPER only.
"""
from __future__ import annotations

from typing import Iterable


def desequilibre_agresseurs(trades: Iterable[dict]) -> float | None:
    """(buy − sell) / (buy + sell) sur le volume des takers. Dans [-1, 1]. None si pas de volume."""
    buy = sell = 0.0
    for t in trades or []:
        if not isinstance(t, dict):
            continue
        s = str(t.get("aggressor") or t.get("side") or "").upper()
        try:
            sz = float(t.get("size") or t.get("sz") or 0.0)
        except (TypeError, ValueError):
            continue
        if s in ("BUY", "B", "A"):
            buy += sz
        elif s in ("SELL", "S"):
            sell += sz
    total = buy + sell
    return (buy - sell) / total if total > 0 else None


def variation_oi(oi_now: float, oi_past: float) -> float | None:
    """Variation relative de l'open interest. None si base invalide."""
    try:
        p = float(oi_past)
        return (float(oi_now) - p) / p if p > 0 else None
    except (TypeError, ValueError):
        return None


def interpretation_oi(delta_oi: float, delta_prix: float, *, seuil: float = 0.0) -> str:
    """OI ↑ + prix ↑ = tendance saine ; OI ↑ + prix ~plat = LEVIER FRAGILE (cascade possible) ;
    OI ↓ = deleveraging (positions qui se ferment)."""
    doi, dpx = float(delta_oi), float(delta_prix)
    if doi <= seuil:
        return "DELEVERAGING"
    if abs(dpx) <= abs(seuil) + 1e-9:
        return "LEVIER_FRAGILE"
    return "TENDANCE_SAINE"


__all__ = ["desequilibre_agresseurs", "variation_oi", "interpretation_oi"]
