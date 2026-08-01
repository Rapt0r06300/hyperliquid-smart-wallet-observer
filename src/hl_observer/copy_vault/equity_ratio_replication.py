"""[COPY-VAULT #51] EQUITY-RATIO REPLICATION : taille paper = leader_fill × (notre_equity / leader_equity), avant
plafonds d'exécution. On ne copie pas la taille brute du leader (il a peut-être 100× notre capital) : on la met à
l'échelle de notre equity. leader_equity ≤ 0 ou inconnue → UNMEASURABLE (jamais de division implicite ni 1:1).
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def taille_paper(leader_fill: Any, *, notre_equity: Any, leader_equity: Any) -> dict[str, Any]:
    """Met la taille du leader à l'échelle de notre equity. Entrées invalides → UNMEASURABLE + refus."""
    if not all(isinstance(x, (int, float)) for x in (leader_fill, notre_equity, leader_equity)):
        return {"taille": UNMEASURABLE, "refuse": True, "raison": "ENTREE_INVALIDE"}
    if float(leader_equity) <= 0 or float(notre_equity) < 0:
        return {"taille": UNMEASURABLE, "refuse": True, "raison": "EQUITY_LEADER_NON_POSITIVE"}
    ratio = float(notre_equity) / float(leader_equity)
    return {"taille": round(float(leader_fill) * ratio, 12), "ratio_equity": round(ratio, 8), "refuse": False}


__all__ = ["taille_paper", "UNMEASURABLE"]
