"""[CROSS-VENUE #12] TICK/LOT PREFLIGHT : transformer la taille (et le prix) en valeurs RÉELLEMENT admissibles
(multiples du lot / du tick de la venue) AVANT de mesurer l'edge. Mesurer l'edge sur une taille non exécutable
donne un edge fictif. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def arrondir_tick(prix: Any, tick: float) -> Any:
    """Arrondit un prix au tick INFÉRIEUR admissible (on ne suppose jamais un prix plus favorable)."""
    if not isinstance(prix, (int, float)) or not isinstance(tick, (int, float)) or tick <= 0:
        return UNMEASURABLE
    return round(math.floor(float(prix) / tick) * tick, 12)


def taille_admissible(taille: Any, *, lot_size: float, min_lot: float = 0.0) -> Any:
    """Plus grand multiple de `lot_size` ≤ `taille` ; 0 si sous `min_lot` (jamais arrondi vers le haut)."""
    if not isinstance(taille, (int, float)) or not isinstance(lot_size, (int, float)) or lot_size <= 0:
        return UNMEASURABLE
    q = math.floor(float(taille) / lot_size) * lot_size
    return 0.0 if q < float(min_lot) else round(q, 12)


def preflight_tick_lot(prix: Any, taille: Any, *, tick: float, lot_size: float, min_lot: float = 0.0) -> dict[str, Any]:
    """Rend le prix et la taille admissibles + `admissible` (False si la taille tombe à 0 après arrondi)."""
    pa = arrondir_tick(prix, tick)
    ta = taille_admissible(taille, lot_size=lot_size, min_lot=min_lot)
    ok = isinstance(ta, (int, float)) and ta > 0 and isinstance(pa, (int, float))
    return {"prix_admissible": pa, "taille_admissible": ta, "admissible": bool(ok),
            "perte_arrondi": (round(float(taille) - ta, 12) if isinstance(ta, (int, float)) else UNMEASURABLE)}


__all__ = ["arrondir_tick", "taille_admissible", "preflight_tick_lot", "UNMEASURABLE"]
