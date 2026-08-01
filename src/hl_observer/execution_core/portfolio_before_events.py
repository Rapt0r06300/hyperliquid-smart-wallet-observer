"""[ACCOUNTING lot2 #93] PORTFOLIO MIS À JOUR AVANT DIFFUSION DES EVENTS D'EXÉCUTION : le portfolio (positions,
equity) doit être mis à jour AVANT de diffuser les événements d'exécution aux stratégies, afin qu'aucune décision
SUIVANTE ne voie une ANCIENNE equity. Diffuser d'abord, mettre à jour ensuite, c'est laisser une stratégie décider
sur un état périmé (Nautilus a corrigé cet ordre d'événements). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

MAJ_PORTFOLIO = "MAJ_PORTFOLIO"
DIFFUSER_EVENT = "DIFFUSER_EVENT"


def ordre_traitement() -> list[str]:
    """L'ordre CANONIQUE : mettre à jour le portfolio, PUIS diffuser l'event aux stratégies."""
    return [MAJ_PORTFOLIO, DIFFUSER_EVENT]


def valider_sequence(sequence: list[Any]) -> dict[str, Any]:
    """Vérifie qu'une séquence traite bien la MAJ portfolio AVANT la diffusion. Diffusion avant MAJ → violation
    (une stratégie verrait l'ancienne equity). MAJ absente → violation."""
    idx_maj = sequence.index(MAJ_PORTFOLIO) if MAJ_PORTFOLIO in sequence else None
    idx_diff = sequence.index(DIFFUSER_EVENT) if DIFFUSER_EVENT in sequence else None
    if idx_maj is None:
        return {"ok": False, "raison": "MAJ_PORTFOLIO_ABSENTE"}
    if idx_diff is not None and idx_diff < idx_maj:
        return {"ok": False, "raison": "DIFFUSION_AVANT_MAJ_EQUITY_PERIMEE"}
    return {"ok": True, "raison": "MAJ_AVANT_DIFFUSION"}


__all__ = ["ordre_traitement", "valider_sequence", "MAJ_PORTFOLIO", "DIFFUSER_EVENT"]
