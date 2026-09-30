"""[ARB lot2 #2] AMEND IN-PLACE (préserve la queue) : lorsqu'une venue le permet, MODIFIER un ordre sans
cancel/recreate afin de PRÉSERVER sa priorité dans la file (queue position). Un cancel/recreate renvoie l'ordre en
fin de file et détruit la priorité acquise. On modélise si l'amend préserve ou non la queue. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

AMEND = "AMEND"
CANCEL_RECREATE = "CANCEL_RECREATE"


def strategie_modification(*, venue_supporte_amend: bool, preserve_queue: bool) -> dict[str, Any]:
    """AMEND (queue préservée) seulement si la venue le supporte ET si le changement est compatible queue ;
    sinon CANCEL_RECREATE (queue perdue). `preserve_queue` vient de l'analyse du type de changement (voir #3)."""
    if bool(venue_supporte_amend) and bool(preserve_queue):
        return {"strategie": AMEND, "queue_preservee": True, "raison": "AMEND_IN_PLACE"}
    raison = "VENUE_SANS_AMEND" if not venue_supporte_amend else "CHANGEMENT_DETRUIT_QUEUE"
    return {"strategie": CANCEL_RECREATE, "queue_preservee": False, "raison": raison}


__all__ = ["strategie_modification", "AMEND", "CANCEL_RECREATE"]
