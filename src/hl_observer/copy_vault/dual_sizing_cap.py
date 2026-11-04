"""[COPY-VAULT #53] DUAL SIZING CAP : la taille copiée finale = min(taille_basée_equity, taille_basée_liquidité).
On ne prend jamais la plus grande des deux : la contrainte la plus serrée gagne (soit notre capital, soit ce que
le carnet peut absorber sans slippage excessif). Une des deux non mesurable → UNMEASURABLE (on ne cappe pas
contre un inconnu). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def taille_finale(taille_equity: Any, taille_liquidite: Any) -> dict[str, Any]:
    """min des deux tailles. Si l'une manque → UNMEASURABLE (jamais retomber sur l'autre en douce)."""
    if (
        not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                for x in (taille_equity, taille_liquidite))
        or not all(math.isfinite(float(x)) for x in (taille_equity, taille_liquidite))
    ):
        return {"taille": UNMEASURABLE, "refuse": True, "raison": "TAILLE_MANQUANTE"}
    te, tl = float(taille_equity), float(taille_liquidite)
    taille = min(te, tl)
    return {"taille": round(max(0.0, taille), 12), "contrainte": ("EQUITY" if te <= tl else "LIQUIDITE"),
            "refuse": False}


def sizing_limits_receipt(*, equity_cap: Any, liquidity_cap: Any, venue_cap: Any) -> dict[str, Any]:
    """Apply every observed sizing ceiling and fail closed on any missing ceiling."""

    base = taille_finale(equity_cap, liquidity_cap)
    if base.get("refuse"):
        return {"status": "UNMEASURABLE", "reason": base.get("raison")}
    if not isinstance(venue_cap, (int, float)) or isinstance(venue_cap, bool) or not math.isfinite(float(venue_cap)) or venue_cap < 0.0:
        return {"status": "UNMEASURABLE", "reason": "VENUE_CAP_INVALID"}
    final = min(float(base["taille"]), float(venue_cap))
    return {"status": "PROVEN", "size": round(final, 12), "binding": "VENUE" if venue_cap <= base["taille"] else base["contrainte"]}


__all__ = ["taille_finale", "UNMEASURABLE"]
