"""[ARB pépite 227] ROUNDING-RESIDUAL FORECAST : simuler AVANT l'entrée le DELTA qui restera après arrondi de chaque
jambe à son lot. Chaque jambe arrondie indépendamment laisse un résidu (jambe A remplie 1,2 vs jambe B 1,17) ; on le
PRÉVOIT au lieu de le découvrir après coup. Le résidu prévu alimente la décision d'entrée (#228). Pur, 0 réseau.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _arrondi_bas(x: float, lot: float) -> float:
    return math.floor(x / lot) * lot


def prevoir(taille_cible: Any, *, lot_a: float, lot_b: float) -> dict[str, Any]:
    """Arrondit la taille cible au lot de chaque jambe et renvoie le résidu = |A_arrondie − B_arrondie|.
    Lot/taille invalide → UNMEASURABLE (jamais supposer un résidu nul)."""
    if not isinstance(taille_cible, (int, float)) or taille_cible < 0 \
            or not all(isinstance(x, (int, float)) and x > 0 for x in (lot_a, lot_b)):
        return {"residu": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    a = _arrondi_bas(float(taille_cible), float(lot_a))
    b = _arrondi_bas(float(taille_cible), float(lot_b))
    residu = abs(a - b)
    return {"taille_a": round(a, 12), "taille_b": round(b, 12), "residu": round(residu, 12),
            "residu_bps_de_cible": (round(residu / float(taille_cible) * 1e4, 4) if taille_cible > 0 else 0.0)}


__all__ = ["prevoir", "UNMEASURABLE"]
