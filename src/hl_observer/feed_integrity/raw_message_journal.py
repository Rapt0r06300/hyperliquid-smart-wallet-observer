"""[DATA lot2 #66] RAW-MESSAGE JOURNAL AVANT PARSING : journaliser les messages BRUTS (tels que reçus) AVANT tout
parsing, pour pouvoir rejouer EXACTEMENT les bytes/messages reçus. Si le parsing a un bug, seul le journal brut
permet de comprendre ce qui est réellement arrivé et de rejouer à l'identique. Ordre de réception préservé.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class JournalBrut:
    """Journal append-only des messages bruts, dans l'ordre de réception, AVANT parsing."""

    def __init__(self) -> None:
        self._messages: list[dict[str, Any]] = []

    def journaliser(self, brut: Any, *, receipt_ts_ms: Any = None) -> dict[str, Any]:
        """Enregistre le message brut inchangé + son horodatage de réception. Aucune interprétation ici."""
        idx = len(self._messages)
        self._messages.append({"idx": idx, "brut": brut, "receipt_ts_ms": receipt_ts_ms})
        return {"idx": idx, "n": len(self._messages)}

    def rejouer(self) -> list[dict[str, Any]]:
        """Renvoie les messages bruts dans l'ordre exact de réception (copie, journal non mutable)."""
        return [dict(m) for m in self._messages]

    def taille(self) -> int:
        return len(self._messages)


__all__ = ["JournalBrut"]
