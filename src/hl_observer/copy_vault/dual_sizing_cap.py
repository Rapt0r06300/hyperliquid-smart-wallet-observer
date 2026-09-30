"""[COPY-VAULT #53] DUAL SIZING CAP : la taille copiée finale = min(taille_basée_equity, taille_basée_liquidité).
On ne prend jamais la plus grande des deux : la contrainte la plus serrée gagne (soit notre capital, soit ce que
le carnet peut absorber sans slippage excessif). Une des deux non mesurable → UNMEASURABLE (on ne cappe pas
contre un inconnu). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def taille_finale(taille_equity: Any, taille_liquidite: Any) -> dict[str, Any]:
    """min des deux tailles. Si l'une manque → UNMEASURABLE (jamais retomber sur l'autre en douce)."""
    if not all(isinstance(x, (int, float)) for x in (taille_equity, taille_liquidite)):
        return {"taille": UNMEASURABLE, "refuse": True, "raison": "TAILLE_MANQUANTE"}
    te, tl = float(taille_equity), float(taille_liquidite)
    taille = min(te, tl)
    return {"taille": round(max(0.0, taille), 12), "contrainte": ("EQUITY" if te <= tl else "LIQUIDITE"),
            "refuse": False}


__all__ = ["taille_finale", "UNMEASURABLE"]
