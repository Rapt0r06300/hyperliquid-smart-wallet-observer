"""AUD-140 — classement des actions par GAIN ATTENDU.

Gain attendu d'une action = valeur * proba_succes - cout. On classe les actions du gain attendu le
plus FORT au plus faible : agir d'abord la ou le retour espere est le plus grand. Read-only.
"""
from __future__ import annotations

from typing import Sequence


def gain_attendu(action: dict) -> float:
    return (float(action.get("valeur", 0.0)) * float(action.get("proba", 0.0))
            - float(action.get("cout", 0.0)))


def classer_actions(actions: Sequence[dict]) -> list:
    """Actions triees par gain attendu DECROISSANT, champ 'gain_attendu' ajoute."""
    enrichies = [{**a, "gain_attendu": round(gain_attendu(a), 8)} for a in actions]
    return sorted(enrichies, key=lambda a: a["gain_attendu"], reverse=True)


__all__ = ["gain_attendu", "classer_actions"]
