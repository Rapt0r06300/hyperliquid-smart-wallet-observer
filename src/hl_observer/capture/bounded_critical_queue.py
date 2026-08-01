"""[DATA pépite 272] BOUNDED CRITICAL QUEUE : une file critique a une capacité FINIE et expose son taux
d'occupation. En cas de rafale, la saturation se traduit par un REJET explicite mesurable — jamais par une
accumulation mémoire infinie qui finit en OOM (et en capture corrompue). Le rejet est compté : on sait qu'on a
perdu, on ne le cache pas. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections import deque
from typing import Any


class FileBornee:
    """File FIFO bornée. enfiler() rejette proprement quand pleine (compteur de rejets), au lieu de croître
    sans limite. Expose occupation et taux d'occupation pour la métrique de santé de capture."""

    def __init__(self, capacite: int) -> None:
        if not isinstance(capacite, int) or capacite <= 0:
            raise ValueError("capacite doit etre un entier > 0")
        self._capacite = capacite
        self._q: deque = deque()
        self._rejets = 0

    def enfiler(self, item: Any) -> dict[str, Any]:
        if len(self._q) >= self._capacite:
            self._rejets += 1
            return {"ok": False, "rejete": True, "occupation": len(self._q), "rejets_total": self._rejets}
        self._q.append(item)
        return {"ok": True, "rejete": False, "occupation": len(self._q)}

    def defiler(self) -> dict[str, Any]:
        if not self._q:
            return {"ok": False, "raison": "FILE_VIDE"}
        return {"ok": True, "item": self._q.popleft(), "occupation": len(self._q)}

    def occupation(self) -> int:
        return len(self._q)

    def taux_occupation(self) -> float:
        return round(len(self._q) / self._capacite, 6)

    def rejets(self) -> int:
        return self._rejets


__all__ = ["FileBornee"]
