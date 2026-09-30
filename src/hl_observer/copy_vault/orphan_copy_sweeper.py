"""[COPY-VAULT #77] ORPHAN-COPY SWEEPER : si le vault leader est désormais FLAT mais que HyperSmart détient encore
une exposition paper (à cause d'un fill manqué à la fermeture), il faut le détecter IMMÉDIATEMENT et programmer le
débouclage. Une exposition paper qui ne correspond plus à aucune position leader est orpheline. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

_TOL = 1e-9


def detecter(position_vault: Any, notre_position_paper: Any) -> dict[str, Any]:
    """Orphelin si le vault est ~flat mais notre position paper ≠ 0. Retourne la quantité à déboucler et son sens.
    Position inconnue → orphelin présumé (prudence : on préfère vérifier/déboucler que garder une expo fantôme)."""
    if not isinstance(notre_position_paper, (int, float)):
        return {"orphelin": True, "raison": "POSITION_PAPER_INCONNUE"}
    if not isinstance(position_vault, (int, float)):
        return {"orphelin": True, "a_deboucler": round(float(notre_position_paper), 12),
                "raison": "POSITION_VAULT_INCONNUE"}
    vault_flat = abs(float(position_vault)) <= _TOL
    on_expose = abs(float(notre_position_paper)) > _TOL
    if vault_flat and on_expose:
        p = float(notre_position_paper)
        return {"orphelin": True, "a_deboucler": round(p, 12),
                "sens_debouclage": ("VENTE" if p > 0 else "ACHAT"), "raison": "VAULT_FLAT_MAIS_EXPO_PAPER"}
    return {"orphelin": False, "raison": "COHERENT"}


__all__ = ["detecter"]
