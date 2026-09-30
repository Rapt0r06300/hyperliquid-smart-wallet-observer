"""[CROSS-VENUE lot2 #79] HARD PRICE CEILING/FLOOR : un plafond et un plancher de prix DURS protègent les algos
maker contre une référence ABERRANTE (spike de données, mid corrompu). Même si tout le reste dit « quote ici »,
un prix hors des bornes dures est refusé. Bornes manquantes ou prix invalide → refusé (fail-closed). Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any


def admissible(prix: Any, *, plancher: Any, plafond: Any) -> dict[str, Any]:
    """Prix admissible seulement si plancher ≤ prix ≤ plafond. Toute borne manquante ou prix invalide → refus."""
    if not all(isinstance(x, (int, float)) for x in (prix, plancher, plafond)):
        return {"admissible": False, "raison": "PRIX_OU_BORNE_INVALIDE"}
    if float(plancher) > float(plafond):
        return {"admissible": False, "raison": "BORNES_INCOHERENTES"}
    ok = float(plancher) <= float(prix) <= float(plafond)
    return {"admissible": bool(ok), "prix": float(prix), "plancher": float(plancher), "plafond": float(plafond),
            "raison": ("OK" if ok else "PRIX_HORS_BORNES_DURES")}


__all__ = ["admissible"]
