"""[DATA lot2 #33] MISSING-UPDATE DETECTOR : un saut de séquence OU une incohérence entre snapshot et delta (le
delta référence une base qui ne correspond pas au snapshot courant) déclenche un RESYNC automatique. On ne continue
jamais à appliquer des deltas sur un carnet dont on sait qu'il a manqué une mise à jour. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

CONTINUER = "CONTINUER"
RESYNC = "RESYNC"


def analyser(*, seq_precedent: Any, seq_courant: Any, base_delta: Any = None,
             seq_snapshot: Any = None, pas: int = 1) -> dict[str, Any]:
    """RESYNC si saut de séquence OU si le delta référence une base ≠ du snapshot courant. Sinon CONTINUER.
    Données de séquence invalides → RESYNC (prudence)."""
    if not all(isinstance(x, (int, float)) for x in (seq_precedent, seq_courant)):
        return {"action": RESYNC, "raison": "SEQUENCE_INVALIDE"}
    if int(seq_courant) != int(seq_precedent) + int(pas):
        return {"action": RESYNC, "raison": "SAUT_DE_SEQUENCE"}
    if base_delta is not None and seq_snapshot is not None and int(base_delta) != int(seq_snapshot):
        return {"action": RESYNC, "raison": "DELTA_INCOHERENT_AVEC_SNAPSHOT"}
    return {"action": CONTINUER, "raison": "SEQUENCE_COHERENTE"}


__all__ = ["analyser", "CONTINUER", "RESYNC"]
