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


def deduplicate_reconnect_fills(fills: list[dict[str, Any]]) -> dict[str, Any]:
    """Suppress only strict native duplicates; a new tid at the same timestamp survives."""

    if not isinstance(fills, list) or any(not isinstance(fill, dict) for fill in fills):
        return {"status": "UNMEASURABLE", "fills": [], "reason": "FILL_LIST_INVALID", "paper_read_only": True}
    seen: set[tuple[Any, ...]] = set()
    retained: list[dict[str, Any]] = []
    for index, fill in enumerate(fills):
        timestamp = fill.get("ts_ms", fill.get("time"))
        native = tuple(fill.get(name) for name in ("tid", "oid", "hash"))
        if type(timestamp) is not int or timestamp <= 0 or not any(value not in (None, "") for value in native):
            return {"status": "UNMEASURABLE", "fills": [], "reason": "NATIVE_IDENTITY_MISSING", "paper_read_only": True}
        key = (str(fill.get("wallet") or "").lower(), timestamp, *native, str(fill.get("coin") or ""))
        if key in seen:
            continue
        seen.add(key)
        retained.append(dict(fill))
    return {"status": "PROVEN", "fills": retained, "retained_count": len(retained),
            "removed_duplicates": len(fills) - len(retained), "paper_read_only": True}


__all__ = ["doit_creer_intent", "deduplicate_reconnect_fills"]
