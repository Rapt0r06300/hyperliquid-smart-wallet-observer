"""[DATA pépite 276] WRITE-AHEAD RAW JOURNAL : l'événement BRUT est écrit durablement AVANT toute modification
de certaines projections critiques (positions, ledger, état de marché dérivé). Ainsi, après un crash, on peut
rejouer le journal et reconstruire les projections : la source de vérité est le brut journalisé, pas un état
dérivé qui aurait pu être modifié à moitié. Projection avant journalisation = refusée. Pur, 0 réseau, 0 ordre
réel.
"""
from __future__ import annotations

from typing import Any


class JournalWAL:
    """Impose l'ordre write-ahead : journaliser(event_id) doit précéder projection_autorisee(event_id). On ne
    peut pas appliquer une projection critique sur un événement dont le brut n'a pas encore été rendu durable."""

    def __init__(self) -> None:
        self._journalises: set = set()
        self._ordre: list[Any] = []

    def journaliser(self, event_id: Any, brut: Any = None) -> dict[str, Any]:
        """Rend le brut durable (ici : marque l'event_id comme journalisé, dans l'ordre)."""
        if event_id in self._journalises:
            return {"ok": True, "deja": True, "event_id": event_id}
        self._journalises.add(event_id)
        self._ordre.append(event_id)
        return {"ok": True, "deja": False, "event_id": event_id, "rang": len(self._ordre)}

    def projection_autorisee(self, event_id: Any) -> dict[str, Any]:
        """Autorisée seulement si le brut a été journalisé auparavant (write-ahead respecté)."""
        ok = event_id in self._journalises
        return {"autorisee": ok, "raison": None if ok else "BRUT_NON_JOURNALISE"}

    def rejouer(self) -> list[Any]:
        """Ordre de rejeu = ordre de journalisation (reconstruction des projections après crash)."""
        return list(self._ordre)


__all__ = ["JournalWAL"]
