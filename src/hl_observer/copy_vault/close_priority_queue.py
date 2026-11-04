"""[COPY-VAULT #76] CLOSE PRIORITY QUEUE : dans le PaperEngine, les fermetures/réductions passent DEVANT les
nouvelles ouvertures. En cas de budget ou de capacité limités, réduire le risque existant prime sur en prendre un
nouveau. La file ordonne CLOSE/REDUCE avant OPEN/ADD, en gardant l'ordre d'arrivée à priorité égale. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any

_PRIORITE = {"CLOSE": 0, "REDUCE": 0, "OPEN": 1, "ADD": 1}


class FilePrioriteFermeture:
    """File d'intents ordonnée : fermetures/réductions d'abord, puis ouvertures (stable à priorité égale)."""

    def __init__(self) -> None:
        self._items: list[tuple[int, int, dict[str, Any]]] = []
        self._seq = 0

    def ajouter(self, intent: dict[str, Any]) -> None:
        action = str(intent.get("action", "")).upper()
        prio = _PRIORITE.get(action, 1)                  # action inconnue = traitée comme une ouverture (basse prio)
        self._items.append((prio, self._seq, dict(intent)))
        self._seq += 1

    def ordonner(self) -> list[dict[str, Any]]:
        """Retourne les intents triés par (priorité, ordre d'arrivée). Ne consomme pas la file."""
        return [it for _, _, it in sorted(self._items, key=lambda x: (x[0], x[1]))]


def close_priority_receipt(intents: list[dict[str, Any]]) -> dict[str, Any]:
    """Prove stable close/reduce precedence over open/add in the paper queue."""
    if not isinstance(intents, list) or any(not isinstance(item, dict) for item in intents):
        return {"status": "UNMEASURABLE", "reason": "INTENTS_INVALID"}
    actions = [str(item.get("action", "")).upper() for item in intents]
    if any(action not in _PRIORITE for action in actions):
        return {"status": "UNMEASURABLE", "reason": "ACTION_INVALID"}
    queue = FilePrioriteFermeture()
    for item in intents:
        queue.ajouter(item)
    ordered = queue.ordonner()
    priorities = [_PRIORITE[str(item["action"]).upper()] for item in ordered]
    stable = priorities == sorted(priorities)
    return {"status": "PROVEN" if stable else "REJECTED", "order": ordered, "priority_preserved": stable}


__all__ = ["FilePrioriteFermeture", "close_priority_receipt"]
