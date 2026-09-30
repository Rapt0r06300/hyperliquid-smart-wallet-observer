"""[EXEC pépite 222] FILLED QUANTITY LOT INVARIANT : même un partial fill SIMULÉ doit respecter le QUANTUM de
quantité de l'instrument (lot size). Un fill de 0,37 lot sur un instrument à lot 0,1 est physiquement impossible ;
un simulateur qui l'autorise fabrique des quantités inexécutables. On vérifie que toute quantité remplie est un
multiple du lot. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any

_TOL = 1e-9


def respecte_lot(quantite: Any, *, lot_size: float) -> dict[str, Any]:
    """Vrai si `quantite` est un multiple entier de lot_size (à tolérance près). Données invalides → refus."""
    if not isinstance(quantite, (int, float)) or not (isinstance(lot_size, (int, float)) and lot_size > 0):
        return {"valide": False, "raison": "ENTREE_INVALIDE"}
    ratio = float(quantite) / float(lot_size)
    reste = abs(ratio - round(ratio))
    ok = reste <= _TOL
    return {"valide": bool(ok), "quantite": float(quantite), "lot_size": float(lot_size),
            "raison": ("OK" if ok else "QUANTITE_NON_MULTIPLE_DU_LOT")}


def arrondir_au_lot(quantite: Any, *, lot_size: float) -> Any:
    """Plus grand multiple de lot_size ≤ quantite (arrondi vers le bas, jamais fabriquer une quantité supérieure)."""
    if not isinstance(quantite, (int, float)) or not (isinstance(lot_size, (int, float)) and lot_size > 0):
        return "UNMEASURABLE"
    return round(math.floor(float(quantite) / lot_size) * lot_size, 12)


__all__ = ["respecte_lot", "arrondir_au_lot"]
