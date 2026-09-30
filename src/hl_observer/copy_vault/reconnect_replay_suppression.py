"""[COPY-VAULT #61] RECONNECT REPLAY SUPPRESSION : après une reconnexion WebSocket, la source rediffuse souvent
les derniers événements. Ces événements REJOUÉS ne doivent créer AUCUN nouveau PaperIntent : ils ont déjà été
traités. On supprime tout événement dont le seq est ≤ au dernier curseur traité. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def doit_creer_intent(seq: Any, *, dernier_traite: Any) -> dict[str, Any]:
    """Un intent n'est créé que pour un événement RÉELLEMENT nouveau (seq > dernier traité). Un rejeu (seq ≤
    dernier) est supprimé. Seq/curseur invalide → suppression (prudence : ne pas dédoubler une position)."""
    if not isinstance(seq, (int, float)) or not isinstance(dernier_traite, (int, float)):
        return {"creer": False, "raison": "SEQ_OU_CURSEUR_INVALIDE"}
    nouveau = int(seq) > int(dernier_traite)
    return {"creer": bool(nouveau), "raison": ("NOUVEL_EVENEMENT" if nouveau else "REJEU_SUPPRIME")}


__all__ = ["doit_creer_intent"]
