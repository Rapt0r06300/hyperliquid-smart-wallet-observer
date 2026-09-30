"""[COPY-VAULT #52] EXPOSURE-RATIO REPLICATION : comparer aussi le POURCENTAGE d'equity que le leader expose sur
un coin, pas seulement la taille de son dernier fill. Cible = (notional_leader / equity_leader) × notre_equity.
Un gros fill isolé peut sur-représenter une petite exposition réelle ; l'exposition en % est plus fidèle.
equity_leader ≤ 0 / inconnue → UNMEASURABLE. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def exposition_cible(*, notional_leader: Any, equity_leader: Any, notre_equity: Any) -> dict[str, Any]:
    """Notional cible paper = ratio d'exposition du leader × notre equity. Entrées invalides → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (notional_leader, equity_leader, notre_equity)):
        return {"notional_cible": UNMEASURABLE, "refuse": True, "raison": "ENTREE_INVALIDE"}
    if float(equity_leader) <= 0:
        return {"notional_cible": UNMEASURABLE, "refuse": True, "raison": "EQUITY_LEADER_NON_POSITIVE"}
    part = float(notional_leader) / float(equity_leader)
    return {"notional_cible": round(part * float(notre_equity), 8), "part_equity_leader": round(part, 8),
            "refuse": False}


__all__ = ["exposition_cible", "UNMEASURABLE"]
