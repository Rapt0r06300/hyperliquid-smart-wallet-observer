"""[EXEC pépite 224] MODIFY-AFTER-PARTIAL CORRECTNESS : après qu'un ordre a été rempli à 37 % puis MODIFIÉ (nouvelle
quantité cible), la quantité qui « travaille » ne doit porter que sur le REMAINING correct, pas sur la quantité
initiale. Le bug (corrigé dans Nautilus) : la modification retravaillait la quantité totale, dédoublant la partie
déjà remplie. remaining = max(0, nouvelle_cible − déjà_rempli). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def quantite_travaillante(*, quantite_initiale: Any, deja_rempli: Any, nouvelle_cible: Any) -> dict[str, Any]:
    """Quantité qui travaille après modification = max(0, nouvelle_cible − déjà_rempli). Une nouvelle cible
    inférieure au déjà-rempli → 0 (rien à travailler, l'ordre est sur-rempli vs la nouvelle cible). Données
    invalides → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (quantite_initiale, deja_rempli, nouvelle_cible)):
        return {"remaining": UNMEASURABLE, "raison": "ENTREE_INVALIDE"}
    remaining = max(0.0, float(nouvelle_cible) - float(deja_rempli))
    return {"remaining": round(remaining, 12), "deja_rempli": float(deja_rempli),
            "nouvelle_cible": float(nouvelle_cible),
            "note": "travaille sur le remaining, pas la quantite initiale"}


__all__ = ["quantite_travaillante", "UNMEASURABLE"]
