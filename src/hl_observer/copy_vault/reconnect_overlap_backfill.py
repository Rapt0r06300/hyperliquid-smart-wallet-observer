"""[COPY-VAULT lot2 #37] RECONNECT OVERLAP BACKFILL : après une reconnexion, on demande VOLONTAIREMENT une fenêtre
de backfill qui commence AVANT le dernier checkpoint (chevauchement), pour détecter les événements manqués juste
avant la coupure. Reprendre pile au checkpoint laisserait un trou si un événement est arrivé pendant la bascule.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def fenetre_backfill(dernier_checkpoint_ms: Any, *, overlap_ms: float = 5000.0) -> dict[str, Any]:
    """Renvoie le début de la fenêtre de backfill = checkpoint − overlap (jamais après le checkpoint).
    Checkpoint invalide → UNMEASURABLE."""
    if not isinstance(dernier_checkpoint_ms, (int, float)):
        return {"debut_ms": UNMEASURABLE, "raison": "CHECKPOINT_INVALIDE"}
    debut = float(dernier_checkpoint_ms) - abs(float(overlap_ms))
    return {"debut_ms": round(debut, 3), "checkpoint_ms": float(dernier_checkpoint_ms),
            "overlap_ms": abs(float(overlap_ms)), "raison": "FENETRE_AVEC_CHEVAUCHEMENT"}


__all__ = ["fenetre_backfill", "UNMEASURABLE"]
