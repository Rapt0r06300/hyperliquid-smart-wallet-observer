"""ALPHA P30 — LIQUIDATION FLOW observer : direction/notional/impact/épuisement/continuation → régime CASCADE.

On agrège les liquidations : sens dominant, notional total, impact carnet, épuisement de profondeur,
continuation du prix. Un amas de liquidations même sens dans une fenêtre courte = régime LIQUIDATION_CASCADE
(filtre de régime, SHADOW jusqu'à preuve). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def analyser(liquidations: Sequence[Mapping[str, Any]], *, fenetre_ms: int = 5000, seuil_amas: int = 3) -> dict[str, Any]:
    """Agrège les liquidations et détecte les amas (cascade). Chaque liq : {ts_ms, side(-1/1), notional_usd, impact_bps}."""
    liqs = sorted((l for l in liquidations if isinstance(l.get("ts_ms"), (int, float))), key=lambda l: l["ts_ms"])
    if not liqs:
        return {"n": 0, "regime": "AUCUNE", "cascades": []}
    notional = sum(float(l.get("notional_usd", 0.0)) for l in liqs)
    net_side = sum(float(l.get("side", 0)) * float(l.get("notional_usd", 0.0)) for l in liqs)
    sens_dominant = 1 if net_side > 0 else (-1 if net_side < 0 else 0)
    # amas : >= seuil liquidations MÊME sens en < fenetre_ms
    cascades = []
    i = 0
    while i < len(liqs):
        j = i
        while j + 1 < len(liqs) and (liqs[j + 1]["ts_ms"] - liqs[i]["ts_ms"]) <= fenetre_ms:
            j += 1
        bloc = liqs[i:j + 1]
        meme_sens = [l for l in bloc if float(l.get("side", 0)) == float(bloc[0].get("side", 0))]
        if len(meme_sens) >= seuil_amas:
            cascades.append({"debut_ms": bloc[0]["ts_ms"], "n": len(meme_sens),
                             "side": bloc[0].get("side"), "notional": round(sum(float(l.get("notional_usd", 0.0)) for l in meme_sens), 2)})
            i = j + 1
        else:
            i += 1
    return {"n": len(liqs), "notional_total_usd": round(notional, 2), "sens_dominant": sens_dominant,
            "cascades": cascades, "regime": ("LIQUIDATION_CASCADE" if cascades else "DIFFUS")}


__all__ = ["analyser"]
