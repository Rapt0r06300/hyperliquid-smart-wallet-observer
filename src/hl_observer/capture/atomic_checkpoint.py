"""[DATA pépite 277] ATOMIC CHECKPOINT : l'offset WS/archive, le state hash et la position dans le dataset sont
commités ATOMIQUEMENT — tout ou rien. Un checkpoint partiel (offset avancé mais state hash de l'ancien état)
créerait une incohérence indétectable au redémarrage : on rejouerait à partir du mauvais point. Tout composant
manquant → refus du commit, aucun état partiel écrit. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_COMPOSANTS = ("offset", "state_hash", "dataset_position")


def commit(offset: Any, state_hash: Any, dataset_position: Any) -> dict[str, Any]:
    """Les trois composants doivent être présents (non None) pour former un checkpoint valide. Tout manquant →
    commit refusé (rien n'est écrit), avec la liste des composants manquants. Sinon → record atomique unique."""
    valeurs = {"offset": offset, "state_hash": state_hash, "dataset_position": dataset_position}
    manquants = [c for c in _COMPOSANTS if valeurs[c] is None]
    if manquants:
        return {"commit": False, "raison": "COMPOSANT_MANQUANT", "manquants": manquants}
    return {"commit": True, "record": dict(valeurs), "atomique": True}


__all__ = ["commit"]
