"""[EXEC pépite 204] CANCEL-VS-FILL RACE RESOLVER : si un fill et un cancel arrivent presque ensemble, résoudre
CAUSALEMENT l'ordre exact (par numéro de séquence / horodatage venue), au lieu de choisir arbitrairement le DERNIER
message traité (qui dépend de l'ordre d'arrivée réseau, pas de la causalité). Un fill de séquence antérieure au cancel
s'est produit AVANT : la partie remplie compte, seul le reliquat est annulé. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

FILL_PUIS_CANCEL = "FILL_PUIS_CANCEL"     # le fill a eu lieu, le reliquat est annulé
CANCEL_PUIS_FILL = "CANCEL_PUIS_FILL"     # annulé avant : le fill (tardif) ne devrait pas exister -> à réconcilier
INDETERMINE = "INDETERMINE"


def resoudre(*, fill_seq: Any, cancel_seq: Any) -> dict[str, Any]:
    """Ordonne fill et cancel par leur SÉQUENCE causale, pas par ordre d'arrivée. fill_seq < cancel_seq →
    FILL_PUIS_CANCEL (fill valide, reliquat annulé). fill_seq > cancel_seq → CANCEL_PUIS_FILL (fill tardif suspect,
    à réconcilier). Séquences manquantes/égales → INDETERMINE (ne pas trancher arbitrairement)."""
    if not all(isinstance(x, (int, float)) for x in (fill_seq, cancel_seq)):
        return {"resolution": INDETERMINE, "raison": "SEQUENCE_MANQUANTE"}
    if int(fill_seq) < int(cancel_seq):
        return {"resolution": FILL_PUIS_CANCEL, "raison": "FILL_ANTERIEUR_AU_CANCEL"}
    if int(fill_seq) > int(cancel_seq):
        return {"resolution": CANCEL_PUIS_FILL, "a_reconcilier": True, "raison": "FILL_POSTERIEUR_AU_CANCEL"}
    return {"resolution": INDETERMINE, "raison": "SEQUENCES_EGALES"}


__all__ = ["resoudre", "FILL_PUIS_CANCEL", "CANCEL_PUIS_FILL", "INDETERMINE"]
