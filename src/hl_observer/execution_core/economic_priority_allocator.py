"""[ALL pépite 248] ECONOMIC PRIORITY ALLOCATOR : ordonnancer les intentions par PRIORITÉ ÉCONOMIQUE —
emergency hedge > close/reduce > arb hedge > profitable entry > research intent. Sous contrainte (budget, quota,
capacité), ce qui protège le capital passe avant ce qui l'explore. Une intention de type inconnu est traitée en
dernier (jamais prioritaire par défaut). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_PRIORITE = {"EMERGENCY_HEDGE": 0, "CLOSE": 1, "REDUCE": 1, "ARB_HEDGE": 2,
             "PROFITABLE_ENTRY": 3, "RESEARCH": 4}
_INCONNU = 99


def rang(type_intent: Any) -> int:
    return _PRIORITE.get(str(type_intent).upper(), _INCONNU)


def ordonnancer(intentions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Trie les intentions par priorité économique (stable à priorité égale via l'ordre d'arrivée)."""
    indexees = list(enumerate(intentions))
    ordonnees = [it for _, it in sorted(indexees, key=lambda p: (rang(p[1].get("type")), p[0]))]
    return {"ordonnees": ordonnees, "n": len(ordonnees)}


__all__ = ["rang", "ordonnancer"]
