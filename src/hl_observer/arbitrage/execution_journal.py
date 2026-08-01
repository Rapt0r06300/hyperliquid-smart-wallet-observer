"""[ARB #48] EXECUTION JOURNAL : chaque épisode d'arbitrage progresse dans une machine à états dont CHAQUE
transition est enregistrée de façon IMMUABLE (append-only) : DETECTED → VALIDATED → RESERVED → SUBMITTED_A →
SUBMITTED_B → PARTIAL → HEDGED → CLOSED. Une transition interdite est refusée (l'état ne saute pas d'étape) et
l'historique ne peut pas être réécrit. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

DETECTED = "DETECTED"
VALIDATED = "VALIDATED"
RESERVED = "RESERVED"
SUBMITTED_A = "SUBMITTED_A"
SUBMITTED_B = "SUBMITTED_B"
PARTIAL = "PARTIAL"
HEDGED = "HEDGED"
CLOSED = "CLOSED"
ABORTED = "ABORTED"

# graphe des transitions autorisées (avant). ABORTED est atteignable depuis tout état actif.
_SUIVANTS = {
    DETECTED: {VALIDATED, ABORTED},
    VALIDATED: {RESERVED, ABORTED},
    RESERVED: {SUBMITTED_A, ABORTED},
    SUBMITTED_A: {SUBMITTED_B, PARTIAL, ABORTED},
    SUBMITTED_B: {PARTIAL, HEDGED, ABORTED},
    PARTIAL: {HEDGED, CLOSED},
    HEDGED: {CLOSED},
    CLOSED: set(),
    ABORTED: set(),
}


class JournalExecution:
    """Journal append-only par épisode. `transition` n'applique QUE les changements autorisés ; l'historique
    est immuable (chaque appel renvoie une copie). Un épisode démarre implicitement à DETECTED."""

    def __init__(self) -> None:
        self._etat: dict[str, str] = {}
        self._histo: dict[str, list[tuple[str, str]]] = {}

    def etat(self, episode_id: str) -> str:
        return self._etat.get(str(episode_id), DETECTED)

    def transition(self, episode_id: str, vers: str, *, note: str = "") -> dict[str, Any]:
        """Applique la transition si elle est autorisée depuis l'état courant ; sinon refuse sans muter."""
        eid = str(episode_id)
        courant = self._etat.get(eid, DETECTED)
        if vers not in _SUIVANTS.get(courant, set()):
            return {"ok": False, "etat": courant, "refuse_vers": vers, "raison": "TRANSITION_INTERDITE"}
        self._etat[eid] = vers
        self._histo.setdefault(eid, [(DETECTED, "")]).append((vers, str(note)))
        return {"ok": True, "etat": vers, "raison": "OK"}

    def historique(self, episode_id: str) -> list[tuple[str, str]]:
        """Copie immuable de l'historique (l'appelant ne peut pas réécrire le journal)."""
        return list(self._histo.get(str(episode_id), [(DETECTED, "")]))


__all__ = ["JournalExecution", "DETECTED", "VALIDATED", "RESERVED", "SUBMITTED_A", "SUBMITTED_B",
           "PARTIAL", "HEDGED", "CLOSED", "ABORTED"]
