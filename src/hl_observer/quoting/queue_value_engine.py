"""[CROSS-VENUE lot2 #85] QUEUE-VALUE ENGINE (AMEND / CANCEL_REPLACE / HOLD) : avant tout repricing, estimer la
VALEUR ATTENDUE de la position actuelle dans la file (une bonne place en queue vaut de l'argent) CONTRE le bénéfice
du nouveau prix. On décide alors : AMEND (modifier en gardant la queue si la venue le permet), CANCEL_REPLACE
(reposter, queue perdue) ou HOLD (ne rien faire). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

AMEND = "AMEND"
CANCEL_REPLACE = "CANCEL_REPLACE"
HOLD = "HOLD"
UNMEASURABLE = "UNMEASURABLE"


def decider(*, valeur_queue: Any, benefice_nouveau_prix: Any, cout_cancel: float = 0.0,
            venue_supporte_amend: bool = False) -> dict[str, Any]:
    """Compare le bénéfice du nouveau prix à la valeur de la queue (+ coût de cancel). Valeurs invalides →
    UNMEASURABLE (on ne reprice pas à l'aveugle). Si la venue supporte l'amend ET que le repricing vaut le coup,
    AMEND (garde la queue) ; sinon CANCEL_REPLACE ; si le repricing ne vaut pas la queue perdue, HOLD."""
    if not all(isinstance(x, (int, float)) for x in (valeur_queue, benefice_nouveau_prix)):
        return {"decision": UNMEASURABLE, "raison": "VALEUR_INVALIDE"}
    gain_net = float(benefice_nouveau_prix) - float(valeur_queue) - float(cout_cancel)
    if gain_net <= 0:
        return {"decision": HOLD, "gain_net": round(gain_net, 8), "raison": "QUEUE_VAUT_PLUS_QUE_LE_REPRIX"}
    if bool(venue_supporte_amend):
        # amend préserve la queue : on compare au seul bénéfice (pas de coût de cancel)
        return {"decision": AMEND, "gain_net": round(gain_net, 8), "raison": "REPRIX_RENTABLE_QUEUE_PRESERVEE"}
    return {"decision": CANCEL_REPLACE, "gain_net": round(gain_net, 8), "raison": "REPRIX_RENTABLE_MALGRE_QUEUE"}


__all__ = ["decider", "AMEND", "CANCEL_REPLACE", "HOLD", "UNMEASURABLE"]
