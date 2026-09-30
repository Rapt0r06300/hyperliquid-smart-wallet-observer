"""[ALL lot2 #26] QoS DES REQUÊTES API : les requêtes sont servies par PRIORITÉ économique, pas dans l'ordre
d'arrivée : emergency_close > hedge > cancel > reconcile > data_refresh > research. Sous contrainte de quota, ce qui
protège le capital passe avant ce qui l'explore. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

_PRIORITE = {"EMERGENCY_CLOSE": 0, "HEDGE": 1, "CANCEL": 2, "RECONCILE": 3, "DATA_REFRESH": 4, "RESEARCH": 5}
_INCONNU = 99


def rang(categorie: Any) -> int:
    """Rang de priorité (plus petit = plus prioritaire). Catégorie inconnue → dernière (jamais prioritaire)."""
    return _PRIORITE.get(str(categorie).upper(), _INCONNU)


class FileQoS:
    """File de requêtes servie par priorité économique (stable à priorité égale)."""

    def __init__(self) -> None:
        self._items: list[tuple[int, int, Any]] = []
        self._seq = 0

    def ajouter(self, requete: Any, *, categorie: Any) -> None:
        self._items.append((rang(categorie), self._seq, requete))
        self._seq += 1

    def ordonner(self) -> list[Any]:
        return [r for _, _, r in sorted(self._items, key=lambda x: (x[0], x[1]))]

    def suivant(self) -> Any:
        """Retire et renvoie la requête la plus prioritaire, ou None si vide."""
        if not self._items:
            return None
        self._items.sort(key=lambda x: (x[0], x[1]))
        return self._items.pop(0)[2]


__all__ = ["FileQoS", "rang"]
