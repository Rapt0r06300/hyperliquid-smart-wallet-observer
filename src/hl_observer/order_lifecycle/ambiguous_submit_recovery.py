"""[ARB lot2 #13] RÉCUPÉRATION DE SUBMIT AMBIGU : si le transport TIMEOUT après l'envoi d'un ordre, il ne faut PAS
conclure immédiatement REJECTED — l'ordre est peut-être passé. On dérive/conserve l'identifiant client attendu et on
place l'ordre en état UNKNOWN pour réconciliation ultérieure (philosophie Nautilus pour Polymarket). Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any

REJECTED = "REJECTED"
UNKNOWN = "UNKNOWN"
ACKED = "ACKED"


def traiter_reponse_submit(*, transport_timeout: bool, ack_recu: bool,
                           client_order_id: Any) -> dict[str, Any]:
    """Timeout après envoi → UNKNOWN + conserver le client_order_id pour réconcilier (jamais REJECTED d'office).
    Un ACK reçu → ACKED. Ni timeout ni ack sans id → REJECTED seulement si explicitement rien n'est parti."""
    if bool(ack_recu):
        return {"statut": ACKED, "client_order_id": client_order_id, "raison": "ACK_RECU"}
    if bool(transport_timeout):
        return {"statut": UNKNOWN, "client_order_id": client_order_id, "a_reconcilier": True,
                "raison": "TIMEOUT_ORDRE_PEUT_ETRE_PASSE"}
    return {"statut": REJECTED, "client_order_id": client_order_id, "raison": "REJET_EXPLICITE"}


__all__ = ["traiter_reponse_submit", "REJECTED", "UNKNOWN", "ACKED"]
