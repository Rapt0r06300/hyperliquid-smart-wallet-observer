"""[ALL #89] EXPLICIT EXECUTOR LIFECYCLE : un executor a un cycle de vie EXPLICITE — au minimum RUNNING /
SHUTTING_DOWN / COMPLETED / FAILED / POSITION_HOLD. Les transitions sont contrôlées : on ne saute pas de RUNNING à
COMPLETED sans passer par l'arrêt, et POSITION_HOLD (exposition résiduelle) est un état terminal explicite, pas un
oubli. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

RUNNING = "RUNNING"
SHUTTING_DOWN = "SHUTTING_DOWN"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
POSITION_HOLD = "POSITION_HOLD"

_SUIVANTS = {
    RUNNING: {SHUTTING_DOWN, FAILED},
    SHUTTING_DOWN: {COMPLETED, POSITION_HOLD, FAILED},
    POSITION_HOLD: {SHUTTING_DOWN, COMPLETED, FAILED},   # on peut re-tenter de déboucler un hold
    COMPLETED: set(),
    FAILED: set(),
}


class CycleVieExecutor:
    """Machine à états du cycle de vie d'un executor. Démarre à RUNNING ; transitions interdites refusées."""

    def __init__(self) -> None:
        self.etat = RUNNING

    def transition(self, vers: str) -> dict[str, Any]:
        if vers not in _SUIVANTS.get(self.etat, set()):
            return {"ok": False, "etat": self.etat, "raison": "TRANSITION_INTERDITE"}
        self.etat = vers
        return {"ok": True, "etat": vers}

    def terminal(self) -> bool:
        return self.etat in (COMPLETED, FAILED)


__all__ = ["CycleVieExecutor", "RUNNING", "SHUTTING_DOWN", "COMPLETED", "FAILED", "POSITION_HOLD"]
