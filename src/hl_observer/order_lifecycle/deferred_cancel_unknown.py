"""[ARB lot2 #14] CANCEL DIFFÉRÉ D'UN ORDRE AU STATUT INCONNU : on DIFFÈRE l'annulation d'un ordre au statut UNKNOWN
jusqu'à ce que son identifiant côté venue soit réconcilié. Annuler un ordre dont on ignore l'id venue peut n'annuler
RIEN (l'ordre vit) ou pire viser le mauvais ordre. On attend l'id avant d'agir. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

ANNULER = "ANNULER"
DIFFERER = "DIFFERER"


def decision_cancel(*, statut: Any, venue_order_id: Any) -> dict[str, Any]:
    """Si le statut est UNKNOWN et que l'id venue manque → DIFFERER (attendre la réconciliation). Sinon, avec un id
    venue connu, l'annulation peut cibler proprement l'ordre → ANNULER."""
    s = str(statut).upper()
    id_connu = venue_order_id is not None and str(venue_order_id) != ""
    if s == "UNKNOWN" and not id_connu:
        return {"action": DIFFERER, "raison": "STATUT_INCONNU_SANS_ID_VENUE"}
    if not id_connu:
        return {"action": DIFFERER, "raison": "ID_VENUE_MANQUANT"}
    return {"action": ANNULER, "raison": "ID_VENUE_CONNU"}


__all__ = ["decision_cancel", "ANNULER", "DIFFERER"]
